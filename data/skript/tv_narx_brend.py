from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
wb=Workbook(); ws=wb.active; ws.title="TV narx"
ws.append(["Бренд","Диагональ","Модель","Нарх ($)"])
for r in [("TCL",'55"',"V6C",370),("TCL",'55"',"T6D",390),("TCL",'65"',"V6C",500),("TCL",'65"',"T6D",520)]:
    ws.append(r)
ws.append([])
ws.append(["Манба: Нигматов юборган нарх рўйхати (2026-10-29)"])
b=Side(style="thin"); 
for c in ws[1]:
    c.font=Font(bold=True,color="FFFFFF"); c.fill=PatternFill("solid",fgColor="1F4E78"); c.alignment=Alignment(horizontal="center")
for row in ws.iter_rows(min_row=1,max_row=5):
    for c in row: c.border=Border(left=b,right=b,top=b,bottom=b)
for col,w in zip("ABCD",(12,12,12,12)): ws.column_dimensions[col].width=w
wb.save(r"D:\it-agent\data\ish\tv_narx.xlsx")
