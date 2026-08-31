#!/usr/bin/env python3
"""Monitor Liberty University athletics schedule pages and send ntfy alerts on changes."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, date
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup

STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))
TIMEOUT = 30
USER_AGENT = "LibertyAthleticsScheduleMonitor/1.0 (+personal schedule-change notifier)"

# Liberty's NCAA menu has 18 sponsored teams; Cross Country and Track & Field each
# share one schedule page for the men's and women's programs, so 16 NCAA URLs cover all 18.
SOURCES = [
    ("Baseball", "https://libertyflames.com/sports/baseball/schedule/text"),
    ("Men's Basketball", "https://libertyflames.com/sports/mens-basketball/schedule/text"),
    ("Cross Country (M/W)", "https://libertyflames.com/sports/cross-country/schedule/text"),
    ("Football", "https://libertyflames.com/sports/football/schedule/text"),
    ("Men's Golf", "https://libertyflames.com/sports/mens-golf/schedule/text"),
    ("Men's Soccer", "https://libertyflames.com/sports/mens-soccer/schedule/text"),
    ("Men's Tennis", "https://libertyflames.com/sports/mens-tennis/schedule/text"),
    ("Track & Field (M/W)", "https://libertyflames.com/sports/track-and-field/schedule/text"),
    ("Women's Basketball", "https://libertyflames.com/sports/womens-basketball/schedule/text"),
    ("Field Hockey", "https://libertyflames.com/sports/field-hockey/schedule/text"),
    ("Women's Lacrosse", "https://libertyflames.com/sports/womens-lacrosse/schedule/text"),
    ("Women's Soccer", "https://libertyflames.com/sports/womens-soccer/schedule/text"),
    ("Softball", "https://libertyflames.com/sports/softball/schedule/text"),
    ("Women's Swimming & Diving", "https://libertyflames.com/sports/womens-swimming-and-diving/schedule/text"),
    ("Women's Tennis", "https://libertyflames.com/sports/womens-tennis/schedule/text"),
    ("Women's Volleyball", "https://libertyflames.com/sports/womens-volleyball/schedule/text"),
    # Club sports requested by the user. "Hockey" is interpreted broadly as both D1 teams.
    ("Men's D1 Hockey (Club)", "https://libertyclubsports.com/sports/mens-ice-hockey/schedule/text"),
    ("Women's D1 Hockey (Club)", "https://libertyclubsports.com/sports/womens-ice-hockey/schedule/text"),
    ("Men's Lacrosse (Club)", "https://libertyclubsports.com/sports/mens-lacrosse/schedule/text"),
]

STATUS_PATTERNS = [
    ("CANCELED", re.compile(r"\b(cancelled|canceled)\b", re.I)),
    ("POSTPONED", re.compile(r"\bpostponed\b", re.I)),
    ("DELAYED", re.compile(r"\b(delay|delayed)\b", re.I)),
    ("SUSPENDED", re.compile(r"\bsuspended\b", re.I)),
    ("RESCHEDULED", re.compile(r"\brescheduled\b", re.I)),
]

NON_COMPETITION = {
    "tryouts",
    "information meeting",
    "team meeting",
    "interest meeting",
}

MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1
)}


@dataclass
class Event:
    date: str
    time: str
    at: str
    opponent: str
    location: str
    tournament: str
    result: str
    status: str

    @classmethod
    def from_dict(cls, value: dict) -> "Event":
        return cls(**{k: value.get(k, "") for k in cls.__dataclass_fields__})


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def normalized_opponent(text: str) -> str:
    text = clean(text).lower()
    text = re.sub(r"\bno\.?\s*\d+\b", "", text)  # ranking changes are not opponent changes
    text = re.sub(r"\(exhibition\)", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return clean(text)


def extract_status(*parts: str) -> str:
    joined = " | ".join(clean(p) for p in parts if p)
    for label, pattern in STATUS_PATTERNS:
        if pattern.search(joined):
            return label
    return ""


def find_schedule_table(soup: BeautifulSoup):
    for table in soup.find_all("table"):
        first_rows = table.find_all("tr", limit=3)
        preview = " ".join(clean(r.get_text(" ", strip=True)) for r in first_rows).lower()
        if "date" in preview and "opponent" in preview:
            return table
    return None


def schedule_label_from_soup(soup: BeautifulSoup) -> str:
    for heading in soup.find_all(["h1", "h2", "h3"]):
        text = clean(heading.get_text(" ", strip=True))
        if "schedule" not in text.lower():
            continue
        match = re.search(r"\b(20\d{2}(?:-\d{2})?)\b", text)
        if match:
            return match.group(1)
    # Fallback for unusual Sidearm markup.
    text = clean(soup.get_text(" ", strip=True))[:1200]
    match = re.search(r"\b(20\d{2}(?:-\d{2})?)\b.{0,80}\bSchedule\b", text, re.I)
    return match.group(1) if match else "unknown"


def parse_schedule_html(html: str) -> tuple[str, list[Event]]:
    soup = BeautifulSoup(html, "html.parser")
    schedule_label = schedule_label_from_soup(soup)
    table = find_schedule_table(soup)
    if table is None:
        raise ValueError("No schedule table found")

    rows = table.find_all("tr")
    header: list[str] | None = None
    events: list[Event] = []

    for row in rows:
        cells = [clean(c.get_text(" ", strip=True)) for c in row.find_all(["th", "td"])]
        if not cells:
            continue

        lower = [c.lower() for c in cells]
        if "date" in lower and "opponent" in lower:
            header = lower
            continue

        if header is None:
            continue

        # Sidearm's text schedules currently expose these seven fields. If an extra
        # column appears, map by header name; if one is absent, safely default blank.
        values = {header[i]: cells[i] for i in range(min(len(header), len(cells)))}
        opponent = values.get("opponent", "")
        event_date = values.get("date", "")
        if not opponent or not event_date:
            continue
        if normalized_opponent(opponent) in NON_COMPETITION:
            continue

        result = values.get("result", "")
        event = Event(
            date=event_date,
            time=values.get("time", ""),
            at=values.get("at", ""),
            opponent=opponent,
            location=values.get("location", ""),
            tournament=values.get("tournament", ""),
            result=result,
            status=extract_status(*cells),
        )
        events.append(event)

    if not events:
        raise ValueError("Schedule table found, but no competition rows were parsed")
    return schedule_label, events


def fetch_events(session: requests.Session, url: str) -> tuple[str, list[Event]]:
    response = session.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    return parse_schedule_html(response.text)


def month_day(text: str) -> tuple[int, int] | None:
    match = re.search(r"\b([A-Z][a-z]{2})\s+(\d{1,2})\b", text or "")
    if not match or match.group(1) not in MONTHS:
        return None
    return MONTHS[match.group(1)], int(match.group(2))


def synthetic_day(text: str) -> int:
    md = month_day(text)
    if not md:
        return 9999
    try:
        return date(2024, md[0], md[1]).timetuple().tm_yday  # leap year keeps Feb 29 valid
    except ValueError:
        return 9999


def time_minutes(text: str) -> int:
    match = re.search(r"\b(\d{1,2}):(\d{2})\s*(AM|PM)\b", text or "", re.I)
    if not match:
        return 9999
    hour, minute, ampm = int(match.group(1)), int(match.group(2)), match.group(3).upper()
    hour %= 12
    if ampm == "PM":
        hour += 12
    return hour * 60 + minute


def match_distance(old: Event, new: Event) -> int:
    od, nd = synthetic_day(old.date), synthetic_day(new.date)
    date_delta = abs(od - nd) if od != 9999 and nd != 9999 else 30
    if date_delta > 180:  # account for Dec/Jan adjacency
        date_delta = 366 - date_delta
    ot, nt = time_minutes(old.time), time_minutes(new.time)
    time_delta = abs(ot - nt) if ot != 9999 and nt != 9999 else 60
    loc_penalty = 0 if clean(old.at).lower() == clean(new.at).lower() else 500
    tournament_penalty = 0 if clean(old.tournament).lower() == clean(new.tournament).lower() else 20
    return date_delta * 100 + min(time_delta, 600) + loc_penalty + tournament_penalty


def pair_events(old_events: list[Event], new_events: list[Event]):
    """Pair events by opponent/venue role, tolerating date/time/ranking changes."""
    used_new: set[int] = set()
    pairs: list[tuple[Event, Event]] = []
    unmatched_old: list[Event] = []

    for old in old_events:
        old_opp = normalized_opponent(old.opponent)
        candidates = [
            (idx, new)
            for idx, new in enumerate(new_events)
            if idx not in used_new
            and normalized_opponent(new.opponent) == old_opp
            and clean(new.at).lower() == clean(old.at).lower()
        ]
        if not candidates:
            # Last resort: same opponent even if Home/Away/Neutral was corrected.
            candidates = [
                (idx, new)
                for idx, new in enumerate(new_events)
                if idx not in used_new and normalized_opponent(new.opponent) == old_opp
            ]
        if not candidates:
            unmatched_old.append(old)
            continue
        idx, best = min(candidates, key=lambda item: match_distance(old, item[1]))
        used_new.add(idx)
        pairs.append((old, best))

    unmatched_new = [new for idx, new in enumerate(new_events) if idx not in used_new]
    return pairs, unmatched_old, unmatched_new


def event_date_delta(schedule_label: str, text: str) -> int | None:
    md = month_day(text)
    if not md:
        return None
    match = re.match(r"^(20\d{2})(?:-(\d{2}))?$", schedule_label or "")
    if not match:
        return None
    start_year = int(match.group(1))
    end_suffix = match.group(2)
    year = start_year
    if end_suffix is not None and md[0] <= 7:
        # Academic-year schedules such as 2026-27: Jan-Jul events are in 2027.
        year = (start_year // 100) * 100 + int(end_suffix)
        if year < start_year:
            year += 100
    try:
        return (date(year, md[0], md[1]) - date.today()).days
    except ValueError:
        return None


def is_relevant_removed_event(schedule_label: str, event: Event) -> bool:
    delta = event_date_delta(schedule_label, event.date)
    return delta is not None and -2 <= delta <= 400


def describe_change(sport: str, old: Event, new: Event) -> list[dict]:
    alerts: list[dict] = []
    context = {
        "sport": sport,
        "opponent": new.opponent or old.opponent,
        "date": new.date or old.date,
        "location": new.location or old.location,
    }

    if clean(old.date) != clean(new.date):
        alerts.append({**context, "kind": "DATE CHANGE", "detail": f"{old.date or 'TBA'} → {new.date or 'TBA'}", "priority": 4})

    if clean(old.time) != clean(new.time):
        alerts.append({**context, "kind": "TIME CHANGE", "detail": f"{old.time or 'TBA'} → {new.time or 'TBA'}", "priority": 4})

    if old.status != new.status and new.status:
        priority = 5 if new.status in {"CANCELED", "POSTPONED", "SUSPENDED"} else 4
        alerts.append({**context, "kind": new.status, "detail": f"Official schedule status: {new.status.title()}", "priority": priority})

    return alerts


def ntfy_url(topic: str) -> str:
    topic = topic.strip()
    if topic.startswith("https://") or topic.startswith("http://"):
        return topic.rstrip("/")
    return f"https://ntfy.sh/{topic}"


def send_ntfy(session: requests.Session, topic: str, alert: dict, source_url: str) -> None:
    title = f"Liberty {alert['sport']} — {alert['kind']}"
    lines = [alert.get("opponent", "Liberty Athletics")]
    if alert.get("date"):
        lines.append(alert["date"])
    if alert.get("detail"):
        lines.append(alert["detail"])
    if alert.get("location"):
        lines.append(alert["location"])
    payload = {
        "topic": topic if not topic.startswith("http") else topic.rstrip("/").split("/")[-1],
        "title": title,
        "message": "\n".join(lines),
        "priority": int(alert.get("priority", 4)),
        "tags": ["warning" if alert.get("priority", 4) >= 5 else "alarm_clock"],
        "click": source_url,
    }
    endpoint = "https://ntfy.sh/" if not topic.startswith("http") else "/".join(ntfy_url(topic).split("/")[:3]) + "/"
    response = session.post(endpoint, json=payload, timeout=TIMEOUT)
    response.raise_for_status()


def send_test(session: requests.Session, topic: str) -> None:
    alert = {
        "sport": "Athletics Monitor",
        "kind": "TEST",
        "opponent": "Your Liberty schedule alerts are working.",
        "date": datetime.now().strftime("%b %-d, %Y") if os.name != "nt" else datetime.now().strftime("%b %#d, %Y"),
        "detail": "Future delays, cancellations, postponements, and date/time changes will appear here.",
        "location": "",
        "priority": 3,
    }
    send_ntfy(session, topic, alert, "https://libertyflames.com/calendar")


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"version": 1, "sources": {}}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "sources": {}}


def save_state(state: dict) -> None:
    state["version"] = 1
    # Intentionally no per-run timestamp: if nothing changed, state.json stays byte-for-byte
    # identical and GitHub does not create a commit every 15 minutes.
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    topic = os.getenv("NTFY_TOPIC", "").strip()
    test_requested = os.getenv("TEST_NOTIFICATION", "").lower() in {"1", "true", "yes", "on"}

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})

    if test_requested:
        if not topic:
            print("TEST_NOTIFICATION requested but NTFY_TOPIC is missing", file=sys.stderr)
            return 2
        send_test(session, topic)
        print("Sent ntfy test notification")

    state = load_state()
    state.setdefault("sources", {})
    total_alerts = 0
    source_errors = 0

    for sport, url in SOURCES:
        old_source = state["sources"].get(sport, {})
        old_events = [Event.from_dict(e) for e in old_source.get("events", [])]
        previous_failures = int(old_source.get("failure_count", 0))

        try:
            new_label, new_events = fetch_events(session, url)
        except Exception as exc:
            source_errors += 1
            failure_count = min(previous_failures + 1, 3)
            print(f"ERROR {sport}: {exc}", file=sys.stderr)
            # Preserve the last good baseline rather than replacing it with bad/empty data.
            state["sources"][sport] = {
                **old_source,
                "url": url,
                "failure_count": failure_count,
                "last_error": clean(str(exc))[:300],
            }
            if previous_failures < 3 and failure_count == 3 and topic:
                send_ntfy(session, topic, {
                    "sport": sport,
                    "kind": "MONITOR ISSUE",
                    "opponent": "Schedule source has failed 3 checks in a row.",
                    "date": "",
                    "detail": "The last known schedule is being preserved; normal sports alerts may be delayed.",
                    "location": "",
                    "priority": 4,
                }, url)
            continue

        old_label = old_source.get("schedule_label", "")

        # The first successful run is a silent baseline. A wholesale season-label
        # rollover (for example 2025-26 -> 2026-27) is also silently re-baselined.
        season_rolled = bool(old_events and old_label and new_label != "unknown" and old_label != new_label)
        if season_rolled:
            print(f"ROLLOVER {sport}: {old_label} -> {new_label}; saved as new baseline")

        if old_events and not season_rolled:
            pairs, unmatched_old, unmatched_new = pair_events(old_events, new_events)
            alerts: list[dict] = []
            for old, new in pairs:
                alerts.extend(describe_change(sport, old, new))

            # If a future/current event disappears entirely, that can be how a cancellation
            # or schedule removal is represented, so flag it even if no keyword remains.
            for old in unmatched_old:
                if is_relevant_removed_event(new_label if new_label != "unknown" else old_label, old):
                    alerts.append({
                        "sport": sport,
                        "kind": "REMOVED FROM SCHEDULE",
                        "opponent": old.opponent,
                        "date": old.date,
                        "detail": f"Previously listed at {old.time or 'TBA'}; it no longer appears on the official schedule.",
                        "location": old.location,
                        "priority": 5,
                    })

            # Rare case: a cancellation/postponement appears as a newly inserted replacement row.
            for new in unmatched_new:
                if new.status:
                    alerts.append({
                        "sport": sport,
                        "kind": new.status,
                        "opponent": new.opponent,
                        "date": new.date,
                        "detail": f"Official schedule status: {new.status.title()}",
                        "location": new.location,
                        "priority": 5 if new.status in {"CANCELED", "POSTPONED", "SUSPENDED"} else 4,
                    })

            # Safety valve: a site redesign/parser issue should not blast dozens of alerts.
            if len(alerts) > 20:
                print(f"WARNING {sport}: suppressed {len(alerts)} alerts (safety threshold)", file=sys.stderr)
                alerts = []

            for alert in alerts:
                print(f"ALERT {sport}: {alert['kind']} — {alert.get('opponent', '')} — {alert.get('detail', '')}")
                if topic:
                    send_ntfy(session, topic, alert, url)
                else:
                    print("  NTFY_TOPIC is not set; alert logged but not pushed", file=sys.stderr)
                total_alerts += 1
        else:
            print(f"BASELINE {sport}: saved {len(new_events)} events")

        state["sources"][sport] = {
            "url": url,
            "schedule_label": new_label,
            "failure_count": 0,
            "last_error": "",
            "events": [asdict(e) for e in new_events],
        }
        time.sleep(0.25)  # be polite to the two official sites

    save_state(state)
    print(f"Done. alerts={total_alerts}, source_errors={source_errors}, sources={len(SOURCES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
