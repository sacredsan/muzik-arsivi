"""Bir şarkının baştan sona işlenmesi: Deezer -> analiz -> etiket -> kültür -> veritabanı satırı.
Ayrıca: sanatçı eşleşmeli Deezer araması ve ilgili sanatçı taraması (crawl)."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

from .analysis import analyze_file
from .config import Config
from .culture import decide_culture
from .db import SupabaseDB
from .normalize import norm, norm_artist
from .sources.deezer import DeezerClient
from .sources.musicbrainz import MusicBrainzClient
from .sources.tags import TagProvider, make_tag_provider, split_tags

log = logging.getLogger(__name__)


@dataclass
class Services:
    cfg: Config
    deezer: DeezerClient
    mb: MusicBrainzClient
    tags: TagProvider
    db: SupabaseDB | None

    @classmethod
    def build(cls, cfg: Config, use_db: bool = True) -> "Services":
        return cls(
            cfg=cfg,
            deezer=DeezerClient(cfg.deezer_requests, cfg.deezer_period),
            mb=MusicBrainzClient(cfg.mb_user_agent),
            tags=make_tag_provider(cfg.tag_provider, cfg.lastfm_api_key),
            db=SupabaseDB(cfg.supabase_url, cfg.supabase_service_key) if use_db and cfg.has_db else None,
        )


def build_row(track: dict, genre: str | None, analysis, mb, tags: dict, tag_source: str,
              source: str) -> dict:
    artist = (track.get("artist") or {})
    title = track.get("title") or track.get("title_short") or ""
    artist_name = artist.get("name") or ""
    culture, reason = decide_culture(mb.artist_country if mb else None, tags, title, artist_name)
    sub_genres, moods = split_tags(tags, artist_name)
    a = analysis.to_dict()
    return {
        "deezer_id": int(track["id"]),
        "isrc": track.get("isrc") or None,
        "mbid": mb.recording_mbid if mb else None,
        "artist_mbid": mb.artist_mbid if mb else None,
        "track_name": title,
        "artist_name": artist_name,
        "artist_id": artist.get("id"),
        "album_name": (track.get("album") or {}).get("title"),
        "title_norm": norm(title),
        "artist_norm": norm_artist(artist_name),
        "duration_sec": track.get("duration"),
        "deezer_rank": track.get("rank"),
        "genre": genre,
        "sub_genres": sub_genres,
        "mood_tags": moods,
        "tags": tags,
        "tag_source": tag_source,
        "cultural_context": culture,
        "culture_reason": reason,
        "artist_country": mb.artist_country if mb else None,
        "bpm": a["bpm"],
        "bpm_raw": a["bpm_raw"],
        "bpm_conf": a["bpm_conf"],
        "musical_key": a["musical_key"],
        "key_scale": a["key_scale"],
        "key_conf": a["key_conf"],
        "camelot": a["camelot"],
        "energy": a["energy"],
        "danceability": a["danceability"],
        "mood_valence": a["mood_valence"],
        "mood_arousal": a["mood_arousal"],
        # pgvector PostgREST üzerinden '[0.1,0.2,...]' metni olarak gönderilir
        "feature_vec": "[" + ",".join(f"{x:.4f}" for x in a["feature_vec"]) + "]",
        "analyzer": a["analyzer"],
        "analysis_version": a["analysis_version"],
        "source": source,
    }


def process_track(svc: Services, deezer_id: int, source: str = "seed", skip_duplicates: bool = True) -> dict:
    """Şarkıyı işler ve (varsa) veritabanına yazar. Dönüş: {'status': ..., 'row': ...}"""
    t0 = time.monotonic()
    track = svc.deezer.track(deezer_id)
    title = track.get("title") or ""
    artist_name = (track.get("artist") or {}).get("name") or ""
    log.info("Şarkı: %s — %s (ISRC %s)", artist_name, title, track.get("isrc"))

    if svc.db and skip_duplicates:
        dup = svc.db.find_duplicate(track.get("isrc"), norm(title), norm_artist(artist_name),
                                    track.get("duration"))
        if dup:
            return {"status": "duplicate", "song_id": dup, "track": track}

    genre = svc.deezer.album_genre((track.get("album") or {}).get("id"))
    mp3 = svc.deezer.download_preview(track.get("preview"))
    try:
        analysis = analyze_file(mp3, svc.cfg.analyzer)
    finally:
        os.remove(mp3)  # ses dosyası asla saklanmaz

    mb = svc.mb.lookup_isrc(track.get("isrc"))
    tags = svc.tags.get_tags(artist_name, title, mb)
    row = build_row(track, genre, analysis, mb, tags, svc.tags.name, source)

    status = "analyzed"
    if svc.db:
        saved = svc.db.upsert_song(row)
        row["id"] = saved.get("id")
        status = "saved"
    return {"status": status, "seconds": round(time.monotonic() - t0, 1), "row": row, "track": track}


def artist_matches(wanted: str, found: str) -> bool:
    """'Tarkan' ~ 'Tarkan', 'Mabel Matiz' !~ 'Mert Demir'. feat./ortak sanatçılara toleranslı."""
    w, f = norm_artist(wanted), norm_artist(found)
    return bool(w and f) and (w == f or w in f or f in w)


def find_track(svc: Services, artist: str, title: str) -> dict | None:
    """Deezer'da sanatçısı EŞLEŞEN ve önizlemesi olan sonucu bulur (remix/cover'a düşmemek için)."""
    hits = svc.deezer.search(f'artist:"{artist}" track:"{title}"', limit=10) or \
        svc.deezer.search(f"{artist} {title}", limit=15)
    title_n = norm(title)
    best = None
    for h in hits:
        if not h.get("preview") or not artist_matches(artist, (h.get("artist") or {}).get("name", "")):
            continue
        h_title = norm(h.get("title", ""))
        if h_title == title_n:
            return h
        if best is None and (title_n in h_title or h_title in title_n):
            best = h
    return best


def crawl_artist(svc: Services, artist_id: int | None, artist_name: str = "",
                 related_limit: int = 8, top_limit: int = 5) -> int:
    """Sanatçının ve benzer sanatçıların popüler şarkılarını kuyruğa ekler (öncelik 0).
    Aynı sanatçı ikinci kez taranmaz. Dönüş: kuyruğa eklenen şarkı sayısı."""
    if not svc.db or not artist_id or svc.db.artist_crawled(artist_id):
        return 0
    related = svc.deezer.artist_related(artist_id, limit=related_limit)
    artists = [(artist_id, artist_name)] + [(a["id"], a.get("name", "")) for a in related]
    items = []
    for aid, _ in artists:
        for t in svc.deezer.artist_top(aid, limit=top_limit):
            if t.get("preview"):
                items.append({"deezer_id": t["id"], "track_name": t.get("title"),
                              "artist_name": (t.get("artist") or {}).get("name")})
    added = svc.db.enqueue(items, priority=0, source="crawl") if items else 0
    svc.db.mark_artist_crawled(artist_id, artist_name, [a for a, _ in artists[1:]])
    log.info("Tarama: %s (+%d benzer sanatçı) -> %d yeni iş", artist_name, len(artists) - 1, added)
    return added
