"""Retry & error handling utilities - Astronomical Events Skill.

Provides exponential backoff, jitter, and circuit breaker patterns
for resilient HTTP requests and database operations.

Usage:
    from retry import with_retry, CircuitBreaker
    
    @with_retry(max_retries=3, base_delay=1.0)
    def fetch(url): ...
"""

import logging
import random
import time
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ─── Exponential Backoff with Jitter ────────────────────────────────────────

def _calculate_delay(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
) -> float:
    """Calculate delay with exponential backoff and jitter.

    Uses "full jitter" strategy (AWS style):
        delay = min(max_delay, random.uniform(0, min(base_delay * 2^attempt, max_delay)))

    This prevents thundering herd when multiple retries happen simultaneously.
    """
    raw_delay = base_delay * (backoff_factor ** attempt)
    capped_delay = min(raw_delay, max_delay)
    jitter = random.uniform(0, capped_delay)
    return round(jitter, 2)


def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: tuple = (Exception,),
    on_retry: Optional[Callable] = None,
):
    """Decorator that retries a function with exponential backoff and jitter.

    Args:
        max_retries: Maximum number of retry attempts (not counting initial call)
        base_delay: Initial delay in seconds before first retry
        max_delay: Maximum delay cap in seconds
        backoff_factor: Multiplier for each retry step
        retryable_exceptions: Tuple of exception types that trigger a retry
        on_retry: Optional callback(retry_num, delay, exc) called before each retry

    Returns:
        Decorated function with retry logic
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e

                    if attempt >= max_retries:
                        logger.error(
                            f"{func.__name__} failed after {max_retries + 1} attempts: {e}"
                        )
                        raise

                    delay = _calculate_delay(attempt, base_delay, max_delay, backoff_factor)
                    logger.warning(
                        f"{func.__name__} attempt {attempt + 1}/{max_retries + 1} failed: {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )

                    if on_retry:
                        on_retry(attempt, delay, e)

                    time.sleep(delay)

            # Should not reach here, but just in case
            raise last_exception  # type: ignore[misc]

        return wrapper
    return decorator


# ─── Circuit Breaker ────────────────────────────────────────────────────────

class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open (too many failures)."""
    pass


class CircuitBreaker:
    """Circuit breaker for external service calls.

    States:
        CLOSED   — Normal operation, requests pass through
        OPEN     — Too many failures, requests fail immediately
        HALF_OPEN— Testing recovery after cooldown period

    Args:
        failure_threshold: Number of consecutive failures before opening circuit
        recovery_timeout: Seconds to wait before transitioning to half-open
        expected_exception: Exception type that counts as a failure
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        expected_exception: type = Exception,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception

        self._failure_count = 0
        self._last_failure_time: Optional[datetime] = None
        self._state: str = "closed"  # closed | open | half_open

    @property
    def state(self) -> str:
        """Return current circuit breaker state."""
        if self._state == "open":
            elapsed = (datetime.now() - self._last_failure_time).total_seconds()
            if elapsed >= self.recovery_timeout:
                logger.info("Circuit breaker transitioning to half-open")
                self._state = "half_open"
        return self._state

    def record_success(self) -> None:
        """Record a successful call."""
        if self.state == "half_open":
            logger.info("Circuit breaker closed (recovery confirmed)")
        self._failure_count = 0
        self._last_failure_time = None
        self._state = "closed"

    def record_failure(self) -> None:
        """Record a failed call."""
        self._failure_count += 1
        self._last_failure_time = datetime.now()

        if self._failure_count >= self.failure_threshold:
            logger.warning(
                f"Circuit breaker opened after {self._failure_count} consecutive failures. "
                f"Recovery timeout: {self.recovery_timeout}s"
            )
            self._state = "open"

    def __call__(self, func: Callable) -> Callable:
        """Decorator to apply circuit breaker to a function."""
        @wraps(func)
        def wrapper(*args, **kwargs):
            if self.state == "open":
                raise CircuitBreakerError(
                    f"Circuit is OPEN (failures={self._failure_count}, "
                    f"timeout={self.recovery_timeout}s). "
                    f"Will retry after recovery period."
                )

            try:
                result = func(*args, **kwargs)
                self.record_success()
                return result
            except self.expected_exception as e:
                self.record_failure()
                raise

        return wrapper


# ─── Rate Limiter ───────────────────────────────────────────────────────────

class RateLimiter:
    """Token bucket rate limiter for HTTP requests.

    Prevents hammering external services by enforcing a maximum request rate.

    Args:
        max_tokens: Maximum burst size (default 3)
        refill_rate: Tokens per second (default 1 = 1 req/sec)
    """

    def __init__(self, max_tokens: int = 3, refill_rate: float = 1.0):
        self.max_tokens = max_tokens
        self.refill_rate = refill_rate
        self._tokens = float(max_tokens)
        self._last_refill = datetime.now()

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = datetime.now()
        elapsed = (now - self._last_refill).total_seconds()
        self._tokens = min(
            self.max_tokens,
            self._tokens + elapsed * self.refill_rate,
        )
        self._last_refill = now

    def acquire(self) -> None:
        """Acquire a token, blocking if necessary."""
        while True:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            # Wait for next token
            wait_time = (1.0 - self._tokens) / self.refill_rate
            logger.debug(f"Rate limiter: waiting {wait_time:.1f}s")
            time.sleep(wait_time)


# ─── Retryable HTTP Fetcher ────────────────────────────────────────────────

def fetch_with_retry(
    url: str,
    timeout: int = 30,
    max_retries: int = 3,
    base_delay: float = 1.5,
    headers: Optional[dict] = None,
) -> Optional[str]:
    """Fetch a URL with retry logic and exponential backoff.

    Args:
        url: URL to fetch
        timeout: Request timeout in seconds
        max_retries: Maximum number of retries
        base_delay: Base delay for backoff
        headers: Custom HTTP headers

    Returns:
        Response text or None on permanent failure
    """
    import urllib.request
    import urllib.error

    default_headers = {
        "User-Agent": "AstronomicalEvents/0.1 (bot)",
        "Accept": "application/rss+xml, application/xml, text/xml",
    }
    if headers:
        default_headers.update(headers)

    def _do_fetch():
        req = urllib.request.Request(url, headers=default_headers)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status == 200:
                return response.read().decode("utf-8", errors="replace")
            else:
                raise urllib.error.HTTPError(
                    url, response.status, f"HTTP {response.status}",
                    {}, None
                )

    try:
        return with_retry(
            max_retries=max_retries,
            base_delay=base_delay,
            retryable_exceptions=(urllib.error.URLError, urllib.error.HTTPError, OSError),
        )(_do_fetch)()
    except Exception as e:
        logger.error(f"fetch_with_retry({url}) failed after retries: {e}")
        return None
