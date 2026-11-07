from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
wb=Workbook(); ws=wb.active; ws.title="Солиштириш"
ws["A1"]="Компьютер сметаси (тузатилган, 04.11.2026)"; ws["A1"].font=Font(bold=True,size=13)
ws["A2"]="Курс (1$ = сўм):"; ws["B2"]=12000
h=["№","Тур","Сизга берилган","Нарх ($)","Топилган товар","Нарх (сўм)","Нарх ($)","Фарқ ($)","Омборда","Текширув","Манба"]
ws.append([]); ws.append(h)
rows=[
(1,"Процессор","Intel i7-14700KF",400,"Intel Core i7-14700KF BOX",4087000,"Бор","САЙТ САҲИФАСИ ОЧИЛДИ","glotr.uz/protsessor-intel-core-i7-14700kf-oem-p-910587"),
(2,"Плата","Gigabyte Z790",275,"Gigabyte Z790D AX DDR5 (Z790 EAGLE AX 2.64-3.49 млн)",2520000,"?","Қидирув натижаси, саҳифа очилмади","glotr.uz (ELSO.uz); mediapark.uz 3 268 000"),
(3,"Совутгич","Suv sovutgich 360 (L360)",125,"DeepCool LM360",1210239,"?","ТЕКШИРИЛМАГАН (олдинги нарх)","prom.uz — саҳифа топилмади"),
(4,"Хотира","DDR5 32GB (2x16) 5600",625,"Teamgroup DDR5 32GB 5600 RGB (16*2)",6875000,"ЙЎҚ","САЙТ САҲИФАСИ ОЧИЛДИ","cyber.uz/teamgroup-ddr5-32gb-5600mhz-rgb-16-2"),
(5,"Видеокарта","ASUS RTX 5060",638,"ASUS PRIME RTX 5060 8GB OC",5246000,"ЙЎҚ","САЙТ САҲИФАСИ ОЧИЛДИ","gshop.uz/product/7227 (avtech.uz ASUS Dual 5 906 250 — очилмади)"),
(6,"Блок","750W modular",63,"ASUS ROG Strix 750W Gold",1355467,"?","ТЕКШИРИЛМАГАН (олдинги нарх)","prom.uz — саҳифа топилмади"),
(7,"Корпус","Katta, 4 fan, oq",100,"DeepCool CG580 4F V2 WH (оқ)",976000,"Бор","САЙТ САҲИФАСИ ОЧИЛДИ","glotr.uz (bmarket.uz)"),
]
for i,r in enumerate(rows):
    n=5+i
    ws.append([r[0],r[1],r[2],r[3],r[4],r[5],f"=F{n}/$B$2",f"=G{n}-D{n}",r[6],r[7],r[8]])
ws.append(["","ЖАМИ","","=SUM(D5:D11)","","=SUM(F5:F11)","=SUM(G5:G11)","=SUM(H5:H11)"])
ws.append([]); ws.append(["Курс 12 000 тахминий. 'ТЕКШИРИЛМАГАН' нарх — тасдиқланмаган, дўконда аниқланг. Илгари ёзилган хотира нархи (5 312 500) хато эди."])
for c in ws[4]: c.font=Font(bold=True,color="FFFFFF"); c.fill=PatternFill("solid",fgColor="305496")
for col,w in zip("ABCDEFGHIJK",[4,12,24,10,46,14,10,10,10,34,52]): ws.column_dimensions[col].width=w
for r in range(5,13): ws.cell(r,6).number_format="#,##0"; ws.cell(r,7).number_format="0"; ws.cell(r,8).number_format="0"
wb.save(r"D:\it-agent\data\ish\smeta_pc_tuzatilgan.xlsx")
