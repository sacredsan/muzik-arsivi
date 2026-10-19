"""Kültürel bağlam (tr / global) kararı. Sıra: sanatçı ülkesi -> etiketler -> harf sezgisi."""

from __future__ import annotations

TR_TAGS = {
    "turkish", "turkce", "türkçe", "turkey", "türkiye", "turkiye", "arabesk", "arabesque",
    "turkish pop", "turkish rock", "turkish folk", "turkish rap", "turkish hip hop", "turkish hip-hop",
    "anatolian rock", "anadolu rock", "türkü", "turku", "fantezi", "türk sanat müziği",
    "turkish classical", "ozgun muzik", "özgün müzik", "halk muzigi", "halk müziği", "roman havasi",
}
# Türkçeye özgü harfler (ö/ü/ç Almanca vb. ile ortak olduğu için kullanılmaz)
TR_ONLY_CHARS = set("ıİğĞşŞ")


def decide_culture(country: str | None, tags: dict[str, float] | None,
                   title: str = "", artist: str = "") -> tuple[str, str]:
    """('tr' | 'global', gerekçe) döndürür."""
    if country:
        if country.upper() in ("TR", "CY"):
            return "tr", f"sanatçı ülkesi {country.upper()}"
    for t in tags or {}:
        if t.lower() in TR_TAGS:
            return "tr", f"etiket '{t}'"
    if TR_ONLY_CHARS & set(f"{title}{artist}"):
        return "tr", "ad/başlıkta Türkçe harf"
    if country:
        return "global", f"sanatçı ülkesi {country.upper()}"
    return "global", "Türk işareti bulunamadı"
