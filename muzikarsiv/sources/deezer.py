"""Deezer public API istemcisi (anahtarsız). Kota: ~50 istek / 5 sn / IP."""

from __future__ import annotations

import os
import tempfile
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
        # Önbellek istemcinin İÇİNDE: eskiden modül düzeyindeki lru_cache istemciyi (ve açık
        # bağlantılarını) sonsuza dek tutuyordu; sürekli modda "Too many open files" hatası buydu.
        self._genre_cache: dict[int, str | None] = {}

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
        if not album_id:
            return None
        if album_id not in self._genre_cache:
            if len(self._genre_cache) > 4096:
                self._genre_cache.clear()
            self._genre_cache[album_id] = self._fetch_album_genre(album_id)
        return self._genre_cache[album_id]

    def _fetch_album_genre(self, album_id: int) -> str | None:
        try:
            album = self._get(f"album/{album_id}")
        except PermanentError:
            return None
        genres = (album.get("genres") or {}).get("data") or []
        return genres[0]["name"] if genres else None

    def close(self) -> None:
        self.session.close()

    def artist_related(self, artist_id: int, limit: int = 20) -> list[dict]:
        return self._get(f"artist/{artist_id}/related", {"limit": limit}).get("data", [])

    def artist_top(self, artist_id: int, limit: int = 10) -> list[dict]:
        return self._get(f"artist/{artist_id}/top", {"limit": limit}).get("data", [])

    def search_playlists(self, query: str, limit: int = 5) -> list[dict]:
        return self._get("search/playlist", {"q": query, "limit": limit}).get("data", [])

    def playlist_tracks(self, playlist_id: int, limit: int = 100) -> list[dict]:
        return self._get(f"playlist/{playlist_id}/tracks", {"limit": limit}).get("data", [])

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

