"""Генератор PPTX для оформленной презентации (холст 1920x1080 px = 13,333x7,5 дюйма; 1 px = 6350 EMU, 1 px шрифта = 0,5 пт).

Поддержано: фон, скруглённые прямоугольники с текстом и поворотом, эллипсы, линии-нити, картинка с обрезкой,
таблица, готовые фигуры PowerPoint вместо иконок, заметки докладчика.
"""

import math
import zipfile
from xml.sax.saxutils import escape

PX = 6350
W, H = 12192000, 6858000
NS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
FONTS = {"h": "Georgia", "b": "Arial", "m": "Courier New"}
INK, PAPER, RED, RED2, MUTED, MUTED2 = "1B1916", "F2EDE2", "B3261E", "E0584F", "6A6358", "A79F90"


def e(px):
    return int(round(px * PX))


def run(text, font="b", px=28, color="23201B", bold=False, italic=False, spc=0):
    sp = f' spc="{int(spc * 50)}"' if spc else ""  # px -> сотые пункта (1 px = 0,5 пт)
    return (f'<a:r><a:rPr lang="ru-RU" sz="{int(px * 50)}" b="{int(bold)}" i="{int(italic)}"{sp} dirty="0">'
            f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill><a:latin typeface="{FONTS[font]}"/><a:cs typeface="{FONTS[font]}"/></a:rPr>'
            f'<a:t>{escape(text)}</a:t></a:r>')


def para(runs, lh=1.3, after=0, align="l"):
    runs = runs if isinstance(runs, str) else "".join(runs)
    pct = int(lh / 1.2 * 100000)
    return (f'<a:p><a:pPr algn="{align}" marL="0" indent="0"><a:lnSpc><a:spcPct val="{pct}"/></a:lnSpc><a:spcBef><a:spcPts val="0"/></a:spcBef>'
            f'<a:spcAft><a:spcPts val="{int(after * 50)}"/></a:spcAft><a:buNone/></a:pPr>{runs}</a:p>')


def est_lines(text, px, width, font="b", bold=False):
    k = {"h": 0.56, "b": 0.52, "m": 0.60}[font] * (1.06 if bold else 1)
    cap = max(1, int(width / (px * k)))
    n, line = 1, 0
    for w in text.split():
        L = len(w) + (1 if line else 0)
        if line + L > cap:
            n += 1
            line = len(w)
        else:
            line += L
    return n


