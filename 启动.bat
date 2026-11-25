@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYW=pythonw.exe"
where pythonw.exe >nul 2>&1 || set "PYW=python.exe"
start "" %PYW% "%~dp0main.py"
exit /b
