from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

data = [
 ("Техно парк","Samsung",55,13200000),("Техно парк","LG",55,14600000),
 ("Техно парк","Haier",55,11000000),("Техно парк","Primer",55,7500000),
 ("Техно парк","Samsung",65,31210000),("Техно парк","LG",65,23520000),
 ("Техно парк","Haier",65,13000000),
 ("Idea","Samsung",65,13000000),("Idea","Loretto",65,7000000),
 ("Idea","Primer",65,6500000),("Idea","Ssmart",65,6500000),
 ("Idea","Artel",55,5000000),("Idea","Samsung",55,7000000),
 ("Idea","LG",55,22000000),("Idea","Loretto",55,5300000),
 ("Idea","Primer",55,4900000),("Idea","Ssmart",55,5000000),
 ("Idea","Honor",55,4300000),
]
data.sort(key=lambda r:(r[2],r[3]))
wb = Workbook(); ws = wb.active; ws.title = "Таққослаш"
hdr = ["Дюйм","Бренд","Дўкон","Нарх (сўм)"]
ws.append(hdr)
for c in ws[1]:
    c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="305496")
    c.alignment = Alignment(horizontal="center")
thin = Side(style="thin", color="999999")
mins = {s: min(r[3] for r in data if r[2]==s) for s in (55,65)}
for b,br,s,p in data:
    ws.append([f'{s}"', br, b, p])
    row = ws.max_row
    ws.cell(row,4).number_format = '#,##0'
    if p == mins[s]:
        for col in range(1,5):
            ws.cell(row,col).fill = PatternFill("solid", fgColor="C6EFCE")
for row in ws.iter_rows(min_row=1, max_row=ws.max_row):
    for c in row: c.border = Border(top=thin,bottom=thin,left=thin,right=thin)
for col,w in zip("ABCD",(8,14,14,16)): ws.column_dimensions[col].width = w
ws.append([]); ws.append(["Яшил — шу ўлчамдаги энг арзон нарх"])
wb.save(r"D:\it-agent\data\ish\tv_narx_taqqos.xlsx")
for s in (55,65):
    print(s, [r for r in data if r[2]==s][:3])
