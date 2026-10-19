#!/usr/bin/env bash
# Google Cloud kurulumu (Cloud Shell'de çalıştırılır). Tekrar çalıştırmak güvenlidir.
#   1) servisleri açar  2) gizli anahtar kutularını hazırlar  3) yetkileri verir
#   4) Docker paketini derleyip Cloud Run işi olarak kurar  5) saatlik zamanlama  6) ilk turu çalıştırır
# Gizli anahtar DEĞERLERİ bu betikte yoktur; kullanıcı Secret Manager ekranından ekler.
set -euo pipefail
PROJECT=$(gcloud config get-value project 2>/dev/null)
REGION=europe-west1
JOB=muzik-ajan
SCHED=muzik-ajan-saatlik
SECRETS="SUPABASE_URL SUPABASE_SERVICE_KEY LASTFM_API_KEY"
cd "$(dirname "$0")/.."

echo "== [1/6] Servisler açılıyor (proje: $PROJECT, bölge: $REGION)"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  cloudscheduler.googleapis.com secretmanager.googleapis.com

NUM=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
SA="$NUM-compute@developer.gserviceaccount.com"

echo "== [2/6] Gizli anahtar kutuları"
for s in $SECRETS; do
  gcloud secrets describe "$s" >/dev/null 2>&1 || gcloud secrets create "$s" --replication-policy=automatic
done
missing=""
for s in $SECRETS; do
  if [ -z "$(gcloud secrets versions list "$s" --filter='state=enabled' --format='value(name)' 2>/dev/null)" ]; then
    missing="$missing $s"
  fi
done
if [ -n "$missing" ]; then
  echo
  echo "############################################################"
  echo "EKSIK ANAHTAR:$missing"
  echo "Secret Manager ekranından bu anahtarların değerlerini ekleyin,"
  echo "sonra bu betiği tekrar çalıştırın."
  echo "############################################################"
  exit 2
fi

echo "== [3/6] Yetkiler (ajan hesabı: $SA)"
for role in roles/secretmanager.secretAccessor roles/run.invoker roles/cloudbuild.builds.builder \
            roles/artifactregistry.writer roles/storage.objectViewer roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" --role="$role" \
    --condition=None -q >/dev/null
done

echo "== [4/6] Docker paketi derleniyor ve Cloud Run işi kuruluyor (birkaç dakika sürer)"
gcloud run jobs deploy "$JOB" --source . --region "$REGION" \
  --tasks 1 --max-retries 0 --task-timeout 900s --cpu 1 --memory 1Gi \
  --service-account "$SA" \
  --set-env-vars "ANALYZER=essentia,TAG_PROVIDER=auto,WORKER_NAME=cloudrun,BATCH_SIZE=50,RUN_BUDGET_SEC=720,MB_USER_AGENT=MuzikArsivi/0.2 ( https://github.com/sacredsan/muzik-arsivi )" \
  --set-secrets "SUPABASE_URL=SUPABASE_URL:latest,SUPABASE_SERVICE_KEY=SUPABASE_SERVICE_KEY:latest,LASTFM_API_KEY=LASTFM_API_KEY:latest" \
  -q

echo "== [5/6] Saatlik zamanlama (her saatin 13. dakikası, İstanbul saati)"
URI="https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/jobs/$JOB:run"
if gcloud scheduler jobs describe "$SCHED" --location "$REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "$SCHED" --location "$REGION" --schedule "13 * * * *" \
    --time-zone "Europe/Istanbul" --uri "$URI" --http-method POST --oauth-service-account-email "$SA" -q
else
  gcloud scheduler jobs create http "$SCHED" --location "$REGION" --schedule "13 * * * *" \
    --time-zone "Europe/Istanbul" --uri "$URI" --http-method POST --oauth-service-account-email "$SA" -q
fi

echo "== [6/6] İlk tur şimdi çalıştırılıyor (5-7 dakika)"
gcloud run jobs execute "$JOB" --region "$REGION" --wait && echo "ILK_TUR_BASARILI" || echo "ILK_TUR_HATALI"
echo
echo "KURULUM_BITTI"
