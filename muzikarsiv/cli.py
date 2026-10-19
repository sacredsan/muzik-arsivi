"""Komut satırı.

  python -m muzikarsiv check                 # kurulum kontrolü (ffmpeg, analiz motoru, Supabase)
  python -m muzikarsiv search "sezen aksu"   # Deezer'da şarkı ara, ID'sini bul
  python -m muzikarsiv analyze 3135556       # tek şarkıyı analiz et ve Supabase'e yaz
  python -m muzikarsiv analyze 3135556 --no-db
  python -m muzikarsiv analyze-file sarki.mp3   # internetsiz: yerel dosyayı analiz et
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys

from . import __version__
from .analysis import FEATURE_NAMES, analyze_file
from .analysis import backends
from .config import load_config


def _print_row(row: dict) -> None:
    show = ["track_name", "artist_name", "genre", "sub_genres", "cultural_context", "culture_reason",
            "bpm", "bpm_conf", "musical_key", "key_scale", "camelot", "key_conf", "energy",
            "mood_tags", "isrc", "mbid", "artist_country", "analyzer"]
    for k in show:
        if k in row:
            v = row[k]
            print(f"  {k:<17} {json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v}")


def _describe_key(key: str) -> str:
    """Anahtarın DEĞERİNİ göstermeden türünü ve uzunluğunu söyler (teşhis için)."""
    if not key:
        return "BOŞ  <-- .env'deki SUPABASE_SERVICE_KEY satırını doldurun"
    if key.startswith("sb_secret_"):
        return f"yeni gizli anahtar (sb_secret_...), {len(key)} karakter  [doğru tür]"
    if key.startswith("sb_publishable_"):
        return "publishable anahtar  <-- YANLIŞ TÜR: 'Secret keys' bölümündeki anahtar gerekli"
    if key.startswith("eyJ"):
        import base64
        import json as _json
        try:
            part = key.split(".")[1]
            role = _json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))).get("role")
        except Exception:  # noqa: BLE001
            role = None
        if role == "service_role":
            return f"eski service_role anahtarı, {len(key)} karakter  [doğru tür]"
        if role == "anon":
            return "eski anon anahtarı  <-- YANLIŞ TÜR: service_role anahtarı gerekli"
        return f"eski biçim ama okunamadı ({len(key)} karakter) <-- eksik kopyalanmış olabilir"
    return f"tanınmayan biçim ({len(key)} karakter, '{key[:3]}...' ile başlıyor) <-- yanlış/eksik kopyalanmış olabilir"


def cmd_check(args, cfg) -> int:
    ok = True
    print(f"muzikarsiv {__version__}")
    print(f"  ffmpeg           {'VAR' if shutil.which('ffmpeg') else 'YOK  <-- kurmanız gerekiyor'}")
    ok &= bool(shutil.which("ffmpeg"))
    print(f"  analiz motorları {', '.join(backends.available())} (seçilen: {backends.pick(cfg.analyzer)})")
    print(f"  etiket kaynağı   {cfg.tag_provider}")
    print(f"  işçi adı         {cfg.worker_name}")
    print(f"  Supabase adresi  {cfg.supabase_url or '(boş)'}")
    print(f"  Supabase anahtarı {_describe_key(cfg.supabase_service_key)}")
    if cfg.has_db:
        from .db import SupabaseDB
        try:
            stats = SupabaseDB(cfg.supabase_url, cfg.supabase_service_key).ping()
            print(f"  Supabase         BAĞLANDI (şarkı sayısı: {stats.get('total_songs')})")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"  Supabase         HATA: {e}")
    else:
        print("  Supabase         .env'de ayar yok (--no-db ile çalışabilirsiniz)")
    return 0 if ok else 1


def cmd_search(args, cfg) -> int:
    from .sources.deezer import DeezerClient

    for t in DeezerClient().search(args.query, limit=args.limit):
        prev = "önizleme var" if t.get("preview") else "ÖNİZLEME YOK"
        print(f"  {t['id']:>12}  {t['artist']['name']} — {t['title']}  ({t['duration']} sn, {prev})")
    return 0


def cmd_analyze(args, cfg) -> int:
    from .pipeline import Services, process_track

    svc = Services.build(cfg, use_db=not args.no_db)
    if not args.no_db and svc.db is None:
        print("Uyarı: Supabase ayarı yok, sonuç sadece ekrana yazılacak.")
    res = process_track(svc, args.deezer_id, source="seed", skip_duplicates=not args.force)
    if res["status"] == "duplicate":
        print(f"Bu şarkı arşivde zaten var (id {res['song_id']}). Yine de analiz için --force kullanın.")
        return 0
    print(f"Durum: {res['status']}  ({res['seconds']} sn)")
    if args.json:
        print(json.dumps(res["row"], ensure_ascii=False, indent=2))
    else:
        _print_row(res["row"])
    return 0


def cmd_analyze_file(args, cfg) -> int:
    r = analyze_file(args.path, cfg.analyzer)
    d = r.to_dict()
    if args.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return 0
    for k, v in d.items():
        if k != "feature_vec":
            print(f"  {k:<17} {v}")
    print("  feature_vec:")
    for name, v in zip(FEATURE_NAMES, r.feature_vec):
        print(f"    {name:<16} {v:.3f}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="muzikarsiv", description="Müzik arşivi analiz ajanı")
    p.add_argument("-v", "--verbose", action="store_true", help="ayrıntılı günlük")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="kurulumu kontrol et")
    s = sub.add_parser("search", help="Deezer'da şarkı ara")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=10)
    a = sub.add_parser("analyze", help="Deezer ID'si ile tek şarkıyı analiz et")
    a.add_argument("deezer_id", type=int)
    a.add_argument("--no-db", action="store_true", help="veritabanına yazma")
    a.add_argument("--force", action="store_true", help="arşivde olsa bile yeniden analiz et")
    a.add_argument("--json", action="store_true")
    f = sub.add_parser("analyze-file", help="yerel ses dosyasını analiz et (internetsiz)")
    f.add_argument("path")
    f.add_argument("--json", action="store_true")

    args = p.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # Windows konsolunda Türkçe karakter sorunu olmasın
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    handlers = {"check": cmd_check, "search": cmd_search, "analyze": cmd_analyze,
                "analyze-file": cmd_analyze_file}
    try:
        return handlers[args.cmd](args, cfg)
    except Exception as e:  # noqa: BLE001
        if args.verbose:
            raise
        print(f"HATA: {e}", file=sys.stderr)
        return 1
