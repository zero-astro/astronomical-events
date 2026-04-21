"""Notification system - Telegram notifications for astronomical events.

Handles:
- P1/P2: Immediate individual notifications with images
- P3: Batched notifications (up to 5 per message)
- P4/P5: Daily digest of all upcoming events
- Thumbnail attachment support
- Retry logic with exponential backoff
"""

import os
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

try:
    from telegram import Bot
    from telegram.error import TelegramError, TimedOut, BadRequest
except ImportError:
    raise ImportError(
        "python-telegram-bot is required. Install with: pip install python-telegram-bot"
    )

from db_manager import DatabaseManager, Event
from classifier import get_priority_emoji, format_visibility_label

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2


class NotificationError(Exception):
    """Raised when notification sending fails."""
    pass


def _get_bot(token: str) -> Bot:
    return Bot(token=token, parse_mode="HTML")


def _send_with_retry(bot: Bot, func, *args, **kwargs):
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except TimedOut as e:
            last_error = e
            delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            logger.warning(f"Timeout on attempt {attempt}/{MAX_RETRIES}, retrying in {delay}s")
            time.sleep(delay)
        except BadRequest as e:
            raise NotificationError(f"Bad request: {e.message}") from e
        except TelegramError as e:
            last_error = e
            delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            logger.warning(f"Telegram error on attempt {attempt}/{MAX_RETRIES}: {e}, retrying in {delay}s")
            time.sleep(delay)

    raise NotificationError(
        f"All {MAX_RETRIES} retries failed. Last error: {last_error}"
    ) from last_error


def _format_event_message(event: Event, compact: bool = False) -> str:
    emoji = get_priority_emoji(event.priority)
    priority_label = f"P{event.priority}"

    today = datetime.now()
    event_date = event.event_date
    delta_days = (event_date.date() - today.date()).days

    if delta_days < 0:
        date_str = "Passed"
    elif delta_days == 0:
        date_str = "Today!"
    elif delta_days == 1:
        date_str = "Tomorrow"
    else:
        date_str = f"{event_date.strftime('%d %b')} ({delta_days} days)"

    vis_str = ""
    if event.visibility_level:
        vis_str = f"\nVisibility: {format_visibility_label(event.visibility_level)}"

    desc_str = ""
    if not compact and event.description:
        desc_text = event.description[:200]
        if len(event.description) > 200:
            desc_text += "..."
        desc_str = f"\n\n{desc_text}"

    link_str = ""
    if event.event_page_url:
        link_str = f'\n\n<a href="{event.event_page_url}">View details</a>'

    message = (
        f"*{priority_label}* — {event.title}\n"
        f"{date_str}{vis_str}{desc_str}{link_str}"
    )
    return message


def _send_event_with_image(
    bot: Bot, chat_id: str, event: Event, message_text: str
) -> bool:
    if event.thumbnail_url:
        try:
            _send_with_retry(
                bot,
                bot.send_photo,
                chat_id=chat_id,
                photo=event.thumbnail_url,
                caption=message_text,
                parse_mode="HTML",
                disable_notification=event.priority <= 2,
            )
            logger.info(f"Sent notification with image for: {event.title[:50]}")
            return True
        except NotificationError as e:
            logger.warning(f"Failed to send photo ({event.thumbnail_url}): {e}")
        except Exception as e:
            logger.warning(f"Photo send failed, falling back to text: {e}")

    try:
        _send_with_retry(
            bot,
            bot.send_message,
            chat_id=chat_id,
            text=message_text,
            parse_mode="HTML",
            disable_notification=event.priority <= 2,
            disable_web_page_preview=True,
        )
        logger.info(f"Sent notification (text only) for: {event.title[:50]}")
        return True
    except NotificationError as e:
        logger.error(f"Failed to send text notification: {e}")
        return False


def _send_batch_notification(
    bot: Bot, chat_id: str, events: list[Event], batch_label: str
) -> int:
    if not events:
        return 0

    lines = [f"*{batch_label}* — {len(events)} event(s)\n"]
    for i, event in enumerate(events[:5], 1):
        emoji = get_priority_emoji(event.priority)
        date_str = event.event_date.strftime("%d %b")
        lines.append(f"{i}. {emoji} {date_str} — {event.title}")

    message_text = "\n".join(lines)

    try:
        _send_with_retry(
            bot,
            bot.send_message,
            chat_id=chat_id,
            text=message_text,
            parse_mode="HTML",
            disable_notification=True,
        )
        logger.info(f"Sent batch notification ({len(events)} events): {batch_label}")
        return len(events)
    except NotificationError as e:
        logger.error(f"Failed to send batch notification: {e}")
        return 0


