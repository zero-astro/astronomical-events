"""Translation orchestration layer — batch translate missing events.

Integrates with db_manager and translate modules to handle the full
translation pipeline: query untranslatable events, call provider API,
store results back into DB.
"""

import json
import logging
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

    Uses GLOBAL BATCHING (Option 1): collects ALL titles/descriptions/rich_descriptions/
    viewing_info from ALL events needing translation and sends ONE batch call per field type.
    Max 4 API calls total per language regardless of event count (vs 2N with per-event).

    Uses checkpoint resume: if a previous run was interrupted, resumes from
    the last successfully processed index instead of starting over.

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

        # Resume from checkpoint if available
        start_idx = db.get_checkpoint(lang)
        if start_idx > 0:
            logger.info(
                f"Resuming {lang} translation from index {start_idx}/{len(events)} "
                f"(checkpoint found)"
            )
            events = events[start_idx:]

        num_events = len(events)
        logger.info(f"Translating {num_events} event(s) to {lang} (global batch mode)")

        lang_results = {"translated": 0, "skipped": 0, "failed": 0}

        try:
            from translate import global_batch_translate, TranslationError

            # Global batch: ONE call per field type for ALL events
            batch_results = global_batch_translate(events, lang, provider_config)

            # Distribute results back to each event and store in DB
            for idx, result in enumerate(batch_results):
                if result is None:
                    logger.error(f"Translation returned None for {events[idx].news_id}")
                    lang_results["failed"] += 1
                    total_failed += 1
                    continue

                # Validate: skip storage if critical fields are empty
                title = result.get("translated_title", "").strip()
                desc = result.get("translated_description", "").strip()

                if not title:
                    logger.error(
                        f"Empty translated title for {events[idx].news_id} — skipping storage"
                    )
                    lang_results["skipped"] += 1
                    total_skipped += 1
                    continue

                # Store translation
                db.insert_or_update_translation(
                    news_id=events[idx].news_id,
                    target_lang=lang,
                    translated_title=result.get("translated_title", ""),
                    translated_description=result.get("translated_description", ""),
                    provider=provider_config["provider"],
                    translated_rich_description=result.get("translated_rich_description", ""),
                    translated_viewing_info=result.get("translated_viewing_info", "")
                )

                lang_results["translated"] += 1
                total_translated += 1
                logger.info(f"✓ Translated {events[idx].news_id} to {lang}")

            # Update checkpoint: all events processed in one batch call
            db.update_checkpoint(lang, start_idx + num_events)

        except TranslationError as e:
            # Circuit breaker or health check failure — skip entire language batch
            logger.error(f"Circuit breaker/health failure for {lang}: {e}")
            lang_results["skipped"] = num_events
            total_skipped += num_events

        except Exception as e:
            logger.error(f"Failed to translate {lang} (global batch): {e}")
            lang_results["failed"] = num_events
            total_failed += num_events

        results[lang] = lang_results
        logger.info(
            f"Language {lang}: {lang_results['translated']} translated, "
            f"{lang_results['failed']} failed, {lang_results['skipped']} skipped"
        )

    return results


def translate_single_event(db, event, provider_config: dict, target_lang: str) -> bool:
    """Translate a single event and store the result (Phase 6: full metadata).

    Args:
        db: DatabaseManager instance
        event: Event object with title/description/rich_description_en/viewing_info_en
        provider_config: Provider config dict
        target_lang: Target language code

    Returns:
        True if translation was stored successfully
    """
    try:
        from translate import translate_event, TranslationError
        
        result = translate_event(event, provider_config, target_lang)
        if result is None:
            logger.error(f"Translation returned None for {event.news_id}")
            return False
        
        db.insert_or_update_translation(
            news_id=event.news_id,
            target_lang=target_lang,
            translated_title=result["translated_title"],
            translated_description=result.get("translated_description", ""),
            provider=provider_config["provider"],
            translated_rich_description=result.get("translated_rich_description", ""),
            translated_viewing_info=result.get("translated_viewing_info", "")
        )
        logger.info(f"Translated {event.news_id} to {target_lang}")
        return True
        
    except TranslationError as e:
        # Circuit breaker or health check failure — skip, do NOT store anything
        logger.error(f"Circuit breaker/health failure for {event.news_id}: {e}")
        return False
        
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
        Dict with translated_title, translated_description, translated_rich_description,
        translated_viewing_info, and provider — or None (if cached data is invalid)
    """
    row = db.get_translation(news_id, target_lang)
    if row is None:
        return None
    
    # Validate that the title is not empty before returning cached data
    title = row.get("translated_title", "").strip()
    if not title:
        logger.warning(f"Cached translation for {news_id}/{target_lang} has empty title — invalid, skipping")
        return None
    
    return {
        "translated_title": row["translated_title"],
        "translated_description": row["translated_description"],
        "translated_rich_description": row.get("translated_rich_description", ""),
        "translated_viewing_info": row.get("translated_viewing_info", ""),
        "provider": row["provider"],
    }
