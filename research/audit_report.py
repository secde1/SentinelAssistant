"""SENTINAL agenti auditi: funksiyalar va kamchiliklar -> Word fayl (data/chiqish/ ga tushadi va Telegram'ga yuboriladi).

Bu hisobot statik tekshiruv (kod, jurnal, testlar, MT5 tarixi) va gate sinov buyruqlariga asoslangan. Jonli penetratsion
test emas. Raqamlar 2026-11-08 holatiga.
"""
from __future__ import annotations

import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"D:\it-agent\data\chiqish\SENTINAL_AUDIT_2026-11-08.docx")

COLORS = {"Yuqori": "F8D7DA", "O'rta": "FFF3CD", "Past": "E2EFDA"}

FUNCS = [
    ("IT-administratorlik", "PowerShell (WinRM), SSH, HTTP API, tekshirish, zaxira nusxa, inventar, parol generatsiyasi, Zabbix kuzatuvi, "
     "kunlik tekshiruv", "Ishlaydi", "srv-file01 ga WinRM parol rad etilgan (xotirada); Zabbix sozlanmagan; ssh/http_api/proactive testlari yo'q"),
    ("Xavfsizlik (gate)", "5 daraja (READ, INTERNAL, CHANGE, DANGER, BLOCK), egasi tasdig'i, maxfiy yashirish, natija tekshiruvi",
     "Ishlaydi", "Regex asosida: aylanib o'tish yo'llari bor (3-bo'lim, K-03)"),
    ("Shaxsiy yordamchi", "Word/Excel/PDF o'qish va yaratish (formulali Excel, kesh qiymat), fayl saralash, veb-qidiruv, ovozli xabar (lokal STT)",
     "Ishlaydi", "STT va reels tool'lari uchun avtotest yo'q"),
    ("Xotira va o'rganish", "skill'lar, xotira (fakt, tarix, inventar), shaxsiyat, haftalik xulosa", "Ishlaydi",
     "Xotira (102 KB) o'sib boradi, tozalanmaydi; ichki IP/hostlar GitHub'ga ketadi"),
    ("Telegram", "28 buyruq, tasdiq tugmalari, progress, fon topshiriqlar, Business, shaxsiy chat/guruh ajratilgan", "Ishlaydi",
     "bot.py 722 qator, buyruqlar if/elif zanjirida"),
    ("Reels studiyasi", "Ssenariy, ovoz, kadr, QC, egasi tasdig'i", "Qisman", "Instagram'ga joylash ulanmagan (2-bosqich)"),
    ("Veb-dashboard", "Qurilmalar, faoliyat, trading (faqat o'qish), 127.0.0.1:8790", "Ishlaydi", "Faqat bitta mahalliy foydalanuvchi, boshqaruv yo'q"),
    ("Trading tadqiqoti (V16)", "Tahlil, paper savdo, natija kuzatuvi, backtest, hisobotlar, iqtisodiy kalendar", "Ishlaydi",
     "Foydali strategiya isbotlanmagan"),
    ("MT5 ma'lumoti va DEMO savdo", "Faqat o'qish ulanishi, tarix, DEMO zdelka (`trading_mt5_order`), pozitsiya monitoringi", "Ishlaydi",
     "Chatdan ochilgan zdelkada kunlik zarar va takroriy kirish tekshiruvi yo'q (K-01)"),
    ("Signal tizimi (V22)", "10 mezonli ball, callback tugmalar, paper + MT5 DEMO zdelka, shaxsiy chat", "Ishlaydi (live)",
     "Faqat 1H, 7 instrument; hozircha faqat WATCH darajali setup; 3 ta simvolda broker savdoni yopgan"),
    ("Strategiya laboratoriyasi (V21, V23)", "5 yillik test, IS/OOS, walk-forward, Holm, korrelyatsiya, 7 faol/arxiv/nomzod strategiya",
     "Ishlaydi", "Hech bir strategiya tuzatmadan o'tmadi; korrelyatsiya himoyasi ulanmagan"),
    ("Tungi tadqiqot (V26)", "21:00-05:00 GitHub/internet/YouTube -> Excel + Word reja", "Ishlaydi", "Sayoz (1-2 daqiqa/faza), YouTube ko'rilmaydi"),
    ("TradingView (V17)", "Pine tayyorlash va OCR bilan tekshirish (Desktop + brauzer)", "Ishlaydi", "GUI/OCR ga bog'liq, nozik"),
    ("Chiqish papkasi (V27)", "data/chiqish/ dagi fayllar shaxsiy chatga yuboriladi", "Yangi", "Faqat ruxsat etilgan kengaytmalar, 20 MB gacha"),
]

