---
name: taskschd-qator-skrinshot
description: Task Scheduler (taskschd.msc) oynasida kerakli vazifa qatorini tanlab, ekran rasmini olish va Telegramga yuborish.
triggers: task scheduler, планировщик, skrinshot, screenshot, AgentRestart, avtozagruzka rasm
yaratilgan: 2026-11-04
yangilangan: 2026-11-04
versiya: 1
---

# taskschd-qator-skrinshot

## Qadamlar (qisman sinalgan)
1. mmc jarayonini top: `Get-Process mmc | Select Id,MainWindowTitle` (oynasi "Планировщик заданий"). Yo'q bo'lsa `Start-Process taskschd.msc`.
2. Faqat o'qish: vazifa holati `Get-ScheduledTask -TaskName AgentRestart`.
3. Oynani oldinga chiqar: user32 `ShowWindow(h,9)` + `SetForegroundWindow(h)` (Add-Type bilan).
4. Chap daraxtni bosish: `SetCursorPos(X+90,Y+120)` + `mouse_event(2/4)`; keyin SendKeys: `{HOME}`, `{DOWN}` (Библиотека), `{TAB}`, so'ng vazifa nomining boshini yoz (`AgentR`) — ro'yxatda type-ahead bilan qator tanlanadi.
5. Skrinshot: System.Drawing Bitmap + `CopyFromScreen` oyna BoundingRectangle bo'yicha, `ish\ekran2.png` ga saqla.
6. `notify_owner(file_path=...)` bilan yubor.

## Cheklovlar (haqiqiy tajriba)
- MMC oynasi UIAutomation'da deyarli bo'sh (faqat Pane'lar), daraxt va ro'yxat qatorlari ko'rinmaydi, shuning uchun SelectionItemPattern ishlamaydi.
- Qator tanlanganini dastur orqali tekshirib bo'lmadi; rasmni agent ko'ra olmaydi. Natijani Jamshidga tasdiqlatish kerak.
- Ishonchliroq muqobil: skrinshotga System.Drawing bilan qizil ramka chizish (qator koordinatasi kerak) yoki Windows OCR bilan qator joyini topish.
- Hech narsa o'chirilmaydi/o'zgartirilmaydi; vazifani o'chirish faqat Jamshid tasdig'i bilan.
