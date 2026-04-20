#!/usr/bin/env python3
"""CLI entry point for Astronomical Events Notification System.

Usage:
    python main.py fetch          Fetch RSS and store in database
    python main.py status         Show upcoming events summary
    python main.py list [days]    List all stored events (default: 15 days)
    python main.py notify-now     Manually trigger notification check
    python main.py history        Show recent fetch log entries
"""

import sys
import os
import re
import logging
from pathlib import Path
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rss_fetcher import fetch_rss, parse_items, get_feed_metadata
from db_manager import DatabaseManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M",
)
logger = logging.getLogger(__name__)


def load_config():
    """Load configuration from .env file or use defaults."""
    env_path = Path(__file__).parent.parent / ".env"

    config = {
        "rss_url": os.environ.get(
            "RSS_URL",
            "https://in-the-sky.org/rss.php?feed=dfan&latitude=43.139006&longitude=-2.966625&timezone=Europe/Madrid"
        ),
        "db_path": os.environ.get("DB_PATH", str(Path(__file__).parent.parent / "data" / "events.db")),
        "window_days": int(os.environ.get("NOTIFICATION_WINDOW_DAYS", "15")),
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

                # Override with env var if set
                if key in os.environ:
                    value = os.environ[key]

                config[key.lower()] = value

    return config


def cmd_fetch(config):
    """Fetch RSS feed and store new events in database."""
    logger.info("=" * 60)
    logger.info("Astronomical Events - Fetch")
    logger.info("=" * 60)

    db = DatabaseManager(config["db_path"])

    # Fetch RSS
    feed = fetch_rss(config["rss_url"])
    if not feed:
        logger.error("Failed to fetch RSS feed. Check network or URL.")
        return False

    # Parse items
    items = parse_items(feed)
    if not items:
        logger.warning("No valid items found in RSS feed.")
        db.log_fetch(0, 0, "success", "No valid items")
        return True

    # Log metadata
    meta = get_feed_metadata(feed)
    logger.info(f"Feed: {meta.get('title', 'Unknown')}")
    if meta.get("last_build_date"):
        logger.info(f"Last build date: {meta['last_build_date']}")

    # Store events
    new_count = 0
    existing_count = 0

    for item in items:
        # Parse event date from title
        event_date = parse_event_date(item.title)

        if not event_date:
            logger.warning(f"Could not parse date from title: {item.title}")
            continue

        inserted = db.insert_event(
            news_id=item.news_id,
            title=item.title,
            event_date=event_date,
            rss_pub_date=item.pub_date,
            description=strip_html(item.description),
            event_type="unknown",  # Will be classified in Phase 2
            priority=5,           # Default low priority (Phase 2)
            visibility_level=None,  # Will be scraped from page (Phase 2)
            thumbnail_url=None,     # Will be fetched from page (Phase 2)
            event_page_url=item.event_page_url,
        )

        if inserted:
            new_count += 1
        else:
            existing_count += 1

    # Log fetch operation
    db.log_fetch(
        items_fetched=len(items),
        new_items=new_count,
        status="success" if new_count > 0 or existing_count == len(items) else "partial",
    )

    logger.info("-" * 40)
    logger.info("Fetch complete!")
    logger.info(f"   Total items: {len(items)}")
    logger.info(f"   New events:  {new_count}")
    logger.info(f"   Existing:    {existing_count}")
    logger.info(f"   Total in DB: {db.count_events()}")

    db.close()
    return True


def cmd_status(config):
    """Show upcoming events summary."""
    logger.info("=" * 60)
    logger.info("Astronomical Events - Status")
    logger.info("=" * 60)

    db = DatabaseManager(config["db_path"])

    total = db.count_events()
    unnotified = db.count_unnotified()

    events = db.get_upcoming_events(days=config["window_days"])

    logger.info(f"Total events in DB: {total}")
    logger.info(f"Unnotified events:  {unnotified}")
    logger.info(f"Upcoming ({config['window_days']} days): {len(events)}")

    if events:
        logger.info("")
        logger.info("Upcoming events:")
        for i, event in enumerate(events[:20], 1):
            priority_emoji = ["", "P1-Critical", "P2-High", "P3-Medium", "P4-Low", "P5-Minor"][event.priority]
            notified = "[NOTIFIED]" if event.is_notified else "[NEW]"

            logger.info(
                f"  {i}. {priority_emoji} | "
                f"{notified} | "
                f"{event.event_date.strftime('%d %b')} | "
                f"{event.title[:60]}"
            )

        if len(events) > 20:
            logger.info(f"  ... and {len(events) - 20} more")

    db.close()


def cmd_list(config):
    """List all stored events."""
    days = int(sys.argv[2]) if len(sys.argv) > 2 else config["window_days"]

    logger.info("=" * 60)
    logger.info("Astronomical Events - List")
    logger.info("=" * 60)

    db = DatabaseManager(config["db_path"])
    events = db.get_upcoming_events(days=days)

    if not events:
        logger.info(f"No events found in the next {days} days.")
        return

    # Group by priority
    for p in range(1, 6):
        p_events = [e for e in events if e.priority == p]
        if not p_events:
            continue

        emoji_map = {1: "P1 Critical", 2: "P2 High", 3: "P3 Medium", 4: "P4 Low", 5: "P5 Minor"}
        logger.info(f"\n{emoji_map[p]} ({len(p_events)} events):")

        for event in p_events:
            notified = "[NOTIFIED]" if event.is_notified else "[NEW]"
            vis = f"(Level {event.visibility_level})" if event.visibility_level else "(Unknown)"

            logger.info(
                f"  - {event.event_date.strftime('%Y-%m-%d %H:%M')} | "
                f"{notified} {vis}"
            )
            logger.info(f"    {event.title}")

    db.close()


def cmd_notify_now(config):
    """Manually trigger notification check."""
    logger.info("=" * 60)
    logger.info("Astronomical Events - Notify Now")
    logger.info("=" * 60)

    # Phase 3: Telegram notifications will be implemented here
    db = DatabaseManager(config["db_path"])
    unnotified = db.get_unnotified_events(priority_max=3)

    if not unnotified:
        logger.info("No new high-priority events to notify.")
    else:
        logger.info(f"Found {len(unnotified)} unnotified high-priority events:")
        for event in unnotified:
            logger.info(f"  - P{event.priority}: {event.title}")

        # TODO: Send Telegram notifications (Phase 3)
        logger.info("\nNotifications not yet implemented. Coming in Phase 3.")

    db.close()


def cmd_history(config):
    """Show recent fetch log entries."""
    logger.info("=" * 60)
    logger.info("Astronomical Events - Fetch History")
    logger.info("=" * 60)

    db = DatabaseManager(config["db_path"])
    history = db.get_fetch_history(limit=10)

    if not history:
        logger.info("No fetch history found.")
        return

    for entry in history:
        status_icon = "OK" if entry.status == "success" else "FAIL"
        logger.info(
            f"{status_icon} {entry.fetched_at.strftime('%Y-%m-%d %H:%M')} | "
            f"Fetched: {entry.items_fetched} | New: {entry.new_items} | "
            f"Status: {entry.status}"
        )
        if entry.error_message:
            logger.info(f"   Error: {entry.error_message}")

    db.close()


def parse_event_date(title):
    """Parse event date from RSS title.

    Examples:
        "23 Apr 2026 (3 days away): 136108 Haumea at opposition"
        "22 Apr 2026 (1 day away): Lyrid meteor shower 2026"

    Returns datetime or None if parsing fails.
    """
    # Pattern: DD Mon YYYY at the start of title
    match = re.match(r"(\d{1,2}) (\w+) (\d{4})", title)
    if not match:
        return None

    day, month_str, year = match.groups()

    months = {
        "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4,
        "May": 5, "Jun": 6, "Jul": 7, "Aug": 8,
        "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
    }

    month = months.get(month_str)
    if not month:
        return None

    try:
        return datetime(int(year), month, int(day))
    except ValueError:
        return None


def strip_html(html_text):
    """Strip HTML tags from text."""
    # Remove HTML tags
    clean = re.sub(r"<[^>]+>", "", html_text)
    # Decode common HTML entities
    clean = (clean.replace("&amp;", "&")
                 .replace("&lt;", "<")
                 .replace("&gt;", ">")
                 .replace("&quot;", '"')
                 .replace("&#39;", "'"))
    # Collapse whitespace
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def main():
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()
    config = load_config()

    commands = {
        "fetch": cmd_fetch,
        "status": cmd_status,
        "list": cmd_list,
        "notify-now": cmd_notify_now,
        "history": cmd_history,
    }

    if command not in commands:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)

    try:
        commands[command](config)
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
