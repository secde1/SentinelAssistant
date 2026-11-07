---
name: strategiya-backtest-tadqiqot
description: 7 strategiyani 5 yillik tarixda xarajat bilan statistik tekshirish (IS/OOS, WFA, MTF, filtrlar, korrelyatsiya).
triggers: backtest, strategiya, walk-forward, OOS, dukascopy, binance tarix
yaratilgan: 2026-11-07
yangilangan: 2026-11-07
versiya: 1
---

# strategiya-backtest-tadqiqot

1. Ma'lumot: skript/bt_fetch.py (Binance klines BTC/ETH H1+M15; Yahoo 2y zaxira). Forex/oltin/indekslar: `npx --yes dukascopy-node -i xauusd|eurusd|gbpusd|usatechidxusd|usa500idxusd -from 2021-01-01 -to <sana> -t h1 -f csv -v true -dir ish\bt\duka` (usa500 da 'fetch failed' bo'lsa qayta uring).
2. skript/bt_engine.py [aktiv...] -> ish/bt/trades_*.csv (7 strategiya, 1h va 4h, xarajat, MFE/MAE, rejim, MTF, filtr belgilari).
3. skript/bt_wfa.py -> grid_all.csv, wfa_results.csv (rr x sl_scale, anchored WFA).
4. skript/bt_analyze.py -> Strategiya_tadqiqot.xlsx; skript/bt_report.py -> docx.
Saboq: limit buyurtma to'lgan shamda TP ni sanamang (intrabar tartib noma'lum) - aks holda soxta foyda chiqadi (MS-BOS misoli). Xarajatlar R birligida: cost_px/risk.
