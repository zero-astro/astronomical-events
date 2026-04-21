#!/usr/bin/env python3
"""CLI entry point for Astronomical Events Notification System.

Usage:
    python main.py fetch          Fetch RSS and store in database (Phase 1)
    python main.py process        Full pipeline: fetch + classify + scrape thumbnails (Phase 2)
    python main.py status         Show upcoming events summary
    python main.py list [days]    List all stored events (default: 15 days)
    python main.py notify-now     Trigger Telegram notifications (Phase 3)
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
from event_parser import parse_rss_item as parse_single_item
from classifier import classify_event, format_priority_label, format_visibility_label
from page_scraper import fetch_event_page, parse_page
from db_manager import DatabaseManager
from notification import send_notifications

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
    """Fetch RSS feed and store new events in database (Phase 1)."""
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

    # Store events (Phase 1 style - no classification yet)
    new_count = 0
    existing_count = 0

    for item in items:
        event_date = _parse_event_date(item.title)

        if not event_date:
            logger.warning(f"Could not parse date from title: {item.title}")
            continue

        inserted = db.insert_event(
            news_id=item["news_id"],
            title=item["title"],
            event_date=event_date,
            rss_pub_date=str(item.get("pub_date", "")),
            description=item["description_text"],
            event_type="unknown",  # Phase 2 will classify
            priority=5,           # Default low priority (Phase 2)
            visibility_level=None,  # Will be scraped from page (Phase 2)
            thumbnail_url=None,     # Will be fetched from page (Phase 2)
            event_page_url=item.get("link"),
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


def cmd_process(config):
    """Full pipeline: fetch + classify + scrape thumbnails (Phase 2)."""
    logger.info("=" * 60)
    logger.info("Astronomical Events - Full Pipeline (Fetch + Classify + Scrape)")
    logger.info("=" * 60)

    db = DatabaseManager(config["db_path"])

    # Step 1: Fetch RSS
    feed = fetch_rss(config["rss_url"])
    if not feed:
        logger.error("Failed to fetch RSS feed.")
        return False

    items = parse_items(feed)
    if not items:
        logger.warning("No valid items found in RSS feed.")
        db.log_fetch(0, 0, "success", "No valid items")
        return True

    meta = get_feed_metadata(feed)
    logger.info(f"Feed: {meta.get('title', 'Unknown')}")

    # Step 2 & 3: Classify and store with metadata
    new_count = 0
    existing_count = 0
    classified_count = 0
    scraped_count = 0

    for item in items:
        event_date = _parse_event_date(item["title"])
        if not event_date:
            logger.warning(f"Could not parse date from title: {item['title']}")
            continue

        # Classify the event (Phase 2)
        classification = classify_event(
            item["title"],
            item.get("description_text", "")
        )

        # Scrape page for thumbnail and visibility level (Phase 2)
        thumbnail_url = None
        visibility_level = None

        if item.get("link"):
            try:
                html = fetch_event_page(item["link"])
                if html:
                    page_data = parse_page(html)
                    if page_data and page_data.is_visible:
                        thumbnail_url = page_data.thumbnail_url
                        visibility_level = page_data.visibility_level
                        scraped_count += 1
            except Exception as e:
                logger.warning(f"Failed to scrape page for {item.get('news_id')}: {e}")

        # Insert/update event with full metadata
        inserted = db.insert_event(
            news_id=item["news_id"],
            title=item["title"],
            event_date=event_date,
            rss_pub_date=str(item.get("pub_date", "")),
            description=item["description_text"],
            event_type=classification.event_type,
            priority=classification.priority,
            visibility_level=visibility_level,
            thumbnail_url=thumbnail_url,
            event_page_url=item.get("link"),
        )

        if inserted:
            new_count += 1
        else:
            existing_count += 1

        classified_count += 1

    # Log fetch operation
    db.log_fetch(
        items_fetched=len(items),
        new_items=new_count,
        status="success" if new_count > 0 or existing_count == len(items) else "partial",
    )

    logger.info("-" * 40)
    logger.info("Full pipeline complete!")
    logger.info(f"   Total items:     {len(items)}")
    logger.info(f"   New events:      {new_count}")
    logger.info(f"   Existing:        {existing_count}")
    logger.info(f"   Classified:      {classified_count}")
    logger.info(f"   Pages scraped:   {scraped_count}")
    logger.info(f"   Total in DB:     {db.count_events()}")

    # Show classification summary
    _print_classification_summary(db)

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
            priority_label = format_priority_label(event.priority)
            notified = "[NOTIFIED]" if event.is_notified else "[NEW]"

            vis_str = ""
            if event.visibility_level:
                vis_str = f" | {format_visibility_label(event.visibility_level)}"

            logger.info(
                f"  {i}. {priority_label} | "
                f"{notified} | "
                f"{event.event_date.strftime('%d %b')} | "
                f"{event.title[:60]}"
                + vis_str
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
            vis_str = ""
            if event.visibility_level:
                vis_str = f" | {format_visibility_label(event.visibility_level)}"

            logger.info(
                f"  - {event.event_date.strftime('%Y-%m-%d %H:%M')} | "
                f"{notified} {vis_str}"
            )
            logger.info(f"    {event.title}")

    db.close()


def cmd_notify_now(config):
    """Manually trigger notification check."""
    logger.info("=" * 60)
    logger.info("Astronomical Events - Notify Now")
    logger.info("=" * 60)

    # Phase 3: OpenClaw-native notification output
    stats = send_notifications(config)
    logger.info("-" * 40)
    logger.info(f"Immediate: {stats['sent_immediate']} | Batch: {stats['sent_batch']} | Digest: {stats['sent_digest']} | Failed: {stats['failed']}")




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


def _print_classification_summary(db):
    """Print a summary of event classifications."""
    logger.info("\nClassification Summary:")
    for p in range(1, 6):
        events = db.get_events_by_priority(p)
        if not events:
            continue

        type_counts = {}
        for e in events:
            etype = e.event_type or "unknown"
            type_counts[etype] = type_counts.get(etype, 0) + 1

        logger.info(f"  P{p}: {len(events)} event(s)")
        for etype, count in sorted(type_counts.items()):
            logger.info(f"    - {etype}: {count}")


def _parse_event_date(title):
    """Parse event date from RSS title."""
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


def main():
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()
    config = load_config()

    commands = {
        "fetch": cmd_fetch,
        "process": cmd_process,
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
