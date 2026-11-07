---
name: avto-skaner-zdelka-savoli
description: Kripto kuchli kirish signalini avtomat topib Telegramga 'zdelka ochaymi?' deb xabar yuborish.
triggers: skaner, avto, signal, zdelka ochaymi, scan, alert
yaratilgan: 2026-11-07
yangilangan: 2026-11-07
versiya: 1
---

# avto-skaner-zdelka-savoli

1. Skript: skript/auto_scan_alert.py (Binance data-api.binance.vision, 10 kripto, 4h+1h trend + 15m kirish, ball>=5/6, SL 1.5 ATR, TP 2.25 ATR, 4 soat cooldown, holat ish/auto_scan_state.json).
2. Sinov: python auto_scan_alert.py --dry (yubormaydi).
3. Task Scheduler: Register-ScheduledTask Auto-Scan-Alert, har 15 daqiqa, pythonw.exe, IgnoreNew.
4. Xabar Telethon orqali Saved Messages ga (api_id/hash ish/tg_env.json, utf-8-sig).
5. Zdelka o'zi ochilmaydi: Jamshid 'ha' desa trading_mt5_order check->open (tasdiq bilan).
6. Tekshiruv: Get-ScheduledTaskInfo LastTaskResult=0. O'chirish: Unregister-ScheduledTask Auto-Scan-Alert.
Eslatma: LTC/BNB MT5 demoda Trade disabled, DOGE ma'lumoti eski.
