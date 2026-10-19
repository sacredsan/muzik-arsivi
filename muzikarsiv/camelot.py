"""Ton (key) <-> Camelot çarkı dönüşümü ve uyum mesafesi."""

from __future__ import annotations

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_ALIASES = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#",
            "Cb": "B", "Fb": "E", "E#": "F", "B#": "C"}


def pitch_class(note: str) -> int:
    n = note.strip()
    n = n[0].upper() + n[1:]
    n = _ALIASES.get(n, n)
    return NOTE_NAMES.index(n)


def to_camelot(note: str, scale: str) -> str:
    """('A','minor') -> '8A', ('C','major') -> '8B'"""
    pc = pitch_class(note)
    if scale.lower().startswith("min"):
        pc = (pc + 3) % 12  # paralel majörün çark numarası aynı
        letter = "A"
    else:
        letter = "B"
    num = (pc * 7 + 8) % 12 or 12
    return f"{num}{letter}"


def parse_camelot(code: str) -> tuple[int, str]:
    return int(code[:-1]), code[-1].upper()


def camelot_distance(a: str, b: str) -> int:
    """0 = aynı ton, 1 = uyumlu komşu (±1 veya A/B geçişi), büyüdükçe uyumsuz (en çok 7)."""
    n1, l1 = parse_camelot(a)
    n2, l2 = parse_camelot(b)
    d = abs(n1 - n2) % 12
    d = min(d, 12 - d)
    return d + (0 if l1 == l2 else 1)


def camelot_mismatch(a: str | None, b: str | None) -> float:
    """Öneri skoru için 0..1 uyumsuzluk (ton bilinmiyorsa nötr 0.5)."""
    if not a or not b:
        return 0.5
    d = camelot_distance(a, b)
    return 0.0 if d == 0 else 0.15 if d == 1 else min(1.0, 0.15 + (d - 1) * 0.17)
