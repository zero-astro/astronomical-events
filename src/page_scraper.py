"""Page scraper - extract thumbnail and visibility level from event pages.

Enhanced with rate limiting, circuit breaker, and retry logic for resilient
HTTP operations against in-the-sky.org (Phase 4).
Caches event page HTML content for configurable TTL periods.
"""

import json
import re
import logging
from dataclasses import dataclass, field
from datetime import datetime
from retry import with_retry

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    logger = logging.getLogger(__name__)
    logger.warning("beautifulsoup4 not installed. Install with: pip install beautifulsoup4 lxml")


logger = logging.getLogger(__name__)

# in-the-sky.org image URL patterns
IMAGE_BASE = "https://in-the-sky.org"
THUMBNAIL_STYLE = "hugeteaser"
LEVEL_ICON_PATTERN = re.compile(r"level(\d+)_icon\.png", re.IGNORECASE)

# Cache configuration for page content (1 hour TTL by default)
PAGE_CACHE_TTL = 3600

# Rate limiter: max 2 requests/sec to avoid hammering in-the-sky.org
_page_rate_limiter = None


def _get_rate_limiter():
    """Lazy initialization of rate limiter."""
    global _page_rate_limiter
    if _page_rate_limiter is None:
        from retry import RateLimiter
        _page_rate_limiter = RateLimiter(max_tokens=3, refill_rate=2.0)  # burst 3, 2/sec sustained
    return _page_rate_limiter


# Circuit breaker for page scraping (separate from RSS)
_page_circuit_breaker = None


def _get_circuit_breaker():
    """Lazy initialization of circuit breaker."""
    global _page_circuit_breaker
    if _page_circuit_breaker is None:
        from retry import CircuitBreaker
        _page_circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60.0,  # 1 min cooldown
        )
    return _page_circuit_breaker


@dataclass
class PageData:
    """Structured data extracted from an event page."""
    thumbnail_url: str | None = None
    visibility_level: int | None = None
    visibility_text: str | None = None
    rich_description_en: str | None = None
    viewing_info_en: str | None = None
    event_details_json: str | None = None

    @property
    def is_visible(self) -> bool:
        return self.visibility_level is not None and self.thumbnail_url is not None


def fetch_event_page(url: str, timeout: int = 15, use_cache: bool = True) -> str | None:
    """Fetch the HTML content of an event page with caching, rate limiting, and retry.

    Args:
        url: Full URL to the event page on in-the-sky.org
        timeout: HTTP request timeout in seconds
        use_cache: Whether to use cached data if available (default: True)

    Returns:
        Raw HTML string or None on failure
    """
    # Check circuit breaker
    cb = _get_circuit_breaker()
    if cb.state == "open":
        logger.warning("Circuit breaker OPEN for page fetch - using cache only")
        use_cache = True

    # Try cache first
    if use_cache:
        from cache import get_cache
        cache = get_cache()
        cached = cache.get("page", url)
        if cached:
            logger.debug(f"Cache hit for page: {url}")
            return cached

    # Fetch from network with rate limiting and retry
    html = _fetch_page(url, timeout)

    # Cache the result
    if html and use_cache:
        from cache import get_cache
        cache = get_cache()
        cache.set("page", url, html, ttl=PAGE_CACHE_TTL)
        logger.debug(f"Cached page: {url} (ttl={PAGE_CACHE_TTL}s)")

    return html


def _fetch_page(url: str, timeout: int) -> str | None:
    """Fetch HTML from network with rate limiting and retry logic."""
    import urllib.request
    import urllib.error

    # Acquire rate limiter token
    rl = _get_rate_limiter()
    rl.acquire()

    cb = _get_circuit_breaker()

    @with_retry(
        max_retries=2,  # Lighter retry for page scraping (less critical)
        base_delay=1.5,
        max_delay=30.0,
        backoff_factor=2.0,
        retryable_exceptions=(urllib.error.URLError, urllib.error.HTTPError, OSError),
    )
    def _do_fetch():
        req = urllib.request.Request(url, headers={
            "User-Agent": "AstronomicalEvents/0.1 (bot)",
            "Accept": "text/html",
        })

        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status == 200:
                cb.record_success()
                return response.read().decode("utf-8", errors="replace")
            else:
                logger.warning(f"HTTP {response.status} for {url}")
                raise urllib.error.HTTPError(url, response.status, f"HTTP {response.status}", {}, None)

    try:
        return _do_fetch()
    except Exception as e:
        cb.record_failure()
        logger.error(f"Failed to fetch page {url}: {e}")
        return None


