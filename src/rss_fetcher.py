"""RSS Feed Fetcher for in-the-sky.org astronomical events."""

import feedparser
import logging
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class RSSItem:
    """Represents a single item from the RSS feed."""
    news_id: str          # Extracted from URL path (e.g., 20260423_13_100)
    title: str
    link: str
    description: str      # Raw HTML
    pub_date: datetime
    guid: str

    @property
    def event_page_url(self) -> str:
        """Return the full URL to the event page."""
        return self.link


def extract_news_id(url: str) -> Optional[str]:
    """Extract the news ID from a URL.
    
    Examples:
        https://in-the-sky.org/news.php?id=20260423_13_100 -> 20260423_13_100
        https://in-the-sky.org/news.php?id=2026_19_CK25R030_100 -> 2026_19_CK25R030_100
    """
    if "id=" in url:
        return url.split("id=")[-1].split("&")[0]
    return None


def fetch_rss(url: str, timeout: int = 30) -> Optional[feedparser.FeedParserDict]:
    """Fetch and parse the RSS feed.
    
    Args:
        url: RSS feed URL
        timeout: HTTP request timeout in seconds
        
    Returns:
        Parsed feedparser object, or None on failure
    """
    try:
        logger.info(f"Fetching RSS from {url}")
        response = feedparser.parse(url)
        
        if response.bozo and not response.entries:
            logger.warning(f"RSS parse error: {response.bozo_exception}")
            return None
        
        if not response.entries:
            logger.warning("No entries found in RSS feed")
            return None
            
        logger.info(f"Fetched {len(response.entries)} entries from RSS feed")
        return response
        
    except Exception as e:
        logger.error(f"Failed to fetch RSS: {e}")
        return None


def parse_items(feed) -> list[RSSItem]:
    """Parse feedparser result into structured RSSItem objects.
    
    Args:
        feed: feedparser FeedParserDict object
        
    Returns:
        List of RSSItem objects
    """
    items = []
    for entry in feed.entries:
        news_id = extract_news_id(entry.get("link", ""))
        if not news_id:
            logger.warning(f"Could not extract news_id from {entry.get('link', 'unknown')}")
            continue
            
        # Parse pubDate
        pub_date = None
        if entry.get("published_parsed"):
            try:
                pub_date = datetime(*entry.published_parsed[:6])
            except Exception as e:
                logger.warning(f"Could not parse published date: {e}")
        
        item = RSSItem(
            news_id=news_id,
            title=entry.get("title", ""),
            link=entry.get("link", ""),
            description=entry.get("description", ""),
            pub_date=pub_date or datetime.now(),
            guid=entry.get("guid", entry.get("link", "")),
        )
        items.append(item)
    
    logger.info(f"Parsed {len(items)} valid RSS items")
    return items


def get_feed_metadata(feed) -> dict:
    """Extract metadata from the feed.
    
    Returns dict with channel info, last build date, etc.
    """
    if not feed.channel:
        return {}
    
    return {
        "title": feed.channel.get("title", ""),
        "link": feed.channel.get("link", ""),
        "description": feed.channel.get("description", ""),
        "language": feed.channel.get("language", ""),
        "last_build_date": feed.channel.get("lastBuildDate", ""),
    }
