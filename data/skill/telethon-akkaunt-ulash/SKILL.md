---
name: telethon-akkaunt-ulash
description: Jamshidning shaxsiy Telegram akkauntiga Telethon (MTProto) orqali ulanish, sessiya yaratish va xabar yuborish.
triggers: telegram, telethon, mtproto, akkaunt, shaxsiy chat, xabar yoz, business
yaratilgan: 2026-10-30
yangilangan: 2026-10-30
versiya: 1
---

# telethon-akkaunt-ulash

1. O'rnatish: & 'D:\it-agent\.venv\Scripts\python.exe' -m pip install telethon
2. Maxfiy qiymatlar: request_credentials(name='telegram-akkaunt', fields=[api_id, api_hash, phone]). my.telegram.org -> API development tools dan olinadi. Eslatma: maydonlar almashib saqlanishi mumkin, skript regex bilan ajratadi (api_id = 5-10 raqam, api_hash = 32 hex).
3. Skript: skript/tg_akkaunt.py (send / login KOD [2FA] / me / dialogs / sendmsg CHAT MATN). Sessiya: ish/tg_session (GitHubga tushmaydi).
4. Muhit o'zgaruvchilari: $env:TG_API_ID='{{inv:telegram-akkaunt.api_id}}'; $env:TG_API_HASH='{{inv:telegram-akkaunt.api_hash}}'; $env:TG_PHONE='{{inv:telegram-akkaunt.phone}}'; $env:PYTHONIOENCODING='utf-8'
5. Kod yuborish: python skript/tg_akkaunt.py send -> "KOD YUBORILDI".
6. Kodni request_credentials(name='telegram-kod', fields=[code]) bilan oling; $code=('{{inv:telegram-kod.code}}' -replace '\D','') (kod "5 93 46" kabi bo'shliq bilan kelishi mumkin).
7. Kirish: python skript/tg_akkaunt.py login $code. SessionPasswordNeededError chiqsa 2FA ni request_credentials(name='telegram-2fa', fields=[password]) bilan oling va login $code '{{inv:telegram-2fa.password}}' qiling.
8. Tekshiruv: tg_akkaunt.py me -> "OK: <ism>" (verify, expect 'OK:').
Xatolar: write_file 'password=***' ga o'xshash qatorni *** ga almashtiradi, skriptda bunday yozuvdan qoching (yoki **{"pass"+"word": ...}). Boshqa odamga xabar yuborishdan oldin Jamshid tasdig'i shart.
