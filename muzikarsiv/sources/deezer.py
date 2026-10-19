"""Deezer public API istemcisi (anahtarsız). Kota: ~50 istek / 5 sn / IP."""

from __future__ import annotations

import os
import tempfile
from functools import lru_cache

import requests

from ..ratelimit import CircuitBreaker, RetryableError, TokenBucket, get_json
from . import PermanentError

BASE = "https://api.deezer.com"


def _is_quota_error(data) -> bool:
    return isinstance(data, dict) and data.get("error", {}).get("code") == 4


class DeezerClient:
    def __init__(self, requests_per_period: int = 40, period: float = 5.0, session=None):
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "MuzikArsivi/0.1")
        self.bucket = TokenBucket(requests_per_period, period)
        self.breaker = CircuitBreaker(threshold=6, cooldown=90)

    def _get(self, path: str, params=None) -> dict:
        data = get_json(self.session, f"{BASE}/{path}", params=params, bucket=self.bucket,
                        breaker=self.breaker, name="deezer", quota_check=_is_quota_error)
        if isinstance(data, dict) and "error" in data:
            err = data["error"]
            raise PermanentError(f"Deezer: {err.get('message')} (kod {err.get('code')}) — {path}")
        return data

    def track(self, track_id: int) -> dict:
        """ISRC, süre, rank, önizleme URL'si, sanatçı ve albüm bilgisi."""
        return self._get(f"track/{track_id}")

    def album_genre(self, album_id: int | None) -> str | None:
        return _album_genre_cached(self, album_id) if album_id else None

    def artist_related(self, artist_id: int, limit: int = 20) -> list[dict]:
        return self._get(f"artist/{artist_id}/related", {"limit": limit}).get("data", [])

    def artist_top(self, artist_id: int, limit: int = 10) -> list[dict]:
        return self._get(f"artist/{artist_id}/top", {"limit": limit}).get("data", [])

    def search(self, query: str, limit: int = 10) -> list[dict]:
        return self._get("search", {"q": query, "limit": limit}).get("data", [])

    def download_preview(self, preview_url: str) -> str:
        """Önizleme MP3'ünü geçici dosyaya indirir, yolunu döndürür. ÇAĞIRAN SİLMEKTEN SORUMLUDUR."""
        if not preview_url:
            raise PermanentError("Bu şarkının Deezer önizlemesi yok")
        self.bucket.acquire()
        try:
            r = self.session.get(preview_url, timeout=30)
        except (requests.ConnectionError, requests.Timeout) as e:
            raise RetryableError(f"önizleme indirilemedi: {e}") from e
        if r.status_code == 403:
            raise RetryableError("önizleme bağlantısının süresi dolmuş (403)")
        if r.status_code != 200 or len(r.content) < 10_000:
            raise RetryableError(f"önizleme indirilemedi (HTTP {r.status_code}, {len(r.content)} bayt)")
        fd, path = tempfile.mkstemp(suffix=".mp3", prefix="dz_")
        with os.fdopen(fd, "wb") as f:
            f.write(r.content)
        return path


@lru_cache(maxsize=4096)
def _album_genre_cached(client: DeezerClient, album_id: int) -> str | None:
    try:
        album = client._get(f"album/{album_id}")
    except PermanentError:
        return None
    genres = (album.get("genres") or {}).get("data") or []
    return genres[0]["name"] if genres else None
