# Astronomical Events Notification System

## 1. Overview

A background service that periodically fetches astronomical event data from **in-the-sky.org** RSS feed, stores it in a SQLite database, classifies events by priority, and outputs structured JSON notifications routed by OpenClaw through any channel (Telegram, WhatsApp, Mastodon, etc.).

### Key Requirements
- Fetch RSS: `https://in-the-sky.org/rss.php?feed=dfan&latitude=43.139006&longitude=-2.966625&timezone=Europe/Madrid`
- Store in SQLite on the server
- Display events within a **15-day window**
- Classify by priority (low → high)
- Output structured JSON notifications (routed by OpenClaw to any channel)
- Mastodon posting when configured

---

## 2. RSS Feed Analysis

### Feed Structure
The RSS feed is standard RSS 2.0 with the following fields per item:

| Field | Example | Notes |
|-------|---------|-------|
| `title` | `23 Apr 2026 (3 days away): 136108 Haumea at opposition` | Contains date, countdown, and event name |
| `link` | `https://in-the-sky.org/news.php?id=20260423_13_100` | Individual event page URL |
| `description` | HTML `<p>` paragraph with short description | May contain links to related objects |
| `pubDate` | `Thu, 23 Apr 2026 08:47:27 GMT` | When the news item was published on in-the-sky.org |
| `guid` | Same as `link` | Unique identifier |

### Thumbnail Strategy
The RSS feed does **not** include `<media:content>` or thumbnail elements. Thumbnails must be fetched from each event's individual page:
- URL pattern: `https://in-the-sky.org/image.php?style=hugeteaser&img=<image_path>`
- Example: `https://in-the-sky.org/image.php?style=hugeteaser&img=imagedump/dwarfplanets/136108.jpg`

### Event Types Identified in Feed
| Type | Examples | Priority |
|------|----------|----------|
| Conjunction (Moon + planet) | Moon & Jupiter, Moon & Venus | Low |
| Conjunction (planet + planet) | Saturn & Mars, Mercury & Saturn | Low |
| Close approach (Moon) | Moon & M45 | Low-Medium |
| Close approach (planets) | Mercury & Saturn | Low-Medium |
| Opposition | Haumea at opposition | Low |
| Meteor shower | Lyrid meteor shower 2026 | High |
| Lunar occultation | Beta Tauri occultation | Very High |
| Comet perihelion | C/2025 R3 (PANSTARRS) passes perihelion | Very High |

---

## 3. Visibility Levels (from in-the-sky.org)

The website uses icon-based visibility levels (`level1_icon.png` through `level5_icon.png`). Each level corresponds to the telescope size required:

| Level | Icon File | Description | Equipment Required |
|-------|-----------|-------------|-------------------|
| **Level 1** | `level1_icon.png` | Naked eye visible | No equipment needed — visible to the naked eye |
| **Level 2** | `level2_icon.png` | Binoculars recommended | Binoculars help, but doable without |
| **Level 3** | `level3_icon.png` | Small telescope required | Small telescope (4-inch / ~100mm) |
| **Level 4** | `level4_icon.png` | Medium telescope required | Medium telescope (8-inch / ~200mm) |
| **Level 5** | `level5_icon.png` | Large telescope required | Large telescope (12-inch+ / ~300mm+) |

### Parsing Strategy
Each event page contains a `<img>` tag referencing the level icon:
```html
<img src="https://in-the-sky.org/images/level4_icon.png" alt="This event is visible through a four-inch telescope from Ferrol." />
```
The `alt` text provides a human-readable description of visibility.

---

## 4. Priority Classification System

Events are classified into **5 priority tiers** based on type and significance:

| Tier | Label | Events Included | Notification Behavior |
|------|-------|-----------------|----------------------|
| **P1** | 🔴 Critical | Eclipses (solar/lunar), Supernovae/Novae, Comet discoveries, Rare object appearances | Immediate notification + alert sound |
| **P2** | 🟠 High | Meteor showers (peaks), Lunar occultations visible from Europe, Planet transits | Immediate notification |
| **P3** | 🟡 Medium | Close approaches of planets (non-Moon), Comet perihelion passages, Asteroid oppositions | Notification with summary |
| **P4** | 🔵 Low | Conjunctions involving only planets, Dwarf planet oppositions, Moon close approaches to deep-sky objects | Included in daily digest |
| **P5** | ⚪ Minor | Moon conjunctions (Moon + planet), Routine planetary alignments | Daily digest only |

