#!/usr/bin/env python3
"""Translate ALL fields (title, description, rich_description, viewing_info) to Basque.

This script ensures every event in the database has complete translations:
- title → translated_title
- description → translated_description  
- rich_description_en → translated_rich_description
- viewing_info_en → translated_viewing_info

Usage: python3 scripts/translate_all_fields.py [--dry-run]
"""

import sys
sys.path.insert(0, '.')

from src.db_manager import DatabaseManager
from src.translate import get_provider_config, translate_batch
import logging
import time
import argparse

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def translate_field(text: str, field_name: str, target_lang: str, config: dict) -> str | None:
    """Translate a single text field with quality check."""
    if not text or len(text.strip()) == 0:
        return None
    
    try:
        translated = translate_batch([text], target_lang, config)[0]
        
        # Basic quality check - ensure it's actually Basque (not English)
        basque_words = ['da', 'eta', 'bere', 'hau', 'izan', 'egongo', 'ikusi', 'behaketa']
        is_basque = any(w in translated.lower() for w in basque_words[:5])
        
        if not is_basque and len(translated) > 30:
            logger.warning(f'  Translation may be English, retrying...')
            time.sleep(2)
            translated = translate_batch([text], target_lang, config)[0]
        
        return translated
    except Exception as e:
        logger.error(f'  Failed to translate {field_name}: {e}')
        return None


def main():
    parser = argparse.ArgumentParser(description='Translate all event fields to Basque')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be translated without saving')
    args = parser.parse_args()
    
    db = DatabaseManager('data/events.db')
    config = get_provider_config('lm-studio')
    target_lang = 'eu'
    
    # Get all events that need translation
    cursor = db.conn.cursor()
    cursor.execute('''
        SELECT e.news_id, e.title, e.description, 
               COALESCE(e.rich_description_en, ''), 
               COALESCE(e.viewing_info_en, '')
        FROM events e
        ORDER BY e.event_date DESC
    ''')
    
    all_events = cursor.fetchall()
    logger.info(f'Total events to process: {len(all_events)}')
    
    stats = {
        'translated': 0,
        'skipped': 0,
        'failed': 0,
        'fields_translated': {'title': 0, 'description': 0, 'rich_description': 0, 'viewing_info': 0}
    }
    
    for event in all_events:
        news_id, title, desc, rich_desc, viewing_info = event
        
        logger.info(f'\n{news_id}: {title[:60]}...')
        
        # Get existing translations
        existing = db.get_translation(news_id, target_lang)
        if not existing:
            existing = {}
        
        needs_update = False
        updates = {}
        
        # 1. Translate title if missing or empty
        if not existing.get('translated_title'):
            translated = translate_field(title, 'title', target_lang, config)
            if translated:
                updates['translated_title'] = translated
                stats['fields_translated']['title'] += 1
                logger.info(f'  ✅ Title: {translated[:80]}')
                needs_update = True
        
        # 2. Translate description if missing or empty
        if desc and not existing.get('translated_description'):
            translated = translate_field(desc, 'description', target_lang, config)
            if translated:
                updates['translated_description'] = translated
                stats['fields_translated']['description'] += 1
                logger.info(f'  ✅ Description: {translated[:80]}')
                needs_update = True
        
        # 3. Translate rich_description if missing or empty
        if rich_desc and not existing.get('translated_rich_description'):
            translated = translate_field(rich_desc, 'rich_description', target_lang, config)
            if translated:
                updates['translated_rich_description'] = translated
                stats['fields_translated']['rich_description'] += 1
                logger.info(f'  ✅ Rich description: {translated[:80]}')
                needs_update = True
        
        # 4. Translate viewing_info if missing or empty
        if viewing_info and not existing.get('translated_viewing_info'):
            translated = translate_field(viewing_info, 'viewing_info', target_lang, config)
            if translated:
                updates['translated_viewing_info'] = translated
                stats['fields_translated']['viewing_info'] += 1
                logger.info(f'  ✅ Viewing info: {translated[:80]}')
                needs_update = True
        
        # Save translations (skip provider for dry-run)
        if needs_update and not args.dry_run:
            try:
                db.insert_or_update_translation(
                    news_id=news_id,
                    target_lang=target_lang,
                    **updates,
                    provider='lm-studio'
                )
                stats['translated'] += 1
                logger.info(f'  💾 Saved translations')
            except Exception as e:
                logger.error(f'  ❌ Failed to save: {e}')
                stats['failed'] += 1
        
        elif needs_update and args.dry_run:
            logger.info(f'  📋 [DRY RUN] Would save {len(updates)} fields')
        
        time.sleep(2)  # Rate limit between events
    
    db.conn.close()
    
    print('\n' + '=' * 60)
    print('TRANSLATION SUMMARY')
    print('=' * 60)
    print(f'Total events processed: {len(all_events)}')
    print(f'Events with new translations: {stats["translated"]}')
    print(f'Skipped (already translated): {stats["skipped"]}')
    print(f'Failed: {stats["failed"]}')
    print()
    print('Fields translated:')
    for field, count in stats['fields_translated'].items():
        print(f'  {field}: {count}')


if __name__ == '__main__':
    main()