# (ID, soha, kamchilik, dalil, xavf, tavsiya, hajm)
ISSUES = [
    ("K-01", "Trading", "Chatdan ochilgan DEMO zdelkada himoya yetarli emas",
     "`DemoTrader.open` faqat lot <= 0.10, pozitsiyalar <= 3 va SL ni tekshiradi. Kunlik zarar chegarasi, shu simvolda takroriy kirish va "
     "1% riskdan lot hisoblash faqat signal (HA) yo'lida. 07.11 dagi BTC zdelka: lot 0.03, SL = 0.22 ATR(1h), spred riskning 11% i; SL da yopildi (-1.73).",
     "Yuqori", "Tekshiruvlarni `DemoTrader` ichiga ko'chirish (ikkala yo'l uchun bitta); lotni 1% riskdan hisoblash; SL ni kamida 1 ATR(1h) qilish.", "M"),
    ("K-02", "Trading", "Hech bir strategiya foydali deb isbotlanmagan",
     "5 yil, 7 instrument, H1/H4, spred bilan: 98 + 56 kombinatsiya; Holm tuzatmasidan o'tgani yo'q. Eng yaxshisi XAU H4 MA-CROSS: +0.44R, 57 savdo, Holm p=0.196; "
     "XAU H4 TL-BREAK p=0.082. Natijalar oltin o'sishiga bog'liq bo'lishi mumkin.",
     "Yuqori", "Demo'da forward-test (3-6 oy), kattalashtirmaslik; yangi nomzodlarni faqat o'tkazilgan (ushlab turilgan) davrda baholash.", "L"),
    ("K-03", "Xavfsizlik", "Gate regex'i aylanib o'tiladi",
     "Sinov: `cmd /c del /q C:\\temp\\*` -> READ; `$c='Remove-'+'Item'; & $c ... -Recurse` -> READ; `net user admin2 ... /add` va `reg add HKLM` -> CHANGE (DANGER emas); "
     "PowerShell orqali `Set-Content ...\\agent\\gate.py` -> CHANGE (BLOCK emas).",
     "Yuqori", "`cmd /c`, chaqiruv operatori (`&`) va o'zgaruvchidan buyruq — DANGER; yadro kodiga har qanday yozish — BLOCK; yangi testlar.", "M"),
    ("K-04", "Xavfsizlik", "Maxfiy ma'lumot ochiq faylda, skriptlar gate'dan tashqarida ishlaydi",
     "Bot tokeni `data\\ish\\bot_env.json` da ochiq matn; bot yozgan skriptlar (`auto_scan_alert.py`, `btc_alert.py`) Task Scheduler orqali nazoratsiz ishlaydi va tokenni "
     "o'zi o'qiydi. Yaratilishi gate'da CHANGE, lekin keyingi xatti-harakati ko'rilmaydi.",
     "Yuqori", "Tokenni Windows Credential Manager/DPAPI ga o'tkazish; jadvalga qo'yilgan skriptlar ro'yxatini kuzatish va ko'rib chiqish talab qilish.", "M"),
    ("K-05", "Ishonchlilik", "Kompyuter uxlasa hamma jadval to'xtaydi",
     "08.11 da 03:44-05:49 oralig'ida agent jurnali yo'q (Windows vaqt o'zgardi voqealari): tungi hisobot 49 daqiqa kechikdi, monitoring ko'r qoldi. Tashqi nazoratchi yo'q.",
     "Yuqori", "Tarmoqdan ishlaganda uyquni o'chirish yoki 04:55 da uyg'otuvchi vazifa; uyg'ongach texnik xabar.", "S"),
    ("K-06", "Obuna", "Claude Pro limitiga qaramlik",
     "Haftalik limit 78-83% ko'rilgan; tungi tadqiqot, chat va avto-topshiriqlar bir limitni bo'lishadi. Limit tugasa agent to'xtaydi (loyihada ataylab).",
     "Yuqori", "Ustuvorlik (chat > tungi tadqiqot), fazalarni kamaytirish, limit 80% dan oshsa tungi tadqiqotni to'xtatish.", "S"),
    ("O-01", "Signal", "Qamrov tor, signal kam",
     "Faqat 1H setup; 7 instrument; 3 faol strategiya; ADX bo'yicha qattiq rejim; tick-hajm; MT5 M15 tarixi <= 100 000 shamdan; forex/oltin/indeks dam olish kunlari yopiq. "
     "Hozir barcha topilmalar 4-6 ball (WATCH).", "O'rta", "H4 strategiyalarini (XAU H4) skanerga qo'shish; ballni forward natija bilan baholash.", "M"),
    ("O-02", "Broker", "Ayrim simvollarda savdo yopiq",
     "retcode 10017 «Trade disabled»: LTC, BNB, SOL (07.11). HA bosilgach rad etiladi, signal chiqarilgan paytda bu tekshirilmaydi.",
     "O'rta", "Signal yuborishdan oldin `order_check` yoki savdoga ruxsat etilgan simvollar ro'yxati.", "S"),
    ("O-03", "Trading", "Korrelyatsiya himoyasi ulanmagan",
     "`exposure.py` yozilgan (BTC-ETH 0.91), lekin signal va zdelka oqimiga ulanmagan: BTC va ETH bir yo'nalishda ochilishi mumkin.", "O'rta",
     "`check()` ni HA oqimiga ulash (samarali risk <= 1.75%).", "S"),
    ("O-04", "Xabarlar", "Yetkazish kafolati bir tekis emas",
     "Pozitsiya monitoringida bazali navbat va qayta urinish bor; signal va boshqa bot xabarlari «yaxshi harakat» (FAILED/UNKNOWN qayta yuborilmaydi).",
     "O'rta", "Signallarni ham navbatga o'tkazish.", "M"),
    ("O-05", "Tungi tadqiqot", "Sifat va takrorlanish",
     "Faza 1-2 daqiqa; birinchi tunda 15 topilma (YouTube 2). URL faqat bir tun ichida takrorlanmaydi: bir xil loyihalar har kecha qaytishi mumkin. Litsenziya/sana ko'p hollarda noma'lum. "
     "Qayta ishga tushganda ishlayotgan topshiriq «tugadi» deb belgilanadi, garchi o'lgan bo'lsa ham.", "O'rta",
     "Oldingi kunlar bilan URL bo'yicha taqqoslash; chuqurroq qidiruv (faza uzunligi); topshiriq holatini qayta tekshirish.", "M"),
    ("O-06", "Testlar", "Sinalmagan modullar",
     "13 modulda test yo'q: claude_cli, proactive (Zabbix), ssh, http_api, knowledge, reels tool, stt, panel, control, console, logsetup, weekly, agentstate. "
     "Jonli MT5 testlari odatda o'tkazib yuboriladi. CI yo'q.", "O'rta", "Eng muhimlari uchun test (proactive, ssh, claude_cli); GitHub Actions bilan avtomatik ishga tushirish.", "M"),
    ("O-07", "Kod sifati", "Katta fayllar va keng `except`",
     "bot.py 722, signals.py 713, panel.py 630, loop.py 628 qator; bot.py da 28 ta buyruq if/elif zanjirida. 71 ta `except Exception` (69 tasi izohli) — "
     "xatoni yashirishi mumkin (masalan, test signal xatosi jim yutilgan edi, bugun tuzatildi). research/lab.py backtest sikli nusxasi.",
     "O'rta", "Buyruqlarni jadval/reyestrga o'tkazish; keng except o'rniga aniq xato turlari; lab ni asosiy backtest bilan birlashtirish.", "L"),
    ("O-08", "Maxfiylik", "Xotira o'sadi va GitHub'ga ketadi",
     "`data/xotira/tarix.md` ~87 KB (jami 102 KB), ichki IP, hostnom, bitta MAC manzil; repo anonim so'rovga 404 beradi (ehtimol maxfiy), lekin tekshirilmagan.",
     "O'rta", "GitHub'da repo Private ekanini tekshirish; tarixni qirqish/arxivlash; ichki manzillarni niqoblash.", "S"),
    ("O-09", "Git", "O'zgarishlar yuborilmagan",
     "29 fayl o'zgargan va yuborilmagan (tungi tadqiqot, demo zdelka, chiqish papkasi, eski skaner tuzatishi). Teglar va CI yo'q.", "O'rta",
     "Commit va push; versiya teglari.", "S"),
    ("O-10", "IT-admin", "Ulanish va sozlash bo'shliqlari",
     "srv-file01 ga WinRM (NTLM) parol rad etilgan (xotira yozuvi); NB-XS-TEX02 vaqti-vaqti bilan; Zabbix «url/host yo'q»; inventar parollari eskirgan bo'lishi mumkin.",
     "O'rta", "Inventarni yangilash; ulanish salomatligi tekshiruvi; Zabbix ulash.", "M"),
    ("O-11", "TradingView", "GUI/OCR ga bog'liq",
     "Interfeys tili/tartibi o'zgarsa buziladi; brauzerda faqat faol tab; bitta kompyuterda sinalgan.", "O'rta", "Indikator o'z-o'zini tekshirishini asosiy dalil qilib qoldirish; yangilanishda qayta sinash.", "S"),
    ("O-12", "Reels", "Joylash yo'q",
     "Instagram'ga joylash (2-bosqich) ulanmagan; TTS tashqi xizmatlarga bog'liq; sifat o'lchovi yo'q.", "O'rta", "Meta API ulash yoki qo'lda joylashni rasmiylashtirish.", "L"),
    ("P-01", "Til", "Til va yozuv aralashishi",
     "Xabar va promptlar o'zbek (lotin/kirill) va inglizcha aralash; sessiyada rus tilida javob berilgan holatlar bo'ldi (egasi o'zbekcha so'ragan).", "Past",
     "Javob tilini sozlama bilan majburlash va test.", "S"),
    ("P-02", "Interfeys", "Har javobda obuna foizi",
     "Har javob oxirida «Pro obuna (5 soatlik X%, haftalik Y%)» — shovqin. Limit ogohlantirishi bugun bir marta/oyna qilib tuzatildi.", "Past",
     "Foizni faqat 80% dan oshganda ko'rsatish.", "S"),
    ("P-03", "Hujjat", "README juda uzun",
     "~1100 qator, versiyalar aralash.", "Past", "Bo'limlarga ajratish (docs/).", "S"),
    ("P-04", "Zaxira", "Zaxira faqat mahalliy",
     "`data\\zaxira` va git; `data\\ish` (tokenlar, holat) tashqarida emas. Bitta kompyuter — yagona nuqta.", "Past", "Shifrlangan tashqi nusxa.", "M"),
    ("P-05", "Konfiguratsiya", "Qattiq qiymatlar va bog'lanmagan versiyalar",
     "Vaqt zonasi Asia/Tashkent, universum va chegaralar sozlama faylida; kutubxonalar oraliq versiya bilan (qulf fayl yo'q).", "Past", "Qulf fayl; sozlamalarni bir joyga.", "S"),
]