### Classification Rules (Implementation)
```python
# P1: Critical — Eclipse or nova/supernova
if "eclipse" in title_lower or "supernova" in title_lower or "nova" in title_lower:
    priority = 1

# P2: High — Meteor shower peak, occultation visible from Europe
elif "meteor shower" in title_lower and ("peak" in title_lower):
    priority = 2
elif "occultation" in title_lower:
    # Check if visible from user's location (parse description for country list)
    priority = 2

# P3: Medium — Planet close approach, comet perihelion
elif "close approach" in title_lower and not ("moon" in title_lower):
    priority = 3
elif "comet" in title_lower and "perihelion" in title_lower:
    priority = 3

# P4: Low — Planet conjunction, dwarf planet opposition
elif "conjunction" in title_lower or "opposition" in title_lower:
    # Check if Moon is involved → demote to P5
    if "moon" in title_lower:
        priority = 5
    else:
        priority = 4

# P5: Minor — Moon conjunctions, routine events
else:
    priority = 5
```

---

## 5. Database Schema (SQLite)

### `events` Table
Stores all fetched astronomical events.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Internal ID |
| `news_id` | TEXT | UNIQUE NOT NULL | in-the-sky.org news ID (e.g., `20260423_13_100`) |
| `title` | TEXT | NOT NULL | Event title from RSS |
| `event_date` | DATETIME | NOT NULL | Date/time of the event (parsed from title) |
| `rss_pub_date` | DATETIME | NOT NULL | When the news item was published on in-the-sky.org |
| `description` | TEXT | | HTML description from RSS (stripped to plain text) |
| `event_type` | TEXT | NOT NULL | Classification: conjunction, opposition, close_approach, meteor_shower, occultation, eclipse, comet, nova_supernova |
| `priority` | INTEGER | NOT NULL DEFAULT 5 | Priority tier (1-5) |
| `visibility_level` | INTEGER | CHECK(visibility_level BETWEEN 1 AND 5) | Visibility level from in-the-sky.org |
| `thumbnail_url` | TEXT | | URL of the event thumbnail image |
| `event_page_url` | TEXT | NOT NULL | Full URL to the event page on in-the-sky.org |
| `is_notified` | BOOLEAN | DEFAULT FALSE | Whether a notification has been sent for this event |
| `created_at` | DATETIME | DEFAULT CURRENT_TIMESTAMP | Record creation time |

### `fetch_log` Table
Tracks RSS fetch operations for monitoring and debugging.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Internal ID |
| `fetched_at` | DATETIME | DEFAULT CURRENT_TIMESTAMP | When the fetch occurred |
| `items_fetched` | INTEGER | | Number of items in this RSS response |
| `new_items` | INTEGER | | Number of new (previously unseen) items |
| `status` | TEXT | NOT NULL | Status: success, error, partial |
| `error_message` | TEXT | | Error details if status != success |

### `config` Table
Stores user preferences and state.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `key` | TEXT | PRIMARY KEY | Configuration key |
| `value` | TEXT | NOT NULL | Configuration value |
| `updated_at` | DATETIME | DEFAULT CURRENT_TIMESTAMP | Last update time |

**Default config values:**
```sql
INSERT INTO config (key, value) VALUES
  ('latitude', '43.139006'),
  ('longitude', '-2.966625'),
  ('timezone', 'Europe/Madrid'),
  ('window_days', '15'),
  ('rss_url', 'https://in-the-sky.org/rss.php?feed=dfan&latitude=43.139006&longitude=-2.966625&timezone=Europe/Madrid'),
  ('telegram_chat_id', '<user_chat_id>'),
  ('notification_hourly_check', 'true'),
  ('digest_enabled', 'true');
```

### Indexes
```sql
CREATE INDEX idx_events_event_date ON events(event_date);
CREATE INDEX idx_events_priority ON events(priority);
CREATE INDEX idx_events_notified ON events(is_notified);
CREATE INDEX idx_fetch_log_fetched_at ON fetch_log(fetched_at DESC);
```

---

## 6. Architecture & Components

