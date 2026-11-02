from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

rows = [
("55\"","Honor","Idea",4300000),("55\"","Primer","Idea",4900000),("55\"","Artel","Idea",5000000),
("55\"","Ssmart","Idea",5000000),("55\"","Loretto","Idea",5300000),("55\"","Samsung","Idea",7000000),
("55\"","Primer","Техно парк",7500000),("55\"","Haier","Техно парк",11000000),
("55\"","Samsung","Техно парк",13200000),("55\"","LG","Техно парк",14600000),("55\"","LG","Idea",22000000),
("65\"","Primer","Idea",6500000),("65\"","Ssmart","Idea",6500000),("65\"","Loretto","Idea",7000000),
("65\"","Haier","Техно парк",13000000),("65\"","Samsung","Idea",13000000),
("65\"","LG","Техно парк",23520000),("65\"","Samsung","Техно парк",31210000)]
wb = Workbook(); ws = wb.active; ws.title = "Narx"
hdr = ["№","Дюйм","Бренд","Дўкон","Нарх (1 та)","6 та","8 та"]
ws.append(hdr)
thin = Side(style="thin", color="999999"); b = Border(left=thin,right=thin,top=thin,bottom=thin)
for c in ws[1]:
    c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="1F4E78")
    c.alignment = Alignment(horizontal="center"); c.border = b
green = PatternFill("solid", fgColor="C6EFCE")
for size in ('55"','65"'):
    mn = min(r[3] for r in rows if r[0]==size)
    for r in [x for x in rows if x[0]==size]:
        i = ws.max_row
        # oddiy son qiymatlari (formula emas) - har qanday ko'rgichda ko'rinadi
        ws.append([i, r[0], r[1], r[2], r[3], r[3]*6, r[3]*8])
        for c in ws[ws.max_row]:
            c.border = b
            if r[3]==mn: c.fill = green
for row in ws.iter_rows(min_row=2, min_col=5, max_col=7):
    for c in row: c.number_format = '#,##0'
for col,w in zip("ABCDEFG",[5,8,12,14,16,18,18]): ws.column_dimensions[col].width = w
ws.freeze_panes = "A2"
wb.save(r"D:\it-agent\data\ish\tv_narx_6_8_tayyor.xlsx")
from openpyxl import load_workbook
w = load_workbook(r"D:\it-agent\data\ish\tv_narx_6_8_tayyor.xlsx").active
for r in list(w.iter_rows(values_only=True))[:4]: print(r)
print(w.max_row-1, "qator")
