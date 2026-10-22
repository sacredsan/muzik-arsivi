#!/usr/bin/env bash
# Oracle sunucusunda (Ubuntu) ajanı 7/24 çalışacak şekilde kurar. Tekrar çalıştırmak güvenlidir
# (kodu günceller, paketi yeniden derler, ajanı yeniden başlatır; gizli anahtarları tekrar sormaz).
#
# Kullanım (sunucuda):  bash <(curl -fsSL https://raw.githubusercontent.com/sacredsan/muzik-arsivi/main/scripts/oracle_kurulum.sh)
set -euo pipefail
REPO=https://github.com/sacredsan/muzik-arsivi
DIR="$HOME/muzik-arsivi"
ENVF=/etc/muzikarsiv.env
NAME=muzik-ajan

echo "== [1/5] Docker ve git kuruluyor"
sudo apt-get update -qq
sudo apt-get install -y -qq docker.io git >/dev/null
sudo systemctl enable --now docker

echo "== [2/5] Kod indiriliyor / güncelleniyor"
if [ -d "$DIR/.git" ]; then git -C "$DIR" pull -q; else git clone -q "$REPO" "$DIR"; fi

echo "== [3/5] Gizli anahtarlar"
if sudo test -s "$ENVF"; then
  echo "Anahtar dosyası zaten var ($ENVF), tekrar sorulmuyor."
else
  echo "Yapıştırdığınız anahtarlar EKRANDA GÖRÜNMEZ (güvenlik için). Yapıştırıp Enter'a basın."
  read -rsp "SUPABASE_SERVICE_KEY (sb_secret_...): " K; echo
  read -rsp "LASTFM_API_KEY: " L; echo
  [ -n "$K" ] || { echo "HATA: Supabase anahtarı boş"; exit 1; }
  printf 'SUPABASE_URL=https://icedddkahnftbqlhznpn.supabase.co\nSUPABASE_SERVICE_KEY=%s\nLASTFM_API_KEY=%s\n' "$K" "$L" \
    | sudo tee "$ENVF" >/dev/null
  sudo chmod 600 "$ENVF"
  unset K L
  echo "Anahtarlar $ENVF dosyasına kaydedildi (yalnız yönetici okuyabilir)."
fi

echo "== [4/5] Docker paketi derleniyor (ARM'da essentia derlendiği için 15-30 dk sürebilir)"
sudo docker build -t muzikarsiv "$DIR"

echo "== [5/5] Ajan başlatılıyor (sürekli mod, sunucu yeniden başlarsa kendiliğinden açılır)"
sudo docker rm -f "$NAME" >/dev/null 2>&1 || true
sudo docker run -d --name "$NAME" --restart unless-stopped --env-file "$ENVF" --ulimit nofile=65536:65536 \
  -e WORKER_NAME="oracle-$(uname -m)" -e ANALYZER=essentia -e TAG_PROVIDER=auto -e BATCH_SIZE=30 \
  -e MB_USER_AGENT="MuzikArsivi/0.2 ( https://github.com/sacredsan/muzik-arsivi )" \
  --log-opt max-size=10m --log-opt max-file=3 \
  muzikarsiv run --loop >/dev/null
sleep 60
sudo docker logs --tail 15 "$NAME"
echo
echo "ORACLE_KURULUM_BITTI  (canlı günlük için: sudo docker logs -f $NAME)"
