"""Повний ланцюжок проєкту одним запуском: дані -> аналіз -> рисунки -> PDF.

Що робить: по черзі запускає всі скрипти проєкту, друкує, що саме робить кожен
крок, і зупиняється на першій помилці (код виходу 1).
Звідки дані: кроки download* беруть їх з мережі (TerraClimate, OSM, Держстат),
але вже наявні файли пропускають, тож повторний запуск працює з кешем data/raw/.
Запуск з кореня репозиторію: .venv/bin/python -m src.run_all
Допоміжні ключі: --skip check_env download  (пропустити кроки за назвою),
                 --list (лише показати кроки).
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (назва, як запускати, що робить). "file" = `python src/x.py`, "module" = `python -m src.x`.
# Спосіб запуску взято з docs/methodology.md, розділ «Як відтворити»: скрипти
# check_env/check_data/download/boundaries/rivers/season/drought_years вимагають запуску файлом
# (вони самі додають корінь у sys.path або не мають пакетних імпортів), решта -- модулем.
STEPS = [
    ("check_env", "file", "перевірка пакетів і доступу до TerraClimate (лише метадані)"),
    ("download", "file", "TerraClimate -> data/raw/terraclimate_*.nc (наявні пропускає)"),
    ("check_data", "file", "перевірка даних: пропуски, діапазони, одиниці (data/raw, data/processed)"),
    ("boundaries", "file", "межі області й районів з OSM (з кешем)"),
    ("rivers", "file", "ріки й лимани з OSM (з кешем)"),
    ("season", "file", "сезонні значення квітень-вересень по клітинках і по області"),
    ("drought_years", "file", "категорії років, частоти, summary.json"),
    ("causes", "module", "причини посух, частота по районах"),
    ("fig_timeline", "module", "рисунок: хронологія"),
    ("fig_maps", "module", "рисунок: карти"),
    ("fig_frequency", "module", "рисунок: частота посух"),
    ("download_yields", "module", "збірники Держстату -> data/raw/statgov (наявні пропускає)"),
    ("yield_tables", "module", "таблиці урожайності з PDF (pypdf)"),
    ("yields", "module", "yields.csv: урожайність пшениці і втрати в роки посухи"),
    ("build_slides", "module", "презентація slides/presentation.pptx і .pdf (LibreOffice)"),
    ("build_methodology", "module", "методологія docs/methodology.md -> methodology.pdf"),
    ("build_prompts_pdf", "module", "prompts.pdf (лише якщо src/build_prompts_pdf.py існує)"),
]


def command(name: str, mode: str) -> list[str]:
    # sys.executable: той самий інтерпретатор (.venv), яким запущено run_all.
    if mode == "file":
        return [sys.executable, str(Path("src") / f"{name}.py")]
    return [sys.executable, "-m", f"src.{name}"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip", nargs="+", default=[], metavar="STEP",
                        help="кроки, які не запускати (наприклад check_env)")
    parser.add_argument("--list", action="store_true", help="показати кроки і вийти")
    args = parser.parse_args()

    steps = [s for s in STEPS if s[0] not in args.skip]
    total = len(steps)
    if args.list:
        for i, (name, mode, what) in enumerate(steps, 1):
            print(f"{i:2d}. {name} ({mode}): {what}")
        return 0

    started = time.time()
    for i, (name, mode, what) in enumerate(steps, 1):
        if not (ROOT / "src" / f"{name}.py").exists():
            # Єдиний необов'язковий крок: prompts.pdf збирає окрема задача.
            print(f"[{i}/{total}] {name}: файлу src/{name}.py немає, пропускаю")
            continue
        print(f"\n[{i}/{total}] {name}: {what}", flush=True)
        t0 = time.time()
        result = subprocess.run(command(name, mode), cwd=ROOT)
        if result.returncode != 0:
            print(f"\nПОМИЛКА на кроці {name} (код {result.returncode}), зупиняюсь.")
            return 1
        print(f"[{i}/{total}] {name}: готово за {time.time() - t0:.1f} с", flush=True)
    print(f"\nУсе виконано за {time.time() - started:.1f} с.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
