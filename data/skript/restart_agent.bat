@echo off
rem Botni qayta ishga tushiradi: eski "-m agent" jarayonlarini to'xtatadi, yangisini ochadi.
rem Chaqirish: schtasks /run /tn AgentRestart
timeout /t 25 /nobreak >nul
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python' -and $_.CommandLine -match '-m agent' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
timeout /t 3 /nobreak >nul
cd /d D:\it-agent
rem Konsol chiqishi (kutilmagan xato traceback'i ham) console.log ga yoziladi - oyna yopilsa ham yo'qolmaydi.
set PYTHONUNBUFFERED=1
set PYTHONFAULTHANDLER=1
rem Python chiqsa - chiqish kodi yoziladi (oyna qo'lda yopilsa bu qator yozilmaydi).
start "" /min cmd /v:on /c ""D:\it-agent\.venv\Scripts\python.exe" -m agent >> "D:\it-agent\data\jurnal\console.log" 2>&1 & echo !date! !time! python chiqdi, kod=!errorlevel! >> "D:\it-agent\data\jurnal\console.log""
echo %date% %time% restart >> D:\it-agent\data\jurnal\restart.log
