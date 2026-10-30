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
    json.dump(toc, open(os.path.join(TMP, name + ".toc.json"), "w"), ensure_ascii=False)
    final_pdf = os.path.join(OUT, name + ".pdf")
    os.replace(pdf, final_pdf)
    print(f"{name}: {len(pages(final_pdf))} стр., заголовков в оглавлении {len(toc)}")


def combine():
    import d00_index
    from common import DOCS
    files = []
    for abbr, (f, name, std) in DOCS.items():
        files.append({"pdf": os.path.join(OUT, f + ".pdf"), "title": name, "toc": json.load(open(os.path.join(TMP, f + ".toc.json")))})
    idx_pdf = None
    starts = None
    for _ in range(3):
        d = d00_index.make(starts)
        p = os.path.join(TMP, d00_index.FILE + ".docx")
        d.save(p)
        idx_pdf = to_pdf(p)
        n_idx = len(pages(idx_pdf))
        calc, acc = [], n_idx + 1
        for fl in files:
            calc.append(acc)
            acc += len(pages(fl["pdf"]))
        if calc == starts:
            break
        starts = calc
    spec = {"files": [{"pdf": idx_pdf, "title": None, "toc": []}] + files}
    sp = os.path.join(TMP, "spec.json")
    json.dump(spec, open(sp, "w"), ensure_ascii=False)
    outp = os.path.join(OUT, "00-komplekt-dokumentacii.pdf")
    r = subprocess.run(["osascript", "-l", "JavaScript", os.path.join(HERE, "combine.js"), sp, outp], capture_output=True, text=True)
    print("combine:", r.stdout.strip(), r.stderr.strip()[:300])


if __name__ == "__main__":
    mods = sys.argv[1:]
    for mod in (mods or MODULES):
        if mod != "combine":
            build(mod)
    if not mods or "combine" in mods:
        combine()
