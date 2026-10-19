"""Analiz motorlarını (essentia / librosa / basic) aynı şarkılar üzerinde karşılaştırır.

Her şarkının Deezer önizlemesi BİR KEZ indirilir, kurulu her motorla analiz edilir, sonra silinir.
Sonuç Markdown tablo olarak yazdırılır (GitHub Actions özet sayfasında görünür).
Veritabanına hiçbir şey yazmaz.

Kullanım: python scripts/compare_engines.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from muzikarsiv.analysis import analyze_file  # noqa: E402
from muzikarsiv.analysis import backends  # noqa: E402
from muzikarsiv.sources.deezer import DeezerClient  # noqa: E402

# (arama, bilinen BPM veya None). Bilinen değerler yaygın kaynaklardaki yaklaşık değerlerdir.
SONGS = [
    ("Sezen Aksu Gidiyorum", None),
    ("Tarkan Şımarık", None),
    ("Müslüm Gürses Nilüfer", None),
    ("Barış Manço Gülpembe", None),
    ("Ferdi Tayfur Bana Sor", None),
    ("Duman Senden Daha Güzel", None),
    ("Mabel Matiz Antidepresan", None),
    ("Daft Punk Harder Better Faster Stronger", 123),
    ("Dua Lipa Levitating", 103),
    ("Adele Rolling in the Deep", 105),
    ("Queen Another One Bites the Dust", 110),
    ("The Weeknd Blinding Lights", 171),
]


def main() -> int:
    engines = [e for e in backends.available() if e != "basic"] + ["basic"]
    dz = DeezerClient()
    head = "| Şarkı | Bilinen BPM | " + " | ".join(f"{e} BPM (güven) | {e} ton" for e in engines) + " |"
    print(f"Kurulu motorlar: {', '.join(engines)}\n")
    print(head)
    print("|" + "---|" * (2 + 2 * len(engines)))
    for query, known in SONGS:
        try:
            hits = [t for t in dz.search(query, limit=5) if t.get("preview")]
            if not hits:
                print(f"| {query} | — | önizleme bulunamadı |")
                continue
            track = dz.track(hits[0]["id"])  # taze önizleme bağlantısı
            path = dz.download_preview(track["preview"])
        except Exception as e:  # noqa: BLE001
            print(f"| {query} | — | HATA: {e} |")
            continue
        try:
            cells = []
            for eng in engines:
                try:
                    r = analyze_file(path, eng)
                    cells += [f"{r.bpm:.1f} ({r.bpm_conf:.2f})", f"{r.musical_key} {r.key_scale} ({r.camelot})"]
                except Exception as e:  # noqa: BLE001
                    cells += [f"HATA: {str(e)[:40]}", "—"]
        finally:
            os.remove(path)
        name = f"{track['artist']['name']} — {track['title']}"
        print(f"| {name} | {known or '?'} | " + " | ".join(cells) + " |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