def _send_daily_digest(
    bot: Bot, chat_id: str, all_events: list[Event]
) -> int:
    if not all_events:
        return 0

    groups = {}
    for event in all_events:
        p = event.priority
        if p not in groups:
            groups[p] = []
        groups[p].append(event)

    lines = [f"*Daily Sky Digest* — {datetime.now().strftime('%d %b %Y')}"]
    lines.append(f"Total upcoming events: {len(all_events)}\n")

    for p in sorted(groups.keys()):
        emoji = get_priority_emoji(p)
        count = len(groups[p])
        lines.append(f"{emoji} *P{p}* ({count}):")

        for event in groups[p][:3]:
            date_str = event.event_date.strftime("%d %b")
            lines.append(f"  - {date_str}: {event.title}")

        if len(groups[p]) > 3:
            lines.append(f"  ... and {len(groups[p]) - 3} more")

    message_text = "\n".join(lines)

    try:
        _send_with_retry(
            bot,
            bot.send_message,
            chat_id=chat_id,
            text=message_text,
            parse_mode="HTML",
            disable_notification=True,
        )
        logger.info(f"Sent daily digest ({len(all_events)} events)")
        return len(all_events)
    except NotificationError as e:
        logger.error(f"Failed to send daily digest: {e}")
        return 0


def send_notifications(config: dict) -> dict:
    """Main notification dispatch function.

    Processes unnotified events and sends appropriate Telegram notifications.

    Args:
        config: Configuration dict with telegram_bot_token, telegram_chat_id, etc.

    Returns:
        Dict with stats: {sent_immediate, sent_batch, sent_digest, failed}
    """
    bot_token = config.get("telegram_bot_token")
    chat_id = config.get("telegram_chat_id")

    if not bot_token or not chat_id:
        logger.warning("Telegram credentials not configured. Skipping notifications.")
        return {"sent_immediate": 0, "sent_batch": 0, "sent_digest": 0, "failed": 0}

    db = DatabaseManager(config["db_path"])

    try:
        bot = _get_bot(bot_token)

        # Verify bot is reachable
        try:
            bot.get_me()
            logger.info("Telegram bot authenticated successfully")
        except TelegramError as e:
            logger.error(f"Failed to authenticate Telegram bot: {e}")
            return {"sent_immediate": 0, "sent_batch": 0, "sent_digest": 0, "failed": 0}

        stats = {"sent_immediate": 0, "sent_batch": 0, "sent_digest": 0, "failed": 0}

        # Get unnotified events (P1-P3)
        all_unnotified = db.get_unnotified_events(priority_max=3)

        if not all_unnotified:
            logger.info("No new high-priority events to notify.")
            return stats

        logger.info(f"Found {len(all_unnotified)} unnotified events (P1-P3)")

        # Separate by priority tier
        p1_events = [e for e in all_unnotified if e.priority == 1]
        p2_events = [e for e in all_unnotified if e.priority == 2]
        p3_events = [e for e in all_unnotified if e.priority == 3]

        # P1/P2: Immediate individual notifications with images
        immediate_events = p1_events + p2_events
        for event in immediate_events:
            message_text = _format_event_message(event, compact=False)
            success = _send_event_with_image(bot, chat_id, event, message_text)

            if success:
                db.mark_as_notified(event.news_id)
                stats["sent_immediate"] += 1
            else:
                stats["failed"] += 1

        # P3: Batched notifications (up to 5 per message)
        if p3_events:
            batch_size = 5
            for i in range(0, len(p3_events), batch_size):
                batch = p3_events[i:i + batch_size]
                sent = _send_batch_notification(bot, chat_id, batch, "P3 Medium Priority")

                for event in batch:
                    db.mark_as_notified(event.news_id)
                    stats["sent_batch"] += 1 if sent > 0 else 0

        # P4/P5: Daily digest (all upcoming events)
        window_days = int(config.get("window_days", "15"))
        all_upcoming = db.get_upcoming_events(days=window_days)

        if all_upcoming:
            _send_daily_digest(bot, chat_id, all_upcoming)
            stats["sent_digest"] = len(all_upcoming)

    except Exception as e:
        logger.error(f"Notification dispatch failed: {e}", exc_info=True)
        return {"sent_immediate": 0, "sent_batch": 0, "sent_digest": 0, "failed": 1}
    finally:
        db.close()

    logger.info(
        f"Notifications complete — Immediate: {stats['sent_immediate']}, "
        f"Batch: {stats['sent_batch']}, Digest: {stats['sent_digest']}, "
        f"Failed: {stats['failed']}"
    )
    return stats
