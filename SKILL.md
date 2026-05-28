---
name: astronomical-events
description: >-
  Fetch and notify about important astronomical events from in-the-sky.org.
  Periodically checks RSS feed, stores events in SQLite, classifies by priority,
  and outputs structured notifications for OpenClaw to route through any channel.
  Supports Basque i18n translations and Mastodon posting.
  Use when the user wants to track sky events or receive astronomical alerts.
---

# Astronomical Events Notification Skill

## Overview

Fetches astronomical news from in-the-sky.org RSS feed, stores them in SQLite, classifies by priority, and outputs structured notifications for OpenClaw routing.

**OpenClaw Integration:** This skill does NOT require a Telegram bot token. Instead, it outputs deterministic JSON to stdout that OpenClaw can route through any channel (Telegram, WhatsApp, etc.) via heartbeat/cron triggers.

## Setup (first-time only)

This skill ships with a `pyproject.toml` but **no pre-installed venv**. On first use:

```bash\ncd /home/urtzai/.hermes/skills/astronomical-events\npython3 -m venv .venv\nsource .venv/bin/activate\npip install -e .   # installs feedparser, beautifulsoup4, lxml, apscheduler, pydantic-settings\n```\n\nAll subsequent commands must use the venv:\n```bash\n.venv/bin/python scripts/main.py fetch\n```\n\n> **Note:** System `pip` may not be available (no root/apt access). Always use `.venv`.\n\n### Mastodon posting dependency\n\nMastodon posting requires `mastodon.py`, which is NOT in the base install:\n```bash\ncd /home/urtzai/.hermes/skills/astronomical-events && .venv/bin/pip install mastodon.py\n```\n\n> **Note:** The skill's `pyproject.toml` does not include `mastodon.py`. Install it separately when you need Mastodon posting.

## Usage

Run the skill script:
```bash
cd /home/urtzai/.hermes/skills/astronomical-events && .venv/bin/python scripts/main.py fetch
cd /home/urtzai/.hermes/skills/astronomical-events && .venv/bin/python scripts/main.py status
cd /home/urtzai/.hermes/skills/astronomical-events && .venv/bin/python scripts/main.py notify-now
```

### CLI Commands

| Command | Description |
|---------|-------------|
| `fetch` | Fetch events from RSS feed and store in SQLite |
| `process` | Full pipeline: fetch + classify + scrape thumbnails (Phase 2) |
| `status` | View stored upcoming events with summary stats |
| `list [days]` | List all stored events (default: 15 days) |
| `notify-now` | Send notifications for high-priority events |
| `schedule` | Run continuous fetch loop (Ctrl+C to stop) |
| `schedule --run-once` | Run one scheduler cycle and exit |
| `health` | Check system health (DB, RSS, logs) |
| `translate --lang eu` | Translate missing events to Basque |
| `history` | Show recent fetch log entries |

> **Dashboard requires FastAPI** (`pip install fastapi uvicorn`). All other commands work without it.

### CLI Commands

| Command | Description |
|---------|-------------|
| `fetch` | Fetch events from RSS feed and store in SQLite |
| `status` | View stored upcoming events with summary stats |
| `notify-now` | Send notifications for high-priority events |
| `daemon` | Run continuous fetch loop (Ctrl+C to stop) |
| `health` | Check system health (DB, RSS, logs) |

## Configuration

Set environment variables in `.env`:
- `RSS_URL` — RSS feed URL (default: in-the-sky.org DFAN)
- `LATITUDE` / `LONGITUDE` — Observer location coordinates
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

## i18n — Basque Translations

The system includes full Basque translations for all event types, time labels, and UI elements.

### Mastodon Posting (Basque)

Post events to Mastodon with automatic Basque translation.

**Step 1 — Create credentials file:**
The script reads `config/mastodon.json` from the workspace root:
```json
{
  "mastodon": {
    "instance_url": "https://mastodon.eus",
    "access_token": "your-personal-access-token"
  }
}
```

**Step 2 — Get an access token:**
- Go to your Mastodon instance → Settings → Development → Personal access tokens
- Generate a new token with `write:statuses` scope
- Paste it into the JSON above

**Step 3 — Post:**
```bash
# Ensure MASTODON_ENABLED=true in .env
python3 scripts/post-today-events.py
```

### Posting a Single Event (Manual)

The skill's `format_mastodon_status()` function can format any event dict. To post a specific event:
```python
import sys; sys.path.insert(0, 'src')
from mastodon_client import format_mastodon_status, post_to_mastodon, load_mastodon_config

event = {
    "title": "Venus ilargarian altuera maximoan",
    "news_id": "abc123",
    "event_date": "2026-05-29T00:00:00",
    "event_type": "planet_conjunction",
    "priority": 5,
    "visibility_label": "Naked eye",
    "rich_description": "Venusen azalera...",
    "event_page_url": "https://in-the-sky.org/news.php?id=12345"
}

status = format_mastodon_status(event)  # returns Basque-formatted string
config = load_mastodon_config()
post_to_mastodon(status, config)
```

**⚠ Pitfall:** If `config/mastodon.json` doesn't exist, `load_mastodon_config()` returns `{}` and posting silently fails with "No Mastodon configuration available". Always verify the file exists before running.

### Translate All Fields

Translate database fields (title, description, viewing info) to Basque:
```bash
# Preview translations without applying
python3 scripts/translate_all_fields.py --dry-run

# Apply translations to all events in the database
python3 scripts/translate_all_fields.py
```

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

