"""Mastodon poster for astronomical events happening tonight.

Posts a formatted message about the next astronomical event to Mastodon,
including visibility info and in-the-sky.org link. All text is in Basque.
"""

import os
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional

try:
    from mastodon import Mastodon
except ImportError:
    Mastodon = None


@dataclass
class EventPost:
    """Represents a formatted event post for Mastodon."""
    title: str  # "Gaurko gertaera astronomikoa"
    subtitle: str  # Event name (translated)
    description: str  # Short description (< 150 chars, translated)
    visibility_emoji: str  # 👁️ or 🔭 or 🌙
    url: str  # in-the-sky.org URL

    def to_mastodon_status(self) -> str:
        """Format as Mastodon status (max 500 chars)."""
        return f"{self.title}\n{self.subtitle}\n\n{self.description} {self.visibility_emoji}\n\n[EN] {self.url}"


# Mastodon instance configuration
MASTODON_INSTANCE = os.environ.get("MASTODON_INSTANCE", "mastodon.social")
MASTODON_ACCESS_TOKEN = os.environ.get("MASTODON_ACCESS_TOKEN", "")

# Visibility mapping based on event type and priority
VISIBILITY_EMOJIS = {
    "meteor_shower": "👁️",  # Meteor showers visible to naked eye
    "eclipse": "👁️",  # Eclipses (if safe)
    "occultation": "🔭",  # Occultations need telescope
    "conjunction": "🔭",  # Conjunctions often need telescope
    "close_approach": "🔭",  # Close approaches need telescope
    "comet": "🔭",  # Comets usually need telescope
}

# Complete Basque translations for event titles (key = English pattern, value = Basque)
TITLE_TRANSLATIONS = {
    # Meteor showers - complete replacements
    "Lyrid meteor shower 2026": "Lyrid meteor txarrua 2026",
    "Lyrid meteor shower": "Lyrid meteor txarrua",
    "Perseid meteor shower": "Perseo meteor txarrua",
    "Geminid meteor shower": "Geminoide meteor txarrua",
    "Quadrantid meteor shower": "Kuadrantide meteor txarrua",

    # Eclipses - complete replacements
    "Solar eclipse": "Eguzki eklipsea",
    "Lunar eclipse": "Ilargi eklipsea",
    "Total solar eclipse": "Eguzki eklipse osoa",
    "Partial lunar eclipse": "Ilargi eklipse partziala",

    # Occultations - complete replacements
    "Lunar occultation of Beta Tauri": "Beta Tauriren ilargi eklipsea",
    "Lunar occultation": "Ilargi eklipsea",
    "Stellar occultation by asteroid 704 Tama": "704 Tama asteroidearen izar eklipsea",
    "Asteroid occultation": "Asteroide eklipsea",

    # Conjunctions and approaches - complete replacements
    "Close approach of the Moon and Jupiter": "Ilargia eta Jupiterren hurbilketa",
    "Conjunction of the Moon and Jupiter": "Ilargia eta Jupiterren konjuntzioa",
    "Moon and Jupiter share the same right ascension": "Ilargia eta Jupiterrek ascendente zuzen bera partekatzen dute",

    # Comets - complete replacements
    "Comet 141P/Machholz passes perihelion": "141P/Machholz kometak perihelioa gainditzen du",
    "Comet 141P/Machholz makes its closest approach to the Sun": "141P/Machholz kometaren Eguzkiko hurbilketa handiena",

    # General patterns (will be used for partial matching)
}


def translate_title(title: str) -> str:
    """Translate event title to Basque.

    Uses exact matches first, then pattern-based replacements.
    Falls back to original if no translation found.
    Strips date prefixes for cleaner output.
    """
    # Strip date prefix (e.g., "23 Apr 2026 (2 days away): ")
    import re
    clean_title = re.sub(r'^\d{1,2}\s+\w{3}\s+\d{4}\s*\([^)]*\)?:?\s*', '', title)

    # Check exact matches first (on cleaned title)
    for eng, basq in TITLE_TRANSLATIONS.items():
        if eng.lower() == clean_title.lower():
            return basq

    # Pattern-based translations (longest match wins)
    patterns = [
        ("meteor shower", "meteor txarrua"),
        ("lunar occultation of", "ilargi eklipsea"),
        ("stellar occultation by asteroid", "izar eklipsea asteroideak"),
        ("asteroid occultation", "asteroide eklipsea"),
        ("close approach of the moon and", "ilargia eta ... hurbilketa"),
        ("conjunction of the moon and", "ilargia eta ... konjuntzioa"),
        ("passes perihelion", "perihelioa gainditzen du"),
        ("closest approach to the sun", "Eguzkiko hurbilketa handiena"),
    ]

    result = clean_title
    for eng, basq in patterns:
        if eng.lower() in result.lower():
            # Replace the English pattern with Basque equivalent
            idx = result.lower().index(eng)
            before = result[:idx]
            after = result[idx + len(eng):]

            if "meteor shower" in eng:
                result = f"{before.strip()} {basq}"
            elif "occultation" in eng:
                result = f"{after.strip()}"  # Keep the rest (star/asteroid name)
            else:
                result = f"{before.strip()} {basq}{after.strip()}"

    return result


