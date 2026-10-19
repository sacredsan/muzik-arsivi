"""Birim + uçtan uca testler (internet gerektirmez). Çalıştırma: python -m unittest discover tests -v"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from muzikarsiv.camelot import camelot_distance, camelot_mismatch, to_camelot  # noqa: E402
from muzikarsiv.config import load_config  # noqa: E402
from muzikarsiv.culture import decide_culture  # noqa: E402
from muzikarsiv.normalize import norm, norm_artist  # noqa: E402
from muzikarsiv.pipeline import Services, process_track  # noqa: E402
from muzikarsiv.ratelimit import TokenBucket  # noqa: E402
from muzikarsiv.sources.musicbrainz import MBInfo  # noqa: E402
from muzikarsiv.sources.tags import MusicBrainzTags, clean_tags, split_tags  # noqa: E402

HAS_FFMPEG = shutil.which("ffmpeg") is not None


class TestNormalize(unittest.TestCase):
    def test_turkish(self):
        self.assertEqual(norm("İSTANBUL Şıkıdım - Gülüm (Çok Özel)"), "istanbul sikidim gulum cok ozel")

    def test_feat_and_remaster(self):
        self.assertEqual(norm("Yalnızlık Senfonisi (feat. Ezhel)"), "yalnizlik senfonisi")
        self.assertEqual(norm("Dudu ft. Tarkan"), "dudu")
        self.assertEqual(norm("Bohemian Rhapsody - Remastered 2011"), "bohemian rhapsody")
        self.assertEqual(norm("Hotel California (2013 Remaster)"), "hotel california")

    def test_artist_keeps_everything(self):
        self.assertEqual(norm_artist("Müslüm Gürses"), "muslum gurses")
        self.assertEqual(norm("Beyoncé"), "beyonce")


class TestCamelot(unittest.TestCase):
    def test_mapping(self):
        cases = {("A", "minor"): "8A", ("C", "major"): "8B", ("G", "major"): "9B", ("E", "minor"): "9A",
                 ("F#", "minor"): "11A", ("Db", "major"): "3B", ("Bb", "minor"): "3A", ("E", "major"): "12B",
                 ("C#", "minor"): "12A", ("G#", "minor"): "1A", ("B", "major"): "1B", ("D", "minor"): "7A"}
        for (k, s), want in cases.items():
            self.assertEqual(to_camelot(k, s), want, f"{k} {s}")

    def test_distance(self):
        self.assertEqual(camelot_distance("8A", "8A"), 0)
        self.assertEqual(camelot_distance("8A", "9A"), 1)
        self.assertEqual(camelot_distance("8A", "8B"), 1)
        self.assertEqual(camelot_distance("12A", "1A"), 1)
        self.assertEqual(camelot_distance("2A", "8B"), 7)
        self.assertLess(camelot_mismatch("8A", "9A"), camelot_mismatch("8A", "11A"))


class TestCultureAndTags(unittest.TestCase):
    def test_culture_order(self):
        self.assertEqual(decide_culture("TR", {}, "Song", "X")[0], "tr")
        self.assertEqual(decide_culture("DE", {"arabesk": 0.8}, "Song", "X")[0], "tr")
        self.assertEqual(decide_culture(None, {}, "Gözlerin", "Ayşe")[0], "tr")
        self.assertEqual(decide_culture(None, {}, "Über", "Björk")[0], "global")  # ö/ü yetmez
        self.assertEqual(decide_culture("GB", {"rock": 1}, "Yellow", "Coldplay")[0], "global")

    def test_clean_and_split(self):
        tags = clean_tags({"Seen Live": 1, "Arabesk": 1, "sad": 0.6, "melancholic": 0.3, "x": 0.05})
        self.assertNotIn("seen live", tags)
        self.assertNotIn("x", tags)
        sub, moods = split_tags(tags)
        self.assertEqual(sub, ["arabesk"])
        self.assertEqual(set(moods), {"sad", "melancholic"})

    def test_mb_tags(self):
        t = MusicBrainzTags().get_tags("a", "b", MBInfo(tags={"rock": 4, "favorites": 9, "sad": 2}))
        self.assertEqual(t, {"rock": 1.0, "sad": 0.5})


class TestTokenBucket(unittest.TestCase):
    def test_rate(self):
        import time
        b = TokenBucket(5, 0.5)  # 0.5 sn'de 5 istek = 10/sn
        t0 = time.monotonic()
        for _ in range(15):
            b.acquire()
        self.assertGreater(time.monotonic() - t0, 0.9)  # ilk 5 hemen, sonraki 10 ~1 sn


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg yok")
class TestAnalysis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from make_test_audio import make_song, write_mp3
        cls.tmp = tempfile.mkdtemp()
        cls.files = {}
        for bpm, key, scale in [(120, "A", "minor"), (128, "F#", "minor"), (100, "G", "major")]:
            p = os.path.join(cls.tmp, f"{bpm}.mp3")
            write_mp3(make_song(bpm, key, scale), p)
            cls.files[(bpm, key, scale)] = p

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_tempo_key_vector(self):
        from muzikarsiv.analysis import analyze_file
        for (bpm, key, scale), path in self.files.items():
            r = analyze_file(path, "basic")
            ratio = r.bpm / bpm
            self.assertTrue(any(abs(ratio - m) < 0.03 for m in (0.5, 1, 2)), f"{bpm} -> {r.bpm}")
            self.assertEqual((r.musical_key, r.key_scale), (key, scale))
            self.assertEqual(len(r.feature_vec), 16)
            self.assertTrue(all(0 <= x <= 1 for x in r.feature_vec))
            self.assertTrue(0 <= r.energy <= 1)


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg yok")
class TestPipelineOffline(unittest.TestCase):
    """Deezer/MusicBrainz/Supabase taklitleriyle tüm akış: indir -> analiz -> sil -> satır -> kaydet."""

    def test_end_to_end(self):
        from make_test_audio import make_song, write_mp3

        tmpdir = tempfile.mkdtemp()
        src = os.path.join(tmpdir, "src.mp3")
        write_mp3(make_song(95, "D", "minor"), src)
        downloaded = []

        class FakeDeezer:
            def track(self, i):
                return {"id": i, "title": "Gül Pembe (feat. Biri)", "isrc": "TRA000000001", "duration": 245,
                        "rank": 500000, "preview": "https://x/preview.mp3",
                        "artist": {"id": 77, "name": "Barış Manço"}, "album": {"id": 5, "title": "Albüm"}}

            def album_genre(self, album_id):
                return "Pop"

            def download_preview(self, url):
                fd, p = tempfile.mkstemp(suffix=".mp3")
                os.close(fd)
                shutil.copy(src, p)
                downloaded.append(p)
                return p

        class FakeMB:
            def lookup_isrc(self, isrc):
                return MBInfo(recording_mbid="11111111-1111-1111-1111-111111111111",
                              artist_mbid="22222222-2222-2222-2222-222222222222", artist_country="TR",
                              tags={"anatolian rock": 5, "turkish": 3, "seen live": 9, "nostalgic": 2})

        class FakeDB:
            saved = []

            def find_duplicate(self, *a):
                return None

            def upsert_song(self, row):
                self.saved.append(row)
                return {"id": "uuid-1"}

        svc = Services(cfg=load_config(), deezer=FakeDeezer(), mb=FakeMB(), tags=MusicBrainzTags(), db=FakeDB())
        res = process_track(svc, 123, source="seed")
        row = res["row"]
        self.assertEqual(res["status"], "saved")
        self.assertFalse(os.path.exists(downloaded[0]), "geçici MP3 silinmeli")
        self.assertEqual(row["title_norm"], "gul pembe")
        self.assertEqual(row["artist_norm"], "baris manco")
        self.assertEqual(row["cultural_context"], "tr")
        self.assertIn("anatolian rock", row["sub_genres"])
        self.assertNotIn("seen live", row["mood_tags"])
        self.assertEqual(row["camelot"], "7A")
        self.assertTrue(row["feature_vec"].startswith("[") and row["feature_vec"].count(",") == 15)
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
