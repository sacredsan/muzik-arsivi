#!/usr/bin/env bash
# essentia'yı kaynak koddan derler (hazır pip paketi olmayan ARM/aarch64 sunucular için).
# Docker paketinin içinde, root olarak çalışır. Yalnız temel algoritmalar derlenir
# (eğitilmiş modeller yok; ses çözme ffmpeg komutuyla yapıldığı için libav* gerekmez).
set -euxo pipefail

apt-get update
apt-get install -y --no-install-recommends build-essential git pkg-config \
  libeigen3-dev libfftw3-dev libyaml-dev libsamplerate0-dev libtag1-dev
pip install six pyyaml

cd /tmp
git clone --depth 1 https://github.com/MTG/essentia.git
cd essentia
git log -1 --format='essentia kaynak: %H (%cs)'
python3 waf configure --mode=release --with-python
python3 waf -j"$(nproc)"
python3 waf install
ldconfig

cd /
rm -rf /tmp/essentia
apt-get purge -y build-essential git pkg-config
apt-get autoremove -y
rm -rf /var/lib/apt/lists/*

python3 -c "import essentia, essentia.standard as es; es.RhythmExtractor2013; es.KeyExtractor; es.Danceability; print('essentia derlendi:', essentia.__version__)"
