"""Integration tests for database layer."""

import sys
import os
import unittest
import tempfile
from datetime import datetime, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from db_manager import DatabaseManager


class TestDatabaseIntegration(unittest.TestCase):
    """Test cases for the DatabaseManager class with real SQLite."""

    def setUp(self):
        """Set up test fixtures with a temporary database."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, 'test_events.db')
        self.db = DatabaseManager(db_path=self.db_path)

    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_insert_and_retrieve_event(self):
        """Test inserting an event and retrieving it by ID."""
        now = datetime.now()
        event_date = now + timedelta(days=7)

        result = self.db.insert_event(
            news_id='test_001',
            title='Test Event',
            event_date=event_date,
            description='A test event for integration testing.',
            event_type='unknown',
            priority=3
        )

        self.assertTrue(result)

        retrieved = self.db.get_event_by_id('test_001')
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.title, 'Test Event')

    def test_get_upcoming_events(self):
        """Test retrieving upcoming events within a date range."""
        now = datetime.now()

        # Add event in 3 days
        future_date = now + timedelta(days=3)
        self.db.insert_event(
            news_id='future_1',
            title='Future Event 1',
            event_date=future_date,
            description='Event in 3 days',
            event_type='unknown',
            priority=3
        )

        # Add event in 20 days (outside 15-day window)
        far_future = now + timedelta(days=20)
        self.db.insert_event(
            news_id='future_2',
            title='Future Event 2',
            event_date=far_future,
            description='Event in 20 days',
            event_type='unknown',
            priority=3
        )

        # Get events within 15 days
        upcoming = self.db.get_upcoming_events(days=15)
        self.assertEqual(len(upcoming), 1)
        self.assertEqual(upcoming[0].title, 'Future Event 1')

    def test_count_events(self):
        """Test counting events in the database."""
        now = datetime.now()
        future_date = now + timedelta(days=7)

        # Add some events
        for i in range(5):
            self.db.insert_event(
                news_id=f'test_{i}',
                title=f'Event {i}',
                event_date=future_date,
                description=f'Description {i}',
                event_type='unknown',
                priority=3
            )

        count = self.db.count_events()
        self.assertEqual(count, 5)

    def test_mark_as_notified(self):
        """Test marking events as notified."""
        now = datetime.now()
        future_date = now + timedelta(days=7)

        # Insert an event
        self.db.insert_event(
            news_id='notify_test',
            title='Notification Test',
            event_date=future_date,
            description='Test notification marking',
            event_type='unknown',
            priority=3
        )

        # Mark as notified
        result = self.db.mark_as_notified('notify_test')
        self.assertTrue(result)

        # Verify it's no longer in unnotified list
        unnotified = self.db.get_unnotified_events()
        titles = [e.title for e in unnotified]
        self.assertNotIn('Notification Test', titles)


if __name__ == '__main__':
    unittest.main()
