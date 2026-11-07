from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

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

wb = Workbook()
ws = wb.active
ws.title = "Смета"
thin = Side(style="thin", color="999999")
border = Border(left=thin, right=thin, top=thin, bottom=thin)
hfill = PatternFill("solid", fgColor="1F4E78")
tfill = PatternFill("solid", fgColor="DDEBF7")

ws["A1"] = "Смета: сборка ПК (i7-14700KF)"
ws["A1"].font = Font(bold=True, size=14)
ws.merge_cells("A1:E1")

ws["A3"] = "Курс доллара (сум)"
ws["B3"] = 12100
ws["A4"] = "Количество ПК"
ws["B4"] = 2
for c in ("A3", "A4"):
    ws[c].font = Font(bold=True)
for c in ("B3", "B4"):
    ws[c].fill = PatternFill("solid", fgColor="FFF2CC")
    ws[c].border = border
ws["B3"].number_format = '#,##0'

hdr = ["№", "Наименование", "Цена, $ (1 ПК)", "Кол-во ПК", "Сумма, $"]
r0 = 6
for i, h in enumerate(hdr, 1):
    c = ws.cell(row=r0, column=i, value=h)
    c.font = Font(bold=True, color="FFFFFF")
    c.fill = hfill
    c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    c.border = border

r = r0 + 1
for n, (name, price) in enumerate(items, 1):
    ws.cell(row=r, column=1, value=n)
    ws.cell(row=r, column=2, value=name)
    ws.cell(row=r, column=3, value=price)
    ws.cell(row=r, column=4, value="=$B$4")
    ws.cell(row=r, column=5, value=f"=C{r}*D{r}")
    for col in range(1, 6):
        ws.cell(row=r, column=col).border = border
    ws.cell(row=r, column=1).alignment = Alignment(horizontal="center")
    ws.cell(row=r, column=3).number_format = '#,##0'
    ws.cell(row=r, column=5).number_format = '#,##0'
    r += 1

first, last = r0 + 1, r - 1
rows = [
    ("Итого 1 ПК, $", f"=SUM(C{first}:C{last})", None),
    ("Итого на все ПК, $", f"=SUM(E{first}:E{last})", None),
    ("Итого в сумах (без НДС)", f"=E{r+1}*$B$3", None),
]
for k, (lab, f, _) in enumerate(rows):
    rr = r + k
    ws.cell(row=rr, column=2, value=lab).font = Font(bold=True)
    col = 3 if k == 0 else 5
    cell = ws.cell(row=rr, column=col, value=f)
    cell.font = Font(bold=True)
    cell.number_format = '#,##0'
    for cc in range(1, 6):
        ws.cell(row=rr, column=cc).fill = tfill
        ws.cell(row=rr, column=cc).border = border

ws.cell(row=r + 4, column=2, value="НДС не включён").font = Font(italic=True)

ws.column_dimensions["A"].width = 20
ws.column_dimensions["B"].width = 42
ws.column_dimensions["C"].width = 16
ws.column_dimensions["D"].width = 12
ws.column_dimensions["E"].width = 20
ws.freeze_panes = ws.cell(row=r0 + 1, column=1)

out = r"D:\it-agent\data\ish\smeta_2_pc.xlsx"
wb.save(out)
print("saved", out)
