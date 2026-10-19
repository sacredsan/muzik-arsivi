# Müzik arşivi ajanı — tek imaj, her yerde: Cloud Run Jobs, Oracle VM, yerel Docker.
# Gizli anahtarlar imaja GİRMEZ; çalışırken ortam değişkeni olarak verilir.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ANALYZER=auto TAG_PROVIDER=auto

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# essentia: x86_64'te hazır paket var. ARM'da (Oracle Ampere) kurulamazsa librosa yedeğine düşülür.
RUN pip install -r requirements.txt \
    && (pip install essentia || pip install librosa) \
    && python -c "import importlib.util as u; print('motor:', 'essentia' if u.find_spec('essentia') else 'librosa')"

COPY muzikarsiv ./muzikarsiv
COPY scripts ./scripts

# Güvenlik: root olmayan kullanıcı
RUN useradd -m ajan
USER ajan

# Varsayılan: tek tur (Cloud Run Jobs için). Sürekli mod: docker run ... run --loop
ENTRYPOINT ["python", "-m", "muzikarsiv"]
CMD ["run"]
