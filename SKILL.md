---
name: astronomical-events
description: >-
  Fetch and notify about important astronomical events from in-the-sky.org.
  Periodically checks RSS feed, stores events in SQLite, classifies by priority,
  and sends Telegram notifications for eclipses, comets, meteor showers, occultations, etc.
  Use when the user wants to track astronomical events or receive sky event alerts.
---

# Astronomical Events Notification Skill

## Overview

Fetches astronomical news from in-the-sky.org RSS feed, stores them in SQLite, classifies by priority, and sends Telegram notifications.

## Usage

Run the skill script:
```bash
python3 /home/urtzai/.openclaw/skills/astronomical-events/scripts/main.py fetch
python3 /home/urtzai/.openclaw/skills/astronomical-events/scripts/main.py status
python3 /home/urtzai/.openclaw/skills/astronomical-events/scripts/main.py notify-now
```

## Configuration

Set environment variables in `.env`:
- `TELEGRAM_BOT_TOKEN` — Telegram bot token
- `TELEGRAM_CHAT_ID` — Target chat ID for notifications
- `RSS_URL` — RSS feed URL (default: in-the-sky.org DFAN)
- `LATITUDE` / `LONGITUDE` — Observer location

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
