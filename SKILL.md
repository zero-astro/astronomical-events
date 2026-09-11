---
name: astronomical-events
description: Track astronomical events. Fetch RSS, translate to Basque.
---

# Astronomical Events Notification Skill

## Overview

Fetches astronomical news from in-the-sky.org RSS feed, stores them in SQLite, classifies by priority, and outputs structured notifications for routing.

**Agent Integration:** This skill outputs deterministic JSON to stdout that any agent system can route through channels (Telegram, WhatsApp, Mastodon, etc.) via heartbeat/cron triggers.

## Setup (first-time only)

This skill ships with a `pyproject.toml` but **no pre-installed venv**. On first use:

```bash
cd /home/urtzai/.hermes/skills/astronomical-events
python3 -m venv .venv
source .venv/bin/activate
pip install -e .   # installs feedparser, beautifulsoup4, lxml, apscheduler, pydantic-settings
```

All subsequent commands must use the venv:
```bash
.venv/bin/python scripts/main.py fetch
```

> **Note:** System `pip` may not be available (no root/apt access). Always use `.venv`.

### Mastodon posting dependency

Mastodon posting requires `mastodon.py`, which is NOT in the base install:
```bash
cd /home/urtzai/.hermes/skills/astronomical-events && .venv/bin/pip install mastodon.py
```

> **Note:** The skill's `pyproject.toml` does not include `mastodon.py`. Install it separately when you need Mastodon posting.

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

**No Telegram bot token required.** Channel routing is handled via stdout JSON.

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

### Translation Provider Configuration

**Supported providers:** `libretranslate` (default), `lm-studio`, `ollama`, `openai`

The system supports multiple translation providers with automatic fallback. Configure in `.env`:

```bash
TRANSLATION_ENABLED=true
TRANSLATION_PROVIDER=libretranslate          # libretranslate | lm-studio | ollama | openai
TRANSLATION_LIBRETRANSLATE_API_BASE=https://itzulpenak.artizar-enea.eus
TRANSLATION_LM_STUDIO_API_BASE=http://192.168.16.20:8080/v1
TRANSLATION_OLLAMA_API_BASE=http://localhost:11434/v1
TRANSLATION_OPENAI_API_BASE=https://api.openai.com/v1
TRANSLATION_MODEL=qwen3.6-35b-a3b           # LM Studio/Ollama model name
OPENAI_API_KEY=your_openai_key_here         # Only for openai provider
TRANSLATION_SOURCE_LANG=en                  # Source language (default: en)
TARGET_LANGUAGES=eu,ca                      # Target languages
```

**Provider selection:**
- **Libretranslate** (default) — Self-hosted at `https://itzulpenak.artizar-enea.eus/`. Machine translation, no GPU needed. Slower on CPU-only environments.
- **LM Studio** — Local LLM at `http://192.168.16.20:8080/v1`. No API key needed.
- **Ollama** — Local LLM at `http://localhost:11434/v1`.
- **OpenAI** — Remote API. Requires `OPENAI_API_KEY`.

**Fallback behavior:** If the primary provider fails, the system attempts the next provider in the chain. All providers are configurable via environment variables — no code changes needed.

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

### Mastodon Posting Format

The Mastodon format is **user-defined** with strict constraints (max 500 chars):

```
[Title]

📅 [date]
[Brief description — max 150 chars]

🔭 Behatzeko:
[Viewing info — fits in remaining space]

🔗 [URL]
🤖 ZERO espazio digitaletik
```

**Format rules:**
- **No** color priority emoji before title
- **No** "Mota" (type) or "Denbora" (time) fields
- **No** "Data:" prefix — only `📅` + date
- **No** "Azalpena:" header — description follows directly after date
- **Description** uses `rich_description` (translated), truncated to 150 characters
- **Viewing info** header is `🔭 Behatzeko:` (shortened from "Behatzeko informazioa")
- **URL** uses only `🔗` + URL (no "Xehetasun gehiago:" prefix)
- Footer (URL + signature) always present
- Auto-truncation: if description + viewing info + metadata exceed 500 chars, description is shortened or removed entirely

