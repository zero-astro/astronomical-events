# Astronomical Events — Internationalization (i18n) Plan

**Goal:** Translate event titles and descriptions from English to configurable target languages via LLM API, with results cached in SQLite.

**Supported Languages:** `eu` (Basque), `ca` (Catalan), `gl` (Galician), `es` (Spanish), `fr` (French) — configurable per user.

---

## Phase 0: Database Schema Changes

**Goal:** Add translations table and config keys for language selection.

### Tasks
- [ ] **0.1** Create `translations` table in SQLite via `_create_tables()` migration in `db_manager.py`:

```sql
CREATE TABLE IF NOT EXISTS translations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    news_id TEXT NOT NULL,
    source_lang TEXT DEFAULT 'en',
    target_lang TEXT NOT NULL,
    translated_title TEXT,
    translated_description TEXT,
    provider TEXT DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(news_id, target_lang)  -- one translation per language per event
);
```

- [ ] **0.2** Add indexes for fast lookup:

```sql
CREATE INDEX IF NOT EXISTS idx_translations_news_id ON translations(news_id);
CREATE INDEX IF NOT EXISTS idx_translations_target_lang ON translations(target_lang);
```

- [ ] **0.3** Add `target_languages` config key to `config` table (default: `"eu"`):

```sql
INSERT OR REPLACE INTO config (key, value) VALUES ('target_languages', '["eu"]');
```

- [ ] **0.4** Add DB methods in `db_manager.py`:
  - `get_translation(news_id, target_lang)` → returns row or None
  - `insert_or_update_translation(news_id, target_lang, translated_title, translated_description, provider)`
  - `get_events_needing_translation(target_langs)` → events without translations for given languages

---

## Phase 1: Translation Provider Module (`src/translate.py`)

**Goal:** Batch translation via OpenAI-compatible API with caching.

### Tasks
- [ ] **1.1** Create `src/translate.py` with provider abstraction:

```python
# Supported providers: lm-studio, ollama, openai
PROVIDERS = {
    "lm-studio": {"api_base": "http://localhost:1234/v1", "model": "local-model"},
    "ollama":    {"api_base": "http://localhost:11434/v1", "model": None},  # user-specified
    "openai":    {"api_base": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
}
```

- [ ] **1.2** Implement `translate_batch_openai(titles, config)` function:
  - Accepts list of English titles (batch up to 20 per call)
  - Constructs prompt with target language instruction
  - Sends single request to OpenAI-compatible API
  - Parses response (one translation per line)
  - Returns list of translated strings

- [ ] **1.3** Implement `translate_event(event, config)` function:
  - Translates both title and description
  - Handles partial failures gracefully
  - Returns dict with `translated_title` and `translated_description`

- [ ] **1.4** Add prompt templates for each language in `src/translate.py`:

```python
TRANSLATION_PROMPTS = {
    "eu": """Translate the following English astronomical event titles to Basque (Euskara).
Return ONLY the translations, one per line, in the same order. Do not add any explanation or numbering.

{titles}

Translations:""",
    "ca": """Translate the following English astronomical event titles to Catalan (Català).
...
```

- [ ] **1.5** Add rate limiting: max 1 batch per 3 seconds between API calls

---

## Phase 2: Integration into RSS Fetch Pipeline

**Goal:** After parsing events, trigger translation if configured.

### Tasks
- [ ] **2.1** Modify `scripts/main.py` fetch flow:
  - After RSS items are parsed and stored in DB (existing pipeline)
  - Check if `target_languages` config is set and non-empty
  - Query DB for events without translations for target languages
  - Call translation module to translate missing ones

- [ ] **2.2** Create `src/translator.py` as the orchestration layer:
  - `translate_missing_events(db, config)` → translates all untranslatable events in batch
  - Groups events by language (one batch per target language)
  - Stores results via DB manager methods from Phase 0

- [ ] **2.3** Add CLI command to trigger translation manually:

```bash
python3 scripts/main.py translate --lang eu    # Translate all missing to Basque
python3 scripts/main.py translate --lang eu,ca  # Translate to multiple languages
```

- [ ] **2.4** Integrate into scheduled fetch (mandatory):
  - All events fetched from RSS are automatically translated — no manual trigger needed
  - Translation runs immediately after RSS parsing, before notification dispatch
  - If translation fails or is unavailable, event is still stored with original English text

---

## Phase 3: Notification Formatting Changes

**Goal:** Output events in configured target language instead of English.

