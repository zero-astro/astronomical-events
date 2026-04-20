"""SQLite database manager for astronomical events."""

import sqlite3
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class EventRecord:
    """Represents an event stored in the database."""
    id: int
    news_id: str
    title: str
    event_date: datetime
    rss_pub_date: datetime
    description: str
    event_type: str
    priority: int
    visibility_level: Optional[int] = None
    thumbnail_url: Optional[str] = None
    event_page_url: str = ""
    is_notified: bool = False
    created_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "news_id": self.news_id,
            "title": self.title,
            "event_date": self.event_date.isoformat(),
            "rss_pub_date": self.rss_pub_date.isoformat(),
            "description": self.description[:200] + "..." if len(self.description) > 200 else self.description,
            "event_type": self.event_type,
            "priority": self.priority,
            "visibility_level": self.visibility_level,
            "thumbnail_url": self.thumbnail_url,
            "event_page_url": self.event_page_url,
            "is_notified": self.is_notified,
        }


@dataclass
class FetchLog:
    """Represents a fetch operation log entry."""
    id: int
    fetched_at: datetime
    items_fetched: int
    new_items: int
    status: str
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "fetched_at": self.fetched_at.isoformat(),
            "items_fetched": self.items_fetched,
            "new_items": self.new_items,
            "status": self.status,
            "error_message": self.error_message,
        }


