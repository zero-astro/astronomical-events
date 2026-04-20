"""RSS fetcher - download and parse in-the-sky.org RSS feed."""

import logging
from datetime import datetime, timezone

try:
    import feedparser
except ImportError:
    raise ImportError("feedparser is required. Install with: pip install feedparser")

from event_parser import parse_rss_item

logger = logging.getLogger(__name__)


def fetch_rss(url: str) -> feedparser.FeedParserDict | None:
    """Fetch RSS feed from in-the-sky.org.

    Args:
        url: Full RSS feed URL

    Returns:
        Parsed feed object or None on failure
    """
    logger.info(f"Fetching RSS from {url}")

    try:
        import urllib.request
        import urllib.error

        req = urllib.request.Request(url, headers={
            "User-Agent": "AstronomicalEvents/0.1 (bot)",
            "Accept": "application/rss+xml, application/xml, text/xml",
        })

        with urllib.request.urlopen(req, timeout=30) as response:
            if response.status == 200:
                data = response.read()
                feed = feedparser.parse(data)

                if not feed.entries:
                    logger.warning("RSS feed has no entries")
                    return None

                logger.info(f"Fetched {len(feed.entries)} entries from RSS feed")
                return feed
            else:
                logger.error(f"HTTP {response.status} fetching RSS")
                return None

    except Exception as e:
        logger.error(f"Failed to fetch RSS: {e}")
        return None


def parse_items(feed) -> list[dict]:
    """Parse all items from an RSS feed into structured data.

    Args:
        feed: feedparser FeedParserDict object

    Returns:
        List of parsed item dicts
    """
    if not feed or not hasattr(feed, "entries"):
        return []

    items = []
    for entry in feed.entries:
        parsed = parse_rss_item(entry)
        if parsed and parsed.get("event_date"):
            items.append(parsed)

    logger.info(f"Parsed {len(items)} valid RSS items")
    return items


def get_feed_metadata(feed) -> dict:
    """Extract metadata from the feed.

    Args:
        feed: feedparser FeedParserDict object

    Returns:
        Dict with title, last_build_date, etc.
    """
    if not feed or not hasattr(feed, "feed"):
        return {}

    meta = {
        "title": getattr(feed.feed, "title", ""),
        "subtitle": getattr(feed.feed, "subtitle", ""),
        "link": getattr(feed.feed, "href", ""),
        "last_build_date": getattr(feed.feed, "updated", ""),
    }
    return meta


def fetch_and_parse(url: str) -> tuple[list[dict], dict]:
    """Fetch RSS and parse all items in one call.

    Args:
        url: Full RSS feed URL

    Returns:
        Tuple of (items_list, metadata_dict)
    """
    feed = fetch_rss(url)
    if not feed:
        return [], {}

    items = parse_items(feed)
    meta = get_feed_metadata(feed)
    return items, meta
