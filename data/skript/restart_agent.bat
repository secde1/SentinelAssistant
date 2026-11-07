@echo off
rem Eski nom saqlangan. Agentni qayta ishga tushiradi, 25 soniya kutib: agent buni o'zi chaqirganda javobini
rem yuborib ulgurishi uchun. Asl boshqaruv: D:\it-agent\agentctl.cmd (status, start, stop, restart, logs).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\agentctl.ps1" restart -Delay 25
