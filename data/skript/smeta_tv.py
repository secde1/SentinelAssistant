from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
wb = Workbook(); ws = wb.active; ws.title = "Смета"
ws.append(["Смета: камера мониторинги учун Smart TV (6 экран)"]); ws.merge_cells("A1:F1")
ws["A1"].font = Font(bold=True, size=14)
ws.append(["Нархлар тахминий (prom.uz, glotr.uz, 2026). Сариқ катаклар - ўзингиз тўлдирасиз."]); ws.merge_cells("A2:F2")
ws.append([])
ws.append(["№", "Номи", "Бирлик", "Сони", "Нархи (сўм)", "Суммаси (сўм)"])
rows = [
 ("Smart TV 55\" 4K (Shivaki 55LU7500)", "дона", 6, 5225000),
 ("Деворга кронштейн 55\"", "дона", 6, None),
 ("HDMI кабель (керак узунликда)", "дона", 6, None),
 ("Видеорегистратор/ПК билан улаш (декодер)", "дона", 6, None),
 ("Розетка/удлинитель", "дона", 6, None),
 ("Ўрнатиш ишлари", "хизмат", 6, None),
]
yellow = PatternFill("solid", fgColor="FFF2A8")
thin = Side(style="thin"); b = Border(left=thin, right=thin, top=thin, bottom=thin)
for i, (n, u, q, p) in enumerate(rows, 1):
    r = 4 + i
    ws.append([i, n, u, q, p, f"=D{r}*E{r}"])
    if p is None: ws.cell(r, 5).fill = yellow
last = 4 + len(rows)
ws.append(["", "ЖАМИ", "", "", "", f"=SUM(F5:F{last})"])
for c in ws[4]: c.font = Font(bold=True); c.fill = PatternFill("solid", fgColor="D9E1F2")
for row in ws.iter_rows(min_row=4, max_row=last+1):
    for c in row: c.border = b
for r in range(5, last+2):
    ws.cell(r, 5).number_format = ws.cell(r, 6).number_format = '#,##0'
ws.cell(last+1, 2).font = ws.cell(last+1, 6).font = Font(bold=True)
for col, w in zip("ABCDEF", [5, 46, 10, 8, 18, 20]): ws.column_dimensions[col].width = w
wb.save(r"D:\it-agent\data\ish\smeta_tv.xlsx")
