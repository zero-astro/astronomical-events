# Astronomical Events Notification System

A background service that periodically fetches astronomical event data from **in-the-sky.org** RSS feed, stores it in a SQLite database, classifies events by priority, and sends notifications via Telegram or Mastodon.

## Features

- 📡 Periodic RSS fetching from in-the-sky.org
- 💾 SQLite storage with WAL mode for crash safety
- 🏷️ Priority classification (P1-Critical to P5-Minor)
- 👁️ Visibility level extraction (1-5 telescope requirements)
- 🖼️ Thumbnail caching from event pages
- 📱 Telegram notifications for high-priority events
- 🐘 Mastodon posting with Basque translations
- 🌐 Full i18n: titles, descriptions, and UI labels in Basque
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
- Optional: Mastodon credentials for social posting

### Setup

```bash
cd /path/to/astronomical-events
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Edit with your tokens and settings
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
0 * * * * cd /path/to/astronomical-events && source venv/bin/activate && python3 scripts/main.py fetch >> logs/fetch.log 2>&1

# Send notifications every 6 hours
0 */6 * * * cd /path/to/astronomical-events && source venv/bin/activate && python3 scripts/main.py notify >> logs/notify.log 2>&1
```

### Daemon Mode

Continuous operation with automatic retry and recovery:

```bash
python3 scripts/main.py daemon
```

The daemon runs in a loop, fetching events at the configured interval. On failure, it waits 60 seconds before retrying to prevent crash-on-error loops.

## Mastodon Integration

Post astronomical events to Mastodon with full Basque translations using a **user-defined format** (max 500 chars).

**Step 1 — Create credentials file:**
Mastodon credentials go in `config/mastodon.json` (relative to skill directory):
```json
{
  "mastodon": {
    "instance_url": "https://mastodon.eus",
    "access_token": "your-personal-access-token"
  }
}
```

**Step 2 — Get an access token:**
Go to your Mastodon instance → Settings → Development → Personal access tokens → Generate a new token with `write:statuses` scope.

**Step 3 — Post today's events:**
```bash
python3 scripts/post-today-events.py
```

### Mastodon Posting Format

```
[Title]

📅 Data: [date]
📝 Azalpena:
[Brief description — max 150 chars]

🔭 Behatzeko informazioa:
[Viewing info — fits in remaining space]

🔗 Xehetasun gehiago: [URL]
🤖 ZERO espazio digitaletik
```

**Format rules:**
- No color priority emoji before title
- No "Mota" (type) or "Denbora" (time) fields
- Description uses `rich_description`, truncated to 150 characters
- Viewing info is included if available, fitting in remaining space
- Auto-truncation to 500 chars total

### Mastodon Posting Strategy

1. **Featured event post** — Today's main astronomical event with full legend
2. **Digest post** — Summary of all upcoming events

Both posts include a Basque translation footer and proper event legends.

## i18n (Basque Translations)

The system includes comprehensive Basque translations for:
- Event titles (eclipses, meteor showers, conjunctions, etc.)
- Descriptions and viewing information
- Time labels ("today", "tomorrow", "{N} days away")
- Priority tiers and visibility levels
- Mastodon post footers

### Translation Provider Configuration

**Supported providers:** `libretranslate` (default), `lm-studio`, `ollama`, `openai`

Configure in `.env`:

```bash
TRANSLATION_ENABLED=true
TRANSLATION_PROVIDER=libretranslate
TRANSLATION_LIBRETRANSLATE_API_BASE=https://itzulpenak.artizar-enea.eus
TRANSLATION_LM_STUDIO_API_BASE=http://192.168.16.20:8080/v1
TRANSLATION_MODEL=qwen3.6-35b-a3b
```

- **Libretranslate** (default): Self-hosted machine translation, CPU-only, slower
- **LM Studio**: Local LLM, no API key needed
- **Ollama**: Local LLM
- **OpenAI**: Remote API, requires `OPENAI_API_KEY`

Fallback: if the primary provider fails, the system tries the next provider automatically.

### Translation Workflow

```bash
# Step 1: Translate missing events
python3 scripts/main.py translate --lang eu

# Step 2: Sync translations to events table (ALWAYS after translate)
python3 scripts/sync_translations.py --lang eu

# Step 3: Verify all fields are populated
python3 scripts/verify_translations.py --lang eu
```

**⚠ Critical:** `translate` writes to the `translations` table only. **Always run `sync_translations.py`** before querying `events` table for translated data.

### Adding New Translations

New translations are added to the `_TRANSLATION_MAP` in `src/mastodon_client.py`:

```python
_TRANSLATION_MAP = {
    "Event name in English": "Itzulpena euskaraz",
    # ... more entries
}
```

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
cd /path/to/astronomical-events
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
cd /path/to/astronomical-events
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

5. **Mastodon posting failures**
   - Verify credentials in `config/mastodon.json` are correct
   - Check instance URL includes `https://` prefix
   - Review logs for rate limit errors (429 responses)

6. **Translations appear empty after `translate --lang eu`**
   - Run `sync_translations.py --lang eu` to sync translations table → events table
   - This is the most common issue — always sync after translation

7. **Translation provider fails**
   - Check `.env` has correct `TRANSLATION_PROVIDER` and API base URL
   - Libretranslate on CPU-only is slow — be patient
   - System will fallback to next provider automatically
   - Check logs to see which provider was used

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
│   ├── mastodon_client.py   # Mastodon posting utilities + i18n translations
│   ├── telegram_notifier.py # Telegram notification helpers
│   ├── retry.py             # Retry utilities (backoff, circuit breaker, rate limiter)
│   ├── cache.py             # Page content caching
│   └── dashboard.py         # FastAPI web dashboard
├── scripts/
│   ├── main.py              # CLI entry point
│   ├── post-today-events.py # Post today's events to Mastodon
│   └── translate_all_fields.py # Translate all DB fields to Basque
├── tests/                   # 76 unit + integration tests
├── docs/                    # Development plan and deployment guide
├── config/                  # Configuration files (credentials)
├── logs/                    # Runtime logs
├── .env.example             # Environment variable template
└── requirements.txt         # Python dependencies
```

## License

MIT