**⚠ Configuration path:** Mastodon credentials are loaded from `config/mastodon.json` relative to the skill directory. If the file is missing, `load_mastodon_config()` returns `{}` and posting silently fails. Always verify the file exists.

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

### ⚠ Critical: Sync translations AFTER every translate run

**User preference:** Always use the provided Python helper scripts — never run raw SQL for DB operations. Scripts are idempotent, versioned, and maintainable.

```bash
# After any `translate --lang eu` run:
.venv/bin/python scripts/sync_translations.py --lang eu
```

**Why this matters:** `translate_event()` writes to the `translations` table only. The `events` table has parallel `translated_*` columns (`translated_title`, `translated_description`, etc.) that remain EMPTY after translation. If you query `events` without syncing first, you will see empty `translated_*` fields — this is the #1 cause of "translations are missing" false reports.

**Verify after sync:**
```bash
.venv/bin/python scripts/verify_translations.py --lang eu
```

> **User correction:** User reported "You said everything was translated but it isn't." The fix: sync step was missing. Always sync, then verify.

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

### Full Translation Workflow (Reproducible, Zero Effort)

**Step 1 — Sync translations to events table (ALWAYS first):**
After `translate --lang eu`, translations live in the `translations` table. The `events` table has parallel `translated_*` columns that remain empty. Use the sync script:
```bash
cd /home/urtzai/.hermes/skills/astronomical-events
.venv/bin/python scripts/sync_translations.py --lang eu
```
**⚠ Critical pitfall:** `translate_event()` writes to the `translations` table only. **Always run the sync above before querying translated data from the events table.**

**Step 2 — Translate missing events (per-event mode):**
```bash
cd /home/urtzai/.hermes/skills/astronomical-events
.venv/bin/python scripts/main.py translate --lang eu
```
- Uses `src/translate.py` `translate_missing_events()` → per-event loop (one request per event, no mixing)
- Default provider: Libretranslate at `https://itzulpenak.artizar-enea.eus/` (CPU-only, slow)
- Fallback: LM Studio at `http://192.168.16.20:8080/v1`
- Translates: `title`, `description`, `rich_description_en`, `viewing_info_en` → Basque
- Sequential mode (5s delay between requests to avoid timeouts)
- Idempotent: only processes missing events

**Step 3 — Generate rich_description_en & viewing_info_en (LLM, not scraping):**
in-the-sky.org blocks all web scraping (Anubis bot-detect). Use LLM to generate these fields from RSS data:
```bash
cd /home/urtzai/.hermes/skills/astronomical-events
# Prepare input JSON (RSS title + description only)
.venv/bin/python -c "
import sqlite3, json
conn = sqlite3.connect('data/events.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute('SELECT news_id, title, description FROM events ORDER BY event_date DESC')
events = [dict(r) for r in cur.fetchall()]
conn.close()
with open('data/events_for_gen.json', 'w') as f:
    json.dump(events, f, indent=2)
print(f'{len(events)} events prepared')
"

# Generate rich_description_en + viewing_info_en via LLM
.venv/bin/python src/translate.py --generate --lang eu
```

**Step 4 — Sync again (if translation modified events columns):**
```bash
# Re-run sync script if needed
.venv/bin/python scripts/sync_translations.py --lang eu
```

**Step 5 — Verify all fields are populated:**
```bash
cd /home/urtzai/.hermes/skills/astronomical-events
.venv/bin/python scripts/verify_translations.py --lang eu
```

### Translation Cache (T1) — Skip API for unchanged content

Translations are cached in SQLite (`translation_cache` table). On re-runs, the system checks the cache before calling the translation API. If a source text was already translated to the target language and field type, it's served from cache instantly.

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

### Translation Speed Tips

- Libretranslate on CPU-only environments is slow — be patient
- Translation is sequential (one event at a time) with a **5-second delay** between requests
- For faster iteration, edit `src/translate.py` delay parameter (default: 5)