class Slide:
    def __init__(self, bg, notes=""):
        self.bg, self.notes_text = bg, notes
        self.sh, self.nid, self.rels, self.media = [], 1, [], []

    def _id(self):
        self.nid += 1
        return self.nid

    def shape(self, x, y, w, h, paras="", fill=None, line=None, lw=0, geom="roundRect", adj=None, rot=0,
              pad=(0, 0, 0, 0), anchor="t", shadow=False, name="Фигура", descr=None, title=False):
        i = self._id()
        fl = f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>' if fill else "<a:noFill/>"
        ln = (f'<a:ln w="{int(lw * PX)}"><a:solidFill><a:srgbClr val="{line}"/></a:solidFill></a:ln>' if line else "<a:ln><a:noFill/></a:ln>")
        av = f'<a:avLst><a:gd name="adj" fmla="val {adj}"/></a:avLst>' if adj is not None and geom == "roundRect" else "<a:avLst/>"
        fx = ('<a:effectLst><a:outerShdw blurRad="177800" dist="76200" dir="5400000" algn="t" rotWithShape="0"><a:srgbClr val="000000"><a:alpha val="45000"/></a:srgbClr></a:outerShdw></a:effectLst>' if shadow else "")
        r = f' rot="{int(rot * 60000)}"' if rot else ""
        body = paras or '<a:p><a:endParaRPr lang="ru-RU"/></a:p>'
        ph = '<p:nvPr><p:ph type="title"/></p:nvPr>' if title else "<p:nvPr/>"
        tb = "" if title else ' txBox="0"'
        d = f' descr="{escape(descr)}"' if descr else ""
        self.sh.append(
            f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="{escape(name)}"{d}/><p:cNvSpPr/>{ph}</p:nvSpPr>'
            f'<p:spPr><a:xfrm{r}><a:off x="{e(x)}" y="{e(y)}"/><a:ext cx="{e(w)}" cy="{e(h)}"/></a:xfrm><a:prstGeom prst="{geom}">{av}</a:prstGeom>{fl}{ln}{fx}</p:spPr>'
            f'<p:txBody><a:bodyPr wrap="square" lIns="{e(pad[0])}" tIns="{e(pad[1])}" rIns="{e(pad[2])}" bIns="{e(pad[3])}" anchor="{anchor}"><a:noAutofit/></a:bodyPr><a:lstStyle/>{body}</p:txBody></p:sp>')

    def text(self, x, y, w, h, paras, name="Текст", anchor="t", title=False):
        i = self._id()
        ph = '<p:nvPr><p:ph type="title"/></p:nvPr>' if title else "<p:nvPr/>"
        cnv = '<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>' if title else '<p:cNvSpPr txBox="1"/>'
        self.sh.append(
            f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="{escape(name)}"/>{cnv}{ph}</p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{e(x)}" y="{e(y)}"/><a:ext cx="{e(w)}" cy="{e(h)}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
            f'<p:txBody><a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" anchor="{anchor}"><a:noAutofit/></a:bodyPr><a:lstStyle/>{"".join(paras)}</p:txBody></p:sp>')

    def line(self, x1, y1, x2, y2, color, lw=3, name="Нить"):
        i = self._id()
        x, y, w, h = min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)
        fl = ""
        if x2 < x1:
            fl += ' flipH="1"'
        if y2 < y1:
            fl += ' flipV="1"'
        self.sh.append(
            f'<p:cxnSp><p:nvCxnSpPr><p:cNvPr id="{i}" name="{name}"/><p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr>'
            f'<p:spPr><a:xfrm{fl}><a:off x="{e(x)}" y="{e(y)}"/><a:ext cx="{e(w)}" cy="{e(h)}"/></a:xfrm><a:prstGeom prst="line"><a:avLst/></a:prstGeom>'
            f'<a:ln w="{int(lw * PX)}"><a:solidFill><a:srgbClr val="{color}"/></a:solidFill></a:ln></p:spPr></p:cxnSp>')

    def pic(self, path, x, y, w, h, crop, descr, radius=False):
        i = self._id()
        rid = f"rIdM{len(self.media) + 1}"
        self.media.append((rid, path))
        l, t, r_, b = crop
        self.sh.append(
            f'<p:pic><p:nvPicPr><p:cNvPr id="{i}" name="Картинка" descr="{escape(descr)}"/><p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
            f'<p:blipFill><a:blip r:embed="{rid}"/><a:srcRect l="{l}" t="{t}" r="{r_}" b="{b}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
            f'<p:spPr><a:xfrm><a:off x="{e(x)}" y="{e(y)}"/><a:ext cx="{e(w)}" cy="{e(h)}"/></a:xfrm><a:prstGeom prst="{"roundRect" if radius else "rect"}"><a:avLst>'
            f'{"<a:gd name=\"adj\" fmla=\"val 1200\"/>" if radius else ""}</a:avLst></a:prstGeom></p:spPr></p:pic>')

    def table(self, x, y, colw, rowh, rows, px=32, hdr_color=MUTED, color="23201B", line="D9D1BF"):
        i = self._id()
        grid = "".join(f'<a:gridCol w="{e(c)}"/>' for c in colw)
        trs = []
        for ri, r in enumerate(rows):
            tcs = []
            for ci, cell in enumerate(r):
                head = ri == 0
                col = hdr_color if head else color
                ln = f'<a:lnB w="{int(1.5 * PX)}"><a:solidFill><a:srgbClr val="{line if not head else "6A6358"}"/></a:solidFill></a:lnB>'
                nol = "".join(f"<a:ln{s} w=\"0\"><a:noFill/></a:ln{s}>" for s in ("L", "R", "T"))
                tcs.append(
                    f'<a:tc><a:txBody><a:bodyPr/><a:lstStyle/>{para(run(cell, "b", px - 4 if head else px, col, bold=head), 1.2)}</a:txBody>'
                    f'<a:tcPr marL="{e(8)}" marR="{e(8)}" marT="{e(10)}" marB="{e(10)}" anchor="ctr">{nol}{ln}<a:noFill/></a:tcPr></a:tc>')
            trs.append(f'<a:tr h="{e(rowh)}">{"".join(tcs)}</a:tr>')
        self.sh.append(
            f'<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="{i}" name="Таблица"/><p:cNvGraphicFramePr><a:graphicFrameLocks noGrp="1"/></p:cNvGraphicFramePr><p:nvPr/></p:nvGraphicFramePr>'
            f'<p:xfrm><a:off x="{e(x)}" y="{e(y)}"/><a:ext cx="{e(sum(colw))}" cy="{e(rowh * len(rows))}"/></p:xfrm>'
            f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table"><a:tbl><a:tblPr firstRow="1"/><a:tblGrid>{grid}</a:tblGrid>{"".join(trs)}</a:tbl></a:graphicData></a:graphic></p:graphicFrame>')

    def xml(self):
        return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sld {NS}><p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="{self.bg}"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>'
                f'<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
                f'{"".join(self.sh)}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')


