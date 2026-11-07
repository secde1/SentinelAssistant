---
name: narx-alert-telegram
description: Крипто нарх даражаларига теккanda Telegram (Saved Messages) га автомат хабар: Task Scheduler + Telethon.
triggers: 
yaratilgan: 2026-11-06
yangilangan: 2026-11-06
versiya: 1
---

# narx-alert-telegram

1. skript/btc_alert.py: даражалар (ENTRY/SL/TP1/TP2) ва ҳолат машинаси WAIT->ENTERED->CLOSED; data-api.binance.vision 1m свечалар (high/low билан, wick қолмайди).
2. api_id/api_hash ish/tg_env.json га inventar placeholder орқали ёзилади (utf-8-sig билан ўқилади, BOM муаммоси). Парол скриптда йўқ.
3. Хабар: Telethon send_message('me') сессия ish/tg_session орқали.
4. Task Scheduler: Register-ScheduledTask BTC-SHORT-Alert, ҳар 1 дақиқа, pythonw.exe, IgnoreNew. Ҳолат ish/btc_alert_state.json.
5. Текширув: Get-ScheduledTaskInfo LastTaskResult=0, state last_ts ўзгаради.
Ўчириш: Unregister-ScheduledTask BTC-SHORT-Alert. Эслатма: Saved Messages'га push келмаслиги мумкин.