### System Flow
```
┌──────────────┐     ┌───────────────┐     ┌──────────────┐
│   Cron Job   │────▶│  RSS Fetcher  │────▶│  Parser      │
│ (every hour) │     │               │     │ + Classifier │
└──────────────┘     └───────────────┘     └──────┬───────┘
                                                  │
                                          ┌───────▼───────┐
                                          │  SQLite DB    │
                                          │  (events,     │
                                          │   fetch_log)  │
                                          └───────┬───────┘
                                                  │
                                          ┌───────▼───────┐
                                          │ Notification  │
                                          │ Engine        │
                                          └───────┬───────┘
                                                  │
                                    ┌─────────────┼───────────────┐
                                    ▼             ▼               ▼
                              ┌──────────┐  ┌──────────┐  ┌──────────┐
                              │ OpenClaw │  │ Mastodon │  │ Stdout   │
                              │ stdout   │  │ (if      │  │ JSON     │
                              │ routing  │  │ config'd)│  │ output   │
                              └──────────┘  └──────────┘  └──────────┘
```

### Components

#### A. RSS Fetcher (`rss_fetcher.py`)
- Fetches the RSS feed from in-the-sky.org
- Handles HTTP errors, retries, and rate limiting
- Parses XML into structured Python objects
- Deduplicates against existing `news_id` values in SQLite

#### B. Event Parser & Classifier (`event_parser.py`)
- Extracts event date from title (e.g., `"23 Apr 2026 (3 days away): ..."`)
- Strips HTML from descriptions → plain text
- Fetches individual event page to extract:
  - Thumbnail URL (`style=hugeteaser` image)
  - Visibility level icon and alt text
- Classifies event type and priority tier

#### C. Database Manager (`db_manager.py`)
- SQLite connection management
- CRUD operations for events, fetch_log, config
- Query helpers: `get_upcoming_events()`, `mark_notified()`, etc.

#### D. Notification Engine (`notifier.py`)
- Formats messages for Telegram (MarkdownV2 or HTML)
- Sends notifications for new/high-priority events
- Generates daily digest of all upcoming events in the 15-day window
- Handles Telegram API rate limits and errors

---

## 7. Development Phases

### Phase 1: Core Infrastructure
**Goal:** Fetch RSS, store in SQLite, basic CLI tooling.

**Tasks:**
1. [x] Create project structure (`src/`, `config/`, `tests/`)
2. [x] Set up Python virtual environment with dependencies:
   - `feedparser` (RSS parsing)
   - `sqlite3` (built-in) or `aiosqlite` (async)
   - `python-telegram-bot` or `requests` (Telegram API)
   - `beautifulsoup4` (HTML parsing for event pages)
   - `schedule` or `apscheduler` (task scheduling)
3. [x] Implement database schema and migrations
4. [x] Implement RSS fetcher with error handling
5. [x] Store fetched items in SQLite (deduplication by `news_id`)
6. [x] CLI command: `python src/fetch.py --status` to view stored events

**Deliverable:** ✅ Working pipeline — RSS → SQLite, queryable via CLI. Completed: `scripts/main.py` (fetch/status/list/history commands), `src/rss_fetcher.py`, `src/db_manager.py`, `.gitignore`.

---

### Phase 2: Event Parsing & Classification — COMPLETED ✅
**Goal:** Extract structured data from each event and classify by priority.

**Completion Date:** April 20, 2026

**Tasks Completed:**
1. [x] Title parser (extract event date + event name) — `event_parser.py`
2. [x] HTML description → plain text converter — `event_parser.py`
3. [x] Event page scraper:
   - Fetch thumbnail URL (`style=hugeteaser`) — `page_scraper.py`
   - Parse visibility level icon and alt text — `page_scraper.py`
   - **Fix:** Clamp visibility_level to 1-5 range (in-the-sky.org returns values up to 6)
4. [x] Event type classifier with improved pattern matching — `classifier.py`:
   - Eclipse detection → P1 Critical
   - Nova/Supernova detection → P1 Critical
   - Meteor shower peak detection → P2 High
   - Non-peak meteor showers → P3 Medium (improved)
   - Occultation detection with Europe visibility check → P2 High
   - Planet close approach (non-Moon) → P3 Medium
   - Comet perihelion → P3 Medium
   - Planet conjunctions → P4 Low
   - Dwarf planet opposition → P4 Low
   - Moon involvement events → P5 Minor
   - **New:** Generic event fallback (`_looks_like_generic_event`) → P4 Low
   - **Default:** Unknown events → P5 Minor (lowest priority)
5. [x] Priority tier assignment based on classification rules — `classifier.py`
6. [x] Database update with parsed fields — `db_manager.py`

**Key Fixes Applied:**
- Visibility level clamping: in-the-sky.org returns values 1-6, but DB constraint is 1-5. Added clamp logic in `_extract_visibility()`.
- Classifier improved to detect "Conjunction of X and Y" patterns (planet-only) → P4 instead of unknown.
- Meteor shower detection extended to non-peak events → P3.
- Unknown events default to P5 Minor (as requested).

