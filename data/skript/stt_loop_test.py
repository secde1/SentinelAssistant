import sys, subprocess, json, os, re
sys.path.insert(0, r'D:\it-agent')
PY = r'D:\it-agent\.venv\Scripts\python.exe'
OUT = r'D:\it-agent\data\ish\stt_test'
os.makedirs(OUT, exist_ok=True)
sents = [
 "Mikrotikni qayta ishga tushir",
 "UniFi controllerga adopt bo'lmayapti",
 "Zabbixda ogohlantirish chiqdi, serverni tekshir",
 "Printer navbatini tozala va Spooler xizmatini qayta ishga tushir",
 "ESXi serverda disk joyi kam qoldi",
 "Foydalanuvchi parolini tiklab ber",
]
from agent.stt import Transcriber
import inspect
print(inspect.signature(Transcriber.__init__))
print([m for m in dir(Transcriber) if not m.startswith('__')])
res = []
for i, s in enumerate(sents):
    f = os.path.join(OUT, f't{i}.ogg')
    subprocess.run([PY, r'D:\it-agent\data\skript\tts_voice.py', s, 'uz', f], check=True)
    res.append((s, f))
json.dump(res, open(os.path.join(OUT, 'list.json'), 'w', encoding='utf-8'), ensure_ascii=False)
