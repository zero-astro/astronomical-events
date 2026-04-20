# Astronomical Events Notification System

A background service that periodically fetches astronomical event data from **in-the-sky.org** RSS feed, stores it in a SQLite database, classifies events by priority, and sends notifications via Telegram.

## Features

- 📡 Periodic RSS fetching from in-the-sky.org
- 💾 SQLite storage with deduplication
- 🏷️ Priority classification (P1-Critical to P5-Minor)
- 👁️ Visibility level extraction (1-5 telescope requirements)
- 🖼️ Thumbnail caching from event pages
- 📱 Telegram notifications for high-priority events
- 📋 Daily digest of upcoming events

## Quick Start

```bash
cd /home/urtzai/.openclaw/skills/astronomical-events
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Edit with your Telegram token and chat ID
python3 scripts/main.py fetch   # First fetch
python3 scripts/main.py status  # View stored events
```

## Project Structure

See [PLAN.md](docs/PLAN.md) for full development plan.

## License

MIT
