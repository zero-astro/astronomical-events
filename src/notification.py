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
from translate import TranslationError, translate_batch, get_provider_config
from classifier import get_priority_emoji, format_visibility_label
from translator import get_translation_for_event
from mastodon_client import (
    load_mastodon_config,
    post_to_mastodon,
    format_mastodon_status,
    format_mastodon_digest
)
from telegram_notifier import (
    load_telegram_config,
    send_telegram_notification,
    send_telegram_digest,
)

logger = logging.getLogger(__name__)


# Deterministic output schema version
SCHEMA_VERSION = "1.0"


def _format_event_for_output(event: Event, db: DatabaseManager | None = None, target_langs: list[str] | None = None) -> dict:
    """Format a single event into a deterministic JSON-serializable dict.

    Uses translated title/description if available for configured languages,
    falls back to original English text otherwise.

    Args:
        event: Event object
        db: DatabaseManager instance (for translation lookup)
        target_langs: List of target language codes to check for translations

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

    # Use translated text if available, fall back to original
    title = event.title
    description = event.description or ""
    rich_description = getattr(event, "rich_description_en", "") or ""
    viewing_info = getattr(event, "viewing_info_en", "") or ""
    target_lang_used = None
    
    if db and target_langs:
        for lang in target_langs:
            try:
                translation = get_translation_for_event(db, event.news_id, lang)
                # Validate: skip invalid cached translations (empty title means corrupt data)
                if translation is None or not translation.get("translated_title", "").strip():
                    logger.warning(f"Invalid cached translation for {event.news_id}/{lang} — skipping")
                    continue
                title = translation["translated_title"]
                description = translation.get("translated_description", "") or description
                rich_description = translation.get("translated_rich_description", "") or rich_description
                viewing_info = translation.get("translated_viewing_info", "") or viewing_info
                target_lang_used = lang
                break
            except TranslationError as e:
                # Circuit breaker or health check failure — skip cache entirely
                logger.warning(f"Circuit breaker/health failure loading cache for {event.news_id}: {e}")
                continue

    result = {
        "news_id": event.news_id,
        "title": title,
        "event_date": event.event_date.isoformat(),
        "time_label": time_label,
        "priority": event.priority,
        "priority_emoji": get_priority_emoji(event.priority),
        "event_type": event.event_type or "unknown",
        "is_notified": bool(event.is_notified),
    }
    if target_lang_used:
        result["target_lang"] = target_lang_used

    if event.visibility_level:
        result["visibility_level"] = event.visibility_level
        result["visibility_label"] = format_visibility_label(event.visibility_level)

    if event.thumbnail_url:
        result["thumbnail_url"] = event.thumbnail_url

    if event.event_page_url:
        result["event_page_url"] = event.event_page_url

    # Truncate description to fixed length for determinism
    if description:
        result["description"] = description[:200]
        if len(description) > 200:
            result["description_truncated"] = True

    # On-the-fly translation: if no cached translation found and we have English text,
    # translate it directly via LLM to ensure Basque output for Mastodon/Telegram.
    import re as _re
    if not target_lang_used and db:
        try:
            provider_config = get_provider_config("lm-studio")
            
            def _clean_translation(text: str) -> str:
                """Clean LLM output to extract only the actual translation."""
                text = text.strip()
                # Remove common LLM artifacts
                text = _re.sub(r'^.*?(?:translation|itzulpen):\s*', '', text, flags=_re.IGNORECASE)
                # Remove "Source Text:" prefix if present
                text = _re.sub(r'^Source Text:\s*.*?\.\s*', '', text, flags=_re.IGNORECASE)
                # Remove any trailing notes/annotations after the main translation
                # Look for patterns like "Important note:", "Note:", etc.
                text = _re.sub(r'(?i)(?:important\s+note|note|warning):[^.]*\.?\s*', '', text)
                return text.strip()
            
            if rich_description:
                translated_rich = translate_batch(
                    [rich_description], "eu", provider_config, field_type="rich_description"
                )
                if translated_rich and translated_rich[0].strip():
                    cleaned = _clean_translation(translated_rich[0])
                    if cleaned:
                        rich_description = cleaned
                        logger.info(f"On-the-fly translated rich_description for {event.news_id}")
            if viewing_info:
                translated_viewing = translate_batch(
                    [viewing_info], "eu", provider_config, field_type="viewing_info"
                )
                if translated_viewing and translated_viewing[0].strip():
                    cleaned = _clean_translation(translated_viewing[0])
                    if cleaned:
                        viewing_info = cleaned
        except Exception as e:
            logger.warning(f"On-the-fly translation failed for {event.news_id}: {e}")

    # Pass through rich metadata (translated or original) for Mastodon formatting
    if rich_description:
        result["rich_description"] = rich_description
    if viewing_info:
        result["viewing_info"] = viewing_info

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
    Uses plain text with clear structure - no markdown tables (WhatsApp/Discord).
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


def _get_target_langs(db: DatabaseManager) -> list[str]:
    """Load target languages from database config."""
    import json as _json
    cursor = db.conn.cursor()
    cursor.execute("SELECT value FROM config WHERE key='target_languages'")
    row = cursor.fetchone()
    if row and row["value"]:
        try:
            return [l.strip() for l in _json.loads(row["value"]) if l.strip()]
        except (_json.JSONDecodeError, TypeError):
            pass
    return []


def post_individual_events(config: dict) -> dict:
    """Post individual high-priority events (P1-P3) to Mastodon/Telegram.

    This is a standalone function for cron/manual use — posts only P1-P3 events,
    marks them as notified, and returns stats. Does NOT post digest.

    Args:
        config: Configuration dict with db_path key

    Returns:
        Dict with stats: {sent_immediate, sent_batch, failed}
    """
    logger.info("=" * 60)
    logger.info("Astronomical Events - Post Individual Events (P1-P3)")
    logger.info("=" * 60)

    db = DatabaseManager(config["db_path"])
    target_langs = _get_target_langs(db)

    mastodon_config = load_mastodon_config()
    mastodon_enabled = bool(mastodon_config)

    telegram_config = load_telegram_config()
    telegram_enabled = bool(telegram_config)

    stats = {"sent_immediate": 0, "sent_batch": 0, "failed": 0}

    try:
        all_unnotified = db.get_unnotified_events(priority_max=3)

        if not all_unnotified:
            logger.info("No new high-priority events to notify.")
            return stats

        p1_events = [e for e in all_unnotified if e.priority == 1]
        p2_events = [e for e in all_unnotified if e.priority == 2]
        p3_events = [e for e in all_unnotified if e.priority == 3]

        # Filter: only post events with valid translations (skip otherwise)
        def _has_valid_translation(event):
            return any(db.has_valid_translation(event.news_id, lang) for lang in target_langs)

        p1_events = [e for e in p1_events if _has_valid_translation(e)]
        p2_events = [e for e in p2_events if _has_valid_translation(e)]
        p3_events = [e for e in p3_events if _has_valid_translation(e)]

        # P1/P2: Immediate individual events
        immediate_events = p1_events + p2_events
        if immediate_events:
            logger.info(f"Processing {len(immediate_events)} P1-P2 event(s)")
            for event in immediate_events:
                db.mark_as_notified(event.news_id)
                stats["sent_immediate"] += 1

                formatted = _format_event_for_output(event, db, target_langs)

                if mastodon_enabled:
                    try:
                        status = format_mastodon_status(formatted)
                        post_to_mastodon(status, mastodon_config)
                        logger.info(f"Mastodon posted: {event.title}")
                    except Exception as e:
                        logger.error(f"Mastodon post failed for {event.news_id}: {e}")
                        stats["failed"] += 1

                if telegram_enabled:
                    try:
                        send_telegram_notification(telegram_config, formatted)
                    except Exception as e:
                        logger.error(f"Telegram notification failed for {event.news_id}: {e}")
                        stats["failed"] += 1

        # P3: Batched (up to 5 per batch)
        if p3_events:
            batch_size = 5
            logger.info(f"Processing {len(p3_events)} P3 event(s) in batches")
            for i in range(0, len(p3_events), batch_size):
                batch = p3_events[i:i + batch_size]
                for event in batch:
                    db.mark_as_notified(event.news_id)
                    stats["sent_batch"] += 1

                    formatted = _format_event_for_output(event, db, target_langs)

                    if mastodon_enabled:
                        try:
                            status = format_mastodon_status(formatted)
                            post_to_mastodon(status, mastodon_config)
                            logger.info(f"Mastodon posted: {event.title}")
                        except Exception as e:
                            logger.error(f"Mastodon post failed for {event.news_id}: {e}")
                            stats["failed"] += 1

                    if telegram_enabled:
                        try:
                            send_telegram_notification(telegram_config, formatted)
                        except Exception as e:
                            logger.error(f"Telegram notification failed for {event.news_id}: {e}")
                            stats["failed"] += 1

    except Exception as e:
        logger.error(f"Individual events posting failed: {e}", exc_info=True)
        return {"sent_immediate": 0, "sent_batch": 0, "failed": 1}
    finally:
        db.close()

    logger.info(
        f"Individual events complete - Immediate: {stats['sent_immediate']}, "
        f"Batch: {stats['sent_batch']}, Failed: {stats['failed']}"
    )
    return stats


def post_digest(config: dict) -> dict:
    """Post daily digest (P4-P5) to Mastodon/Telegram.

    This is a standalone function for cron/manual use — posts only the P4-P5
    digest of all upcoming events. Does NOT mark any events as notified or
    post individual event notifications.

    Args:
        config: Configuration dict with db_path key

    Returns:
        Dict with stats: {sent_digest, failed}
    """
    logger.info("=" * 60)
    logger.info("Astronomical Events - Post Digest (P4-P5)")
    logger.info("=" * 60)

    db = DatabaseManager(config["db_path"])
    target_langs = _get_target_langs(db)

    mastodon_config = load_mastodon_config()
    mastodon_enabled = bool(mastodon_config)

    telegram_config = load_telegram_config()
    telegram_enabled = bool(telegram_config)

    stats = {"sent_digest": 0, "failed": 0}

    try:
        window_days = int(config.get("window_days", "15"))
        all_upcoming = db.get_upcoming_events(days=window_days)

        # Filter: only include events with valid translations in digest
        def _has_valid_translation(event):
            return any(db.has_valid_translation(event.news_id, lang) for lang in target_langs)

        upcoming_with_translations = [e for e in all_upcoming if _has_valid_translation(e)]

        if not upcoming_with_translations:
            logger.info("No upcoming events for digest.")
            return stats

        formatted = [_format_event_for_output(e, db, target_langs) for e in upcoming_with_translations]
        stats["sent_digest"] = len(upcoming_with_translations)

        if mastodon_enabled:
            try:
                digest_status = format_mastodon_digest(formatted)
                post_to_mastodon(digest_status, mastodon_config)
                logger.info(f"Mastodon digest posted ({len(all_upcoming)} events)")
            except Exception as e:
                logger.error(f"Mastodon digest post failed: {e}")
                stats["failed"] += 1

        if telegram_enabled:
            try:
                send_telegram_digest(telegram_config, formatted)
                logger.info("Telegram digest sent")
            except Exception as e:
                logger.error(f"Telegram digest failed: {e}")
                stats["failed"] += 1

    except Exception as e:
        logger.error(f"Digest posting failed: {e}", exc_info=True)
        return {"sent_digest": 0, "failed": 1}
    finally:
        db.close()

    logger.info(
        f"Digest complete - Events in digest: {stats['sent_digest']}, Failed: {stats['failed']}"
    )
    return stats


def send_notifications(config: dict) -> dict:
    """Main notification dispatch function (calls both individual + digest).

    Processes unnotified events AND posts daily digest in one run.
    For separate control, use post_individual_events() or post_digest().

    Args:
        config: Configuration dict

    Returns:
        Dict with stats: {sent_immediate, sent_batch, sent_digest, failed}
    """
    db = DatabaseManager(config["db_path"])
    target_langs = _get_target_langs(db)

    mastodon_config = load_mastodon_config()
    mastodon_enabled = bool(mastodon_config)

    telegram_config = load_telegram_config()
    telegram_enabled = bool(telegram_config)

    # Delegate to separate functions for individual events and digest
    stats_individual = post_individual_events(config)
    stats_digest = post_digest(config)

    combined_stats = {
        "sent_immediate": stats_individual.get("sent_immediate", 0),
        "sent_batch": stats_individual.get("sent_batch", 0),
        "sent_digest": stats_digest.get("sent_digest", 0),
        "failed": stats_individual.get("failed", 0) + stats_digest.get("failed", 0),
    }

    return combined_stats
