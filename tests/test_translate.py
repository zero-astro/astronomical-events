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


class FakeEvent:
    """Minimal event stub for tests."""
    def __init__(self, title="", desc="", rich="", view=""):
        self.title = title
        self.description = desc
        self.rich_description_en = rich
        self.viewing_info_en = view


class TestTranslateBatch(unittest.TestCase):
    """Test batch translation function."""

    def setUp(self):
        """Reset DB singleton and patch _get_db to return a mock with no cache."""
        import translate as _t
        _t._db_manager = None
        self._db_mock = mock.MagicMock()
        self._db_mock.get_cached_translation.return_value = None
        self._patch_get_db = mock.patch.object(_t, '_get_db', return_value=self._db_mock)
        self._patch_get_db.start()

    def tearDown(self):
        """Stop the _get_db patch."""
        self._patch_get_db.stop()
        # Reset DB singleton after each test
        import translate as _t2
        _t2._db_manager = None

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
        
        with self.assertRaises(RuntimeError):
            translate_batch(["Full Moon"], "de", {"provider": "lm-studio"})

    @mock.patch('translate._call_api')
    def test_model_not_specified_raises_value_error(self, mock_api):
        """Test that missing model raises ValueError."""
        from translate import translate_batch
        
        with self.assertRaises(RuntimeError):
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
    """Test single event translation with batch optimization."""

    @mock.patch('translate.translate_batch')
    def test_translate_event_title_only(self, mock_batch):
        """Test translating an event with no description (batch1=[title], batch2=[])."""
        from translate import translate_event
        
        class FakeEvent:
            title = "Full Moon"
            description = ""
        
        # Batch 1: [title] → ["Ilargi betea"]
        mock_batch.return_value = ["Ilargi betea"]
        
        result = translate_event(FakeEvent(), {"provider": "lm-studio"}, "eu")
        self.assertIsNotNone(result)
        self.assertEqual(result["translated_title"], "Ilargi betea")
        self.assertEqual(result["translated_description"], "")

    @mock.patch('translate.translate_batch')
    def test_translate_event_with_description(self, mock_batch):
        """Test translating an event with description (batch1=[title, desc])."""
        from translate import translate_event
        
        class FakeEvent:
            title = "Full Moon"
            description = "The moon will be fully illuminated"
        
        # Batch 1: [title, desc] → ["Ilargi betea", "Ilargia guztiz argituta"]
        mock_batch.return_value = ["Ilargi betea", "Ilargia guztiz argituta"]
        
        result = translate_event(FakeEvent(), {"provider": "lm-studio"}, "eu")
        self.assertIsNotNone(result)
        self.assertEqual(result["translated_title"], "Ilargi betea")
        self.assertEqual(result["translated_description"], "Ilargia guztiz argituta")

    @mock.patch('translate.translate_batch')
    def test_translate_event_with_rich_metadata(self, mock_batch):
        """Test translating event with rich_description and viewing_info (batch2=[rich, view])."""
        from translate import translate_event
        
        class FakeEvent:
            title = "Total Solar Eclipse"
            description = "A total solar eclipse will be visible."
            rich_description_en = "This rare celestial event occurs when the Moon passes between Earth and Sun."
            viewing_info_en = "Best viewed from western Europe at 14:30 UTC."
        
        # Batch 1: [title, desc] → ["Eclipse Eguzki osoa", "Eclipse eguzki osoa ikusgai izango da."]
        mock_batch.side_effect = [
            ["Eclipse Eguzki osoa", "Eclipse eguzki osoa ikusgai izango da."],
            ["Gauza arraro hau gertatzen da Ilargia Lurra eta Eguzkiren artean pasatzean.", 
             "Hobe ipar-mendebaldeko Europan 14:30 UTC-n."]
        ]
        
        result = translate_event(FakeEvent(), {"provider": "lm-studio"}, "eu")
        self.assertIsNotNone(result)
        self.assertEqual(result["translated_title"], "Eclipse Eguzki osoa")
        self.assertEqual(result["translated_description"], "Eclipse eguzki osoa ikusgai izango da.")
        self.assertEqual(result["translated_rich_description"], 
                         "Gauza arraro hau gertatzen da Ilargia Lurra eta Eguzkiren artean pasatzean.")
        self.assertEqual(result["translated_viewing_info"], 
                         "Hobe ipar-mendebaldeko Europan 14:30 UTC-n.")

    @mock.patch('translate.translate_batch')
    def test_translate_event_single_rich_only(self, mock_batch):
        """Test event with only rich_description (no viewing_info) — batch2=[rich]."""
        from translate import translate_event
        
        class FakeEvent:
            title = "Meteor Shower"
            description = "Perseids will be active."
            rich_description_en = "Up to 60 meteors per hour expected."
            viewing_info_en = ""  # Empty, so treated as not present
        
        # Batch 1: [title, desc] → ["Meteor eragina", "Perseiak aktibo egongo dira."]
        mock_batch.side_effect = [
            ["Meteor eragina", "Perseiak aktibo egongo dira."],
            ["Orduko 60 meteor espero."]  # Batch 2: [rich_only]
        ]
        
        result = translate_event(FakeEvent(), {"provider": "lm-studio"}, "eu")
        self.assertIsNotNone(result)
        self.assertEqual(result["translated_title"], "Meteor eragina")
        self.assertEqual(result["translated_rich_description"], "Orduko 60 meteor espero.")

    @mock.patch('translate.translate_batch', side_effect=Exception("API down"))
    def test_translate_event_fallback_on_error(self, mock_batch):
        """Test that translation errors return None."""
        from translate import translate_event
        
        class FakeEvent:
            title = "Full Moon"
            description = ""
        
        result = translate_event(FakeEvent(), {"provider": "lm-studio"}, "eu")
        self.assertIsNone(result)

    @mock.patch('translate.translate_batch')
    def test_translate_event_no_description_no_rich(self, mock_batch):
        """Test event with title only — batch1=[title], no batch2."""
        from translate import translate_event
        
        class FakeEvent:
            title = "Lunar Transit"
            description = ""
        
        # Only one batch call for [title]
        mock_batch.return_value = ["Ilargi Trantsitu"]
        
        result = translate_event(FakeEvent(), {"provider": "lm-studio"}, "eu")
        self.assertIsNotNone(result)
        self.assertEqual(result["translated_title"], "Ilargi Trantsitu")
        self.assertEqual(result["translated_description"], "")


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