### Tasks
- [ ] **3.1** Modify `_format_event_for_output()` in `src/notification.py`:
  - Check if translation exists for the event + target language
  - If yes, use translated title/description
  - If no, fall back to original English text (with `[EN]` prefix)

- [ ] **3.2** Update notification JSON schema:
  ```json
  {
    "news_id": "...",
    "title_original": "136108 Haumea at opposition",
    "title_translated": "136108 Haumea aurkabetan dago",
    "target_lang": "eu"
  }
  ```

- [ ] **3.3** Update `_build_human_readable()` to use translated text:
  - Replace `event.title` with `translated_title` when available
  - Fall back to original English if no translation exists

- [ ] **3.4** Update Mastodon formatting (`mastodon_client.py`):
  - Use translated title for social media posts
  - Keep original English as fallback

---

## Phase 4: Config System Updates

**Goal:** Allow users to configure target languages and translation provider.

### Tasks
- [ ] **4.1** Update `.env.example`:

```bash
# i18n Configuration
TRANSLATION_ENABLED=true
TRANSLATION_PROVIDER=lm-studio          # lm-studio | ollama | openai
TRANSLATION_API_BASE=http://localhost:1234/v1
TRANSLATION_MODEL=local-model           # LM Studio always uses "local-model"
TARGET_LANGUAGES=eu,ca                  # comma-separated list of target languages
```

- [ ] **4.2** Update `config/astronomical_events.json` (or equivalent config file):
  ```json
  {
    "translation": {
      "enabled": true,
      "provider": "lm-studio",
      "api_base": "http://localhost:1234/v1",
      "model": "local-model"
    },
    "target_languages": ["eu"]
  }
  ```

- [ ] **4.3** Add CLI flags to `scripts/main.py`:
  - `--set-lang eu` — set target language(s)
  - `--show-langs` — show current configuration
  - `--translate-all` — translate all existing events in DB for configured languages (one-time backfill)

---

## Phase 5: Testing & Validation

**Goal:** Ensure translations are accurate and pipeline works end-to-end.

### Tasks
- [ ] **5.1** Create `tests/test_translate.py`:
  - Test batch translation with mock API responses
  - Test prompt formatting for each language
  - Test rate limiting behavior

- [ ] **5.2** Create `tests/test_i18n_integration.py`:
  - End-to-end test: fetch RSS → parse → translate → notify
  - Verify translated events appear in notifications
  - Test fallback to English when no translation exists

- [ ] **5.3** Manual validation:
  - Run full pipeline with LM Studio running
  - Verify translations for all target languages (eu, ca, gl, es, fr)
  - Check DB for correct storage and retrieval of translations
  - Test edge cases: empty titles, special characters, very long descriptions

- [ ] **5.4** Performance testing:
  - Measure translation latency per batch
  - Verify cache hit rate (translations should be cached, not re-translated)
  - Check DB query performance with indexes

---

## File Structure Changes

```
astronomical-events/
├── src/
│   ├── translate.py          # NEW: Translation provider module
│   ├── translator.py         # NEW: Orchestration layer (batch + DB integration)
│   ├── db_manager.py         # MODIFIED: Add translations table & methods
│   ├── notification.py       # MODIFIED: Use translated text in output
│   └── mastodon_client.py    # MODIFIED: Use translated title for posts
├── tests/
│   ├── test_translate.py     # NEW: Unit tests for translation module
│   └── test_i18n_integration.py  # NEW: End-to-end i18n tests
├── config/
│   └── astronomical_events.json  # MODIFIED: Add translation config
├── .env.example              # MODIFIED: Add i18n variables
└── docs/
    └── I18N_PLAN.md          # THIS FILE
```

---

## Estimated Timeline

| Phase | Duration | Dependencies |
|-------|----------|-------------|
| Phase 0: DB Schema | 0.5 days | None |
| Phase 1: Translation Provider | 1-2 days | Phase 0 |
| Phase 2: Pipeline Integration | 1 day | Phase 1 |
| Phase 3: Notification Formatting | 0.5-1 day | Phase 2 |
| Phase 4: Config System | 0.5 days | Phase 3 |
| Phase 5: Testing & Validation | 1-2 days | All phases |

**Total estimated:** 4-7 development days (part-time)

---

## Notes

- LM Studio must be running on `http://localhost:1234` with a loaded model before translation can work
- Ollama alternative: change provider to `ollama` and set appropriate API base (`http://localhost:11434/v1`)
- OpenAI API alternative: change provider to `openai` and add `OPENAI_API_KEY` env var
- Translations are cached in DB — each event is translated only once per target language
