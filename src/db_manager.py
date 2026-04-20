"""Database manager - SQLite operations for astronomical events."""

import sqlite3
import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """Represents an astronomical event."""
    news_id: str
    title: str
    event_date: datetime
    rss_pub_date: Optional[datetime] = None
    description: str = ""
    event_type: str = "unknown"
    priority: int = 5
    visibility_level: Optional[int] = None
    thumbnail_url: Optional[str] = None
    event_page_url: Optional[str] = None
    is_notified: bool = False

    def __post_init__(self):
        if isinstance(self.event_date, str):
            self.event_date = datetime.fromisoformat(self.event_date)


@dataclass
class FetchLogEntry:
    """Represents a fetch log entry."""
    fetched_at: datetime
    items_fetched: int
    new_items: int
    status: str
    error_message: Optional[str] = None


class DatabaseManager:
    """SQLite database manager for astronomical events."""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        """Create database tables if they don't exist."""
        cursor = self.conn.cursor()

        # Events table - stores all astronomical events
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                news_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                event_date DATETIME NOT NULL,
                rss_pub_date DATETIME,
                description TEXT DEFAULT '',
                event_type TEXT DEFAULT 'unknown',
                priority INTEGER DEFAULT 5 CHECK(priority BETWEEN 1 AND 5),
                visibility_level INTEGER CHECK(visibility_level IS NULL OR (visibility_level BETWEEN 1 AND 5)),
                thumbnail_url TEXT,
                event_page_url TEXT,
                is_notified INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Fetch log table - tracks RSS fetch operations
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fetch_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                items_fetched INTEGER DEFAULT 0,
                new_items INTEGER DEFAULT 0,
                status TEXT DEFAULT 'unknown',
                error_message TEXT
            )
        """)

        # Config table - stores system configuration
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        self.conn.commit()
        logger.info("Database tables created/verified")

    def insert_event(self, news_id: str, title: str, event_date: datetime,
                     rss_pub_date: Optional[str] = None, description: str = "",
                     event_type: str = "unknown", priority: int = 5,
                     visibility_level: Optional[int] = None,
                     thumbnail_url: Optional[str] = None,
                     event_page_url: Optional[str] = None) -> bool:
        """Insert or update an event in the database.

        Args:
            news_id: Unique identifier from RSS feed
            title: Event title
            event_date: When the event occurs
            rss_pub_date: Original publication date string
            description: Plain text description
            event_type: Classified type (eclipse, meteor_shower, etc.)
            priority: Priority level 1-5
            visibility_level: Visibility requirement 1-5
            thumbnail_url: URL to event image
            event_page_url: Link to full event page

        Returns:
            True if inserted/updated successfully
        """
        cursor = self.conn.cursor()

        # Convert datetime objects to ISO format strings for SQLite
        event_date_str = event_date.isoformat() if isinstance(event_date, datetime) else str(event_date)

        try:
            cursor.execute("""
                INSERT INTO events (news_id, title, event_date, rss_pub_date, description,
                                   event_type, priority, visibility_level, thumbnail_url,
                                   event_page_url, is_notified)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(news_id) DO UPDATE SET
                    title=excluded.title,
                    event_date=excluded.event_date,
                    description=excluded.description,
                    event_type=excluded.event_type,
                    priority=excluded.priority,
                    visibility_level=excluded.visibility_level,
                    thumbnail_url=excluded.thumbnail_url,
                    event_page_url=excluded.event_page_url,
                    updated_at=CURRENT_TIMESTAMP
            """, (news_id, title, event_date_str, rss_pub_date, description,
                  event_type, priority, visibility_level, thumbnail_url, event_page_url))

            self.conn.commit()
            logger.info(f"Inserted/updated event: {news_id} - {title[:60]}")
            return True

        except Exception as e:
            logger.error(f"Failed to insert event {news_id}: {e}")
            self.conn.rollback()
            return False

    def get_upcoming_events(self, days: int = 15) -> list[Event]:
        """Get events within the next N days.

        Args:
            days: Number of days into the future (default 15)

        Returns:
            List of Event objects sorted by event_date
        """
        cursor = self.conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        future = (datetime.now().replace(hour=0, minute=0, second=0) +
                  __import__("datetime").timedelta(days=days)).strftime("%Y-%m-%d")

        cursor.execute("""
            SELECT * FROM events
            WHERE event_date >= ? AND event_date <= ?
            ORDER BY event_date ASC, priority ASC
        """, (today, future))

        return [self._row_to_event(row) for row in cursor.fetchall()]

    def get_unnotified_events(self, priority_max: int = 3) -> list[Event]:
        """Get unnotified events with priority <= priority_max.

        Args:
            priority_max: Maximum priority level to include (1=critical, 5=minor)

        Returns:
            List of Event objects sorted by event_date
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM events
            WHERE is_notified = 0 AND priority <= ?
            ORDER BY priority ASC, event_date ASC
        """, (priority_max,))

        return [self._row_to_event(row) for row in cursor.fetchall()]

    def mark_as_notified(self, news_id: str) -> bool:
        """Mark an event as notified.

        Args:
            news_id: Event identifier

        Returns:
            True if updated successfully
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                UPDATE events SET is_notified = 1, updated_at = CURRENT_TIMESTAMP
                WHERE news_id = ?
            """, (news_id,))
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to mark event {news_id} as notified: {e}")
            self.conn.rollback()
            return False

    def count_events(self) -> int:
        """Count total events in database."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM events")
        return cursor.fetchone()[0]

    def count_unnotified(self) -> int:
        """Count unnotified events."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM events WHERE is_notified = 0")
        return cursor.fetchone()[0]

    def log_fetch(self, items_fetched: int, new_items: int, status: str,
                  error_message: Optional[str] = None):
        """Log a fetch operation.

        Args:
            items_fetched: Total items fetched from RSS
            new_items: Number of new events inserted
            status: success/partial/failed
            error_message: Error details if failed
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO fetch_log (items_fetched, new_items, status, error_message)
                VALUES (?, ?, ?, ?)
            """, (items_fetched, new_items, status, error_message))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Failed to log fetch: {e}")

    def get_fetch_history(self, limit: int = 10) -> list[FetchLogEntry]:
        """Get recent fetch history.

        Args:
            limit: Number of entries to return (default 10)

        Returns:
            List of FetchLogEntry objects sorted by fetched_at DESC
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM fetch_log
            ORDER BY fetched_at DESC
            LIMIT ?
        """, (limit,))

        return [FetchLogEntry(
            fetched_at=row["fetched_at"],
            items_fetched=row["items_fetched"],
            new_items=row["new_items"],
            status=row["status"],
            error_message=row["error_message"]
        ) for row in cursor.fetchall()]

    def get_event_by_id(self, news_id: str) -> Optional[Event]:
        """Get a single event by its ID.

        Args:
            news_id: Event identifier

        Returns:
            Event object or None if not found
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM events WHERE news_id = ?", (news_id,))
        row = cursor.fetchone()
        return self._row_to_event(row) if row else None

    def get_events_by_type(self, event_type: str) -> list[Event]:
        """Get all events of a specific type.

        Args:
            event_type: Event classification (eclipse, meteor_shower, etc.)

        Returns:
            List of Event objects sorted by event_date
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM events WHERE event_type = ?
            ORDER BY event_date ASC
        """, (event_type,))

        return [self._row_to_event(row) for row in cursor.fetchall()]

    def get_events_by_priority(self, priority: int) -> list[Event]:
        """Get all events with a specific priority level.

        Args:
            priority: Priority level 1-5

        Returns:
            List of Event objects sorted by event_date
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM events WHERE priority = ?
            ORDER BY event_date ASC
        """, (priority,))

        return [self._row_to_event(row) for row in cursor.fetchall()]

    def _row_to_event(self, row: sqlite3.Row) -> Event:
        """Convert a database row to an Event object."""
        return Event(
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

    def close(self):
        """Close the database connection."""
        self.conn.close()