PLAN = [
    ("1", "K-01", "DemoTrader ichiga kunlik zarar, takroriy kirish va 1% risk lotini ko'chirish; SL >= 1 ATR(1h)", "1-2 kun"),
    ("2", "K-03", "Gate: cmd /c, `&` o'zgaruvchi, net user/reg add -> DANGER; yadro kodiga yozish BLOCK; testlar", "1 kun"),
    ("3", "K-05", "Uyquni o'chirish yoki 04:55 uyg'otish vazifasi (egasi bilan kelishib)", "1 soat"),
    ("4", "K-04", "Bot tokenini DPAPI/Credential Manager ga; jadvaldagi skriptlar ro'yxati", "1-2 kun"),
    ("5", "K-06", "Chat ustuvorligi va 80% limitda tungi tadqiqotni to'xtatish", "0.5 kun"),
    ("6", "O-02, O-03", "Savdoga ruxsat etilgan simvollar filtri va korrelyatsiya himoyasini HA oqimiga ulash", "1 kun"),
    ("7", "O-09, O-08", "Commit/push va GitHub maxfiyligini tekshirish; xotirani qirqish", "0.5 kun"),
    ("8", "K-02", "Demo'da forward-test: signal va zdelka natijalarini 3 oy yig'ish, keyin qayta baholash", "doimiy"),
]