## User Preference — Single-Event Cards

When the user asks for an event card/fitxa, prefer **individual detailed cards** over grouped summaries. Each card should include:
- Title with emoji
- Date and time details
- What happens (explanation)
- How to observe it
- Key data points
- Hashtags

Grouped digests are only appropriate when the user explicitly asks for a summary of multiple events.

## Event Type Inference

The system automatically infers event types from titles when classification is uncertain:
- Contains "meteor" or "shower" → `meteor_shower`
- Contains "eclipse" → `eclipse`
- Contains "comet" or "komet" → `comet`
- Default fallback → `unknown`

## Adding New Translations

To add new event translations, edit `_TRANSLATION_MAP` in `src/mastodon_client.py`:

```python
_TRANSLATION_MAP = {
    "English event name": "Euskarazko itzulpena",
    # Add more entries here
}
```

After editing, run the translate script to update existing database records:
```bash
python3 scripts/translate_all_fields.py --dry-run  # Preview first
python3 scripts/translate_all_fields.py            # Apply changes
```

### Translation Cache (T1) — Skip API for unchanged content

Translations are cached in SQLite (`translation_cache` table). On re-runs, the system checks the cache before calling the LLM API. If a source text was already translated to the target language and field type, it's served from cache instantly.

**Cache key:** `(source_lang, target_lang, field_type, hash(source_text))`
- `field_type`: `'title'`, `'description'`, `'rich_description'`, or `'viewing_info'`
- This means translating the same title to Basque twice skips the API call on the second run.

**⚠ Pitfall — always pass `field_type` in `translate_batch()` calls.** Without it, cache lookups fall back to a generic key and may return wrong field content (e.g., a cached `rich_description` returned for a `viewing_info` query). Every call must specify the exact field type.

**Lazy DB manager pattern:** The database manager is initialized lazily at module level in `translate.py` via `_db_manager = None` + lazy init inside `get_db()`. This avoids circular imports between `translate.py` and `db_manager.py` and ensures a single connection pool per process. Never instantiate `DatabaseManager()` directly from other modules — always go through the lazy accessor.

**Clear cache:**
```bash
# Clear all translation cache
python3 scripts/main.py translate --clear-cache

# Clear cache for a specific language
TRANSLATION_TARGET_LANG=eu python3 -c "from db_manager import DatabaseManager; db = DatabaseManager(); db.invalidate_cache(target_lang='eu'); db.close()"
```

### Translation Speed Tip

Translation is sequential (one event at a time) with a **5-second delay** between requests to avoid LM Studio CPU timeouts. For faster iteration, edit `src/translator.py` line ~128:

```python
delay = 1  # seconds between requests (default: 5)
```

The translation provider defaults to `lm-studio` at `http://192.168.16.20:1234/v1` with model `qwen3.6-35b-a3b`. Override via env vars:

```bash
TRANSLATION_PROVIDER=openai   # or lm-studio, ollama
TRANSLATION_LM_STUDIO_API_BASE=http://localhost:1234/v1
TRANSLATION_MODEL=your-model-name
OPENAI_API_KEY=sk-...         # for openai provider
```

## Pitfalls & Known Issues

| Issue | Fix |
|-------|-----|
| `ModuleNotFoundError: feedparser` | Run `.venv/bin/pip install -e .` |
| `FastAPI not installed` blocking non-dashboard commands | Fixed in code (lazy import). If still seen, run `pip install fastapi uvicorn` or ignore — dashboard is the only command that needs it. |
| f-string syntax error (`unmatched '['`) in `main.py` | The file uses nested quotes in f-strings on Python 3.12+. Fixed by changing inner quotes to single quotes. If re-editing, avoid `{item["title"]}` inside double-quoted f-strings — use `{item['title']}` or escape. |
| Translation takes forever (5s delay × N events) | Reduce `delay` in `src/translator.py`. For 12 events at 5s each: ~60s + LLM inference time (~3-4s per call). |
| LM Studio health check fails → circuit breaker opens | The translator checks `http://192.168.16.20:1234/api/health` before translating. If the local LLM isn't running, translations are skipped. Start LM Studio first. |
| `translate --lang eu` times out mid-run | Long translation runs can exceed the 600s timeout, leaving some events untranslated. The script is idempotent — just re-run `.venv/bin/python scripts/main.py translate --lang eu`; it only processes missing events. Check progress with `status` between runs. |
| Translation cache stale (wrong translations) | If you changed the translation prompt or model, old cached results may be inaccurate. Clear cache first: see "Translation Cache" section above. |
| Mastodon posting fails: config not found | `post-next-event.py` and `post-today-events.py` look for `config/mastodon.json` relative to the workspace dir resolved via `OPENCLAW_WORKSPACE_DIR`. When running from cron/scheduler (no env var set), they fail. Fix: prefix with `OPENCLAW_WORKSPACE_DIR=/home/urtzai/.hermes/skills/astronomical-events` or set it as a persistent env var in the cron job. |\n| Manual `translate_single_event()` API changed | Module-level functions in `src/translator.py` expect an object with `.news_id`, `.title`, `.description` attributes (not a dict). Use the CLI instead of hand-calling module internals — the CLI handles the object construction correctly. |

## References

- Full troubleshooting guide: see `references/setup-troubleshooting.md`
- Mastodon posting setup & config: see `references/mastodon-setup.md`
