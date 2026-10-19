"""Tempo, ton ve dans edilebilirlik arka uçları: essentia (en iyi) -> librosa -> basic (numpy yedek)."""

from __future__ import annotations

import importlib.util

import numpy as np

from .features import basic_key, danceability_heuristic, pulse_and_tempo


def available() -> list[str]:
    out = []
    if importlib.util.find_spec("essentia"):
        out.append("essentia")
    if importlib.util.find_spec("librosa"):
        out.append("librosa")
    out.append("basic")
    return out


def pick(requested: str = "auto") -> str:
    avail = available()
    if requested == "auto":
        return avail[0]
    if requested not in avail:
        raise RuntimeError(f"ANALYZER={requested} kurulu değil. Kurulu olanlar: {', '.join(avail)}")
    return requested


def tempo_key(name: str, y: np.ndarray, sr: int, desc: dict) -> dict:
    """{'bpm', 'bpm_conf', 'key', 'scale', 'key_conf', 'danceability'} döndürür."""
    if name == "essentia":
        return _essentia(y, sr)
    if name == "librosa":
        return _librosa(y, sr, desc)
    return _basic(desc)


def _basic(desc: dict) -> dict:
    bpm, clarity = pulse_and_tempo(desc)
    key, scale, kconf = basic_key(desc["chroma"])
    return {"bpm": bpm, "bpm_conf": round(min(1.0, clarity * 1.5), 3),
            "key": key, "scale": scale, "key_conf": kconf,
            "danceability": danceability_heuristic(desc, bpm, clarity)}


def _essentia(y: np.ndarray, sr: int) -> dict:
    # Yalnız temel DSP algoritmaları; eğitilmiş model kullanılmaz (lisans).
    import essentia.standard as es

    audio = y.astype(np.float32)
    bpm, _beats, beats_conf, _, _ = es.RhythmExtractor2013(method="multifeature")(audio)
    key, scale, strength = es.KeyExtractor(sampleRate=sr, profileType="bgate")(audio)
    dance, _dfa = es.Danceability(sampleRate=sr)(audio)  # yaklaşık 0..3 aralığı
    return {"bpm": float(bpm), "bpm_conf": round(float(min(1.0, beats_conf / 5.32)), 3),
            "key": key, "scale": scale, "key_conf": round(float(strength), 3),
            "danceability": round(float(np.clip(dance / 3.0, 0, 1)), 4)}


def _librosa(y: np.ndarray, sr: int, desc: dict) -> dict:
    import librosa

    tempo, _ = librosa.beat.beat_track(y=y, sr=sr, hop_length=512)
    bpm = float(np.atleast_1d(tempo)[0])
    _, clarity = pulse_and_tempo(desc)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr).mean(axis=1)
    key, scale, kconf = basic_key(chroma / (chroma.sum() + 1e-10))
    return {"bpm": bpm, "bpm_conf": round(min(1.0, clarity * 1.5), 3),
            "key": key, "scale": scale, "key_conf": kconf,
            "danceability": danceability_heuristic(desc, bpm, clarity)}
