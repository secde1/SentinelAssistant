---
name: telegram-guruhga-signal
description: Telethon orqali Jamshid akkauntidagi guruhni topish va skaner xabarlarini o'sha guruhga yo'naltirish.
triggers: telegram, guruh, kanal, group, signal, alert, telethon, invite
yaratilgan: 2026-11-07
yangilangan: 2026-11-07
versiya: 1
---

# telegram-guruhga-signal

1. Havolani qo'shilmasdan tekshirish: skript/tg_guruh_tekshir.py <invite_hash> (CheckChatInviteRequest, chaqiruv: await c(Request(...))). InviteHashExpiredError = havola eskirgan.
2. Guruhlar ro'yxati: Telethon iter_dialogs, d.is_group/is_channel, entity.creator = o'zi yaratgan. PYTHONIOENCODING=utf-8.
3. api_id/hash ish/tg_env.json dan, sessiya ish/tg_session (parol skriptga yozilmaydi).
4. Yuborishdan oldin await cl.get_dialogs(limit=100) (entity keshi), keyin cl.send_message(GROUP_ID, text).
5. skript/auto_scan_alert.py da GROUP_ID o'zgaruvchisi; nusxa 'me' ga.
6. Tekshiruv: python auto_scan_alert.py --dry exit 0; sinov xabari message id qaytaradi.
Eslatma: boshqa odamga/begona guruhga yuborishdan oldin Jamshid tasdig'i kerak.
