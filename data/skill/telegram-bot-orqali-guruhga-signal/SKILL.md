---
name: telegram-bot-orqali-guruhga-signal
description: Skaner/alert xabarlarini guruhga shaxsiy akkaunt emas, BOT nomidan (Bot API) yuborish.
triggers: bot, guruh, signal, alert, sendMessage, Bot API, akkauntimdan yozdi
yaratilgan: 2026-11-07
yangilangan: 2026-11-07
versiya: 1
---

# telegram-bot-orqali-guruhga-signal

1. Bot tokenini request_credentials(name='telegram-bot-alert', fields=['token']) bilan so'ra (chatda so'rama).
2. Tekshir: call_http_api GET https://api.telegram.org/bot{{inv:telegram-bot-alert.token}}/getMe -> ok:true, username.
3. Bot guruhdami: GET .../getChat?chat_id=<GROUP_ID> -> 200 bo'lsa bot guruhda. (Basic guruh ID: manfiy, masalan -5588340884.) Bo'lmasa Jamshid botni guruhga qo'shishi kerak.
4. Tokenni skriptga yozma: run_powershell bilan ish\bot_env.json ga yoz: $j=@{token='{{inv:telegram-bot-alert.token}}'}|ConvertTo-Json; [IO.File]::WriteAllText(path,$j,(New-Object Text.UTF8Encoding($false))). ish/ GitHubga tushmaydi.
5. Skriptda send() ni almashtir: tok=json.load(open(BASE+r"\bot_env.json",encoding="utf-8-sig"))["token"]; requests.post("https://api.telegram.org/bot%s/sendMessage"%tok, json={"chat_id":GROUP_ID,"text":text}, timeout=20); r.json()["ok"] ni qaytar. asyncio/Telethon kerak emas.
6. Sinov: call_http_api POST .../sendMessage (json_body chat_id, text) -> from.is_bot true. Keyin skriptni --dry bilan ishga tushirib verify (exit 0).
Eslatma: token chatda ko'ringan bo'lsa BotFather'da /revoke tavsiya qil.