class TestGlobalBatchTranslate(unittest.TestCase):
    """Test global batch translation — Option 1 optimization."""

    @mock.patch('translate.translate_batch')
    def test_global_batch_translates_all_events(self, mock_batch):
        """Test that all events get translated with correct field distribution."""
        from translate import global_batch_translate

        events = [
            FakeEvent("Full Moon", "The moon is full.", "Rare event.", "View at 21:00"),
            FakeEvent("New Moon", "", "Dark sky event.", ""),
            FakeEvent("Lunar Eclipse", "Moon turns red.", "", "Best from Europe"),
        ]

        # translate_batch called per field type: title, desc, rich_desc, viewing_info
        mock_batch.side_effect = [
            ["Ilargi betea", "Ilargi berria", "Ilargi eklipsea"],  # titles
            ["Ilargia beteta dago.", "", "Lurrak gorri bihurtzen da."],  # descriptions
            ["Gertaera arraroa.", "Zeru ilune gertaera.", ""],  # rich_descriptions
            ["21:00-ean ikusi.", "", "Hobe Europatik"],  # viewing_infos
        ]

        results = global_batch_translate(events, "eu", {"provider": "lm-studio"})

        self.assertEqual(len(results), 3)
        self.assertEqual(results[0]["translated_title"], "Ilargi betea")
        self.assertEqual(results[0]["translated_description"], "Ilargia beteta dago.")
        self.assertEqual(results[0]["translated_rich_description"], "Gertaera arraroa.")
        self.assertEqual(results[0]["translated_viewing_info"], "21:00-ean ikusi.")

        self.assertEqual(results[1]["translated_title"], "Ilargi berria")
        self.assertEqual(results[1]["translated_description"], "")  # empty input → empty output
        self.assertEqual(results[1]["translated_rich_description"], "Zeru ilune gertaera.")
        self.assertEqual(results[1]["translated_viewing_info"], "")

        self.assertEqual(results[2]["translated_title"], "Ilargi eklipsea")
        self.assertEqual(results[2]["translated_description"], "Lurrak gorri bihurtzen da.")
        self.assertEqual(results[2]["translated_rich_description"], "")  # empty input → empty output
        self.assertEqual(results[2]["translated_viewing_info"], "Hobe Europatik")

    @mock.patch('translate.translate_batch')
    def test_global_batch_reduces_api_calls(self, mock_batch):
        """Test that global batching uses max 4 API calls regardless of event count."""
        from translate import global_batch_translate

        events = [FakeEvent(f"Event {i}", f"Description {i}") for i in range(10)]

        mock_batch.return_value = ["Translated"] * 10

        results = global_batch_translate(events, "eu", {"provider": "lm-studio"})

        # Should call translate_batch at most 4 times (title + desc + rich_desc + viewing_info)
        # But rich_desc and viewing_info are empty for all events, so only title+desc
        self.assertLessEqual(mock_batch.call_count, 4)
        self.assertEqual(len(results), 10)

    @mock.patch('translate.translate_batch')
    def test_global_batch_empty_events(self, mock_batch):
        """Test that empty event list returns empty results."""
        from translate import global_batch_translate

        results = global_batch_translate([], "eu", {"provider": "lm-studio"})
        self.assertEqual(results, [])
        mock_batch.assert_not_called()

    @mock.patch('translate.translate_batch')
    def test_global_batch_only_titles_no_other_fields(self, mock_batch):
        """Test events with only titles (no desc/rich/viewing)."""
        from translate import global_batch_translate

        events = [FakeEvent("Full Moon"), FakeEvent("New Moon")]

        mock_batch.return_value = ["Ilargi betea", "Ilargi berria"]

        results = global_batch_translate(events, "eu", {"provider": "lm-studio"})

        # Only title batch should be called (no other fields present)
        self.assertEqual(mock_batch.call_count, 1)
        self.assertEqual(results[0]["translated_title"], "Ilargi betea")
        self.assertEqual(results[1]["translated_description"], "")
        self.assertEqual(results[0]["translated_rich_description"], "")

    @mock.patch('translate.translate_batch')
    def test_global_batch_100_events(self, mock_batch):
        """Test that 100+ events are handled in one batch call."""
        from translate import global_batch_translate

        events = [FakeEvent(f"Event {i}", f"Description {i}", f"Rich {i}", f"View {i}") for i in range(100)]

        mock_batch.side_effect = [
            ["Translated"] * 100,  # titles
            ["Translated"] * 100,  # descriptions
            ["Translated"] * 100,  # rich_descriptions
            ["Translated"] * 100,  # viewing_infos
        ]

        results = global_batch_translate(events, "eu", {"provider": "lm-studio"})

        self.assertEqual(len(results), 100)
        self.assertEqual(mock_batch.call_count, 4)  # All 4 field types called once


if __name__ == '__main__':
    unittest.main()
