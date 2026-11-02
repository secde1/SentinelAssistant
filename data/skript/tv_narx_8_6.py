from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
rows = [
('55"','Honor','Idea',4300000),('55"','Primer','Idea',4900000),('55"','Artel','Idea',5000000),
('55"','Ssmart','Idea',5000000),('55"','Loretto','Idea',5300000),('55"','Samsung','Idea',7000000),
('55"','Primer','Техно парк',7500000),('55"','Haier','Техно парк',11000000),('55"','Samsung','Техно парк',13200000),
('55"','LG','Техно парк',14600000),('55"','LG','Idea',22000000),
('65"','Primer','Idea',6500000),('65"','Ssmart','Idea',6500000),('65"','Loretto','Idea',7000000),
('65"','Haier','Техно парк',13000000),('65"','Samsung','Idea',13000000),('65"','LG','Техно парк',23520000),
('65"','Samsung','Техно парк',31210000)]
wb=Workbook(); ws=wb.active; ws.title='Narx'
h=['Дюйм','Бренд','Дўкон','Нарх (1 та)','6 та','8 та']
ws.append(h)
thin=Side(style='thin'); b=Border(left=thin,right=thin,top=thin,bottom=thin)
for c in ws[1]:
    c.font=Font(bold=True); c.fill=PatternFill('solid',fgColor='D9E1F2'); c.alignment=Alignment(horizontal='center'); c.border=b
for i,r in enumerate(rows,start=2):
    ws.append(list(r)+[f'=D{i}*6',f'=D{i}*8'])
    for c in ws[i]:
        c.border=b
    for col in 'DEF': ws[f'{col}{i}'].number_format='#,##0'
for size in ('55"','65"'):
    idx=[i for i,r in enumerate(rows,start=2) if r[0]==size]
    m=min(idx,key=lambda i:rows[i-2][3])
    for c in ws[m]: c.fill=PatternFill('solid',fgColor='C6EFCE')
for col,w in zip('ABCDEF',[8,14,14,16,16,16]): ws.column_dimensions[col].width=w
wb.save(r'D:\it-agent\data\ish\tv_narx_8_6.xlsx')
print('OK')
