@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PY=%USERPROFILE%\.venvs\muzikarsiv\Scripts\python.exe
echo Last.fm etiketleri test ediliyor (veritabanina yazmadan)...
(
  echo === Last.fm testi: %date% %time% ===
  "%PY%" -m muzikarsiv check
  for %%I in (3518914151 3135556 66134321) do (
    echo.
    echo --- sarki %%I ---
    "%PY%" -m muzikarsiv analyze %%I --no-db --force
  )
) > lastfm_test_log.txt 2>&1
type lastfm_test_log.txt
echo.
echo Bitti. Claude'a "bitti" yazabilirsiniz.
pause