def translate_description(desc: str, event_type: str) -> str:
    """Translate description to Basque.

    Translates complete phrases and patterns in the description.
    Falls back to original if no translation found.
    """
    # Complete phrase translations (order matters - longer first)
    phrase_translations = [
        ("reaches its peak", "goragunean da"),
        ("will pass in front of", "aurkitik pasatuko du"),
        ("passes in front of", "aurkitik pasatzen du"),
        ("makes its closest approach to the Sun", "Eguzkiko hurbilketa handiena egiten du"),
        ("closest approach to the Sun", "hurbilketa handiena Eguzkira"),
        ("share the same right ascension", "ascendente zuzen bera partekatzen dute"),
        ("pass close to each other", "elkarrengana hurbiltzen dira"),
        ("creating a lunar occultation", "ilargi eklipsea sortuz"),
    ]

    result = desc
    for eng, basq in phrase_translations:
        if eng.lower() in desc.lower():
            # Replace the entire English phrase with Basque equivalent
            idx = desc.lower().index(eng)
            before = desc[:idx]
            after = desc[idx + len(eng):]

            # Capitalize first letter of result
            replacement = basq.capitalize() if before.strip() else basq
            result = f"{before.strip()} {replacement}{after.strip()}"

    return result


def get_visibility_emoji(event_type: str, priority: int) -> str:
    """Get visibility emoji based on event type and priority."""
    if event_type in VISIBILITY_EMOJIS:
        return VISIBILITY_EMOJIS[event_type]

    # Default based on priority
    if priority <= 2:
        return "👁️"  # High priority events often visible
    return "🔭"  # Lower priority usually need telescope


def truncate_description(text: str, max_chars: int = 150) -> str:
    """Truncate description to max_chars without breaking words."""
    if len(text) <= max_chars:
        return text

    # Find last space before max_chars
    truncated = text[:max_chars].rsplit(" ", 1)[0]
    return truncated.rstrip() + "…"


def get_tonight_events(db_path: str, hours_ahead: int = 8) -> list:
    """Get events happening within the next N hours from now.

    Args:
        db_path: Path to SQLite database
        hours_ahead: Number of hours to look ahead (default 8 for evening)

    Returns:
        List of Event objects sorted by event_date
    """
    from db_manager import DatabaseManager

    db = DatabaseManager(db_path)
    now = datetime.now()
    cutoff = now + timedelta(hours=hours_ahead)

    # Get all upcoming events and filter by date range
    all_events = db.get_upcoming_events(days=30)
    tonight_events = []

    for event in all_events:
        if isinstance(event.event_date, str):
            event_date = datetime.fromisoformat(event.event_date)
        else:
            event_date = event.event_date

        # Check if event is within the next N hours but not in the past
        if now <= event_date <= cutoff:
            tonight_events.append(event)

    return sorted(tonight_events, key=lambda e: e.event_date)


def create_event_post(event, db_path: str = None) -> EventPost:
    """Create a formatted Mastodon post from an event.

    Args:
        event: Event object from database
        db_path: Path to database (for fetching description if needed)

    Returns:
        Formatted EventPost ready for Mastodon
    """
    # Use stored description or fetch from DB
    raw_description = event.description or ""

    # Translate title and description to Basque
    translated_title = translate_title(event.title)
    translated_desc = translate_description(raw_description, event.event_type)

    # Truncate to 150 chars max
    translated_desc = truncate_description(translated_desc, 150)

    # Get visibility emoji
    visibility_emoji = get_visibility_emoji(event.event_type, event.priority)

    return EventPost(
        title="Gaurko gertaera astronomikoa",
        subtitle=translated_title,
        description=translated_desc,
        visibility_emoji=visibility_emoji,
        url=event.event_page_url or "",
    )


