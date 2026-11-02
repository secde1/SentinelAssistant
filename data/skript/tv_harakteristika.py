from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

wb = Workbook()
thin = Side(style="thin", color="999999")
bd = Border(left=thin, right=thin, top=thin, bottom=thin)
hf = PatternFill("solid", fgColor="1F4E78")

def style(ws, widths):
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF"); c.fill = hf
    for row in ws.iter_rows():
        for c in row:
            c.border = bd
            c.alignment = Alignment(wrap_text=True, vertical="center")
    for i, w in enumerate(widths):
        ws.column_dimensions[chr(65 + i)].width = w

ws = wb.active
ws.title = "Xarakteristika"
ws.append(["Parametr", "Talab", "Izoh"])
rows = [
 ("Diagonal", "65 dyuym", "8 ta bir xil televizor"),
 ("Ruxsat (panel)", "4K UHD 3840x2160", "Full HD yetmaydi: katakchalar juda mayda bo'ladi"),
 ("Gers (Hz)", "60 Hz", "Kamera oqimi 25-30 kadr/s, 120 Hz kerak emas"),
 ("Panel turi", "VA yoki IPS (LED)", "OLED olinmaydi: statik rasmda burn-in (yonib qolish)"),
 ("HDMI port", "Kamida 2 ta HDMI port (kamida bittasi HDMI 2.0, 4K60)", "HDMI 1.4 da 4K faqat 30 Hz. 2 ta port: ikkinchi manba yoki zaxira ulanish uchun"),
 ("Ishlash rejimi", "Kuniga 24 soat", "Yaxshi sovutish, avto-o'chirish (sleep/eco) o'chirilishi kerak"),
 ("Yorqinlik", "300 nit va undan yuqori", "Xona yorug' bo'lsa foydali"),
 ("Smart TV", "SHART: Smart TV bo'lishi kerak (Android TV / Google TV / webOS / Tizen)", "Wi-Fi/LAN, o'rnatilgan brauzer va ilovalar; kamera saytini TV o'zi ochishi mumkin. LAN (Ethernet) port bo'lishi shart"),
 ("Burn-in himoyasi", "Ekran saqlagich/pixel shift o'chiq, yorqinlik 70-80%", "Panel umrini uzaytiradi"),
 ("Mahkamlash", "VESA kronshteyn", "65 dyuym uchun VESA 400x300 yoki 400x400 tekshirilsin"),
]
for r in rows: ws.append(r)
style(ws, [24, 42, 62])

ws2 = wb.create_sheet("Kamera taqsimoti")
ws2.append(["Ko'rsatkich", "Qiymat", "Izoh"])
for r in [
 ("Televizorlar soni", 8, ""),
 ("Kameralar soni (taxminan)", 300, ""),
 ("Bitta ekranga kamera", "=ROUNDUP(B3/B2,0)", "300 / 8 = 37.5 -> 38"),
 ("Setka 6x6", 36, "8 ekranda 288 kamera (300 ga yetmaydi)"),
 ("Setka 7x6", 42, "8 ekranda 336 kamera (300 ga yetadi)"),
 ("6x6 da bitta katak (piksel)", "640x360", "3840/6 x 2160/6"),
 ("7x6 da bitta katak (piksel)", "548x360", "3840/7 x 2160/6"),
]: ws2.append(r)
style(ws2, [32, 18, 50])

ws3 = wb.create_sheet("Narx")
ws3.append(["Model", "Brend", "1 dona ($)", "Soni", "Jami ($)"])
ws3.append(["65V6C (V6C)", "TCL", 500, 8, "=C2*D2"])
ws3.append(["65T6D (T6D)", "TCL", 520, 8, "=C3*D3"])
ws3.append(["Manba: Nigmatov narx ro'yxati. Kronshteyn, kabel, kompyuter/dekoder narxi kirmagan.", "", "", "", ""])
ws3.merge_cells("A4:E4")
style(ws3, [24, 12, 14, 10, 14])

wb.save(r"D:\it-agent\data\ish\tv_harakteristika.xlsx")
print("ok")


