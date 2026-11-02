from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

NUM = '001/26'
DATE_TXT = '2026 yil «30» oktyabr'
DATE_XL = '30.10.2026'
PHONE = '+998 70 308 50 78'
FIO = "Saidkosimov Boburmirzo Murod o'g'li"
PASS = 'AE5553982'
DOCX = r'D:\it-agent\data\ish\Хат_№001-26_2026-10-30.docx'
XLSX = r'D:\it-agent\data\ish\Chiquvchi_xatlar_jurnali.xlsx'

d = Document()
s = d.sections[0]
s.page_width, s.page_height = Cm(21), Cm(29.7)
s.left_margin, s.right_margin, s.top_margin, s.bottom_margin = Cm(2), Cm(1.5), Cm(2), Cm(2)
st = d.styles['Normal']
st.font.name = 'Times New Roman'; st.font.size = Pt(14)
st.element.rPr.rFonts.set(qn('w:eastAsia'), 'Times New Roman')
st.paragraph_format.line_spacing = 1.15
st.paragraph_format.space_after = Pt(0)

def p(t='', al=None, b=False, after=0, before=0, indent=None, left=None):
    x = d.add_paragraph(); r = x.add_run(t); r.bold = b
    if al is not None: x.alignment = al
    pf = x.paragraph_format
    pf.space_after = Pt(after); pf.space_before = Pt(before)
    if indent: pf.first_line_indent = Cm(indent)
    if left: pf.left_indent = Cm(left)
    return x

C, R, L, J = (WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.RIGHT,
              WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.JUSTIFY)

h = p('"XONSAROY GROUP" MCHJ', C, True, after=4)
h.runs[0].font.size = Pt(14)
# ostida chiziq
pPr = h._p.get_or_add_pPr(); bd = OxmlElement('w:pBdr'); bt = OxmlElement('w:bottom')
for k, v in (('val', 'single'), ('sz', '8'), ('space', '4'), ('color', '000000')): bt.set(qn('w:' + k), v)
bd.append(bt); pPr.append(bd)

p('2026 yil “____” _______dagi', L, before=64)
p('№________-sonli', L, after=20)

for i, line in enumerate(['"O\'zbektelekom" AK', '"Markaziy" filiali', "direktor o'rinbosari", "Murodov M.M.ga"]):
    p(line, R, b=(i == 3))

p('Hurmatli Muzaffar Muzrobovich!', C, True, before=22, after=12)

p(f'"XONSAROY GROUP" MCHJ rahbariyati sizdan {PHONE} raqamini jismoniy shaxs '
  f'{FIO} (pasport: {PASS}) nomiga qayta rasmiylashtirib berishingizni so\'raymiz.',
  J, indent=1.25, after=8)
p("Mazkur masalada yordam berganingiz uchun oldindan minnatdorchilik bildiramiz.",
  J, indent=1.25, after=8)
p("Hurmat bilan,", L, indent=1.25, before=6, after=30)

t = d.add_table(rows=2, cols=3); t.alignment = WD_TABLE_ALIGNMENT.CENTER
t.autofit = False; w = [Cm(6.5), Cm(5.5), Cm(5.5)]
vals = [['Direktor', '_______________', '____________________'],
        ['', '(imzo)  (muhr)', '(F.I.SH.)']]
for ri in range(2):
    for ci in range(3):
        c = t.cell(ri, ci); c.width = w[ci]
        para = c.paragraphs[0]; para.alignment = C if ci else L
        r = para.add_run(vals[ri][ci])
        if ri == 1: r.font.size = Pt(10)
        elif ci == 0: r.bold = True
d.save(DOCX)

if __name__ == '__main__' and True:
    print('DOCX OK'); raise SystemExit
wb = Workbook(); ws = wb.active; ws.title = 'Chiquvchi xatlar'
hdr = ['№ т/р', 'Raqam', 'Sana', 'Qabul qiluvchi tashkilot', 'Qabul qiluvchi F.I.SH.', 'Mavzu',
       'Kim uchun (F.I.SH., pasport)', 'Imzolagan', 'Holati', 'Fayl nomi']
ws.append(hdr)
ws.append([1, NUM, DATE_XL, "O'zbektelekom AK, Markaziy filiali", 'Murodov M.M.',
           f'{PHONE} raqamini jismoniy shaxsga qayta rasmiylashtirish',
           f'{FIO}, {PASS}', '', 'Imzolanmagan', 'Хат_№001-26_2026-10-30.docx'])
thin = Side(style='thin', color='999999')
for c in ws[1]:
    c.font = Font(bold=True, color='FFFFFF'); c.fill = PatternFill('solid', fgColor='1F4E78')
    c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
for row in ws.iter_rows():
    for c in row:
        c.border = Border(left=thin, right=thin, top=thin, bottom=thin)
        if c.row > 1: c.alignment = Alignment(vertical='top', wrap_text=True)
for i, wd in enumerate([7, 10, 12, 30, 22, 40, 36, 16, 14, 30], 1):
    ws.column_dimensions[get_column_letter(i)].width = wd
ws.freeze_panes = 'A2'; ws.auto_filter.ref = ws.dimensions
wb.save(XLSX)
print('OK')



