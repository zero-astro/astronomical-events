#!/usr/bin/env python3
"""Post the next unnotified astronomical event to Mastodon.

Usage:
    python3 post-next-event.py

Outputs JSON with result info for OpenClaw to report back.
"""

import sys
import os
import json
import logging
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from db_manager import DatabaseManager, Event
from mastodon_client import (
    load_mastodon_config,
    post_to_mastodon,
    format_mastodon_status,
)
from notification import _format_event_for_output

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M",
)
logger = logging.getLogger(__name__)


def main():
    logger.info("=" * 60)
    logger.info("Astronomical Events - Post Next Event to Mastodon")
    logger.info("=" * 60)

    # Load config
    env_path = Path(__file__).parent.parent / ".env"
    config = {
        "db_path": str(Path(__file__).parent.parent / "data" / "events.db"),
    }
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"\'')
                if key in os.environ:
                    value = os.environ[key]
                config[key.lower()] = value

    db = DatabaseManager(config["db_path"])

    # Get target languages for translation
    cursor = db.conn.cursor()
    cursor.execute("SELECT value FROM config WHERE key='target_languages'")
    row_cfg = cursor.fetchone()
    target_langs = []
    if row_cfg and row_cfg["value"]:
        try:
            target_langs = [l.strip() for l in json.loads(row_cfg["value"]) if l.strip()]
        except (json.JSONDecodeError, TypeError):
            pass

    # Get the next unnotified event (sorted by date, lowest priority number first)
    today = datetime.now().strftime("%Y-%m-%d")
    future = (datetime.now() + __import__("datetime").timedelta(days=15)).strftime("%Y-%m-%d")

    cursor.execute("""
        SELECT * FROM events
        WHERE is_notified = 0 AND event_date >= ? AND event_date <= ?
        ORDER BY priority ASC, event_date ASC
        LIMIT 1
    """, (today, future))

    row = cursor.fetchone()

    if not row:
        logger.info("No unnotified upcoming events found.")
        result = {
            "success": False,
            "error": "No unnotified upcoming events found in the next 15 days.",
            "posted_to_mastodon": False,
        }
        print(json.dumps(result, ensure_ascii=False))
        db.close()
        return

    # Build Event object from DB row
    event = Event(
        news_id=row["news_id"],
        title=row["title"],
        event_date=datetime.fromisoformat(row["event_date"]),
        rss_pub_date=row["rss_pub_date"] and datetime.fromisoformat(row["rss_pub_date"]),
        description=row["description"] or "",
        event_type=row["event_type"] or "unknown",
        priority=int(row["priority"]) if row["priority"] else 5,
        visibility_level=int(row["visibility_level"]) if row["visibility_level"] else None,
        thumbnail_url=row["thumbnail_url"],
        event_page_url=row["event_page_url"],
        is_notified=bool(row["is_notified"]),
    )

    logger.info(f"Found event: {event.title}")

    # Format with translations (same as notification system)
    formatted = _format_event_for_output(event, db, target_langs if target_langs else None)

    # Load Mastodon config
    mastodon_config = load_mastodon_config()
    if not mastodon_config:
        logger.error("Mastodon configuration not found.")
        result = {
            "success": False,
            "error": "Mastodon configuration not found.",
            "posted_to_mastodon": False,
        }
        print(json.dumps(result, ensure_ascii=False))
        db.close()
        return

    # Format Mastodon status using the translated event data
    try:
        status = format_mastodon_status(formatted)
        logger.info(f"Formatted status:\n{status}")
    except Exception as e:
        logger.error(f"Failed to format status: {e}", exc_info=True)
        result = {
            "success": False,
            "error": f"Failed to format status: {e}",
            "posted_to_mastodon": False,
        }
        print(json.dumps(result, ensure_ascii=False))
        db.close()
        return

    # Post to Mastodon
    try:
        success = post_to_mastodon(status, mastodon_config)
    except Exception as e:
        logger.error(f"Mastodon posting failed: {e}", exc_info=True)
        result = {
            "success": False,
            "error": f"Mastodon posting failed: {e}",
            "posted_to_mastodon": False,
        }
        print(json.dumps(result, ensure_ascii=False))
        db.close()
        return

    if not success:
        logger.error("Mastodon post returned failure.")
        result = {
            "success": False,
            "error": "Mastodon post returned failure.",
            "posted_to_mastodon": False,
        }
        print(json.dumps(result, ensure_ascii=False))
        db.close()
        return

    # Mark as notified in database
    cursor.execute("UPDATE events SET is_notified = 1 WHERE news_id = ?", (event.news_id,))
    db.conn.commit()

    logger.info(f"Event marked as notified: {event.news_id}")

    result = {
        "success": True,
        "title": event.title,
        "translated_title": formatted.get("title", ""),
        "event_date": event.event_date.strftime("%Y-%m-%d"),
        "priority": event.priority,
        "status_text": status[:300],
        "posted_to_mastodon": True,
    }

    print(json.dumps(result, ensure_ascii=False))
    db.close()


if __name__ == "__main__":
    main()
