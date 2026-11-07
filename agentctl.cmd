@echo off
rem SENTINAL AI boshqaruvi: agentctl status ^| start ^| stop ^| restart ^| autostart on/off ^| logs ^| install
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0agentctl.ps1" %*
