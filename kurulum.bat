@echo off
chcp 65001 >nul
echo Muzik Arsivi kurulumu basliyor. Pencereyi kapatmayin...
echo Windows "degisiklik yapilsin mi" diye sorarsa "Evet" deyin.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0kurulum.ps1"
echo.
echo Bitti. Sonuclar kurulum_log.txt dosyasinda. Claude'a "bitti" yazabilirsiniz.
pause
