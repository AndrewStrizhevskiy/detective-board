"""Минимальный генератор PPTX (16:9, белый фон, Arial) без внешних библиотек."""

import zipfile
from xml.sax.saxutils import escape

EMU = 914400
W, H = 12192000, 6858000


def e(inch: float) -> int:
    return int(inch * EMU)


NS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')

FONT = "Arial"
INK, MUTED, ACCENT, SOFT, WARN = "111111", "595959", "1F3A5F", "EEF1F5", "9B1C1C"


def _rpr(sz, bold=False, color=INK, italic=False):
    return (f'<a:rPr lang="ru-RU" sz="{int(sz * 100)}" b="{1 if bold else 0}" i="{1 if italic else 0}" dirty="0">'
            f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
            f'<a:latin typeface="{FONT}"/><a:cs typeface="{FONT}"/></a:rPr>')


def _para(text, sz, bold=False, color=INK, align="l", space_after=0, italic=False):
    return (f'<a:p><a:pPr algn="{align}" marL="0" indent="0"><a:spcBef><a:spcPts val="0"/></a:spcBef>'
            f'<a:spcAft><a:spcPts val="{int(space_after * 100)}"/></a:spcAft><a:buNone/></a:pPr>'
            f'<a:r>{_rpr(sz, bold, color, italic)}<a:t>{escape(text)}</a:t></a:r></a:p>')


class Slide:
    def __init__(self, num, total):
        self.shapes = []
        self.id = 1
        self.num = num
        self.total = total

    def _id(self):
        self.id += 1
        return self.id

    def title(self, text, sz=40, y=0.45, h=1.0):
        i = self._id()
        self.shapes.append(
            f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="Заголовок"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{e(0.7)}" y="{e(y)}"/><a:ext cx="{e(11.9)}" cy="{e(h)}"/></a:xfrm></p:spPr>'
            f'<p:txBody><a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" anchor="t"><a:normAutofit/></a:bodyPr><a:lstStyle/>{_para(text, sz, True, ACCENT)}</p:txBody></p:sp>')

    def text(self, x, y, w, h, paras, name="Текст", anchor="t"):
        """paras: список (text, sz, bold, color, align, space_after)."""
        i = self._id()
        body = "".join(_para(*p) if isinstance(p, tuple) else _para(p, 24) for p in paras)
        self.shapes.append(
            f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="{escape(name)}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{e(x)}" y="{e(y)}"/><a:ext cx="{e(w)}" cy="{e(h)}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
            f'<p:txBody><a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" anchor="{anchor}"><a:noAutofit/></a:bodyPr><a:lstStyle/>{body}</p:txBody></p:sp>')

    def lines(self, items, x=0.7, y=1.9, w=11.9, sz=28, gap=0.18, h=4.8):
        self.text(x, y, w, h, [(t, sz, False, INK, "l", sz * gap) for t in items], name="Список")

    def box(self, x, y, w, h, text, sz=20, fill=SOFT, color=INK, bold=False, name="Блок", line=None):
        i = self._id()
        ln = f'<a:ln w="19050"><a:solidFill><a:srgbClr val="{line}"/></a:solidFill></a:ln>' if line else '<a:ln><a:noFill/></a:ln>'
        paras = "".join(_para(t, sz, bold, color, "ctr") for t in text.split("\n"))
        self.shapes.append(
            f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="{escape(name)}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{e(x)}" y="{e(y)}"/><a:ext cx="{e(w)}" cy="{e(h)}"/></a:xfrm><a:prstGeom prst="roundRect"><a:avLst><a:gd name="adj" fmla="val 8000"/></a:avLst></a:prstGeom>'
            f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>{ln}</p:spPr>'
            f'<p:txBody><a:bodyPr wrap="square" lIns="91440" tIns="45720" rIns="91440" bIns="45720" anchor="ctr"><a:noAutofit/></a:bodyPr><a:lstStyle/>{paras}</p:txBody></p:sp>')

    def arrow(self, x1, y1, x2, y2, name="Стрелка"):
        i = self._id()
        x, y = min(x1, x2), min(y1, y2)
        w, h = abs(x2 - x1), abs(y2 - y1)
        flip = ""
        if x2 < x1:
            flip += ' flipH="1"'
        if y2 < y1:
            flip += ' flipV="1"'
        self.shapes.append(
            f'<p:cxnSp><p:nvCxnSpPr><p:cNvPr id="{i}" name="{name}"/><p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr>'
            f'<p:spPr><a:xfrm{flip}><a:off x="{e(x)}" y="{e(y)}"/><a:ext cx="{e(w)}" cy="{e(h)}"/></a:xfrm><a:prstGeom prst="line"><a:avLst/></a:prstGeom>'
            f'<a:ln w="28575"><a:solidFill><a:srgbClr val="{ACCENT}"/></a:solidFill><a:tailEnd type="triangle"/></a:ln></p:spPr></p:cxnSp>')

    def number(self):
        i = self._id()
        self.shapes.append(
            f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="Номер слайда"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{e(5.9)}" y="{e(6.95)}"/><a:ext cx="{e(1.5)}" cy="{e(0.35)}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
            f'<p:txBody><a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" anchor="ctr"/><a:lstStyle/><a:p><a:pPr algn="ctr"/>'
            f'<a:fld id="{{B6F15528-21DE-4FAA-801E-634DDDAF4B2B}}" type="slidenum">{_rpr(14, False, MUTED)}<a:t>{self.num}</a:t></a:fld></a:p></p:txBody></p:sp>')

    def xml(self):
        return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sld {NS}><p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>'
                f'<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
                f'{"".join(self.shapes)}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')


