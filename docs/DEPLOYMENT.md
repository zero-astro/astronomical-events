# Astronomical Events — Deployment Guide

## Prerequisites

- Python 3.12+
- SQLite (built into Python)
- Internet connection (for RSS feed + Mastodon API)

---

## Installation

### 1. Clone the repository

```bash
git clone git@github.com:zero-astro/astronomical-events.git
cd astronomical-events
```

### 2. Create virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure

Copy the example config and edit:

```bash
cp config/default_config.json config/config.json
# Edit config/config.json with your settings
```

**Required fields:**
- `db_path` — SQLite database location (default: `data/events.db`)
- `rss_url` — in-the sky.org RSS feed URL
- `fetch_interval_minutes` — How often to fetch new events (default: 60)
- `window_days` — Event window for notifications (default: 15)

**Optional fields:**
- `mastodon_client_id`, `mastodon_instance_url`, `mastodon_access_token` — For Mastodon posting
- `telegram_chat_id` — For Telegram notifications (if using direct Telegram bot)

---

## Running

### One-time fetch + notify

```bash
python3 scripts/main.py schedule --run-once
```

### Start daemon mode (persistent background service)

```bash
python3 scripts/main.py schedule --daemon
```

### Health check

```bash
python3 scripts/main.py health
# Returns JSON: {"status": "healthy", ...}
# Exit code 0 = healthy, 1 = degraded, 2 = unhealthy
```

---

## Systemd Service (Linux)

Create `/etc/systemd/system/astronomical-events.service`:

```ini
[Unit]
Description=Astronomical Events Notification Service
After=network-online.target

[Service]
Type=simple
User=urtzai
WorkingDirectory=/home/urtzai/.openclaw/skills/astronomical-events
ExecStart=/home/urtzai/.openclaw/skills/astronomical-events/.venv/bin/python3 scripts/main.py schedule --daemon
Restart=on-failure
RestartSec=60

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable astronomical-events
sudo systemctl start astronomical-events
systemctl status astronomical-events
journalctl -u astronomical-events -f  # Follow logs
```

---

## OpenClaw Integration

The skill is designed to work with **OpenClaw** via stdout JSON routing.

### Cron trigger (heartbeat)

Add to your OpenClaw heartbeat or cron configuration:

```bash
# Every hour at :05
0 * * * * cd /home/urtzai/.openclaw/skills/astronomical-events && .venv/bin/python3 scripts/main.py schedule --run-once >> logs/cron.log 2>&1
```

### OpenClaw skill config

In your `skills.json` or equivalent:

```json
{
  "astronomical-events": {
    "path": "/home/urtzai/.openclaw/skills/astronomical-events",
    "trigger": "cron",
    "schedule": "0 * * * *"
  }
}
```

---

## Monitoring

### Health check endpoint (CLI)

```bash
python3 scripts/main.py health | jq .status
# Output: "healthy" or "degraded" or "unhealthy"
```

### Log files

Logs are written to `logs/app.log` in structured JSON format.

```bash
tail -f logs/app.log | jq .  # Pretty-print JSON logs
grep ERROR logs/app.log      # Filter errors only
```

### Database stats

```bash
python3 scripts/main.py status
# Shows: total events, upcoming events, last fetch time
```

---

## Troubleshooting

### RSS feed not fetching

1. Check network connectivity: `curl -I https://in-the-sky.org/rss.php`
2. Verify RSS URL in config
3. Check logs for HTTP errors: `grep "RSS" logs/app.log`

### Notifications not sending

1. Verify Mastodon/Telegram credentials in config
2. Run manually: `python3 scripts/main.py notify-now`
3. Check stdout output for JSON notifications

### Database locked errors

- SQLite WAL mode is enabled by default (should prevent most lock issues)
- If still seeing locks, increase `fetch_interval_minutes` to reduce concurrent writes
- Check for multiple daemon instances: `ps aux | grep main.py`

---

## Backup & Recovery

### Database backup

```bash
cp data/events.db data/events.db.backup
# Or use cron for automated backups:
0 3 * * * cp /home/urtzai/.openclaw/skills/astronomical-events/data/events.db /backup/astronomical-events-$(date +\%Y-\%m-\%d).db
```

### Restore from backup

```bash
cp /backup/astronomical-events-2026-04-28.db data/events.db
# Restart service if running
sudo systemctl restart astronomical-events
```

---

## Updating

```bash
cd /home/urtzai/.openclaw/skills/astronomical-events
git pull origin main
pip install -r requirements.txt  # If new dependencies added
# No database migrations needed (SQLite schema is stable)
sudo systemctl restart astronomical-events
```
