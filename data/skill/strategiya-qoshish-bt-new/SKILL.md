---
name: strategiya-qoshish-bt-new
description: Backtest tizimiga yangi strategiya qo'shish (eski natijalarga tegmasdan).
triggers: strategiya qo'shish, backtest, trendline, SNR, sweep
yaratilgan: 2026-11-07
yangilangan: 2026-11-07
versiya: 1
---

# strategiya-qoshish-bt-new

1. skript/bt_new.py: NEW ro'yxati, E.VALID/E.FIXED_RR.update, build() ichida yangi qoidalar (BANK-SWEEP, TL-BOUNCE, TL-BREAK, SNR-REJ, SNR-FLIP).
2. Ishga tushirish: python bt_new.py (7 aktiv, ~1 daqiqa) -> ish/bt/trades_<aktiv>_<tf>_new.csv.
3. python bt_analyze.py va bt_report.py: glob trades_*.csv yangilarini ham oladi -> xlsx/docx qayta yoziladi.
4. verify_artifact(require_labels=strategiya nomlari), notify_owner(file).
Saboq: signal sham yopilgach, buyurtma keyingi shamdan; pivot 3 sham keyin tasdiqlanadi.
