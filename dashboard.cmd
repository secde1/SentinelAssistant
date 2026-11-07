@echo off
rem SENTINAL CONTROL CENTER - mahalliy veb-dashboard (faqat 127.0.0.1, faqat o'qish).
rem Brauzer token bilan o'zi ochiladi. To'xtatish: shu oynani yoping yoki Ctrl+C.
rem   dashboard.cmd --no-browser   - faqat server
title SENTINAL Control Center
cd /d "%~dp0"
if not exist "web\out\index.html" echo Web UI build qilinmagan: cd web ^&^& npm ci ^&^& npm run build
".venv\Scripts\python.exe" -m agent.dashboard %*
if errorlevel 1 pause
