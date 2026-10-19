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
        self.assertEqual(moods, {"sad": 0.6})  # sad + melancholic -> tek "sad"
        # sanatçı adı ve ülke/dil etiketleri mood sayılmaz
        _, moods = split_tags({"sezen aksu": 1.0, "turkish": 1.0, "melancholic": 0.5}, "Sezen Aksu")
        self.assertEqual(moods, {"sad": 0.5})

    def test_combined_tags(self):
        from muzikarsiv.sources.tags import CombinedTags

        class A:
            name = "a"

            def get_tags(self, *x):
                return {"sad": 1.0, "pop": 0.5}

        class B:
            name = "b"

            def get_tags(self, *x):
                return {"pop": 1.0, "chill": 0.5}

        c = CombinedTags([A(), B()], [1.0, 0.7])
        self.assertEqual(c.name, "a+b")
        self.assertEqual(c.get_tags("x", "y", None), {"sad": 1.0, "pop": 0.7, "chill": 0.35})

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
        self.assertEqual(row["mood_tags"], {"nostalgic": 0.4})  # standart mood adı
        self.assertIn("turkish", row["tags"])                    # ham etiketler korunur
        self.assertEqual(row["camelot"], "7A")
        for k in ("danceability", "mood_valence", "mood_arousal"):
            self.assertTrue(0 <= row[k] <= 1, k)
        self.assertTrue(70 <= row["bpm"] < 180)
        self.assertTrue(row["feature_vec"].startswith("[") and row["feature_vec"].count(",") == 15)
        shutil.rmtree(tmpdir, ignore_errors=True)


class TestAgent(unittest.TestCase):
    """Toplu ajan: başarılı, tekrar, kalıcı hata, geçici hata, zaman sınırı, tarama."""

    def _svc(self, outcomes, pending=0, crawled=()):
        from muzikarsiv import agent
        from muzikarsiv.sources import PermanentError

        class DB:
            def __init__(self):
                self.log, self.enqueued, self.marked = [], [], []

            def start_run(self, w):
                return 1

            def finish_run(self, *a):
                self.log.append(("finish",) + a[1:4])

            def claim_jobs(self, n, w):
                return [{"id": i, "deezer_id": d, "source": "seed"} for i, d in enumerate(outcomes)][:n]

            def pending_count(self):
                return pending

            def outdated_songs(self, version, limit):
                return []

            def complete_job(self, jid, note=None):
                self.log.append(("complete", jid, note))

            def fail_job(self, jid, err, permanent=False):
                self.log.append(("fail", jid, permanent))
                return "failed" if permanent else "pending"

            def release_jobs(self, ids):
                self.log.append(("release", tuple(ids)))
                return len(ids)

            def artist_crawled(self, aid):
                return aid in crawled

            def enqueue(self, items, priority, source):
                self.enqueued += items
                return len(items)

            def mark_artist_crawled(self, aid, name, rel):
                self.marked.append((aid, tuple(rel)))

        class DZ:
            def artist_related(self, aid, limit):
                return [{"id": 900, "name": "Benzer"}]

            def artist_top(self, aid, limit):
                return [{"id": aid * 10, "title": "x", "preview": "p", "artist": {"name": "a"}},
                        {"id": aid * 10 + 1, "title": "y", "preview": "", "artist": {"name": "a"}}]

        def fake_process(svc, did, source):
            kind = outcomes[did]
            if kind == "dup":
                return {"status": "duplicate"}
            if kind == "perm":
                raise PermanentError("önizleme yok")
            if kind == "boom":
                raise ValueError("ses çözülemedi")
            return {"status": "saved", "row": {"artist_name": "A", "track_name": "T", "bpm": 120,
                                               "camelot": "8A", "key_scale": "minor", "energy": .5,
                                               "danceability": .5, "cultural_context": "tr",
                                               "artist_id": 50}}

        agent.process_track = fake_process
        cfg = load_config()
        svc = Services(cfg=cfg, deezer=DZ(), mb=None, tags=None, db=DB())
        return agent, svc

    def test_outcomes(self):
        agent, svc = self._svc({0: "ok", 1: "dup", 2: "perm", 3: "boom"})
        st = agent.run_batch(svc, batch_size=10, budget_sec=60)
        self.assertEqual((st.processed, st.skipped, st.failed), (1, 1, 2))
        log = svc.db.log
        self.assertIn(("complete", 0, None), log)
        self.assertIn(("complete", 1, "arşivde zaten var"), log)
        self.assertIn(("fail", 2, True), log)    # kalıcı -> DLQ
        self.assertIn(("fail", 3, False), log)   # geçici -> tekrar denenecek
        self.assertEqual(log[-1], ("finish", 1, 2, 1))
        # tarama: sanatçı 50 + benzer 900, önizlemesi olmayanlar eklenmez
        self.assertEqual(sorted(i["deezer_id"] for i in svc.db.enqueued), [500, 9000])
        self.assertEqual(svc.db.marked, [(50, (900,))])

    def test_budget_releases_rest(self):
        agent, svc = self._svc({0: "ok", 1: "ok", 2: "ok"})
        st = agent.run_batch(svc, batch_size=10, budget_sec=-1)  # süre baştan dolmuş
        self.assertEqual(st.processed, 0)
        self.assertIn(("release", (0, 1, 2)), svc.db.log)

    def test_crawl_brake_and_no_repeat(self):
        agent, svc = self._svc({0: "ok"}, pending=10_000)
        st = agent.run_batch(svc, batch_size=10, budget_sec=60)
        self.assertEqual(st.crawled, 0)              # kuyruk dolu: tarama yok
        agent, svc = self._svc({0: "ok"}, crawled=(50,))
        st = agent.run_batch(svc, batch_size=10, budget_sec=60)
        self.assertEqual(st.crawled, 0)              # zaten taranmış sanatçı

    def test_artist_match(self):
        from muzikarsiv.pipeline import artist_matches
        self.assertTrue(artist_matches("Barış Manço", "Baris Manco"))
        self.assertTrue(artist_matches("Bob Marley", "Bob Marley & The Wailers"))
        self.assertFalse(artist_matches("Mabel Matiz", "Mert Demir"))
        self.assertFalse(artist_matches("Adele", "The Drum & Bass Remixers"))


