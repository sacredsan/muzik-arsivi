# Müzik arşivi ajanı — tek imaj, her yerde: Cloud Run Jobs, Oracle VM (ARM veya x86), yerel Docker.
# Gizli anahtarlar imaja GİRMEZ; çalışırken ortam değişkeni olarak verilir.
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ANALYZER=essentia TAG_PROVIDER=auto

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
COPY scripts/build_essentia.sh /tmp/build_essentia.sh
# essentia: x86_64'te hazır paket kurulur; hazır paket yoksa (ARM, ör. Oracle Ampere) kaynaktan derlenir.
# İkisi de olmazsa derleme HATA verir: farklı motorla tutarsız veri üretmektense durmak daha iyi.
RUN pip install -r requirements.txt \
    && (pip install essentia || bash /tmp/build_essentia.sh) \
    && python -c "import essentia; print('essentia', essentia.__version__)" \
    && rm -f /tmp/build_essentia.sh

COPY muzikarsiv ./muzikarsiv
COPY scripts ./scripts

# Güvenlik: root olmayan kullanıcı
RUN useradd -m ajan
USER ajan

# Varsayılan: tek tur (Cloud Run Jobs için). Sürekli mod: docker run ... run --loop
ENTRYPOINT ["python", "-m", "muzikarsiv"]
CMD ["run"]
