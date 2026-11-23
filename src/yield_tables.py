"""Урожайність пшениці в Миколаївській області з 11 збірників Держстату 2010-2020.

Що робить:
  Для кожного випуску «Рослинництво України» (2010, 2011, ..., 2020) бере текст
  табл. 2.6 «Урожайність пшениці» (ц з 1 га), знаходить рядок «Миколаївська» і
  зіставляє його з 7-8 колонками років цього випуску. Результат: таблиця
  рік -> значення -> випуск(и), де той самий рік у різних випусках перевіряється
  на збіг.

Звідки дані: PDF data/raw/statgov/zb_rosl_<YY>.pdf (11 випусків). Текст сторінок
  читає бібліотека pypdf напряму з PDF: жодних проміжних .txt і macOS-інструментів
  (раніше текст витягав PDFKit). Чому pypdf, а не pdfplumber: pypdf (чистий Python,
  одна залежність) віддає для всіх 11 випусків рядки таблиці, що розбираються
  тими самими правилами, і результат збігається з попереднім розбором байт у байт
  (yields.csv не змінився), тож важчий pdfplumber не потрібен. PDF недовірений:
  ми лише читаємо текст і розбираємо його регулярними виразами, нічого не виконуємо.

Сторінку з табл. 2.6 шукаємо за заголовком «2.6. Урожайність пшениці» разом із
  рядком років колонок (зміст містить той самий заголовок, але без рядка років),
  а не за номером сторінки: він різний у різних випусках.

Як знайти рядок Миколаївської (у pypdf-тексті всіх 11 випусків підпис є, метод
  «label»; запасний «position» лишено на випадок PDF без підписів):
  - основний: у рядку є підпис «Миколаївська 39,5 16,4 ...»;
  - запасний: якщо підписів областей у тексті немає, лишаються лише рядки чисел. Тоді беремо рядки, що складаються суто з
    чисел (рядки з «...» відкидаємо), і рахуємо з кінця: останній рядок = Чернігівська,
    Миколаївська = 13-та область із 24, тому це 12-й рядок з кінця. Рахуємо з кінця,
    бо на початку рядки України/Криму то є, то немає.
  Правильність зіставлення перевіряємо за роками, що повторюються між випусками
  (1990 = 39,5, 2000 = 16,4, 2010 = 28,5): див. compare().

Коли той самий рік у різних випусках розходиться, беремо найновіший випуск
  (Держстат уточнює дані).

Як відтворити весь ланцюжок (з кореня репозиторію, .venv з requirements.txt):
  .venv/bin/python -m src.download_yields   # PDF -> data/raw/statgov/
  .venv/bin/python -m src.yield_tables      # PDF -> таблиця рік -> значення (друк)
  .venv/bin/python -m src.yields            # -> data/processed/yields.csv
"""

import re
import sys
from pathlib import Path

from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config

PDF_DIR = config.RAW_DIR / "statgov"
ISSUES = tuple(range(2010, 2021))          # випуски 2010..2020 (11 збірників)
REGION = "Миколаївська"
TITLE_RE = re.compile(r"^2\.6\. *Урожайність пшениці\d?\s*$", re.IGNORECASE)
YEARS_RE = re.compile(r"^(?:\d{4}\d? ){6,7}\d{4}\d?$")   # «1990 2000 ... 20181»
NUM_RE = re.compile(r"^\d+,\d$")
N_OBLASTS = 24
MYKOLAIV_NUMBER = 13                       # 13-та область за абеткою
ROWS_FROM_END = N_OBLASTS - MYKOLAIV_NUMBER + 1   # 12: Миколаївська = rows[-12]


def _find_table_page(pdf_path: Path) -> list[str]:
    """Рядки сторінки з табл. 2.6: є заголовок «2.6. Урожайність пшениці» і рядок років.

    У змісті заголовок теж є, але з крапками-відбивками і без рядка років, тому
    його відсіюємо. Беремо останній збіг (дані стоять після змісту).
    """
    found = []
    for page in PdfReader(pdf_path).pages:
        lines = [s.strip() for s in (page.extract_text() or "").splitlines()]
        if any(TITLE_RE.match(s) for s in lines) and any(YEARS_RE.match(s) for s in lines):
            found.append(lines)
    if not found:
        raise ValueError(f"{pdf_path.name}: сторінку табл. 2.6 не знайдено")
    return found[-1]


def _parse_years(line: str) -> tuple[list[int], list[bool]]:
    """Роки колонок і ознака виноски: «20181» = 2018 з виноскою ¹ (цифра злипла)."""
    toks = line.split()
    return [int(t[:4]) for t in toks], [len(t) == 5 for t in toks]


def extract_issue(issue: int) -> dict:
    """{'years': [...], 'values': [...], 'footnote': [...], 'method': 'label'|'position'}."""
    yy = issue % 100
    block = _find_table_page(PDF_DIR / f"zb_rosl_{yy}.pdf")
    year_line = next(s.strip() for s in block if YEARS_RE.match(s.strip()))
    years, foot = _parse_years(year_line)

    labelled = [s for s in block if s.startswith(REGION)]
    if labelled:
        vals = []
        for tok in labelled[0].split()[1:]:
            if not NUM_RE.match(tok):
                break
            vals.append(float(tok.replace(",", ".")))
        method = "label"
    else:
        rows = [s.split() for s in block
                if len(s.split()) == len(years) and all(NUM_RE.match(t) for t in s.split())]
        vals = [float(t.replace(",", ".")) for t in rows[-ROWS_FROM_END]]
        method = "position"
    if len(vals) != len(years):
        raise ValueError(f"випуск {issue}: {len(vals)} чисел для {len(years)} років")
    return {"years": years, "values": vals, "footnote": foot, "method": method}


def extract_all() -> dict[int, dict]:
    return {i: extract_issue(i) for i in ISSUES}


def build_series(parsed: dict[int, dict] | None = None) -> dict[int, dict]:
    """Рік -> {'value': з найновішого випуску, 'issue', 'all': {випуск: значення}, 'footnote'}."""
    parsed = parsed or extract_all()
    out: dict[int, dict] = {}
    for issue in sorted(parsed):                      # від старого до нового
        p = parsed[issue]
        for y, v, f in zip(p["years"], p["values"], p["footnote"]):
            rec = out.setdefault(y, {"all": {}})
            rec["all"][issue] = v
            rec["value"], rec["issue"], rec["footnote"] = v, issue, f   # новіший перезаписує
    return out


def compare(series: dict[int, dict]) -> list[tuple[int, dict]]:
    """Роки, де значення у випусках розходяться."""
    return [(y, r["all"]) for y, r in sorted(series.items()) if len(set(r["all"].values())) > 1]


def main() -> None:
    parsed = extract_all()
    for i, p in parsed.items():
        print(i, p["method"], dict(zip(p["years"], p["values"])))
    series = build_series(parsed)
    print("\nрік  значення  випуски (значення)")
    for y, r in sorted(series.items()):
        print(y, r["value"], "; ".join(f"{i}:{v}" for i, v in r["all"].items()))
    diffs = compare(series)
    print("\nРозбіжності між випусками:", diffs if diffs else "немає")


if __name__ == "__main__":
    main()