class TestSearchAndMoodFixes(unittest.TestCase):
    def test_skips_remix(self):
        from types import SimpleNamespace
        from muzikarsiv.pipeline import find_track

        class DZ:
            def search(self, q, limit):
                return [{"id": 1, "title": "Everyway That I Can (Special Bubbling Mix)", "preview": "p",
                         "artist": {"name": "Sertab Erener"}},
                        {"id": 2, "title": "Everyway That I Can", "preview": "p",
                         "artist": {"name": "Sertab Erener"}}]
        hit = find_track(SimpleNamespace(deezer=DZ()), "Sertab Erener", "Everyway That I Can")
        self.assertEqual(hit["id"], 2)

    def test_low_vote_moods_survive(self):
        from muzikarsiv.sources.tags import CombinedTags, split_tags

        class LF:
            name = "lf"

            def get_tags(self, *a):  # Last.fm tipik dağılım: türler çok oy, mood'lar az oy
                return {"pop": 1.0, "turkish pop": 0.6, "sad": 0.05, "melancholic": 0.04}
        tags = CombinedTags([LF()], [1.0]).get_tags("a", "b", None)
        sub, moods = split_tags(tags, "a")
        self.assertEqual(moods, {"sad": 0.05})
        self.assertEqual(sub, ["pop", "turkish pop"])


class TestStage2Features(unittest.TestCase):
    def test_fold_and_mood(self):
        from muzikarsiv.analysis.features import fold_bpm, mood_scores
        self.assertEqual(fold_bpm(63), 126)
        self.assertEqual(fold_bpm(190), 95)
        self.assertEqual(fold_bpm(171), 171)
        happy = mood_scores(0.9, 0.9, "major", 0.9, 125)
        sad = mood_scores(0.2, 0.2, "minor", 0.9, 70)
        self.assertGreater(happy[0], sad[0])
        self.assertGreater(happy[1], sad[1])

    def test_mood_vocab_turkish(self):
        from muzikarsiv.sources.tags import split_tags
        _, moods = split_tags({"hüzünlü": 0.8, "melancholic": 0.5, "aşk": 0.4, "pop": 1.0})
        self.assertEqual(moods, {"sad": 0.8, "romantic": 0.4})


if __name__ == "__main__":
    unittest.main(verbosity=2)
