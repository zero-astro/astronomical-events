"""Integration tests for database manager module (db_manager.py)."""

import sys
import os
import unittest
import tempfile
from datetime import datetime, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from db_manager import DatabaseManager, Event


class TestDbManager(unittest.TestCase):
    """Test cases for the DatabaseManager class."""

    def setUp(self):
        """Create a temporary database for each test."""
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test_events.db')
        self.db = DatabaseManager(self.db_path)

    def tearDown(self):
        """Close the database connection."""
        self.db.close()

    def test_insert_and_get_event(self):
        """Insert an event and retrieve it via get_upcoming_events."""
        now = datetime.now()
        result = self.db.insert_event(
            news_id='test_001',
            title='Test Event',
            event_date=now + timedelta(days=3),
            description='A test event.',
            event_type='eclipse',
            priority=2,
        )
        self.assertTrue(result)

        events = self.db.get_upcoming_events(days=7)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].news_id, 'test_001')
        self.assertEqual(events[0].title, 'Test Event')
        self.assertEqual(events[0].event_type, 'eclipse')

    def test_mark_as_notified(self):
        """Marking an event as notified should update the database."""
        now = datetime.now()
        self.db.insert_event(
            news_id='test_002',
            title='Notifiable Event',
            event_date=now + timedelta(days=1),
        )

        result = self.db.mark_as_notified('test_002')
        self.assertTrue(result)

        events = self.db.get_unnotified_events()
        self.assertEqual(len(events), 0)

    def test_count_events(self):
        """count_events should return the correct number."""
        now = datetime.now()
        self.db.insert_event('c1', 'Event A', now + timedelta(days=1))
        self.db.insert_event('c2', 'Event B', now + timedelta(days=2))

        count = self.db.count_events()
        self.assertEqual(count, 2)

    def test_count_unnotified(self):
        """count_unnotified should return unnotified event count."""
        now = datetime.now()
        self.db.insert_event('u1', 'Unnotified A', now + timedelta(days=1))
        self.db.insert_event('u2', 'Unnotified B', now + timedelta(days=2))

        self.assertEqual(self.db.count_unnotified(), 2)

        self.db.mark_as_notified('u1')
        self.assertEqual(self.db.count_unnotified(), 1)

    def test_log_and_get_fetch_history(self):
        """Logging a fetch should be retrievable via get_fetch_history."""
        import time
        self.db.log_fetch(items_fetched=5, new_items=3, status='success')
        time.sleep(0.1)  # Ensure distinct timestamps for deterministic ordering
        self.db.log_fetch(items_fetched=2, new_items=0, status='partial', error_message='Some items skipped')

        history = self.db.get_fetch_history(limit=10)
        self.assertEqual(len(history), 2)
        # Most recent entry (second logged) comes first due to DESC ordering
        self.assertEqual(history[0].items_fetched, 2)
        self.assertEqual(history[0].status, 'partial')
        self.assertEqual(history[1].items_fetched, 5)

    def test_get_events_without_thumbnail(self):
        """Events without thumbnails should be returned."""
        now = datetime.now()
        self.db.insert_event('t1', 'No Thumb Event', now + timedelta(days=1))
        self.db.insert_event(
            't2', 'Has Thumb Event', now + timedelta(days=2),
            thumbnail_url='https://example.com/thumb.jpg'
        )

        no_thumb = self.db.get_events_without_thumbnail()
        self.assertEqual(len(no_thumb), 1)
        self.assertEqual(no_thumb[0].news_id, 't1')

    def test_update_thumbnail(self):
        """Updating a thumbnail should persist."""
        now = datetime.now()
        self.db.insert_event('th1', 'Thumbnail Update', now + timedelta(days=1))

        result = self.db.update_thumbnail('th1', 'https://example.com/new_thumb.jpg')
        self.assertTrue(result)

        event = self.db.get_event_by_title('Thumbnail Update')
        self.assertIsNotNone(event)
        self.assertEqual(event.thumbnail_url, 'https://example.com/new_thumb.jpg')

    def test_get_event_by_title_fuzzy(self):
        """Fuzzy title search should find matching events."""
        now = datetime.now()
        self.db.insert_event('f1', 'Full Event Title Here', now + timedelta(days=1))

        event = self.db.get_event_by_title('Event Title')
        self.assertIsNotNone(event)
        self.assertEqual(event.title, 'Full Event Title Here')

    def test_round_trip_insert_get(self):
        """Insert and retrieve should preserve all fields."""
        now = datetime.now()
        result = self.db.insert_event(
            news_id='rt1',
            title='Round Trip Test',
            event_date=now + timedelta(days=5),
            rss_pub_date='2026-04-20T10:00:00',
            description='A round trip test event.',
            event_type='meteor_shower',
            priority=3,
            visibility_level=2,
            thumbnail_url='https://example.com/thumb.jpg',
            event_page_url='https://in-the-sky.org/news.php?id=rt1',
        )
        self.assertTrue(result)

        events = self.db.get_upcoming_events(days=7)
        self.assertEqual(len(events), 1)
        e = events[0]
        self.assertEqual(e.news_id, 'rt1')
        self.assertEqual(e.title, 'Round Trip Test')
        self.assertEqual(e.description, 'A round trip test event.')
        self.assertEqual(e.event_type, 'meteor_shower')
        self.assertEqual(e.priority, 3)
        self.assertEqual(e.visibility_level, 2)
        self.assertEqual(e.thumbnail_url, 'https://example.com/thumb.jpg')
        self.assertEqual(e.event_page_url, 'https://in-the-sky.org/news.php?id=rt1')


if __name__ == '__main__':
    unittest.main()
