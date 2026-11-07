---
name: tradingview-desktop-holat
description: TradingView Desktop oynasi holatini xavfsiz (faqat o'qish) tekshirish va Pine kodni qo'lda qo'yish uchun tayyorlash.
triggers: tradingview, treading view, pine, grafik, chiziq, sl tp
yaratilgan: 2026-11-06
yangilangan: 2026-11-06
versiya: 1
---

# tradingview-desktop-holat

1. Oynani topish (o'qish): Get-Process | Where MainWindowTitle -ne '' | Select Id,ProcessName,MainWindowTitle. TradingView sarlavhasida joriy simvol va narx chiqadi (masalan XAUUSD ...).
2. UI Automation (System.Windows.Automation, ControlType.TabItem) bilan tablarni o'qishga urinish: TradingView'da 0 ta natija qaytdi, ya'ni ichki elementlar ko'rinmaydi.
3. Pine kod buferda turibdimi: Get-Clipboard -Raw. Kod hline(narx, "nom") ko'rinishida SL, KIRISH, TP1, TP2 chiziqlarini chizadi.
4. SendKeys bilan kor-korona simvol almashtirmang: oynani yopib yuborgan. Agent grafikni ko'rmaydi.
5. Foydalanuvchiga qo'lda qadamlar: qidiruvga simvol yozib Enter; pastdan Pine Editor; Ctrl+A, Ctrl+V; Add to chart.
6. Tekshiruv: oyna sarlavhasida kerakli simvol (masalan BTCUSDT) chiqqanini verify bilan o'qish. Chiziqlar chizilganini sarlavha isbotlamaydi.
