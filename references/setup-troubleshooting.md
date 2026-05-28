# Astronomical Events — Setup & Troubleshooting

## First-Time Setup

The skill ships with `pyproject.toml` but no pre-installed venv.

```bash
cd /home/urtzai/.hermes/skills/astronomical-events
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Dependencies: `feedparser`, `beautifulsoup4`, `lxml`, `apscheduler`, `pydantic-settings`.

All commands must use `.venv/bin/python` (system pip may not be available).

## Common Errors

### `ModuleNotFoundError: feedparser`
→ Run `.venv/bin/pip install -e .`

### `FastAPI not installed. Install with: pip install fastapi uvicorn`
→ Only the `dashboard` command needs FastAPI. All other commands (`fetch`, `status`, `translate`) work without it after the lazy-import fix in `main.py`.

### `SyntaxError: f-string: unmatched '[' (line 133)`
The file uses nested quotes in f-strings that break on Python 3.12+. Fixed by changing inner double quotes to single quotes inside f-strings:
```python
# Bad (Python 3.12+):
logger.warning(f"Could not parse date from title: {item["title"]}")

# Good:
logger.warning(f'Could not parse date from title: {item["title"]}')
```

### Translation is slow / timing out
Translation runs sequentially with a 5-second delay between requests (to avoid LM Studio CPU timeouts). For N events, expect ~N × (LLM inference time + 5s).

To speed up, edit `src/translator.py` line ~128:
```python
delay = 1  # was 5
```

### Circuit breaker opens during translation
The translator health-checks LM Studio at `http://192.168.16.20:1234/api/health`. If the local LLM isn't running, it skips translations and opens a circuit breaker (5-minute cooldown).

Fix: Start LM Studio first, then retry translation.

## Provider Configuration

Translation providers (all use OpenAI-compatible API):
- `lm-studio` — default, at `http://192.168.16.20:1234/v1`, model `qwen3.6-35b-a3b`
- `ollama` — at `http://localhost:11434/v1`, user-specified model
- `openai` — at `https://api.openai.com/v1`, model `gpt-4o-mini`

Override via environment variables:
```bash
TRANSLATION_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

Or provider-specific overrides:
```bash
TRANSLATION_LM_STUDIO_API_BASE=http://localhost:1234/v1
TRANSLATION_MODEL=my-custom-model
```

## RSS Feed

Default URL (Gasteiz/Vitoria coordinates):
```
https://in-the-sky.org/rss.php?feed=dfan&latitude=43.1417601&longitude=-2.9622358&timezone=Europe/Madrid
```

Override via `RSS_URL` in `.env`.

## Database

SQLite at `data/events.db`. Tables: `events`, `translations`, `config`, `fetch_history`.

Query example (use with caution):
```bash
.venv/bin/python -c "
import sqlite3
conn = sqlite3.connect('data/events.db')
conn.row_factory = sqlite3.Row
for r in conn.execute('SELECT * FROM events ORDER BY event_date DESC LIMIT 5'):
    print(dict(r))
"
```
