#!/usr/bin/env python3
"""Verify translations in the events table.

Checks that all expected fields are populated for the given language.

Usage:
    cd /home/urtzai/.hermes/skills/astronomical-events
    .venv/bin/python scripts/verify_translations.py [--lang eu]
"""

import argparse
import sqlite3
import os


def verify_translations(target_lang: str = "eu") -> None:
    """Verify translations are properly synced in events table.

    Args:
        target_lang: Target language code (default: 'eu')
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    db_path = os.path.join(project_root, "data", "events.db")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT news_id, translated_title, translated_description,
               rich_description_en, viewing_info_en
        FROM events
        WHERE translated_title IS NOT NULL
           OR translated_description IS NOT NULL
           OR rich_description_en IS NOT NULL
           OR viewing_info_en IS NOT NULL
        ORDER BY event_date DESC
    """)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        print(f"No translations found for language '{target_lang}'")
        return

    print(f"{len(rows)} event(s) with translations for '{target_lang}':")
    all_ok = True
    for r in rows:
        title_ok = bool(r["translated_title"])
        desc_ok = bool(r["translated_description"])
        rich_ok = bool(r["rich_description_en"])
        view_ok = bool(r["viewing_info_en"])

        status = "✅" if (title_ok and desc_ok and rich_ok and view_ok) else "⚠️"
        if not (title_ok and desc_ok and rich_ok and view_ok):
            all_ok = False

        print(f"  {status} {r['news_id']}: "
              f"title={'✅' if title_ok else '❌'}, "
              f"desc={'✅' if desc_ok else '❌'}, "
              f"rich={'✅' if rich_ok else '❌'}, "
              f"viewing={'✅' if view_ok else '❌'}")

    print()
    if all_ok:
        print("✅ All fields populated for all events.")
    else:
        print("⚠️ Some fields are missing. Run sync_translations.py first.")


def main():
    parser = argparse.ArgumentParser(
        description="Verify translations in events table"
    )
    parser.add_argument(
        "--lang",
        type=str,
        default="eu",
        help="Target language code (default: eu)",
    )
    args = parser.parse_args()

    verify_translations(args.lang)


if __name__ == "__main__":
    main()
