"""Unit tests for page scraper module (page_scraper.py)."""

import sys
import os
import unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from page_scraper import parse_page, _extract_thumbnail, _extract_visibility, _resolve_url


class TestParsePage(unittest.TestCase):
    """Test cases for the parse_page function."""

    def test_parse_with_thumbnail_and_level(self):
        """HTML with thumbnail and level icon should extract both."""
        html = '''<html><body>
            <img src="https://in-the-sky.org/imagedump.php?style=hugeteaser&id=123" />
            <img src="/level4_icon.png" alt="Medium telescope required" />
        </body></html>'''

        result = parse_page(html)
        self.assertIsNotNone(result)
        self.assertIn('in-the-sky.org', result.thumbnail_url)
        self.assertEqual(result.visibility_level, 4)
        self.assertEqual(result.visibility_text, 'Medium telescope required')

    def test_parse_no_thumbnail(self):
        """HTML without thumbnail should return None for thumbnail."""
        html = '''<html><body>
            <p>No images here</p>
        </body></html>'''

        result = parse_page(html)
        self.assertIsNotNone(result)
        self.assertIsNone(result.thumbnail_url)


class TestExtractThumbnail(unittest.TestCase):
    """Test cases for the _extract_thumbnail function."""

    def test_extract_hugeteaser(self):
        """Should extract hugeteaser-style thumbnail URL."""
        html = '''<html><body>
            <img src="https://in-the-sky.org/imagedump.php?style=hugeteaser&id=123" />
        </body></html>'''

        soup_mock = mock.MagicMock()
        img_tag = mock.MagicMock()
        img_tag.get.return_value = "https://in-the-sky.org/imagedump.php?style=hugeteaser&id=123"
        soup_mock.find.return_value = img_tag

        result = _extract_thumbnail(soup_mock)
        self.assertIsNotNone(result)

    def test_extract_content_image(self):
        """Should fallback to content area image."""
        html = '''<html><body>
            <div class="news">
                <img src="/imagedump.php?id=456" />
            </div>
        </body></html>'''

        soup_mock = mock.MagicMock()
        img_tag = mock.MagicMock()
        img_tag.get.return_value = "/imagedump.php?id=456"

        content_div = mock.MagicMock()
        content_div.find.return_value = img_tag
        soup_mock.find.return_value = content_div

        result = _extract_thumbnail(soup_mock)
        self.assertIsNotNone(result)


class TestExtractVisibility(unittest.TestCase):
    """Test cases for the _extract_visibility function."""

    def test_extract_level_icon(self):
        """Should extract visibility level from level icon image."""
        html = '''<html><body>
            <img src="/level3_icon.png" alt="Binoculars required" />
        </body></html>'''

        soup_mock = mock.MagicMock()
        img_tag = mock.MagicMock()
        img_tag.get.side_effect = lambda key, default='': {
            'src': '/level3_icon.png',
            'alt': 'Binoculars required',
        }.get(key, default)

        soup_mock.find_all.return_value = [img_tag]

        level, text = _extract_visibility(soup_mock)
        self.assertEqual(level, 3)
        self.assertEqual(text, 'Binoculars required')

    def test_extract_level_clamped(self):
        """Level > 5 should be clamped to 5."""
        html = '''<html><body>
            <img src="/level10_icon.png" alt="Very hard" />
        </body></html>'''

        soup_mock = mock.MagicMock()
        img_tag = mock.MagicMock()
        img_tag.get.side_effect = lambda key, default='': {
            'src': '/level10_icon.png',
            'alt': 'Very hard',
        }.get(key, default)

        soup_mock.find_all.return_value = [img_tag]

        level, text = _extract_visibility(soup_mock)
        self.assertEqual(level, 5)


class TestResolveUrl(unittest.TestCase):
    """Test cases for the _resolve_url function."""

    def test_absolute_url(self):
        """Absolute URLs should pass through unchanged."""
        result = _resolve_url("https://in-the-sky.org/imagedump.php?id=123")
        self.assertEqual(result, "https://in-the-sky.org/imagedump.php?id=123")

    def test_protocol_relative_url(self):
        """Protocol-relative URLs should get https: prefix."""
        result = _resolve_url("//in-the-sky.org/image.jpg")
        self.assertEqual(result, "https://in-the-sky.org/image.jpg")

    def test_root_relative_url(self):
        """Root-relative URLs should be resolved against IMAGE_BASE."""
        result = _resolve_url("/image.jpg")
        self.assertEqual(result, "https://in-the-sky.org/image.jpg")

    def test_relative_path_image_php(self):
        """Relative image.php paths should resolve correctly."""
        result = _resolve_url("imagedump.php?id=123")
        self.assertEqual(result, "https://in-the-sky.org/imagedump.php?id=123")


if __name__ == '__main__':
    unittest.main()
