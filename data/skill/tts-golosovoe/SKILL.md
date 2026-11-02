---
name: tts-golosovoe
description: Matnni ovozli (voice) xabarga aylantirib Telegramga yuborish (uz/ru/en).
triggers: голосовой, ovozli, voice, tts, озвучить
yaratilgan: 2026-10-24
yangilangan: 2026-10-24
versiya: 1
---

# tts-golosovoe

1. venv da edge-tts va imageio-ffmpeg o'rnatilgan (pip install edge-tts imageio-ffmpeg).
2. python skript/tts_voice.py "matn" uz|ru|en C:\agent\ish\voice.ogg  (uz uchun matnni LOTIN harfida yoz: kirill bilan NoAudioReceived xatosi).
3. notify_owner(file_path=...ogg) — telegram_api.send_document .ogg/.opus ni sendVoice bilan yuboradi (bot qayta ishga tushirilgach).
Eslatma: edge-tts internet talab qiladi. Ovozlar: uz-UZ-MadinaNeural, ru-RU-SvetlanaNeural, en-US-JennyNeural.