class Deck:
    def __init__(self, title, authors):
        self.title, self.authors = title, authors
        self.slides: list[Slide] = []
        self.notes: list[str] = []

    def add(self, total=0):
        s = Slide(len(self.slides) + 1, total)
        self.slides.append(s)
        return s

    def save(self, path):
        n = len(self.slides)
        theme = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Detective Board">'
            '<a:themeElements><a:clrScheme name="DB"><a:dk1><a:srgbClr val="111111"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="1F3A5F"/></a:dk2><a:lt2><a:srgbClr val="EEF1F5"/></a:lt2>'
            '<a:accent1><a:srgbClr val="1F3A5F"/></a:accent1><a:accent2><a:srgbClr val="595959"/></a:accent2><a:accent3><a:srgbClr val="9B1C1C"/></a:accent3><a:accent4><a:srgbClr val="2E7D32"/></a:accent4>'
            '<a:accent5><a:srgbClr val="7A5C00"/></a:accent5><a:accent6><a:srgbClr val="555555"/></a:accent6><a:hlink><a:srgbClr val="1F3A5F"/></a:hlink><a:folHlink><a:srgbClr val="595959"/></a:folHlink></a:clrScheme>'
            f'<a:fontScheme name="DB"><a:majorFont><a:latin typeface="{FONT}"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont><a:minorFont><a:latin typeface="{FONT}"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme>'
            '<a:fmtScheme name="DB"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>'
            '<a:lnStyleLst><a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="12700"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="19050"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>'
            '<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>'
            '<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>')
        grp = '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
        ph_title = (f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="Заголовок"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>'
                    f'<p:spPr><a:xfrm><a:off x="{e(0.7)}" y="{e(0.45)}"/><a:ext cx="{e(11.9)}" cy="{e(1.0)}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
                    f'<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="ru-RU"/><a:t>Заголовок</a:t></a:r></a:p></p:txBody></p:sp>')
        master = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sldMaster {NS}><p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill><a:effectLst/></p:bgPr></p:bg><p:spTree>{grp}{ph_title}</p:spTree></p:cSld>'
                  '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
                  '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
                  f'<p:txStyles><p:titleStyle><a:lvl1pPr algn="l"><a:defRPr sz="4000" b="1"><a:solidFill><a:srgbClr val="{ACCENT}"/></a:solidFill><a:latin typeface="{FONT}"/></a:defRPr></a:lvl1pPr></p:titleStyle>'
                  f'<p:bodyStyle><a:lvl1pPr><a:defRPr sz="2800"><a:latin typeface="{FONT}"/></a:defRPr></a:lvl1pPr></p:bodyStyle><p:otherStyle><a:lvl1pPr><a:defRPr sz="2400"><a:latin typeface="{FONT}"/></a:defRPr></a:lvl1pPr></p:otherStyle></p:txStyles></p:sldMaster>')
        layout = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sldLayout {NS} type="titleOnly" preserve="1"><p:cSld name="Только заголовок"><p:spTree>{grp}{ph_title}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>')
        pres = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:presentation {NS}><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
                f'<p:sldIdLst>{"".join(f"<p:sldId id=\"{256 + i}\" r:id=\"rId{10 + i}\"/>" for i in range(n))}</p:sldIdLst>'
                f'<p:sldSz cx="{W}" cy="{H}"/><p:notesSz cx="6858000" cy="9144000"/><p:defaultTextStyle><a:lvl1pPr><a:defRPr sz="2400"><a:latin typeface="{FONT}"/></a:defRPr></a:lvl1pPr></p:defaultTextStyle></p:presentation>')
        R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        pres_rels = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                     f'<Relationship Id="rId1" Type="{R}/slideMaster" Target="slideMasters/slideMaster1.xml"/><Relationship Id="rId2" Type="{R}/theme" Target="theme/theme1.xml"/>'
                     + "".join(f'<Relationship Id="rId{10 + i}" Type="{R}/slide" Target="slides/slide{i + 1}.xml"/>' for i in range(n)) + "</Relationships>")
        ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
              '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
              '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
              '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
              '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
              + "".join(f'<Override PartName="/ppt/slides/slide{i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>' for i in range(n))
              + '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>')
        root = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{R}/officeDocument" Target="ppt/presentation.xml"/>'
                '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>')
        core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" '
                f'xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>{escape(self.title)}</dc:title><dc:creator>{escape(", ".join(self.authors))}</dc:creator><dc:language>ru-RU</dc:language>'
                '<dcterms:created xsi:type="dcterms:W3CDTF">2026-10-30T00:00:00Z</dcterms:created></cp:coreProperties>')
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", ct)
            z.writestr("_rels/.rels", root)
            z.writestr("docProps/core.xml", core)
            z.writestr("ppt/presentation.xml", pres)
            z.writestr("ppt/_rels/presentation.xml.rels", pres_rels)
            z.writestr("ppt/theme/theme1.xml", theme)
            z.writestr("ppt/slideMasters/slideMaster1.xml", master)
            z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{R}/slideLayout" Target="../slideLayouts/slideLayout1.xml"/><Relationship Id="rId2" Type="{R}/theme" Target="../theme/theme1.xml"/></Relationships>')
            z.writestr("ppt/slideLayouts/slideLayout1.xml", layout)
            z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{R}/slideMaster" Target="../slideMasters/slideMaster1.xml"/></Relationships>')
            for i, s in enumerate(self.slides):
                z.writestr(f"ppt/slides/slide{i + 1}.xml", s.xml())
                z.writestr(f"ppt/slides/_rels/slide{i + 1}.xml.rels", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{R}/slideLayout" Target="../slideLayouts/slideLayout1.xml"/></Relationships>')
