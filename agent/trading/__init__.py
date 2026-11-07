"""SENTINAL — Trading Research (V16): bozor tahlili, QOG'OZ savdo (paper trading) va strategiya tadqiqoti.

FAQAT tadqiqot va simulyatsiya: haqiqiy pul bilan savdo YO'Q, broker/birja buyurtma API'siga ulanish YO'Q, broker
login/kalitlari saqlanmaydi. Bozor ma'lumoti faqat ochiq, ruxsat etilgan manbalardan (Binance ochiq market-data API,
ixtiyoriy Twelve Data kaliti, CSV); narx yoki indikator O'YLAB TOPILMAYDI — ma'lumot bo'lmasa tahlil ham bo'lmaydi.

Tarkib:
  settings.py   — trading_memory/config/research_settings.json (instrumentlar, jadval, xarajat modeli)
  db.py         — trading_memory/database/trading_research.db (asosiy manba; tahlillar o'zgarmas)
  data.py       — OHLCV provayderlar va ma'lumot sifati tekshiruvi
  indicators.py, regime.py, strategies.py — indikatorlar, bozor rejimi, versiyali strategiyalar kutubxonasi
  analysis.py   — tahlil (TRADE yoki NO-TRADE) yaratish
  outcomes.py   — qog'oz savdo natijasini kuzatish (PENDING ... TP_HIT/SL_HIT/AMBIGUOUS_DATA)
  analytics.py, review.py, backtest.py — statistika, SL tahlili, eksperimentlar (IS/OOS, xarajat bilan)
  publish.py, report.py, research.py, scheduler.py — Telegram, kunlik hisobot, tadqiqot, jadval
"""
