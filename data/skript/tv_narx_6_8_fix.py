from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
rows = [
("55\"","Honor","Idea",4300000),("55\"","Primer","Idea",4900000),("55\"","Artel","Idea",5000000),
("55\"","Ssmart","Idea",5000000),("55\"","Loretto","Idea",5300000),("55\"","Samsung","Idea",7000000),
("55\"","Primer","Техно парк",7500000),("55\"","Haier","Техно парк",11000000),
("55\"","Samsung","Техно парк",13200000),("55\"","LG","Техно парк",14600000),("55\"","LG","Idea",22000000),
("65\"","Primer","Idea",6500000),("65\"","Ssmart","Idea",6500000),("65\"","Loretto","Idea",7000000),
("65\"","Haier","Техно парк",13000000),("65\"","Samsung","Idea",13000000),
("65\"","LG","Техно парк",23520000),("65\"","Samsung","Техно парк",31210000)]
wb=Workbook(); ws=wb.active; ws.title="Нарх"
hd=["Дюйм","Бренд","Дўкон","Нарх (1 та)","6 та","8 та"]
b=Side(style="thin"); bd=Border(left=b,right=b,top=b,bottom=b)
for c,h in enumerate(hd,1):
    x=ws.cell(1,c,h); x.font=Font(bold=True); x.border=bd; x.alignment=Alignment(horizontal="center")
    x.fill=PatternFill("solid",fgColor="D9E1F2")
green=PatternFill("solid",fgColor="C6EFCE")
mins={}
for r in rows: mins[r[0]]=min(mins.get(r[0],10**12),r[3])
for i,r in enumerate(rows,2):
    for c,v in enumerate(r,1): ws.cell(i,c,v)
    ws.cell(i,5,f"=D{i}*6"); ws.cell(i,6,f"=D{i}*8")
    for c in range(1,7):
        x=ws.cell(i,c); x.border=bd
        if c>=4: x.number_format="#,##0"
        if r[3]==mins[r[0]]: x.fill=green
for col,w in zip("ABCDEF",[8,12,14,16,18,18]): ws.column_dimensions[col].width=w
wb.save(r"D:\it-agent\data\ish\tv_narx_6_8.xlsx")
