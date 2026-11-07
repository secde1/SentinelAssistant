p = r"D:\it-agent\data\skript\auto_scan_alert.py"
t = open(p, encoding="utf-8").read()
open(p + ".bak", "w", encoding="utf-8").write(t)
t = t.replace("def send(text):", "def send(text, buttons=None):")
t = t.replace('json={"chat_id": GROUP_ID, "text": text}, timeout=20)',
              'json=dict({"chat_id": GROUP_ID, "text": text}, **({"reply_markup": {"inline_keyboard": buttons}} if buttons else {})), timeout=20)')
t = t.replace("Zdelka ochaymi? (ha/yo'q deb yozing, o'zim ochmayman)",
              "Zdelka ochaymi? Pastdagi tugmani bosing (o'zim ochmayman, avval sizdan tasdiq so'rayman)")
new = '''BOT = "sentinel_v4bot"
    btns = []
    for r in strong[:3]:
        k = "%s_%s" % (r["sym"], r["side"])
        btns.append([{"text": "HA: %s %s" % (r["sym"], r["side"]), "url": "https://t.me/%s?start=ha_%s" % (BOT, k)},
                     {"text": "YO'Q", "url": "https://t.me/%s?start=yoq_%s" % (BOT, k)}])
    if send(txt, btns):'''
t = t.replace("if send(txt):", new)
open(p, "w", encoding="utf-8").write(t)
print("ok")
