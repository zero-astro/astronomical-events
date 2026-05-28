# Mastodon Posting — Setup & Troubleshooting

## Config File Location

Mastodon credentials go in `config/mastodon.json` relative to the workspace dir:

```json
{
  "mastodon": {
    "instance_url": "https://mastodon.eus",
    "access_token": "your_access_token_here",
    "client_key": "optional_client_key",
    "client_secret": "optional_client_secret"
  }
}
```

The `mastodon_client.py` resolves the workspace path by walking up from `src/` to find a `config/mastodon.json`. This works when running interactively but **fails in cron/scheduler contexts** where no env var is set.

## Required Environment Variable for Cron/Scheduler

When posting via `post-next-event.py` or `post-today-events.py`, you MUST set:

```bash
OPENCLAW_WORKSPACE_DIR=/home/urtzai/.hermes/skills/astronomical-events
```

Without it, the config file is not found and posting fails silently.

### Example cron command:
```bash
OPENCLAW_WORKSPACE_DIR=/home/urtzai/.hermes/skills/astronomical-events \
  cd /home/urtzai/.hermes/skills/astronomical-events && .venv/bin/python scripts/post-next-event.py
```

## Mastodon API Token Setup

1. Go to your Mastodon instance → Settings → Development → Personal access tokens
2. Generate new token with scope: `write:statuses`
3. Copy the token and paste into `config/mastodon.json`

Optional: client_key/client_secret for pre-registered apps (skip if using personal access token only).

## Dependencies

Mastodon posting requires `mastodon.py`:
```bash
cd /home/urtzai/.hermes/skills/astronomical-events && .venv/bin/pip install mastodon.py
```

This is NOT in the base `pyproject.toml` — install separately.

## Common Errors

### "Mastodon config not found"
→ Set `OPENCLAW_WORKSPACE_DIR` env var (see above) or verify `config/mastodon.json` exists at the resolved path.

### "Mastodon authentication failed"
→ Check access_token is valid and has `write:statuses` scope. Regenerate if expired.

### Post truncated to 500 chars
→ The script auto-truncates descriptions that exceed Mastodon's limit, preserving header + footer. If the description is too long, it gets removed entirely (header/footer always preserved).
