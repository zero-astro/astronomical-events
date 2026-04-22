"""Mastodon client for posting astronomical event notifications.

Uses Mastodon.py library to post status updates to a Mastodon instance.
Credentials are loaded from config/mastodon.json in the workspace.
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def load_mastodon_config() -> dict:
    """Load Mastodon credentials from config file."""
    config_path = Path("/home/urtzai/.openclaw/workspace/config/mastodon.json")
    
    if not config_path.exists():
        logger.warning("Mastodon config not found at %s", config_path)
        return {}
    
    try:
        with open(config_path) as f:
            data = json.load(f)
        
        mastodon_config = data.get("mastodon")
        if not mastodon_config:
            logger.warning("No 'mastodon' key found in config file")
            return {}
        
        # Validate required fields
        required = ["instance_url", "access_token"]
        for field in required:
            if field not in mastodon_config:
                logger.error(f"Missing required Mastodon config field: {field}")
                return {}
        
        return mastodon_config
    
    except Exception as e:
        logger.error(f"Failed to load Mastodon config: {e}", exc_info=True)
        return {}


def create_mastodon_client(mastodon_config: dict):
    """Create and return a Mastodon client instance.
    
    Args:
        mastodon_config: Dict with instance_url, access_token (and optionally client_key/secret)
        
    Returns:
        Mastodon client instance or None if config is invalid
    """
    try:
        from mastodon import Mastodon
        
        instance_url = mastodon_config["instance_url"]
        access_token = mastodon_config["access_token"]
        
        # If client credentials are provided, register app first
        client_key = mastodon_config.get("client_key")
        client_secret = mastodon_config.get("client_secret")
        
        if client_key and client_secret:
            # Use existing credentials (for pre-registered apps)
            return Mastodon(
                access_token=access_token,
                api_base_url=instance_url
            )
        else:
            # No client credentials - just use access token directly
            return Mastodon(
                token=access_token,
                api_base_url=instance_url
            )
    
    except Exception as e:
        logger.error(f"Failed to create Mastodon client: {e}", exc_info=True)
        return None


def post_to_mastodon(message: str, mastodon_config: Optional[dict] = None) -> bool:
    """Post a message to Mastodon.
    
    Args:
        message: The status message to post (max 500 chars for Mastodon)
        mastodon_config: Mastodon config dict (loads from file if None)
        
    Returns:
        True if posted successfully, False otherwise
    """
    try:
        # Load config if not provided
        if mastodon_config is None:
            mastodon_config = load_mastodon_config()
        
        if not mastodon_config:
            logger.warning("No Mastodon configuration available")
            return False
        
        client = create_mastodon_client(mastodon_config)
        if client is None:
            return False
        
        # Truncate message to 500 chars (Mastodon limit)
        if len(message) > 500:
            message = message[:497] + "..."
        
        # Verify connection first
        try:
            client.account_verify_credentials()
        except Exception as e:
            logger.error(f"Mastodon authentication failed: {e}")
            return False
        
        # Post the status
        client.status_post(message)
        logger.info(f"Mastodon post successful: {message[:80]}...")
        return True
    
    except Exception as e:
        logger.error(f"Mastodon posting failed: {e}", exc_info=True)
        return False


# Event type emoji mapping
EVENT_TYPE_EMOJI = {
    "comet": "☄️",
    "meteor_shower": "🌠",
    "eclipse": "🌑",
    "nova": "💥",
    "occultation": "🌑",
    "planet_conjunction": "🪐",
    "moon_conjunction": "🌙",
    "opposition": "🔴",
    "perihelion": "☀️",
    "galaxy": "🌀",
}

# Planet name translations
PLANET_TRANSLATIONS = {
    "Mercury": "Merkurio",
    "Venus": "Artizarra",
    "Mars": "Marte",
    "Jupiter": "Jupiter",
    "Saturn": "Saturno",
    "Uranus": "Urano",
    "Neptune": "Neptuno",
}


def _translate_planets(title: str) -> str:
    """Replace English planet names with Basque in a string."""
    for eng, basq in PLANET_TRANSLATIONS.items():
        title = title.replace(eng, basq)
    return title


# Basque time labels
def _translate_time_label(time_label: str) -> str:
    """Translate English time label to Basque."""
    mapping = {
        "past": "Gaur",
        "today": "Gaur",
        "tomorrow": "Biharko",
        "1 days away": "Belerano",
        "2 days away": "2 egunetan",
        "3 days away": "3 egunetan",
        "4 days away": "4 egunetan",
        "5 days away": "5 egunetan",
    }
    return mapping.get(time_label, time_label)

# Basque event type descriptions
def _translate_event_type(event_type: str) -> str:
    """Translate English event type to Basque."""
    mapping = {
        "eclipse": "Eclipsea",
        "nova": "Supernoba/Novak",
        "meteor_shower": "Meteor-ekasea",
        "occultation": "Okultazioa",
        "comet": "Kometa",
        "planet_conjunction": "Planeta konjuntzioa",
        "moon_conjunction": "Ilargi konjuntzioa",
        "opposition": "Oposizioa",
        "perihelion": "Perihelioa",
    }
    return mapping.get(event_type, event_type)

# Basque visibility labels
def _translate_visibility(vis_label: str) -> str:
    """Translate English visibility label to Basque."""
    mapping = {
        "Naked eye": "Begi hutsez ikustekoa",
        "Binoculars": "Binokularrekin",
        "Small telescope": "Teleskopio txikiarekin",
        "Medium telescope": "Teleskopio ertainarekin",
        "Large telescope": "Teleskopio handiarekin",
    }
    return mapping.get(vis_label, vis_label)

# Basque priority emoji and label with description
def _get_priority_info(priority: int) -> tuple:
    """Return (emoji, level_label, description) for given priority."""
    mapping = {
        1: ("🔴", "L1", "Lehentasun oso altua"),
        2: ("🟠", "L2", "Lehentasun altua"),
        3: ("🟡", "L3", "Lehentasun baxua"),
        4: ("🔵", "L4", "Lehentasun oso baxua"),
        5: ("⚪", "L5", "Informazioa"),
    }
    return mapping.get(priority, ("⚪", f"L{priority}", "Ezezaguna"))

# Basque title translation helper - full sentence style
def _translate_title(title: str) -> str:
    """Translate English event titles to Basque in natural sentence style.
    
    Converts titles like 'Comet C/2025 R3 (PANSTARRS) passes perihelion'
    into 'C/2025 R3 (PANSTARRS) kometak perihelioa igaro du'.
    """
    # Full title translations
    full_translations = {
        "Close approach of the Moon and Jupiter": "Ilargiak eta Jupiterrek hurbilketa bat izan dute",
        "Conjunction of the Moon and Jupiter": "Ilargia eta Jupiterren konjuntzioa",
        "Lyrid meteor shower 2026": "Lyrid meteor-ekasearen gorena 2026",
        "π-Puppid meteor shower 2026": "π-Puppid meteor-ekasearen gorena 2026",
        "136108 Haumea at opposition": "136108 Haumea oposizioan dago",
        "Messier 101 is well placed": "M101 galaxia ondo kokatuta dago",
    }
    
    for eng, bas in full_translations.items():
        if eng.lower() in title.lower():
            return bas
    
    # Pattern-based translations for comet perihelion events
    import re
    
    # First, strip date prefix: "19 Apr 2026 (Today): " or similar
    cleaned = re.sub(r'^\d+\s+\w+\s+\d{4}\s+\([^)]*\):\s*', '', title)
    
    # Match: "Comet C/2025 R3 (PANSTARRS) passes perihelion"
    m = re.search(r'(?:Comet\s+)?(C/\d{4}\s+\w+\s*\([^)]*\))\s+passes\s+perihelion', cleaned, re.IGNORECASE)
    if m:
        comet_name = m.group(1).strip()
        return _translate_planets(f"{comet_name} kometak perihelioa igaro du")
    
    # Match: "Comet XXX passes perihelion" (no parentheses)
    m = re.search(r'(?:Comet\s+)?([^\s]+)\s+passes\s+perihelion', cleaned, re.IGNORECASE)
    if m:
        comet_name = m.group(1).strip()
        return _translate_planets(f"{comet_name} kometak perihelioa igaro du")
    
    # Match: "XXX at opposition"
    m = re.search(r'(.+)\s+at\s+opposition', title, re.IGNORECASE)
    if m:
        obj = m.group(1).strip()
        return _translate_planets(f"{obj} oposizioan dago")
    
    # Match: "XXX is well placed"
    m = re.search(r'(.+)\s+is\s+well\s+placed', title, re.IGNORECASE)
    if m:
        obj = m.group(1).strip()
        return _translate_planets(f"{obj} ondo kokatuta dago")
    
    # If no translation found, clean up the title (remove date prefix)
    result = cleaned
    
    # Translate any remaining English planet names to Basque
    result = _translate_planets(result)
    
    return result


def format_mastodon_status(event_data: dict) -> str:
    """Format event data into a Mastodon-friendly Basque status message.
    
    Format:
        📅 Gaur
        ☄️ C/2025 R3 (PANSTARRS) kometak perihelioa igaro du
        🔭 Begi hutsez ikustekoa
        🟡 L3 (Lehentasun baxua)
    
        🌍 https://in-the-sky.org/news.php?id=...
    
    Args:
        event_data: Dict with event information from notification
        
    Returns:
        Formatted string for Mastodon (max 500 chars)
    """
    priority = event_data.get("priority", 5)
    time_label = event_data.get("time_label", "unknown")
    title = event_data.get("title", "")
    event_type = event_data.get("event_type", "unknown")
    
    # Get Basque priority info
    emoji, level, desc = _get_priority_info(priority)
    
    # Translate time label to Basque (Gaur/Biharko/etc)
    basque_time = _translate_time_label(time_label)
    
    # Translate title to Basque
    basque_title = _translate_title(title)
    
    # Get event type emoji
    type_emoji = EVENT_TYPE_EMOJI.get(event_type, "🌟")
    
    # Build status message in exact user-specified format
    lines = []
    lines.append(f"📅 {basque_time}")
    lines.append(f"{type_emoji} {basque_title}")
    
    # Add visibility if available (translated to Basque)
    vis_label = event_data.get("visibility_label", "")
    if vis_label:
        basque_vis = _translate_visibility(vis_label)
        lines.append(f"🔭 {basque_vis}")
    
    # Add priority line
    lines.append(f"{emoji} {level} ({desc})")
    
    # Add URL if available
    url = event_data.get("event_page_url", "")
    if url:
        lines.append("")
        lines.append(f"🌍 {url}")
    
    return "\n".join(lines)


def format_mastodon_digest(events: list[dict]) -> str:
    """Format a digest of events into Basque for Mastodon.
    
    Compact format — one line per event to fit within 500 chars.
    
    Args:
        events: List of event dicts from notification
        
    Returns:
        Formatted digest string in Basque (max 500 chars)
    """
    lines = [f"📅 Egungo Laburpena ({len(events)} gertaera):"]
    
    for evt in events[:8]:  # Limit to first 8 for Mastodon
        event_status = format_mastodon_status(evt)
        # Extract just the title line from the formatted status
        for line in event_status.split("\n"):
            if any(line.startswith(e) for e in ["🌟", "☄️", "🌠", "🔴", "🌙", "🪐", "☀️", "🌀"]):
                lines.append(line)
    
    if len(events) > 8:
        lines.append(f"... eta {len(events) - 8} gertaera gehiago")
    
    return "\n".join(lines)