**Pipeline Results:**
```
Total items:     12
New events:      12
Existing:        0
Classified:      12
Pages scraped:   12
Total in DB:     13

Classification Summary:
  P2 (High):       1 event — occultation
  P3 (Medium):     4 events — close_approach, comet, meteor_shower
  P4 (Low):        4 events — conjunction, opposition
  P5 (Minor):      4 events — moon_conjunction
```

**Deliverable:** ✅ All events in DB have `event_type`, `priority`, `visibility_level`, and `thumbnail_url`. Pipeline runs end-to-end without errors.

---

### Phase 3: Notification System — COMPLETED ✅
**Goal:** Send structured notifications for new and high-priority events via OpenClaw routing.

**Completion Date:** April 21, 2026

**Tasks Completed:**
1. [x] **OpenClaw stdout JSON routing** (instead of Telegram bot):
   - No Telegram bot token required — outputs deterministic JSON to stdout
   - OpenClaw routes notifications through any channel (Telegram, WhatsApp, etc.)
   - `telegram_notifier.py` is a stub module (imports satisfied only)
2. [x] **Message formatter** (`notification.py`):
   - `_format_event_for_output()` — fixed-schema dict per event
   - `_format_notification_message()` — batched output with schema version, type, count, events[], generated_at
   - Priority emoji + tier label (P1-P5)
   - Time label: "today", "tomorrow", or "{N} days away"
   - Visibility level + human-readable label
   - Thumbnail URL and event page URL included when available
   - Description truncated to 200 chars with `description_truncated` flag
3. [x] **Notification logic**:
   - P1/P2 → Immediate individual notifications (one per event)
   - P3 → Batched, up to 5 events per batch
   - P4/P5 → Daily digest of all upcoming events in the window
4. [x] Mark events as `is_notified = true` after dispatch (`db.mark_as_notified(event.news_id)`)
5. [x] **Mastodon integration** (bonus, not in original plan):
   - P1-P3 events posted to Mastodon when configured (`mastodon_client.py`, `mastodon_poster.py`)
   - Daily digest also posted to Mastodon
6. [x] Basic error handling with try/except and stats tracking

**Key Differences from Plan:**
- ❌ No Telegram bot/client — replaced by OpenClaw stdout JSON routing (more flexible, multi-channel capable)
- ✅ Mastodon integration added as bonus channel
- ⚠️ Retry logic not implemented (basic error handling only)

**Deliverable:** ✅ Structured notifications dispatched via stdout JSON. P1-P2 immediate, P3 batched, P4-P5 daily digest. Mastodon posting when configured.

---

### Phase 4: Scheduling & Automation
**Goal:** Fully automated background service.

**Tasks:**
1. ✅ Implement cron-like scheduling (hourly RSS fetch)
2. ✅ Daily digest job (e.g., at 08:00 Europe/Madrid)
3. ✅ Systemd service config for persistence
4. ✅ Logging with rotation (structured JSON logs)
5. ✅ Health check CLI command
6. ✅ Configuration via environment variables or `.env` file

**Deliverable:** Fully automated, self-healing background service.

---

### Phase 5: Polish & Monitoring
**Goal:** Production-ready with monitoring and user feedback.

**Tasks:**
1. [ ] Web dashboard (optional): simple Flask/FastAPI app showing upcoming events
2. [ ] Manual notification trigger via Telegram command (`/notify now`)
3. [ ] Config update via Telegram commands (`/set_location 43.1,-2.9`)
4. [ ] Performance: batch fetch thumbnails, cache event pages
5. [ ] Tests: unit tests for parser/classifier, integration tests for DB
6. [ ] Documentation: README, deployment guide

**Deliverable:** Production-ready system with monitoring and user interaction.

---

## 8. Telegram Message Format

### Individual Event Notification (P1-P3)
```
🔴 PRIORITY EVENT — Comet C/2025 R3 (PANSTARRS) passes perihelion

Comet C/2025 R3 (PANSTARRS) makes its closest approach to the Sun.

👁️ Visibility: Level 1 — Naked eye visible
📅 Event date: 19 Apr 2026
🔗 More info: https://in-the-sky.org/news.php?id=2026_19_CK25R030_100
```