def post_to_mastodon(status: str) -> bool:
    """Post a status to Mastodon.

    Args:
        status: The status text to post (max 500 chars for Mastodon)

    Returns:
        True if successful, False otherwise
    """
    if not MASTODON_ACCESS_TOKEN:
        print("⚠️ Mastodon token not configured")
        return False

    if Mastodon is None:
        print("❌ mastodon.py not installed")
        return False

    try:
        mastodon = Mastodon(
            client_id=None,  # Using access token only
            api_base_url=MASTODON_INSTANCE,
            access_token=MASTODON_ACCESS_TOKEN,
        )
        mastodon.status_post(status)
        print(f"✅ Posted to Mastodon: {status[:50]}...")
        return True
    except Exception as e:
        print(f"❌ Failed to post to Mastodon: {e}")
        return False


def create_digest_post(db_path: str, days_ahead: int = 14) -> Optional[str]:
    """Create a condensed digest of upcoming astronomical events for Mastodon.

    Args:
        db_path: Path to SQLite database
        days_ahead: Number of days to look ahead (default 14)

    Returns:
        Formatted status string (max 500 chars) or None if no events
    """
    from db_manager import DatabaseManager

    db = DatabaseManager(db_path)
    try:
        all_events = db.get_upcoming_events(days=days_ahead)
    finally:
        db.close()

    # Include ALL upcoming events in the daily digest (not just P1-P3)
    priority_events = list(all_events)  # copy, no filtering

    if not priority_events:
        return "🔭 Astronomia Digest\nEz dago gertaerarik hurrengo egunetan.\n📋 0 gertaera | 👁️=Begi hutsez | 🔭=Teleskopioa"

    # Sort by date
    priority_events.sort(key=lambda e: e.event_date)

    # Build condensed lines (max ~45 chars each to fit Mastodon)
    L1, L2, L3 = "🔴", "🟠", "🟡"
    lines = ["🔭 Astronomia Digest"]

    for event in priority_events:
        # Translate title to Basque
        basq_title = translate_title(event.title)
        emoji = get_visibility_emoji(event.event_type, event.priority)

        # Condense: P + short title (max 30 chars) + emoji
        line = f"{L1 if event.priority == 1 else L2 if event.priority == 2 else L3} {basq_title[:30]} {emoji}"
        lines.append(line)

    # Add footer
    lines.append(f"📋 {len(priority_events)} gertaera | 👁️=Begi hutsez | 🔭=Teleskopioa")

    status = "\n".join(lines)

    # Truncate to 500 chars if needed (remove last line if too long)
    while len(status) > 500 and len(lines) > 2:
        lines.pop()
        status = "\n".join(lines)
        break  # Only one truncation pass

    return status if len(status) <= 500 else None


def run_mastodon_post(db_path: str = "data/events.db") -> bool:
    """Main function to check for tonight's events and post to Mastodon.

    Args:
        db_path: Path to SQLite database

    Returns:
        True if a post was made, False otherwise
    """
    # Get events happening in the next 8 hours (evening window)
    tonight_events = get_tonight_events(db_path, hours_ahead=8)

    if not tonight_events:
        print("ℹ️ No astronomical events scheduled for tonight")
        return False

    # Post about the first/next event
    next_event = tonight_events[0]
    post = create_event_post(next_event, db_path)
    status = post.to_mastodon_status()

    # Check Mastodon character limit (500 chars)
    if len(status) > 500:
        print(f"⚠️ Status too long ({len(status)} chars), truncating...")
        status = status[:497] + "..."

    return post_to_mastodon(status)


def post_digest_to_mastodon(db_path: str = "data/events.db") -> bool:
    """Post a condensed digest of upcoming events to Mastodon.

    Args:
        db_path: Path to SQLite database

    Returns:
        True if posted, False otherwise
    """
    status = create_digest_post(db_path)
    if not status:
        print("ℹ️ No priority events for digest")
        return False

    print(f"📋 Digest ({len(status)} chars):\n{status}")
    return post_to_mastodon(status)


if __name__ == "__main__":
    import sys

    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/events.db"
    mode = sys.argv[2] if len(sys.argv) > 2 else "event"  # "event" or "digest"

    if mode == "digest":
        success = post_digest_to_mastodon(db_path)
    else:
        success = run_mastodon_post(db_path)
    sys.exit(0 if success else 1)
