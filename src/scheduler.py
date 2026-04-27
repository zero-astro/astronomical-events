"""Scheduling & Automation - Astronomical Events Skill.

Provides cron-like scheduling for automated RSS fetches and notifications.
Designed to run as a systemd service or via OpenClaw cron/heartbeat.

Usage:
    python3 scripts/main.py schedule --run-once   # Run one cycle (fetch + notify)
    python3 scripts/main.py schedule              # Start daemon mode
    python3 scripts/main.py health                # Health check command
"""

import json
import logging
import os
import signal
import sys
import time
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rss_fetcher import fetch_rss, parse_items
from event_parser import parse_rss_item as parse_single_item
from classifier import classify_event
from page_scraper import fetch_event_page, parse_page
from db_manager import DatabaseManager
from notification import send_notifications

logger = logging.getLogger(__name__)


# ─── Configuration ──────────────────────────────────────────────────────────

def load_config() -> dict:
    """Load configuration from .env file and environment variables."""
    env_path = Path(__file__).parent.parent / ".env"
    config = {}

    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                config[key.strip()] = value.strip()

    # Override with environment variables
    for key in ["RSS_URL", "LATITUDE", "LONGITUDE", "TIMEZONE",
                 "FETCH_INTERVAL_MINUTES", "NOTIFICATION_WINDOW_DAYS", "DB_PATH"]:
        if os.environ.get(key):
            config[key] = os.environ[key]

    return {
        "rss_url": config.get("RSS_URL",
            "https://in-the-sky.org/rss.php?feed=dfan&latitude=43.139006&longitude=-2.966625&timezone=Europe/Madrid"),
        "latitude": float(config.get("LATITUDE", "43.139006")),
        "longitude": float(config.get("LONGITUDE", "-2.966625")),
        "timezone": config.get("TIMEZONE", "Europe/Madrid"),
        "fetch_interval_minutes": int(config.get("FETCH_INTERVAL_MINUTES", "60")),
        "window_days": int(config.get("NOTIFICATION_WINDOW_DAYS", "15")),
        "db_path": config.get("DB_PATH", str(Path(__file__).parent.parent / "data" / "events.db")),
    }


# ─── Logging with Rotation ──────────────────────────────────────────────────

def setup_logging(log_dir: Optional[str] = None) -> logging.Logger:
    """Configure structured JSON logging with rotation.

    Creates logs in data/logs/ directory with daily rotation.
    Format: {"timestamp": "...", "level": "...", "message": "..."}
    """
    if log_dir is None:
        log_dir = str(Path(__file__).parent.parent / "data" / "logs")

    Path(log_dir).mkdir(parents=True, exist_ok=True)

    # Custom JSON formatter
    class JsonFormatter(logging.Formatter):
        def format(self, record):
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            if record.exc_info:
                log_entry["exception"] = self.formatException(record.exc_info)
            return json.dumps(log_entry, ensure_ascii=False)

    logger_instance = logging.getLogger("astronomical_events")
    logger_instance.setLevel(logging.INFO)

    # File handler with rotation (10MB max, keep 5 backups)
    file_handler = logging.FileHandler(
        os.path.join(log_dir, "astronomical_events.log"),
        encoding="utf-8"
    )
    file_handler.setFormatter(JsonFormatter())
    logger_instance.addHandler(file_handler)

    # Console handler (human-readable for CLI)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
    ))
    logger_instance.addHandler(console_handler)

    return logger_instance


# ─── Core Pipeline ──────────────────────────────────────────────────────────

