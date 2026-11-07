from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

RATE = 12000
wb = Workbook()
thin = Side(style="thin", color="999999")
B = Border(left=thin, right=thin, top=thin, bottom=thin)
HF = PatternFill("solid", fgColor="1F4E78")
TF = PatternFill("solid", fgColor="DDEBF7")
GF = PatternFill("solid", fgColor="E2EFDA")

def head(ws, row, cols):
    for i, c in enumerate(cols, 1):
        x = ws.cell(row=row, column=i, value=c)
        x.font = Font(bold=True, color="FFFFFF"); x.fill = HF
        x.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True); x.border = B

# (тур, сиз олган модел, сиз нархи $, УЗ модел, УЗ нарх сўм, манба)
items = [
 ("Процессор", "Intel i7-14700KF", 400, "Intel i7-14700KF", 4400000, "Mytech.uz (openshop.uz 4 899 000)"),
 ("Плата", "Gigabyte Z790", 275, "ASUS Z790-AYW WIFI (Gigabyte нархи топилмади)", 2783549, "prom.uz"),
 ("Совутгич", "Suv sovutgich 360 (L360)", 125, "DeepCool LM360", 1210239, "prom.uz"),
 ("Хотира", "DDR5 32GB (2x16) 5600", 625, "Teamgroup DDR5 32GB 5600 (2x16) RGB", 5312500, "cyber.uz (mediapark.uz 5 700 000)"),
 ("Видеокарта", "ASUS RTX 5060", 638, "MSI RTX 5060 Shadow 2X OC 8GB (ASUS нархи топилмади)", 4840956, "prom.uz (OLX.uz янги: 4 350 960)"),
 ("Блок", "750W modular", 63, "ASUS ROG Strix 750W Gold", 1355467, "prom.uz"),
 ("Корпус", "Katta, 4 fan, oq", 100, "DeepCool CG580 4F V2", 968191, "prom.uz"),
]

ws = wb.active; ws.title = "Солиштириш"
ws["A1"] = "Компьютер сметаси: сизга берилган нарх ва Ўзбекистон бозори"; ws["A1"].font = Font(bold=True, size=14)
ws["A2"] = "Курс (1$ = сўм):"; ws["B2"] = RATE; ws["B2"].fill = GF; ws["A2"].font = Font(bold=True)
head(ws, 4, ["№", "Тур", "Сизга берилган", "Нарх ($)", "Ўзбекистонда топилган", "Нарх (сўм)", "Нарх ($)", "Фарқ ($)", "Манба"])
r = 5
for n, (t, m1, p1, m2, p2, src) in enumerate(items, 1):
    vals = [n, t, m1, p1, m2, p2, f"=ROUND(F{r}/$B$2,0)", f"=G{r}-D{r}", src]
    for c, v in enumerate(vals, 1):
        x = ws.cell(row=r, column=c, value=v); x.border = B
        x.alignment = Alignment(wrap_text=True, vertical="center")
    ws.cell(row=r, column=6).number_format = "#,##0"
    r += 1
ws.cell(row=r, column=2, value="ЖАМИ")
ws.cell(row=r, column=4, value=f"=SUM(D5:D{r-1})")
ws.cell(row=r, column=6, value=f"=SUM(F5:F{r-1})")
ws.cell(row=r, column=7, value=f"=ROUND(F{r}/$B$2,0)")
ws.cell(row=r, column=8, value=f"=G{r}-D{r}")
for c in range(1, 10):
    x = ws.cell(row=r, column=c); x.font = Font(bold=True); x.fill = TF; x.border = B
ws.cell(row=r, column=6).number_format = "#,##0"
ws.cell(row=r + 2, column=1, value="Манфий фарқ = Ўзбекистонда арзонроқ. Плата, хотира ва видеокарта бренди сиздаги рўйхатдан фарқ қилади: бу тўлиқ бир хил солиштириш эмас.")
ws.cell(row=r + 3, column=1, value="Нархлар 04.11.2026 да интернетдан олинди (prom.uz, cyber.uz, mytech.uz, mediapark.uz, olx.uz). Дўконда ўзгариши мумкин. Курс тахминий.")
for i, w in enumerate([5, 13, 24, 11, 42, 15, 11, 11, 36], 1):
    ws.column_dimensions[get_column_letter(i)].width = w

