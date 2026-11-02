import math
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors

pdfmetrics.registerFont(TTFont('A', r'C:\Windows\Fonts\arial.ttf'))
pdfmetrics.registerFont(TTFont('AB', r'C:\Windows\Fonts\arialbd.ttf'))

# TAXMINIY taqsimot (jami 265) - aniq sonlar kelgach almashtiriladi
cams = [40, 35, 32, 30, 30, 28, 26, 24, 20]
PER = 16  # 4x4
total = sum(cams)
scr = [math.ceil(c / PER) for c in cams]
RES = 0.10
pal = [colors.HexColor(x) for x in ['#d6eaf8', '#d5f5e3', '#fcf3cf', '#fadbd8', '#e8daef', '#d0ece7', '#fdebd0', '#d4e6f1', '#ebdef0']]

W, H = landscape(A4)
c = canvas.Canvas(r'D:\it-agent\data\ish\kamera_monitoring_smeta.pdf', pagesize=landscape(A4))
c.setTitle('Kamera monitoring smetasi')

def title(t, sub=None):
    c.setFont('AB', 18); c.drawString(30, H - 40, t)
    if sub:
        c.setFont('A', 10); c.setFillColor(colors.grey); c.drawString(30, H - 56, sub); c.setFillColor(colors.black)

# 1-bet: xulosa
title('Видеокузатув мониторинги: экранлар сметаси', '9 та объект, 265 та камера | Сана: 2026-10-29')
y = H - 90
c.setFont('A', 11)
lines = [
    'Асосий вариант: марказий диспетчер хонаси, 55" (4K) экранлар, ҳар экранда 4x4 = 16 камера.',
    'Камералар объект бўйича гуруҳланади: ҳар объект ўз экран(лар)ида, аралашмайди.',
    'Жами: %d камера -> %d та экран (16 тадан). Запас (+%d%% келажак камера) учун +2 экран тавсия.' % (total, sum(scr), RES * 100),
    'Муқобил (тежамли): объектларни аралаштириб, узлуксиз 4x4 -> %d та экран.' % math.ceil(total / PER),
    'Эслатма: объектлар бўйича камера сони ТАХМИНИЙ тақсимланган (жами 265). Аниқ сон келса, қайта ҳисобланади.',
]
for l in lines:
    c.drawString(30, y, l); y -= 18
y -= 8
cols = ['Объект', 'Камера', 'Экран (4x4)', 'Охирги экранда', 'Бўш жой']
xs = [30, 150, 230, 340, 470]
c.setFont('AB', 11)
for x, t in zip(xs, cols): c.drawString(x, y, t)
y -= 6; c.line(30, y, 560, y); y -= 16
c.setFont('A', 11)
for i, (n, s) in enumerate(zip(cams, scr)):
    last = n - (s - 1) * PER
    free = s * PER - n
    for x, t in zip(xs, ['Объект %d' % (i + 1), n, s, '%d камера' % last, free]):
        c.drawString(x, y, str(t))
    y -= 17
c.setFont('AB', 11)
c.line(30, y + 12, 560, y + 12)
for x, t in zip(xs, ['ЖАМИ', total, sum(scr), '', sum(scr) * PER - total]):
    c.drawString(x, y, str(t))
y -= 30
c.setFont('A', 10)
for l in [
    'Жиҳозлар (тахминий): 20 экран 55" 4K; 5 та декодер/ишчи станция (ҳар бири 4 экран чиқаради);',
    'HikCentral (серверда бор) орқали видеодевор; кабель HDMI/DP; монитор стенд ёки девор кронштейни.',
    'Тармоқ: 265 камера x 4 Мбит/с (main) ~ 1.1 Гбит/с; мониторингда sub-stream (1 Мбит/с) ~ 265 Мбит/с.',
    'Нархлар киритилмаган: экран ва ишчи станция нархи бўйича таклиф керак бўлса, айтинг.',
]:
    c.drawString(30, y, l); y -= 15
c.showPage()

# 2-bet: devor sxemasi
title('Видеодевор жойлашуви (умумий схема)', 'Қатор бўйича: экран рақами ва объект. Ҳар катак = 1 экран (16 камера)')
sx, sy_top = 30, H - 90
cw, ch = 125, 80
gap = 8
per_row = 6
idx = 0
labels = []
for o, s in enumerate(scr):
    for k in range(s):
        labels.append((o, k))
for i, (o, k) in enumerate(labels):
    r, cc = divmod(i, per_row)
    x = sx + cc * (cw + gap)
    yy = sy_top - (r + 1) * (ch + gap)
    c.setFillColor(pal[o]); c.setStrokeColor(colors.black)
    c.rect(x, yy, cw, ch, fill=1)
    c.setFillColor(colors.black)
    c.setFont('AB', 12); c.drawString(x + 6, yy + ch - 18, 'Экран %d' % (i + 1))
    n = cams[o] - k * PER; n = min(n, PER)
    c.setFont('A', 10)
    c.drawString(x + 6, yy + ch - 34, 'Объект %d' % (o + 1))
    c.drawString(x + 6, yy + ch - 48, '%d камера' % n)
    c.drawString(x + 6, yy + ch - 62, 'Тўплам %d/%d' % (k + 1, s))
c.showPage()

# keyingi betlar: har obyekt uchun 4x4 setkalar
cam_no = 0
scr_no = 0
for o in range(9):
    title('Объект %d: %d камера, %d экран' % (o + 1, cams[o], scr[o]), 'Ҳар экран 4x4. Камера белгиси: О%d-К## (объект-камера тартиби)' % (o + 1))
    left = cams[o]
    k = 0
    gx0 = 30
    gw = (W - 60 - 12 * (scr[o] - 1)) / scr[o]
    gw = min(gw, 380)
    gh = gw * 9 / 16 * 1.0
    gh = min(gh, 330)
    gw = gh * 16 / 9
    for k in range(scr[o]):
        x0 = gx0 + k * (gw + 14)
        ytop = H - 100
        n_in = min(PER, left); left -= n_in
        scr_no += 1
        c.setFont('AB', 12); c.drawString(x0, ytop + 6, 'Экран %d' % scr_no)
        cwid = gw / 4; chei = gh / 4
        for j in range(PER):
            r, cc = divmod(j, 4)
            xx = x0 + cc * cwid; yy = ytop - (r + 1) * chei
            if j < n_in:
                cam_no += 1
                c.setFillColor(pal[o]); c.rect(xx, yy, cwid, chei, fill=1)
                c.setFillColor(colors.black); c.setFont('A', 7)
                c.drawCentredString(xx + cwid / 2, yy + chei / 2 - 2, 'О%d-К%02d' % (o + 1, cam_no - sum(cams[:o])))
            else:
                c.setFillColor(colors.HexColor('#f2f3f4')); c.rect(xx, yy, cwid, chei, fill=1)
                c.setFillColor(colors.grey); c.setFont('A', 7)
                c.drawCentredString(xx + cwid / 2, yy + chei / 2 - 2, 'бўш')
        c.setFillColor(colors.black)
    c.showPage()
c.save()
print('OK', total, sum(scr))
