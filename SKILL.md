---
name: astronomical-events
description: >-
  Fetch and notify about important astronomical events from in-the-sky.org.
  Periodically checks RSS feed, stores events in SQLite, classifies by priority,
  and outputs structured notifications for OpenClaw to route through any channel.
  Use when the user wants to track sky events or receive astronomical alerts.
---

# Astronomical Events Notification Skill

## Overview

Fetches astronomical news from in-the-sky.org RSS feed, stores them in SQLite, classifies by priority, and outputs structured notifications for OpenClaw routing.

**OpenClaw Integration:** This skill does NOT require a Telegram bot token. Instead, it outputs deterministic JSON to stdout that OpenClaw can route through any channel (Telegram, WhatsApp, etc.) via heartbeat/cron triggers.

## Usage

Run the skill script:
```bash
python3 /home/urtzai/.openclaw/skills/astronomical-events/scripts/main.py fetch
python3 /home/urtzai/.openclaw/skills/astronomical-events/scripts/main.py status
python3 /home/urtzai/.openclaw/skills/astronomical-events/scripts/main.py notify-now
```

## Configuration

Set environment variables in `.env`:
- `RSS_URL` — RSS feed URL (default: in-the-sky.org DFAN)
- `LATITUDE` / `LONGITUDE` — Observer location
- `FETCH_INTERVAL_MINUTES` — How often to fetch (default: 60)
- `NOTIFICATION_WINDOW_DAYS` — Days ahead to track events (default: 15)

**No Telegram bot token required.** OpenClaw handles channel routing.

## Priority Tiers

| Tier | Events | Notification |
|------|--------|-------------|
| P1 🔴 | Eclipses, Novae/Supernovae | Immediate + alert |
| P2 🟠 | Meteor showers (peak), Occultations | Immediate |
| P3 🟡 | Planet close approaches, Comet perihelion | Summary |
| P4 🔵 | Planet conjunctions, Dwarf planet oppositions | Daily digest |
| P5 ⚪ | Moon conjunctions, Routine events | Digest only |

## Visibility Levels (1-5)

Level 1: Naked eye | Level 2: Binoculars | Level 3: Small telescope | Level 4: Medium telescope | Level 5: Large telescope
## Scheduling & Automation (Phase 4)

The skill includes a built-in scheduler daemon for fully automated operation.

### Daemon Mode
```bash
python3 scripts/main.py schedule              # Start continuous daemon
python3 scripts/main.py schedule --run-once   # Run one cycle and exit
```

**Jobs:**
- **Fetch job:** Every `FETCH_INTERVAL_MINUTES` (default: 60) — fetches RSS, classifies events
- **Notify job:** After each fetch — dispatches notifications for new events
- **Daily digest:** At 08:00 Europe/Madrid — summarizes all upcoming events

### Systemd Service
Install as a persistent service:
```bash
sudo cp scripts/astronomical-events.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now astronomical-events
```

**Management:**
```bash
sudo systemctl status astronomical-events    # Check status
sudo journalctl -u astronomical-events       # View logs
sudo systemctl restart astronomical-events   # Restart
```

### Health Check
```bash
python3 scripts/main.py health               # JSON output, exit codes: 0=healthy, 1=degraded, 2=unhealthy
```

Checks database connectivity, RSS feed reachability, and logging directory.

### Logging
Logs are written to `data/logs/astronomical_events.log` in structured JSON format with daily rotation (10MB max, 5 backups).


## Output Format (Deterministic)

When `notify-now` is called, the skill outputs structured JSON to stdout:

```json
{
  "schema_version": "1.0",
  "type": "astronomical_events",
  "batch_label": "P1-P2 High Priority",
  "count": 3,
  "events": [
    {
      "news_id": "abc123",
      "title": "Total Lunar Eclipse",
      "event_date": "2026-09-18T00:00:00",
      "time_label": "89 days away",
      "priority": 1,
      "priority_emoji": "🔴",
      "event_type": "eclipse",
      "is_notified": false,
      "visibility_level": 1,
      "visibility_label": "Naked eye"
    }
  ],
  "generated_at": "2026-04-21T07:00:00"
}
```

**Fixed schema keys:** `schema_version`, `type`, `batch_label`, `count`, `events[]`, `generated_at`

Each event in `events[]` has fixed keys: `news_id`, `title`, `event_date`, `time_label`, `priority`, `priority_emoji`, `event_type`, `is_notified`, plus optional `visibility_level`, `visibility_label`, `thumbnail_url`, `event_page_url`.

This deterministic format ensures consistent rendering across all channels.
