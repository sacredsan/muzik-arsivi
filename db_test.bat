@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PY=%USERPROFILE%\.venvs\muzikarsiv\Scripts\python.exe
echo Veritabani baglantisi test ediliyor...
(
  echo === DB testi: %date% %time% ===
  "%PY%" -m muzikarsiv check
  echo.
  echo --- Daft Punk analiz edilip Supabase'e kaydediliyor ---
  "%PY%" -m muzikarsiv analyze 3135556
  echo.
  echo --- Ayni sarki tekrar: arsivde var demeli ---
  "%PY%" -m muzikarsiv analyze 3135556
  echo.
  echo --- Turkce ornek: Sezen Aksu - Gidiyorum ---
  "%PY%" -m muzikarsiv analyze 3518914151
) > db_test_log.txt 2>&1
type db_test_log.txt
echo.
echo Bitti. Claude'a "bitti" yazabilirsiniz.
pause
