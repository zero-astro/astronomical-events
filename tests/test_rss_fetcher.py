"""Unit tests for RSS fetcher module (rss_fetcher.py)."""

import sys
import os
import unittest
from unittest import mock
from io import BytesIO
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from rss_fetcher import fetch_rss, parse_items, get_feed_metadata, fetch_and_parse


class TestFetchRss(unittest.TestCase):
    """Test cases for the fetch_rss function."""

    def test_fetch_success(self):
        """Successful RSS fetch should return parsed feed."""
        mock_xml = b'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>In The Sky News</title>
    <item>
      <title>23 Apr 2026 (3 days away): Test Event</title>
      <link>https://in-the-sky.org/news.php?id=test_001</link>
      <description>A test event.</description>
    </item>
  </channel>
</rss>'''

        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_response = mock.MagicMock()
            mock_response.status = 200
            mock_response.read.return_value = mock_xml
            mock_urlopen.return_value.__enter__ = mock.MagicMock(return_value=mock_response)
            mock_urlopen.return_value.__exit__ = mock.MagicMock(return_value=False)

            result = fetch_rss('https://example.com/feed.xml')
            self.assertIsNotNone(result)
            self.assertTrue(hasattr(result, 'entries'))

    def test_fetch_empty_feed(self):
        """RSS feed with no entries should return None."""
        mock_xml = b'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>In The Sky News</title>
  </channel>
</rss>'''

        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_response = mock.MagicMock()
            mock_response.status = 200
            mock_response.read.return_value = mock_xml
            mock_urlopen.return_value.__enter__ = mock.MagicMock(return_value=mock_response)
            mock_urlopen.return_value.__exit__ = mock.MagicMock(return_value=False)

            result = fetch_rss('https://example.com/feed.xml')
            self.assertIsNone(result)

    def test_fetch_http_error(self):
        """HTTP error should return None."""
        import urllib.error

        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_response = mock.MagicMock()
            mock_response.status = 500
            mock_urlopen.return_value.__enter__ = mock.MagicMock(return_value=mock_response)
            mock_urlopen.return_value.__exit__ = mock.MagicMock(return_value=False)

            result = fetch_rss('https://example.com/feed.xml')
            self.assertIsNone(result)


class TestParseItems(unittest.TestCase):
    """Test cases for the parse_items function."""

    def test_parse_valid_entries(self):
        """Valid RSS entries should be parsed into dicts."""
        mock_feed = mock.MagicMock()
        entry1 = mock.MagicMock()
        entry1.get.side_effect = lambda key, default='': {
            'title': '23 Apr 2026 (3 days away): Test Event',
            'link': 'https://in-the-sky.org/news.php?id=test_001',
            'description': '<p>A test event.</p>',
        }.get(key, default)
        entry1.get.return_value = ''

        def get_side_effect(key, default=''):
            return {
                'title': '23 Apr 2026 (3 days away): Test Event',
                'link': 'https://in-the-sky.org/news.php?id=test_001',
                'description': '<p>A test event.</p>',
            }.get(key, default)

        entry1.get = mock.MagicMock(side_effect=get_side_effect)

        mock_feed.entries = [entry1]

        result = parse_items(mock_feed)
        self.assertEqual(len(result), 1)
        self.assertIn('news_id', result[0])
        self.assertIn('title', result[0])
        self.assertIn('event_date', result[0])

    def test_parse_empty_feed(self):
        """Empty feed should return empty list."""
        mock_feed = mock.MagicMock()
        mock_feed.entries = []

        result = parse_items(mock_feed)
        self.assertEqual(result, [])

    def test_parse_none_feed(self):
        """None feed should return empty list."""
        result = parse_items(None)
        self.assertEqual(result, [])


class TestGetFeedMetadata(unittest.TestCase):
    """Test cases for the get_feed_metadata function."""

    def test_extract_metadata(self):
        """Should extract title, subtitle, link from feed metadata."""
        mock_feed = mock.MagicMock()
        mock_feed.feed.title = "In The Sky News"
        mock_feed.feed.subtitle = "Astronomical Events"
        mock_feed.feed.href = "https://in-the-sky.org/"
        mock_feed.feed.updated = "Mon, 20 Apr 2026 12:00:00 GMT"

        result = get_feed_metadata(mock_feed)
        self.assertEqual(result['title'], 'In The Sky News')
        self.assertEqual(result['subtitle'], 'Astronomical Events')
        self.assertEqual(result['link'], 'https://in-the-sky.org/')
        self.assertEqual(result['last_build_date'], 'Mon, 20 Apr 2026 12:00:00 GMT')

    def test_metadata_missing_fields(self):
        """Missing metadata fields should return empty strings."""
        mock_feed = mock.MagicMock()
        # Use a real object for feed so getattr returns the default
        from types import SimpleNamespace
        mock_feed.feed = SimpleNamespace(title="Test Feed")
        # subtitle, href, updated are not set → getattr returns ""

        result = get_feed_metadata(mock_feed)
        self.assertEqual(result['title'], 'Test Feed')
        self.assertEqual(result['subtitle'], '')
        self.assertEqual(result['link'], '')
        self.assertEqual(result['last_build_date'], '')

    def test_none_feed(self):
        """None feed should return empty dict."""
        result = get_feed_metadata(None)
        self.assertEqual(result, {})


class TestFetchAndParse(unittest.TestCase):
    """Test cases for the fetch_and_parse function."""

    def test_successful_fetch_and_parse(self):
        """Full pipeline should return items and metadata."""
        mock_xml = b'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>In The Sky News</title>
    <item>
      <title>23 Apr 2026 (3 days away): Test Event</title>
      <link>https://in-the-sky.org/news.php?id=test_001</link>
      <description>A test event.</description>
    </item>
  </channel>
</rss>'''

        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_response = mock.MagicMock()
            mock_response.status = 200
            mock_response.read.return_value = mock_xml
            mock_urlopen.return_value.__enter__ = mock.MagicMock(return_value=mock_response)
            mock_urlopen.return_value.__exit__ = mock.MagicMock(return_value=False)

            items, meta = fetch_and_parse('https://example.com/feed.xml')
            self.assertEqual(len(items), 1)
            self.assertIn('title', meta)


class TestCircuitBreakerTransitions(unittest.TestCase):
    """Test circuit breaker state transitions during failures."""

    def test_circuit_opens_after_threshold(self):
        """Circuit should open after consecutive failures."""
        from rss_fetcher import rss_circuit_breaker

        # Reset to closed state for clean test
        rss_circuit_breaker._state = "closed"
        rss_circuit_breaker._failure_count = 0
        rss_circuit_breaker._last_failure_time = None

        threshold = rss_circuit_breaker.failure_threshold
        for _ in range(threshold):
            rss_circuit_breaker.record_failure()

        self.assertEqual(rss_circuit_breaker.state, "open")

    def test_circuit_allows_after_recovery(self):
        """Circuit should allow requests after recovery timeout."""
        from retry import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0.1)
        for _ in range(3):
            cb.record_failure()
        self.assertEqual(cb.state, "open")

        # Wait for recovery
        import time
        time.sleep(0.15)

        # Success should close it (transitioning through half-open)
        cb.record_success()
        self.assertEqual(cb.state, "closed")


if __name__ == '__main__':
    unittest.main()