def parse_page(html: str) -> PageData | None:
    """Parse event page HTML to extract thumbnail and visibility level.

    Args:
        html: Raw HTML content of the event page

    Returns:
        PageData with extracted fields, or None if parsing fails
    """
    if not HAS_BS4:
        logger.warning("beautifulsoup4 required for page scraping")
        return None

    try:
        soup = BeautifulSoup(html, "lxml" if _has_lxml() else "html.parser")
        data = PageData()

        # Extract thumbnail from teaser image
        data.thumbnail_url = _extract_thumbnail(soup)

        # Extract visibility level from icon
        data.visibility_level, data.visibility_text = _extract_visibility(soup)

        # Extract rich description and viewing info (Phase 6)
        data.rich_description_en = _extract_rich_description(soup)
        data.viewing_info_en = _extract_viewing_info(soup)

        # Extract structured event details as JSON (Phase 6)
        try:
            data.event_details_json = json.dumps(_extract_event_details(soup), ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Failed to extract event details: {e}")
            data.event_details_json = ""

        return data
    except Exception as e:
        logger.error(f"Failed to parse page HTML: {e}")
        return None


def _has_lxml() -> bool:
    """Check if lxml parser is available."""
    try:
        import lxml  # noqa: F401
        return True
    except ImportError:
        return False


def _extract_thumbnail(soup) -> str | None:
    """Extract the main teaser/thumbnail image URL from the page.

    Looks for images with style=hugeteaser or in the teaser section.
    """
    try:
        # Try to find the large teaser image
        teaser = soup.find("img", src=re.compile(r"style=.*?teaser"))
        if teaser and teaser.get("src"):
            return _resolve_url(teaser["src"])

        # Fallback: look for any image in the main content area
        content = soup.find("div", class_=re.compile(r"news|content|article", re.I))
        if content:
            img = content.find("img")
            if img and img.get("src"):
                return _resolve_url(img["src"])

        # Last resort: first image on page that's not a level icon
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if "level" not in src.lower() and "icon" not in src.lower():
                return _resolve_url(src)

        return None
    except Exception as e:
        logger.error(f"Failed to extract thumbnail: {e}")
        return None


def _extract_visibility(soup) -> tuple[int | None, str | None]:
    """Extract visibility level from the page.

    Looks for level icon images (level1_icon.png through level5_icon.png).
    The alt text provides a human-readable description.

    Returns:
        Tuple of (visibility_level_int, alt_text)
    """
    try:
        # Find all images and look for level icons
        for img in soup.find_all("img"):
            src = img.get("src", "")
            match = LEVEL_ICON_PATTERN.search(src)
            if match:
                level = int(match.group(1))
                # Clamp to valid range 1-5 (in-the-sky.org may return higher values)
                if level < 1:
                    level = 1
                elif level > 5:
                    level = 5
                alt_text = img.get("alt", "").strip() or None
                return level, alt_text

        # Fallback: look for text mentioning visibility level
        body_text = soup.get_text().lower()
        for lvl in range(5, 0, -1):
            if f"level {lvl}" in body_text:
                return lvl, None

        return None, None
    except Exception as e:
        logger.error(f"Failed to extract visibility level: {e}")
        return None, None


def _extract_rich_description(soup) -> str:
    """Extract a rich English description of the event from the page.

    Targets div.newsbody which is the main article body on in-the-sky.org pages.
    Filters out author lines, feed references, and other metadata noise.
    Returns cleaned up text suitable for translation and display.
    """
    try:
        # Primary strategy: target div.newsbody (the actual article content)
        newsbody = soup.find("div", class_="newsbody")

        if not newsbody:
            return ""

        body_text = newsbody.get_text()
        lines = [line.strip() for line in body_text.split("\n") if line.strip()]

        texts = []
        for line in lines:
            lower = line.lower()

            # Skip author/credit lines
            if any(skip in lower for skip in ["by", "editor", "contributed by"]):
                continue
            # Skip feed reference lines
            if re.search(r"^from\s+(the\s+)?feed", lower):
                continue
            # Skip table/chart reference lines (not actual content)
            table_ref_patterns = [
                r"^(the\s+)?(table|chart|diagram)\s+(below|above|shown)",
                r"\bfollows:\s*$",  # "are as follows:" type lines (at end)
            ]
            skip_line = False
            for pat in table_ref_patterns:
                if re.search(pat, lower, re.I):
                    skip_line = True
                    break

            if not skip_line:
                texts.append(line)

        return " ".join(texts[:8]).strip() if texts else ""
    except Exception as e:
        logger.error(f"Failed to extract rich description: {e}")
        return ""


def _extract_viewing_info(soup) -> str:
    """Extract viewing information (best times, directions, conditions) from the page.

    Targets div.newsbody and extracts lines mentioning visibility parameters.
    Returns structured text suitable for translation.
    Filters out table data rows and general article content.
    """
    try:
        newsbody = soup.find("div", class_="newsbody")

        if not newsbody:
            return ""

        body_text = newsbody.get_text()
        lines = [line.strip() for line in body_text.split("\n") if line.strip()]

        viewing_lines = []
        # Use word-boundary matching to avoid false positives like "rise" in "comprise"
        viewing_keywords = [
            r"\bbest\b", r"\bvisible\b", r"\bdirection\b", r"\bhorizon\b",
            r"\bmagnitude\b", r"\bbrightness\b", r"\billumination\b",
            r"\bdistance\b", r"\bseparation\b", r"\baltitude\b",
            r"\bazimuth\b", r"\bconstellation\b", r"\brise\b", r"\bset\b",
            r"\btransit\b", r"\bphase\b", r"\bangular\b",
            r"\bobservable\b", r"\bdawn\b", r"\bdusk\b",
            r"\btwilight\b", r"\bnight\b",
        ]

        # Patterns to skip: table data rows (date + constellation + status)
        table_row_pattern = re.compile(r"^\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}")

        for line in lines:
            lower = line.lower()

            # Skip navigation-like content and metadata
            if any(skip in lower for skip in ["rising & setting", "list of the constellations",
                                              "sunrise & sunset", "ephemeris"]):
                continue
            # Skip short noise lines
            if len(line) < 15:
                continue
            # Skip table data rows (date + constellation + status, e.g. "29 Mar 2026PegasusNot observable")
            if table_row_pattern.match(line):
                continue
            # Skip general article content about comets in general
            if re.search(r"^comets are\s+", lower) or re.search(r"^(in consequence|based on)", lower):
                continue
            # Skip table/chart reference lines (not actual viewing info)
            if re.search(r"(table below|chart below|available here|events that comprise|detailed table)", lower):
                continue
            # Skip continuation lines starting with lowercase (article body, not viewing data)
            if line[0].islower() and len(line) > 40:
                continue
            # Must contain at least one viewing keyword (word-boundary match)
            if not any(re.search(pat, lower) for pat in viewing_keywords):
                continue

            viewing_lines.append(line)

        return "; ".join(viewing_lines[:5]).strip() if viewing_lines else ""
    except Exception as e:
        logger.error(f"Failed to extract viewing info: {e}")
        return ""


def _resolve_url(url: str) -> str:
    """Resolve a relative URL to an absolute URL."""
    if url.startswith("http"):
        return url
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return IMAGE_BASE + url
    # Relative path - assume same domain
    base = "https://in-the-sky.org"
    if url.startswith("image.php") or url.startswith("imagedump/"):
        return f"{base}/{url}"
    return f"{base}/{url}"


def _extract_event_details(soup) -> dict:
    """Extract structured event details from the page as a JSON-serializable dict.

    Extracts:
    - Event date/time (from time table)
    - Object information (RA, Dec, constellation, magnitude, angular size)
    - Visibility times by country/region
    - Planet rise/culminate/set times if present

    Returns a dict suitable for JSON serialization.
    """
    details = {}

    # Extract event date/time table (usually the first or second table)
    tables = soup.find_all("table")
    for i, table in enumerate(tables):
        rows = table.find_all("tr")
        if not rows:
            continue

        headers = [h.get_text(strip=True) for h in rows[0].find_all(["th", "td"])]

        # Time table: has columns like "from", "to" or date + time info
        if any("time" in h.lower() or "from" in h.lower() or "to" in h.lower()
               for h in headers):
            times = {}
            for row in rows[1:]:
                cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
                if len(cells) >= 2:
                    label = cells[0].strip()
                    time_val = cells[-1].strip() if len(cells) > 1 else ""
                    times[label] = time_val
            if times:
                details["event_times"] = times

        # Object info table: has columns like "Object", "Right Ascension", etc.
        elif any("object" in h.lower() or "right ascension" in h.lower()
                 for h in headers):
            obj_info = {}
            for row in rows[1:]:
                cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
                if len(cells) >= 2:
                    obj_name = cells[0].strip()
                    # Build dict of properties
                    props = {}
                    for j, header in enumerate(headers[1:], start=1):
                        if j < len(cells):
                            props[header] = cells[j]
                    obj_info[obj_name] = props
            if obj_info:
                details["objects"] = obj_info

        # Country visibility table: has "Country", "Time span(UTC)"
        elif any("country" in h.lower() or "time span" in h.lower()
                 for h in headers):
            visibility = []
            for row in rows[1:]:
                cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
                if len(cells) >= 2:
                    visibility.append({"country": cells[0], "time_span_utc": cells[-1]})
            if visibility:
                details["visibility_by_country"] = visibility[:50]  # Limit to 50

        # Planet rise/culminate/set table
        elif any("rise" in h.lower() or "culm" in h.lower()
                 for h in headers):
            planets = []
            for row in rows[1:]:
                cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
                if len(cells) >= 4:
                    planet_name = cells[0].strip()
                    planets.append({
                        "name": planet_name,
                        "rise": cells[1],
                        "culminate": cells[2],
                        "set": cells[3]
                    })
            if planets:
                details["planets"] = planets

    return details


async def fetch_event_page_async(url: str, timeout: int = 15) -> str | None:
    """Async version of fetch_event_page (for Phase 4)."""
    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=timeout,
                                   headers={"User-Agent": "AstronomicalEvents/0.1"}) as resp:
                if resp.status == 200:
                    return await resp.text()
                return None
    except Exception as e:
        logger.error(f"Async fetch failed for {url}: {e}")
        return None


async def parse_page_async(url: str) -> PageData | None:
    """Fetch and parse an event page asynchronously."""
    html = await fetch_event_page_async(url)
    if not html:
        return None
    return parse_page(html)
