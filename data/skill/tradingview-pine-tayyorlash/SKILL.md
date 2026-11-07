---
name: tradingview-pine-tayyorlash
description: Savdo ssenariysidan (entry/SL/TP) tekshirilgan Pine v5 kod tayyorlash, dublikatsiz saqlash, clipboard va skrinshot+OCR orqali TradingView holatini rost tekshirish.
triggers: tradingview, pine, chizish, annotatsiya, entry, sl, tp, grafik, skrinshot
yaratilgan: 2026-11-06
yangilangan: 2026-11-06
versiya: 3
---

# tradingview-pine-tayyorlash

V2: endi agent tool'lari bor (agent kodida, holatni kod belgilaydi). skript/tv_pine.py — eski (birinchi) versiya,
ma'lumot uchun qoldirilgan; yangi ishda tool'larni ishlat.

1. tradingview_environment(device) — qurilma: "local" = asosiy noutbuk XS-NB-AUP06 (TradingView Desktop bor);
   nb-xs-tex02 — masofaviy, GUI yo'q -> NEEDS_SETUP. Noaniq bo'lsa egasidan so'ra.
2. tradingview_prepare — tahlil bazada bo'lsa analysis_id (TA-...) bilan; qo'lda ssenariy: id, symbol, timeframe,
   direction, entry, sl, tp[], strategy, version, created (ISO + vaqt mintaqasi), invalidation. Natija:
   data/trading_memory/pine/<TICKER>_<TF>_<ID>.pine (ustiga yozilmaydi, dublikat yaratilmaydi), clipboard, yo'riqnoma.
   open_chart=web — brauzerda to'g'ri simvol/taymfreym URL (klik yo'q). Holat: PARTIAL.
3. Egasi: Pine Editor -> barcha matn -> qo'yish -> Add to chart.
4. tradingview_verify(scenario_id, device, window=auto) — TradingView Desktop VA brauzer (Chrome/Edge, faqat faol
   yorliq; begona sahifa rasmi o'chiriladi), har oyna alohida. O'z skrinshot skriptini yozma (skript/chrome_shot_ocr.py
   — eski). PrintWindow + RapidOCR. Dalil: simulyatsiya
   belgisi, ID, barcha "SIM ..." darajalar va indikatorning o'zi yozgan "Chart matches scenario" (instrument +
   taymfreym). OCR legendada 1h ni 1y deb o'qishi mumkin — moslik dalili shu yozuvdan. Indikator 2 marta qo'shilsa —
   dublikat ogohlantirishi. SUCCESS faqat shu yerdan.
5. Hech qachon oyna sarlavhasidan yoki Pine fayl yaratilganidan grafik o'zgardi deb xulosa qilma.
