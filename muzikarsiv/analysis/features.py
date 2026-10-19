"""Arka uçtan bağımsız ortak ölçümler (yalnız numpy/scipy).

- describe(): tını, ritim ve ton profili ölçümleri
- energy_score(): 0..1 enerji
- feature_vector(): 16 boyutlu, 0..1 aralığına sabitlenmiş vektör (öneri benzerliği için)
- basic_tempo() / basic_key(): essentia ve librosa yoksa kullanılan yedek algoritmalar

NOT: Normalize aralıkları (lo, hi) ilk tahmindir; Aşama 2'de gerçek veriyle kalibre edilecek,
değişirse ANALYSIS_VERSION artırılır.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import find_peaks

FRAME = 2048
HOP = 512
EPS = 1e-10

FEATURE_NAMES = [
    "centroid_mean", "centroid_std", "rolloff_mean", "flatness_mean",
    "zcr_mean", "loudness_db", "loudness_var_db", "flux_mean",
    "onset_rate", "pulse_clarity", "band_low", "band_mid",
    "band_high", "chroma_entropy", "mode_major", "tempo_norm",
]

# Krumhansl-Schmuckler ton profilleri
_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _scale(x: float, lo: float, hi: float) -> float:
    return float(np.clip((x - lo) / (hi - lo), 0.0, 1.0))


def _frames(y: np.ndarray) -> np.ndarray:
    n = 1 + (len(y) - FRAME) // HOP
    idx = np.arange(FRAME)[None, :] + HOP * np.arange(n)[:, None]
    return y[idx]


def describe(y: np.ndarray, sr: int) -> dict:
    """Tüm ortak ölçümleri tek geçişte hesaplar."""
    frames = _frames(y)
    mag = np.abs(np.fft.rfft(frames * np.hanning(FRAME), axis=1))
    power = mag ** 2
    freqs = np.fft.rfftfreq(FRAME, 1 / sr)
    mag_sum = mag.sum(axis=1) + EPS
    total_power = power.sum(axis=1) + EPS

    # Ses yüksekliği (kare ortalamanın karekökü)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    rms_db = 20 * np.log10(rms + 1e-6)
    active = rms_db > rms_db.max() - 40  # sessiz kısımları dışla

    centroid = (mag * freqs).sum(axis=1) / mag_sum
    cum = np.cumsum(power, axis=1)
    rolloff = freqs[np.argmax(cum >= 0.85 * cum[:, -1:], axis=1)]
    flatness = np.exp(np.log(power + EPS).mean(axis=1)) / (power.mean(axis=1) + EPS)
    zcr = np.abs(np.diff(np.signbit(frames), axis=1)).mean(axis=1)

    # Spektral akış = başlangıç (onset) zarfı
    logmag = np.log1p(100 * mag / (mag.max() + EPS))
    flux = np.maximum(0, np.diff(logmag, axis=0)).mean(axis=1)
    fps = sr / HOP
    env = flux - np.convolve(flux, np.ones(int(fps * 0.5)) / int(fps * 0.5), mode="same")
    env = np.maximum(env, 0)
    peaks, _ = find_peaks(env, height=env.mean() + env.std(), distance=max(1, int(fps * 0.07)))
    duration = len(y) / sr

    low = power[:, freqs < 250].sum(axis=1)
    high = power[:, freqs >= 4000].sum(axis=1)
    mid = total_power - low - high

    # Kroma (12 perde sınıfı) profili: 65 Hz - 2100 Hz arası
    band = (freqs >= 65) & (freqs <= 2100)
    midi = 69 + 12 * np.log2(freqs[band] / 440.0)
    pcs = np.round(midi).astype(int) % 12
    bmag = mag[active][:, band].sum(axis=0)
    chroma = np.bincount(pcs, weights=bmag, minlength=12)
    chroma = chroma / (chroma.sum() + EPS)
    chroma_entropy = float(-(chroma * np.log(chroma + EPS)).sum() / np.log(12))

    a = active
    return {
        "sr": sr,
        "duration": duration,
        "fps": fps,
        "onset_env": env,
        "chroma": chroma,
        "centroid_mean": float(centroid[a].mean()),
        "centroid_std": float(centroid[a].std()),
        "rolloff_mean": float(rolloff[a].mean()),
        "flatness_mean": float(flatness[a].mean()),
        "zcr_mean": float(zcr[a].mean()),
        "loudness_db": float(20 * np.log10(rms[a].mean() + 1e-6)),
        "loudness_var_db": float(rms_db[a].std()),
        "flux_mean": float(flux[a[1:]].mean()),
        "onset_rate": len(peaks) / duration,
        "band_low": float(low[a].sum() / total_power[a].sum()),
        "band_mid": float(mid[a].sum() / total_power[a].sum()),
        "band_high": float(high[a].sum() / total_power[a].sum()),
        "chroma_entropy": chroma_entropy,
    }


def _autocorr(env: np.ndarray) -> np.ndarray:
    x = env - env.mean()
    n = 1 << (2 * len(x) - 1).bit_length()
    f = np.fft.rfft(x, n)
    ac = np.fft.irfft(f * np.conj(f))[: len(x)]
    return ac / (ac[0] + EPS)


def pulse_and_tempo(desc: dict, lo: float = 60, hi: float = 200) -> tuple[float, float]:
    """Otokorelasyonla tempo tahmini. (bpm, ritim netliği 0..1) döndürür."""
    ac = _autocorr(desc["onset_env"])
    fps = desc["fps"]
    lags = np.arange(len(ac))
    bpms = np.arange(lo, hi + 0.01, 0.25)
    lag = 60 * fps / bpms

    def at(l):
        return np.interp(l, lags, ac, right=0)

    support = at(lag) + 0.5 * at(2 * lag) + 0.25 * at(4 * lag)
    prior = np.exp(-0.5 * (np.log2(bpms / 120) / 1.0) ** 2)
    best = int(np.argmax(support * prior))
    clarity = float(np.clip(at(lag[best]), 0, 1))
    return float(bpms[best]), clarity


def basic_key(chroma: np.ndarray) -> tuple[str, str, float]:
    """Krumhansl yöntemiyle ton. (nota, 'major'/'minor', güven 0..1)"""
    scores = []
    for scale, prof in (("major", _MAJOR), ("minor", _MINOR)):
        for k in range(12):
            r = np.corrcoef(chroma, np.roll(prof, k))[0, 1]
            scores.append((r, NOTE_NAMES[k], scale))
    scores.sort(reverse=True)
    best, second = scores[0], scores[1]
    conf = float(np.clip(best[0], 0, 1) * np.clip((best[0] - second[0]) * 5 + 0.5, 0, 1))
    return best[1], best[2], round(conf, 3)


def energy_score(desc: dict) -> float:
    """0..1 enerji: ses yüksekliği (%50) + spektral akış (%30) + vuruş yoğunluğu (%20)."""
    e = (0.5 * _scale(desc["loudness_db"], -30, -6)
         + 0.3 * _scale(desc["flux_mean"], 0.002, 0.03)
         + 0.2 * _scale(desc["onset_rate"], 0.5, 6.0))
    return round(float(e), 4)


def feature_vector(desc: dict, bpm: float, scale: str, pulse_clarity: float) -> list[float]:
    folded = bpm
    while folded > 140:
        folded /= 2
    while folded < 70:
        folded *= 2
    v = [
        _scale(desc["centroid_mean"], 300, 5000),
        _scale(desc["centroid_std"], 0, 2500),
        _scale(desc["rolloff_mean"], 1000, 12000),
        _scale(desc["flatness_mean"], 0, 0.5),
        _scale(desc["zcr_mean"], 0, 0.25),
        _scale(desc["loudness_db"], -30, -6),
        _scale(desc["loudness_var_db"], 0, 12),
        _scale(desc["flux_mean"], 0.002, 0.03),
        _scale(desc["onset_rate"], 0, 8),
        float(np.clip(pulse_clarity, 0, 1)),
        float(np.clip(desc["band_low"], 0, 1)),
        float(np.clip(desc["band_mid"], 0, 1)),
        float(np.clip(desc["band_high"], 0, 1)),
        float(np.clip(desc["chroma_entropy"], 0, 1)),
        1.0 if scale == "major" else 0.0,
        _scale(folded, 70, 140),
    ]
    assert len(v) == len(FEATURE_NAMES) == 16
    return [round(x, 4) for x in v]
