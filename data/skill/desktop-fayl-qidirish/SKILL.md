---
name: desktop-fayl-qidirish
description: Jamshidning Desktop papkasidagi fayllarni (masalan PDF) topish va o'qishga tayyorlash.
triggers: desktop, ish stoli, рабочий стол, pdf, fayl qidirish, файл топ
yaratilgan: 2026-10-24
yangilangan: 2026-10-24
versiya: 1
---

# desktop-fayl-qidirish

1. $env:USERPROFILE\Desktop BO'SH natija berishi mumkin (agent boshqa profilda ishlaydi). To'g'ri yo'l: C:\Users\A.ABDULLAYEV\Desktop (OneDrive\Desktop yo'q).
2. Ro'yxat: Get-ChildItem "C:\Users\A.ABDULLAYEV\Desktop" -Force | Select Name,Length,LastWriteTime | Out-String
3. PDF qidirish (ichki papkalar bilan): Get-ChildItem "C:\Users\A.ABDULLAYEV\Desktop" -Recurse -Filter *.pdf -ErrorAction SilentlyContinue | Select FullName,Length,LastWriteTime
4. PDF topilsa: read_file(path=<to'liq yo'l>) matnini chiqaradi, undan qisqa xulosa yoziladi.
5. PDF topilmasa: Downloads (C:\Users\A.ABDULLAYEV\Downloads) ni tekshirib, qaysi fayl kerakligini Jamshiddan so'rash.
Xato: bo'sh natijani "fayl yo'q" deb bo'lmaydi - avval papka mavjudligini Test-Path bilan tekshir.
