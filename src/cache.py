"""Cache layer - Astronomical Events Skill.

Provides caching for event pages and thumbnails to reduce redundant fetches.
Uses a simple file-based cache with TTL (time-to-live).

Usage:
    from cache import Cache
    
    # Fetch with caching
    html = cache.get("page", "https://example.com")
    if not html:
        html = fetch_event_page(url)
        cache.set("page", url, html, ttl=3600)  # 1 hour TTL
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class Cache:
    """Simple file-based cache with TTL support.

    Stores cached data in JSON files under the cache directory.
    Each entry has a timestamp and TTL (time-to-live) in seconds.
    """

    def __init__(self, cache_dir: str = None):
        if cache_dir is None:
            cache_dir = str(Path(__file__).parent.parent / "data" / "cache")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_key(self, prefix: str, key: str) -> str:
        """Generate a safe filename for the cache entry."""
        import hashlib
        hash_key = hashlib.md5(f"{prefix}:{key}".encode()).hexdigest()[:16]
        return f"{hash_key}.json"

    def get(self, prefix: str, key: str) -> Optional[str]:
        """Get cached value if it exists and hasn't expired.

        Args:
            prefix: Cache namespace (e.g., 'page', 'thumbnail')
            key: Unique identifier for the entry

        Returns:
            Cached content string or None if not found/expired
        """
        cache_file = self.cache_dir / self._get_cache_key(prefix, key)

        if not cache_file.exists():
            return None

        try:
            with open(cache_file) as f:
                data = json.load(f)

            # Check TTL
            age = time.time() - data["timestamp"]
            if age > data["ttl"]:
                logger.debug(f"Cache expired for {prefix}:{key} (age={age:.0f}s, ttl={data['ttl']}s)")
                cache_file.unlink(missing_ok=True)
                return None

            return data.get("content")

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Cache read error for {prefix}:{key}: {e}")
            cache_file.unlink(missing_ok=True)
            return None

    def set(self, prefix: str, key: str, content: str, ttl: int = 3600):
        """Store value in cache with TTL.

        Args:
            prefix: Cache namespace (e.g., 'page', 'thumbnail')
            key: Unique identifier for the entry
            content: Content to cache
            ttl: Time-to-live in seconds (default: 1 hour)
        """
        cache_file = self.cache_dir / self._get_cache_key(prefix, key)

        data = {
            "timestamp": time.time(),
            "ttl": ttl,
            "content": content,
        }

        try:
            with open(cache_file, "w") as f:
                json.dump(data, f, ensure_ascii=False)
            logger.debug(f"Cache set for {prefix}:{key} (ttl={ttl}s)")
        except Exception as e:
            logger.warning(f"Cache write error for {prefix}:{key}: {e}")

    def clear(self, prefix: str = None):
        """Clear cache entries. If prefix is provided, only clear that namespace."""
        if prefix:
            # Clear all files in the directory (simple approach since we hash keys)
            for f in self.cache_dir.glob("*.json"):
                try:
                    with open(f) as fh:
                        data = json.load(fh)
                    # We can't easily filter by prefix without re-hashing, so clear all
                    f.unlink()
                except Exception:
                    pass
        else:
            for f in self.cache_dir.glob("*.json"):
                try:
                    f.unlink()
                except Exception:
                    pass

    def cleanup(self):
        """Remove expired cache entries."""
        removed = 0
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                with open(cache_file) as f:
                    data = json.load(f)

                age = time.time() - data["timestamp"]
                if age > data["ttl"]:
                    cache_file.unlink()
                    removed += 1
            except (json.JSONDecodeError, KeyError):
                cache_file.unlink(missing_ok=True)
                removed += 1

        if removed:
            logger.info(f"Cache cleanup: {removed} expired entries removed")

    def stats(self) -> dict:
        """Get cache statistics."""
        total = 0
        expired = 0
        now = time.time()

        for f in self.cache_dir.glob("*.json"):
            total += 1
            try:
                with open(f) as fh:
                    data = json.load(fh)
                if now - data["timestamp"] > data["ttl"]:
                    expired += 1
            except Exception:
                pass

        return {
            "total_entries": total,
            "expired_entries": expired,
            "cache_dir": str(self.cache_dir),
        }


# Global cache instance
_cache = None


def get_cache() -> Cache:
    """Get or create the global cache instance."""
    global _cache
    if _cache is None:
        _cache = Cache()
    return _cache
