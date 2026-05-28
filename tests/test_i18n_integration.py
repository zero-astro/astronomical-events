"""End-to-end integration tests for i18n pipeline.

Tests the full flow: fetch RSS → parse → translate → notify,
verifying translated events appear in notifications and fallbacks work.
"""

import json
import os
import sys
import sqlite3
import tempfile
import unittest
from datetime import datetime
from unittest import mock


# Ensure src is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from db_manager import DatabaseManager, Event
from translator import get_target_languages, translate_missing_events, get_translation_for_event
from notification import _format_event_for_output


class TestDatabaseIntegration(unittest.TestCase):
    """Test DB methods for translation storage and retrieval."""

    def setUp(self):
        """Create a temporary SQLite database with test data."""
        self.db_path = tempfile.mktemp(suffix='.db')
        self.db = DatabaseManager(self.db_path)
        
        # Set target languages to ['eu', 'ca']
        cursor = self.db.conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('target_languages', ?)",
                       (json.dumps(['eu', 'ca']),))
        self.db.conn.commit()

    def tearDown(self):
        """Close DB and remove temp file."""
        self.db.close()
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_insert_and_get_translation(self):
        """Test storing and retrieving a translation."""
        self.db.insert_or_update_translation(
            news_id='test_001',
            target_lang='eu',
            translated_title='Ilargi betea',
            translated_description='Ilargia guztiz argituta',
            provider='lm-studio'
        )

        result = self.db.get_translation('test_001', 'eu')
        self.assertIsNotNone(result)
        self.assertEqual(result['translated_title'], 'Ilargi betea')
        self.assertEqual(result['provider'], 'lm-studio')

    def test_insert_or_update_overwrites(self):
        """Test that insert_or_update_translation overwrites existing translation."""
        # First insertion
        self.db.insert_or_update_translation(
            news_id='test_002',
            target_lang='eu',
            translated_title='Lehen itzulpena',
            translated_description='',
            provider='lm-studio'
        )

        # Second insertion should overwrite
        self.db.insert_or_update_translation(
            news_id='test_002',
            target_lang='eu',
            translated_title='Bigarren itzulpena',
            translated_description='',
            provider='openai'
        )

        result = self.db.get_translation('test_002', 'eu')
        self.assertEqual(result['translated_title'], 'Bigarren itzulpena')
        self.assertEqual(result['provider'], 'openai')

    def test_get_events_needing_translation(self):
        """Test querying events that need translation."""
        # Insert some events
        for i in range(3):
            self.db.insert_event(
                news_id=f'event_{i}',
                title=f'Test Event {i}',
                event_date=datetime.now(),
                description='Test description',
                event_type='lunar'
            )

        # Translate only one of them to 'eu'
        self.db.insert_or_update_translation(
            news_id='event_0',
            target_lang='eu',
            translated_title='Ilargi proba',
            translated_description='',
            provider='lm-studio'
        )

        # Get events needing translation
        needs_translation = self.db.get_events_needing_translation(['eu'])
        
        # Should return 2 events (event_1 and event_2)
        self.assertEqual(len(needs_translation), 2)
        news_ids = [e.news_id for e in needs_translation]
        self.assertIn('event_1', news_ids)
        self.assertIn('event_2', news_ids)

    def test_get_target_languages(self):
        """Test reading target languages from config."""
        langs = get_target_languages(self.db)
        self.assertEqual(langs, ['eu', 'ca'])


class TestNotificationIntegration(unittest.TestCase):
    """Test that notifications use translated text correctly."""

    def setUp(self):
        """Create a temporary DB with test data and translations."""
        self.db_path = tempfile.mktemp(suffix='.db')
        self.db = DatabaseManager(self.db_path)

        # Insert an event
        self.db.insert_event(
            news_id='notify_test_01',
            title='Full Moon over Spain',
            event_date=datetime.now(),
            description='The moon will appear fully illuminated tonight.',
            event_type='lunar',
            priority=2
        )

        # Add Basque translation
        self.db.insert_or_update_translation(
            news_id='notify_test_01',
            target_lang='eu',
            translated_title='Ilargi betea Espainian',
            translated_description='Gaur gauean ilargia guztiz argituta agertuko da.',
            provider='lm-studio'
        )

    def tearDown(self):
        self.db.close()
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_format_event_uses_translation(self):
        """Test that _format_event_for_output uses translated title."""
        result = _format_event_for_output(
            Event(news_id='notify_test_01', title='Full Moon over Spain', event_date=datetime.now()),
            self.db,
            ['eu']
        )

        # Title should be replaced with translation
        self.assertEqual(result['title'], 'Ilargi betea Espainian')
        self.assertIn('target_lang', result)
        self.assertEqual(result['target_lang'], 'eu')
        # Description should also be translated
        self.assertIn('Gaur gauean', result.get('description', ''))

    def test_format_event_falls_back_to_english(self):
        """Test fallback to English when no translation exists."""
        result = _format_event_for_output(
            Event(news_id='notify_test_01', title='Full Moon over Spain', event_date=datetime.now()),
            self.db,
            ['fr']  # French - no translation exists
        )

        # Should fall back to English (original)
        self.assertEqual(result['title'], 'Full Moon over Spain')


