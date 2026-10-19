"""Ses dosyasını ffmpeg ile mono float32 diziye çevirir (her platformda aynı sonuç)."""

from __future__ import annotations

import shutil
import subprocess

import numpy as np

SAMPLE_RATE = 44100


def load_audio(path: str, sr: int = SAMPLE_RATE, max_seconds: float | None = 60) -> np.ndarray:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg bulunamadı. Kurulum: README'deki 'ffmpeg kurulumu' bölümü.")
    cmd = [ffmpeg, "-v", "error", "-nostdin", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(sr)]
    if max_seconds:
        cmd += ["-t", str(max_seconds)]
    cmd.append("-")
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise ValueError(f"ses çözülemedi: {proc.stderr.decode(errors='ignore')[:300]}")
    y = np.frombuffer(proc.stdout, dtype=np.float32).copy()
    if y.size < sr * 5:
        raise ValueError(f"ses çok kısa ({y.size / sr:.1f} sn)")
    return y
