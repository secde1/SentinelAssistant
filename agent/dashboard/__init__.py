"""SENTINAL CONTROL CENTER — mahalliy veb-dashboard (faqat o'qish).

Agentdan ALOHIDA jarayon: `python -m agent.dashboard` (yoki dashboard.cmd). Agent kodi o'zgarmaydi, agent
to'xtab qolsa ham dashboard ishlaydi. Faqat 127.0.0.1, token + sessiya cookie bilan.

Hech qanday buyruq bajarmaydi, boshqa kompyuterga ulanmaydi, tarmoqni skanerlamaydi:
  • qurilmalar — mavjud ma'lumotlardan (maxfiy/inventar.json ning maxfiy bo'lmagan maydonlari, AD eksport CSV,
    xotira/tuzilma.json) va shu kompyuterning o'zidan (psutil + Windows registry);
  • faoliyat — jurnal/*.jsonl (agent yozgan, allaqachon redaction qilingan);
  • AI chat — Claude obunasi orqali, tool'larsiz (hech narsa bajara olmaydi, faqat javob beradi).
"""
