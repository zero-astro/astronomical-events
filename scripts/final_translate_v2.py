#!/usr/bin/env python3
"""Final translation pass - translate only missing fields, one at a time."""

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
    
    # Process each event individually to avoid batch parsing issues
    for event in events:
        news_id, rd_en, vi_en = event[0], event[1] or '', event[2] or ''
        
        # Translate rich_description if missing
        if rd_en:
            try:
                logger.info(f'{news_id}: Translating rich_description ({len(rd_en)} chars)')
                translated_rd = translate_batch([rd_en], 'eu', config)[0]
                
                # Verify it's actually Basque (not English original)
                is_basque = any(w in translated_rd.lower() for w in ['izango da', 'egongo da', 'bere', 'hau', 'eta', 'pixka'])
                if not is_basque and len(translated_rd) > 50:
                    logger.warning(f'{news_id}: Translation may be English, retrying...')
                    # Retry with simpler prompt
                    translated_rd = translate_batch([rd_en], 'eu', config)[0]
                
                db.insert_or_update_translation(
                    news_id=news_id, target_lang='eu',
                    provider='lm-studio',
                    translated_rich_description=translated_rd
                )
                logger.info(f'{news_id}: RD stored ({len(translated_rd)} chars)')
            except Exception as e:
                logger.error(f'{news_id}: RD failed: {e}')
            
            time.sleep(3)  # Delay between translations
        
        # Translate viewing_info if missing
        if vi_en:
            try:
                logger.info(f'{news_id}: Translating viewing_info ({len(vi_en)} chars)')
                translated_vi = translate_batch([vi_en], 'eu', config)[0]
                
                is_basque = any(w in translated_vi.lower() for w in ['izango da', 'egongo da', 'bere', 'hau', 'eta'])
                if not is_basque and len(translated_vi) > 50:
                    logger.warning(f'{news_id}: VI translation may be English, retrying...')
                    translated_vi = translate_batch([vi_en], 'eu', config)[0]
                
                db.insert_or_update_translation(
                    news_id=news_id, target_lang='eu',
                    provider='lm-studio',
                    translated_viewing_info=translated_vi
                )
                logger.info(f'{news_id}: VI stored ({len(translated_vi)} chars)')
            except Exception as e:
                logger.error(f'{news_id}: VI failed: {e}')
            
            time.sleep(3)  # Delay between translations
    
    db.conn.close()
    logger.info('Done!')

if __name__ == '__main__':
    main()
