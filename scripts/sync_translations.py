#!/usr/bin/env python3
"""Sync translations from translations table to events table.

After running `translate --lang eu`, translations are stored in the
`translations` table. The `events` table has parallel `translated_*`
columns that remain empty. This script syncs them.

Usage:
    cd /home/urtzai/.hermes/skills/astronomical-events
    .venv/bin/python scripts/sync_translations.py [--lang eu]
"""

import argparse
import sqlite3
import os


def sync_translations(target_lang: str = "eu") -> int:
    """Sync translations from `translations` to `events` table.

    Args:
        target_lang: Target language code (default: 'eu')

    Returns:
        Number of events synced
    """
    # Resolve paths relative to this script's parent (project root)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    db_path = os.path.join(project_root, "data", "events.db")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Get events that have translations
    cur.execute("""
        SELECT news_id, translated_title, translated_description,
               translated_rich_description, translated_viewing_info
        FROM events
        WHERE news_id IN (
            SELECT news_id FROM translations WHERE target_lang = ?
        )
    """, (target_lang,))
    existing = cur.fetchall()

    # Build updates
    updates = 0
    for row in existing:
        news_id = row["news_id"]

        # Fetch translations
        cur.execute("""
            SELECT translated_title, translated_description,
                   translated_rich_description, translated_viewing_info
            FROM translations
            WHERE news_id = ? AND target_lang = ?
        """, (news_id, target_lang))
        trans = cur.fetchone()
        if not trans:
            continue

        # Update events table columns (COALESCE: only fill if empty)
        cur.execute("""
            UPDATE events SET
                translated_title = COALESCE(?, translated_title),
                translated_description = COALESCE(?, translated_description),
                translated_rich_description = COALESCE(?, translated_rich_description),
                translated_viewing_info = COALESCE(?, translated_viewing_info),
                updated_at = datetime('now')
            WHERE news_id = ?
        """, (
            trans["translated_title"] or "",
            trans["translated_description"] or "",
            trans["translated_rich_description"] or "",
            trans["translated_viewing_info"] or "",
            news_id,
        ))
        if cur.rowcount > 0:
            updates += 1

    conn.commit()
    conn.close()
    return updates


def main():
    parser = argparse.ArgumentParser(
        description="Sync translations from translations table to events table"
    )
    parser.add_argument(
        "--lang",
        type=str,
        default="eu",
        help="Target language code (default: eu)",
    )
    args = parser.parse_args()

    count = sync_translations(args.lang)
    print(f"✅ Synced {count} event(s) to events table for language '{args.lang}'")


if __name__ == "__main__":
    main()
