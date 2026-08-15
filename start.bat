@echo off
REM Launch LiveWhisper with no console window. Quit from the tray icon.
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" run.py
