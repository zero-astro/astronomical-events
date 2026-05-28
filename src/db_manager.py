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
    # Phase 6: Rich metadata fields
    rich_description_en: str = ""
    viewing_info_en: str = ""
    event_details_json: str = ""

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

    def __init__(self, db_path: str, max_retries: int = 3):
        """Initialize database connection with WAL mode and retry logic.

        Args:
            db_path: Path to the SQLite database file
            max_retries: Maximum number of connection attempts (default 3)
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._max_retries = max_retries
        self.conn = None
        self._connect_with_retry()
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
        self._migrate_schema()

    def _connect_with_retry(self):
        """Connect to SQLite with retry logic for transient failures."""
        import time as _time
        last_exception = None

        for attempt in range(self._max_retries + 1):
            try:
                self.conn = sqlite3.connect(
                    str(self.db_path),
                    timeout=30.0,  # Wait up to 30s for lock
                    isolation_level=None,  # Autocommit mode
                )
                # Enable WAL mode for better concurrent read/write performance
                self.conn.execute("PRAGMA journal_mode=WAL")
                # Enable busy timeout (SQLite will retry on locked DB)
                self.conn.execute("PRAGMA busy_timeout=5000")
                # Optimize for write-heavy workloads
                self.conn.execute("PRAGMA synchronous=NORMAL")
                logger.info(
                    f"Database connected at {self.db_path} "
                    f"(attempt {attempt + 1}/{self._max_retries + 1})"
                )
                return
            except Exception as e:
                last_exception = e
                if attempt < self._max_retries:
                    delay = 0.5 * (2 ** attempt)  # Exponential backoff: 0.5s, 1s, 2s
                    logger.warning(
                        f"Database connection failed (attempt {attempt + 1}/{self._max_retries + 1}): {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    _time.sleep(delay)
                else:
                    logger.error(f"Database connection failed after {self._max_retries + 1} attempts: {e}")

        raise last_exception  # type: ignore[misc]

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
                rich_description_en TEXT DEFAULT '',
                viewing_info_en TEXT DEFAULT '',
                event_details_json TEXT DEFAULT '',
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

        # Translations table - i18n cached translations (Phase 0.1)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS translations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                news_id TEXT NOT NULL,
                source_lang TEXT DEFAULT 'en',
                target_lang TEXT NOT NULL,
                translated_title TEXT,
                translated_description TEXT,
                provider TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(news_id, target_lang)
            )
        """)

        # Indexes for fast translation lookup (Phase 0.2)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_translations_news_id ON translations(news_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_translations_target_lang ON translations(target_lang)"
        )

        # Initialize default target_languages config if not present (Phase 0.3)
        try:
            cursor.execute(
                "INSERT OR IGNORE INTO config (key, value) VALUES ('target_languages', '[\\\"eu\\\"]')"
            )
        except Exception:
            pass

        # Translations checkpoint table — resume capability for long translation runs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS translations_checkpoint (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lang TEXT NOT NULL UNIQUE,
                last_processed_idx INTEGER DEFAULT 0,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Translation cache table — hash-based dedup to avoid re-translating identical content
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS translation_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_lang TEXT DEFAULT 'en',
                target_lang TEXT NOT NULL,
                field_type TEXT NOT NULL CHECK(field_type IN ('title','description','rich_description','viewing_info')),
                source_hash TEXT NOT NULL,
                cached_text TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source_lang, target_lang, field_type, source_hash)
            )
        """)

        # Index for fast cache lookup by (target_lang, field_type, cached_text) — used to find duplicates
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_cache_lookup
            ON translation_cache(target_lang, field_type, source_hash)
        """)

        self.conn.commit()
        logger.info("Database tables created/verified")

    def _migrate_schema(self):
        """Add new columns for Phase 6 if they don't exist."""
        cursor = self.conn.cursor()
        
        # Check which columns are missing
        cursor.execute("PRAGMA table_info(events)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        
        new_columns = {
            'rich_description_en': 'TEXT DEFAULT \"\"',
            'viewing_info_en': 'TEXT DEFAULT \"\"',
            'event_details_json': 'TEXT DEFAULT \"\"',
        }
        
        for col_name, col_def in new_columns.items():
            if col_name not in existing_columns:
                try:
                    cursor.execute(f"ALTER TABLE events ADD COLUMN {col_name} {col_def}")
                    logger.info(f"Added column: {col_name}")
                except Exception as e:
                    logger.warning(f"Could not add column {col_name}: {e}")
        
        # Add new columns to translations table
        cursor.execute("PRAGMA table_info(translations)")
        existing_trans_cols = {row[1] for row in cursor.fetchall()}
        
        new_trans_columns = {
            'translated_rich_description': 'TEXT',
            'translated_viewing_info': 'TEXT',
        }
        
        for col_name, col_def in new_trans_columns.items():
            if col_name not in existing_trans_cols:
                try:
                    cursor.execute(f"ALTER TABLE translations ADD COLUMN {col_name} {col_def}")
                    logger.info(f"Added translation column: {col_name}")
                except Exception as e:
                    logger.warning(f"Could not add translation column {col_name}: {e}")
        
        self.conn.commit()

    def _execute_with_retry(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute SQL with retry logic for transient database errors.

        Handles SQLiteBusyError and database locked errors by retrying
        with exponential backoff. This is critical for concurrent access
        from the scheduler daemon.

        Args:
            sql: SQL query string
            params: Query parameters

        Returns:
            Cursor object
        """
        import time as _time
        last_exception = None

        for attempt in range(self._max_retries + 1):
            try:
                return self.conn.execute(sql, params)
            except sqlite3.OperationalError as e:
                last_exception = e
                if "database is locked" in str(e).lower() or "busy" in str(e).lower():
                    if attempt < self._max_retries:
                        delay = 0.25 * (1.5 ** attempt)  # Gentle backoff: 0.25s, 0.375s, 0.56s
                        logger.warning(f"Database locked (attempt {attempt + 1}/{self._max_retries + 1}). Retrying in {delay:.1f}s...")
                        _time.sleep(delay)
                    else:
                        logger.error(f"Database locked after {self._max_retries + 1} attempts: {e}")
                else:
                    raise
        raise last_exception  # type: ignore[misc]

    def insert_event(self, news_id: str, title: str, event_date: datetime,
                     rss_pub_date: Optional[str] = None, description: str = "",
                     event_type: str = "unknown", priority: int = 5,
                     visibility_level: Optional[int] = None,
                     thumbnail_url: Optional[str] = None,
                     event_page_url: Optional[str] = None,
                     rich_description_en: str = "",
                     viewing_info_en: str = "",
                     event_details_json: str = "") -> bool:
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
            rich_description_en: Detailed description in English (Phase 6)
            viewing_info_en: Viewing information in English (Phase 6)
            event_details_json: Structured metadata JSON (Phase 6)

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
                                   event_page_url, is_notified, rich_description_en,
                                   viewing_info_en, event_details_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                ON CONFLICT(news_id) DO UPDATE SET
                    title=excluded.title,
                    event_date=excluded.event_date,
                    description=excluded.description,
                    event_type=excluded.event_type,
                    priority=excluded.priority,
                    visibility_level=excluded.visibility_level,
                    thumbnail_url=excluded.thumbnail_url,
                    event_page_url=excluded.event_page_url,
                    rich_description_en=excluded.rich_description_en,
                    viewing_info_en=excluded.viewing_info_en,
                    event_details_json=excluded.event_details_json,
                    updated_at=CURRENT_TIMESTAMP
            """, (news_id, title, event_date_str, rss_pub_date, description,
                  event_type, priority, visibility_level, thumbnail_url, event_page_url,
                  rich_description_en, viewing_info_en, event_details_json))

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

    def get_events_without_thumbnail(self, limit: int = 10) -> list[Event]:
        """Get events that don't have a thumbnail URL yet.

        Args:
            limit: Maximum number of events to return (default 10)

        Returns:
            List of Event objects without thumbnails
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM events
            WHERE thumbnail_url IS NULL OR thumbnail_url = ''
            ORDER BY event_date ASC
            LIMIT ?
        """, (limit,))
        return [self._row_to_event(row) for row in cursor.fetchall()]

    def update_thumbnail(self, news_id: str, thumbnail_url: str) -> bool:
        """Update the thumbnail URL for an event.

        Args:
            news_id: Event identifier
            thumbnail_url: New thumbnail URL

        Returns:
            True if updated successfully
        """
        try:
            self._execute_with_retry(
                "UPDATE events SET thumbnail_url = ?, updated_at = CURRENT_TIMESTAMP WHERE news_id = ?",
                (thumbnail_url, news_id)
            )
            logger.info(f"Updated thumbnail for event {news_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to update thumbnail for {news_id}: {e}")
            return False

    def update_event_metadata(self, news_id: str, **fields) -> bool:
        """Update Phase 6 rich metadata fields for an event.

        Args:
            news_id: Event identifier
            **fields: Key-value pairs of fields to update
                    (rich_description_en, viewing_info_en, event_details_json)

        Returns:
            True if updated successfully
        """
        if not fields:
            return False

        # Build dynamic UPDATE query
        set_clause = ", ".join(f"{k} = ?" for k in fields.keys())
        set_clause += ", updated_at = CURRENT_TIMESTAMP"
        values = list(fields.values()) + [news_id]

        try:
            self._execute_with_retry(
                f"UPDATE events SET {set_clause} WHERE news_id = ?",
                tuple(values)
            )
            logger.info(f"Updated metadata for event {news_id}: {', '.join(fields.keys())}")
            return True
        except Exception as e:
            logger.error(f"Failed to update metadata for {news_id}: {e}")
            return False

    def get_event_by_title(self, title: str) -> Optional[Event]:
        """Get an event by its title (fuzzy match).

        Args:
            title: Event title to search for

        Returns:
            Event object or None if not found
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM events WHERE title LIKE ? LIMIT 1
        """, (f"%{title[:50]}%",))
        row = cursor.fetchone()
        return self._row_to_event(row) if row else None

    def get_event_count(self) -> int:
        """Alias for count_events() — used by health_check."""
        return self.count_events()

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
            rich_description_en=row["rich_description_en"] or "",
            viewing_info_en=row["viewing_info_en"] or "",
            event_details_json=row["event_details_json"] or "",
        )


    def get_translation(self, news_id: str, target_lang: str):
        """Get a cached translation for an event.

        Args:
            news_id: Event identifier
            target_lang: Target language code (e.g., 'eu')

        Returns:
            Dict with translation data or None if not found
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM translations WHERE news_id = ? AND target_lang = ?",
            (news_id, target_lang)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def insert_or_update_translation(self, news_id: str, target_lang: str,
                                      translated_title: str = "",
                                      translated_description: str = "",
                                      provider: str = "",
                                      translated_rich_description: str = "",
                                      translated_viewing_info: str = "") -> bool:
        """Insert or update a translation for an event.

        Args:
            news_id: Event identifier
            target_lang: Target language code
            translated_title: Translated title text
            translated_description: Translated description text (from RSS)
            provider: Translation provider name (e.g., 'lm-studio')
            translated_rich_description: Translated rich description (Phase 6)
            translated_viewing_info: Translated viewing info (Phase 6)

        Returns:
            True if successful
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO translations (news_id, target_lang, translated_title,
                                          translated_description, provider,
                                          translated_rich_description, translated_viewing_info)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(news_id, target_lang) DO UPDATE SET
                    translated_title=excluded.translated_title,
                    translated_description=excluded.translated_description,
                    provider=excluded.provider,
                    translated_rich_description=excluded.translated_rich_description,
                    translated_viewing_info=excluded.translated_viewing_info,
                    created_at=CURRENT_TIMESTAMP
            """, (news_id, target_lang, translated_title, translated_description,
                  provider, translated_rich_description, translated_viewing_info))
            self.conn.commit()
            logger.info(f"Translation stored: {news_id} -> {target_lang}")
            return True
        except Exception as e:
            logger.error(f"Failed to store translation for {news_id}: {e}")
            self.conn.rollback()
            return False

    def has_valid_translation(self, news_id: str, target_lang: str) -> bool:
        """Check if an event has a complete Basque (or other language) translation.

        A valid translation requires non-empty translated_title AND
        non-empty translated_description fields.

        Args:
            news_id: Event identifier
            target_lang: Target language code (e.g., 'eu')

        Returns:
            True if both title and description are non-empty, False otherwise
        """
        row = self.get_translation(news_id, target_lang)
        if row is None:
            return False

        title = (row.get("translated_title") or "").strip()
        desc = (row.get("translated_description") or "").strip()

        if not title:
            logger.debug(f"Empty translated_title for {news_id}/{target_lang}")
            return False
        if not desc:
            logger.debug(f"Empty translated_description for {news_id}/{target_lang}")
            return False

        return True

    def get_events_with_valid_translation(self, target_langs: list[str]) -> list[Event]:
        """Get all upcoming events that have valid translations for given languages.

        An event is considered to have a valid translation if ALL specified
        target languages have non-empty title AND description fields.

        Args:
            target_langs: List of language codes (e.g., ['eu'])

        Returns:
            List of Event objects with valid translations, sorted by date
        """
        if not target_langs:
            return []

        cursor = self.conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        future = (datetime.now() + __import__("datetime").timedelta(days=30)).strftime("%Y-%m-%d")

        # Get all upcoming events
        cursor.execute(
            "SELECT * FROM events WHERE event_date >= ? AND event_date <= ? ORDER BY event_date ASC",
            (today, future)
        )
        all_events = [self._row_to_event(row) for row in cursor.fetchall()]

        # Filter: keep only events with valid translations for ALL target languages
        valid_events = []
        for event in all_events:
            has_all = True
            for lang in target_langs:
                if not self.has_valid_translation(event.news_id, lang):
                    has_all = False
                    logger.debug(f"Event {event.news_id} missing valid translation for {lang}")
                    break
            if has_all:
                valid_events.append(event)

        return valid_events

    def get_events_needing_translation(self, target_langs: list[str]) -> list[Event]:
        """Get events that don't have translations for given target languages.

        Args:
            target_langs: List of language codes to check (e.g., ['eu', 'ca'])

        Returns:
            List of Event objects needing translation
        """
        if not target_langs:
            return []

        placeholders = ",".join("?" for _ in target_langs)
        cursor = self.conn.cursor()
        cursor.execute(f"""
            SELECT DISTINCT e.* FROM events e
            WHERE NOT EXISTS (
                SELECT 1 FROM translations t
                WHERE t.news_id = e.news_id AND t.target_lang IN ({placeholders})
            )
            ORDER BY e.event_date ASC
        """, target_langs)

        return [self._row_to_event(row) for row in cursor.fetchall()]

    def cleanup_past_events(self, keep_days: int = 0) -> dict:
        """Remove events that have already passed from the database.

        Deletes both event rows and their associated translations to maintain
        referential integrity. Only keeps events within keep_days from today.

        Args:
            keep_days: Number of days to keep past events (default 0 = delete all past)

        Returns:
            Dict with counts of deleted events and translations
        """
        cursor = self.conn.cursor()
        cutoff_date = (datetime.now() - __import__("datetime").timedelta(days=keep_days)).strftime("%Y-%m-%d")

        # First delete translations for past events (foreign key order)
        cursor.execute(f"""
            DELETE FROM translations
            WHERE news_id IN (
                SELECT news_id FROM events WHERE event_date < ?
            )
        """, (cutoff_date,))
        translations_deleted = cursor.rowcount

        # Then delete past events
        cursor.execute(
            "DELETE FROM events WHERE event_date < ?",
            (cutoff_date,)
        )
        events_deleted = cursor.rowcount

        self.conn.commit()
        logger.info(f"Cleanup: {events_deleted} events + {translations_deleted} translations removed")

        return {
            "events_deleted": events_deleted,
            "translations_deleted": translations_deleted,
        }

    def get_checkpoint(self, lang: str) -> int:
        """Get the last processed index for a language checkpoint.

        Args:
            lang: Target language code (e.g., 'eu')

        Returns:
            Last processed index (0 if no checkpoint exists)
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT last_processed_idx FROM translations_checkpoint WHERE lang = ?",
            (lang,)
        )
        row = cursor.fetchone()
        return row["last_processed_idx"] if row else 0

    def update_checkpoint(self, lang: str, idx: int) -> bool:
        """Update the checkpoint for a language.

        Args:
            lang: Target language code (e.g., 'eu')
            idx: Index to mark as last processed

        Returns:
            True if updated successfully
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO translations_checkpoint (lang, last_processed_idx)
                VALUES (?, ?)
                ON CONFLICT(lang) DO UPDATE SET
                    last_processed_idx=excluded.last_processed_idx,
                    updated_at=CURRENT_TIMESTAMP
            """, (lang, idx))
            self.conn.commit()
            logger.info(f"Checkpoint updated: {lang} -> index {idx}")
            return True
        except Exception as e:
            logger.error(f"Failed to update checkpoint for {lang}: {e}")
            self.conn.rollback()
            return False

    def reset_checkpoint(self, lang: str) -> bool:
        """Reset the checkpoint for a language (start from 0).

        Args:
            lang: Target language code (e.g., 'eu')

        Returns:
            True if reset successfully
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO translations_checkpoint (lang, last_processed_idx)
                VALUES (?, 0)
                ON CONFLICT(lang) DO UPDATE SET
                    last_processed_idx=0,
                    updated_at=CURRENT_TIMESTAMP
            """, (lang,))
            self.conn.commit()
            logger.info(f"Checkpoint reset: {lang} -> index 0")
            return True
        except Exception as e:
            logger.error(f"Failed to reset checkpoint for {lang}: {e}")
            self.conn.rollback()
            return False

    # ── Translation Cache (T1) ─────────────────────────────────────────────

    @staticmethod
    def _hash_text(text: str) -> str:
        """Compute a SHA-256 hash of text for cache key generation."""
        import hashlib
        return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()[:16]

    def get_cached_translation(
        self,
        source_text: str,
        target_lang: str,
        field_type: str = "description",
        source_lang: str = "en",
    ) -> Optional[str]:
        """Look up a cached translation for the given source text.

        Args:
            source_text: The original (source-language) text to look up.
            target_lang: Target language code (e.g., 'eu').
            field_type: One of 'title', 'description', 'rich_description', 'viewing_info'.
            source_lang: Source language code (default 'en').

        Returns:
            Cached translated text, or None if not found.
        """
        source_hash = self._hash_text(source_text)
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT cached_text FROM translation_cache "
            "WHERE source_lang = ? AND target_lang = ? AND field_type = ? AND source_hash = ?",
            (source_lang, target_lang, field_type, source_hash),
        )
        row = cursor.fetchone()
        if row:
            logger.debug(f"Cache HIT: {field_type} '{source_text[:40]}...' -> {target_lang}")
            return row["cached_text"]
        logger.debug(f"Cache MISS: {field_type} '{source_text[:40]}...' -> {target_lang}")
        return None

    def store_translation_cache(
        self,
        source_text: str,
        translated_text: str,
        target_lang: str,
        field_type: str = "description",
        source_lang: str = "en",
    ) -> bool:
        """Store a translation result in the cache.

        Args:
            source_text: The original (source-language) text.
            translated_text: The translated text to cache.
            target_lang: Target language code.
            field_type: One of 'title', 'description', 'rich_description', 'viewing_info'.
            source_lang: Source language code (default 'en').

        Returns:
            True if stored successfully (or already existed).
        """
        source_hash = self._hash_text(source_text)
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO translation_cache
                    (source_lang, target_lang, field_type, source_hash, cached_text)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_lang, target_lang, field_type, source_hash) DO NOTHING
            """, (source_lang, target_lang, field_type, source_hash, translated_text))
            self.conn.commit()
            if cursor.rowcount > 0:
                logger.debug(f"Cache STORED: {field_type} '{source_text[:40]}...' -> {target_lang}")
            return True
        except Exception as e:
            logger.error(f"Failed to store cache for {field_type}: {e}")
            self.conn.rollback()
            return False

    def invalidate_cache(
        self,
        news_id: Optional[str] = None,
        target_lang: Optional[str] = None,
        field_type: Optional[str] = None,
    ) -> int:
        """Invalidate (delete) cached translations.

        Args:
            news_id: If set, only invalidate cache entries related to this event's fields.
                     Note: the cache table does not store news_id directly; we clear all
                     entries for the given target_lang and/or field_type as a proxy.
            target_lang: Clear cache for this language (all field types).
            field_type: Clear cache for this field type (all languages).

        Returns:
            Number of rows deleted.
        """
        cursor = self.conn.cursor()
        conditions = []
        params = []

        if target_lang:
            conditions.append("target_lang = ?")
            params.append(target_lang)
        if field_type:
            conditions.append("field_type = ?")
            params.append(field_type)

        if not conditions:
            # No filter — clear entire cache
            cursor.execute("DELETE FROM translation_cache")
            count = cursor.rowcount
            self.conn.commit()
            logger.info(f"Cache cleared entirely ({count} rows)")
            return count

        sql = f"DELETE FROM translation_cache WHERE {' AND '.join(conditions)}"
        cursor.execute(sql, params)
        count = cursor.rowcount
        self.conn.commit()
        logger.info(f"Cache invalidated: {count} rows removed")
        return count

    def close(self):
        """Close the database connection."""
        self.conn.close()