def run_fetch_pipeline(config: dict) -> dict:
    """Execute the full fetch + classify pipeline.

    Returns stats dict with counts of fetched, new, and classified events.
    """
    db = DatabaseManager(config["db_path"])
    stats = {"fetched": 0, "new": 0, "classified": 0, "errors": 0}

    try:
        # Fetch RSS feed
        logger.info("Fetching RSS feed...")
        raw_items = fetch_rss(config["rss_url"])
        stats["fetched"] = len(raw_items) if raw_items else 0
        logger.info(f"Fetched {stats['fetched']} items from RSS")

        # Parse and store new items
        for item in raw_items:
            title = item.get("title", "")
            if not title or "error" in title.lower():
                continue

            existing = db.get_event_by_id(item.get("guid", ""))
            if existing:
                continue  # Already stored

            stats["new"] += 1

            # Parse event date from title
            import re
            match = re.match(r"(\d{1,2}) (\w+) (\d{4})", title)
            event_date = None
            if match:
                day, month_str, year = match.groups()
                months = {
                    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4,
                    "May": 5, "Jun": 6, "Jul": 7, "Aug": 8,
                    "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
                }
                month = months.get(month_str)
                if month:
                    try:
                        event_date = datetime(int(year), month, int(day))
                    except ValueError:
                        pass

            # Classify the event
            classification = classify_event(title, item.get("description", ""))

            db.insert_event(
                news_id=item.get("guid", ""),
                title=title,
                event_date=event_date if event_date else datetime.now(),
                rss_pub_date=item.get("pubDate"),
                description=item.get("description", "")[:500],
                event_type=classification["event_type"],
                priority=classification["priority"],
                visibility_level=classification.get("visibility_level"),
            )

        # Scrape thumbnails for events without them (up to 10 per run)
        unscraped = db.get_events_without_thumbnail(limit=10)
        scraped = 0
        for event in unscraped:
            try:
                page_html = fetch_event_page(event.event_page_url or "")
                if page_html:
                    page_data = parse_page(page_html)
                    if page_data and page_data.thumbnail_url:
                        db.update_thumbnail(event.news_id, page_data.thumbnail_url)
                        scraped += 1
            except Exception as e:
                logger.warning(f"Thumbnail scrape failed for {event.title}: {e}")

        stats["scraped"] = scraped

    except Exception as e:
        logger.error(f"Pipeline error: {e}", exc_info=True)
        stats["errors"] += 1
    finally:
        db.close()

    return stats


def run_notify(config: dict) -> dict:
    """Run notification dispatch. Returns stats from send_notifications."""
    config_with_window = {**config, "window_days": config.get("window_days", 15)}
    return send_notifications(config_with_window)


# ─── Scheduler Daemon ──────────────────────────────────────────────────────

class Scheduler:
    """Cron-like scheduler for astronomical events.

    Runs two jobs:
    - Fetch job: every FETCH_INTERVAL_MINUTES (default: 60)
    - Digest job: daily at 08:00 Europe/Madrid
    """

    def __init__(self, config: dict):
        self.config = config
        self._running = False
        self._last_fetch = None
        self._last_digest = None

    def _should_fetch(self) -> bool:
        """Check if enough time has passed since last fetch."""
        if self._last_fetch is None:
            return True
        elapsed = (datetime.now() - self._last_fetch).total_seconds() / 60
        return elapsed >= self.config["fetch_interval_minutes"]

    def _should_digest(self) -> bool:
        """Check if it's time for the daily digest (08:00 Europe/Madrid)."""
        now = datetime.now()
        if self._last_digest is None:
            # First run: check if we're past 08:00
            return now.hour >= 8 and now.minute >= 0

        last = self._last_digest.date()
        return now.date() > last

    def _run_cycle(self):
        """Execute one full cycle: fetch + notify.

        Each sub-job is wrapped in try/except so a failure in one
        doesn't prevent the other from running. This ensures that
        even if RSS fetching fails, notifications for previously
        cached events can still be sent.
        """
        logger.info("=" * 60)
        logger.info(f"Scheduler cycle started at {datetime.now().isoformat()}")
        logger.info("-" * 40)

        # Fetch job (isolated error handling)
        fetch_stats = {"fetched": 0, "new": 0, "errors": 0}
        if self._should_fetch():
            try:
                logger.info("Running fetch pipeline...")
                fetch_stats = run_fetch_pipeline(self.config)
                logger.info(
                    f"Fetch complete: {fetch_stats['fetched']} fetched, "
                    f"{fetch_stats['new']} new events"
                )
            except Exception as e:
                logger.error(f"Fetch pipeline failed: {e}", exc_info=True)
                fetch_stats["errors"] = 1
            finally:
                self._last_fetch = datetime.now()
        else:
            logger.debug("Skipping fetch (interval not elapsed)")

        # Notify job (always runs, even if fetch failed)
        try:
            notify_stats = run_notify(self.config)
            logger.info(
                f"Notifications: {notify_stats['sent_immediate']} immediate, "
                f"{notify_stats['sent_batch']} batched, "
                f"{notify_stats['sent_digest']} digest"
            )
        except Exception as e:
            logger.error(f"Notification dispatch failed: {e}", exc_info=True)

        # Digest job (daily at 08:00)
        if self._should_digest():
            logger.info("Running daily digest...")
            db = DatabaseManager(self.config["db_path"])
            try:
                all_events = db.get_upcoming_events(days=self.config["window_days"])
                logger.info(f"Daily digest: {len(all_events)} upcoming events in next {self.config['window_days']} days")
                self._last_digest = datetime.now()
            finally:
                db.close()

        logger.info("=" * 60)

    def run_once(self):
        """Run a single cycle and exit."""
        self._run_cycle()

    def run_daemon(self):
        """Run as a persistent daemon with signal handling and health degradation tracking."""
        self._running = True
        self._consecutive_errors = 0
        self._max_consecutive_errors = 10  # Graceful shutdown after this many errors

        logger.info(f"Scheduler daemon started (fetch interval: {self.config['fetch_interval_minutes']}min)")
        logger.info("Press Ctrl+C to stop.")

        def handle_signal(signum, frame):
            logger.info(f"Received signal {signum}, shutting down...")
            self._running = False

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        while self._running:
            try:
                self._run_cycle()
                # Reset error counter on success
                self._consecutive_errors = 0

                # Sleep until next fetch cycle (check every 30s for graceful shutdown)
                sleep_seconds = min(30, self.config["fetch_interval_minutes"] * 60)
                time.sleep(sleep_seconds)
            except Exception as e:
                self._consecutive_errors += 1
                logger.error(f"Scheduler daemon error (#{self._consecutive_errors}): {e}", exc_info=True)

                if self._consecutive_errors >= self._max_consecutive_errors:
                    logger.critical(
                        f"Max consecutive errors ({self._max_consecutive_errors}) reached. "
                        "Shutting down daemon to prevent resource exhaustion."
                    )
                    self._running = False
                else:
                    time.sleep(120)  # Wait before retrying

        logger.info("Scheduler daemon stopped.")