class TestTranslatorOrchestration(unittest.TestCase):
    """Test the translator orchestration layer."""

    def setUp(self):
        """Create a temporary DB with test events."""
        self.db_path = tempfile.mktemp(suffix='.db')
        self.db = DatabaseManager(self.db_path)

        # Set target languages
        cursor = self.db.conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('target_languages', ?)",
                       (json.dumps(['eu']),))
        self.db.conn.commit()

    def tearDown(self):
        self.db.close()
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    @mock.patch('translator.translate_missing_events')
    def test_translate_single_event_success(self, mock_translate):
        """Test translating a single event."""
        from translator import translate_single_event
        
        # Insert an event
        self.db.insert_event(
            news_id='single_test',
            title='Comet Discovery',
            event_date=datetime.now(),
            description='A new comet has been discovered.',
            event_type='comet'
        )

        mock_translate.return_value = {
            'translated_title': 'Kometaren Aurkikuntza',
            'translated_description': 'Komet berri bat aurkitu da.'
        }

        # Mock translate_event at the module level
        with mock.patch('translate.translate_event', return_value=mock_translate.return_value):
            result = translate_single_event(
                self.db,
                Event(news_id='single_test', title='Comet Discovery', event_date=datetime.now(), description='A new comet.'),
                {'provider': 'lm-studio'},
                'eu'
            )

        self.assertTrue(result)

    def test_get_translation_for_event(self):
        """Test retrieving cached translation."""
        result = get_translation_for_event(self.db, 'notify_test_01', 'eu')
        # This will fail because notify_test_01 is not in this DB
        self.assertIsNone(result)


class TestEndToEndPipeline(unittest.TestCase):
    """Full end-to-end test: insert event → translate → verify notification."""

    def setUp(self):
        """Create a temporary DB with full pipeline setup."""
        self.db_path = tempfile.mktemp(suffix='.db')
        self.db = DatabaseManager(self.db_path)

        # Set target languages to ['eu']
        cursor = self.db.conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('target_languages', ?)",
                       (json.dumps(['eu']),))
        self.db.conn.commit()

    def tearDown(self):
        self.db.close()
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    @mock.patch('translate.translate_batch')
    def test_full_pipeline_translate_and_notify(self, mock_translate_batch):
        """Test the full pipeline: insert → translate → verify notification."""
        # Mock translation response
        mock_translate_batch.return_value = ['Ilargiaren eta M45en hurbilketa']

        # Step 1: Insert event (simulating RSS fetch)
        self.db.insert_event(
            news_id='e2e_001',
            title='Moon and M45 Conjunction',
            event_date=datetime.now(),
            description='The moon will pass near the Pleiades star cluster.',
            event_type='conjunction',
            priority=3
        )

        # Step 2: Translate (simulating post-fetch translation)
        with mock.patch('translator.get_target_languages', return_value=['eu']):
            results = translate_missing_events(self.db, {'provider': 'lm-studio'})

        # Verify translation was stored
        translation = self.db.get_translation('e2e_001', 'eu')
        self.assertIsNotNone(translation)
        self.assertEqual(translation['translated_title'], 'Ilargiaren eta M45en hurbilketa')

        # Step 3: Verify notification would use translated text
        result = _format_event_for_output(
            Event(news_id='e2e_001', title='Moon and M45 Conjunction', event_date=datetime.now()),
            self.db,
            ['eu']
        )

        # Should have translation info in output
        self.assertIn('target_lang', result)


if __name__ == '__main__':
    unittest.main()
