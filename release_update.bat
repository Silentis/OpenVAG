@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe release.py
pause