"""Unit tests for cache module."""

import sys
import os
import unittest
import tempfile
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from cache import Cache


class TestCache(unittest.TestCase):
    """Test cases for the Cache class."""

    def setUp(self):
        """Set up test fixtures with a temporary directory."""
        self.temp_dir = tempfile.mkdtemp()
        self.cache = Cache(cache_dir=self.temp_dir)

    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_set_and_get(self):
        """Test basic set and get operations."""
        self.cache.set("test", "key1", "value1")
        result = self.cache.get("test", "key1")
        self.assertEqual(result, "value1")

    def test_get_nonexistent_key(self):
        """Test getting a key that doesn't exist."""
        result = self.cache.get("test", "nonexistent")
        self.assertIsNone(result)

    def test_ttl_expiration(self):
        """Test that cache entries expire after TTL."""
        # Set with 1 second TTL
        self.cache.set("test", "expiring_key", "value", ttl=1)
        
        # Should be available immediately
        result = self.cache.get("test", "expiring_key")
        self.assertEqual(result, "value")
        
        # Wait for expiration
        time.sleep(1.5)
        
        # Should be expired now
        result = self.cache.get("test", "expiring_key")
        self.assertIsNone(result)

    def test_cleanup_expired_entries(self):
        """Test cleanup of expired cache entries."""
        # Add some entries with different TTLs
        self.cache.set("test", "short_ttl", "value1", ttl=1)
        self.cache.set("test", "long_ttl", "value2", ttl=3600)
        
        # Wait for short TTL to expire
        time.sleep(1.5)
        
        # Cleanup should remove only the expired entry
        stats_before = self.cache.stats()
        self.cache.cleanup()
        stats_after = self.cache.stats()
        
        self.assertEqual(stats_before['total_entries'], 2)
        self.assertEqual(stats_after['total_entries'], 1)

    def test_stats(self):
        """Test cache statistics reporting."""
        # Add some entries
        self.cache.set("test", "key1", "value1")
        self.cache.set("test", "key2", "value2")
        
        stats = self.cache.stats()
        self.assertEqual(stats['total_entries'], 2)
        self.assertEqual(stats['expired_entries'], 0)


if __name__ == '__main__':
    unittest.main()
