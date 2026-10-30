from common import COMMIT, DATE, DOCS
from gostdoc import Doc

FILE = "00-komplekt-dokumentacii-index"


def make(starts=None, total=None):
    d = Doc("Комплект документации", "", "", {"date": "2026-10-30", "creator": "Команда проекта Detective Board"})
    d.p("**ДЕТЕКТИВНАЯ ДОСКА (Detective Board)**", style="Title0", size=32)
    d.p("Комплект программной документации ЕСПД", style="Title0", size=28)
    d.p(f"Версия комплекса 0.0.1, коммит {COMMIT}, дата составления {DATE}. Черновик: не согласован, подписи и организация не заполнены.", style="Title0", size=24)
    d.p("", style="Title0")
    d.p("Единый PDF: названия документов в таблице – ссылки на их первые страницы; панель закладок содержит оглавление каждого документа; "
        "пути к файлам репозитория в тексте (`docs/...`, `src/...`) – ссылки на GitHub на коммите " + COMMIT + ". Нумерация страниц внутри документов своя.", style="NoIndent")
    rows = []
    for i, (abbr, (f, name, std)) in enumerate(DOCS.items()):
        pg = str(starts[i]) if starts else ""
        rows.append([str(i + 1), name, abbr, std, pg, f + ".docx"])
    d.table("Документы комплекта", ["№", "Документ", "Сокр.", "ГОСТ", "Стр.", "Файл DOCX"], rows, [0.4, 2.6, 0.9, 1.6, 0.8, 2.9])
    d.p("Дополнительно в каталоге `docs/gost/`: `docs/gost/README.md` (перечень), `docs/gost/CHECKLIST.md` (соответствие ГОСТ, пробелы, неизмеренное).", style="NoIndent")
    return d
