"""Ad normalizasyonu: tekrar kayıt kontrolü ve bulanık arama için.

SQL'deki public.tr_norm() ile aynı kuralı uygular (ek olarak feat./remaster temizliği yapar).
"""

from __future__ import annotations

import re
import unicodedata

_TR_MAP = str.maketrans({
    "ı": "i", "İ": "i", "I": "i",
    "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
    "ö": "o", "Ö": "o", "ü": "u", "Ü": "u",
    "ç": "c", "Ç": "c", "â": "a", "Â": "a",
    "î": "i", "Î": "i", "û": "u", "Û": "u",
})

_FEAT = re.compile(r"[\(\[]\s*(feat\.?|ft\.?|featuring|with)\b[^\)\]]*[\)\]]", re.I)
_FEAT_TAIL = re.compile(r"\s+(feat\.?|ft\.?|featuring)\s+.*$", re.I)
_REMASTER = re.compile(
    r"\s*([-–]\s*|[\(\[]\s*)(\d{4}\s+)?(remaster(ed)?|digitally remastered)(\s+(version|\d{4}))?\s*[\)\]]?\s*$",
    re.I,
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def norm(text: str | None, strip_extras: bool = True) -> str:
    """'Gülüm (feat. X) - 2011 Remaster' -> 'gulum'"""
    s = text or ""
    if strip_extras:
        s = _FEAT.sub(" ", s)
        s = _FEAT_TAIL.sub("", s)
        s = _REMASTER.sub("", s)
    s = s.translate(_TR_MAP).lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return _NON_ALNUM.sub(" ", s).strip()


def norm_artist(text: str | None) -> str:
    return norm(text, strip_extras=False)