# ─── Health Check ────────────────────────────────────────────────────────────

def health_check(config: dict) -> dict:
    """Run a health check and return status as JSON.

    Checks: database connectivity, RSS feed reachability, last fetch time.
    Exit code 0 = healthy, 1 = degraded, 2 = unhealthy.
    """
    result = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "checks": {},
    }

    # Check database
    try:
        db = DatabaseManager(config["db_path"])
        event_count = db.get_event_count()
        recent_events = len(db.get_upcoming_events(days=7))
        db.close()
        result["checks"]["database"] = {
            "status": "ok",
            "total_events": event_count,
            "upcoming_7d": recent_events,
        }
    except Exception as e:
        result["checks"]["database"] = {"status": "error", "message": str(e)}
        result["status"] = "unhealthy"

    # Check RSS feed reachability (lightweight)
    try:
        raw_items = fetch_rss(config["rss_url"])
        result["checks"]["rss_feed"] = {
            "status": "ok",
            "items_available": len(raw_items) if raw_items else 0,
        }
    except Exception as e:
        result["checks"]["rss_feed"] = {"status": "error", "message": str(e)}
        if result["status"] != "unhealthy":
            result["status"] = "degraded"

    # Check logs directory
    log_dir = Path(__file__).parent.parent / "data" / "logs"
    if log_dir.exists():
        log_files = list(log_dir.glob("*.log"))
        result["checks"]["logging"] = {
            "status": "ok",
            "log_files": len(log_files),
        }
    else:
        result["checks"]["logging"] = {"status": "missing"}

    # Overall status
    if all(c.get("status") == "ok" for c in result["checks"].values()):
        result["status"] = "healthy"
    elif any(c.get("status") == "error" for c in result["checks"].values()):
        result["status"] = "unhealthy"
    else:
        result["status"] = "degraded"

    # Print JSON output
    print(json.dumps(result, indent=2, ensure_ascii=False))

    return result


# ─── CLI Entry Points ────────────────────────────────────────────────────────

def cmd_schedule_run_once(config: dict):
    """Run one scheduler cycle and exit."""
    setup_logging()
    logger.info("Scheduler: running single cycle")
    scheduler = Scheduler(config)
    scheduler.run_once()


def cmd_schedule_daemon(config: dict):
    """Start the scheduler daemon."""
    setup_logging()
    logger.info("Scheduler: starting daemon mode")
    scheduler = Scheduler(config)
    scheduler.run_daemon()


def cmd_health(config: dict):
    """Run health check and output JSON status."""
    result = health_check(config)
    # Exit code based on health status
    if result["status"] == "healthy":
        sys.exit(0)
    elif result["status"] == "degraded":
        sys.exit(1)
    else:
        sys.exit(2)
