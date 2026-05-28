#!/usr/bin/env python3
"""Post today's astronomical events to Mastodon in Basque.

Usage:
    python post-today-events.py [--db PATH] [--dry-run]

Queries the SQLite database for events happening today and posts each one
to Mastodon using the format_mastodon_status() function from mastodon_client.
"""

import json
import logging
import os
import sys
from pathlib import Path
from datetime import date, datetime

# Add src to path
skill_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(skill_dir / "src"))

import sqlite3
from mastodon_client import format_mastodon_status, post_to_mastodon, load_mastodon_config

logger = logging.getLogger("astronomical-events.post-today")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")


def get_today_events(db_path: str) -> list[dict]:
    """Query today's events from the database.

    Returns a list of event dicts ready for formatting.
    """
    conn = sqlite3.connect(db_path)
    today_str = date.today().isoformat()

    # Query events for today
    events = conn.execute(
        "SELECT * FROM events WHERE event_date LIKE ? ORDER BY priority, event_date",
        (f"{today_str}%",),
    ).fetchall()

    cols = [
        "id", "news_id", "title", "event_date", "rss_pub_date", "description",
        "event_type", "priority", "visibility_level", "thumbnail_url",
        "event_page_url", "is_notified", "created_at", "updated_at",
        "rich_description_en", "viewing_info_en", "event_details_json",
    ]

    result = []
    for event in events:
        data = dict(zip(cols, event))

        # Check for Basque translation
        trans = conn.execute(
            "SELECT translated_title, translated_rich_description FROM translations WHERE news_id=? AND target_lang='eu'",
            (data["news_id"],),
        ).fetchone()

        title = trans[0] if trans and trans[0] else data["title"]
        rich_desc = trans[1] if trans and trans[1] else ""

        event_data = {
            "title": title,
            "news_id": data["news_id"],
            "event_date": data["event_date"],
            "event_type": data.get("event_type", "unknown"),
            "priority": data.get("priority", 5),
            "rich_description": rich_desc,
            "viewing_info": "",
            "event_page_url": data.get("event_page_url", ""),
            "visibility_label": "",
            "time_label": "today",
        }
        result.append(event_data)

    conn.close()
    return result


def main():
    """Main entry point."""
    # Parse args
    db_path = "data/events.db"
    dry_run = False

    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--db" and i + 1 < len(sys.argv):
            db_path = sys.argv[i + 2]
        elif arg == "--dry-run":
            dry_run = True

    # Resolve paths relative to skill dir if not absolute
    if not os.path.isabs(db_path):
        db_path = str(skill_dir / db_path)

    logger.info(f"🔍 Querying events for {date.today()} from {db_path}")

    # Get today's events
    events = get_today_events(db_path)

    if not events:
        logger.info("ℹ️ No astronomical events scheduled for today")
        return False

    logger.info(f"✅ Found {len(events)} event(s) for today")

    # Post each event
    mastodon_config = load_mastodon_config()
    posted_count = 0

    for i, event_data in enumerate(events):
        status = format_mastodon_status(event_data)
        logger.info(f"📝 Event {i + 1}/{len(events)}: {event_data['title'][:60]}... ({len(status)} chars)")

        if dry_run:
            logger.info(f"🧪 DRY RUN — would post:\n{status}")
            posted_count += 1
            continue

        success = post_to_mastodon(status, mastodon_config)
        if success:
            logger.info(f"✅ Posted to Mastodon")
            posted_count += 1
        else:
            logger.error(f"❌ Failed to post event {i + 1}")

    logger.info(f"📊 Summary: {posted_count}/{len(events)} events posted")
    return posted_count > 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
