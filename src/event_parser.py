"""Event parser - extract structured data from RSS items."""

import re
from datetime import datetime


MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4,
    "May": 5, "Jun": 6, "Jul": 7, "Aug": 8,
    "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def parse_event_date(title: str) -> datetime | None:
    """Parse event date from RSS title.

    Examples:
        "23 Apr 2026 (3 days away): 136108 Haumea at opposition"
        "22 Apr 2026 (1 day away): Lyrid meteor shower 2026"
        "19 Apr 2026 (Today): Comet C/2025 R3 (PANSTARRS) passes perihelion"

    Returns datetime or None if parsing fails.
    """
    match = re.match(r"(\d{1,2}) (\w+) (\d{4})", title)
    if not match:
        return None

    day, month_str, year = match.groups()
    month = MONTHS.get(month_str)
    if not month:
        return None

    try:
        return datetime(int(year), month, int(day))
    except ValueError:
        return None


def parse_event_name(title: str) -> str:
    """Extract the event name from RSS title.

    Strips the date prefix like "23 Apr 2026 (3 days away): ".

    Examples:
        "23 Apr 2026 (3 days away): 136108 Haumea at opposition" -> "136108 Haumea at opposition"
        "22 Apr 2026 (1 day away): Lyrid meteor shower 2026" -> "Lyrid meteor shower 2026"

    Returns the event name or the full title if no date prefix found.
    """
    # Pattern: DD Mon YYYY (...) : event_name
    match = re.match(r"\d{1,2} \w+ \d{4} \(.*?\):\s*(.*)", title)
    if match:
        return match.group(1).strip()
    return title.strip()


def strip_html(html_text: str) -> str:
    """Strip HTML tags and decode entities from text.

    Args:
        html_text: Raw HTML string from RSS description

    Returns:
        Clean plain text
    """
    # Remove HTML tags
    clean = re.sub(r"<[^>]+>", "", html_text)
    # Decode common HTML entities
    clean = (clean.replace("&amp;", "&")
                 .replace("&lt;", "<")
                 .replace("&gt;", ">")
                 .replace("&quot;", '"')
                 .replace("&#39;", "'"))
    # Collapse whitespace
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def extract_event_date_from_title(title: str) -> tuple[datetime | None, str]:
    """Parse both date and event name from title.

    Returns:
        Tuple of (event_datetime, event_name)
    """
    event_date = parse_event_date(title)
    event_name = parse_event_name(title)
    return event_date, event_name


def extract_countdown_days(title: str) -> int | None:
    """Extract countdown days from title.

    Examples:
        "23 Apr 2026 (3 days away): ..." -> 3
        "19 Apr 2026 (Today): ..." -> 0
        "19 Apr 2026 (Yesterday): ..." -> -1

    Returns None if no countdown found.
    """
    match = re.search(r"\((\d+) days?\s+(?:away|ago)\)", title)
    if match:
        return int(match.group(1))

    # Handle "Today" and "Yesterday"
    if "(Today)" in title:
        return 0
    if "(Yesterday)" in title:
        return -1

    return None


def parse_rss_item(item) -> dict | None:
    """Parse a single RSS feed item into structured data.

    Args:
        item: feedparser entry object

    Returns:
        Dict with parsed fields, or None if parsing fails
    """
    title = item.get("title", "")
    link = item.get("link", "")
    description = item.get("description", "")

    event_date, event_name = extract_event_date_from_title(title)
    countdown = extract_countdown_days(title)

    return {
        "news_id": _extract_news_id(link),
        "title": title,
        "event_name": event_name,
        "event_date": event_date,
        "countdown_days": countdown,
        "link": link,
        "description_raw": description,
        "description_text": strip_html(description),
        "pub_date": _parse_pub_date(item),
    }


def _extract_news_id(url: str) -> str | None:
    """Extract the news ID from a URL.

    Examples:
        https://in-the-sky.org/news.php?id=20260423_13_100 -> 20260423_13_100
        https://in-the-sky.org/news.php?id=2026_19_CK25R030_100 -> 2026_19_CK25R030_100
    """
    if "id=" in url:
        return url.split("id=")[-1].split("&")[0]
    return None


def _parse_pub_date(item) -> datetime | None:
    """Parse the published date from a feed item."""
    parsed = item.get("published_parsed") or item.get("updated_parsed")
    if not parsed:
        return None
    try:
        return datetime(*parsed[:6])
    except (ValueError, TypeError):
        return None
