import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Смета"
thin = Side(style="thin", color="999999")
box = Border(left=thin, right=thin, top=thin, bottom=thin)
hdr = PatternFill("solid", fgColor="1F4E78")
tot = PatternFill("solid", fgColor="FFE699")
inp = PatternFill("solid", fgColor="DDEBF7")

ws["A1"] = "Смета: игровой ПК (i7-14700KF)"
ws["A1"].font = Font(bold=True, size=14)
ws.merge_cells("A1:E1")
ws["A3"] = "Курс доллара (сўм)"; ws["B3"] = 12100
ws["A4"] = "ПК сони"; ws["B4"] = 2
for c in ("B3", "B4"):
    ws[c].fill = inp; ws[c].font = Font(bold=True)
ws["B3"].number_format = "#,##0"

heads = ["№", "Номи", "Нарх, $ (1 ПК)", "ПК сони", "Сумма, $"]
for i, h in enumerate(heads, 1):
    c = ws.cell(row=6, column=i, value=h)
    c.font = Font(bold=True, color="FFFFFF"); c.fill = hdr
    c.alignment = Alignment(horizontal="center"); c.border = box

items = [
    ("Процессор Intel Core i7-14700KF", 400),
    ("Материнская плата Gigabyte Z790", 275),
    ("Водяное охлаждение L360", 125),
    ("DDR5 32GB (2x16GB) 5600", 625),
    ("Видеокарта ASUS RTX 5060 (1)", 638),
    ("Видеокарта ASUS RTX 5060 (2)", 638),
    ("Блок питания 750W модульный", 63),
    ("Корпус большой, 4 вентилятора, белый", 100),
    ("SSD Samsung 1TB", 245),
]
r = 7
for n, (name, price) in enumerate(items, 1):
    ws.cell(r, 1, n); ws.cell(r, 2, name); ws.cell(r, 3, price)
    ws.cell(r, 4, "=$B$4"); ws.cell(r, 5, f"=C{r}*D{r}")
    for col in range(1, 6):
        ws.cell(r, col).border = box
    ws.cell(r, 3).number_format = "#,##0"; ws.cell(r, 5).number_format = "#,##0"
    r += 1
last = r - 1

rows = [
    ("ИТОГО 1 ПК, $", 3, f"=SUM(C7:C{last})", "#,##0"),
    ("ИТОГО за все ПК, $", 5, f"=SUM(E7:E{last})", "#,##0"),
    ("ИТОГО в сумах (без НДС)", 5, f"=E{last+2}*$B$3", "#,##0"),
    ("НДС 12% (справочно), сўм", 5, f"=E{last+3}*0.12", "#,##0"),
    ("С НДС (справочно), сўм", 5, f"=E{last+3}+E{last+4}", "#,##0"),
]
r = last + 1
for label, col, f, fmt in rows:
    ws.cell(r, 2, label)
    ws.cell(r, col, f).number_format = fmt
    bold = "справочно" not in label
    for cc in range(2, 6):
        ws.cell(r, cc).fill = tot if bold else PatternFill()
        ws.cell(r, cc).font = Font(bold=bold, size=12 if bold else 11)
        ws.cell(r, cc).border = box
    r += 1

ws.column_dimensions["A"].width = 24
ws.column_dimensions["B"].width = 42
ws.column_dimensions["C"].width = 18
ws.column_dimensions["D"].width = 10
ws.column_dimensions["E"].width = 22
ws.freeze_panes = "A7"
wb.save(r"D:\it-agent\data\ish\smeta_2_pc_final.xlsx")
print("OK")
