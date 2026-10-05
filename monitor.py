--- /mnt/data/files/monitor.py	2026-10-05 12:34:31.600109061 +0000
+++ /mnt/data/monitor_v3.py	2026-10-05 12:35:55.114825372 +0000
@@ -19,7 +19,7 @@
 
 STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))
 TIMEOUT = 30
-USER_AGENT = "LibertyAthleticsScheduleMonitor/2.0 (+personal schedule-change notifier)"
+USER_AGENT = "LibertyAthleticsScheduleMonitor/2.1 (+personal schedule-change notifier)"
 
 # Liberty's NCAA menu has 18 sponsored teams; Cross Country and Track & Field each
 # share one schedule page for the men's and women's programs, so 16 NCAA URLs cover all 18.
@@ -46,6 +46,15 @@
 ]
 
 
+# Sidearm's /schedule/text view can omit disruption labels that are visible on the
+# normal schedule page. For Club Sports, check the normal page too and let an
+# explicit status there override a blank status from the text feed.
+STATUS_FALLBACK_URLS = {
+    "Men's D1 Hockey (Club)": "https://libertyclubsports.com/sports/mens-ice-hockey/schedule",
+    "Men's Lacrosse (Club)": "https://libertyclubsports.com/sports/mens-lacrosse/schedule",
+}
+
+
 # Phase 2: official Liberty story archives. These are an early-warning layer only.
 # A news-source failure never prevents the schedule monitor from running.
 NEWS_SOURCES = [
@@ -249,6 +258,97 @@
     return schedule_label, events
 
 
+def _event_date_tokens(event: Event) -> list[str]:
+    """Return compact date tokens useful for matching a visual schedule card."""
+    text = clean(event.date)
+    tokens = [text.casefold()] if text else []
+    match = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})\b", text)
+    if match:
+        month_lookup = {
+            "jan": "january", "january": "january",
+            "feb": "february", "february": "february",
+            "mar": "march", "march": "march",
+            "apr": "april", "april": "april",
+            "may": "may",
+            "jun": "june", "june": "june",
+            "jul": "july", "july": "july",
+            "aug": "august", "august": "august",
+            "sep": "september", "sept": "september", "september": "september",
+            "oct": "october", "october": "october",
+            "nov": "november", "november": "november",
+            "dec": "december", "december": "december",
+        }
+        month = month_lookup.get(match.group(1).casefold())
+        day = int(match.group(2))
+        if month:
+            tokens.extend([f"{month} {day}", f"{month[:3]} {day}"])
+    return list(dict.fromkeys(t for t in tokens if t))
+
+
+def enrich_statuses_from_visual_schedule(html: str, events: list[Event]) -> int:
+    """Fill blank event statuses from explicit labels on Sidearm's visual schedule.
+
+    The /schedule/text table has occasionally left Result as '-' even when the
+    visual schedule card says CANCELED. We search around opponent text and only
+    apply an explicit disruption label found in a nearby ancestor that also looks
+    like the same dated event. Existing text-feed statuses always win.
+    """
+    soup = BeautifulSoup(html, "html.parser")
+    changed = 0
+
+    for event in events:
+        if event.status:
+            continue
+        opponent_key = normalized_opponent(event.opponent)
+        if not opponent_key:
+            continue
+        date_tokens = _event_date_tokens(event)
+        best_status = ""
+
+        for node in soup.find_all(string=True):
+            node_text = clean(str(node))
+            if not node_text or opponent_key not in normalized_opponent(node_text):
+                continue
+
+            parent = node.parent
+            for _ in range(7):
+                if parent is None:
+                    break
+                block_text = clean(parent.get_text(" ", strip=True))
+                status = extract_status(block_text)
+                if status:
+                    block_fold = block_text.casefold()
+                    # Require the opponent plus the event date when possible. This
+                    # prevents a cancellation elsewhere on the page from bleeding
+                    # into the wrong event.
+                    if opponent_key in normalized_opponent(block_text) and (
+                        not date_tokens or any(token in block_fold for token in date_tokens)
+                    ):
+                        best_status = status
+                        break
+                parent = parent.parent
+            if best_status:
+                break
+
+        if best_status:
+            event.status = best_status
+            changed += 1
+
+    return changed
+
+
+def apply_status_fallback(
+    session: requests.Session, sport: str, events: list[Event]
+) -> tuple[str, int]:
+    """Use the visual Club Sports schedule as a non-fatal status fallback."""
+    fallback_url = STATUS_FALLBACK_URLS.get(sport, "")
+    if not fallback_url or not events:
+        return "", 0
+    response = session.get(fallback_url, timeout=TIMEOUT)
+    response.raise_for_status()
+    return fallback_url, enrich_statuses_from_visual_schedule(response.text, events)
+
+
 def fetch_events(session: requests.Session, url: str) -> tuple[str, list[Event]]:
     response = session.get(url, timeout=TIMEOUT)
     response.raise_for_status()
@@ -632,6 +732,19 @@
         try:
             new_label, all_new_events = fetch_events(session, url)
             new_events = [event for event in all_new_events if is_home_event(event)]
+            fallback_url = STATUS_FALLBACK_URLS.get(sport, "")
+            if fallback_url:
+                try:
+                    _, enriched = apply_status_fallback(session, sport, new_events)
+                    if enriched:
+                        print(f"STATUS FALLBACK {sport}: enriched {enriched} event(s) from {fallback_url}")
+                except Exception as fallback_exc:
+                    # The text schedule remains authoritative for dates/times and
+                    # must keep working even if the visual page temporarily fails.
+                    print(
+                        f"STATUS FALLBACK WARNING {sport}: {fallback_exc}",
+                        file=sys.stderr,
+                    )
             home_events[sport] = (new_label, new_events)
         except Exception as exc:
             source_errors += 1
