from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors

pdfmetrics.registerFont(TTFont("F", r"C:\Windows\Fonts\arial.ttf"))
pdfmetrics.registerFont(TTFont("FB", r"C:\Windows\Fonts\arialbd.ttf"))

objs = [("Орзулар сотув", 22), ("Зорсан сотув", 8), ("Ватан сотув", 7),
        ("Муҳаббат шаҳри сотув", 10), ("Водий сотув", 7),
        ("Федерович сотув", 7), ("Воҳа сотув", 2)]
total = sum(n for _, n in objs)
assert total == 63
cols = [colors.HexColor(c) for c in
        ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#008080", "#9a6324"]]
# экран 1: дастлабки 4 объект (47), экран 2: қолгани (16)
screens = [[objs[0], objs[1], objs[6]], [objs[2], objs[3], objs[4], objs[5]]]

# камера рақамлари
num = 1
layout = []
for sc in screens:
    cells = []
    for i, (name, n) in enumerate(sc):
        ci = objs.index((name, n))
        for k in range(n):
            cells.append((num, ci))
            num += 1
    layout.append(cells)

W, H = landscape(A4)
c = canvas.Canvas(r"D:\it-agent\data\ish\sotuv_2ekran_6x6.pdf", pagesize=(W, H))

# 1-бет: жадвал
c.setFont("FB", 18)
c.drawString(40, H - 50, "Сотув бўлими камералари — 2 та экран (6x6)")
c.setFont("F", 12)
c.drawString(40, H - 72, "Жами: %d та камера. Ҳар экран 6x6 = 36 катак, 2 экран = 72 катак." % total)
y = H - 110
c.setFont("FB", 12)
for x, t in [(40, "№"), (70, "Объект"), (330, "Камера"), (410, "Экран"), (480, "Рақамлар")]:
    c.drawString(x, y, t)
y -= 6
c.line(40, y, W - 40, y)
y -= 20
c.setFont("F", 12)
start = 1
rng = {}
for sc_ in layout:
    pass
for i, (name, n) in enumerate(objs):
    sc = 1 if (name, n) in screens[0] else 2
    c.setFillColor(cols[i]); c.rect(40, y - 2, 14, 12, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.drawString(70, y, name)
    c.drawString(330, y, str(n))
    c.drawString(410, y, str(sc))
    nums = [k for sc_ in layout for (k, cj) in sc_ if cj == i]; c.drawString(480, y, "%d–%d" % (min(nums), max(nums)))
    start += n
    y -= 22
c.line(40, y + 14, W - 40, y + 14)
c.setFont("FB", 12)
c.drawString(70, y - 4, "Жами")
c.drawString(330, y - 4, str(total))
y -= 40
c.setFont("F", 12)
c.drawString(40, y, "Экран 1: %d та камера (%d бўш катак)" % (len(layout[0]), 36 - len(layout[0])))
c.drawString(40, y - 18, "Экран 2: %d та камера (%d бўш катак)" % (len(layout[1]), 36 - len(layout[1])))
c.drawString(40, y - 36, "Ҳар объект бир экранда бутун туради, объектлар экранлар орасида бўлинмайди.")
c.showPage()

# схема бетлари
for s, cells in enumerate(layout):
    c.setFont("FB", 16)
    c.drawString(40, H - 40, "Экран %d — 6x6 (%d та камера)" % (s + 1, len(cells)))
    gx, gy, gw, gh = 40, 70, W - 80, H - 130
    cw, ch = gw / 6, gh / 6
    for idx in range(36):
        r, col = divmod(idx, 6)
        x = gx + col * cw
        yy = gy + gh - (r + 1) * ch
        if idx < len(cells):
            n, ci = cells[idx]
            c.setFillColor(cols[ci])
            c.rect(x, yy, cw, ch, fill=1, stroke=0)
            c.setFillColor(colors.white)
            c.setFont("FB", 16)
            c.drawCentredString(x + cw / 2, yy + ch / 2 - 2, str(n))
        else:
            c.setFillColor(colors.HexColor("#dddddd"))
            c.rect(x, yy, cw, ch, fill=1, stroke=0)
        c.setStrokeColor(colors.white); c.setLineWidth(2)
        c.rect(x, yy, cw, ch, fill=0, stroke=1)
    # легенда
    lx = 40
    c.setFont("F", 9)
    for name, n in screens[s]:
        ci = objs.index((name, n))
        c.setFillColor(cols[ci]); c.rect(lx, 40, 10, 10, fill=1, stroke=0)
        c.setFillColor(colors.black)
        t = "%s (%d)" % (name, n)
        c.drawString(lx + 14, 42, t)
        lx += 20 + pdfmetrics.stringWidth(t, "F", 9) + 10
    c.setFillColor(colors.HexColor("#dddddd")); c.rect(lx, 40, 10, 10, fill=1, stroke=0)
    c.setFillColor(colors.black); c.drawString(lx + 14, 42, "бўш")
    c.showPage()
c.save()
print("OK", [len(x) for x in layout])