### Parallel Translation Note

`global_batch_translate()` runs field-type batches **sequentially** by default. Parallel (`ThreadPoolExecutor`) was tested but reverted — it would only queue requests without speeding things up.

If you switch to a provider that supports concurrent requests (e.g., OpenAI API, Ollama with `--parallel`), re-enable parallel in `src/translate.py` by uncommenting the `ThreadPoolExecutor(max_workers=2)` block.

The translation provider defaults to `libretranslate` at `https://itzulpenak.artizar-enea.eus/`. Override via env vars:

```bash
TRANSLATION_PROVIDER=libretranslate   # or lm-studio, ollama, openai
TRANSLATION_LIBRETRANSLATE_API_BASE=https://itzulpenak.artizar-enea.eus
TRANSLATION_LM_STUDIO_API_BASE=http://192.168.16.20:8080/v1
TRANSLATION_MODEL=your-model-name
OPENAI_API_KEY=sk-...         # for openai provider
```

## Web Scraping Pitfalls

| Issue | Fix |
|-------|-----|
| `in-the-sky.org` Anubis bot-detect blocks all scraping | `/news.php?id=` pages are behind Anubis Proof-of-Work challenge. `web_extract`, `urllib`, browser tool ALL get blocked with "Making sure you're not a bot!" page. RSS feed (`in-the-sky.org/dfan.rss`) works fine. Never rely on scraping individual news pages from this domain. |
| Web scraping blocked → content fields empty | When `rich_description_en` and `viewing_info_en` need filling but scraping is blocked, use llama.cpp to GENERATE them from RSS title + description. Build a prompt with event data and ask the LLM to produce detailed paragraphs. Save as JSON, then UPDATE the DB. |
| LLM generation prompt pattern | Build a prompt listing all events with their RSS data (title + description), ask for a JSON array with `rich_description_en` (3-5 sentence detailed explanation) and `viewing_info_en` (practical observing details). Use temperature 0.3, max_tokens 8000. Extract JSON from response with regex `\[.*\]`. |

## Pitfalls & Known Issues

| Issue | Fix |
|-------|-----|
| `ModuleNotFoundError: feedparser` | Run `.venv/bin/pip install -e .` |
| `FastAPI not installed` blocking non-dashboard commands | Fixed in code (lazy import). If still seen, run `pip install fastapi uvicorn` or ignore — dashboard is the only command that needs it. |
| f-string syntax error (`unmatched '['`) in `main.py` | The file uses nested quotes in f-strings on Python 3.12+. Fixed by changing inner quotes to single quotes. If re-editing, avoid `{item["title"]}` inside double-quoted f-strings — use `{item['title']}` or escape. |
|| Translation takes forever | Libretranslate on CPU-only is slow. Reduce `delay` in `src/translate.py`. For 12 events at 5s each: ~60s + inference time. |
|| Translation provider fails → fallback | System automatically tries next provider. Check logs for which provider was used. |
|| `translate --lang eu` times out mid-run | Long translation runs can exceed the 600s timeout, leaving some events untranslated. The script is idempotent — just re-run. Check progress with `status` between runs. |
|| Translation cache stale (wrong translations) | If you changed the translation provider or model, old cached results may be inaccurate. Clear cache first: see "Translation Cache" section above. |
|| Manual `translate_single_event()` API changed | Module-level functions in `src/translate.py` expect an object with `.news_id`, `.title`, `.description` attributes (not a dict). Use the CLI instead of hand-calling module internals. |
|| Sequential translation only | Libretranslate and LM Studio process one request at a time. Never use `ThreadPoolExecutor` or async for translation calls. If you switch to OpenAI API or Ollama with `--parallel`, re-enable parallelism then.

## References

- Full troubleshooting guide: see `references/setup-troubleshooting.md`
- Mastodon posting setup & config: see `references/mastodon-setup.md`
- LM Studio parallel translation pitfall: see `references/lm-studio-parallel-pitfall.md` — why `ThreadPoolExecutor` fails with local LLMs and when to re-enable it.
