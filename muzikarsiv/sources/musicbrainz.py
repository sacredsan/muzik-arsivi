"""MusicBrainz istemcisi: ISRC -> kayıt/sanatçı MBID, sanatçı ülkesi, topluluk etiketleri.

KURAL: en fazla 1 istek/sn ve anlamlı User-Agent (aksi halde IP engellenir).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache

import requests

from ..ratelimit import CircuitBreaker, RetryableError, TokenBucket, get_json

log = logging.getLogger(__name__)
BASE = "https://musicbrainz.org/ws/2"


@dataclass
class MBInfo:
    recording_mbid: str | None = None
    artist_mbid: str | None = None
    artist_country: str | None = None
    tags: dict[str, int] = field(default_factory=dict)  # etiket -> oy sayısı (kayıt + sanatçı)


class MusicBrainzClient:
    def __init__(self, user_agent: str, session=None):
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.session.headers["Accept"] = "application/json"
        self.bucket = TokenBucket(1, 1.1)
        self.breaker = CircuitBreaker(threshold=5, cooldown=120)

    def _get(self, path: str, params: dict) -> dict:
        params = {**params, "fmt": "json"}
        try:
            return get_json(self.session, f"{BASE}/{path}", params=params, bucket=self.bucket,
                            breaker=self.breaker, name="musicbrainz", retries=3)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                return {}
            raise

    def lookup_isrc(self, isrc: str | None) -> MBInfo:
        """MusicBrainz isteğe bağlı zenginleştirmedir: hata verirse boş bilgiyle devam edilir."""
        if not isrc:
            return MBInfo()
        try:
            data = self._get(f"isrc/{isrc}", {"inc": "artist-credits+tags"})
            recs = data.get("recordings") or []
            if not recs:
                return MBInfo()
            rec = recs[0]
            info = MBInfo(recording_mbid=rec.get("id"))
            for t in rec.get("tags") or []:
                info.tags[t["name"]] = info.tags.get(t["name"], 0) + int(t.get("count", 1))
            credits = rec.get("artist-credit") or []
            if credits and credits[0].get("artist"):
                info.artist_mbid = credits[0]["artist"]["id"]
                country, artist_tags = self._artist(info.artist_mbid)
                info.artist_country = country
                for name, cnt in artist_tags.items():
                    info.tags[name] = info.tags.get(name, 0) + cnt
            return info
        except (RetryableError, requests.RequestException) as e:
            log.warning("MusicBrainz atlandı (%s): %s", isrc, e)
            return MBInfo()

    def _artist(self, mbid: str) -> tuple[str | None, dict[str, int]]:
        return _artist_cached(self, mbid)


@lru_cache(maxsize=4096)
def _artist_cached(client: MusicBrainzClient, mbid: str):
    data = client._get(f"artist/{mbid}", {"inc": "tags"})
    country = data.get("country")
    if not country:
        codes = (data.get("area") or {}).get("iso-3166-1-codes") or []
        country = codes[0] if codes else None
    tags = {t["name"]: int(t.get("count", 1)) for t in data.get("tags") or []}
    return country, tags
