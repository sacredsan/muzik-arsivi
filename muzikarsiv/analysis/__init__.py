"""Tek giriş noktası: analyze_file(yol) -> AnalysisResult"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .. import ANALYSIS_VERSION
from ..camelot import to_camelot
from . import backends
from .audio_io import SAMPLE_RATE, load_audio
from .features import FEATURE_NAMES, describe, energy_score, feature_vector, pulse_and_tempo


@dataclass
class AnalysisResult:
    bpm: float
    bpm_conf: float
    musical_key: str
    key_scale: str
    key_conf: float
    camelot: str
    energy: float
    feature_vec: list[float]
    analyzer: str
    analysis_version: int
    seconds_analyzed: float

    def to_dict(self) -> dict:
        return asdict(self)


def analyze_file(path: str, analyzer: str = "auto") -> AnalysisResult:
    name = backends.pick(analyzer)
    y = load_audio(path, SAMPLE_RATE)
    desc = describe(y, SAMPLE_RATE)
    tk = backends.tempo_key(name, y, SAMPLE_RATE, desc)
    _, clarity = pulse_and_tempo(desc)
    return AnalysisResult(
        bpm=round(tk["bpm"], 2),
        bpm_conf=tk["bpm_conf"],
        musical_key=tk["key"],
        key_scale=tk["scale"],
        key_conf=tk["key_conf"],
        camelot=to_camelot(tk["key"], tk["scale"]),
        energy=energy_score(desc),
        feature_vec=feature_vector(desc, tk["bpm"], tk["scale"], clarity),
        analyzer=name,
        analysis_version=ANALYSIS_VERSION,
        seconds_analyzed=round(desc["duration"], 1),
    )


__all__ = ["analyze_file", "AnalysisResult", "FEATURE_NAMES"]
