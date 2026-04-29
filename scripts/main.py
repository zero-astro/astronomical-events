#!/usr/bin/env python3
"""CLI entry point for Astronomical Events Notification System.

Usage:
    python main.py fetch          Fetch RSS and store in database (Phase 1)
    python main.py process        Full pipeline: fetch + classify + scrape thumbnails (Phase 2)
    python main.py status         Show upcoming events summary
    python main.py list [days]    List all stored events (default: 15 days)
    python main.py notify-now     Trigger notifications (Phase 3)
    python main.py history        Show recent fetch log entries
    python main.py schedule       Start scheduler daemon (Phase 4)
    python main.py schedule --run-once   Run one scheduler cycle and exit
    python main.py health         Health check (JSON output, exit codes: 0=healthy, 1=degraded, 2=unhealthy)
    python main.py dashboard      Start web dashboard (Phase 5)
    python main.py translate --lang eu,ca   Translate missing events to specified language(s)
    python main.py translate-all              Backfill translations for all configured languages
"""

import sys
import os
import re
import logging
import argparse
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
from scheduler import (
    load_config,
    setup_logging,
    run_fetch_pipeline,
    run_notify,
    Scheduler,
    health_check,
    cmd_schedule_run_once,
    cmd_schedule_daemon,
    cmd_health,
)
from dashboard import cmd_dashboard
from translate import get_provider_config, PROVIDERS

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
        event_date = _parse_event_date(item["title"])

        if not event_date:
            logger.warning(f"Could not parse date from title: {item["title"]}")
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
    setup_logging()
    logger.info("=" * 60)
    logger.info("Astronomical Events - Notify Now")
    logger.info("=" * 60)

    # Phase 3: OpenClaw-native notification output
    stats = send_notifications(config)
    logger.info("-" * 40)
    logger.info(f"Immediate: {stats['sent_immediate']} | Batch: {stats['sent_batch']} | Digest: {stats['sent_digest']} | Failed: {stats['failed']}")


def cmd_schedule(config):
    """Start scheduler daemon or run one cycle.

    Usage:
        python main.py schedule              # Start daemon mode (continuous)
        python main.py schedule --run-once   # Run one cycle and exit
    """
    setup_logging()
    parser = argparse.ArgumentParser(description="Scheduler")
    parser.add_argument("--run-once", action="store_true", help="Run one cycle and exit")
    args, _ = parser.parse_known_args()

    if args.run_once:
        cmd_schedule_run_once(config)
    else:
        cmd_schedule_daemon(config)


def cmd_health(config):
    """Health check - outputs JSON status to stdout.

    Exit codes: 0=healthy, 1=degraded, 2=unhealthy
    Checks: database connectivity, RSS feed reachability, logging directory.
    """
    result = health_check(config)
    if result["status"] == "healthy":
        sys.exit(0)
    elif result["status"] == "degraded":
        sys.exit(1)
    else:
        sys.exit(2)




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


def cmd_translate(config):
    """Translate missing events to specified language(s)."""
    setup_logging()
    logger.info("=" * 60)
    logger.info("Astronomical Events - Translate")
    logger.info("=" * 60)

    # Parse --lang argument
    parser = argparse.ArgumentParser(description="Translate missing events")
    parser.add_argument("--lang", type=str, default=None,
                        help="Comma-separated list of target languages (e.g., eu,ca)")
    args, _ = parser.parse_known_args()

    db = DatabaseManager(config["db_path"])

    # Determine which languages to translate
    if args.lang:
        target_langs = [l.strip() for l in args.lang.split(",")]
        logger.info(f"Translating to specified languages: {target_langs}")
    else:
        from translator import get_target_languages as _get_tlangs
        target_langs = _get_tlangs(db)
        if not target_langs:
            logger.error("No target languages configured. Set 'target_languages' in config table.")
            db.close()
            sys.exit(1)
        logger.info(f"Translating to configured languages: {target_langs}")

    # Get provider config (use first available from env or default lm-studio)
    import os
    provider_name = os.environ.get("TRANSLATION_PROVIDER", "lm-studio")
    if provider_name not in PROVIDERS:
        logger.warning(f"Unknown provider '{provider_name}', falling back to 'lm-studio'")
        provider_name = "lm-studio"
    
    provider_config = get_provider_config(provider_name)

    # Translate each language
    from translator import translate_missing_events
    results = translate_missing_events(db, provider_config)

    db.close()

    logger.info("-" * 40)
    logger.info("Translation complete!")
    for lang, stats in results.items():
        logger.info(f"  {lang}: {stats['translated']} translated, "
                     f"{stats['failed']} failed")


