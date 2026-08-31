# Liberty Athletics → ntfy Schedule Alerts

A free personal notifier that checks official Liberty schedules every 15 minutes and sends an **ntfy push notification** when a game/meet is delayed, postponed, canceled, suspended, removed from the schedule, or has a date/time change.

## What it watches

### NCAA athletics — all Liberty sponsored teams
The 18 NCAA teams are covered by 16 official schedule pages because men's/women's Cross Country share one schedule and men's/women's Track & Field share one schedule:

- Baseball
- Men's Basketball
- Men's & Women's Cross Country
- Football
- Men's Golf
- Men's Soccer
- Men's Tennis
- Men's & Women's Track & Field
- Women's Basketball
- Field Hockey
- Women's Lacrosse
- Women's Soccer
- Softball
- Women's Swimming & Diving
- Women's Tennis
- Women's Volleyball

### Club sports added
- Men's D1 Hockey
- Women's D1 Hockey
- Men's Lacrosse

The monitor ignores schedule rows labeled as tryouts or information/team meetings.

## Cost

- **ntfy:** free push notifications to the ntfy app
- **GitHub Actions:** use a **public GitHub repository** so standard hosted runners are free
- No Twilio, SMS gateway, server, or paid hosting required

> This sends ntfy push notifications, not carrier SMS. They show up on your phone like text-style alerts through the ntfy app.

## Setup — about 5 minutes

### 1. Pick a private-looking ntfy topic

In the ntfy app, subscribe to a hard-to-guess topic such as:

`lu-athletics-7f3c9a-yourrandomstring`

Do **not** use something obvious like `liberty` or `flames`. On ntfy.sh, knowing the topic name is effectively knowing where messages can be published.

### 2. Create a GitHub repository

Create a new **PUBLIC** repository, for example:

`liberty-athletics-alerts`

Public matters because GitHub's standard Actions runners are free for public repositories.

### 3. Upload this project

Upload everything in this folder to the root of the repository, including the hidden `.github` folder.

Your repo should look like:

```
.github/
  workflows/
    monitor.yml
monitor.py
requirements.txt
state.json
README.md
```

### 4. Add your ntfy topic as a GitHub Secret

In the repository:

**Settings → Secrets and variables → Actions → New repository secret**

Name:

`NTFY_TOPIC`

Value:

Your ntfy topic name, e.g. `lu-athletics-7f3c9a-yourrandomstring`

The topic stays hidden from the public repository.

### 5. Run it once to build the baseline + test ntfy

Go to:

**Actions → Liberty Athletics Schedule Monitor → Run workflow**

Turn on **Send a test ntfy notification**, then run it.

You should receive a test push. The same run also saves the current official schedules as the baseline. It intentionally does **not** send dozens of alerts for events already on the schedule.

### 6. Done

The workflow checks at minutes **:07, :22, :37, and :52** every hour.

Examples of future alerts:

- `Liberty Football — TIME CHANGE` — `6:00 PM ET → 7:30 PM ET`
- `Liberty Softball — CANCELED`
- `Liberty Men's D1 Hockey (Club) — POSTPONED`
- `Liberty Track & Field (M/W) — DATE CHANGE`
- `Liberty Women's Soccer — REMOVED FROM SCHEDULE`

Tapping the notification opens the official schedule page that triggered it.

## How it avoids false alerts

- First run is a silent baseline.
- Normal final scores (W/L) do not trigger notifications.
- National ranking changes such as `Virginia` → `No. 18 Virginia` are ignored for matching.
- Repeated opponents in baseball/softball/hockey series are matched by their nearest date/time.
- If one schedule source fails, the last good version is preserved rather than treated as a cancellation.
- After three consecutive failures for one sport, ntfy sends a monitor-health warning.
- A safety threshold prevents a site redesign from blasting your phone with dozens of alerts.

## Important limitation

This system is only as fast as Liberty updates its official schedule pages. If a weather delay is announced on social media several minutes before the official schedule page changes, this monitor cannot know about it until the official page is updated. For schedule/time/cancellation changes, the official pages are the cleanest no-cost source.

## Want only Men's D1 hockey?

Open `monitor.py` and remove this source line:

`Women's D1 Hockey (Club)`

The rest of the system stays the same.
