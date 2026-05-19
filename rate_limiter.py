"""
rate_limiter.py — Per-domain rate limiting and request randomization.
Keeps scrapers polite and reduces bot-detection risk.
"""
from __future__ import annotations
import asyncio
import random
import time
from collections import defaultdict
from typing import Dict


class RateLimiter:
    """
    Per-domain async rate limiter.
    Ensures minimum gap between requests to the same domain.
    """

    def __init__(self):
        self._last_request: Dict[str, float] = defaultdict(float)
        self._locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def wait(self, domain: str, min_gap: float = 3.0, jitter: float = 2.0):
        """Wait until it's safe to make a request to `domain`."""
        async with self._locks[domain]:
            now = time.monotonic()
            elapsed = now - self._last_request[domain]
            gap = min_gap + random.uniform(0, jitter)
            if elapsed < gap:
                await asyncio.sleep(gap - elapsed)
            self._last_request[domain] = time.monotonic()


# Global singleton
rate_limiter = RateLimiter()


# ── Domain-specific limits ───────────────────────────────────────────────────

DOMAIN_LIMITS = {
    "linkedin.com": (8.0, 5.0),      # Very strict
    "indeed.com": (5.0, 3.0),        # Moderately strict
    "glassdoor.com": (6.0, 4.0),
    "remoteok.com": (2.0, 1.0),
    "remotive.com": (2.0, 1.0),
    "weworkremotely.com": (3.0, 2.0),
    "hunter.io": (1.0, 0.5),
    "2captcha.com": (5.0, 2.0),
    "default": (3.0, 2.0),
}


async def polite_wait(domain: str):
    """Apply domain-appropriate rate limiting."""
    limits = DOMAIN_LIMITS.get(domain, DOMAIN_LIMITS["default"])
    await rate_limiter.wait(domain, *limits)


def extract_domain(url: str) -> str:
    """Extract base domain from URL."""
    import re
    m = re.search(r"https?://(?:www\.)?([a-zA-Z0-9.\-]+)", url)
    return m.group(1).split(".")[0] + "." + ".".join(m.group(1).split(".")[1:]) if m else "default"


# ── Email sending throttle ────────────────────────────────────────────────────

class EmailThrottle:
    """
    Tracks emails sent per day to stay under Gmail limits.
    Gmail personal: 500/day
    """

    def __init__(self, daily_limit: int = 450):  # conservative buffer
        self.daily_limit = daily_limit
        self._count = 0
        self._reset_date = time.strftime("%Y-%m-%d")

    def _check_reset(self):
        today = time.strftime("%Y-%m-%d")
        if today != self._reset_date:
            self._count = 0
            self._reset_date = today

    def can_send(self) -> bool:
        self._check_reset()
        return self._count < self.daily_limit

    def record_send(self):
        self._check_reset()
        self._count += 1

    @property
    def remaining(self) -> int:
        self._check_reset()
        return max(0, self.daily_limit - self._count)


email_throttle = EmailThrottle()
