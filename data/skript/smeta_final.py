from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
wb = Workbook(); ws = wb.active; ws.title = "Смета"
Y = PatternFill("solid", fgColor="FFF2CC"); G = PatternFill("solid", fgColor="E2EFDA")
b = Side(style="thin"); B = Border(left=b, right=b, top=b, bottom=b)
ws["A1"] = "Смета: 9 та объект + 7 та сотув — 328 та камера (мониторинг)"; ws["A1"].font = Font(bold=True, size=13)
ws["A2"] = "Сариқ катак — нархи ҳали номаълум (ёзсангиз, жами ўзи ҳисобланади). 328 камера / 8 ТВ = 41 камера бир ТВга."
r = 4
for title, name, price in [("Вариант 1: 55\" Smart TV", "Smart TV 55\" (Honor, Idea)", 4300000),
                           ("Вариант 2: 65\" Smart TV", "Smart TV 65\" (Primer, Idea)", 6500000)]:
    ws.cell(r, 1, title).font = Font(bold=True); r += 1
    for c, h in enumerate(["№", "Номи", "Сони", "Нархи (сўм)", "Жами (сўм)", "Изоҳ"], 1):
        x = ws.cell(r, c, h); x.font = Font(bold=True); x.border = B
    r += 1; s = r
    rows = [(name, 8, price, "Idea, энг арзон"), ("Кронштейн (ТВ учун)", 8, None, "нарх номаълум"),
            ("UTP кабель, 1 бухта (305 м)", 1, None, "нарх номаълум"),
            ("RJ45 коннектор, 1 почка (1000 дона)", 1, None, "нарх номаълум")]
    for i, (n, q, p, note) in enumerate(rows, 1):
        ws.cell(r, 1, i); ws.cell(r, 2, n); ws.cell(r, 3, q)
        ws.cell(r, 4, p if p else None); ws.cell(r, 5, f"=C{r}*D{r}"); ws.cell(r, 6, note)
        if not p: ws.cell(r, 4).fill = Y
        else: ws.cell(r, 4).fill = G
        for c in range(1, 7): ws.cell(r, c).border = B
        ws.cell(r, 4).number_format = ws.cell(r, 5).number_format = '#,##0'
        r += 1
    ws.cell(r, 2, "ЖАМИ (ҳозирча фақат ТВ)").font = Font(bold=True)
    ws.cell(r, 5, f"=SUM(E{s}:E{r-1})").font = Font(bold=True); ws.cell(r, 5).number_format = '#,##0'
    r += 3
for col, w in zip("ABCDEF", [5, 42, 8, 16, 18, 22]): ws.column_dimensions[col].width = w
wb.save(r"D:\it-agent\data\ish\smeta_328_yakuniy.xlsx")
print("ok")
