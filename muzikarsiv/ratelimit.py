"""Hız sınırlama: token bucket + basit devre kesici + dayanıklı HTTP isteği."""

from __future__ import annotations

import logging
import random
import threading
import time

import requests

log = logging.getLogger(__name__)


class TokenBucket:
    """'period' saniyede en fazla 'capacity' istek."""

    def __init__(self, capacity: int, period: float):
        self.capacity = capacity
        self.rate = capacity / period
        self.tokens = float(capacity)
        self.last = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
                self.last = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / self.rate
            time.sleep(wait)


class CircuitOpen(RuntimeError):
    """Servis üst üste hata veriyor; bir süre istek atılmıyor."""


class CircuitBreaker:
    def __init__(self, threshold: int = 5, cooldown: float = 120):
        self.threshold, self.cooldown = threshold, cooldown
        self.failures = 0
        self.opened_at = 0.0

    def check(self, name: str) -> None:
        if self.failures >= self.threshold:
            if time.monotonic() - self.opened_at < self.cooldown:
                raise CircuitOpen(f"{name}: devre açık, {self.cooldown:.0f} sn bekleniyor")
            self.failures = self.threshold - 1  # yarı açık: bir deneme hakkı

    def success(self) -> None:
        self.failures = 0

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = time.monotonic()


class RetryableError(RuntimeError):
    """Geçici hata (429, 5xx, kota): daha sonra tekrar denenebilir."""


def get_json(session: requests.Session, url: str, *, params=None, bucket: TokenBucket | None = None,
             breaker: CircuitBreaker | None = None, name: str = "api", retries: int = 4,
             quota_check=None, timeout: float = 20):
    """GET + JSON. 429/5xx/kota hatasında üstel geri çekilme ile tekrar dener."""
    if breaker:
        breaker.check(name)
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        if bucket:
            bucket.acquire()
        try:
            r = session.get(url, params=params, timeout=timeout)
            if r.status_code == 429 or r.status_code >= 500:
                raise RetryableError(f"{name} HTTP {r.status_code}")
            r.raise_for_status()
            data = r.json()
            if quota_check and quota_check(data):
                raise RetryableError(f"{name} kota aşıldı")
            if breaker:
                breaker.success()
            return data
        except (RetryableError, requests.ConnectionError, requests.Timeout) as e:
            last_err = e
            if breaker:
                breaker.failure()
            if attempt < retries:
                delay = min(60, 2 ** attempt * 1.5) + random.uniform(0, 1)
                log.warning("%s: %s — %.1f sn sonra tekrar (%d/%d)", name, e, delay, attempt + 1, retries)
                time.sleep(delay)
    raise RetryableError(str(last_err))
