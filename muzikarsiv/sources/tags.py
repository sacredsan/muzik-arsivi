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
MAX_TAGS = 25

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

# Ülke / dil / dönem etiketleri: kültür ve yıl bilgisi zaten ayrı tutuluyor, mood sayılmaz
NON_MOOD = {
    "turkish", "turkce", "türkçe", "turkey", "türkiye", "turk", "türk", "french", "france",
    "british", "uk", "english", "american", "usa", "german", "deutsch", "italian", "spanish",
    "latin american", "korean", "japanese", "swedish", "canadian", "australian", "russian",
    "greek", "arabic", "kurdish", "azerbaijani", "60s", "70s", "80s", "90s", "00s", "2000s",
    "2010s", "2020s", "oldies", "classic",
}


def is_blacklisted(name: str) -> bool:
    key = name.strip().lower()
    return not key or key in BLACKLIST or norm(key) in BLACKLIST or len(key) > 40


# Kaynaklardan gelen ham etiketler için daha düşük eşik: mood etiketleri genelde az oy alır,
# bu yüzden ilk elemede kaybolmamalı. Görüntülenen/saklanan liste yine MIN_WEIGHT ile süzülür.
RAW_MIN_WEIGHT = 0.02
RAW_MAX_TAGS = 80


def clean_tags(raw: dict[str, float], min_weight: float = MIN_WEIGHT,
               max_tags: int = MAX_TAGS) -> dict[str, float]:
    """Kara liste, küçük harf, tekilleştirme, eşik ve en çok max_tags etiket."""
    out: dict[str, float] = {}
    for name, w in raw.items():
        key = name.strip().lower()
        if is_blacklisted(key):
            continue
        if w >= min_weight:
            out[key] = round(max(out.get(key, 0), min(1.0, w)), 3)
    return dict(sorted(out.items(), key=lambda kv: -kv[1])[:max_tags])


GENRE_VOCAB |= {
    "french house", "electropop", "dance-pop", "dance pop", "europop", "eurodance", "nu disco",
    "synthwave", "electro", "electro house", "progressive house", "big room", "future bass",
    "trip-hop", "trip hop", "neo-soul", "contemporary r&b", "pop rock", "soft rock", "hard rock",
    "classic rock", "psychedelic rock", "art rock", "progressive rock", "post-punk", "shoegaze",
    "dream pop", "art pop", "bedroom pop", "emo", "pop punk", "nu metal", "thrash metal",
    "gangsta rap", "east coast hip hop", "west coast hip hop", "boom bap", "drill", "grime",
    "afrobeats", "dancehall", "bossa nova", "salsa", "bachata", "flamenco", "chanson",
    "anatolian psych", "turkish psychedelic", "turkish alternative", "türk pop", "turk pop",
    "arabesk pop", "türk halk müziği", "halk muzigi", "türk sanat müziği", "fantezi müzik",
    "turkish trap", "turkish r&b", "world", "world music", "instrumental", "orchestral",
}

# Etiket -> standart mood adı (Türkçe karşılıklar dahil). Bu listede olmayan etiketler mood sayılmaz.
MOOD_VOCAB = {
    "happy": "happy", "cheerful": "happy", "uplifting": "happy", "feel good": "happy",
    "feelgood": "happy", "fun": "happy", "joyful": "happy", "summer": "happy", "sunny": "happy",
    "mutlu": "happy", "neşeli": "happy", "neseli": "happy", "eğlenceli": "happy",
    "sad": "sad", "melancholy": "sad", "melancholic": "sad", "heartbreak": "sad",
    "depressing": "sad", "depressive": "sad", "sorrow": "sad", "lonely": "sad", "tearjerker": "sad",
    "hüzünlü": "sad", "huzunlu": "sad", "hüzün": "sad", "acı": "sad", "ayrılık": "sad", "dertli": "sad",
    "energetic": "energetic", "upbeat": "energetic", "high energy": "energetic", "powerful": "energetic",
    "hareketli": "energetic", "enerjik": "energetic",
    "calm": "calm", "relaxing": "calm", "relax": "calm", "mellow": "calm", "soothing": "calm",
    "peaceful": "calm", "chill": "calm", "sakin": "calm", "huzurlu": "calm",
    "romantic": "romantic", "love songs": "romantic", "love song": "romantic", "sensual": "romantic",
    "sexy": "romantic", "aşk": "romantic", "ask": "romantic", "romantik": "romantic",
    "dark": "dark", "gloomy": "dark", "haunting": "dark", "ominous": "dark", "karanlık": "dark",
    "aggressive": "aggressive", "angry": "aggressive", "intense": "aggressive", "öfkeli": "aggressive",
    "nostalgic": "nostalgic", "nostalgia": "nostalgic", "memories": "nostalgic", "nostalji": "nostalgic",
    "dreamy": "dreamy", "atmospheric": "dreamy", "ethereal": "dreamy",
    "emotional": "emotional", "passionate": "emotional", "touching": "emotional", "duygusal": "emotional",
    "party": "party", "club": "party", "dance floor": "party", "dancefloor": "party", "parti": "party",
    "epic": "epic", "anthem": "epic", "motivational": "epic", "motivation": "epic",
}


