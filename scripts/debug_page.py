#!/usr/bin/env python3
"""Debug/test script for _extract_rich_description() and _extract_viewing_info().

Tests both functions against real in-the-sky.org event pages of different types:
- Asteroid/dwarf planet opposition (Haumea)
- Lunar occultation (Beta Tauri, Regulus)
- Planet conjunction (Saturn & Mars, Mercury & Saturn)
- Meteor shower (Lyrids, Pi-Puppids)
- Comet perihelion (C/2025 R3)

Run: python scripts/debug_page.py
"""

import sys
import os
import logging
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Enable debug logging
logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")

from page_scraper import fetch_event_page, parse_page


# Test URLs covering different event types
TEST_URLS = [
    # Asteroid/dwarf planet opposition
    {
        "url": "https://in-the-sky.org/news.php?id=20260423_13_100",
        "type": "asteroid_opposition",
        "title": "136108 Haumea at opposition",
    },
    # Lunar occultation (Beta Tauri)
    {
        "url": "https://in-the-sky.org/news.php?id=20260421_16_100",
        "type": "lunar_occultation",
        "title": "Lunar occultation of Beta Tauri",
    },
    # Planet conjunction (Saturn & Mars)
    {
        "url": "https://in-the-sky.org/news.php?id=20260420_20_102",
        "type": "planet_conjunction",
        "title": "Conjunction of Saturn and Mars",
    },
    # Meteor shower (Lyrids)
    {
        "url": "https://in-the-sky.org/news.php?id=20260424_10_100",
        "type": "meteor_shower",
        "title": "Lyrid meteor shower 2026",
    },
    # Comet perihelion (C/2025 R3)
    {
        "url": "https://in-the-sky.org/news.php?id=2026_19_CK25R030_100",
        "type": "comet_perihelion",
        "title": "Comet C/2025 R3 (PANSTARRS) passes perihelion",
    },
    # Another lunar occultation (Regulus) - different geometry
    {
        "url": "https://in-the-sky.org/news.php?id=20260426_16_100",
        "type": "lunar_occultation_regulus",
        "title": "Lunar occultation of Regulus",
    },
    # Another planet conjunction (Mercury & Saturn)
    {
        "url": "https://in-the-sky.org/news.php?id=20260420_15_100",
        "type": "planet_conjunction_mercury_saturn",
        "title": "Close approach of Mercury and Saturn",
    },
    # Moon conjunction (Venus) - edge case for viewing info extraction
    {
        "url": "https://in-the-sky.org/news.php?id=20260419_20_100",
        "type": "moon_conjunction",
        "title": "Conjunction of the Moon and Venus",
    },
    # Additional regression tests for Phase 6
    # η-Aquariid meteor shower (another meteor shower type)
    {
        "url": "https://in-the-sky.org/news.php?id=20260506_10_100",
        "type": "meteor_shower_aquariids",
        "title": "η-Aquariid meteor shower 2026",
    },
    # Close approach of Moon and M44 (Moon + deep sky object)
    {
        "url": "https://in-the-sky.org/news.php?id=20260424_15_100",
        "type": "moon_deepsky_approach",
        "title": "Close approach of the Moon and M44",
    },
    # Conjunction of Venus and Uranus (planet + planet, different from Saturn/Mars)
    {
        "url": "https://in-the-sky.org/news.php?id=20260424_20_100",
        "type": "planet_conjunction_uranus",
        "title": "Conjunction of Venus and Uranus",
    },
    # Conjunction of Mercury and Eris (Moon + dwarf planet)
    {
        "url": "https://in-the-sky.org/news.php?id=20260502_20_100",
        "type": "moon_dwarf_conjunction",
        "title": "Conjunction of Mercury and Eris",
    },
    # Moon at First Quarter (moon phase event)
    {
        "url": "https://in-the-sky.org/news.php?id=20260424_08_100",
        "type": "moon_phase",
        "title": "Moon at First Quarter",
    },
]


def test_url(test_case):
    """Fetch a page, parse it, and print extracted rich metadata."""
    url = test_case["url"]
    name = test_case["type"]
    title = test_case["title"]

    print(f"\n{'='*70}")
    print(f"TEST: {name} — {title}")
    print(f"URL:  {url}")
    print(f"{'='*70}")

    # Fetch page HTML
    html = fetch_event_page(url, use_cache=False)
    if not html:
        print("❌ FAILED to fetch page")
        return False

    # Parse
    data = parse_page(html)
    if not data:
        print("❌ FAILED to parse page")
        return False

    # Print results
    print(f"\n📷 Thumbnail: {data.thumbnail_url or '(none)'}")
    print(f"🔭 Visibility: Level {data.visibility_level} — {data.visibility_text or '(no alt text)'}")

    print(f"\n--- rich_description_en ---")
    desc = data.rich_description_en
    if desc:
        # Show first 500 chars
        preview = desc[:500] + ("..." if len(desc) > 500 else "")
        print(preview)
        print(f"\n[Total length: {len(desc)} chars]")
    else:
        print("(empty)")

    print(f"\n--- viewing_info_en ---")
    info = data.viewing_info_en
    if info:
        preview = info[:500] + ("..." if len(info) > 500 else "")
        print(preview)
        print(f"\n[Total length: {len(info)} chars]")
    else:
        print("(empty)")

    # Check for issues
    issues = []
    if not desc and name in ["comet_perihelion", "meteor_shower"]:
        issues.append("No rich description extracted (expected content)")
    if not info and name in ["lunar_occultation", "planet_conjunction"]:
        issues.append("No viewing info extracted (expected content)")

    # Check for noise leakage (standalone lines, not substrings of real content)
    import re
    noise_patterns = [
        r"^From\s+(the\s+\w+\s+)?feed",
        r",\s*Editor$",
        r"^Click and drag$",
        r"^Begin typing$",
        r"^Loading$",
    ]
    for pat in noise_patterns:
        if re.search(pat, desc, re.I):
            issues.append(f"Noise leaked into description: pattern '{pat}' matched")

    if issues:
        print(f"\n⚠️  ISSUES FOUND:")
        for iss in issues:
            print(f"   - {iss}")
        return False
    else:
        print("\n✅ No obvious issues detected")
        return True


def main():
    """Run all tests and summarize results."""
    print("🧪 Testing _extract_rich_description() and _extract_viewing_info()")
    print(f"Testing {len(TEST_URLS)} event pages...\n")

    results = []
    for tc in TEST_URLS:
        ok = test_url(tc)
        results.append((tc["type"], ok))

    # Summary
    print(f"\n{'='*70}")
    print("📊 SUMMARY")
    print(f"{'='*70}")
    passed = sum(1 for _, ok in results if ok)
    failed = len(results) - passed
    for name, ok in results:
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"  {status} — {name}")
    print(f"\nTotal: {passed}/{len(results)} passed")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
