@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0arrancar_windows.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo [ERROR] El lanzador termino con codigo %RC%.
exit /b %RC%