def split_tags(tags: dict[str, float], artist: str = "") -> tuple[list[str], dict[str, float]]:
    """Etiketleri alt türlere ve standart mood'lara ayırır.

    Sanatçı adı, ülke/dil etiketleri ve sözlükte olmayan etiketler mood sayılmaz
    (hepsi ham olarak 'tags' sütununda saklanır, ileride yeniden işlenebilir).
    """
    artist_n = norm(artist, strip_extras=False)
    sub_genres = [t for t in clean_tags(tags) if t in GENRE_VOCAB]  # alt türler: yalnız güçlü etiketler
    moods: dict[str, float] = {}
    for t, w in tags.items():
        if t in NON_MOOD or (artist_n and norm(t, strip_extras=False) == artist_n):
            continue
        canon = MOOD_VOCAB.get(t)
        if canon:
            moods[canon] = round(max(moods.get(canon, 0.0), w), 3)
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
        return clean_tags({t: c / top for t, c in useful.items()}, RAW_MIN_WEIGHT, RAW_MAX_TAGS)


class LastFmTags:
    """Last.fm track.getTopTags + artist.getTopTags. Ticari kullanım için anlaşma + atıf gerekir."""

    name = "lastfm"
    BASE = "https://ws.audioscrobbler.com/2.0/"

    def __init__(self, api_key: str, session=None):
        if not api_key:
            raise ValueError("TAG_PROVIDER=lastfm için LASTFM_API_KEY gerekli")
        self.api_key = api_key
        self.session = session or requests.Session()
        self.bucket = TokenBucket(4, 1.0)
        self.breaker = CircuitBreaker(threshold=5, cooldown=120)
        self._artist_cache: dict[str, dict[str, float]] = {}

    def _call(self, method: str, **params) -> list[dict]:
        data = get_json(self.session, self.BASE, bucket=self.bucket, breaker=self.breaker, name="lastfm",
                        params={"method": method, "api_key": self.api_key, "format": "json",
                                "autocorrect": 1, **params},
                        quota_check=lambda d: isinstance(d, dict) and d.get("error") == 29)
        tags = (data.get("toptags") or {}).get("tag") or []
        return tags if isinstance(tags, list) else [tags]

    ARTIST_WEIGHT = 0.5  # sanatçı etiketleri şarkı etiketlerinden daha az ağırlıklı

    def _artist_tags(self, artist: str) -> dict[str, float]:
        key = norm(artist, strip_extras=False)
        if key not in self._artist_cache:
            tags = self._call("artist.gettoptags", artist=artist)
            self._artist_cache[key] = {t["name"]: int(t.get("count", 0)) / 100 for t in tags}
        return self._artist_cache[key]

    def get_tags(self, artist, title, mb):
        """Şarkı etiketleri (tam ağırlık) + sanatçı etiketleri (yarı ağırlık) birleştirilir."""
        out: dict[str, float] = {}
        try:
            for t in self._call("track.gettoptags", artist=artist, track=title):
                out[t["name"]] = int(t.get("count", 0)) / 100
            for name, w in self._artist_tags(artist).items():
                out[name] = max(out.get(name, 0.0), w * self.ARTIST_WEIGHT)
        except (RetryableError, requests.RequestException) as e:
            log.warning("Last.fm atlandı: %s", e)
        return clean_tags(out, RAW_MIN_WEIGHT, RAW_MAX_TAGS)


class CombinedTags:
    """Birden çok kaynağı birleştirir: ilk kaynak tam ağırlık, sonrakiler azaltılmış ağırlık."""

    def __init__(self, providers: list, weights: list[float]):
        self.providers, self.weights = providers, weights
        self.name = "+".join(p.name for p in providers)

    def get_tags(self, artist, title, mb):
        out: dict[str, float] = {}
        for p, w in zip(self.providers, self.weights):
            for t, v in p.get_tags(artist, title, mb).items():
                out[t] = max(out.get(t, 0.0), v * w)
        return clean_tags(out, RAW_MIN_WEIGHT, RAW_MAX_TAGS)


def make_tag_provider(kind: str, lastfm_api_key: str = "") -> TagProvider:
    """auto: Last.fm anahtarı varsa Last.fm + MusicBrainz birlikte, yoksa sadece MusicBrainz."""
    if kind == "auto":
        if lastfm_api_key:
            return CombinedTags([LastFmTags(lastfm_api_key), MusicBrainzTags()], [1.0, 0.7])
        return MusicBrainzTags()
    if kind == "lastfm":
        return LastFmTags(lastfm_api_key)
    if kind == "musicbrainz":
        return MusicBrainzTags()
    return NoTags()
