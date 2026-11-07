# Doimiy faktlar

> Bir marta aytilgan doimiy ma'lumot.

## STT
- [2026-10-26] STT sinov halqasi: skript/stt_loop_test.py (TTS audio yaratadi) + skript/stt_loop_run.py (Transcriber orqali, natija ish/stt_test/natija.txt). 2026-10-26: univoice 6 jumlada o'rtacha ~0.96 o'xshashlik; xatolar texnik atamalarda (Zabbix, Spooler, ESXi, UniFi). stt.py da IT_GLOSSARY/apply_glossary post-correction qo'shildi (bot qayta ishga tushgach kuchga kiradi).

## Rasmiy xatlar (XONSAROY GROUP)
- [2026-10-30] [2026-10-30] Xat namunasi (Jamshid rasmi): sarlavha markazda qalin "XONSAROY GROUP" MCHJ 14pt, ostida to'liq chiziq; keyin ~4 qator bo'sh joy; chapda 2026 yil “____” _______dagi / №________-sonli (bo'sh, “ ” tirnoq); o'ngda qabul qiluvchi (oxirgi qator qalin "...ga"); markazda qalin "Hurmatli ...!"; matn krasnaya stroka, justify; "Hurmat bilan,"; pastda imzo: chapda qalin "Direktor", o'rtada ______ (imzo) (muhr), o'ngda ______ (F.I.SH.). Skript: skript/xat_saidkosimov.py — keyingi xatlarni shu maketda qil.
- [2026-10-30] [2026-10-30] Rasmiy xat qoidasi: Word (.docx), Times New Roman 14pt, interval 1.15, hoshiya chap 3sm/o'ng 1.5sm/yuqori-pastki 2sm, A4 bitta sahifa. Tuzilishi: markazda qalin "XONSAROY GROUP" MCHJ; chapda "2026 yil «__» ________ № ____"; o'ngda qabul qiluvchi (tashkilot, lavozim, F.I.SH.); markazda "Hurmatli ...!"; asosiy matn krasnaya stroka bilan; pastda imzo bloki (lavozim _______ (imzo) (muhr) _______ F.I.SH.). Bir xil tirnoq/apostrof stili (o'rinbosari, so'raymiz). Raqam: № 001/26 (tartib/yil oxirgi 2 raqami), har yil 1 dan, yangi xatdan oldin jurnaldan oxirgi raqamni o'qib +1, takrorlanmasin. Excel jurnal "Chiquvchi xatlar jurnali": ustunlar № т/р | Raqam | Sana (KK.OO.YYYY) | Qabul qiluvchi tashkilot | Qabul qiluvchi F.I.SH. | Mavzu | Kim uchun (F.I.SH., pasport) | Imzolagan | Holati | Fayl nomi; sarlavha qalin, filtr, freeze; har xat yangi qator. Fayl nomi: Хат_№001-26_2026-10-30.docx. Kirish: kimga, mazmun, imzo qo'yuvchi. Oxirida docx va xlsx qaytariladi. Oldingi xat (Saidkosimov, O'zbektelekom) jurnalga hali kiritilmagan.

## Telegram Client API
- [2026-10-30] [2026-10-30] Telethon 1.45 o'rnatilgan, Jamshid akkaunti ulangan. Skript: skript/tg_akkaunt.py (send/login/me/dialogs/sendmsg), sessiya ish/tg_session. Maxfiy qiymatlar inventar yozuvlari telegram-akkaunt (api_id/api_hash maydonlari almashgan: skript regex bilan ajratadi), telefon shu yozuvda. Ishlatish: env TG_API_ID/TG_API_HASH/TG_PHONE ni {{inv:telegram-akkaunt.*}} placeholder bilan bering, UTF-8 uchun PYTHONIOENCODING=utf-8. Boshqa odamga xabar yuborishdan oldin Jamshid tasdig'i kerak.

## Telegram guruh
- [2026-11-07] [2026-11-07] Signal guruhi 'sentinel treading alert' chat_id = -5588340884 (Jamshid tasdiqladi). Skaner (auto_scan_alert.py) shu guruhga bot @sentinel_v4bot nomidan yuboradi. Guruhda javob berish uchun agent yadrosida (guruh chat_id + user_id juftligi ruxsati) o'zgarish kerak; yadro agentga yopiq.
