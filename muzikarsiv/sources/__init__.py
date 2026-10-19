"""Dış veri kaynakları (Deezer, MusicBrainz, etiket sağlayıcıları)."""


class PermanentError(RuntimeError):
    """Tekrar denemenin anlamı olmayan hata (şarkı yok, önizleme yok...)."""
