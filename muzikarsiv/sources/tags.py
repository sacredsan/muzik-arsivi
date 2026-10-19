"""Etiket (tür / ruh hali) sağlayıcıları. Hepsi aynı arayüzü uygular, .env ile seçilir.

Dönüş: {etiket: ağırlık 0..1}. Kara liste ve eşik burada uygulanır.
"""

from __future__ import annotations

import logging
from typing import Protocol

import requests

from ..normalize import norm
from ..ratelimit import CircuitBreaker, RetryableError, TokenBucket, get_json
from .musicbrainz import MBInfo

log = logging.getLogger(__name__)

# Müzikal anlamı olmayan kişisel etiketler
BLACKLIST = {
    "seen live", "favorites", "favourite", "favorite", "favourites", "owned", "albums i own",
    "my favorite", "beautiful", "awesome", "love", "loved", "amazing", "good", "best",
    "spotify", "youtube", "under 2000 listeners", "check out", "to listen", "fip", "radio",
    "male vocalists", "female vocalists", "male vocalist", "female vocalist", "vocal",
    "my music", "favorite songs", "favourite songs", "cool", "nice", "great",
}

MIN_WEIGHT = 0.10
MAX_TAGS = 15

# Bu sözlükteki etiketler sub_genres'e, kalanlar mood_tags'e gider
GENRE_VOCAB = {
    "pop", "rock", "hip hop", "hip-hop", "rap", "trap", "r&b", "rnb", "soul", "funk", "disco",
    "house", "deep house", "tech house", "techno", "trance", "edm", "electronic", "electronica",
    "dance", "drum and bass", "dnb", "dubstep", "ambient", "downtempo", "chillout", "lo-fi", "lofi",
    "jazz", "blues", "classical", "metal", "heavy metal", "punk", "indie", "indie rock", "indie pop",
    "alternative", "alternative rock", "folk", "country", "reggae", "reggaeton", "latin", "afrobeat",
    "k-pop", "synthpop", "new wave", "grunge", "acoustic", "singer-songwriter", "soundtrack",
    "arabesk", "arabesque", "turkish pop", "turkish rock", "anatolian rock", "turkish folk",
    "türkü", "turku", "fantezi", "turkish hip hop", "turkish rap", "ozgun muzik", "sanat muzigi",
    "turkish classical", "oriental", "belly dance", "halay", "roman havasi",
}


def is_blacklisted(name: str) -> bool:
    key = name.strip().lower()
    return not key or key in BLACKLIST or norm(key) in BLACKLIST or len(key) > 40


def clean_tags(raw: dict[str, float]) -> dict[str, float]:
    """Kara liste, küçük harf, tekilleştirme, eşik ve en çok MAX_TAGS etiket."""
    out: dict[str, float] = {}
    for name, w in raw.items():
        key = name.strip().lower()
        if is_blacklisted(key):
            continue
        if w >= MIN_WEIGHT:
            out[key] = round(max(out.get(key, 0), min(1.0, w)), 3)
    return dict(sorted(out.items(), key=lambda kv: -kv[1])[:MAX_TAGS])


def split_tags(tags: dict[str, float]) -> tuple[list[str], dict[str, float]]:
    sub_genres = [t for t in tags if t in GENRE_VOCAB]
    moods = {t: w for t, w in tags.items() if t not in GENRE_VOCAB}
    return sub_genres, moods


class TagProvider(Protocol):
    name: str

    def get_tags(self, artist: str, title: str, mb: MBInfo | None) -> dict[str, float]: ...


class NoTags:
    name = "none"

    def get_tags(self, artist, title, mb):
        return {}


class MusicBrainzTags:
    """Ek istek atmaz: MusicBrainz sorgusunda gelen topluluk etiketlerini kullanır."""

    name = "musicbrainz"

    def get_tags(self, artist, title, mb):
        if not mb or not mb.tags:
            return {}
        useful = {t: c for t, c in mb.tags.items() if not is_blacklisted(t) and c > 0}
        if not useful:
            return {}
        top = max(useful.values())
        return clean_tags({t: c / top for t, c in useful.items()})


class LastFmTags:
    """Last.fm track.getTopTags (boşsa artist.getTopTags). Ticari kullanım için anlaşma + atıf gerekir."""

    name = "lastfm"
    BASE = "https://ws.audioscrobbler.com/2.0/"

    def __init__(self, api_key: str, session=None):
        if not api_key:
            raise ValueError("TAG_PROVIDER=lastfm için LASTFM_API_KEY gerekli")
        self.api_key = api_key
        self.session = session or requests.Session()
        self.bucket = TokenBucket(4, 1.0)
        self.breaker = CircuitBreaker(threshold=5, cooldown=120)

    def _call(self, method: str, **params) -> list[dict]:
        data = get_json(self.session, self.BASE, bucket=self.bucket, breaker=self.breaker, name="lastfm",
                        params={"method": method, "api_key": self.api_key, "format": "json",
                                "autocorrect": 1, **params},
                        quota_check=lambda d: isinstance(d, dict) and d.get("error") == 29)
        tags = (data.get("toptags") or {}).get("tag") or []
        return tags if isinstance(tags, list) else [tags]

    def get_tags(self, artist, title, mb):
        try:
            tags = self._call("track.gettoptags", artist=artist, track=title)
            if not tags:
                tags = self._call("artist.gettoptags", artist=artist)
        except (RetryableError, requests.RequestException) as e:
            log.warning("Last.fm atlandı: %s", e)
            return {}
        return clean_tags({t["name"]: int(t.get("count", 0)) / 100 for t in tags})


def make_tag_provider(kind: str, lastfm_api_key: str = "") -> TagProvider:
    if kind == "lastfm":
        return LastFmTags(lastfm_api_key)
    if kind == "musicbrainz":
        return MusicBrainzTags()
    return NoTags()
