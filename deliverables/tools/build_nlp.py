"""Bring the user's humanised NLP Review III report in line with the Review III template.

Body text is never rewritten. Changes are limited to: figure sizes, page numbering sections,
template-style TOC / lists, appendix numbering and appendix code listings.
Usage: py build_nlp.py <input.docx> <output.docx> [pages.json]
"""
import copy
import io
import json
import re
import sys

import docx
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from PIL import Image

SRC, OUT = sys.argv[1], sys.argv[2]
PAGES = json.load(open(sys.argv[3], encoding="utf-8-sig")) if len(sys.argv) > 3 else None
APP = r"D:\cowork\debate-rec\app"

TEXT_W = 11906 - 1984 - 1701   # twips between the template margins (3.5 cm / 3.0 cm)
EMU_CM = 360000

d = docx.Document(SRC)
body = d.element.body


def roman(n):
    vals = [(10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
    s = ""
    for v, r in vals:
        while n >= v:
            s += r
            n -= v
    return s


def els():
    return list(body.iterchildren())


def para_text(el):
    return "".join(t.text or "" for t in el.iter(qn("w:t")))


def style_of(el):
    ps = el.find(qn("w:pPr") + "/" + qn("w:pStyle"))
    return ps.get(qn("w:val")) if ps is not None else None


# ---------------------------------------------------------------- 1. figure sizes
NEW_ARCH = open(r"architecture_new.png", "rb").read()
d.part.related_parts["rId8"]._blob = NEW_ARCH
fix = {"rId8": 14.0, "rId9": 14.0}   # figure 1 (tall diagram) / figure 2 (chart), width in cm
for el in els():
    for dr in el.iter(qn("w:drawing")):
        blip = dr.find(".//" + qn("a:blip"))
        rid = blip.get(qn("r:embed"))
        if rid not in fix:
            continue
        w_px, h_px = Image.open(io.BytesIO(d.part.related_parts[rid].blob)).size
        cx = int(fix[rid] * EMU_CM)
        cy = int(cx * h_px / w_px)
        for tag in (".//" + "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}extent",
                    ".//" + qn("a:ext")):
            e = dr.find(tag)
            e.set("cx", str(cx))
            e.set("cy", str(cy))
        # keep the picture with its caption
        p = dr.getparent().getparent()
        while p.tag != qn("w:p"):
            p = p.getparent()
        ppr = p.find(qn("w:pPr"))
        if ppr is None:
            ppr = parse_xml('<w:pPr %s/>' % nsdecls("w"))
            p.insert(0, ppr)
        if ppr.find(qn("w:keepNext")) is None:
            ppr.insert(0, parse_xml('<w:keepNext %s/>' % nsdecls("w")))

# ---------------------------------------------------------------- 2. caption styles
styles = d.styles
from docx.enum.style import WD_STYLE_TYPE
for name in ("Figure Caption", "Table Caption"):
    if name not in [s.name for s in styles]:
        st = styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        st.base_style = styles["Normal"]


def set_style(el, style_name):
    sid = style_name.replace(" ", "")
    ppr = el.find(qn("w:pPr"))
    if ppr is None:
        ppr = parse_xml('<w:pPr %s/>' % nsdecls("w"))
        el.insert(0, ppr)
    ps = ppr.find(qn("w:pStyle"))
    if ps is None:
        ps = parse_xml('<w:pStyle %s w:val="%s"/>' % (nsdecls("w"), sid))
        ppr.insert(0, ps)
    else:
        ps.set(qn("w:val"), sid)


for el in els():
    if el.tag == qn("w:p") and re.match(r"^\s*Fig\.\s*\d+\.", para_text(el)):
        set_style(el, "Figure Caption")

# Table caption (added so the template's List of Tables has an entry) ---------------
tbl_el = [e for e in els() if e.tag == qn("w:tbl") and para_text(e).startswith("Cond.")][0]
fig_cap = [e for e in els() if e.tag == qn("w:p") and style_of(e) == "FigureCaption"][0]
tcap = copy.deepcopy(fig_cap)
for r in tcap.findall(qn("w:r"))[1:]:
    tcap.remove(r)
tcap.find(qn("w:r") + "/" + qn("w:t")).text = (
    "Table 1. Ablation results: retrieval-only baselines vs. multi-agent debate stages (E0 to E4).")
set_style(tcap, "Table Caption")
ppr = tcap.find(qn("w:pPr"))
if ppr.find(qn("w:keepNext")) is None:
    ppr.insert(1, parse_xml('<w:keepNext %s/>' % nsdecls("w")))
tbl_el.addprevious(tcap)

# ---------------------------------------------------------------- 3. appendix numbering + code
for el in els():
    if el.tag == qn("w:p") and para_text(el).strip() == "APPENDIX \u2014 CODING":
        ts = list(el.iter(qn("w:t")))
        ts[0].text = ts[0].text.replace("APPENDIX \u2014", "APPENDIX 1 \u2014", 1)
        if "APPENDIX 1" not in ts[0].text:
            ts[0].text = "APPENDIX 1 \u2014 CODING"
            for t in ts[1:]:
                t.text = ""
        appendix_p = el
        break

appendix_intro = appendix_p.getnext()          # existing paragraph, left untouched
pb_after = appendix_intro.getnext()            # page-break paragraph before REFERENCES

FILES = [
    ("A1.1", "app/nlp/parser.py", "nlp/parser.py"),
    ("A1.2", "app/nlp/preferences.py", "nlp/preferences.py"),
    ("A1.3", "app/agents/base.py", "agents/base.py"),
    ("A1.4", "app/agents/debate.py", "agents/debate.py"),
    ("A1.5", "app/agents/judge.py", "agents/judge.py"),
    ("A1.6", "app/recommender/index.py", "recommender/index.py"),
]
W = nsdecls("w")


def heading2(text, page_break=True):
    return parse_xml(
        '<w:p %s><w:pPr><w:pStyle w:val="Heading3"/><w:keepNext/>%s</w:pPr><w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>'
        % (W, "<w:pageBreakBefore/>" if page_break else "", text.replace("&", "&amp;")))


def code_para(line):
    line = line.replace("\t", "    ").rstrip()
    esc = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return parse_xml(
        '<w:p %s><w:pPr><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/><w:ind w:left="284" w:hanging="284"/></w:pPr>'
        '<w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas"/><w:sz w:val="16"/><w:szCs w:val="16"/></w:rPr>'
        '<w:t xml:space="preserve">%s</w:t></w:r></w:p>' % (W, esc))


anchor = appendix_intro
for num, title, rel in FILES:
    h = heading2("%s  %s" % (num, title))
    anchor.addnext(h)
    anchor = h
    for line in open(APP + "\\" + rel.replace("/", "\\"), encoding="utf-8").read().splitlines():
        p = code_para(line)
        anchor.addnext(p)
        anchor = p

# ---------------------------------------------------------------- 4. front matter
all_els = els()


def find_p(text, style=None):
    for e in all_els:
        if e.tag == qn("w:p") and para_text(e).strip() == text and (style is None or style_of(e) == style):
            return e
    raise KeyError(text)


abstract_h = find_p("ABSTRACT", "Heading1")
toc_h = find_p("TABLE OF CONTENTS", "Heading1")
sdt = [e for e in all_els if e.tag == qn("w:sdt")][0]
pb_before_ch1 = sdt.getnext()                   # page-break paragraph that ends the front matter
pb_after_cover = abstract_h.getprevious()       # page-break paragraph that ends the cover

# TABLE OF CONTENTS heading: centred, bold 14 pt, but NOT a Heading 1 (so it is not listed in itself)
toc_h.find(qn("w:pPr")).remove(toc_h.find(qn("w:pPr")).find(qn("w:pStyle")))
ppr = toc_h.find(qn("w:pPr"))
for x in ppr.findall(qn("w:jc")):
    ppr.remove(x)
_tail = [x for x in ppr if x.tag in (qn("w:rPr"), qn("w:sectPr"), qn("w:pPrChange"))]
for x in _tail:
    ppr.remove(x)
ppr.append(parse_xml('<w:spacing %s w:before="480" w:after="240"/>' % W))
ppr.append(parse_xml('<w:jc %s w:val="center"/>' % W))
for x in _tail:
    ppr.append(x)
for r in toc_h.findall(qn("w:r")):
    rpr = r.find(qn("w:rPr"))
    if rpr is None:
        rpr = parse_xml('<w:rPr %s/>' % W)
        r.insert(0, rpr)
    rpr.append(parse_xml('<w:b %s/>' % W))
    rpr.append(parse_xml('<w:sz %s w:val="28"/>' % W))
    rpr.append(parse_xml('<w:szCs %s w:val="28"/>' % W))


def cell(width, text="", span=1, jc=None, bold=False, left=0, size=24, right=0):
    tcw = '<w:tcW w:w="%d" w:type="dxa"/>' % width
    grid = '<w:gridSpan w:val="%d"/>' % span if span > 1 else ""
    ind = ('<w:ind w:left="%d" w:right="%d"/>' % (left, right)) if (left or right) else ""
    jcx = '<w:jc w:val="%s"/>' % jc if jc else ""
    b = "<w:b/><w:bCs/>" if bold else ""
    run = ""
    if text:
        run = ('<w:r><w:rPr>%s<w:sz w:val="%d"/><w:szCs w:val="%d"/></w:rPr><w:t xml:space="preserve">%s</w:t></w:r>'
               % (b, size, size, text.replace("&", "&amp;").replace("<", "&lt;")))
    return ('<w:tc><w:tcPr>%s%s<w:vAlign w:val="top"/></w:tcPr><w:p><w:pPr><w:spacing w:after="50" w:line="259" w:lineRule="auto"/>%s%s</w:pPr>%s</w:p></w:tc>'
            % (tcw, grid, ind, jcx, run))


def table_xml(grid, rows):
    g = "".join('<w:gridCol w:w="%d"/>' % w for w in grid)
    trs = "".join('<w:tr><w:trPr><w:cantSplit/></w:trPr>%s</w:tr>' % "".join(r) for r in rows)
    return parse_xml(
        '<w:tbl %s><w:tblPr><w:tblW w:w="%d" w:type="dxa"/><w:tblLayout w:type="fixed"/>'
        '<w:tblCellMar><w:left w:w="0" w:type="dxa"/><w:right w:w="0" w:type="dxa"/></w:tblCellMar></w:tblPr>'
        '<w:tblGrid>%s</w:tblGrid>%s</w:tbl>' % (W, sum(grid), g, trs))


def pb():
    return parse_xml('<w:p %s><w:r><w:br w:type="page"/></w:r></w:p>' % W)


def h1_el(text):
    return parse_xml('<w:p %s><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>%s</w:t></w:r></w:p>' % (W, text))


def jc_center_heading_fix(el):
    return el


# collect heading / caption entries in final order (after code inserts) ------------------
HEAD_LISTS = ["LIST OF TABLES", "LIST OF FIGURES", "LIST OF SYMBOLS, ABBREVIATIONS AND NOMENCLATURE"]

# build the three new list pages first (placeholders for page numbers)
tables = []
figures = []
for e in els():
    if e.tag == qn("w:p") and style_of(e) == "TableCaption":
        m = re.match(r"^\s*Table\s+(\d+)\.\s*(.*)$", para_text(e))
        tables.append((m.group(1), m.group(2)))
    if e.tag == qn("w:p") and style_of(e) == "FigureCaption":
        m = re.match(r"^\s*Fig\.\s*(\d+)\.\s*(.*)$", para_text(e))
        figures.append((m.group(1), m.group(2)))

# ordered heading list (H1/H2) for page lookup: front headings + body headings
body_heads = [e for e in els() if e.tag == qn("w:p") and style_of(e) in ("Heading1", "Heading2")]
heading_entries = []      # (level, number, title)
for name in ("ABSTRACT",) + tuple(HEAD_LISTS):
    heading_entries.append((1, "", name))
for e in body_heads:
    t = para_text(e).strip()
    if t == "ABSTRACT":
        continue
    lvl = 1 if style_of(e) == "Heading1" else 2
    m = re.match(r"^(A?\d+(?:\.\d+)*)\.?\s+(.*)$", t)
    if m:
        heading_entries.append((lvl, m.group(1) + ("." if lvl == 1 else ""), m.group(2)))
    else:
        heading_entries.append((lvl, "", t))

# page lookup from the Word-computed map -------------------------------------------------
H_ORDER = [(1, "ABSTRACT")] + [(1, h) for h in HEAD_LISTS]
page_for = {}
fig_pages, tab_pages = [], []
if PAGES:
    items = PAGES["items"] if isinstance(PAGES["items"], list) else [PAGES["items"]]
    hs = [i for i in items if i["style"] in ("Heading 1", "Heading 2")]
    for i, it in enumerate(hs):
        page_for[i] = (it["page"], it["sect"])
    fig_pages = [(i["page"], i["sect"]) for i in items if i["style"] == "Figure Caption"]
    tab_pages = [(i["page"], i["sect"]) for i in items if i["style"] == "Table Caption"]


def fmt_page(pair):
    if not pair:
        return "0"
    page, sect = pair
    return roman(page) if sect <= 2 else str(page)


# order of headings in the document differs from heading_entries only by the TOC heading (excluded)
doc_order = []   # heading_entries order == document order of Heading1/2 once lists are inserted
toc_rows = []
G = [1800, 700, 4521, 1200]   # chapter no | sub no | title | page no
toc_rows.append([cell(G[0], "CHAPTER NO.", jc="right", bold=True), cell(G[1]), cell(G[2], "TITLE", bold=True, left=40),
                 cell(G[3], "PAGE NO.", jc="center", bold=True)])
for i, (lvl, num, title) in enumerate(heading_entries):
    pg = fmt_page(page_for.get(i))
    if lvl == 1:
        toc_rows.append([cell(G[0], num, jc="right", bold=True, right=160), cell(G[1] + G[2], title, span=2, bold=True, left=40),
                         cell(G[3], pg, jc="center", bold=True)])
    else:
        toc_rows.append([cell(G[0]), cell(G[1], num, left=100), cell(G[2], title, left=40), cell(G[3], pg, jc="center")])
toc_tbl = table_xml(G, toc_rows)

L = [1500, 5121, 1600]
fig_rows = [[cell(L[0], "FIGURE NO.", jc="center", bold=True), cell(L[1], "TITLE", bold=True, left=80), cell(L[2], "PAGE NO.", jc="center", bold=True)]]
for i, (n, t) in enumerate(figures):
    fig_rows.append([cell(L[0], n, jc="center"), cell(L[1], t, left=80), cell(L[2], fmt_page(fig_pages[i] if i < len(fig_pages) else None), jc="center")])
tab_rows = [[cell(L[0], "TABLE NO.", jc="center", bold=True), cell(L[1], "TITLE", bold=True), cell(L[2], "PAGE NO.", jc="center", bold=True)]]
for i, (n, t) in enumerate(tables):
    tab_rows.append([cell(L[0], n, jc="center"), cell(L[1], t, left=80), cell(L[2], fmt_page(tab_pages[i] if i < len(tab_pages) else None), jc="center")])

SYM = [
    ("NLP", "Natural Language Processing"),
    ("LLM", "Large Language Model"),
    ("QA", "Question Answering"),
    ("BM25", "Best Matching 25 (Okapi probabilistic ranking function)"),
    ("TF-IDF", "Term Frequency \u2013 Inverse Document Frequency"),
    ("P@5", "Precision at rank 5"),
    ("NDCG@5", "Normalised Discounted Cumulative Gain at rank 5"),
    ("MRR", "Mean Reciprocal Rank"),
    ("E0 \u2013 E4", "Ablation conditions: E0 popularity only, E1 hybrid retrieval only, E2 + Supporter, E3 + Critic, E4 full debate"),
    ("JSON", "JavaScript Object Notation"),
    ("GPU", "Graphics Processing Unit"),
    ("HTML / CSS / JS", "HyperText Markup Language / Cascading Style Sheets / JavaScript"),
    ("EPJ", "Experiential Project (course component)"),
]
S = [2400, 5821]
sym_rows = [[cell(S[0], "SYMBOL / ABBREVIATION", bold=True), cell(S[1], "MEANING", bold=True)]]
for a, b in SYM:
    sym_rows.append([cell(S[0], a, bold=True), cell(S[1], b)])

# assemble: [abstract...][PB] [TOC heading][TOC table][PB] lists... [section-end]
sdt.addprevious(toc_tbl)
sdt.getparent().remove(sdt)
# pb_before_ch1 currently follows the (removed) sdt; the new lists go before it
anchor = toc_tbl
for title, tbl_xml in ((HEAD_LISTS[0], table_xml(L, tab_rows)), (HEAD_LISTS[1], table_xml(L, fig_rows)),
                       (HEAD_LISTS[2], table_xml(S, sym_rows))):
    for e in (pb(), h1_el(title), tbl_xml):
        anchor.addnext(e)
        anchor = e
# the original page-break paragraph before chapter 1 becomes the end-of-front-matter section break

# ---------------------------------------------------------------- 5. sections / page numbers
final_sect = body.find(qn("w:sectPr"))


def make_sect(roman_fmt, start=None, footer=True):
    s = copy.deepcopy(final_sect)
    for f in s.findall(qn("w:footerReference")):
        if not footer:
            s.remove(f)
    for x in s.findall(qn("w:pgNumType")):
        s.remove(x)
    attrs = 'w:fmt="%s"' % ("lowerRoman" if roman_fmt else "decimal")
    if start:
        attrs += ' w:start="%d"' % start
    pg_mar = s.find(qn("w:pgMar"))
    pg_mar.addnext(parse_xml('<w:pgNumType %s %s/>' % (W, attrs)))
    return s


def end_section_with(p_el, sect):
    for r in list(p_el.findall(qn("w:r"))):
        p_el.remove(r)
    ppr = p_el.find(qn("w:pPr"))
    if ppr is None:
        ppr = parse_xml('<w:pPr %s/>' % W)
        p_el.insert(0, ppr)
    for x in ppr.findall(qn("w:sectPr")):
        ppr.remove(x)
    ppr.append(sect)


end_section_with(pb_after_cover, make_sect(True, footer=False))      # cover: no page number
end_section_with(pb_before_ch1, make_sect(True))                      # front matter: i, ii, iii ...
# body section (final sectPr): decimal, restart at 1
for x in final_sect.findall(qn("w:pgNumType")):
    final_sect.remove(x)
final_sect.find(qn("w:pgMar")).addnext(parse_xml('<w:pgNumType %s w:fmt="decimal" w:start="1"/>' % W))

for t in body.iter(qn("w:tbl")):
    if para_text(t).startswith(("LTE_CUES", "async def understand", "def audit_block", "DATA_OPEN")):
        for tr in t.findall(qn("w:tr")):
            trpr = tr.find(qn("w:trPr"))
            if trpr is None:
                trpr = parse_xml('<w:trPr %s/>' % W)
                tr.insert(0, trpr)
            if trpr.find(qn("w:cantSplit")) is None:
                trpr.append(parse_xml('<w:cantSplit %s/>' % W))

# headings keep with next
for e in els():
    if e.tag == qn("w:p") and style_of(e) in ("Heading1", "Heading2", "Heading3"):
        ppr = e.find(qn("w:pPr"))
        if ppr is not None and ppr.find(qn("w:keepNext")) is None:
            ppr.insert(1, parse_xml('<w:keepNext %s/>' % W))

d.save(OUT)
print("saved", OUT, "| headings:", len(heading_entries), "figures:", len(figures), "tables:", len(tables))
