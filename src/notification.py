"""Notification system - Astronomical event notifications for OpenClaw.

This module outputs structured notification data that OpenClaw can route
through any channel (Telegram, WhatsApp, etc.) via heartbeat/cron triggers.

Usage:
    python3 scripts/main.py notify-now   # Outputs JSON to stdout
    
Output format is deterministic and machine-readable so the skill works
consistently regardless of which messaging channel delivers it.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from db_manager import DatabaseManager, Event
from classifier import get_priority_emoji, format_visibility_label

logger = logging.getLogger(__name__)


# Deterministic output schema version
SCHEMA_VERSION = "1.0"


def _format_event_for_output(event: Event) -> dict:
    """Format a single event into a deterministic JSON-serializable dict.

    Returns a fixed-schema dict so consumers always know the structure.
    """
    today = datetime.now()
    delta_days = (event.event_date.date() - today.date()).days

    if delta_days < 0:
        time_label = "past"
    elif delta_days == 0:
        time_label = "today"
    elif delta_days == 1:
        time_label = "tomorrow"
    else:
        time_label = f"{delta_days} days away"

    result = {
        "news_id": event.news_id,
        "title": event.title,
        "event_date": event.event_date.isoformat(),
        "time_label": time_label,
        "priority": event.priority,
        "priority_emoji": get_priority_emoji(event.priority),
        "event_type": event.event_type or "unknown",
        "is_notified": bool(event.is_notified),
    }

    if event.visibility_level:
        result["visibility_level"] = event.visibility_level
        result["visibility_label"] = format_visibility_label(event.visibility_level)

    if event.thumbnail_url:
        result["thumbnail_url"] = event.thumbnail_url

    if event.event_page_url:
        result["event_page_url"] = event.event_page_url

    # Truncate description to fixed length for determinism
    if event.description:
        result["description"] = event.description[:200]
        if len(event.description) > 200:
            result["description_truncated"] = True

    return result


def _format_notification_message(events: list[dict], batch_label: str) -> dict:
    """Format a notification message in deterministic structure.

    Returns a dict with fixed keys that OpenClaw can render consistently
    across all channels (Telegram, WhatsApp, etc.).
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "astronomical_events",
        "batch_label": batch_label,
        "count": len(events),
        "events": events,
        "generated_at": datetime.now().isoformat(),
    }


def _build_human_readable(notifications: list[dict]) -> str:
    """Build a human-readable message from structured notification data.

    This ensures consistent formatting regardless of channel.
    Uses plain text with clear structure — no markdown tables (WhatsApp/Discord).
    """
    lines = []

    for notif in notifications:
        label = notif["batch_label"]
        count = notif["count"]
        lines.append(f"📋 {label} ({count} event(s))")

        for evt in notif["events"]:
            emoji = evt.get("priority_emoji", "")
            date_str = evt.get("time_label", "unknown")
            title = evt["title"]
            vis = ""
            if "visibility_label" in evt:
                vis = f" | {evt['visibility_label']}"

            lines.append(f"{emoji} P{evt['priority']} | {date_str} | {title}{vis}")

        lines.append("")  # separator between batches

    return "\n".join(lines)


def send_notifications(config: dict) -> dict:
    """Main notification dispatch function.

    Processes unnotified events and outputs structured notifications.
    Returns a summary dict with stats.

    Args:
        config: Configuration dict (currently unused, kept for API compatibility)

    Returns:
        Dict with stats: {sent_immediate, sent_batch, sent_digest, failed}
    """
    db = DatabaseManager(config["db_path"])

    try:
        # Get unnotified events (P1-P3)
        all_unnotified = db.get_unnotified_events(priority_max=3)

        if not all_unnotified:
            logger.info("No new high-priority events to notify.")
            return {"sent_immediate": 0, "sent_batch": 0, "sent_digest": 0, "failed": 0}

        logger.info(f"Found {len(all_unnotified)} unnotified events (P1-P3)")

        # Separate by priority tier
        p1_events = [e for e in all_unnotified if e.priority == 1]
        p2_events = [e for e in all_unnotified if e.priority == 2]
        p3_events = [e for e in all_unnotified if e.priority == 3]

        notifications = []
        stats = {"sent_immediate": 0, "sent_batch": 0, "sent_digest": 0, "failed": 0}

        # P1/P2: Immediate individual events
        immediate_events = p1_events + p2_events
        if immediate_events:
            formatted = [_format_event_for_output(e) for e in immediate_events]
            notifications.append(_format_notification_message(formatted, "P1-P2 High Priority"))

            # Mark as notified
            for event in immediate_events:
                db.mark_as_notified(event.news_id)
                stats["sent_immediate"] += 1

        # P3: Batched (up to 5 per batch)
        if p3_events:
            batch_size = 5
            for i in range(0, len(p3_events), batch_size):
                batch = p3_events[i:i + batch_size]
                formatted = [_format_event_for_output(e) for e in batch]
                notifications.append(_format_notification_message(formatted, "P3 Medium Priority"))

                for event in batch:
                    db.mark_as_notified(event.news_id)
                    stats["sent_batch"] += 1

        # P4/P5: Daily digest (all upcoming events)
        window_days = int(config.get("window_days", "15"))
        all_upcoming = db.get_upcoming_events(days=window_days)

        if all_upcoming:
            formatted = [_format_event_for_output(e) for e in all_upcoming]
            notifications.append(_format_notification_message(formatted, "Daily Digest (P4-P5)"))
            stats["sent_digest"] = len(all_upcoming)

    except Exception as e:
        logger.error(f"Notification dispatch failed: {e}", exc_info=True)
        return {"sent_immediate": 0, "sent_batch": 0, "sent_digest": 0, "failed": 1}
    finally:
        db.close()

    # Output structured notifications to stdout (JSON lines format)
    for notif in notifications:
        print(json.dumps(notif, ensure_ascii=False))

    # Also output human-readable version
    readable = _build_human_readable(notifications)
    if readable.strip():
        logger.info("NOTIFICATION_OUTPUT_START")
        logger.info(readable)
        logger.info("NOTIFICATION_OUTPUT_END")

    logger.info(
        f"Notifications complete — Immediate: {stats['sent_immediate']}, "
        f"Batch: {stats['sent_batch']}, Digest: {stats['sent_digest']}, "
        f"Failed: {stats['failed']}"
    )
    return stats
