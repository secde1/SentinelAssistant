from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

rows = [
    ('55"', 'V6C', 370),
    ('55"', 'T6D', 390),
    ('65"', 'V6C', 500),
    ('65"', 'T6D', 520),
]
wb = Workbook()
ws = wb.active
ws.title = 'TV narx'
ws.append(['Диагональ', 'Модель', 'Нарх ($)'])
for r in rows:
    ws.append(list(r))
thin = Side(style='thin')
for row in ws.iter_rows():
    for c in row:
        c.border = Border(left=thin, right=thin, top=thin, bottom=thin)
        c.alignment = Alignment(horizontal='center')
for c in ws[1]:
    c.font = Font(bold=True, color='FFFFFF')
    c.fill = PatternFill('solid', fgColor='305496')
for col in 'ABC':
    ws.column_dimensions[col].width = 16
ws.append([])
ws.append(['Манба: Нигматов юборган нарх рўйхати (2026-10-29)'])
wb.save(r'D:\it-agent\data\ish\tv_narx.xlsx')
