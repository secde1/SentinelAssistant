---
name: stt-uzbek-whisper
description: Botning ovozli xabar tanishi (faster-whisper, o'zbekcha univoice modeli): sozlamalar, model, tekshiruv va muammolar.
triggers: stt, whisper, univoice, ovozli, голосовой, uzbek, распознавание, транскрипция
yaratilgan: 2026-10-24
yangilangan: 2026-10-31
versiya: 3
---

# stt-uzbek-whisper

Kod: D:\it-agent\agent\stt.py (Transcriber). Kodni agent O'ZGARTIRMAYDI — o'zgarish kerak bo'lsa egasiga taklif yoz.
Sozlash faqat .env orqali (keyin agentni qayta ishga tushirish kerak):
- STT_ENABLED=1
- STT_MODEL=univoice-stt-uz-ct2 — AGENT_HOME\modellar\<STT_MODEL> dagi CTranslate2 papkasi (internetdan yuklanmaydi).
- STT_LANGUAGE= (bo'sh -> uz; avtoaniqlash o'zbekchani ru/en deb o'qigani uchun til qat'iy).

Ishlash tartibi (kodda):
1. Audio ffmpeg (imageio-ffmpeg) bilan 16 kHz mono'ga o'tadi; boshi/oxiridagi jimlik kesiladi, highpass/lowpass/loudnorm.
   ffmpeg ishlamasa — PyAV.
2. Model birinchi ovozli xabarda yuklanadi va xotirada qoladi (CPU, int8).
3. transcribe: language=uz, beam_size=5, without_timestamps=True, condition_on_previous_text=False, temperature=0,
   vad_filter=True. initial_prompt YO'Q — univoice model kartasi talabi.
4. Natijaga IT_GLOSSARY qo'llanadi (Zabbix, Spooler, UniFi controller, Mikrotik, adopt, Windows).

Tekshiruv:
- python -m agent --check -> "STT" qatori: model papkasi topildimi.
- Runtime log: AGENT_HOME\jurnal\stt_runtime.log (model, logprob, raw matn yoki XATO).
- Yopiq sinov (real ovozsiz): skill stt-uzbek-yopiq-sinov.

Muammolar:
- Bo'sh natija -> stt_runtime.log dagi XATO; model papkasi to'liqmi (model.bin, config.json, tokenizer).
- Agent jarayoni xotirasi model bilan bir necha GB ga yetishi mumkin; tizim xotirasi tugasa (ffmpeg "Cannot allocate
  memory") agentni qayta ishga tushirish kerak.
- Eski large-v3 / large-v3-turbo / small modellari ishlatilmaydi (o'chirish egasining qarori).
