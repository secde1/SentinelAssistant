from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
wb = Workbook(); ws = wb.active; ws.title = "Смета"
thin = Side(style="thin"); b = Border(left=thin, right=thin, top=thin, bottom=thin)
yel = PatternFill("solid", fgColor="FFF2CC"); hd = PatternFill("solid", fgColor="D9E1F2")
ws["A1"] = "Смета: 9 та объект + 7 та сотув — 328 та камера (мониторинг)"; ws["A1"].font = Font(bold=True, size=13)
ws["A2"] = "Сариқ катаклар — нархни ўзингиз ёзасиз, жами автоматик ҳисобланади. 328 камера / 8 ТВ = 41 камера бир ТВга."
def block(r, title, tv_name, tv_price):
    ws.cell(r,1,title).font = Font(bold=True, size=12)
    h = ["№","Номи","Сони","Нархи (сўм)","Жами (сўм)","Изоҳ"]
    for i,x in enumerate(h,1):
        c = ws.cell(r+1,i,x); c.font = Font(bold=True); c.fill = hd; c.border = b
    rows = [
        (tv_name, 8, tv_price, "Idea нархи (энг арзон Smart TV)"),
        ("Кронштейн (ТВ учун)", 8, None, "ТВ билан бирга"),
        ("UTP кабель, 1 бухта (305 м)", 1, None, "ТВни интернетга улаш учун"),
        ("RJ45 коннектор, 1 почка (1000 дона)", 1, None, ""),
    ]
    for i,(n,q,p,note) in enumerate(rows,1):
        rr = r+1+i
        vals = [i,n,q,p,f"=C{rr}*D{rr}",note]
        for j,v in enumerate(vals,1):
            c = ws.cell(rr,j,v); c.border = b
        ws.cell(rr,4).fill = yel
        for col in (4,5): ws.cell(rr,col).number_format = '#,##0'
    t = r+6
    ws.cell(t,2,"ЖАМИ").font = Font(bold=True)
    ws.cell(t,5,f"=SUM(E{r+2}:E{r+5})").font = Font(bold=True)
    ws.cell(t,5).number_format = '#,##0'
block(4, "Вариант 1: 55\" Smart TV", "Smart TV 55\" (Artel/Primer)", 4900000)
block(13, "Вариант 2: 65\" Smart TV", "Smart TV 65\" (Primer/Ssmart)", 6500000)
for col,w in zip("ABCDEF",(5,42,8,16,18,38)): ws.column_dimensions[col].width = w
wb.save(r"D:\it-agent\data\ish\smeta_328.xlsx")
