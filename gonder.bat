@echo off
chcp 65001 >nul
echo Kod GitHub'a gonderiliyor (sacredsan/muzik-arsivi)...
echo GitHub giris penceresi acilirsa "Sign in with your browser" secip onaylayin.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0gonder.ps1"
echo.
echo Bitti. Claude'a "bitti" yazabilirsiniz.
pause
