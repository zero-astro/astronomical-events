"""Translation orchestration layer — batch translate missing events.

Integrates with db_manager and translate modules to handle the full
translation pipeline: query untranslatable events, call provider API,
store results back into DB.
"""

import json
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


def get_target_languages(db) -> list[str]:
    """Read target languages from config table.

    Args:
        db: DatabaseManager instance

    Returns:
        List of language codes (e.g., ['eu', 'ca'])
    """
    cursor = db.conn.cursor()
    cursor.execute("SELECT value FROM config WHERE key='target_languages'")
    row = cursor.fetchone()
    if row is None or not row["value"]:
        return []
    try:
        langs = json.loads(row["value"])
        return [l.strip() for l in langs if l.strip()]
    except (json.JSONDecodeError, TypeError):
        logger.warning(f"Invalid target_languages config value: {row['value']}")
        return []


def translate_missing_events(db, provider_config: dict) -> dict:
    """Translate all events missing translations for configured languages.

    Groups events by language to minimize API calls (one batch per language).
    Respects rate limiting between batches.

    Args:
        db: DatabaseManager instance
        provider_config: Provider config dict from translate.get_provider_config()

    Returns:
        Dict with summary stats: {translated, skipped, failed} per language
    """
    target_langs = get_target_languages(db)
    if not target_langs:
        logger.info("No target languages configured; skipping translation")
        return {}

    results = {}
    total_translated = 0
    total_failed = 0
    total_skipped = 0

    for lang in target_langs:
        # Get events needing this language
        events = db.get_events_needing_translation([lang])
        
        if not events:
            logger.info(f"No events need translation to {lang}")
            results[lang] = {"translated": 0, "skipped": 0, "failed": 0}
            continue

        logger.info(f"Translating {len(events)} event(s) to {lang}")
        
        lang_results = {"translated": 0, "skipped": 0, "failed": 0}
        
        # Process events in batches of up to 20 titles per API call
        batch_size = 5
        for i in range(0, len(events), batch_size):
            batch = events[i:i + batch_size]
            
            try:
                from translate import translate_batch
                
                titles = [e.title for e in batch]
                translated_titles = translate_batch(titles, lang, provider_config)
                
                # Store translations one by one (descriptions may need separate handling)
                for j, event in enumerate(batch):
                    try:
                        db.insert_or_update_translation(
                            news_id=event.news_id,
                            target_lang=lang,
                            translated_title=translated_titles[j],
                            translated_description="",  # Will be filled on next pass if needed
                            provider=provider_config["provider"]
                        )
                        lang_results["translated"] += 1
                    except Exception as e:
                        logger.error(f"Failed to store translation for {event.news_id}: {e}")
                        lang_results["failed"] += 1
                
                total_translated += len(batch)
                
            except Exception as e:
                logger.error(f"Batch translation failed ({lang}, batch {i//batch_size + 1}): {e}")
                # Count remaining events in this batch as failed
                for event in batch:
                    lang_results["failed"] += 1
                    total_failed += 1

            # Rate limiting: wait between batches
            if i + batch_size < len(events):
                time.sleep(3)

        results[lang] = lang_results
        logger.info(f"Language {lang}: {lang_results['translated']} translated, "
                     f"{lang_results['failed']} failed")

    return results


def translate_single_event(db, event, provider_config: dict, target_lang: str) -> bool:
    """Translate a single event and store the result.

    Args:
        db: DatabaseManager instance
        event: Event object with title/description attributes
        provider_config: Provider config dict
        target_lang: Target language code

    Returns:
        True if translation was stored successfully
    """
    try:
        from translate import translate_event
        
        result = translate_event(event, provider_config, target_lang)
        if result is None:
            logger.error(f"Translation returned None for {event.news_id}")
            return False
        
        db.insert_or_update_translation(
            news_id=event.news_id,
            target_lang=target_lang,
            translated_title=result["translated_title"],
            translated_description=result["translated_description"],
            provider=provider_config["provider"]
        )
        logger.info(f"Translated {event.news_id} to {target_lang}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to translate single event {event.news_id}: {e}")
        return False


def get_translation_for_event(db, news_id: str, target_lang: str) -> Optional[dict]:
    """Get cached translation for an event.

    Args:
        db: DatabaseManager instance
        news_id: Event identifier
        target_lang: Target language code

    Returns:
        Dict with translated_title and translated_description, or None
    """
    row = db.get_translation(news_id, target_lang)
    if row is None:
        return None
    
    return {
        "translated_title": row["translated_title"],
        "translated_description": row["translated_description"],
        "provider": row["provider"],
    }
