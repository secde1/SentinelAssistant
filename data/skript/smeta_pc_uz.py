from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
RATE = 12000
items = [
 ("Процессор", "Intel i7-14700KF", 4400000, "Mytech.uz (бошқа: openshop.uz 4 899 000)"),
 ("Плата", "ASUS Z790-AYW WIFI (Gigabyte Z790 топилмади)", 2783549, "prom.uz, Prime Desktop"),
 ("Совутгич", "DeepCool LM360", 1210239, "prom.uz, Prime Desktop"),
 ("Хотира", "Teamgroup DDR5 32GB 5600 (2x16) RGB", 5312500, "cyber.uz (mediapark.uz 5 700 000; Corsair glotr.uz 6 180 000)"),
 ("Видеокарта", "MSI RTX 5060 Shadow 2X OC 8GB (ASUS 5060 нархи топилмади)", 4840956, "prom.uz"),
 ("Блок", "ASUS ROG Strix 750W Gold", 1355467, "prom.uz, Desktop Digital (Corsair RM750E 1 936 382)"),
 ("Корпус", "DeepCool CG580 4F V2 (қора/оқ)", 968191, "prom.uz (4 вентилятор модел номидан, тасдиқланмаган)"),
]
wb = Workbook()
def sheet(ws, title, rows):
    ws.title = title
    ws.append(["№","Тур","Модель","Нарх (сўм)","Нарх ($)","Манба"])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="305496")
    for i, (t, m, p, s) in enumerate(rows, 1):
        ws.append([i, t, m, p, round(p/RATE), s])
    n = len(rows) + 1
    ws.append(["", "ЖАМИ", "", f"=SUM(D2:D{n})", f"=ROUND(D{n+1}/{RATE},0)", ""])
    for c in ws[n+1]: c.font = Font(bold=True)
    for r in ws.iter_rows(min_row=2, min_col=4, max_col=4):
        for c in r: c.number_format = '#,##0'
    for col, w in zip("ABCDEF", (5, 14, 55, 16, 10, 60)): ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
sheet(wb.active, "Смета 1 (рўйхатингиз)", items)
items2 = list(items)
items2[4] = ("Видеокарта", "Gigabyte RTX 5070 Windforce OC SFF 12GB", 8290137, "prom.uz (ASUS Prime 5070: 8 467 921)")
sheet(wb.create_sheet(), "Смета 2 (RTX 5070)", items2)
ws = wb.create_sheet("Изоҳ")
for r in ["Курс: 1$ = 12 000 сўм (тахминий, бугунги расмий курс топилмади).",
          "Нархлар 04.11.2026 да интернетдан олинди, дўконда ўзгариши мумкин.",
          "Смета 1 = сизнинг рўйхат, Ўзбекистон нархларида. Смета 2 = шу, фақат RTX 5060 ўрнига RTX 5070 12GB.",
          "Сизнинг нарх: 2226$ (рўйхат)."]:
    ws.append([r])
ws.column_dimensions["A"].width = 110
wb.save(r"D:\it-agent\data\ish\smeta_pc_uz.xlsx")
