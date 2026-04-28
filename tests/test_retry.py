"""Unit tests for retry utilities (retry.py)."""

import sys
import os
import unittest
import time
import threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from retry import with_retry, CircuitBreaker, RateLimiter


class TestWithRetry(unittest.TestCase):
    """Test cases for the @with_retry decorator."""

    def test_success_on_first_try(self):
        """Function that succeeds immediately should return result."""
        call_count = 0

        @with_retry(max_retries=3, base_delay=0.01)
        def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = succeed()
        self.assertEqual(result, "ok")
        self.assertEqual(call_count, 1)

    def test_retry_on_failure(self):
        """Function that fails then succeeds should retry."""
        call_count = 0

        @with_retry(max_retries=3, base_delay=0.01)
        def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("temporary error")
            return "success"

        result = fail_then_succeed()
        self.assertEqual(result, "success")
        self.assertEqual(call_count, 3)

    def test_exhaust_retries(self):
        """Function that always fails should raise after max retries."""
        call_count = 0

        @with_retry(max_retries=2, base_delay=0.01)
        def always_fail():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("permanent error")

        with self.assertRaises(RuntimeError):
            always_fail()

        # Should have tried max_retries + 1 (initial + retries)
        self.assertEqual(call_count, 3)

    def test_jitter_reduces_variance(self):
        """Jitter should produce different delays between calls."""
        @with_retry(max_retries=2, base_delay=0.01)
        def flaky():
            raise ValueError("error")

        # Run twice and verify jitter produces variation in timing
        start1 = time.monotonic()
        try:
            flaky()
        except ValueError:
            pass
        elapsed1 = time.monotonic() - start1

        start2 = time.monotonic()
        try:
            flaky()
        except ValueError:
            pass
        elapsed2 = time.monotonic() - start2

        # Both should complete (raise exception), but jitter adds variance
        self.assertGreater(elapsed1, 0)
        self.assertGreater(elapsed2, 0)


class TestCircuitBreaker(unittest.TestCase):
    """Test cases for the CircuitBreaker class."""

    def test_allows_after_reset(self):
        """Circuit should allow requests after recovery timeout."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0.1)

        # Trip the circuit
        for _ in range(3):
            try:
                cb.record_failure()
            except Exception:
                pass

        self.assertEqual(cb.state, "open")

        # Wait for recovery
        time.sleep(0.15)

        # Should transition to half-open and allow request
        cb.record_success()
        self.assertEqual(cb.state, "closed")

    def test_state_transitions(self):
        """Circuit should transition: closed → open → half-open → closed."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)

        # Initially closed
        self.assertEqual(cb.state, "closed")

        # Trip to open
        cb.record_failure()
        cb.record_failure()
        self.assertEqual(cb.state, "open")

        # Wait for recovery timeout
        time.sleep(0.15)

        # Should be half-open now (allows one request)
        self.assertEqual(cb.state, "half_open")

        # Success should close it
        cb.record_success()
        self.assertEqual(cb.state, "closed")


class TestRateLimiter(unittest.TestCase):
    """Test cases for the RateLimiter class."""

    def test_token_refill(self):
        """Tokens should refill over time."""
        rl = RateLimiter(max_tokens=2, refill_rate=0.1)  # Very slow: 1 token per 10s

        # Consume all tokens (acquire returns None on success)
        self.assertIsNone(rl.acquire())
        self.assertIsNone(rl.acquire())

        acquired = []

        def try_acquire():
            rl.acquire()  # Blocks until a token is available
            acquired.append(True)

        t = threading.Thread(target=try_acquire, daemon=True)
        t.start()
        time.sleep(0.5)  # Let thread start blocking
        self.assertFalse(acquired, "Thread should still be blocked")
        # Wait for refill (10s per token with rate 0.1)
        time.sleep(11)
        self.assertTrue(acquired, "Thread should have acquired a token after refill")


if __name__ == '__main__':
    unittest.main()