STRENGTHS = [
    "Gate 5 darajali, egasi tasdig'i va natija tekshiruvi kodda; sinov to'plami ichida tekshiriladi.",
    "Savdo kodda faqat DEMO: hisob turi har buyurtmadan oldin o'qiladi, REAL rad etiladi; AUTO rejim yo'q; buyurtma DANGER sifatida tasdiq so'raydi.",
    "MT5 ma'lumot qatlami faqat o'qish ruxsat ro'yxati orqali; tarixiy vaqt faqat jonli tikdan UTC ga o'giriladi (taxmin yo'q).",
    "Tahlil va tarixiy natijalar o'zgarmas (baza triggerlari); look-ahead yo'q; xarajat va ko'p sinov tuzatmasi hisobga olinadi.",
    "Pozitsiya yopilishi faqat MT5 tarixida tasdiqlangandan keyin xabar qilinadi; xabar navbati dublikatsiz va yo'qolmaydi.",
    "325 avtomatik test, har yangi funksiya uchun yangi testlar; mavjud funksiyalar buzilmasligi ta'minlangan.",
    "Agent o'zining xatosini (eski skaner, jim yutilgan xato, ogohlantirish takrori) aniqlab tuzatish imkoniga ega.",
]

LIMITS = [
    "Bu statik tekshiruv: kod, jurnal, testlar, MT5 tarixi va gate sinov buyruqlari. Penetratsion test va yuklama sinovi o'tkazilmagan.",
    "Gate sinovi 18 ta buyruqda; to'liq qamrov emas.",
    "MT5 faqat DEMO hisobda va bitta terminalda ko'rilgan (Exness REAL terminali ochilmagan).",
    "Veb-sahifalar va tashqi xizmatlar (Instagram, Zabbix, srv-file01) bu tekshiruvda jonli ishga tushirilmagan.",
    "Foydalilik darajalari (Yuqori/O'rta/Past) muallifning bahosi, ehtimollik hisobi emas.",
]


