"""Telegram notification system - Sends astronomical event notifications via Telegram.

Uses python-telegram-bot library to send formatted messages with thumbnails
to a configured chat ID. Handles rate limits, retries, and errors gracefully.
"""

import io
import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def load_telegram_config() -> dict:
    """Load Telegram credentials from .env file or environment variables.
    
    Returns:
        Dict with 'bot_token' and 'chat_id', or empty dict if not configured.
    """
    # Try environment variables first
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    
    # Fallback to .env file in project root
    if not bot_token or not chat_id:
        env_path = Path(__file__).parent.parent / ".env"
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key == "TELEGRAM_BOT_TOKEN":
                        bot_token = value
                    elif key == "TELEGRAM_CHAT_ID":
                        chat_id = value
    
    if not bot_token or not chat_id:
        logger.warning("Telegram config missing (need TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)")
        return {}
    
    return {"bot_token": bot_token, "chat_id": chat_id}


def _format_telegram_message(event: dict) -> str:
    """Format a single event into Telegram HTML message.
    
    Args:
        event: Dict with event data (from _format_event_for_output)
        
    Returns:
        Formatted HTML string for Telegram
    """
    emoji = event.get("priority_emoji", "🌟")
    time_label = event.get("time_label", "unknown")
    title = event["title"]
    vis = ""
    if "visibility_label" in event:
        vis = f"\n🔭 <i>{event['visibility_label']}</i>"
    
    priority_map = {1: "L1 (Lehentasun oso altua)", 2: "L2 (Lehentasun altua)", 
                    3: "L3 (Lehentasun baxua)", 4: "L4 (Lehentasun oso baxua)",
                    5: "L5 (Informazioa)"}
    priority_label = priority_map.get(event.get("priority", 5), f"L{event.get('priority', '?')}")
    
    message = (
        f"{emoji} <b>{title}</b>\n"
        f"📅 {time_label}\n"
        f"{'🟡' if event.get('priority') == 3 else '⚪'} {priority_label}"
        f"{vis}"
    )
    
    return message


def _format_telegram_digest(events: list) -> str:
    """Format multiple events into a compact Telegram digest message.
    
    Args:
        events: List of event dicts
        
    Returns:
        Formatted HTML string for Telegram digest
    """
    lines = ["<b>🌌 Egungo Laburpena</b>"]
    
    priority_map = {1: "🔴 L1", 2: "🟠 L2", 3: "🟡 L3", 4: "🔵 L4", 5: "⚪ L5"}
    
    for event in events[:10]:  # Limit to 10 events per digest
        emoji = event.get("priority_emoji", "🌟")
        time_label = event.get("time_label", "?")
        title = event["title"]
        priority_label = priority_map.get(event.get("priority", 5), f"L{event.get('priority', '?')}")
        
        lines.append(f"{emoji} {title}")
    
    if len(events) > 10:
        lines.append(f"\n... eta {len(events) - 10} gertaera gehiago")
    
    return "\n".join(lines)


def _download_thumbnail(url: str, cache_dir: Optional[str] = None) -> Optional[bytes]:
    """Download thumbnail image from URL.
    
    Args:
        url: Image URL to download
        cache_dir: Directory to cache images locally
        
    Returns:
        Image bytes or None if download fails
    """
    try:
        import requests
    except ImportError:
        logger.warning("requests library not installed, cannot download thumbnails")
        return None
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        # Cache locally if cache_dir provided
        if cache_dir:
            import hashlib
            hash_key = hashlib.md5(url.encode()).hexdigest()[:16]
            cache_path = Path(cache_dir) / f"{hash_key}.jpg"
            
            if not cache_path.exists():
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                with open(cache_path, "wb") as f:
                    f.write(response.content)
        
        return response.content
    
    except Exception as e:
        logger.warning(f"Failed to download thumbnail from {url}: {e}")
        return None


def send_telegram_notification(config: dict, event: dict, use_photo: bool = True) -> bool:
    """Send a single event notification via Telegram.
    
    Args:
        config: Dict with 'bot_token' and 'chat_id'
        event: Event dict (from _format_event_for_output)
        use_photo: If True, send as photo with caption; otherwise as text
        
    Returns:
        True if sent successfully, False otherwise
    """
    try:
        from telegram import Bot
        from telegram.error import TelegramError, TimedOut, BadRequest
    except ImportError:
        logger.warning("python-telegram-bot not installed")
        return False
    
    bot_token = config.get("bot_token", "")
    chat_id = config.get("chat_id", "")
    
    if not bot_token or not chat_id:
        logger.error("Telegram config missing (bot_token or chat_id)")
        return False
    
    message = _format_telegram_message(event)
    
    # Add event page link
    if event.get("event_page_url"):
        message += f"\n\n🌍 <a href=\"{event['event_page_url']}\">Iruzkinak</a>"
    
    try:
        bot = Bot(token=bot_token)
        
        if use_photo and event.get("thumbnail_url"):
            # Download thumbnail
            image_data = _download_thumbnail(event["thumbnail_url"])
            
            if image_data:
                # Send as photo with caption
                bio = io.BytesIO(image_data)
                bot.send_photo(
                    chat_id=chat_id,
                    photo=bio,
                    caption=message,
                    parse_mode="HTML",
                    disable_notification=True
                )
                logger.info(f"Telegram notification sent (photo): {event['title']}")
                return True
            else:
                logger.warning("Failed to download thumbnail, sending as text instead")
        
        # Fallback: send as text message
        bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode="HTML",
            disable_notification=True,
            disable_web_page_preview=False  # Show link preview for event_page_url
        )
        logger.info(f"Telegram notification sent (text): {event['title']}")
        return True
        
    except (TelegramError, TimedOut) as e:
        logger.error(f"Telegram send failed: {e}")
        return False
    finally:
        try:
            bot.close()
        except Exception:
            pass


def send_telegram_digest(config: dict, events: list) -> bool:
    """Send a digest of multiple events via Telegram.
    
    Args:
        config: Dict with 'bot_token' and 'chat_id'
        events: List of event dicts
        
    Returns:
        True if sent successfully, False otherwise
    """
    try:
        from telegram import Bot
        from telegram.error import TelegramError, TimedOut
    except ImportError:
        logger.warning("python-telegram-bot not installed")
        return False
    
    bot_token = config.get("bot_token", "")
    chat_id = config.get("chat_id", "")
    
    if not bot_token or not chat_id:
        logger.error("Telegram config missing (bot_token or chat_id)")
        return False
    
    message = _format_telegram_digest(events)
    
    try:
        bot = Bot(token=bot_token)
        
        bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode="HTML",
            disable_notification=True
        )
        logger.info(f"Telegram digest sent ({len(events)} events)")
        return True
        
    except (TelegramError, TimedOut) as e:
        logger.error(f"Telegram digest send failed: {e}")
        return False
    finally:
        try:
            bot.close()
        except Exception:
            pass
