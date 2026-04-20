"""Page scraper - extract thumbnail and visibility level from event pages."""

import re
import logging
from dataclasses import dataclass
from datetime import datetime

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


@dataclass
class PageData:
    """Structured data extracted from an event page."""
    thumbnail_url: str | None = None
    visibility_level: int | None = None
    visibility_text: str | None = None

    @property
    def is_visible(self) -> bool:
        return self.visibility_level is not None and self.thumbnail_url is not None


def fetch_event_page(url: str, timeout: int = 15) -> str | None:
    """Fetch the HTML content of an event page.

    Args:
        url: Full URL to the event page on in-the-sky.org
        timeout: HTTP request timeout in seconds

    Returns:
        Raw HTML string or None on failure
    """
    try:
        import urllib.request
        import urllib.error

        req = urllib.request.Request(url, headers={
            "User-Agent": "AstronomicalEvents/0.1 (bot)",
            "Accept": "text/html",
        })

        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status == 200:
                return response.read().decode("utf-8", errors="replace")
            else:
                logger.warning(f"HTTP {response.status} for {url}")
                return None

    except Exception as e:
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

    soup = BeautifulSoup(html, "lxml" if _has_lxml() else "html.parser")
    data = PageData()

    # Extract thumbnail from teaser image
    data.thumbnail_url = _extract_thumbnail(soup)

    # Extract visibility level from icon
    data.visibility_level, data.visibility_text = _extract_visibility(soup)

    return data


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


def _extract_visibility(soup) -> tuple[int | None, str | None]:
    """Extract visibility level from the page.

    Looks for level icon images (level1_icon.png through level5_icon.png).
    The alt text provides a human-readable description.

    Returns:
        Tuple of (visibility_level_int, alt_text)
    """
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
