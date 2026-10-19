# Müzik Arşivi ve Analiz Ajanları

SmartFlow2 uygulamasının şarkı önerileri için kendi müzik analiz arşivimiz.
Ajan, Deezer'ın 30 saniyelik önizlemelerini indirir, BPM / ton (Camelot) / enerji / özellik vektörü
çıkarır, etiketleri ekler ve Supabase'e kaydeder. Ses dosyası hiçbir zaman saklanmaz.

Projenin tüm kuralları ve yol haritası: **CLAUDE.md**

## Klasör yapısı

```
muzik-arsivi/
├─ CLAUDE.md                 proje talimatı ve aşamalar
├─ README.md                 bu dosya
├─ .env.example              ayar şablonu (kopyalayıp .env yapılır)
├─ requirements.txt          Python paketleri
├─ supabase/migrations/      veritabanı kurulum SQL'leri (sırayla çalıştırılır)
├─ muzikarsiv/               ajanın Python kodu
│  ├─ analysis/              ses analizi (BPM, ton, enerji, vektör)
│  ├─ sources/               Deezer, MusicBrainz, Last.fm
│  ├─ pipeline.py            bir şarkının baştan sona işlenmesi
│  └─ cli.py                 komut satırı
└─ tests/                    testler
```

## Kurulum (Windows, adım adım)

### 1) Gerekli programlar
PowerShell'i açın ve sırayla:

```powershell
winget install Python.Python.3.12
winget install Gyan.FFmpeg
winget install Git.Git
```
Kurulumdan sonra PowerShell'i **kapatıp yeniden açın**. Kontrol:
```powershell
python --version
ffmpeg -version
```

### 2) Proje klasöründe sanal ortam
```powershell
cd "$env:USERPROFILE\OneDrive\Masaüstü\müzikanalizdata\muzik-arsivi"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install librosa
```
> "Activate.ps1 çalıştırılamıyor" hatası alırsanız bir kez şunu çalıştırın:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

Her yeni PowerShell penceresinde yalnızca `.\.venv\Scripts\Activate.ps1` satırını tekrar çalıştırmanız yeterli.

### 3) Supabase veritabanı
1. https://supabase.com adresinde ücretsiz bir proje açın (bölge: Frankfurt / eu-central önerilir).
2. Sol menüden **SQL Editor**'ü açın.
3. `supabase/migrations` klasöründeki dosyaları **sırayla** (0001 → 0004) açın, içeriğini yapıştırıp **Run** deyin.
4. **Project Settings → API Keys** sayfasından proje adresini (URL) ve **secret** (veya eski adıyla service_role) anahtarını alın.

### 4) Ayar dosyası
`.env.example` dosyasını kopyalayıp adını `.env` yapın, içini doldurun:
```powershell
copy .env.example .env
notepad .env
```

### 5) Çalıştırma
```powershell
python -m muzikarsiv check                       # her şey hazır mı?
python -m muzikarsiv search "sezen aksu gidiyorum"   # Deezer ID bul
python -m muzikarsiv analyze 3135556 --no-db     # sadece ekrana yaz
python -m muzikarsiv analyze 3135556             # analiz et ve Supabase'e kaydet
python -m muzikarsiv analyze-file sarki.mp3      # yerel dosya (internetsiz)
```

### 6) Testler
```powershell
python -m unittest discover tests -v
```

## Analiz motorları
| Motor | Nerede | Not |
|---|---|---|
| essentia | Linux / Docker (sunucu) | En isabetli. Windows'ta kurulamaz. AGPL lisans: sunucuda kalır. |
| librosa | Windows (yerel geliştirme) | `pip install librosa` |
| basic | Her yer | Sadece numpy/scipy; yedek |

`ANALYZER=auto` en iyisini kendisi seçer. 16 boyutlu özellik vektörü her motorda aynı kodla hesaplanır.

## Lisans ve hukuki notlar
CLAUDE.md §9'a bakın (Deezer şartları, Last.fm ticari kullanım, Essentia AGPL, MusicBrainz).