### Daily Digest (P4-P5 + summary)
```
🌌 Astronomical Events — Next 15 Days

Today's events:
• 🟡 Lyrid meteor shower peak — 22 Apr
• 🔵 Moon & Jupiter conjunction — 22 Apr

Upcoming highlights:
• 🟠 Haumea opposition — 23 Apr (Level 4, telescope required)
• ⚪ Mercury-Saturn conjunction — 20 Apr

Total upcoming events: 12
```

### Message Structure with Image
Telegram `sendPhoto` method:
- **Photo:** Thumbnail from in-the-sky.org
- **Caption:** Formatted text as above (MarkdownV2 or HTML)
- **Parse mode:** HTML for rich formatting

---

## 9. File Structure

```
astronomical-events-notify/
├── PLAN.md                    # This document
├── README.md                  # User documentation
├── pyproject.toml             # Python project config + dependencies
├── .env.example               # Environment variable template
│
├── src/
│   ├── __init__.py
│   ├── main.py                # Entry point (CLI + daemon)
│   │
│   ├── rss_fetcher.py         # RSS download & XML parsing
│   ├── event_parser.py        # Title/date extraction, HTML stripping
│   ├── page_scraper.py        # Event page → thumbnail + visibility level
│   ├── classifier.py          # Event type + priority classification
│   ├── db_manager.py          # SQLite operations
│   ├── notifier.py            # Telegram notification logic
│   └── scheduler.py           # Cron/scheduling logic
│
├── config/
│   └── default_config.json    # Default configuration values
│
├── data/
│   └── events.db              # SQLite database (created at runtime)
│
├── logs/
│   └── app.log                # Application log
│
├── tests/
│   ├── test_rss_fetcher.py
│   ├── test_event_parser.py
│   ├── test_classifier.py
│   └── test_notifier.py
│
└── scripts/
    ├── start.sh               # Service startup script
    └── health_check.sh        # Health check script
```

---

## 10. Technology Stack

| Component | Technology | Rationale |
|-----------|------------|-----------|
| Language | Python 3.12+ | Rich ecosystem, easy scripting |
| RSS Parsing | `feedparser` | Robust, handles edge cases |
| Database | SQLite (built-in) | Zero-config, file-based, perfect for single-user |
| HTML Parsing | `beautifulsoup4` + `lxml` | Reliable event page scraping |
| Notification routing | OpenClaw stdout JSON | Multi-channel (Telegram, WhatsApp, etc.) |
| Mastodon | `mastodon.py` / custom client | Optional social media posting |
| Scheduling | `apscheduler` or cron | Flexible scheduling options |
| Logging | Python `logging` module | Structured JSON output |
| Config | `.env` + `pydantic-settings` | Type-safe configuration |

---

## 11. Key Design Decisions

### Why SQLite over a full RDBMS?
- Single-user system, no concurrent writers
- File-based = easy backup (sync with git/Forgejo)
- Zero maintenance, built into Python

### Thumbnail Caching Strategy
- Download and cache thumbnails locally on first fetch
- Store both URL and local file path in DB
- Reduces bandwidth and speeds up notifications
- Cache TTL: 30 days (events are one-time occurrences)

### Deduplication
- `news_id` from RSS guid is the unique key
- On each fetch, only insert items with new `news_id` values
- Old events outside the 15-day window are soft-deleted (keep for history)

### Timezone Handling
- All event dates stored in UTC internally
- Display/conversion to `Europe/Madrid` at notification time
- Configurable timezone in `config` table

---

## 12. Estimated Timeline

| Phase | Duration | Dependencies | Status |
|-------|----------|-------------|
| Phase 1: Core Infrastructure | 2-3 days | None | ✅ Done |
| Phase 2: Event Parsing & Classification | 2-3 days | Phase 1 | ✅ Done |
| Phase 3: Notification System | 1 day | Phase 2 | ✅ Done (Apr 21) |
| Phase 4: Scheduling & Automation | 1-2 days | Phase 3 | ✅ Done |
| Phase 5: Polish & Monitoring | 2-3 days | Phase 4 |

**Total estimated:** 9-14 development days (part-time)

---

### Phase 6: Rich Metadata Extraction & Structured Output
**Goal:** Enrich event data with detailed information from in-the-sky.org pages, store it in the database, and use it for structured output across all channels.

**Motivation:** Current `description` field is too short (46 chars) to produce rich, informative posts. Web pages contain valuable details: peak dates, rates, active periods, visibility regions, radiant constellations, magnitudes, etc.

