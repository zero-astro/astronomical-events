#!/usr/bin/env python3
"""Final translation pass for all missing rich_description and viewing_info."""

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
    
    # Get events with rich metadata that need translation
    cursor = db.conn.cursor()
    cursor.execute('''
        SELECT e.news_id, e.rich_description_en, e.viewing_info_en
        FROM events e
        LEFT JOIN translations t ON e.news_id = t.news_id AND t.target_lang = 'eu'
        WHERE (e.rich_description_en IS NOT NULL AND e.rich_description_en != '')
           OR (e.viewing_info_en IS NOT NULL AND e.viewing_info_en != '')
    ''')
    
    events = cursor.fetchall()
    logger.info(f'Total events with rich metadata: {len(events)}')
    
    # Separate RD and VI texts with their news_ids
    rd_data = []  # (news_id, text)
    vi_data = []
    
    for event in events:
        news_id, rd, vi = event[0], event[1] or '', event[2] or ''
        if rd:
            rd_data.append((news_id, rd))
        if vi:
            vi_data.append((news_id, vi))
    
    logger.info(f'Rich descriptions to translate: {len(rd_data)}')
    logger.info(f'Viewing infos to translate: {len(vi_data)}')
    
    # Translate rich descriptions in batches of 2 (smaller for stability)
    batch_size = 2
    if rd_data:
        logger.info('Translating rich descriptions...')
        for i in range(0, len(rd_data), batch_size):
            batch = rd_data[i:i+batch_size]
            texts = [t[1] for t in batch]
            ids = [t[0] for t in batch]
            
            try:
                logger.info(f'  Batch {i//batch_size + 1}/{(len(rd_data)+batch_size-1)//batch_size} ({len(texts)} items)')
                translated = translate_batch(texts, 'eu', config)
                
                for j, news_id in enumerate(ids):
                    if j < len(translated):
                        db.insert_or_update_translation(
                            news_id=news_id, target_lang='eu',
                            provider='lm-studio',
                            translated_rich_description=translated[j]
                        )
                logger.info(f'  Batch {i//batch_size + 1} done')
            except Exception as e:
                logger.error(f'  Batch {i//batch_size + 1} failed: {e}')
            
            time.sleep(3)  # Delay between batches
    
    # Translate viewing infos in batches of 2
    if vi_data:
        logger.info('Translating viewing infos...')
        for i in range(0, len(vi_data), batch_size):
            batch = vi_data[i:i+batch_size]
            texts = [t[1] for t in batch]
            ids = [t[0] for t in batch]
            
            try:
                logger.info(f'  Batch {i//batch_size + 1}/{(len(vi_data)+batch_size-1)//batch_size} ({len(texts)} items)')
                translated = translate_batch(texts, 'eu', config)
                
                for j, news_id in enumerate(ids):
                    if j < len(translated):
                        db.insert_or_update_translation(
                            news_id=news_id, target_lang='eu',
                            provider='lm-studio',
                            translated_viewing_info=translated[j]
                        )
                logger.info(f'  Batch {i//batch_size + 1} done')
            except Exception as e:
                logger.error(f'  Batch {i//batch_size + 1} failed: {e}')
            
            time.sleep(3)
    
    db.conn.close()
    logger.info('Done!')

if __name__ == '__main__':
    main()
