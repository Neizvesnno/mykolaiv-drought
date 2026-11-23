"""Завантаження збірників Держстату «Рослинництво України» 2010-2020 (11 PDF).

Що робить:
  Для кожного випуску зі списку ISSUES качає PDF
  https://stat.gov.ua/sites/default/files/2026-10/zb_rosl_<YY>.pdf у
  data/raw/statgov/zb_rosl_<YY>.pdf. Уже наявні файли пропускає (повторний запуск
  безпечний і мережі не потребує). Після завантаження перевіряє, що файл справді
  PDF (перші байти «%PDF-»); інакше видаляє його й завершується помилкою, щоб
  сторінка помилки не потрапила в дані. data/raw у .gitignore.

Як відтворити весь ланцюжок (з кореня репозиторію, .venv з requirements.txt):
  .venv/bin/python -m src.download_yields   # PDF -> data/raw/statgov/
  .venv/bin/python -m src.yield_tables      # PDF -> таблиця рік -> значення (друк)
  .venv/bin/python -m src.yields            # -> data/processed/yields.csv
"""

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config

URL_TEMPLATE = "https://stat.gov.ua/sites/default/files/2026-10/zb_rosl_{yy:02d}.pdf"
ISSUES = tuple(range(2010, 2021))          # випуски 2010..2020, YY = 10..20
OUT_DIR = config.RAW_DIR / "statgov"
PDF_MAGIC = b"%PDF-"
TIMEOUT_S = 120


def _is_pdf(path: Path) -> bool:
    with path.open("rb") as f:
        return f.read(len(PDF_MAGIC)) == PDF_MAGIC


def download_issue(issue: int) -> str:
    """Повертає 'skipped' (файл уже є) або 'downloaded'."""
    yy = issue % 100
    out = OUT_DIR / f"zb_rosl_{yy:02d}.pdf"
    if out.exists() and _is_pdf(out):
        return "skipped"
    url = URL_TEMPLATE.format(yy=yy)
    r = requests.get(url, timeout=TIMEOUT_S)
    r.raise_for_status()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.write_bytes(r.content)
    if not _is_pdf(out):
        out.unlink()                      # не лишаємо не-PDF у сирих даних
        raise ValueError(f"{url}: відповідь не є PDF")
    return "downloaded"


def main() -> None:
    for issue in ISSUES:
        print(issue, URL_TEMPLATE.format(yy=issue % 100), download_issue(issue))


if __name__ == "__main__":
    main()
