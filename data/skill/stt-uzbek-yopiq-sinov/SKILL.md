---
name: stt-uzbek-yopiq-sinov
description: STT ni real ovozsiz sinash: TTS bilan o'zbekcha jumlalar yaratib Transcriber'dan o'tkazish va o'xshashlikni o'lchash.
triggers: stt, sinov, tts, whisper, univoice, lug'at, glossary, ovozli, голосовой
yaratilgan: 2026-10-26
yangilangan: 2026-10-31
versiya: 2
---

# stt-uzbek-yopiq-sinov

1. Sinov audiolari: skript/stt_loop_test.py — jumlalar (lotin o'zbekcha) uchun tts_voice.py bilan ish/stt_test/tN.ogg
   yaratadi, ro'yxat ish/stt_test/list.json ga yoziladi.
2. Sinov: skript/stt_loop_run.py [model] — Transcriber(model, 'uz', AGENT_HOME\modellar), standart model
   univoice-stt-uz-ct2. transcribe ASYNC — asyncio.run(...). Natija: ish/stt_test/natija.txt (o'xshashlik | asl | STT).
3. Konsol cp1251 UnicodeEncodeError bermasligi uchun: $env:PYTHONIOENCODING='utf-8' va natijani fayldan o'qi.
4. Runtime log: AGENT_HOME\jurnal\stt_runtime.log (model, logprob, raw).
5. Lug'at (IT_GLOSSARY) agent/stt.py ichida. Agent kodni o'zgartirmaydi: yangi atama kerak bo'lsa (STT doim bir xil xato
   yozsa) — regex va to'g'ri shaklni egasiga taklif qil. Umumiy so'zlarni (masalan "eski server") lug'atga QO'SHMA.
Natija 2026-10-26: univoice 6 jumlada o'xshashlik 0.87-1.00; xatolar faqat texnik atamalarda.
