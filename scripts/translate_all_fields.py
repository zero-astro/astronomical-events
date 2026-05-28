#!/usr/bin/env python3
"""Translate ALL fields (title, description, rich_description, viewing_info) to Basque.

This script ensures every event in the database has complete translations:
- title → translated_title
- description → translated_description  
- rich_description_en → translated_rich_description
- viewing_info_en → translated_viewing_info

Optimized batching (T2): collects all items of each field type into one batch,
reducing API calls from N×4 to ~4 per run.

Usage: python3 scripts/translate_all_fields.py [--dry-run]
"""

import sys
sys.path.insert(0, '.')

from src.db_manager import DatabaseManager
from src.translate import get_provider_config, translate_batch
import logging
import time
import argparse
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


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
               COALESCE(e.viewing_info_en)
        FROM events e
        ORDER BY e.event_date DESC
    ''')

    all_events = cursor.fetchall()
    logger.info(f'Total events to process: {len(all_events)}')

    # ── T2: Collect items by field type (batch optimization) ──────────────
    # Group untranslated items by field_type for batch API calls
    batches = defaultdict(list)  # field_type -> [(news_id, source_text)]
    
    for event in all_events:
        news_id, title, desc, rich_desc, viewing_info = event
        
        existing = db.get_translation(news_id, target_lang)
        if not existing:
            existing = {}

        # Collect untranslated items per field type
        if not existing.get('translated_title') and title:
            batches['title'].append((news_id, title))
        
        if desc and not existing.get('translated_description'):
            batches['description'].append((news_id, desc))
        
        if rich_desc and not existing.get('translated_rich_description'):
            batches['rich_description'].append((news_id, rich_desc))
        
        if viewing_info and not existing.get('translated_viewing_info'):
            batches['viewing_info'].append((news_id, viewing_info))

    # Stats tracking
    stats = {
        'events_with_translations': 0,
        'skipped_events': 0,
        'failed_events': 0,
        'fields_translated': {'title': 0, 'description': 0, 'rich_description': 0, 'viewing_info': 0},
        'api_calls_saved': 0,
    }

    # ── T2: Process each field type in one batched pass ───────────────────
    field_type_map = {
        'title': ('translated_title', 'Title'),
        'description': ('translated_description', 'Description'),
        'rich_description': ('translated_rich_description', 'Rich description'),
        'viewing_info': ('translated_viewing_info', 'Viewing info'),
    }

    # Track per-event updates to avoid duplicate DB writes
    event_updates = defaultdict(dict)  # news_id -> {field: translated_text}

    for field_type, (db_field, display_name) in field_type_map.items():
        items = batches.get(field_type, [])
        if not items:
            logger.info(f'  ✅ {display_name}: all already translated ({len(items)} items)')
            continue

        # Split into chunks of max 20 (LLM API limit)
        chunk_size = 20
        for chunk_start in range(0, len(items), chunk_size):
            chunk = items[chunk_start:chunk_size + chunk_start]
            source_texts = [text for _, text in chunk]

            logger.info(f'\n📦 {display_name}: translating {len(source_texts)} items (batch {chunk_start // chunk_size + 1})')

            try:
                translated = translate_batch(source_texts, target_lang, config, field_type=field_type)
            except Exception as e:
                logger.error(f'  ❌ Failed to translate {display_name}: {e}')
                stats['failed_events'] += len(chunk)
                continue

            # Store results per event
            for (news_id, _), trans_text in zip(chunk, translated):
                if trans_text and len(trans_text.strip()) > 0:
                    event_updates[news_id][db_field] = trans_text
                    stats['fields_translated'][field_type] += 1

    # ── Save all translations to DB (one write per event) ────────────────
    if not args.dry_run and event_updates:
        logger.info(f'\n💾 Saving {len(event_updates)} events to database...')
        for news_id, updates in event_updates.items():
            try:
                db.insert_or_update_translation(
                    news_id=news_id,
                    target_lang=target_lang,
                    **updates,
                    provider='lm-studio'
                )
                stats['events_with_translations'] += 1
            except Exception as e:
                logger.error(f'  ❌ Failed to save event {news_id}: {e}')
                stats['failed_events'] += 1

    db.conn.close()

    # ── Summary ──────────────────────────────────────────────────────────
    total_api_calls = sum(
        max(1, len(items) // 20 + (1 if len(items) % 20 else 0))
        for items in batches.values()
    )
    naive_api_calls = sum(len(items) for items in batches.values())

    print('\n' + '=' * 60)
    print('TRANSLATION SUMMARY')
    print('=' * 60)
    print(f'Total events processed: {len(all_events)}')
    print(f'Events with new translations: {stats["events_with_translations"]}')
    print(f'Skipped (already translated): {stats["skipped_events"]}')
    print(f'Failed: {stats["failed_events"]}')
    print()
    print('Fields translated:')
    for field, count in stats['fields_translated'].items():
        print(f'  {field}: {count}')
    print()
    print(f'API calls made (batched): {total_api_calls}')
    print(f'API calls if naive (N×4): {naive_api_calls}')
    savings = max(0, naive_api_calls - total_api_calls)
    print(f'API calls saved: {savings} ({100*savings//max(1,naive_api_calls)}% reduction)')


if __name__ == '__main__':
    main()
