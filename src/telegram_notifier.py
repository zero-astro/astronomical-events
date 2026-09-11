"""Telegram notification sender using Telegram Bot API with provider routing.

Routes notifications through providers defined in config/telegram_providers.json.
Providers are tried in order — first success wins, then moves to next on failure.

Environment variables expected (set in .env or system env):
  HERMES_TELEGRAM_BOT_TOKEN     — bot token for primary provider
  HERMES_TELEGRAM_CHAT_ID       — chat ID (e.g. -1003760960975)
  HERMES_TELEGRAM_FALLBACK_TOKEN — optional fallback bot token

Provider config (config/telegram_providers.json):
  Each provider has id, name, enabled flag, base_url, and env var names for
  bot_token and chat_id. Add/remove providers freely.

Usage:
  from src.telegram_notifier import TelegramNotifier
  notifier = TelegramNotifier(workspace_dir="/path/to/project")
  notifier.send_event(event_dict)
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger(__name__)


class TelegramProvider:
    """A single Telegram bot provider with token and chat ID from env vars."""

    def __init__(self, config: Dict[str, Any], workspace_dir: str):
        self.id = config["id"]
        self.name = config.get("name", self.id)
        self.enabled = config.get("enabled", True)
        self.base_url = config["base_url"]
        self.api_url = f"{self.base_url}/bot"

        # Resolve token and chat_id from env vars
        token_env = config["bot_token_env"]
        chat_env = config["chat_id_env"]

        self.bot_token = os.environ.get(token_env, "")
        self.chat_id = os.environ.get(chat_env, "")

        if not self.bot_token:
            log.warning("Provider %s: missing env var %s — disabled", self.id, token_env)
            self.enabled = False
            return
        if not self.chat_id:
            log.warning("Provider %s: missing env var %s — disabled", self.id, chat_env)
            self.enabled = False
            return

        self.api_url += self.bot_token

    def send(self, text: str, parse_mode: str = "Markdown", disable_web_page_preview: bool = True) -> bool:
        """Send a message to the chat. Returns True on success."""
        if not self.enabled:
            return False
        try:
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": disable_web_page_preview,
            }
            resp = requests.post(
                f"{self.api_url}/sendMessage",
                json=payload,
                timeout=15,
            )
            if resp.status_code == 200:
                log.info("Sent via provider %s (%s)", self.id, self.name)
                return True
            else:
                log.error("Provider %s HTTP %s: %s", self.id, resp.status_code, resp.text[:200])
                return False
        except requests.exceptions.Timeout:
            log.error("Provider %s timeout", self.id)
            return False
        except requests.exceptions.ConnectionError as exc:
            log.error("Provider %s connection error: %s", self.id, exc)
            return False
        except Exception as exc:
            log.error("Provider %s unexpected error: %s", self.id, exc)
            return False


class TelegramNotifier:
    """Route event notifications through configured Telegram providers."""

    def __init__(self, workspace_dir: Optional[str] = None):
        if workspace_dir is None:
            workspace_dir = os.environ.get("WORKSPACE_DIR", "")
        self.workspace_dir = workspace_dir or str(Path(__file__).resolve().parent.parent)
        self.providers: List[TelegramProvider] = self._load_providers()
        log.info("Telegram notifier loaded %d provider(s)", len(self.providers))

    def _load_providers(self) -> List[TelegramProvider]:
        """Load providers from config/telegram_providers.json."""
        config_path = Path(self.workspace_dir) / "config" / "telegram_providers.json"

        try:
            with open(config_path, "r") as f:
                config = json.load(f)
        except FileNotFoundError:
            log.error("Telegram providers config not found: %s", config_path)
            return []
        except json.JSONDecodeError as exc:
            log.error("Invalid JSON in telegram_providers.json: %s", exc)
            return []

        providers = []
        for pcfg in config.get("providers", []):
            if not pcfg.get("enabled", True):
                continue
            p = TelegramProvider(pcfg, self.workspace_dir)
            if p.enabled:
                providers.append(p)
        return providers

    def send_event(self, event: Dict[str, Any]) -> bool:
        """Send an astronomical event notification through the first available provider.
        Returns True if at least one provider succeeded."""
        text = self._format_message(event)
        return self._send_with_fallback(text)

    def send_text(self, text: str) -> bool:
        """Send arbitrary text through the first available provider."""
        return self._send_with_fallback(text)

    def send_event_with_url(self, event: Dict[str, Any], embed_preview: bool = False) -> bool:
        """Send event with link preview enabled (for URL-rich messages)."""
        text = self._format_message(event)
        return self._send_with_fallback(text, disable_web_page_preview=not embed_preview)

    def _send_with_fallback(self, text: str, disable_web_page_preview: bool = True) -> bool:
        """Try providers in order — first success wins."""
        for provider in self.providers:
            if provider.send(text, disable_web_page_preview=disable_web_page_preview):
                return True
        log.error("All Telegram providers failed — no messages sent")
        return False

    @staticmethod
    def _format_message(event: Dict[str, Any]) -> str:
        """Format an event dict into a Telegram Markdown message.

        Format:
          🔭 *<translated_title>*

          📅 <date>

          <brief description>

          🔭 *Behatzeko:*
          <viewing info>

          🔗 <url>

          🤖 *ZERO espazio digitaletik*
        """
        lines = []

        # Title
        title = event.get("translated_title") or event.get("title", "")
        if title:
            lines.append(f"🔭 *{title}*")
            lines.append("")

        # Date
        date_str = event.get("translated_date") or event.get("date", "") or event.get("event_date", "")
        if date_str:
            lines.append(f"📅 {date_str}")
            lines.append("")

        # Description (brief)
        desc = event.get("translated_description") or event.get("description", "") or event.get("rich_description", "")
        if desc:
            # Telegram max 4096 chars; keep it reasonable
            lines.append(desc[:500])
            lines.append("")

        # Viewing info
        viewing = event.get("translated_viewing_info") or event.get("viewing_info", "")
        if viewing:
            lines.append(f"🔭 *Behatzeko:*")
            lines.append(viewing[:300])
            lines.append("")

        # URL
        url = event.get("url") or event.get("event_page_url") or event.get("event_page", "")
        if url:
            lines.append(f"🔗 {url}")

        # Footer
        lines.append("")
        lines.append("🤖 *ZERO espazio digitaletik*")

        return "\n".join(lines)
