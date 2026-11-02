import asyncio, sys, json, os, difflib, re
sys.path.insert(0, r'D:\it-agent')
from pathlib import Path
from agent.stt import Transcriber
# Ishlatish: python stt_loop_run.py [model]  (standart: botdagi univoice-stt-uz-ct2)
t = Transcriber(sys.argv[1] if len(sys.argv) > 1 else 'univoice-stt-uz-ct2', 'uz', Path(r'D:\it-agent\data\modellar'))
res = json.load(open(r'D:\it-agent\data\ish\stt_test\list.json', encoding='utf-8'))
norm = lambda x: re.sub(r"[^a-z0-9 ]", "", x.lower().replace("'", "").replace("вЂ","").replace("вЂ™",""))
rows = []
for s, f in res:
    try:
        r = asyncio.run(t.transcribe(Path(f)))
    except Exception as e:
        r = 'XATO: ' + repr(e)
    if not isinstance(r, str):
        r = str(r)
    sc = difflib.SequenceMatcher(None, norm(s), norm(r)).ratio()
    rows.append(f"{sc:.2f} | {s} | {r}")
    print(rows[-1], flush=True)
open(r'D:\it-agent\data\ish\stt_test\natija.txt', 'w', encoding='utf-8').write("\n".join(rows))

