"""Event classifier - determine event type and priority tier."""

import re
from dataclasses import dataclass


@dataclass
class Classification:
    """Result of classifying an astronomical event."""
    event_type: str = "unknown"
    priority: int = 5
    is_meteor_shower_peak: bool = False
    is_occultation_visible: bool = False

    @property
    def label(self) -> str:
        labels = {
            1: "Critical",
            2: "High",
            3: "Medium",
            4: "Low",
            5: "Minor",
        }
        return labels.get(self.priority, "Unknown")


def classify_event(title: str, description_text: str = "") -> Classification:
    """Classify an astronomical event by type and priority.

    Args:
        title: Event title from RSS feed
        description_text: Plain text description (for occultation visibility check)

    Returns:
        Classification with event_type and priority
    """
    title_lower = title.lower()
    desc_lower = description_text.lower() if description_text else ""
    combined = f"{title_lower} {desc_lower}"

    classification = Classification()

    # P1: Critical - Eclipses, Novae/Supernovae, Comet discoveries
    if _is_eclipse(combined):
        classification.event_type = "eclipse"
        classification.priority = 1
        return classification

    if _is_nova_or_supernova(combined):
        classification.event_type = "nova_supernova"
        classification.priority = 1
        return classification

    # P2: High - Meteor shower peaks, Occultations visible from Europe
    if _is_meteor_shower_peak(title_lower):
        classification.event_type = "meteor_shower"
        classification.is_meteor_shower_peak = True
        classification.priority = 2
        return classification

    # Meteor showers (non-peak) are still interesting - P3 medium priority
    if _is_meteor_shower(title_lower):
        classification.event_type = "meteor_shower"
        classification.priority = 3
        return classification

    if _is_occultation(combined):
        classification.event_type = "occultation"
        # Check if visible from user's location (Europe)
        classification.is_occultation_visible = _is_visible_from_europe(desc_lower, title_lower)
        
        # Distinguish between lunar occultations (common, lower priority) 
        # and asteroid/stellar occultations (rare, higher priority)
        is_lunar = "lunar" in title_lower or "moon" in title_lower
        if is_lunar:
            classification.priority = 4  # Common event
        else:
            classification.priority = 2  # Rare/interesting event
        return classification

    # P3: Medium - Planet close approaches (non-Moon), Comet perihelion
    if _is_planet_close_approach(title_lower):
        classification.event_type = "close_approach"
        classification.priority = 3
        return classification

    if _is_comet_perihelion(combined):
        classification.event_type = "comet"
        classification.priority = 3
        return classification

    # P4: Low - Planet conjunctions, Dwarf planet oppositions (non-Moon)
    if _is_planet_conjunction(title_lower):
        classification.event_type = "conjunction"
        classification.priority = 4
        return classification

    if _is_dwarf_planet_opposition(combined):
        classification.event_type = "opposition"
        classification.priority = 4
        return classification

    # P5: Minor - Moon conjunctions, routine events
    if _has_moon_involvement(title_lower):
        classification.event_type = "moon_conjunction"
        classification.priority = 5
        return classification

    # Fallback: check if it looks like a generic event (conjunction without moon)
    if _looks_like_generic_event(title_lower):
        classification.event_type = "conjunction"
        classification.priority = 4
        return classification

    # Ultimate fallback: unknown event type, lowest priority
    classification.event_type = "unknown"
    classification.priority = 5
    return classification


def _is_eclipse(text: str) -> bool:
    """Check if the text describes an eclipse."""
    eclipse_patterns = [
        r"\beclipse\b",
        r"solar eclipse",
        r"lunar eclipse",
        r"total solar eclipse",
        r"partial eclipse",
    ]
    return any(re.search(p, text) for p in eclipse_patterns)


def _is_nova_or_supernova(text: str) -> bool:
    """Check if the text describes a nova or supernova."""
    patterns = [
        r"\bnova\b",
        r"\bsupernova\b",
        r"new star",
        r"comet discovery",
        r"discovered comet",
    ]
    return any(re.search(p, text) for p in patterns)


def _is_meteor_shower(text: str) -> bool:
    """Check if this is a meteor shower event (any type)."""
    return "meteor shower" in text or "meteor showers" in text

def _is_meteor_shower_peak(text: str) -> bool:
    """Check if this is a meteor shower peak event."""
    has_meteor = "meteor shower" in text or "meteor showers" in text
    has_peak = any(w in text for w in ["peak", "maximum", "maxima"])
    return has_meteor and has_peak


