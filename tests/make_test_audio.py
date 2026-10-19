"""Bilinen tempo ve tonda sentetik test şarkısı (MP3) üretir. İnternet gerektirmez.

Kullanım: python tests/make_test_audio.py cikti.mp3 120 A minor
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import wave

import numpy as np

SR = 44100
NOTES = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def _tone(freq, dur, amp=0.12):
    t = np.arange(int(SR * dur)) / SR
    wave_ = sum(amp / h * np.sin(2 * np.pi * freq * h * t) for h in range(1, 5))
    env = np.minimum(1, t * 20) * np.minimum(1, (dur - t) * 10)
    return wave_ * env


def make_song(bpm: float, key: str, scale: str, seconds: float = 30, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    y = np.zeros(n)
    beat = 60 / bpm
    root = NOTES[key]
    steps = [0, 4, 7] if scale == "major" else [0, 3, 7]
    # i - iv - v - i ilerlemesi (ton tespiti için)
    degrees = [0, 5, 7, 0]
    bar = 4 * beat
    for b in range(int(seconds / bar) + 1):
        start = int(b * bar * SR)
        deg = degrees[b % 4]
        sub = steps if not (scale == "minor" and deg == 7) else [0, 4, 7]
        for s in sub:
            midi = 60 + (root + deg + s) % 12
            seg = _tone(440 * 2 ** ((midi - 69) / 12), bar)
            y[start:start + len(seg)] += seg[: max(0, n - start)]
        bass = _tone(440 * 2 ** ((36 + (root + deg) % 12 - 69) / 12), bar, 0.2)
        y[start:start + len(bass)] += bass[: max(0, n - start)]
    t_k = np.arange(int(0.15 * SR)) / SR
    kick = np.sin(2 * np.pi * (50 + 70 * np.exp(-t_k * 30)) * t_k) * np.exp(-t_k * 18) * 0.9
    snare = rng.normal(0, 0.35, int(0.12 * SR)) * np.exp(-np.arange(int(0.12 * SR)) / SR * 30)
    hat = rng.normal(0, 0.12, int(0.04 * SR)) * np.exp(-np.arange(int(0.04 * SR)) / SR * 120)
    i = 0
    while (pos := int(i * beat / 2 * SR)) < n:
        if i % 2 == 0:
            y[pos:pos + len(kick)] += kick[: n - pos]
            if (i // 2) % 2 == 1:
                y[pos:pos + len(snare)] += snare[: n - pos]
        y[pos:pos + len(hat)] += hat[: n - pos]
        i += 1
    return (y / np.abs(y).max() * 0.8).astype(np.float32)


def write_mp3(y: np.ndarray, path: str) -> None:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav = f.name
    with wave.open(wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((y * 32767).astype(np.int16).tobytes())
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", wav, "-b:a", "128k", path], check=True)


if __name__ == "__main__":
    out, bpm, key, scale = sys.argv[1], float(sys.argv[2]), sys.argv[3], sys.argv[4]
    write_mp3(make_song(bpm, key, scale), out)
    print(f"{out}: {bpm} BPM, {key} {scale}")
