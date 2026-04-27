"""RSS fetcher - download and parse in-the-sky.org RSS feed.

Enhanced with retry logic, exponential backoff, and circuit breaker
for resilient network operations (Phase 4).
"""

import logging
from datetime import datetime, timezone

try:
    import feedparser
except ImportError:
    raise ImportError("feedparser is required. Install with: pip install feedparser")

from event_parser import parse_rss_item
from retry import with_retry, CircuitBreaker, fetch_with_retry

logger = logging.getLogger(__name__)

# RSS fetch circuit breaker - open after 5 consecutive failures
rss_circuit_breaker = CircuitBreaker(
    failure_threshold=5,
    recovery_timeout=120.0,  # 2 min cooldown before half-open
)


def fetch_rss(url: str) -> feedparser.FeedParserDict | None:
    """Fetch RSS feed from in-the-sky.org with retry logic and circuit breaker.

    Uses exponential backoff (up to 3 retries) for transient failures.
    Circuit breaker opens after 5 consecutive failures, preventing
    resource exhaustion during extended outages.

    Args:
        url: Full RSS feed URL

    Returns:
        Parsed feed object or None on failure
    """
    logger.info(f"Fetching RSS from {url}")

    # Check circuit breaker state
    if rss_circuit_breaker.state == "open":
        logger.error("Circuit breaker OPEN for RSS fetch - skipping")
        return None

    @with_retry(
        max_retries=3,
        base_delay=2.0,
        max_delay=60.0,
        backoff_factor=2.0,
        retryable_exceptions=(Exception,),
    )
    def _do_fetch():
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
                rss_circuit_breaker.record_success()
                return feed
            else:
                logger.error(f"HTTP {response.status} fetching RSS")
                raise urllib.error.HTTPError(url, response.status, f"HTTP {response.status}", {}, None)

    try:
        feed = _do_fetch()
        if feed is not None:
            rss_circuit_breaker.record_success()
        return feed
    except Exception as e:
        rss_circuit_breaker.record_failure()
        logger.error(f"Failed to fetch RSS after retries: {e}")
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
        try:
            parsed = parse_rss_item(entry)
            if parsed and parsed.get("event_date"):
                items.append(parsed)
        except Exception as e:
            logger.warning(f"Failed to parse RSS item: {e}")

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
