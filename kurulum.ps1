# Müzik Arşivi - Windows kurulum betiği
# kurulum.bat'a çift tıklayınca çalışır. Tekrar çalıştırmak güvenlidir (kurulu olanları atlar).
# Her şey kurulum_log.txt dosyasına yazılır.

$ErrorActionPreference = "Continue"
$Root = $PSScriptRoot
Set-Location $Root
$Log = Join-Path $Root "kurulum_log.txt"
$Venv = Join-Path $env:USERPROFILE ".venvs\muzikarsiv"   # OneDrive DIŞINDA
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

Set-Content -Path $Log -Value "=== Kurulum basladi: $(Get-Date -Format s) ===" -Encoding UTF8

function Say($msg) {
    Write-Host $msg -ForegroundColor Cyan
    Add-Content -Path $Log -Value $msg -Encoding UTF8
}

function Run($exe) {
    # Bir programı çalıştırır, çıktısını hem ekrana hem günlüğe yazar
    $cmdArgs = $args
    Add-Content -Path $Log -Value "> $exe $($cmdArgs -join ' ')" -Encoding UTF8
    & $exe @cmdArgs 2>&1 | ForEach-Object {
        $line = "$_"
        Write-Host $line
        Add-Content -Path $Log -Value $line -Encoding UTF8
    }
    Add-Content -Path $Log -Value "[cikis kodu: $LASTEXITCODE]" -Encoding UTF8
    return $LASTEXITCODE
}

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User") + ";" +
                (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links")
}

function Find-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in "3.13", "3.12", "3.11") {
            $p = & py "-$v" -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $p) { return "$p".Trim() }
        }
    }
    foreach ($v in "313", "312", "311") {
        $p = Join-Path $env:LOCALAPPDATA "Programs\Python\Python$v\python.exe"
        if (Test-Path $p) { return $p }
    }
    return $null
}

function Winget-Install($id) {
    Say "-> $id kuruluyor (winget)..."
    Run winget install -e --id $id --silent --accept-package-agreements --accept-source-agreements | Out-Null
    Refresh-Path
}

# ---------------------------------------------------------------- 1) Programlar
Say "`n[1/6] Gerekli programlar kontrol ediliyor"
Refresh-Path
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Say "HATA: winget bulunamadi. Microsoft Store'dan 'Uygulama Yukleyicisi' (App Installer) guncellenmeli."
}

$py = Find-Python
if (-not $py) { Winget-Install "Python.Python.3.12"; $py = Find-Python }
if ($py) { Say "Python: $py"; Run $py --version | Out-Null } else { Say "HATA: Python 3.11+ bulunamadi." }

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { Winget-Install "Gyan.FFmpeg" }
if (Get-Command ffmpeg -ErrorAction SilentlyContinue) { Say "ffmpeg: VAR ($((Get-Command ffmpeg).Source))" }
else { Say "HATA: ffmpeg kurulamadi." }

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Winget-Install "Git.Git" }
if (Get-Command git -ErrorAction SilentlyContinue) { Say "git: VAR" } else { Say "UYARI: git kurulamadi (Asama 4'e kadar gerekmez)." }

if (-not $py) { Say "Python olmadan devam edilemiyor."; exit 1 }

# ---------------------------------------------------------------- 2) Sanal ortam
Say "`n[2/6] Sanal ortam: $Venv"
$vpy = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $vpy)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $Venv) | Out-Null
    Run $py -m venv $Venv | Out-Null
}
if (-not (Test-Path $vpy)) { Say "HATA: sanal ortam olusturulamadi."; exit 1 }

# ---------------------------------------------------------------- 3) Paketler
Say "`n[3/6] Python paketleri yukleniyor (birkac dakika surebilir)"
Run $vpy -m pip install --upgrade pip --disable-pip-version-check -q | Out-Null
Run $vpy -m pip install -r requirements.txt --disable-pip-version-check -q | Out-Null
Run $vpy -m pip install librosa --disable-pip-version-check -q | Out-Null

# ---------------------------------------------------------------- 4) Ayar dosyası
Say "`n[4/6] .env dosyasi"
if (-not (Test-Path (Join-Path $Root ".env"))) {
    Copy-Item (Join-Path $Root ".env.example") (Join-Path $Root ".env")
    Say ".env olusturuldu (Supabase bilgileri daha sonra doldurulacak)."
} else { Say ".env zaten var, dokunulmadi." }

# ---------------------------------------------------------------- 5) Testler
Say "`n[5/6] Testler"
$t = Run $vpy -m unittest discover tests -v
Run $vpy -m muzikarsiv check | Out-Null

# ---------------------------------------------------------------- 6) Gerçek Deezer denemesi
Say "`n[6/6] Gercek Deezer sarkisi ile analiz (veritabanina yazmadan)"
Run $vpy -m muzikarsiv search "sezen aksu gidiyorum" --limit 3 | Out-Null
Run $vpy -m muzikarsiv analyze 3135556 --no-db | Out-Null

Say "`n=== Kurulum bitti: $(Get-Date -Format s) ==="
Say "Sanal ortami acmak icin: $Venv\Scripts\Activate.ps1"
