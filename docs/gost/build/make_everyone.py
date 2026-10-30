"""PDF «Проект для всех»: python3 make_everyone.py  (нужен data/file_descriptions.json = слияние описаний файлов)."""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make as M  # noqa: E402
import d09_everyone as E  # noqa: E402


def key_pages(pgs, keys, start):
    res, cur = {}, start
    stripped = [re.sub(r"\s+", "", t) for t in pgs]
    for n, _ in keys:
        k = f"[{n}]"
        for i in range(cur, len(pgs)):
            if k in stripped[i]:
                res[n] = i + 1
                cur = i
                break
    return res


def main():
    pages, toc = None, None
    path = os.path.join(M.OUT, E.FILE + ".docx")
    for it in range(5):
        d = E.make(pages)
        d.toc = toc
        d.save(path)
        pdf = M.to_pdf(path)
        pgs = M.pages(pdf)
        new_toc = M.toc_for(d.heads, pgs)
        start = next(i for i, t in enumerate(pgs) if "СОДЕРЖАНИЕ" in t[:40].upper()) + 1
        new_pages = key_pages(pgs, d.keys, start)
        if new_toc == toc and new_pages == pages:
            break
        toc, pages = new_toc, new_pages
    missing = [n for n, _ in d.keys if n not in pages]
    os.replace(pdf, os.path.join(M.OUT, E.FILE + ".pdf"))
    print(f"{E.FILE}: {len(pgs)} стр., файлов {len(d.keys)}, без страницы {len(missing)}, итераций {it + 1}")


if __name__ == "__main__":
    main()
