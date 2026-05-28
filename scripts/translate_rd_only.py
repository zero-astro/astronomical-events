#!/usr/bin/env python3
"""Translate only missing rich_description_en fields."""

import sys
sys.path.insert(0, '.')

from src.db_manager import DatabaseManager
from src.translate import get_provider_config, translate_batch
import logging
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def main():
    db = DatabaseManager('data/events.db')
    config = get_provider_config('lm-studio')
    
    # Get events with rich_description_en that need translation
    cursor = db.conn.cursor()
    cursor.execute('''
        SELECT e.news_id, e.rich_description_en
        FROM events e
        LEFT JOIN translations t ON e.news_id = t.news_id AND t.target_lang = 'eu'
        WHERE e.rich_description_en IS NOT NULL AND e.rich_description_en != ''
          AND (t.translated_rich_description IS NULL OR t.translated_rich_description = '')
    ''')
    
    events = cursor.fetchall()
    logger.info(f'Events needing rich description translation: {len(events)}')
    
    if not events:
        logger.info('Nothing to translate!')
        db.conn.close()
        return
    
    # Translate in batches of 2 (smallest stable batch)
    batch_size = 2
    for i in range(0, len(events), batch_size):
        batch = events[i:i+batch_size]
        texts = [e[1] for e in batch]
        ids = [e[0] for e in batch]
        
        try:
            logger.info(f'Batch {i//batch_size + 1}/{(len(events)+batch_size-1)//batch_size} ({len(texts)} items)')
            translated = translate_batch(texts, 'eu', config)
            
            for j, news_id in enumerate(ids):
                if j < len(translated):
                    db.insert_or_update_translation(
                        news_id=news_id, target_lang='eu',
                        provider='lm-studio',
                        translated_rich_description=translated[j]
                    )
            logger.info(f'Batch {i//batch_size + 1} done')
        except Exception as e:
            logger.error(f'Batch {i//batch_size + 1} failed: {e}')
        
        time.sleep(3)  # Longer delay between batches
    
    db.conn.close()
    logger.info('Done!')

if __name__ == '__main__':
    main()
