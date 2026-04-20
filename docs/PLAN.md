# Astronomical Events Notification System

## 1. Overview

A background service that periodically fetches astronomical event data from **in-the-sky.org** RSS feed, stores it in a SQLite database, classifies events by priority, and sends notifications to the user via Telegram.

### Key Requirements
- Fetch RSS: `https://in-the-sky.org/rss.php?feed=dfan&latitude=43.139006&longitude=-2.966625&timezone=Europe/Madrid`
- Store in SQLite on the server
- Display events within a **15-day window**
- Classify by priority (low → high)
- Notify via Telegram with title, thumbnail, description, and visibility level

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
                                          ┌───────▼───────┐
                                          │ Telegram API  │
                                          │ (send message)│
                                          └───────────────┘
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

### Phase 2: Event Parsing & Classification
**Goal:** Extract structured data from each event and classify by priority.

**Tasks:**
1. [ ] Implement title parser (extract event date + event name)
2. [ ] HTML description → plain text converter
3. [ ] Event page scraper:
   - Fetch thumbnail URL (`style=hugeteaser`)
   - Parse visibility level icon and alt text
4. [ ] Event type classifier (regex/pattern matching on title)
5. [ ] Priority tier assignment based on classification rules
6. [ ] Update database with parsed fields

**Deliverable:** All events in DB have `event_type`, `priority`, `visibility_level`, and `thumbnail_url`.

---

### Phase 3: Notification System
**Goal:** Send Telegram notifications for new and high-priority events.

**Tasks:**
1. [ ] Implement Telegram bot / user client (using API key + chat_id)
2. [ ] Message formatter:
   - Title with emoji based on priority tier
   - Thumbnail image as attachment
   - Short description
   - Visibility level icon + text
   - Link to full event page
3. [ ] Notification logic:
   - Immediate notification for P1-P2 events
   - Batched notification for P3-P4 events
   - Daily digest (P5 + summary of all upcoming)
4. [ ] Mark events as `is_notified = true` after sending
5. [ ] Error handling and retry logic

**Deliverable:** Telegram notifications sent for new astronomical events with rich formatting.

---

### Phase 4: Scheduling & Automation
**Goal:** Fully automated background service.

**Tasks:**
1. [ ] Implement cron-like scheduling (hourly RSS fetch)
2. [ ] Daily digest job (e.g., at 08:00 Europe/Madrid)
3. [ ] Systemd service or supervisor config for persistence
4. [ ] Logging with rotation (structured JSON logs)
5. [ ] Health check endpoint / CLI command
6. [ ] Configuration via environment variables or `.env` file

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
| Telegram | `python-telegram-bot` v20+ | Well-maintained, async support |
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

| Phase | Duration | Dependencies |
|-------|----------|-------------|
| Phase 1: Core Infrastructure | 2-3 days | None |
| Phase 2: Event Parsing & Classification | 2-3 days | Phase 1 |
| Phase 3: Notification System | 2-3 days | Phase 2 |
| Phase 4: Scheduling & Automation | 1-2 days | Phase 3 |
| Phase 5: Polish & Monitoring | 2-3 days | Phase 4 |

**Total estimated:** 9-14 development days (part-time)

---

## 13. Future Enhancements (Out of Scope v1)

- 📸 Sky map image generation for each event
- 🌦️ Weather-aware notification suppression
- 🗺️ Interactive sky map in web dashboard
- 🔔 Push notification via multiple channels (WhatsApp, email)
- 📊 Historical event tracking and observation logging
- 🤖 AI-generated summaries of complex events