# 2-варақ: расмий смета
w2 = wb.create_sheet("Расмий смета")
w2["A1"] = "СМЕТА (харид қиймати ҳисоби)"; w2["A1"].font = Font(bold=True, size=14)
w2["A2"] = "Буюртмачи: ____________________   Сана: 04.11.2026   Смета №: ______"
head(w2, 4, ["№", "Номи ва характеристикаси", "Ўлчов бирлиги", "Миқдори", "Нархи (сўм)", "Суммаси (сўм)", "Изоҳ"])
r = 5
for n, (t, m1, p1, m2, p2, src) in enumerate(items, 1):
    for c, v in enumerate([n, f"{t}: {m2}", "дона", 1, p2, f"=D{r}*E{r}", "кафолат: ___ ой"], 1):
        x = w2.cell(row=r, column=c, value=v); x.border = B
        x.alignment = Alignment(wrap_text=True, vertical="center")
    w2.cell(row=r, column=5).number_format = "#,##0"; w2.cell(row=r, column=6).number_format = "#,##0"
    r += 1
tot = r
rows = [("Жами (ҚҚСсиз)", f"=SUM(F5:F{r-1})"), ("ҚҚС 12%", f"=ROUND(F{r}*0.12,0)"), ("Жами ҚҚС билан", f"=F{r}+F{r+1}")]
for i, (lab, f) in enumerate(rows):
    w2.cell(row=r + i, column=2, value=lab); w2.cell(row=r + i, column=6, value=f)
    for c in range(1, 8):
        x = w2.cell(row=r + i, column=c); x.font = Font(bold=True); x.fill = TF; x.border = B
    w2.cell(row=r + i, column=6).number_format = "#,##0"
w2.cell(row=r + 4, column=2, value="Эслатма: нархлар дўкон нархи; ҚҚС қўшилган-қўшилмаганини сотувчи билан аниқланг (ҚҚС ставкаси 12%).")
w2.cell(row=r + 6, column=2, value="Тузувчи: ____________ (имзо)      Тасдиқловчи: ____________ (имзо) М.П.")
for i, w in enumerate([5, 60, 12, 10, 16, 18, 20], 1):
    w2.column_dimensions[get_column_letter(i)].width = w

# 3-варақ: қўлланма
w3 = wb.create_sheet("Смета қандай тузилади")
lines = [
 "СМЕТАНИ ТАШКИЛОТ УЧУН ҚАНДАЙ РАСМИЙЛАШТИРИШ КЕРАК",
 "",
 "1. Сарлавҳа: 'Смета №__' , сана, буюртмачи ташкилот номи (XONSAROY GROUP МЧЖ), асос (хизмат хати ёки буйруқ).",
 "2. Жадвал устунлари: № | Номи ва характеристикаси | Ўлчов бирлиги | Миқдори | Нархи | Суммаси | Изоҳ.",
 "3. Ҳар қатор: аниқ модел (масалан 'Intel Core i7-14700KF'), 'процессор' деб ёзиш етарли эмас.",
 "4. Нарх манбаси: камида 2-3 та таклиф (тижорий таклиф / сайт скриншоти). Энг арзони танланади, сабаби ёзилади.",
 "5. Жами: ҚҚСсиз сумма, ҚҚС 12%, ҚҚС билан жами. Пастда сумма сўзлар билан.",
 "6. Кафолат муддати ва етказиб бериш шарти алоҳида ёзилади.",
 "7. Имзолар: тузувчи (IT), молия бўлими/бош ҳисобчи, директор, муҳр.",
 "8. Иловалар: сотувчиларнинг нарх таклифлари (счёт-фактура ёки счёт-оферта).",
 "9. Тижорий таклифсиз 'интернетдан олинган нарх' расмий ҳужжат бўлмайди: тасдиқлаш учун дўконлардан счёт олинг.",
 "10. Курс билан эмас, сўмда тузинг. Долларда бўлса ҳам, Марказий банк курси ва санаси ёзилади.",
 "",
 "Эслатма: давлат харидлари (tender / E-xarid) бўлса, талаблар бошқача: спецификация брендсиз ёзилади (характеристика бўйича).",
]
for i, t in enumerate(lines, 1):
    w3.cell(row=i, column=1, value=t).alignment = Alignment(wrap_text=True)
w3["A1"].font = Font(bold=True, size=13)
w3.column_dimensions["A"].width = 130

wb.save(r"D:\it-agent\data\ish\smeta_pc_yakuniy.xlsx")
print("OK")
