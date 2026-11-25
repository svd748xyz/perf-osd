@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYW=pythonw.exe"
where pythonw.exe >nul 2>&1 || set "PYW=python.exe"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p='%~dp0main.py'; Start-Process -FilePath '%PYW%' -ArgumentList ('\"'+$p+'\" --elevate') -Verb RunAs"
exit /b