def cmd_translate_all(config):
    """Backfill translations for all configured languages."""
    setup_logging()
    logger.info("=" * 60)
    logger.info("Astronomical Events - Translate All (Backfill)")
    logger.info("=" * 60)

    db = DatabaseManager(config["db_path"])

    from translator import get_target_languages as _get_tlangs
    target_langs = _get_tlangs(db)
    if not target_langs:
        logger.error("No target languages configured.")
        db.close()
        sys.exit(1)

    import os
    provider_name = os.environ.get("TRANSLATION_PROVIDER", "lm-studio")
    if provider_name not in PROVIDERS:
        provider_name = "lm-studio"
    
    provider_config = get_provider_config(provider_name)

    from translator import translate_missing_events
    results = translate_missing_events(db, provider_config)

    db.close()

    logger.info("-" * 40)
    total_translated = sum(r["translated"] for r in results.values())
    total_failed = sum(r["failed"] for r in results.values())
    logger.info(f"Backfill complete! {total_translated} translated, {total_failed} failed")


def cmd_set_lang(config):
    """Set target language(s) for translation."""
    setup_logging()
    logger.info("=" * 60)
    logger.info("Astronomical Events - Set Target Language(s)")
    logger.info("=" * 60)

    db = DatabaseManager(config["db_path"])

    # Parse --lang argument
    parser = argparse.ArgumentParser(description="Set target language(s)")
    parser.add_argument("--lang", type=str, required=True,
                        help="Comma-separated list of target languages (e.g., eu,ca)")
    args, _ = parser.parse_known_args()

    # Validate languages
    valid_langs = {"eu", "ca", "gl", "es", "fr"}
    new_langs = [l.strip() for l in args.lang.split(",")]
    invalid = [l for l in new_langs if l not in valid_langs]
    
    if invalid:
        logger.error(f"Invalid language(s): {invalid}. Valid: {sorted(valid_langs)}")
        db.close()
        sys.exit(1)

    # Update config table
    import json as _json
    cursor = db.conn.cursor()
    cursor.execute("UPDATE OR REPLACE INTO config (key, value) VALUES ('target_languages', ?)",
                   (_json.dumps(new_langs),))
    db.conn.commit()

    logger.info(f"Target languages set to: {new_langs}")
    
    # Verify
    cursor.execute("SELECT value FROM config WHERE key='target_languages'")
    row = cursor.fetchone()
    if row and row["value"]:
        stored = _json.loads(row["value"])
        logger.info(f"Stored: {stored}")
    
    db.close()


def cmd_show_langs(config):
    """Show current target language configuration."""
    setup_logging()
    logger.info("=" * 60)
    logger.info("Astronomical Events - Target Languages")
    logger.info("=" * 60)

    db = DatabaseManager(config["db_path"])

    from translator import get_target_languages as _get_tlangs
    target_langs = _get_tlangs(db)
    
    if not target_langs:
        logger.info("No target languages configured.")
        logger.info("Use: python3 scripts/main.py set-lang --lang eu,ca")
    else:
        valid_langs = {"eu": "Basque (Euskara)", "ca": "Catalan (Català)", 
                       "gl": "Galician (Galego)", "es": "Spanish (Español)", 
                       "fr": "French (Français)"}
        logger.info(f"Current target languages:")
        for lang in target_langs:
            name = valid_langs.get(lang, "Unknown")
            logger.info(f"  - {lang}: {name}")
    
    # Show translation provider
    import os
    provider_name = os.environ.get("TRANSLATION_PROVIDER", "lm-studio")
    logger.info(f"Translation provider: {provider_name}")
    
    db.close()


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
        "schedule": cmd_schedule,
        "health": cmd_health,
        "dashboard": cmd_dashboard,
        "history": cmd_history,
        "translate": cmd_translate,
        "translate-all": cmd_translate_all,
        "set-lang": cmd_set_lang,
        "show-langs": cmd_show_langs,
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
