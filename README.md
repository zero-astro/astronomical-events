# Astronomical Events Notification System

A background service that periodically fetches astronomical event data from **in-the-sky.org** RSS feed, stores it in a SQLite database, classifies events by priority, and sends notifications via Telegram.

## Features

- 📡 Periodic RSS fetching from in-the-sky.org
- 💾 SQLite storage with WAL mode for crash safety
- 🏷️ Priority classification (P1-Critical to P5-Minor)
- 👁️ Visibility level extraction (1-5 telescope requirements)
- 🖼️ Thumbnail caching from event pages
- 📱 Telegram notifications for high-priority events
- 📋 Daily digest of upcoming events
- 🔌 Per-channel error isolation (Mastodon, Telegram)
- ⚡ Retry logic with exponential backoff and jitter
- 🛡️ Circuit breaker pattern for resilient HTTP requests
- 🌐 FastAPI web dashboard for event browsing

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│ RSS Fetcher │────▶│ Event Parser │────▶│ Classifier   │
│ (retry +    │     │ (date/name   │     │ (P1-P5       │
│  circuit    │     │  extraction) │     │  priority)   │
└─────────────┘     └──────────────┘     └──────┬───────┘
                                                │
                                          ┌─────▼──────┐
                                          │  Database   │
                                          │ (SQLite +   │
                                          │  WAL mode)  │
                                          └─────┬──────┘
                                                │
                                        ┌───────▼────────┐
                                        │ Notification   │
                                        │ Dispatcher     │
                                        │ (Telegram,     │
                                        │  Mastodon)     │
                                        └────────────────┘
```

## Installation

### Prerequisites

- Python 3.12+
- Internet access (to fetch RSS from in-the-sky.org)
- Telegram bot token and chat ID for notifications

### Setup

```bash
cd /home/urtzai/.openclaw/skills/astronomical-events
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Edit with your Telegram token and chat ID
```

### Configuration

Create or edit `.env` file:

| Variable | Description | Example |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot API token | `123456:ABC-DEF...` |
| `TELEGRAM_CHAT_ID` | Target chat/group ID | `-1003948838238` |
| `DATABASE_PATH` | SQLite database file path | `/tmp/astronomical_events.db` |
| `FETCH_INTERVAL_SECONDS` | Seconds between fetches | `3600` |
| `WINDOW_DAYS` | Days ahead to fetch events | `15` |
| `LATITUDE` | Observer latitude (for visibility) | `43.139006` |
| `LONGITUDE` | Observer longitude | `-2.966625` |

## Usage

### CLI Commands

```bash
# Fetch events from RSS feed
python3 scripts/main.py fetch

# View stored upcoming events
python3 scripts/main.py status

# Send notifications for high-priority events
python3 scripts/main.py notify

# Run in daemon mode (continuous fetching)
python3 scripts/main.py daemon

# Check system health
python3 scripts/main.py health
```

### Cron Setup

For periodic fetches without daemon mode:

```bash
# Fetch every hour
0 * * * * cd /home/urtzai/.openclaw/skills/astronomical-events && source venv/bin/activate && python3 scripts/main.py fetch >> logs/fetch.log 2>&1

# Send notifications every 6 hours
0 */6 * * * cd /home/urtzai/.openclaw/skills/astronomical-events && source venv/bin/activate && python3 scripts/main.py notify >> logs/notify.log 2>&1
```

### Daemon Mode

Continuous operation with automatic retry and recovery:

```bash
python3 scripts/main.py daemon
```

The daemon runs in a loop, fetching events at the configured interval. On failure, it waits 60 seconds before retrying to prevent crash-on-error loops.

## Output Format

Notifications are sent as structured JSON following schema version `"1.0"`:

```json
{
  "schema_version": "1.0",
  "event_type": "eclipse",
  "title": "Total Lunar Eclipse",
  "date": "2026-09-07T18:43:00+02:00",
  "priority": 1,
  "visibility_level": 1,
  "description": "Total lunar eclipse visible from Europe.",
  "thumbnail_url": "https://in-the-sky.org/images/eclipse.jpg"
}
```

## Web Dashboard

A FastAPI-based web dashboard is available at `src/dashboard.py`:

```bash
cd /home/urtzai/.openclaw/skills/astronomical-events
source venv/bin/activate
pip install fastapi uvicorn
uvicorn src.dashboard:app --host 0.0.0.0 --port 8000
```

### API Endpoints

- `GET /` — Web dashboard (HTML)
- `GET /api/events?days=15` — JSON list of upcoming events
- `GET /api/stats` — Summary statistics (total, by priority, unnotified count)
- `GET /api/health` — Health check endpoint

## Testing

Run the full test suite:

```bash
cd /home/urtzai/.openclaw/skills/astronomical-events
source venv/bin/activate
pip install pytest
python3 -m pytest tests/ -v
```

### Test Coverage

| Module | Tests | Status |
|--------|-------|--------|
| `test_cache.py` | 5 | ✅ |
| `test_classifier.py` | 8 | ✅ |
| `test_db_integration.py` | 4 | ✅ |
| `test_db_manager.py` | 9 | ✅ |
| `test_event_parser.py` | 10 | ✅ |
| `test_notification_format.py` | 7 | ✅ |
| `test_page_scraper.py` | 8 | ✅ |
| `test_retry.py` | 8 | ✅ |
| `test_rss_fetcher.py` | 9 | ✅ |

**Total: 76 tests, all passing.**

## Troubleshooting

### Common Issues

1. **Telegram notifications not sending**
   - Check bot token is valid and hasn't expired
   - Verify chat ID includes the `-100` prefix for groups
   - Ensure the bot has been added to the target group

2. **RSS fetch failures**
   - Check network connectivity to in-the-sky.org
   - Review logs for circuit breaker state (open = too many failures)
   - The system will auto-recover after the recovery timeout period

3. **Database locked errors**
   - WAL mode should prevent most locking issues
   - Ensure only one instance runs at a time
   - Check file permissions on the database directory

4. **High CPU usage during thumbnail fetches**
   - Rate limiter prevents hammering in-the-sky.org (2 req/s default)
   - Adjust `refill_rate` in `.env` if needed

## Project Structure

```
astronomical-events/
├── src/
│   ├── main.py              # Entry point + CLI commands
│   ├── rss_fetcher.py       # RSS fetching with retry/circuit breaker
│   ├── event_parser.py      # RSS item parsing (date, name extraction)
│   ├── classifier.py        # Event classification (P1-P5 priority tiers)
│   ├── page_scraper.py      # Thumbnail/visibility extraction from pages
│   ├── db_manager.py        # SQLite operations (WAL mode, 15+ methods)
│   ├── notification.py      # Notification dispatch with error isolation
│   ├── mastodon_client.py   # Mastodon posting utilities
│   ├── telegram_notifier.py # Telegram notification helpers
│   ├── retry.py             # Retry utilities (backoff, circuit breaker, rate limiter)
│   ├── cache.py             # Page content caching
│   └── dashboard.py         # FastAPI web dashboard
├── tests/                   # 76 unit + integration tests
├── docs/                    # Development plan and deployment guide
├── config/                  # Configuration files (credentials)
├── logs/                    # Runtime logs
├── .env.example             # Environment variable template
└── requirements.txt         # Python dependencies
```

## License

MIT
