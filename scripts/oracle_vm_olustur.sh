#!/usr/bin/env bash
# Oracle Cloud Shell'de çalışır: ücretsiz (Always Free) bir sunucu oluşturur.
#   Önce Ampere ARM (2 çekirdek, 12 GB) dener; tüm bölgelerde kapasite yoksa AMD Micro'ya (x86) düşer.
#   Ağ (VCN, internet geçidi, alt ağ) yoksa oluşturur. Tekrar çalıştırmak güvenlidir.
set -euo pipefail
C="${OCI_TENANCY:?OCI_TENANCY yok - bu betik Oracle Cloud Shell icinde calistirilmali}"
NAME=muzik-ajan
q() { oci "$@" --raw-output 2>/dev/null || true; }

echo "== [1/5] SSH anahtari (Cloud Shell -> sunucu baglantisi icin)"
[ -f ~/.ssh/id_ed25519 ] || ssh-keygen -q -t ed25519 -N '' -f ~/.ssh/id_ed25519

echo "== [2/5] Ag"
VCN=$(q network vcn list -c "$C" --display-name muzik-vcn --query 'data[0].id')
if [ -z "$VCN" ] || [ "$VCN" = "null" ]; then
  VCN=$(oci network vcn create -c "$C" --cidr-blocks '["10.0.0.0/16"]' --display-name muzik-vcn \
        --wait-for-state AVAILABLE --query data.id --raw-output)
fi
IGW=$(q network internet-gateway list -c "$C" --vcn-id "$VCN" --query 'data[0].id')
if [ -z "$IGW" ] || [ "$IGW" = "null" ]; then
  IGW=$(oci network internet-gateway create -c "$C" --vcn-id "$VCN" --is-enabled true --display-name muzik-igw \
        --wait-for-state AVAILABLE --query data.id --raw-output)
fi
RT=$(oci network vcn get --vcn-id "$VCN" --query 'data."default-route-table-id"' --raw-output)
oci network route-table update --rt-id "$RT" --force \
  --route-rules "[{\"destination\":\"0.0.0.0/0\",\"destinationType\":\"CIDR_BLOCK\",\"networkEntityId\":\"$IGW\"}]" >/dev/null
SUB=$(q network subnet list -c "$C" --vcn-id "$VCN" --display-name muzik-subnet --query 'data[0].id')
if [ -z "$SUB" ] || [ "$SUB" = "null" ]; then
  SUB=$(oci network subnet create -c "$C" --vcn-id "$VCN" --cidr-block 10.0.0.0/24 --display-name muzik-subnet \
        --wait-for-state AVAILABLE --query data.id --raw-output)
fi

echo "== [3/5] Mevcut sunucu kontrolu"
ID=$(q compute instance list -c "$C" --display-name "$NAME" --lifecycle-state RUNNING --query 'data[0].id')

launch() {  # $1=shape $2=image $3=AD $4=shape-config(json veya bos)
  local extra=()
  [ -n "$4" ] && extra=(--shape-config "$4")
  oci compute instance launch -c "$C" --availability-domain "$3" --shape "$1" "${extra[@]}" \
    --image-id "$2" --subnet-id "$SUB" --assign-public-ip true --display-name "$NAME" \
    --ssh-authorized-keys-file ~/.ssh/id_ed25519.pub --boot-volume-size-in-gbs 50 \
    --wait-for-state RUNNING --query data.id --raw-output
}

if [ -z "$ID" ] || [ "$ID" = "null" ]; then
  echo "== [4/5] Sunucu olusturuluyor"
  ADS=$(oci iam availability-domain list -c "$C" --query 'data[].name' --raw-output | tr -d '[]", ' | grep -v '^$')
  IMG_ARM=$(oci compute image list -c "$C" --operating-system "Canonical Ubuntu" --operating-system-version "24.04" \
            --shape VM.Standard.A1.Flex --sort-by TIMECREATED --query 'data[0].id' --raw-output)
  for AD in $ADS; do
    echo "   Ampere ARM deneniyor: $AD"
    if ID=$(launch VM.Standard.A1.Flex "$IMG_ARM" "$AD" '{"ocpus":2,"memoryInGBs":12}' 2>/tmp/launch.err); then break; fi
    grep -o '"message": "[^"]*"' /tmp/launch.err | head -1 || true
    ID=""
  done
  if [ -z "$ID" ]; then
    echo "   Ampere kapasitesi yok; AMD Micro (x86) deneniyor"
    IMG_X86=$(oci compute image list -c "$C" --operating-system "Canonical Ubuntu" --operating-system-version "24.04" \
              --shape VM.Standard.E2.1.Micro --sort-by TIMECREATED --query 'data[0].id' --raw-output)
    for AD in $ADS; do
      echo "   AMD Micro deneniyor: $AD"
      if ID=$(launch VM.Standard.E2.1.Micro "$IMG_X86" "$AD" "" 2>/tmp/launch.err); then break; fi
      grep -o '"message": "[^"]*"' /tmp/launch.err | head -1 || true
      ID=""
    done
  fi
  [ -n "$ID" ] || { echo "SUNUCU_OLUSTURULAMADI (kapasite yok, daha sonra tekrar deneyin)"; exit 1; }
else
  echo "== [4/5] Sunucu zaten var, yeniden olusturulmuyor"
fi

echo "== [5/5] Bilgiler"
SHAPE=$(oci compute instance get --instance-id "$ID" --query 'data.shape' --raw-output)
IP=$(oci compute instance list-vnics --instance-id "$ID" --query 'data[0]."public-ip"' --raw-output)
echo "$IP" > ~/muzik_ip.txt
echo "SUNUCU_HAZIR  tip=$SHAPE  ip=$IP"
echo "Baglanmak icin: ssh ubuntu@\$(cat ~/muzik_ip.txt)"
