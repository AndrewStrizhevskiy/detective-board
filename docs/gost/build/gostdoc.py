"""Минимальный генератор DOCX по ГОСТ 2.105 / 7.32 / ЕСПД без внешних зависимостей.

Поля 30/15/20/20 мм, Times New Roman 14, интервал 1,5, абзацный отступ 1,25 см,
нумерация страниц внизу по центру (на титульном листе номера нет).
"""

from __future__ import annotations

import re
import struct
import zipfile
from xml.sax.saxutils import escape

CM = 567  # twips в сантиметре
TEXT_W = 9354  # ширина текста, twips (210-30-15 = 165 мм)
EMU_CM = 360000

NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"'
)


def _run(text: str, bold=False, italic=False, mono=False, size=None, link=False) -> str:
    rpr = '<w:rStyle w:val="Hyperlink"/>' if link else ""
    if mono:
        rpr += '<w:rFonts w:ascii="Courier New" w:hAnsi="Courier New" w:cs="Courier New"/>'
    if bold:
        rpr += "<w:b/>"
    if italic:
        rpr += "<w:i/>"
    if size:
        rpr += f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'
    rpr = f"<w:rPr>{rpr}</w:rPr>" if rpr else ""
    parts = text.split("\n")
    out = []
    for i, part in enumerate(parts):
        if i:
            out.append("<w:br/>")
        out.append(f'<w:t xml:space="preserve">{escape(part)}</w:t>')
    return f"<w:r>{rpr}{''.join(out)}</w:r>"


import os
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
GH_BASE = "https://github.com/AndrewStrizhevskiy/detective-board"
try:
    _SHA = subprocess.run(["git", "-C", REPO, "rev-parse", "16122fc"], capture_output=True, text=True).stdout.strip() or "main"
except Exception:  # noqa: BLE001
    _SHA = "main"
_PATH = re.compile(r"^(?:(?:docs|src|eval|scripts|tests|web|data|prompts)/[\w./-]+|README\.md|THIRD_PARTY_NOTICES\.md|CONTRIBUTING\.md|pyproject\.toml|justfile)$")
_LINKS: list[str] = []


def _url(path: str):
    if not _PATH.match(path) or "..." in path or path.startswith("docs/gost"):
        return None
    full = os.path.join(REPO, path)
    if not os.path.exists(full):
        return None
    kind = "tree" if os.path.isdir(full) else "blob"
    return f"{GH_BASE}/{kind}/{_SHA}/{path.rstrip('/')}"


_TOKEN = re.compile(r"(\*\*.+?\*\*|`.+?`)")


def runs(text: str, size=None, bold=False) -> str:
    """Разметка: **жирный**, `моно`."""
    out = []
    for part in _TOKEN.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            out.append(_run(part[2:-2], bold=True, size=size))
        elif part.startswith("`") and part.endswith("`"):
            code = part[1:-1]
            url = _url(code)
            msz = size - 4 if size else 24
            if url:
                _LINKS.append(url)
                out.append(f'<w:hyperlink r:id="rIdLnk{len(_LINKS)}" w:history="1">{_run(code, mono=True, size=msz, bold=bold, link=True)}</w:hyperlink>')
            else:
                out.append(_run(code, mono=True, size=msz, bold=bold))
        else:
            out.append(_run(part, bold=bold, size=size))
    return "".join(out)


def png_size(path: str) -> tuple[int, int]:
    with open(path, "rb") as f:
        d = f.read(32)
    return struct.unpack(">II", d[16:24])


AUTHORS = ["Верховых Егор", "Стрижевский Андрей", "Парамонов Даниил", "Приц Артём"]


