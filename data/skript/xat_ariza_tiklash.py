from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

PHONE = '+998 70 051 74 00'
FIO = '________________________________'
PASS = '____________'
DOCX = r'D:\it-agent\data\ish\Ariza_tiklash_998700517400.docx'

d = Document()
s = d.sections[0]
s.page_width, s.page_height = Cm(21), Cm(29.7)
s.left_margin, s.right_margin, s.top_margin, s.bottom_margin = Cm(2), Cm(1.5), Cm(2), Cm(2)
st = d.styles['Normal']
st.font.name = 'Times New Roman'; st.font.size = Pt(14)
st.element.rPr.rFonts.set(qn('w:eastAsia'), 'Times New Roman')
st.paragraph_format.line_spacing = 1.15
st.paragraph_format.space_after = Pt(0)

C, R, L, J = (WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.RIGHT,
              WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.JUSTIFY)

def p(t='', al=None, b=False, after=0, before=0, indent=None):
    x = d.add_paragraph(); r = x.add_run(t); r.bold = b
    if al is not None: x.alignment = al
    pf = x.paragraph_format
    pf.space_after = Pt(after); pf.space_before = Pt(before)
    if indent: pf.first_line_indent = Cm(indent)
    return x

h = p('"XONSAROY GROUP" MCHJ', C, True, after=4)
pPr = h._p.get_or_add_pPr(); bd = OxmlElement('w:pBdr'); bt = OxmlElement('w:bottom')
for k, v in (('val', 'single'), ('sz', '8'), ('space', '4'), ('color', '000000')): bt.set(qn('w:' + k), v)
bd.append(bt); pPr.append(bd)

p('2026 yil “____” _______dagi', L, before=64)
p('№________-sonli', L, after=20)
for i, line in enumerate(['"O\'zbektelekom" AK', '"Markaziy" filiali', "direktor o'rinbosari", "Murodov M.M.ga"]):
    p(line, R, b=(i == 3))

p('ARIZA', C, True, before=22, after=12)
p(f'"XONSAROY GROUP" MCHJ rahbariyati sizdan "Markaziy" filiali bilan tuzilgan №193482603-sonli abonent shartnomasi doirasida ulangan {PHONE} abonent raqamini tiklab (qayta faollashtirib) berish bo\'yicha amaliy yordam berishingizni so\'raymiz.', J, indent=1.25, after=8)
p("Mazkur raqam \"XONSAROY GROUP\" MCHJ (tashkilot) nomiga rasmiylashtirilgan.", J, indent=1.25, after=8)
p("Hurmat bilan,", L, indent=1.25, before=6, after=30)
t = d.add_table(rows=2, cols=3); t.alignment = WD_TABLE_ALIGNMENT.CENTER
t.autofit = False; w = [Cm(6.5), Cm(5.5), Cm(5.5)]
vals = [['Direktor', '_______________', '____________________'], ['(rahbar lavozimi)', '(imzo) (muhr)', '(F.I.SH.)']]
for ri in range(2):
    for ci in range(3):
        c = t.cell(ri, ci); c.width = w[ci]
        para = c.paragraphs[0]; para.alignment = C if ci else L
        r = para.add_run(vals[ri][ci])
        if ri == 1: r.font.size = Pt(10)
        elif ci == 0: r.bold = True
d.save(DOCX)
print('OK')