class DatabaseManager:
    """Manages SQLite database operations."""

    def __init__(self, db_path: str = "data/events.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connect()

    def _connect(self) -> sqlite3.Connection:
        """Create database connection and ensure schema exists."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")  # Better concurrency
        conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables(conn)
        self.conn = conn
        return conn

    def _create_tables(self, conn: sqlite3.Connection):
        """Create all database tables if they don't exist."""
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                news_id TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                event_date DATETIME NOT NULL,
                rss_pub_date DATETIME NOT NULL,
                description TEXT,
                event_type TEXT NOT NULL DEFAULT 'unknown',
                priority INTEGER NOT NULL DEFAULT 5,
                visibility_level INTEGER CHECK(visibility_level BETWEEN 1 AND 5),
                thumbnail_url TEXT,
                event_page_url TEXT NOT NULL,
                is_notified BOOLEAN DEFAULT FALSE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS fetch_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                items_fetched INTEGER,
                new_items INTEGER,
                status TEXT NOT NULL,
                error_message TEXT
            );

            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_events_event_date ON events(event_date);
            CREATE INDEX IF NOT EXISTS idx_events_priority ON events(priority);
            CREATE INDEX IF NOT EXISTS idx_events_notified ON events(is_notified);
            CREATE INDEX IF NOT EXISTS idx_fetch_log_fetched_at ON fetch_log(fetched_at DESC);

            INSERT OR IGNORE INTO config (key, value) VALUES
                ('latitude', '43.139006'),
                ('longitude', '-2.966625'),
                ('timezone', 'Europe/Madrid'),
                ('window_days', '15');
        """)
        conn.commit()

    def insert_event(self, news_id: str, title: str, event_date: datetime,
                      rss_pub_date: datetime, description: str, event_type: str = "unknown",
                      priority: int = 5, visibility_level: Optional[int] = None,
                      thumbnail_url: Optional[str] = None, event_page_url: str = "") -> bool:
        """Insert a new event. Returns True if inserted, False if duplicate."""
        try:
            self.conn.execute(
                """INSERT INTO events 
                   (news_id, title, event_date, rss_pub_date, description, event_type, priority, visibility_level, thumbnail_url, event_page_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (news_id, title, event_date.isoformat(), rss_pub_date.isoformat(),
                 description, event_type, priority, visibility_level, thumbnail_url, event_page_url)
            )
            self.conn.commit()
            logger.info(f"Inserted event: {news_id} - {title[:50]}")
            return True
        except sqlite3.IntegrityError:
            logger.debug(f"Event already exists: {news_id}")
            return False

    def get_event(self, news_id: str) -> Optional[EventRecord]:
        """Get a single event by news_id."""
        row = self.conn.execute("SELECT * FROM events WHERE news_id = ?", (news_id,)).fetchone()
        if not row:
            return None
        return self._row_to_event(row)

    def get_upcoming_events(self, days: int = 15, priority_max: Optional[int] = None) -> list[EventRecord]:
        """Get upcoming events within the specified window.
        
        Args:
            days: Number of days to look ahead
            priority_max: Only return events with priority <= this value (None = all)
            
        Returns:
            List of EventRecord sorted by event_date ascending
        """
        now = datetime.now()
        future = now + timedelta(days=days)
        
        query = "SELECT * FROM events WHERE event_date BETWEEN ? AND ?"
        params = [now.isoformat(), future.isoformat()]
        
        if priority_max is not None:
            query += " AND priority <= ?"
            params.append(priority_max)
            
        query += " ORDER BY event_date ASC, priority ASC"
        
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_event(row) for row in rows]

    def get_all_events(self, limit: int = 100) -> list[EventRecord]:
        """Get all events (most recent first)."""
        rows = self.conn.execute(
            "SELECT * FROM events ORDER BY event_date DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def get_unnotified_events(self, priority_max: int = 3) -> list[EventRecord]:
        """Get events that haven't been notified yet."""
        rows = self.conn.execute(
            "SELECT * FROM events WHERE is_notified = FALSE AND priority <= ? ORDER BY event_date ASC",
            (priority_max,)
        ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def mark_notified(self, news_id: str) -> bool:
        """Mark an event as notified."""
        cursor = self.conn.execute(
            "UPDATE events SET is_notified = TRUE WHERE news_id = ?", (news_id,)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def log_fetch(self, items_fetched: int, new_items: int, status: str, error_message: Optional[str] = None):
        """Log a fetch operation."""
        self.conn.execute(
            "INSERT INTO fetch_log (items_fetched, new_items, status, error_message) VALUES (?, ?, ?, ?)",
            (items_fetched, new_items, status, error_message)
        )
        self.conn.commit()

    def get_fetch_history(self, limit: int = 10) -> list[FetchLog]:
        """Get recent fetch log entries."""
        rows = self.conn.execute(
            "SELECT * FROM fetch_log ORDER BY fetched_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_fetch_log(row) for row in rows]

    def get_config(self, key: str) -> Optional[str]:
        """Get a config value."""
        row = self.conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_config(self, key: str, value: str):
        """Set or update a config value."""
        self.conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, CURRENT_TIMESTAMP)",
            (key, value)
        )
        # Fix: the above doesn't set updated_at properly with INSERT OR REPLACE
        self.conn.execute(
            "UPDATE config SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?",
            (value, key)
        )
        self.conn.commit()

    def count_events(self) -> int:
        """Count total events in database."""
        row = self.conn.execute("SELECT COUNT(*) FROM events").fetchone()
        return row[0] if row else 0

    def count_unnotified(self) -> int:
        """Count unnotified events."""
        row = self.conn.execute("SELECT COUNT(*) FROM events WHERE is_notified = FALSE").fetchone()
        return row[0] if row else 0

    def cleanup_old_events(self, days: int = 30):
        """Remove events older than specified days (soft delete by marking)."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor = self.conn.execute(
            "DELETE FROM events WHERE event_date < ? AND is_notified = TRUE",
            (cutoff,)
        )
        self.conn.commit()
        logger.info(f"Cleaned up {cursor.rowcount} old events")

    def _row_to_event(self, row) -> EventRecord:
        """Convert a database row to an EventRecord."""
        return EventRecord(
            id=row["id"],
            news_id=row["news_id"],
            title=row["title"],
            event_date=datetime.fromisoformat(row["event_date"]),
            rss_pub_date=datetime.fromisoformat(row["rss_pub_date"]),
            description=row["description"] or "",
            event_type=row["event_type"],
            priority=row["priority"],
            visibility_level=row["visibility_level"],
            thumbnail_url=row["thumbnail_url"],
            event_page_url=row["event_page_url"],
            is_notified=bool(row["is_notified"]),
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
        )

    def _row_to_fetch_log(self, row) -> FetchLog:
        """Convert a database row to a FetchLog."""
        return FetchLog(
            id=row["id"],
            fetched_at=datetime.fromisoformat(row["fetched_at"]),
            items_fetched=row["items_fetched"],
            new_items=row["new_items"],
            status=row["status"],
            error_message=row["error_message"],
        )

    def close(self):
        """Close database connection."""
        if hasattr(self, "conn"):
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