def _is_occultation(text: str) -> bool:
    """Check if the text describes an occultation."""
    return "occultation" in text or "occults" in text


def _is_visible_from_europe(description: str, title: str = "") -> bool:
    """Check if an occultation is visible from Europe.

    Looks for country/region mentions in the description or title.
    Common European countries to check for.
    """
    european_countries = [
        "spain", "españa", "euskadi", "basque", "france", "germany",
        "uk", "united kingdom", "italy", "portugal", "ireland",
        "netherlands", "belgium", "poland", "austria", "switzerland",
        "scandinavia", "europe", "europa", "iberian", "atlantic",
    ]

    # If description mentions specific countries, check if any are European
    for country in european_countries:
        if country.lower() in description or country.lower() in title:
            return True

    # If no specific location mentioned, assume potentially visible
    # (conservative approach - only mark as visible if we can confirm)
    return False


def _is_planet_close_approach(title: str) -> bool:
    """Check if this is a planet close approach (not involving the Moon)."""
    has_close = "close approach" in title or "closest" in title
    has_moon = "moon" in title or "lunar" in title
    return has_close and not has_moon


def _is_comet_perihelion(text: str) -> bool:
    """Check if this is a comet perihelion passage."""
    has_comet = "comet" in text
    has_perihelion = any(w in text for w in ["perihelion", "closest approach to the sun"])
    return has_comet and has_perihelion


def _is_planet_conjunction(title: str) -> bool:
    """Check if this is a planet conjunction (not involving the Moon)."""
    has_conjunction = "conjunction" in title or "conjoin" in title
    has_moon = "moon" in title.lower() or "lunar" in title.lower()
    return has_conjunction and not has_moon


def _is_dwarf_planet_opposition(text: str) -> bool:
    """Check if this is a dwarf planet opposition."""
    # Check for known dwarf planets + opposition
    dwarf_planets = ["haumea", "makemake", "eris", "pluto", "ceres"]
    has_opposition = "opposition" in text

    for dp in dwarf_planets:
        if dp in text and has_opposition:
            return True

    # Generic opposition without moon involvement
    has_moon = "moon" in text or "lunar" in text
    if "opposition" in text and not has_moon:
        return True

    return False


def _has_moon_involvement(title: str) -> bool:
    """Check if the Moon is involved in this event."""
    moon_keywords = ["moon", "lunar"]
    return any(kw in title for kw in moon_keywords)

def _looks_like_generic_event(title: str) -> bool:
    """Check if title looks like a generic astronomical event (not moon-related)."""
    has_conjunction = "conjunction" in title or "conjoin" in title
    has_close_approach = ("close approach" in title or "closest" in title) and "moon" not in title
    
    planets = ["mercury", "venus", "mars", "jupiter", "saturn", "uranus", "neptune"]
    has_planet = any(p in title for p in planets)
    
    return (has_conjunction or has_close_approach) and has_planet


def get_priority_emoji(priority: int) -> str:
    """Get emoji representation for a priority level."""
    emojis = {
        1: "\U0001f534",   # Red circle
        2: "\U0001f7e0",   # Orange circle
        3: "\U0001f7e1",   # Yellow circle
        4: "\U0001f535",   # Blue circle
        5: "\u26aa",       # White circle
    }
    return emojis.get(priority, "?")


def get_visibility_emoji(level: int | None) -> str:
    """Get emoji representation for a visibility level."""
    if level is None:
        return "?"
    emojis = {
        1: "\U0001f440",   # Eye (naked eye)
        2: "\U0001f52d",   # Binoculars
        3: "\U0001f52c",   # Telescope small
        4: "\U0001f52c",   # Telescope medium
        5: "\U0001f52c",   # Telescope large
    }
    return emojis.get(level, "?")


def format_priority_label(priority: int) -> str:
    """Format priority as a display string."""
    labels = {
        1: "P1 Critical",
        2: "P2 High",
        3: "P3 Medium",
        4: "P4 Low",
        5: "P5 Minor",
    }
    return labels.get(priority, f"P{priority} Unknown")


def format_visibility_label(level: int | None) -> str:
    """Format visibility level as a display string."""
    if level is None:
        return "Unknown"

    descriptions = {
        1: "Naked eye",
        2: "Binoculars recommended",
        3: "Small telescope required (4 inch)",
        4: "Medium telescope required (8 inch)",
        5: "Large telescope required (12+ inch)",
    }
    return descriptions.get(level, f"Level {level}")
