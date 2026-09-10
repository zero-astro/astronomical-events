"""Mastodon client for posting astronomical event notifications.

Uses Mastodon.py library to post status updates to a Mastodon instance.
Credentials are loaded from config/mastodon.json in the workspace.
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def load_mastodon_config() -> dict:
    """Load Mastodon credentials from config file."""
    # Resolve workspace path: env var > relative to skill dir
    ws = os.environ.get("OPENCLAW_WORKSPACE_DIR", "")
    if not ws:
        # Skill is at ~/.hermes/skills/astronomical-events/src/
        skill_dir = Path(__file__).resolve().parent.parent
        # config/mastodon.json is in the skill root (same as src/)
        candidate = str(skill_dir / "config")
        if Path(candidate).exists():
            # ws IS the config directory
            config_path = Path(candidate) / "mastodon.json"
        else:
            # Fallback: try parent of skills directory
            ws = str(skill_dir.parent.parent)
            config_path = Path(ws) / "config" / "mastodon.json"
    else:
        config_path = Path(ws) / "config" / "mastodon.json"

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
    "occultation": "🌒",
    "planet_conjunction": "🪐",
    "moon_conjunction": "🌙",
    "opposition": "🔴",
    "perihelion": "☀️",
    "galaxy": "🌀",
}

# Title-based emoji mapping for events without a clear event_type
TITLE_EMOJI_MAP = {
    "full moon": "🌕",
    "new moon": "🌑",
    "first quarter": "🌓",
    "last quarter": "🌗",
    "apogee": "🌍",
    "aphelion": "☀️",
    "perigee": "🌍",
    "perihelion": "☀️",
    "mercury": "🪨",
    "venus": "✨",
    "mars": "🔴",
    "jupiter": "🟤",
    "saturn": "🪐",
    "uranus": "🔵",
    "neptune": "💙",
    "eris": "❄️",
    "pluto": "⚫",
    "antares": "❤️",
    "regulus": "💎",
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
        "η-Lyrid meteor shower 2026": "η-Lyrid meteor-ekasearen gorena 2026",
        "η-Aquariid meteor shower 2026": "η-Aquariideen meteoru-sakada 2026",
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


# Event type display names in Basque
EVENT_TYPE_DISPLAY = {
    "eclipse": "Eclipsea",
    "nova": "Supernoba/Novak",
    "meteor_shower": "Meteor-ekasea",
    "occultation": "Okultazioa",
    "comet": "Kometa",
    "planet_conjunction": "Konjuntzia planetarioa",
    "conjunction": "Konjuntzia planetarioa",
    "moon_conjunction": "Ilargi konjuntzioa",
    "opposition": "Oposizioa",
    "perihelion": "Perihelioa",
}

# Priority display in Basque
PRIORITY_DISPLAY = {
    1: "🔴 L1 — Lehentasun oso altua",
    2: "🟠 L2 — Lehentasun altua",
    3: "🟡 L3 — Lehentasun baxua",
    4: "🔵 L4 — Lehentasun oso baxua",
    5: "⚪ L5 — Informazioa",
}

# Visibility display in Basque (with level)
VISIBILITY_DISPLAY = {
    "Naked eye": "Begi hutsez ikustekoa",
    "Binoculars recommended": "Binokularrekin gomendatua",
    "Small telescope required (6+ inch)": "Teleskopio txikia behar da (6+ haztako)",
    "Medium telescope required (8-10 inch)": "Teleskopio ertaina behar da (8-10 haztako)",
    "Large telescope required (12+ inch)": "Teleskopio handia behar da (12+ haztako)",
}

VISIBILITY_LEVEL = {
    "Naked eye": 1,
    "Binoculars recommended": 2,
    "Small telescope required (6+ inch)": 3,
    "Medium telescope required (8-10 inch)": 4,
    "Large telescope required (12+ inch)": 5,
}


def _get_time_label_basque(time_label: str) -> str:
    """Get Basque time label with hours remaining."""
    if time_label == "today":
        return "Gaur — 9 ordu inguru geratzen dira"
    elif time_label == "past":
        return "Gaur"
    elif "days away" in time_label:
        days = time_label.split()[0]
        return f"{days} egunetan"
    return time_label


def format_mastodon_status(event_data: dict) -> str:
    """Format event data into a Mastodon-friendly Basque status message.

    Format (user-specified):
        Ilargiaren eta Artizarraren hurbilpen hurbila

        📅 2026ko irailaren 14a

        Ilargiak eta Artizarrak gaueko zeruan duten hurbiltasunak...

        🔭 Behatzeko:
        Mendebaldeko zeruan, 2026ko irailaren 14an ilundu eta...

        🔗 https://in-the-sky.org/news.php?id=...
        🤖 ZERO espazio digitaletik

    Args:
        event_data: Dict with event information from notification (prefers translated fields)

    Returns:
        Formatted string for Mastodon (max 500 chars)
    """
    import re

    # Prefer translated fields, fallback to English
    basque_title = event_data.get("translated_title") or _translate_title(event_data.get("title", ""))
    # Strip any remaining date prefixes from translated titles
    basque_title = re.sub(r'^\d{4}ko\s+\w+ren\s+\d+(?:\s*a)?(?:\s*\([^)]*\))?:\s*', '', basque_title)

    # Use translated rich_description if available, else fallback to English
    translated_rich_desc = event_data.get("translated_rich_description")
    if not translated_rich_desc:
        rich_en = event_data.get("rich_description") or event_data.get("rich_description_en", "")
        translated_rich_desc = _translate_title(rich_en) if rich_en else ""

    # Use translated viewing_info if available, else fallback to English
    translated_viewing = event_data.get("translated_viewing_info")
    if not translated_viewing:
        viewing_en = event_data.get("viewing_info") or event_data.get("viewing_info_en", "")
        translated_viewing = viewing_en  # fallback: use English as-is

    # Build base (title + date)
    base_lines = []
    base_lines.append(basque_title)
    base_lines.append("")
    base_lines.append(f"📅 {event_data.get('event_date', '').split('T')[0]}")
    base_text = "\n".join(base_lines)

    # URL and signature (footer — always preserved)
    url = event_data.get("event_page_url", "")
    footer_lines = []
    if url:
        footer_lines.append(f"🔗 {url}")
    footer_lines.append("🤖 ZERO espazio digitaletik")
    footer_text = "\n".join(footer_lines)

    # Fixed parts lengths
    viewing_header = "\n🔭 Behatzeko:\n"
    max_desc = 150

    # Calculate available space for description + viewing_info
    # Message structure: base_text + "\n" + desc + "\n" + viewing_header + viewing + "\n" + footer_text
    # Fixed chars: base_text + "\n" + "\n" + viewing_header + "\n" + footer_text
    fixed_len = len(base_text) + 1 + 1 + len(footer_text)  # +1 for blank line after desc, +1 for blank line after title

    # Reserve max 150 for description
    available_for_viewing = 500 - fixed_len - max_desc - len(viewing_header) - 3  # -3 for "…"

    # Build description (truncated to max 150)
    rich_desc = translated_rich_desc or ""
    if len(rich_desc) > max_desc:
        rich_desc = rich_desc[:max_desc - 3] + "…"

    # Build viewing_info (truncated to available space, only if it fits)
    viewing_info = translated_viewing if available_for_viewing > 50 and translated_viewing else ""
    if viewing_info:
        if len(viewing_info) > available_for_viewing - 3:
            viewing_info = viewing_info[:available_for_viewing - 3] + "…"

    # Assemble the message
    result = base_text + "\n" + rich_desc

    if viewing_info:
        result += "\n" + viewing_header + viewing_info
        result += "\n"  # blank line before footer

    result += "\n" + footer_text

    # Safety: if still over 500, remove viewing_info and shrink description
    while len(result) > 500:
        viewing_start = result.find('🔭 Behatzeko:')
        if viewing_start > 0:
            # Remove viewing_info
            newline_after_viewing = result.find("\n\n", viewing_start)
            if newline_after_viewing > 0:
                result = result[:viewing_start] + "\n" + footer_text
                continue

        # Shrink description
        max_content = 500 - len(base_text) - 1 - 1 - len(footer_text) - 3
        if max_content < 0:
            break
        result = base_text + "\n" + rich_desc[:max(max_content - 3, 0)] + "…"
        result += "\n" + footer_text
        break

    return result


def _get_event_emoji(event_data: dict) -> str:
    """Get the best emoji for an event based on type and title.

    Falls back to title-based matching if event_type is unknown or generic.
    """
    event_type = event_data.get("event_type", "")
    title = event_data.get("title", "").lower()

    # First try event_type mapping
    emoji = EVENT_TYPE_EMOJI.get(event_type)
    if emoji and event_type != "unknown":
        return emoji

    # Fall back to title-based matching
    for keyword, em in TITLE_EMOJI_MAP.items():
        if keyword in title:
            return em

    # Default
    return "🌟"


def _clean_title(title: str) -> str:
    """Clean up event title — remove date prefix and extra info.

    Args:
        title: Raw event title like '01 May 2026 (3 days away): Full Moon'

    Returns:
        Cleaned title like 'Full Moon'
    """
    import re
    # Remove date prefix: "01 May 2026 (3 days away): "
    cleaned = re.sub(r'^\d{1,2}\s+\w+\s+\d{4}\s*\([^)]*\)?:?\s*', '', title)
    return cleaned.strip()


def _translate_digest_title(title: str) -> str:
    """Translate a cleaned event title to Basque for digest display.

    Uses the same translation logic as format_mastodon_status but
    returns only the short translated title (no date prefix).
    """
    # Full translations first
    full_translations = {
        "full moon": "Ilargi betea",
        "new moon": "Ilargi berria",
        "first quarter": "Lehen laurdena",
        "last quarter": "Azken laurdena",
        "lunar occultation of antares": "Antaresen ilargi okultazioa",
        "the moon at apogee": "Ilargia apogeean",
        "the moon at aphelion": "Ilargia afelian",
        "conjunction of mercury and eris": "Merkurio eta Erisren konjuntzioa",
        "η-aquariid meteor shower 2026": "η-Aquariidak meteor-ekasea 2026",
    }

    lower = title.lower()
    for eng, bas in full_translations.items():
        if eng == lower:
            return bas

    # Pattern-based: conjunction of X and Y
    import re
    m = re.search(r'conjunction of (.+?) and (.+)', lower)
    if m:
        planet1 = _translate_planets(m.group(1).title())
        planet2 = _translate_planets(m.group(2).title())
        return f"{planet1} eta {planet2}ren konjuntzioa"

    # Pattern-based: lunar occultation of X
    m = re.search(r'lunar occultation of (.+)', lower)
    if m:
        star = _translate_planets(m.group(1).title())
        return f"{star}ren ilargi okultazioa"

    # Pattern-based: the moon at X
    m = re.search(r'the moon at (.+)', lower)
    if m:
        pos = _translate_planets(m.group(1).title())
        return f"Ilargia {pos}"

    # Pattern-based: meteor shower
    m = re.search(r'(.+) meteor shower', lower)
    if m:
        shower = m.group(1).strip()
        return f"{shower} meteor-ekasea"

    # Default: return cleaned title as-is (already cleaned by _clean_title)
    return title


def format_mastodon_digest(events: list[dict]) -> str:
    """Format a digest of events into Basque for Mastodon.

    Rich format — each event on its own line with proper emoji, short date,
    and optional rich description snippet (translated or original).
    Fits within 500 chars by limiting to ~6 events.

    Args:
        events: List of event dicts from notification

    Returns:
        Formatted digest string in Basque (max 500 chars)
    """
    lines = [f"📅 Astronomia Laburpena"]

    for evt in events[:6]:  # Limit to first 6 for Mastodon
        emoji = _get_event_emoji(evt)
        raw_title = _clean_title(evt.get("title", ""))
        time_label = evt.get("time_label", "")

        # Translate title to Basque
        basq_title = _translate_digest_title(raw_title)

        # Short date label
        if time_label == "past":
            date_str = "Gaur"
        elif "days away" in time_label:
            days = time_label.split()[0]
            date_str = f"+{days}d"
        else:
            date_str = time_label

        # Truncate title to ~35 chars
        if len(basq_title) > 35:
            basq_title = basq_title[:32] + "…"

        line = f"{emoji} {date_str}: {basq_title}"

        # Add rich description snippet (translated or original) — max 40 chars
        rich_desc = evt.get("rich_description", "")
        if rich_desc:
            snippet = rich_desc[:40]
            if len(rich_desc) > 40:
                snippet += "…"
            line += f" | 📝{snippet}"

        lines.append(line)

    result = "\n".join(lines)

    # Hard truncate to 500 if needed (Mastodon limit)
    if len(result) > 500:
        cutoff = result[:497]
        last_newline = cutoff.rfind("\n")
        if last_newline > 100:
            cutoff = result[:last_newline].rstrip()
        result = cutoff + "…"

    return result
