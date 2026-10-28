@echo off
rem Ustki panel (oynacha) - ekran tepasidagi boshqaruv oynasi.
rem Agent xizmati ishlab turganda oching (python -m agent). Konsolsiz, pythonw bilan.
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m agent.panel
