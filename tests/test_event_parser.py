"""Unit tests for event parser module (event_parser.py)."""

import sys
import os
import unittest
from datetime import datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from event_parser import parse_event_date, parse_event_name, strip_html, extract_countdown_days


class TestParseEventDate(unittest.TestCase):
    """Test cases for the parse_event_date function."""

    def test_parse_standard_format(self):
        """Standard date format should parse correctly."""
        result = parse_event_date("23 Apr 2026 (3 days away): Test Event")
        self.assertEqual(result, datetime(2026, 4, 23))

    def test_parse_different_months(self):
        """Should handle all month abbreviations."""
        months = [
            ("15 Jan 2026", datetime(2026, 1, 15)),
            ("1 Feb 2026", datetime(2026, 2, 1)),
            ("31 Dec 2026", datetime(2026, 12, 31)),
        ]
        for title, expected in months:
            result = parse_event_date(title)
            self.assertEqual(result, expected, f"Failed for {title}")

    def test_invalid_no_date_prefix(self):
        """Titles without date prefix should return None."""
        result = parse_event_date("Just a random event name")
        self.assertIsNone(result)

    def test_empty_string(self):
        """Empty string should return None."""
        result = parse_event_date("")
        self.assertIsNone(result)

    def test_invalid_month(self):
        """Invalid month abbreviation should return None."""
        result = parse_event_date("32 Xyz 2026: Bad date")
        self.assertIsNone(result)


class TestParseEventName(unittest.TestCase):
    """Test cases for the parse_event_name function."""

    def test_strip_date_prefix(self):
        """Should strip date prefix from title."""
        result = parse_event_name("23 Apr 2026 (3 days away): Haumea at opposition")
        self.assertEqual(result, "Haumea at opposition")

    def test_no_date_prefix(self):
        """Title without date prefix should return as-is."""
        result = parse_event_name("Just a title")
        self.assertEqual(result, "Just a title")


class TestStripHtml(unittest.TestCase):
    """Test cases for the strip_html function."""

    def test_strip_simple_tags(self):
        """Simple HTML tags should be removed."""
        result = strip_html("<p>Hello world</p>")
        self.assertEqual(result, "Hello world")

    def test_strip_nested_tags(self):
        """Nested HTML tags should all be removed."""
        result = strip_html("<div><p><b>Bold text</b></p></div>")
        self.assertEqual(result, "Bold text")

    def test_decode_entities(self):
        """HTML entities should be decoded."""
        result = strip_html("&lt;script&gt;&amp;&quot;test&quot;")
        self.assertEqual(result, "<script>&\"test\"")

    def test_collapse_whitespace(self):
        """Multiple whitespace should collapse to single space."""
        result = strip_html("<p>  Hello   world  </p>")
        self.assertEqual(result, "Hello world")


class TestExtractCountdownDays(unittest.TestCase):
    """Test cases for the extract_countdown_days function."""

    def test_normal_countdown(self):
        """Normal countdown should return correct days."""
        result = extract_countdown_days("23 Apr 2026 (5 days away): Event")
        self.assertEqual(result, 5)

    def test_today(self):
        """Today should return 0."""
        result = extract_countdown_days("19 Apr 2026 (Today): Event")
        self.assertEqual(result, 0)

    def test_yesterday(self):
        """Yesterday should return -1."""
        result = extract_countdown_days("18 Apr 2026 (Yesterday): Event")
        self.assertEqual(result, -1)

    def test_no_countdown(self):
        """Title without countdown info should return None."""
        result = extract_countdown_days("Just a title with no date info")
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
