"""Unit tests for event_parser module."""

import sys
import os
import unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from event_parser import parse_rss_item


class TestEventParser(unittest.TestCase):
    """Test cases for the event parser functions."""

    def test_parse_rss_item_basic(self):
        """Test parsing a basic RSS item with all required fields."""
        item = {
            'title': '[2026-04-19] Comet C/2025 R3 (PANSTARRS)',
            'link': 'https://in-the-sky.org/news.php?id=2026_19_CK25R030_100',
            'description': 'Comet C/2025 R3 makes its closest approach.',
        }

        event = parse_rss_item(item)

        self.assertIsNotNone(event)
        self.assertEqual(event['title'], '[2026-04-19] Comet C/2025 R3 (PANSTARRS)')
        self.assertIn('in-the-sky.org', event['link'])
        self.assertIn('news_id', event)

    def test_parse_rss_item_missing_title(self):
        """Test that items without title return empty dict."""
        item = {
            'link': 'https://in-the-sky.org/news.php?id=test',
            'description': 'Some description',
        }

        event = parse_rss_item(item)
        # Returns dict with empty title, not None
        self.assertIsNotNone(event)
        self.assertEqual(event['title'], '')

    def test_parse_rss_item_missing_link(self):
        """Test that items without link return empty link."""
        item = {
            'title': 'Test Event',
            'description': 'Some description',
        }

        event = parse_rss_item(item)
        self.assertIsNotNone(event)
        self.assertEqual(event['link'], '')


if __name__ == '__main__':
    unittest.main()