**Tasks:**
1. [ ] Add 3 new columns to `events` table (`rich_description_en`, `viewing_info_en`, `event_details_json`) + migration logic in `db_manager.py`
2. [ ] Enhance `page_scraper.py` to extract rich metadata from event pages (meteor showers, lunar events, conjunctions)
3. [ ] Update `main.py` pipeline: RSS fetch → enrichment phase (batch scrape with 1s rate limit) → store enriched data
4. [ ] Extend translation pipeline (`translator.py`) for new fields + add columns to `translations` table
5. [ ] Upgrade `post-next-event.py` Mastodon format to use structured card sections ("Zer da?", "Non ikusi?", etc.)
6. [ ] Test end-to-end: fetch → enrich → translate → post, verify JSON schema compatibility across channels
7. [ ] Update timeline estimate and mark Phase 6 as complete

**Deliverable:** Rich metadata stored in DB before translation; structured multi-section posts for Mastodon/Telegram using enriched data.

#### 6.1 Database Schema Extension
Add new columns to the `events` table:

| Column | Type | Description |
|--------|------|-------------|
| `rich_description_en` | TEXT | Detailed description in English ("Zer da?" section) |
| `viewing_info_en` | TEXT | Viewing information in English ("Non ikusi?" section) |
| `event_details_json` | JSON | Structured metadata: peak_date, rate, active_from, active_to, radiant, magnitude, etc. |

**Migration SQL:**
```sql
ALTER TABLE events ADD COLUMN rich_description_en TEXT;
ALTER TABLE events ADD COLUMN viewing_info_en TEXT;
ALTER TABLE events ADD COLUMN event_details_json TEXT;
```

#### 6.2 Event Page Scraper Enhancement (`page_scraper.py`)
Extract detailed information from each event page:

**Meteor Showers:**
- Active period (start/end dates)
- Peak date and time
- Zenithal Hourly Rate (ZHR)
- Radiant constellation and coordinates
- Best viewing hemisphere

**Lunar Events (eclipses, occultations):**
- Event type details (total/partial/penumbral)
- Magnitude
- Duration of key phases
- Visible regions/countries

**Conjunctions:**
- Objects involved
- Separation angle
- Best viewing time window

**General pattern:** Parse the main content `<div>` or article body, extract paragraphs and bullet points.

#### 6.3 Translation Pipeline Extension (`translator.py`)
Extend translation to cover new fields:
- `rich_description_en` → translated to target languages (e.g., Basque `eu`)
- `viewing_info_en` → translated to target languages
- Store translations in the `translations` table with new columns:
  - `translated_rich_description`
  - `translated_viewing_info`

#### 6.4 Mastodon Post Format Upgrade (`post-next-event.py`)
Use enriched data for structured posts:

```
🌠 METEOR KAIOA: η-AQUARIOIDEAK 2026

💫 Zer da?
Eta Aquariideak urteko ekaitzarik oparoenetako bat dira...

📅 Gailurra: Maiatzaren 6a (asteartea)
⏱️ Denbora: ~7 egunera
🔭 Ikusgarritasuna: Begi hutsez, ~50 meteoro/ordutan

🌍 Non ikusi?
Ipar hemisferiotik ikusgarriena. Hegoaldean ere bai...

📖 Informazio gehiago: https://in-the-sky.org/news.php?id=...
```

#### 6.5 RSS Fetch Pipeline Update (`main.py`)
After initial RSS fetch + basic classification, iterate over each event's `event_page_url` and:
1. Fetch the page (with rate limiting — 1s delay between requests)
2. Extract rich metadata using BeautifulSoup
3. Populate `rich_description_en`, `viewing_info_en`, `event_details_json`
4. Store in database
5. Mark as processed so it's not re-scraped unnecessarily

**Rate limit strategy:**
- Max 1 request/second to avoid overwhelming the server
- Batch scrape: fetch all event pages during a dedicated "enrich" phase
- Cache scraped data — only refresh for new events or if `event_details_json` is empty

#### 6.6 Translation Priority
Translate enriched fields **after** enrichment phase completes:
1. Identify events with rich metadata but no translations → `get_events_needing_translation()`
2. Translate `rich_description_en` and `viewing_info_en` to configured target languages
3. Store in `translations` table
4. Use translated versions for channel output

---

## 13. Future Enhancements (Out of Scope v1)

- 📸 Sky map image generation for each event
- 🌦️ Weather-aware notification suppression
- 🗺️ Interactive sky map in web dashboard
- 🔔 Push notification via multiple channels (WhatsApp, email)
- 📊 Historical event tracking and observation logging
- 🤖 AI-generated summaries of complex events
