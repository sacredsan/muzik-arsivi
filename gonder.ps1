# Kodu GitHub'a gönderir (sacredsan/muzik-arsivi). gonder.bat çalıştırır.
# Güvenlik: .env veya şifre klasörü gönderilecekler arasında görünürse DURUR.

$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Log = Join-Path $PSScriptRoot "gonder_log.txt"
Start-Transcript -Path $Log -Force | Out-Null

function Fail($msg) { Write-Host "DURDURULDU: $msg" -ForegroundColor Red; Stop-Transcript | Out-Null; exit 1 }

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Fail "git bulunamadi" }

if (-not (Test-Path ".git")) {
    git init -b main | Out-Host
}
git config user.name "sacredsan"
git config user.email "sacredsan@users.noreply.github.com"
git config core.autocrlf false
git config core.quotepath false

git add -A
$files = git diff --cached --name-only
$all = (git ls-files) + $files
Write-Host "Gonderilecek dosyalar:"; $all | Sort-Object -Unique | ForEach-Object { Write-Host "  $_" }

# Güvenlik kontrolü
$bad = $all | Where-Object { $_ -match '(^|/)\.env$' -or $_ -match 'ifre' -or $_ -match 'secret' -or $_ -match '_log\.txt$' }
if ($bad) { git reset -q; Fail "gizli olabilecek dosya bulundu: $($bad -join ', ')" }
Write-Host "Guvenlik kontrolu: TAMAM (.env ve sifre klasoru yok)" -ForegroundColor Green

if ($files) {
    git commit -q -m "Guncelleme: $(Get-Date -Format 'yyyy-MM-dd HH:mm')" | Out-Host
}

$remote = git remote
if (-not ($remote -contains "origin")) {
    git remote add origin https://github.com/sacredsan/muzik-arsivi.git
}

Write-Host "`nGitHub'daki son degisiklikler aliniyor (ornegin web uzerinden eklenen dosyalar)..."
git -c rebase.autoStash=true pull --rebase origin main 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) { git rebase --abort 2>$null; Fail "GitHub ile birlestirme yapilamadi; Claude'a haber verin" }

Write-Host "`nGitHub'a gonderiliyor... (ilk seferde tarayicida GitHub girisi isteyebilir)"
git push -u origin main 2>&1 | Out-Host
if ($LASTEXITCODE -eq 0) { Write-Host "`nBASARILI: https://github.com/sacredsan/muzik-arsivi" -ForegroundColor Green }
else { Write-Host "`nGonderim basarisiz (cikis kodu $LASTEXITCODE)" -ForegroundColor Red }
Stop-Transcript | Out-Null