class Doc:
    def __init__(self, title: str, subtitle: str, std: str, props: dict):
        self.title, self.subtitle, self.std, self.props = title, subtitle, std, props
        self.body: list[str] = []
        self.media: list[tuple[str, str]] = []  # (имя в zip, путь на диске)
        self.numbering: list[str] = []  # доп. num для нумерованных списков
        self.n = [0, 0, 0]
        self.tbl_no = 0
        self.fig_no = 0
        self._bm = 0
        self.app_letter = None
        self.heads: list[tuple[int, str]] = []
        _LINKS.clear()
        self.toc = None

    # ----- абзацы -----
    def raw(self, xml: str):
        self.body.append(xml)

    def p(self, text: str, style: str | None = None, align: str | None = None, keep=False, bold=False, size=None):
        ppr = ""
        if style:
            ppr += f'<w:pStyle w:val="{style}"/>'
        if keep:
            ppr += "<w:keepNext/>"
        if align:
            ppr += f'<w:jc w:val="{align}"/>'
        ppr = f"<w:pPr>{ppr}</w:pPr>" if ppr else ""
        self.body.append(f"<w:p>{ppr}{runs(text, size=size, bold=bold)}</w:p>")

    def h(self, level: int, text: str, numbered=True, pagebreak=False):
        if numbered:
            if level == 1:
                self.n = [self.n[0] + 1, 0, 0]
                label = f"{self.n[0]}"
            elif level == 2:
                self.n[1] += 1
                self.n[2] = 0
                label = f"{self.n[0]}.{self.n[1]}"
            else:
                self.n[2] += 1
                label = f"{self.n[0]}.{self.n[1]}.{self.n[2]}"
            text = f"{label} {text}"
        ppr = f'<w:pStyle w:val="Heading{level}"/>'
        if pagebreak:
            ppr += "<w:pageBreakBefore/>"
        self._bm += 1
        if level <= 2:
            self.heads.append((level, text))
        self.body.append(f"<w:p><w:pPr>{ppr}</w:pPr>{_run(text)}</w:p>")

    def appendix(self, letter: str, title: str, kind="обязательное"):
        self.app_letter = letter
        self.n = [0, 0, 0]
        self.tbl_no = 0
        self.fig_no = 0
        self.body.append(
            f'<w:p><w:pPr><w:pStyle w:val="Heading1"/><w:pageBreakBefore/><w:ind w:firstLine="0"/><w:jc w:val="center"/></w:pPr>'
            f"{_run('ПРИЛОЖЕНИЕ ' + letter)}</w:p>"
        )
        self.heads.append((1, f"ПРИЛОЖЕНИЕ {letter}"))
        self.p(f"({kind})", align="center", keep=True)
        self.p(f"**{title}**", align="center", keep=True)

    def ah(self, level: int, text: str):
        """Заголовок внутри приложения: А.1, А.1.1"""
        if level == 2:
            self.n[1] += 1
            self.n[2] = 0
            label = f"{self.app_letter}.{self.n[1]}"
        else:
            self.n[2] += 1
            label = f"{self.app_letter}.{self.n[1]}.{self.n[2]}"
        if level == 2:
            self.heads.append((2, label + " " + text))
        self.body.append(f'<w:p><w:pPr><w:pStyle w:val="Heading{level}"/></w:pPr>{_run(label + " " + text)}</w:p>')

    def fhead(self, label: str, path: str):
        self.body.append(f'<w:p><w:pPr><w:pStyle w:val="FH"/></w:pPr>{_run(label + " ")}{runs(chr(96) + path + chr(96), size=28, bold=True)}</w:p>')

    def ftext(self, text: str):
        self.body.append(f'<w:p><w:pPr><w:pStyle w:val="FT"/></w:pPr>{runs(text)}</w:p>')

    # ----- списки -----
    def bul(self, items: list[str]):
        for it in items:
            self.body.append(
                f'<w:p><w:pPr><w:pStyle w:val="ListDash"/><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr>{runs(it)}</w:p>'
            )

    def num(self, items: list[str]):
        numid = 10 + len(self.numbering)
        self.numbering.append(
            f'<w:num w:numId="{numid}"><w:abstractNumId w:val="2"/>'
            f'<w:lvlOverride w:ilvl="0"><w:startOverride w:val="1"/></w:lvlOverride></w:num>'
        )
        for it in items:
            self.body.append(
                f'<w:p><w:pPr><w:pStyle w:val="ListNum"/><w:numPr><w:ilvl w:val="0"/><w:numId w:val="{numid}"/></w:numPr></w:pPr>{runs(it)}</w:p>'
            )

    # ----- код -----
    def code(self, text: str):
        lines = []
        for ln in text.strip("\n").split("\n"):
            head, sep, tail = ln.partition("  # ")
            if sep and head.strip():  # комментарий в конце строки – отдельной строкой выше
                lines += [f"# {tail.strip()}", head.rstrip()]
            else:
                lines.append(ln)
        for i, ln in enumerate(lines):
            self.body.append(
                f'<w:p><w:pPr><w:pStyle w:val="Code"/>{"<w:keepNext/>" if i < len(lines) - 1 else ""}</w:pPr>'
                f"{_run(ln if ln else ' ', mono=True, size=19)}</w:p>"
            )
        self.body.append('<w:p><w:pPr><w:pStyle w:val="Small"/></w:pPr></w:p>')

    # ----- таблицы -----
    def _label(self, kind: str, n: int) -> str:
        return f"{self.app_letter}.{n}" if self.app_letter else str(n)

    def table(self, caption: str, header: list[str], rows: list[list[str]], widths: list[float] | None = None, fsize: int = 24):
        if caption:
            self.tbl_no += 1
            no = self._label("t", self.tbl_no)
            self.p(f"Таблица {no} – {caption}", style="TableCaption", keep=True)
        k = len(header)
        widths = widths or [1 / k] * k
        tw = [int(TEXT_W * w / sum(widths)) for w in widths]

        def cell(txt: str, w: int, head=False):
            shade = '<w:shd w:val="clear" w:color="auto" w:fill="E7E6E6"/>' if head else ""
            paras = "".join(
                f'<w:p><w:pPr><w:pStyle w:val="TableText"/>{"<w:jc w:val=\"center\"/>" if head else ""}</w:pPr>{runs(line, size=fsize, bold=head)}</w:p>'
                for line in (str(txt).split("\n\n") or [""])
            )
            return f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/>{shade}</w:tcPr>{paras}</w:tc>'

        xml = ['<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="%d" w:type="dxa"/><w:tblLayout w:type="fixed"/></w:tblPr>' % TEXT_W]
        xml.append("<w:tblGrid>" + "".join(f'<w:gridCol w:w="{w}"/>' for w in tw) + "</w:tblGrid>")
        xml.append('<w:tr><w:trPr><w:cantSplit/><w:tblHeader/></w:trPr>' + "".join(cell(h, w, True) for h, w in zip(header, tw)) + "</w:tr>")
        for r in rows:
            r = list(r) + [""] * (k - len(r))
            xml.append("<w:tr><w:trPr><w:cantSplit/></w:trPr>" + "".join(cell(c, w) for c, w in zip(r, tw)) + "</w:tr>")
        xml.append("</w:tbl>")
        self.body.append("".join(xml))
        self.body.append('<w:p><w:pPr><w:pStyle w:val="Small"/></w:pPr></w:p>')

    # ----- рисунки -----
    def figure(self, path: str, caption: str, width_cm: float = 15.5, max_h_cm: float = 19.5):
        self.fig_no += 1
        no = self._label("f", self.fig_no)
        w, h = png_size(path)
        wc = width_cm
        hc = wc * h / w
        if hc > max_h_cm:
            hc = max_h_cm
            wc = hc * w / h
        idx = len(self.media) + 1
        name = f"media/image{idx}.png"
        self.media.append((name, path))
        cx, cy = int(wc * EMU_CM), int(hc * EMU_CM)
        drawing = (
            f'<w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
            f'<wp:docPr id="{idx}" name="Рисунок {idx}" descr="{escape(caption, {chr(34): "&quot;"})}"/>'
            f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{idx}" name="image{idx}.png"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="rIdImg{idx}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
            f"</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing>"
        )
        self.body.append(f'<w:p><w:pPr><w:pStyle w:val="Figure"/><w:keepNext/></w:pPr><w:r>{drawing}</w:r></w:p>')
        self.p(f"Рисунок {no} – {caption}", style="FigCaption")

    def pagebreak(self):
        self.body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')

    # ----- титульные страницы -----
    def title_pages(self, meta_lines: list[str]):
        c = lambda t, b=False, sz=None, size=None: self.p(t, style="Title0", bold=b, size=sz or size)
        simple = not self.std
        if simple:
            for _ in range(3):
                self.p("", style="Title0")
        if not simple:
            c("________________________________________________")
            self.p("(наименование организации – заполнить)", style="Title0", size=20)
            self.p("", style="Title0")
        if not simple:
          self.raw(
            '<w:p><w:pPr><w:pStyle w:val="Title0"/><w:ind w:left="5200"/><w:jc w:val="left"/></w:pPr>'
            + _run("УТВЕРЖДАЮ", bold=True)
            + "</w:p>"
          )
        if not simple:
          for t in ["Должность ____________________", "____________ / ____________", "«____» ______________ 2026 г."]:
            self.raw(f'<w:p><w:pPr><w:pStyle w:val="Title0"/><w:ind w:left="5200"/><w:jc w:val="left"/></w:pPr>{_run(t)}</w:p>')
          self.raw('<w:p><w:pPr><w:pStyle w:val="Title0"/><w:ind w:left="5200"/><w:jc w:val="left"/></w:pPr>' + _run("(поля подписи оставлены пустыми)", italic=True, size=20) + "</w:p>")
        for _ in range(3):
            self.p("", style="Title0")
        c("ДЕТЕКТИВНАЯ ДОСКА (Detective Board)", True, 32)
        c("Локальный офлайн нейро-символический следователь по рассказам о Шерлоке Холмсе")
        self.p("", style="Title0")
        c(self.title.upper(), True, 32)
        if self.subtitle:
            c(self.subtitle)
        if not simple:
            c(self.std)
            self.p("", style="Title0")
            c("Обозначение документа: ____________ (присваивается организацией)", size=24)
        self.p("", style="Title0")
        self.p("**Авторы:**", style="Title0", size=24)
        for a in AUTHORS:
            self.p(a, style="Title0", size=24)
        self.p("", style="Title0")
        for ln in meta_lines:
            self.p(ln, style="Title0", size=24)
        for _ in range(2):
            self.p("", style="Title0")
        c("2026")
        self.pagebreak()
        if not simple:
          self._approval_sheet()
        self.p("**СОДЕРЖАНИЕ**", style="Title0")
        self.body.append('@@TOC@@')
        self.pagebreak()

    def _approval_sheet(self):
        self.p("**ЛИСТ СОГЛАСОВАНИЯ**", style="Title0")
        self.p("Подписи, фамилии и даты не заполнены: документ составлен по состоянию репозитория и не согласован ни с кем.", style="NoIndent")
        self.table(
            None,
            ["Роль", "Должность", "Фамилия И. О.", "Подпись", "Дата"],
            [["Разработал", "", "", "", ""], ["Проверил", "", "", "", ""], ["Нормоконтроль", "", "", "", ""], ["Утвердил", "", "", "", ""]],
            [1.4, 1.6, 1.8, 1.1, 1.0],
        )
        self.pagebreak()

    def change_sheet(self):
        self.h(1, "ЛИСТ РЕГИСТРАЦИИ ИЗМЕНЕНИЙ", numbered=False, pagebreak=True)
        self.table(
            None,
            ["Изм.", "Номера листов (страниц)", "", "", "Всего листов", "№ докум.", "Подп.", "Дата"],
            [["", "изменённых", "замененных", "новых", "", "", "", ""]] + [[""] * 8 for _ in range(4)],
            [0.6, 1.2, 1.2, 0.8, 1, 0.9, 0.8, 0.8],
        )

    def _toc_xml(self) -> str:
        begin = (
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> TOC \\o "1-2" \\h \\z \\u </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        )
        end = '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        entries = self.toc or [(1, "Оглавление не обновлено: в Word выберите «Обновить поле» (Ctrl+A, F9)", "")]
        out = []
        for i, (lvl, text, page) in enumerate(entries):
            pre = begin if i == 0 else ""
            post = end if i == len(entries) - 1 else ""
            out.append(
                f'<w:p><w:pPr><w:pStyle w:val="TOC{lvl}"/></w:pPr>{pre}{_run(text.upper() if lvl == 1 else text)}'
                f'<w:r><w:tab/></w:r>{_run(str(page))}{post}</w:p>'
            )
        return "".join(out)

    # ----- сборка -----
    def save(self, path: str):
        sect = (
            '<w:sectPr><w:footerReference w:type="default" r:id="rIdFtr"/><w:footerReference w:type="first" r:id="rIdFtr1"/>'
            '<w:pgSz w:w="11906" w:h="16838"/>'
            f'<w:pgMar w:top="{20*56.7:.0f}" w:right="{15*56.7:.0f}" w:bottom="{20*56.7:.0f}" w:left="{30*56.7:.0f}" w:header="709" w:footer="567" w:gutter="0"/>'
            "<w:titlePg/></w:sectPr>"
        )
        body = "".join(self.body).replace("@@TOC@@", self._toc_xml())
        doc = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {NS}><w:body>{body}{sect}</w:body></w:document>'
        rels = ['<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>',
                '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>',
                '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>',
                '<Relationship Id="rIdFtr" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>',
                '<Relationship Id="rIdFtr1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer2.xml"/>']
        for i, url in enumerate(_LINKS, 1):
            rels.append(f'<Relationship Id="rIdLnk{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="{escape(url)}" TargetMode="External"/>')
        for i, (name, _) in enumerate(self.media, 1):
            rels.append(f'<Relationship Id="rIdImg{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="{name}"/>')
        footer = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr {NS}><w:p><w:pPr><w:pStyle w:val="Footer"/></w:pPr>'
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>2</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:ftr>'
        )
        footer_first = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr {NS}><w:p><w:pPr><w:pStyle w:val="Footer"/></w:pPr></w:p></w:ftr>'
        numbering = NUMBERING.replace("</w:numbering>", "".join(self.numbering) + "</w:numbering>")
        p = self.props
        core = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f"<dc:title>{escape(self.title)} – Detective Board</dc:title><dc:creator>{escape(p.get('creator', ''))}</dc:creator>"
            f'<dc:language>ru-RU</dc:language><dcterms:created xsi:type="dcterms:W3CDTF">{p["date"]}T00:00:00Z</dcterms:created></cp:coreProperties>'
        )
        ct = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="png" ContentType="image/png"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
            '<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
            '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
            '<Override PartName="/word/footer2.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>'
        )
        root_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>'
        )
        settings = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:settings {NS}><w:defaultTabStop w:val="709"/><w:compat><w:compatSetting w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat></w:settings>'
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", ct)
            z.writestr("_rels/.rels", root_rels)
            z.writestr("word/document.xml", doc)
            z.writestr("word/_rels/document.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(rels) + "</Relationships>")
            z.writestr("word/styles.xml", STYLES)
            z.writestr("word/numbering.xml", numbering)
            z.writestr("word/settings.xml", settings)
            z.writestr("word/footer1.xml", footer)
            z.writestr("word/footer2.xml", footer_first)
            z.writestr("docProps/core.xml", core)
            for name, src in self.media:
                z.write(src, "word/" + name)


def _style(sid, name, based="Normal", ppr="", rpr="", nxt=None, outline=None, typ="paragraph", q=True):
    return (
        f'<w:style w:type="{typ}" w:styleId="{sid}"><w:name w:val="{name}"/>'
        + (f'<w:basedOn w:val="{based}"/>' if based else "")
        + (f'<w:next w:val="{nxt}"/>' if nxt else "")
        + ("<w:qFormat/>" if q else "")
        + (f"<w:pPr>{ppr}</w:pPr>" if ppr else "")
        + (f"<w:rPr>{rpr}</w:rPr>" if rpr else "")
        + "</w:style>"
    )


STYLES = (
    f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles {NS}>'
    '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman" w:eastAsia="Times New Roman"/>'
    '<w:sz w:val="28"/><w:szCs w:val="28"/><w:lang w:val="ru-RU" w:eastAsia="ru-RU"/></w:rPr></w:rPrDefault>'
    '<w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="360" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/>'
    '<w:pPr><w:widowControl/><w:spacing w:after="0" w:line="360" w:lineRule="auto"/><w:ind w:firstLine="709"/><w:jc w:val="both"/></w:pPr></w:style>'
    '<w:style w:type="character" w:default="1" w:styleId="DefaultParagraphFont"><w:name w:val="Default Paragraph Font"/><w:uiPriority w:val="1"/><w:semiHidden/></w:style>'
    '<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/><w:semiHidden/><w:tblPr><w:tblInd w:w="0" w:type="dxa"/>'
    '<w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="108" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>'
    + _style("TableGrid", "Table Grid", "TableNormal", typ="table")
    .replace("</w:style>", '<w:tblPr><w:tblBorders>' + "".join(f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="000000"/>' for s in ["top", "left", "bottom", "right", "insideH", "insideV"]) + "</w:tblBorders></w:tblPr></w:style>")
    + _style("Heading1", "heading 1", ppr='<w:keepNext/><w:keepLines/><w:spacing w:before="240" w:after="120"/><w:ind w:firstLine="709"/><w:jc w:val="left"/><w:outlineLvl w:val="0"/>', rpr="<w:b/><w:caps/>", nxt="Normal")
    + _style("Heading2", "heading 2", ppr='<w:keepNext/><w:keepLines/><w:spacing w:before="200" w:after="80"/><w:ind w:firstLine="709"/><w:jc w:val="left"/><w:outlineLvl w:val="1"/>', rpr="<w:b/>", nxt="Normal")
    + _style("Heading3", "heading 3", ppr='<w:keepNext/><w:keepLines/><w:spacing w:before="160" w:after="60"/><w:ind w:firstLine="709"/><w:jc w:val="left"/><w:outlineLvl w:val="2"/>', rpr="<w:b/><w:i/>", nxt="Normal")
    + '<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/><w:uiPriority w:val="99"/><w:unhideWhenUsed/><w:rPr><w:color w:val="0563C1"/><w:u w:val="single"/></w:rPr></w:style>'
    + _style("FH", "File Heading", ppr='<w:keepNext/><w:keepLines/><w:spacing w:before="140" w:after="20" w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/><w:jc w:val="left"/>', rpr='<w:b/><w:sz w:val="24"/><w:szCs w:val="24"/>', nxt="FT")
    + _style("FT", "File Text", ppr='<w:spacing w:after="40" w:line="252" w:lineRule="auto"/><w:ind w:firstLine="0"/><w:jc w:val="left"/>', rpr='<w:sz w:val="23"/><w:szCs w:val="23"/>')
    + _style("ListDash", "List Dash", ppr='<w:ind w:left="709" w:firstLine="0"/>')
    + _style("ListNum", "List Number", ppr='<w:ind w:left="709" w:firstLine="0"/>')
    + _style("NoIndent", "No Indent", ppr='<w:ind w:firstLine="0"/>')
    + _style("Title0", "Title Page", ppr='<w:spacing w:line="276" w:lineRule="auto"/><w:ind w:firstLine="0"/><w:jc w:val="center"/>')
    + _style("TableText", "Table Text", ppr='<w:spacing w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/><w:jc w:val="left"/>', rpr='<w:sz w:val="24"/><w:szCs w:val="24"/>')
    + _style("TableCaption", "Table Caption", ppr='<w:keepNext/><w:spacing w:before="120" w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/><w:jc w:val="left"/>')
    + _style("Figure", "Figure", ppr='<w:spacing w:before="120" w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/><w:jc w:val="center"/>')
    + _style("FigCaption", "Figure Caption", ppr='<w:spacing w:after="160" w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/><w:jc w:val="center"/>')
    + _style("Code", "Code", ppr='<w:shd w:val="clear" w:color="auto" w:fill="F2F2F2"/><w:spacing w:line="240" w:lineRule="auto"/><w:ind w:left="284" w:firstLine="0"/><w:jc w:val="left"/>', rpr='<w:rFonts w:ascii="Courier New" w:hAnsi="Courier New" w:cs="Courier New"/><w:sz w:val="19"/><w:szCs w:val="19"/>')
    + _style("Small", "Small Spacer", ppr='<w:spacing w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/>', rpr='<w:sz w:val="12"/>')
    + _style("Footer", "footer", ppr='<w:spacing w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/><w:jc w:val="center"/>', rpr='<w:sz w:val="24"/>')
    + _style("TOC1", "toc 1", ppr='<w:tabs><w:tab w:val="right" w:leader="dot" w:pos="9344"/></w:tabs><w:spacing w:line="276" w:lineRule="auto"/><w:ind w:firstLine="0"/><w:jc w:val="left"/>', q=False)
    + _style("TOC2", "toc 2", ppr='<w:tabs><w:tab w:val="right" w:leader="dot" w:pos="9344"/></w:tabs><w:spacing w:line="276" w:lineRule="auto"/><w:ind w:left="284" w:firstLine="0"/><w:jc w:val="left"/>', q=False)
    + _style("TOC3", "toc 3", ppr='<w:tabs><w:tab w:val="right" w:leader="dot" w:pos="9344"/></w:tabs><w:spacing w:line="276" w:lineRule="auto"/><w:ind w:left="567" w:firstLine="0"/><w:jc w:val="left"/>', q=False)
    + "</w:styles>"
)

NUMBERING = (
    f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:numbering {NS}>'
    '<w:abstractNum w:abstractNumId="1"><w:multiLevelType w:val="singleLevel"/><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="–"/><w:lvlJc w:val="left"/>'
    '<w:pPr><w:ind w:left="1276" w:hanging="567"/></w:pPr></w:lvl></w:abstractNum>'
    '<w:abstractNum w:abstractNumId="2"><w:multiLevelType w:val="singleLevel"/><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1)"/><w:lvlJc w:val="left"/>'
    '<w:pPr><w:ind w:left="1276" w:hanging="567"/></w:pPr></w:lvl></w:abstractNum>'
    '<w:num w:numId="1"><w:abstractNumId w:val="1"/></w:num></w:numbering>'
)
