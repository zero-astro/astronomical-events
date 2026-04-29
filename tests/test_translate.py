"""Unit tests for the translation provider module (translate.py).

Tests batch translation, prompt formatting, rate limiting behavior,
and error handling. Uses mock API responses to avoid network calls.
"""

import json
import os
import sys
import unittest
from unittest import mock

# Ensure src is on path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestTranslateBatch(unittest.TestCase):
    """Test batch translation function."""

    @mock.patch('translate._call_api')
    def test_single_translation(self, mock_api):
        """Test translating a single title."""
        from translate import translate_batch
        
        mock_api.return_value = "Ilargi betea"
        
        result = translate_batch(["Full Moon"], "eu", {"provider": "lm-studio"})
        self.assertEqual(result, ["Ilargi betea"])

    @mock.patch('translate._call_api')
    def test_multiple_translations(self, mock_api):
        """Test translating multiple titles."""
        from translate import translate_batch
        
        mock_api.return_value = "Ilargi berria\nArtizarra"
        
        result = translate_batch(["New Moon", "Venus"], "eu", {"provider": "lm-studio"})
        self.assertEqual(len(result), 2)

    @mock.patch('translate._call_api')
    def test_response_padding_on_short_output(self, mock_api):
        """Test that missing translations are padded with originals."""
        from translate import translate_batch
        
        mock_api.return_value = "Ilargi betea"  # Only one line for two titles
        
        result = translate_batch(
            ["Full Moon", "New Moon"], "eu", {"provider": "lm-studio"}
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], "Ilargi betea")
        self.assertEqual(result[1], "New Moon")  # Padded with original

    def test_empty_titles_raises_value_error(self):
        """Test that empty titles list raises ValueError."""
        from translate import translate_batch
        
        with self.assertRaises(ValueError):
            translate_batch([], "eu", {"provider": "lm-studio"})

    def test_unsupported_language_raises_value_error(self):
        """Test that unsupported language codes raise ValueError."""
        from translate import translate_batch
        
        with self.assertRaises(ValueError):
            translate_batch(["Full Moon"], "de", {"provider": "lm-studio"})

    @mock.patch('translate._call_api')
    def test_model_not_specified_raises_value_error(self, mock_api):
        """Test that missing model raises ValueError."""
        from translate import translate_batch
        
        with self.assertRaises(ValueError):
            translate_batch(
                ["Full Moon"], "eu", {"provider": "ollama", "model": None}
            )

    @mock.patch('translate._call_api')
    def test_all_languages_work(self, mock_api):
        """Test that all supported languages produce results."""
        from translate import TRANSLATION_PROMPTS
        
        for lang in TRANSLATION_PROMPTS:
            with self.subTest(lang=lang):
                mock_api.return_value = "Translated"
                
                from translate import translate_batch
                
                result = translate_batch(["Full Moon"], lang, {"provider": "lm-studio"})
                self.assertEqual(result, ["Translated"])


class TestTranslateEvent(unittest.TestCase):
    """Test single event translation."""

    @mock.patch('translate.translate_batch')
    def test_translate_event_title_only(self, mock_batch):
        """Test translating an event with no description."""
        from translate import translate_event
        
        class FakeEvent:
            title = "Full Moon"
            description = ""
        
        mock_batch.side_effect = [
            ["Ilargi betea"],       # title translation
            [""]                     # empty description
        ]
        
        result = translate_event(FakeEvent(), {"provider": "lm-studio"}, "eu")
        self.assertIsNotNone(result)
        self.assertEqual(result["translated_title"], "Ilargi betea")

    @mock.patch('translate.translate_batch')
    def test_translate_event_with_description(self, mock_batch):
        """Test translating an event with description."""
        from translate import translate_event
        
        class FakeEvent:
            title = "Full Moon"
            description = "The moon will be fully illuminated"
        
        mock_batch.side_effect = [
            ["Ilargi betea"],
            ["Ilargia guztiz argituta"]
        ]
        
        result = translate_event(FakeEvent(), {"provider": "lm-studio"}, "eu")
        self.assertIsNotNone(result)
        self.assertEqual(result["translated_title"], "Ilargi betea")
        self.assertEqual(result["translated_description"], "Ilargia guztiz argituta")

    @mock.patch('translate.translate_batch', side_effect=Exception("API down"))
    def test_translate_event_fallback_on_error(self, mock_batch):
        """Test that translation errors return None."""
        from translate import translate_event
        
        class FakeEvent:
            title = "Full Moon"
            description = ""
        
        result = translate_event(FakeEvent(), {"provider": "lm-studio"}, "eu")
        self.assertIsNone(result)


class TestCallApi(unittest.TestCase):
    """Test the low-level API call function."""

    @mock.patch('urllib.request.urlopen')
    def test_api_call_constructs_correct_url(self, mock_urlopen):
        """Test that the API URL is constructed correctly."""
        # Setup mock response
        import translate
        
        mock_response = mock.Mock()
        mock_response.read.return_value = json.dumps({
            "choices": [{"message": {"content": "Test result"}}]
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__ = lambda self: mock_response
        mock_urlopen.return_value.__exit__ = mock.Mock()

        translate._call_api(
            messages=[{"role": "user", "content": "Hello"}],
            api_base="http://test.local/v1",
            model="test-model"
        )

        # Verify the URL was called correctly
        mock_urlopen.assert_called_once()
        request = mock_urlopen.call_args[0][0]
        self.assertIn("/chat/completions", request.full_url)


if __name__ == '__main__':
    unittest.main()