class Deck:
    def __init__(self, title, authors):
        self.title, self.authors, self.slides = title, authors, []

    def add(self, bg, notes=""):
        s = Slide(bg, notes)
        self.slides.append(s)
        return s

    def save(self, path):
        n = len(self.slides)
        theme = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Detective Board Design">'
                 '<a:themeElements><a:clrScheme name="DBD"><a:dk1><a:srgbClr val="1B1916"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="23201B"/></a:dk2><a:lt2><a:srgbClr val="F2EDE2"/></a:lt2>'
                 '<a:accent1><a:srgbClr val="B3261E"/></a:accent1><a:accent2><a:srgbClr val="E0584F"/></a:accent2><a:accent3><a:srgbClr val="6A6358"/></a:accent3><a:accent4><a:srgbClr val="A79F90"/></a:accent4>'
                 '<a:accent5><a:srgbClr val="B07A1A"/></a:accent5><a:accent6><a:srgbClr val="8A8273"/></a:accent6><a:hlink><a:srgbClr val="B3261E"/></a:hlink><a:folHlink><a:srgbClr val="6A6358"/></a:folHlink></a:clrScheme>'
                 '<a:fontScheme name="DBD"><a:majorFont><a:latin typeface="Georgia"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont><a:minorFont><a:latin typeface="Arial"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme>'
                 '<a:fmtScheme name="DBD"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>'
                 '<a:lnStyleLst><a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="12700"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="19050"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>'
                 '<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>'
                 '<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>')
        grp = '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
        ph = (f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="Заголовок"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>'
              f'<p:spPr><a:xfrm><a:off x="{e(128)}" y="{e(128)}"/><a:ext cx="{e(1664)}" cy="{e(90)}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
              '<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="ru-RU"/><a:t>Заголовок</a:t></a:r></a:p></p:txBody></p:sp>')
        master = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sldMaster {NS}><p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="F2EDE2"/></a:solidFill><a:effectLst/></p:bgPr></p:bg><p:spTree>{grp}{ph}</p:spTree></p:cSld>'
                  '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
                  '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
                  '<p:txStyles><p:titleStyle><a:lvl1pPr algn="l"><a:defRPr sz="3600" b="1"><a:latin typeface="Georgia"/></a:defRPr></a:lvl1pPr></p:titleStyle><p:bodyStyle><a:lvl1pPr><a:defRPr sz="2000"><a:latin typeface="Arial"/></a:defRPr></a:lvl1pPr></p:bodyStyle><p:otherStyle><a:lvl1pPr><a:defRPr sz="1400"><a:latin typeface="Arial"/></a:defRPr></a:lvl1pPr></p:otherStyle></p:txStyles></p:sldMaster>')
        layout = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sldLayout {NS} type="titleOnly" preserve="1"><p:cSld name="Только заголовок"><p:spTree>{grp}{ph}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>'
        nm = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:notesMaster {NS}><p:cSld><p:spTree>{grp}'
              '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Slide Image"/><p:cNvSpPr><a:spLocks noGrp="1" noRot="1" noChangeAspect="1"/></p:cNvSpPr><p:nvPr><p:ph type="sldImg" idx="2"/></p:nvPr></p:nvSpPr><p:spPr><a:xfrm><a:off x="685800" y="1143000"/><a:ext cx="5486400" cy="3086100"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:sp>'
              '<p:sp><p:nvSpPr><p:cNvPr id="3" name="Notes"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="body" sz="quarter" idx="3"/></p:nvPr></p:nvSpPr><p:spPr><a:xfrm><a:off x="685800" y="4400550"/><a:ext cx="5486400" cy="3600450"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr lang="ru-RU"/></a:p></p:txBody></p:sp>'
              '</p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/></p:notesMaster>')
        pres = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:presentation {NS}><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
                '<p:notesMasterIdLst><p:notesMasterId r:id="rId3"/></p:notesMasterIdLst>'
                f'<p:sldIdLst>{"".join(f"<p:sldId id=\"{256 + i}\" r:id=\"rId{10 + i}\"/>" for i in range(n))}</p:sldIdLst>'
                f'<p:sldSz cx="{W}" cy="{H}"/><p:notesSz cx="6858000" cy="9144000"/><p:defaultTextStyle><a:lvl1pPr><a:defRPr sz="1400"><a:latin typeface="Arial"/></a:defRPr></a:lvl1pPr></p:defaultTextStyle></p:presentation>')
        pr = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
              f'<Relationship Id="rId1" Type="{R}/slideMaster" Target="slideMasters/slideMaster1.xml"/><Relationship Id="rId2" Type="{R}/theme" Target="theme/theme1.xml"/>'
              f'<Relationship Id="rId3" Type="{R}/notesMaster" Target="notesMasters/notesMaster1.xml"/>'
              + "".join(f'<Relationship Id="rId{10 + i}" Type="{R}/slide" Target="slides/slide{i + 1}.xml"/>' for i in range(n)) + "</Relationships>")
        ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="jpg" ContentType="image/jpeg"/>'
              '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
              '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
              '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
              '<Override PartName="/ppt/notesMasters/notesMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesMaster+xml"/>'
              '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/><Override PartName="/ppt/theme/theme2.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
              + "".join(f'<Override PartName="/ppt/slides/slide{i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/><Override PartName="/ppt/notesSlides/notesSlide{i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"/>' for i in range(n))
              + '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>')
        root = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{R}/officeDocument" Target="ppt/presentation.xml"/>'
                '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>')
        core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" '
                f'xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>{escape(self.title)}</dc:title><dc:creator>{escape(", ".join(self.authors))}</dc:creator><dc:language>ru-RU</dc:language>'
                '<dcterms:created xsi:type="dcterms:W3CDTF">2026-10-30T00:00:00Z</dcterms:created></cp:coreProperties>')
        rel = lambda body: f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{body}</Relationships>'
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", ct)
            z.writestr("_rels/.rels", root)
            z.writestr("docProps/core.xml", core)
            z.writestr("ppt/presentation.xml", pres)
            z.writestr("ppt/_rels/presentation.xml.rels", pr)
            z.writestr("ppt/theme/theme1.xml", theme)
            z.writestr("ppt/theme/theme2.xml", theme)
            z.writestr("ppt/slideMasters/slideMaster1.xml", master)
            z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", rel(f'<Relationship Id="rId1" Type="{R}/slideLayout" Target="../slideLayouts/slideLayout1.xml"/><Relationship Id="rId2" Type="{R}/theme" Target="../theme/theme1.xml"/>'))
            z.writestr("ppt/slideLayouts/slideLayout1.xml", layout)
            z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", rel(f'<Relationship Id="rId1" Type="{R}/slideMaster" Target="../slideMasters/slideMaster1.xml"/>'))
            z.writestr("ppt/notesMasters/notesMaster1.xml", nm)
            z.writestr("ppt/notesMasters/_rels/notesMaster1.xml.rels", rel(f'<Relationship Id="rId1" Type="{R}/theme" Target="../theme/theme2.xml"/>'))
            for i, s in enumerate(self.slides):
                k = i + 1
                z.writestr(f"ppt/slides/slide{k}.xml", s.xml())
                extra = "".join(f'<Relationship Id="{rid}" Type="{R}/image" Target="../media/{p.rsplit("/", 1)[-1]}"/>' for rid, p in s.media)
                z.writestr(f"ppt/slides/_rels/slide{k}.xml.rels", rel(f'<Relationship Id="rId1" Type="{R}/slideLayout" Target="../slideLayouts/slideLayout1.xml"/><Relationship Id="rId2" Type="{R}/notesSlide" Target="../notesSlides/notesSlide{k}.xml"/>{extra}'))
                for rid, p in s.media:
                    z.write(p, f"ppt/media/{p.rsplit('/', 1)[-1]}")
                z.writestr(f"ppt/notesSlides/notesSlide{k}.xml",
                           f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:notes {NS}><p:cSld><p:spTree>{grp}'
                           '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Slide Image"/><p:cNvSpPr><a:spLocks noGrp="1" noRot="1" noChangeAspect="1"/></p:cNvSpPr><p:nvPr><p:ph type="sldImg"/></p:nvPr></p:nvSpPr><p:spPr/></p:sp>'
                           f'<p:sp><p:nvSpPr><p:cNvPr id="3" name="Notes"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="ru-RU"/><a:t>{escape(s.notes_text)}</a:t></a:r></a:p></p:txBody></p:sp>'
                           '</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:notes>')
                z.writestr(f"ppt/notesSlides/_rels/notesSlide{k}.xml.rels", rel(f'<Relationship Id="rId1" Type="{R}/notesMaster" Target="../notesMasters/notesMaster1.xml"/><Relationship Id="rId2" Type="{R}/slide" Target="../slides/slide{k}.xml"/>'))
