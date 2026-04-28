"""Unit tests for notification formatting (notification.py)."""

import sys
import os
import unittest
from datetime import datetime, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from notification import _format_event_for_output, _format_notification_message


class TestEventFormatting(unittest.TestCase):
    """Test cases for event formatting functions."""

    def test_format_event_basic(self):
        """Basic event should have all required fields."""
        from db_manager import Event
        
        event = Event(
            news_id='test_001',
            title='Test Event',
            event_date=datetime.now() + timedelta(days=3),
            rss_pub_date=None,
            description='A test event.',
            event_type='unknown',
            priority=3,
            visibility_level=None,
            thumbnail_url=None,
            event_page_url='https://example.com/test',
            is_notified=False,
        )

        result = _format_event_for_output(event)

        self.assertEqual(result['news_id'], 'test_001')
        self.assertEqual(result['title'], 'Test Event')
        self.assertIn('event_date', result)
        self.assertEqual(result['time_label'], '3 days away')
        self.assertEqual(result['priority'], 3)
        self.assertEqual(result['priority_emoji'], '\U0001f7e1')  # Yellow circle
        self.assertEqual(result['event_type'], 'unknown')

    def test_format_event_today(self):
        """Event happening today should have time_label='today'."""
        from db_manager import Event
        
        event = Event(
            news_id='test_002',
            title='Today Event',
            event_date=datetime.now(),
            rss_pub_date=None,
            description='',
            event_type='eclipse',
            priority=1,
            visibility_level=1,
            thumbnail_url=None,
            event_page_url=None,
            is_notified=False,
        )

        result = _format_event_for_output(event)
        self.assertEqual(result['time_label'], 'today')

    def test_format_event_tomorrow(self):
        """Event happening tomorrow should have time_label='tomorrow'."""
        from db_manager import Event
        
        event = Event(
            news_id='test_003',
            title='Tomorrow Event',
            event_date=datetime.now() + timedelta(days=1),
            rss_pub_date=None,
            description='',
            event_type='unknown',
            priority=5,
            visibility_level=None,
            thumbnail_url=None,
            event_page_url=None,
            is_notified=False,
        )

        result = _format_event_for_output(event)
        self.assertEqual(result['time_label'], 'tomorrow')

    def test_format_event_past(self):
        """Past events should have time_label='past'."""
        from db_manager import Event
        
        event = Event(
            news_id='test_004',
            title='Past Event',
            event_date=datetime.now() - timedelta(days=1),
            rss_pub_date=None,
            description='',
            event_type='unknown',
            priority=5,
            visibility_level=None,
            thumbnail_url=None,
            event_page_url=None,
            is_notified=False,
        )

        result = _format_event_for_output(event)
        self.assertEqual(result['time_label'], 'past')

    def test_format_event_with_visibility(self):
        """Event with visibility level should include label."""
        from db_manager import Event
        
        event = Event(
            news_id='test_005',
            title='Visible Event',
            event_date=datetime.now() + timedelta(days=7),
            rss_pub_date=None,
            description='',
            event_type='comet',
            priority=3,
            visibility_level=4,  # Medium telescope required
            thumbnail_url=None,
            event_page_url=None,
            is_notified=False,
        )

        result = _format_event_for_output(event)
        self.assertEqual(result['visibility_level'], 4)
        self.assertIn('Medium telescope', result['visibility_label'])

    def test_format_notification_message_schema(self):
        """Notification message should have deterministic schema."""
        events = [
            {'news_id': 'e1', 'title': 'Event 1'},
            {'news_id': 'e2', 'title': 'Event 2'},
        ]

        result = _format_notification_message(events, "Test Batch")

        self.assertEqual(result['schema_version'], '1.0')
        self.assertEqual(result['type'], 'astronomical_events')
        self.assertEqual(result['batch_label'], 'Test Batch')
        self.assertEqual(result['count'], 2)
        self.assertEqual(len(result['events']), 2)
        self.assertIn('generated_at', result)


if __name__ == '__main__':
    unittest.main()
