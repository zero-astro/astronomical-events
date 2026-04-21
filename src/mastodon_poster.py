"""Mastodon poster for astronomical events happening tonight.

Posts a formatted message about the next astronomical event to Mastodon,
including visibility info and in-the-sky.org link.
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
    subtitle: str  # Event name
    description: str  # Short description (< 150 chars)
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
    from src.db_manager import DatabaseManager

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
    description = event.description or ""

    # Truncate to 150 chars max
    description = truncate_description(description, 150)

    # Get visibility emoji
    visibility_emoji = get_visibility_emoji(event.event_type, event.priority)

    return EventPost(
        title="Gaurko gertaera astronomikoa",
        subtitle=event.title,
        description=description,
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
            token=MASTODON_ACCESS_TOKEN,
        )
        mastodon.status_post(status)
        print(f"✅ Posted to Mastodon: {status[:50]}...")
        return True
    except Exception as e:
        print(f"❌ Failed to post to Mastodon: {e}")
        return False


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


if __name__ == "__main__":
    import sys

    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/events.db"
    success = run_mastodon_post(db_path)
    sys.exit(0 if success else 1)
