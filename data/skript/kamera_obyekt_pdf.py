from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor, black, white

pdfmetrics.registerFont(TTFont('A', 'C:/Windows/Fonts/arial.ttf'))
pdfmetrics.registerFont(TTFont('AB', 'C:/Windows/Fonts/arialbd.ttf'))

objs = [("Орзулар", 89, "#e6194b"), ("Зорсан", 64, "#3cb44b"), ("Ватан", 26, "#4363d8"),
        ("Муҳаббат шаҳрида", 22, "#f58231"), ("Водий", 12, "#911eb4"), ("Афсона", 18, "#42d4f4"),
        ("Ширин ҳаёт", 26, "#bfa600"), ("Воҳа", 2, "#f032e6"), ("Чинобод", 6, "#808080")]
total = sum(o[1] for o in objs)
assert total == 265
# camera no -> object idx
cam = []
for i, o in enumerate(objs):
    cam += [i] * o[1]
PER, COLS, ROWS, SCR = 48, 8, 6, 6
W, H = landscape(A4)
out = "D:/it-agent/data/ish/kamera_obyektlar_6ekran.pdf"
c = canvas.Canvas(out, pagesize=(W, H))

# 1-bet: ma'lumot
c.setFont('AB', 18); c.drawString(40, H-50, "Камералар рўйхати (9 та объект)")
y = H-90
c.setFont('AB', 12)
c.drawString(40, y, "№"); c.drawString(70, y, "Объект"); c.drawString(300, y, "Камера сони"); c.drawString(400, y, "Рақамлари"); c.drawString(530, y, "Экранлар")
c.line(40, y-5, W-40, y-5)
c.setFont('A', 12)
start = 1
for i, (n, k, col) in enumerate(objs):
    y -= 24
    a, b = start, start+k-1
    s1, s2 = (a-1)//PER+1, (b-1)//PER+1
    c.setFillColor(HexColor(col)); c.rect(40, y-2, 12, 12, fill=1, stroke=0); c.setFillColor(black)
    c.drawString(58, y, str(i+1)); c.drawString(75, y, n); c.drawString(300, y, str(k))
    c.drawString(400, y, f"{a}–{b}")
    c.drawString(530, y, str(s1) if s1 == s2 else f"{s1}–{s2}")
    start += k
y -= 28
c.setFont('AB', 13)
c.drawString(70, y, "ЖАМИ"); c.drawString(300, y, str(total))
y -= 40
c.setFont('A', 12)
for t in ["6 та экран × 48 катак (8×6) = 288 катак.",
          f"Камера: {total}, бўш катак: {288-total} (запас).",
          "Жойлашув тартиби: объектлар кетма-кет, чапдан ўнгга, юқоридан пастга."]:
    c.drawString(40, y, t); y -= 20
c.showPage()

# 2-bet: umumiy jadval ekranlar
c.setFont('AB', 18); c.drawString(40, H-50, "Экранлар бўйича тақсимот")
y = H-90
c.setFont('AB', 12); c.drawString(40, y, "Экран"); c.drawString(110, y, "Камералар"); c.drawString(210, y, "Таркиби"); c.line(40, y-5, W-40, y-5)
c.setFont('A', 11)
for s in range(SCR):
    y -= 28
    a = s*PER+1; b = min((s+1)*PER, total)
    parts = {}
    for n in range(a, b+1):
        parts[cam[n-1]] = parts.get(cam[n-1], 0)+1
    txt = ", ".join(f"{objs[i][0]} {k}" for i, k in parts.items())
    if b < (s+1)*PER: txt += f", бўш {(s+1)*PER-b}"
    c.drawString(40, y, f"{s+1}-экран"); c.drawString(110, y, f"{a}–{b}")
    c.drawString(210, y, txt)
c.showPage()

# ekran sahifalari
cw, ch = 95, 60
gx = (W - cw*COLS)/2
gy = H-110
for s in range(SCR):
    c.setFont('AB', 18); c.drawString(40, H-50, f"{s+1}-экран  (8×6 = 48 катак)")
    for r in range(ROWS):
        for col in range(COLS):
            idx = s*PER + r*COLS + col + 1
            x = gx + col*cw; yy = gy - (r+1)*ch
            if idx <= total:
                o = objs[cam[idx-1]]
                c.setFillColor(HexColor(o[2])); c.rect(x, yy, cw, ch, fill=1, stroke=0)
                c.setFillColor(white); c.setFont('AB', 14); c.drawCentredString(x+cw/2, yy+ch/2+2, str(idx))
                c.setFont('A', 8); c.drawCentredString(x+cw/2, yy+8, o[0])
            else:
                c.setFillColor(HexColor("#dddddd")); c.rect(x, yy, cw, ch, fill=1, stroke=0)
                c.setFillColor(HexColor("#888888")); c.setFont('A', 9); c.drawCentredString(x+cw/2, yy+ch/2-3, "бўш")
            c.setStrokeColor(white); c.setLineWidth(1.5); c.rect(x, yy, cw, ch, fill=0, stroke=1)
    # legend
    lx = 40; ly = 50
    c.setFont('A', 9)
    for n, k, colr in objs:
        c.setFillColor(HexColor(colr)); c.rect(lx, ly, 10, 10, fill=1, stroke=0)
        c.setFillColor(black); c.drawString(lx+14, ly+2, f"{n} ({k})"); lx += 14 + pdfmetrics.stringWidth(f"{n} ({k})", 'A', 9) + 14
    c.showPage()
c.save()
print("OK", out)
