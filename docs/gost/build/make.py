"""Сборка комплекта: python3 make.py [модуль ...]  (по умолчанию все).
Двухпроходная сборка: DOCX -> PDF (LibreOffice) -> номера страниц заголовков (PDFKit) -> оглавление -> DOCX/PDF."""
import importlib, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.dirname(HERE)
LO = os.path.expanduser("~/Applications/LibreOffice.app/Contents/MacOS/soffice")
sys.path.insert(0, HERE)
MODULES = ["d01_tz", "d02_pz", "d03_op", "d04_ro", "d05_rsp", "d06_pmi", "d07_opr", "d08_fo"]
import tempfile

TMP = os.environ.get("GOST_TMP", os.path.join(tempfile.gettempdir(), "gost-build"))
os.makedirs(TMP, exist_ok=True)


def to_pdf(docx: str) -> str:
    subprocess.run([LO, "--headless", "--convert-to", "pdf", "--outdir", TMP, docx], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return os.path.join(TMP, os.path.basename(docx).replace(".docx", ".pdf"))


def pages(pdf: str) -> list[str]:
    js = os.path.join(TMP, "pages.json")
    subprocess.run(["osascript", "-l", "JavaScript", os.path.join(HERE, "pdf_pages.js"), pdf, js], check=True, stdout=subprocess.DEVNULL)
    return json.load(open(js))


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().upper()


def toc_for(heads, pgs):
    start = next(i for i, t in enumerate(pgs) if "СОДЕРЖАНИЕ" in t[:40].upper()) + 1
    cur, res = start, []
    for lvl, text in heads:
        key = norm(text)
        found = None
        for i in range(cur, len(pgs)):
            if key in norm(pgs[i]):
                found = i
                break
        if found is None:
            found = cur
            print("  !! заголовок не найден в PDF:", text, file=sys.stderr)
        cur = found
        res.append((lvl, text, found + 1))
    return res


def build(mod: str):
    m = importlib.import_module(mod)
    name = m.FILE
    path = os.path.join(OUT, name + ".docx")
    toc = None
    for it in range(3):
        d = m.make()
        d.toc = toc
        d.save(path)
        pdf = to_pdf(path)
        new = toc_for(d.heads, pages(pdf))
        if new == toc:
            break
        toc = new
    final_pdf = os.path.join(OUT, name + ".pdf")
    os.replace(pdf, final_pdf)
    print(f"{name}: {len(pages(final_pdf))} стр., заголовков в оглавлении {len(toc)}")


if __name__ == "__main__":
    for mod in (sys.argv[1:] or MODULES):
        build(mod)