def shade(cell, color: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color)
    tcPr.append(shd)


def table(doc, headers, rows, widths=None, risk_col=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for c, h in zip(t.rows[0].cells, headers):
        c.text = ""
        r = c.paragraphs[0].add_run(h)
        r.bold, r.font.size = True, Pt(9)
        shade(c, "D9E2F3")
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            run = cells[i].paragraphs[0].add_run(str(v))
            run.font.size = Pt(8.5)
            if risk_col is not None and i == risk_col and v in COLORS:
                shade(cells[i], COLORS[v])
                run.bold = True
    if widths:
        for row in t.rows:
            for c, w in zip(row.cells, widths):
                c.width = Pt(w)
    return t


def build(path: Path) -> Path:
    d = Document()
    d.styles["Normal"].font.name = "Calibri"
    d.styles["Normal"].font.size = Pt(10.5)
    d.add_heading("SENTINAL agenti: funksiyalar va kamchiliklar auditi", 0)
    p = d.add_paragraph("Sana: 2026-11-08 · Muallif: agentning o'zi (statik tekshiruv) · Til: o'zbekcha")
    p.runs[0].italic = True

    d.add_heading("1. Qisqa xulosa", 1)
    d.add_paragraph(
        f"Agent 14 sohada ishlaydi: IT-administratorlik, shaxsiy yordamchi, trading tadqiqoti, MT5, signal tizimi, tungi tadqiqot va boshqalar. "
        f"Kod ~{6417 + 2596 + 6328 + 1997 + 2037 + 916:,} qator (Python), 34 tool, 28 Telegram buyruq tarmog'i, 325 avtomatik test. "
        f"Audit {len(ISSUES)} ta kamchilik topdi: {sum(1 for i in ISSUES if i[4] == 'Yuqori')} yuqori, "
        f"{sum(1 for i in ISSUES if i[4] == 'O' + chr(39) + 'rta')} o'rta, {sum(1 for i in ISSUES if i[4] == 'Past')} past xavfli.")
    d.add_paragraph("Eng muhim uchtasi: (1) chatdan ochilgan demo zdelkada himoya yetarli emas (K-01); (2) hech bir strategiya foydali deb "
                    "isbotlanmagan (K-02); (3) gate regex'i ba'zi xavfli buyruqlarni aylanib o'tadi (K-03). Hozircha savdo faqat DEMO hisobda, "
                    "shuning uchun real pul xavfi yo'q, lekin K-01 va K-03 real hisobga o'tishdan oldin albatta tuzatilishi kerak.")

    d.add_heading("2. Funksiyalar xaritasi", 1)
    table(d, ["Soha", "Nima qiladi", "Holat", "Asosiy cheklov"], FUNCS, [85, 190, 55, 170])

    d.add_heading("3. Kamchiliklar", 1)
    d.add_paragraph("Xavf: Yuqori — real zarar yoki xavfsizlik teshigi; O'rta — ishonchlilik yoki sifat; Past — qulaylik. "
                    "Hajm: S ~ bir kunga qadar, M ~ 1-3 kun, L ~ bir haftadan ko'p.")
    for group, title in (("Yuqori", "3.1 Yuqori xavf"), ("O'rta", "3.2 O'rta xavf"), ("Past", "3.3 Past xavf")):
        d.add_heading(title, 2)
        rows = [(i[0], i[1], i[2], i[3], i[4], i[5], i[6]) for i in ISSUES if i[4] == group]
        table(d, ["ID", "Soha", "Kamchilik", "Dalil", "Xavf", "Tavsiya", "Hajm"], rows, [30, 50, 85, 170, 36, 120, 28], risk_col=4)
        d.add_paragraph()

    d.add_heading("4. Tuzatish rejasi (ustuvorlik bo'yicha)", 1)
    table(d, ["#", "Kamchilik", "Ish", "Vaqt"], PLAN, [20, 60, 330, 60])
    d.add_paragraph("Hammasi taklif. Asosiy kodni o'zgartirish va tizim sozlamalari (uyqu, vazifalar) egasining tasdig'i bilan amalga oshiriladi.")

    d.add_heading("5. Yaxshi ishlayotgan tomonlar", 1)
    for s in STRENGTHS:
        d.add_paragraph(s, style="List Bullet")

    d.add_heading("6. Auditning cheklovlari", 1)
    for s in LIMITS:
        d.add_paragraph(s, style="List Bullet")

    for sec in d.sections:
        sec.left_margin = sec.right_margin = Pt(42)
        sec.top_margin = sec.bottom_margin = Pt(48)
    path.parent.mkdir(parents=True, exist_ok=True)
    d.save(path)
    return path


if __name__ == "__main__":
    print(build(OUT))
