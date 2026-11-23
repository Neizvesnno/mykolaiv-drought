"""Збирає methodology.pdf з docs/methodology.md і звіряє числа з файлами даних.

Що робить:
  1. Читає docs/methodology.md (текст пише людина, а не скрипт).
  2. Перевіряє, що ключові параметри з src/config.py і числа з data/processed
     (summary.json, causes.json, yields.csv) стоять у тексті саме в тому вигляді,
     в якому їх показують людині: кома, мінус «−», 2 знаки (біля порогу 3).
     Якщо хоч одного числа немає, PDF не збирається: так текст не розійдеться з даними
     після перерахунку.
  3. Перетворює markdown на HTML (пакет markdown, розширення tables) зі стилями для друку.
  4. Конвертує HTML у PDF через LibreOffice без вікна (soffice --headless) і кладе
     результат у корінь репозиторію: methodology.pdf.
Звідки дані: docs/methodology.md, src/config.py, data/processed/summary.json,
  causes.json, yields.csv.
Потрібно: пакет markdown у .venv, LibreOffice (команда soffice у PATH).
Запуск з кореня репозиторію: .venv/bin/python -m src.build_methodology
"""

import csv
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import config  # noqa: E402

MD_FILE = config.DOCS_DIR / "methodology.md"
PDF_FILE = config.ROOT / "methodology.pdf"
NBSP = "\u00a0"
SUMMARY = config.PROCESSED_DIR / "summary.json"
CAUSES = config.PROCESSED_DIR / "causes.json"
YIELDS = config.PROCESSED_DIR / "yields.csv"
SOFFICE = "soffice"
# Фільтр імпорту HTML у Writer (а не Writer/Web): тоді діють розміри сторінки й поля.
SOFFICE_INFILTER = "HTML (StarWriter)"

# Правило точності Павла (state.json -> shared.precision): PDSI і відсотки 2 знаки,
# значення біля порогу 3 знаки, щоб було видно, з якого боку порогу воно лежить.
DIGITS = 2
DIGITS_NEAR = 3
PDSI_NEAR_BAND = 0.1   # PDSI у межах ±0,1 від порогу -> 3 знаки

# Стилі для друку: A4, компактний шрифт, щоб текст уміщався у 2–3 сторінки.
CSS = """
@page { size: A4; margin: 1.5cm 1.6cm; }
body { font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 9pt; line-height: 1.3; }
h1, h2, h3 { font-family: 'Helvetica Neue', Arial, sans-serif; }
h1 { font-size: 14pt; margin: 0 0 4pt 0; }
h2 { font-size: 11pt; margin: 9pt 0 3pt 0; }
h3 { font-size: 9.5pt; margin: 6pt 0 2pt 0; }
p, li { margin: 0 0 3pt 0; }
table { border-collapse: collapse; margin: 3pt 0 5pt 0; width: 100%; }
th, td { border: 0.5pt solid #888888; padding: 1pt 4pt; font-size: 8.5pt; vertical-align: top; }
th { background: #e8e8e8; }
code { font-family: Menlo, 'Courier New', monospace; font-size: 8pt; }
a { color: #1a4f8b; }
"""


def fmt(x, digits=DIGITS, sign=False):
    """Число для людини: кома замість крапки, типографський мінус, плюс за потреби."""
    s = f"{x:.{digits}f}".replace(".", ",")
    if s.startswith("-"):
        return "−" + s[1:]
    return ("+" + s) if sign and x > 0 else s


def fmt_pdsi(x):
    """PDSI: 3 знаки біля порогу, інакше 2."""
    near = abs(x - config.DROUGHT_THRESHOLD_PDSI) <= PDSI_NEAR_BAND
    return fmt(x, DIGITS_NEAR if near else DIGITS)


def expected_strings():
    """Рядки, які мають бути в тексті: параметри з config.py і числа з даних."""
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    c = json.loads(CAUSES.read_text(encoding="utf-8"))
    exp = {}

    # Параметри методу (критерій A1).
    exp["сезон"] = f"SEASON_MONTHS = {config.SEASON_MONTHS}"
    exp["назва сезону"] = config.SEASON_LABEL
    exp["поріг"] = f"DROUGHT_THRESHOLD_PDSI = {config.DROUGHT_THRESHOLD_PDSI}"
    exp["норма"] = f"{config.NORMAL_PERIOD[0]}–{config.NORMAL_PERIOD[1]}"
    for a, b in config.COMPARE_PERIODS:
        exp[f"період {a}"] = f"{a}–{b}"
    bb = config.BBOX_DOWNLOAD
    exp["рамка lon"] = f"{fmt(bb['lon_min'], 1)}–{fmt(bb['lon_max'], 1)}"
    exp["рамка lat"] = f"{fmt(bb['lat_min'], 1)}–{fmt(bb['lat_max'], 1)}"

    # Підсумок по роках.
    ff = s["for_farmers"]
    n = s["n_years"]
    exp["за PDSI"] = f"{ff['drought_years_pdsi']} з {n} (1 рік із {fmt(n / ff['drought_years_pdsi'])})"
    exp["підтверджені"] = f"Підтверджених {ff['drought_years_confirmed']} (1 рік із {fmt(n / ff['drought_years_confirmed'])})"
    exp["інерційні"] = "інерційних {} ({})".format(
        ff["inertial_years"], ", ".join(map(str, s["categories"]["інерційна"])))
    for per, d in s["periods"].items():
        exp[f"{per} PDSI"] = (f"{d['drought_years_pdsi']} ({fmt(d['share_pdsi_pct'])} %, "
                              f"1 із {fmt(d['one_year_in_pdsi'])})")
        exp[f"{per} підтв."] = (f"{d['drought_years_confirmed']} ({fmt(d['share_confirmed_pct'])} %, "
                                f"1 із {fmt(d['one_year_in_confirmed'])})")
        exp[f"{per} опадами"] = f"{d['drought_years_confirmed_by_ppt']} з {d['n_years']}"
    for w in s["worst_years"]:
        exp[f"найсухіший {w['year']}"] = f"{w['year']} ({fmt_pdsi(w['pdsi'])})"
    exp["лише ґрунт"] = (f"{len(s['confirmed_by']['ґрунт'])} із {ff['drought_years_confirmed']} "
                         "підтверджених років тримаються лише на ґрунті")

    # Перевірки (критерії A2, A3).
    cc = s["cross_check"]
    exp["опади середня"] = fmt(cc["mean_ppt_anom_pct"]) + " %"
    exp["ґрунт середня"] = fmt(cc["mean_soil_anom_pct"]) + " %"
    exp["чутливість -1,5"] = f"при −1,5 посушливих {s['sensitivity']['-1.5']['n_years']}"
    exp["чутливість -3"] = f"при −3 лише {s['sensitivity']['-3.0']['n_years']}"
    sp = s["spatial"]
    lo, hi = sp["frequency_cells_min_max_pct"]
    exp["частота клітинок"] = f"{fmt(lo)}–{fmt(hi)} %"
    exp["кореляція"] = fmt(sp["corr_frequency_vs_lat"], sign=True)
    for name, r in c["rayons_frequency"].items():
        if name.startswith("_"):
            continue
        short = name.replace(" район", "")
        exp[f"район {short}"] = (f"| {short} | {r['n_cells']} | {fmt(r['frequency_index_pct'])} | "
                                 f"{fmt(r['frequency_confirmed_pct'])} |")
    spread = c["rayons_frequency"]["_spread_pp"]
    exp["розкид"] = f"{fmt(spread['index'])} в.п. за індексом і {fmt(spread['confirmed'])} в.п."

    # Причини.
    diff = c["periods"]["difference"]
    exp["опади мм"] = f"{fmt(abs(diff['ppt_mm']))} мм ({fmt(diff['ppt_pct_of_first'])} %)"
    exp["tmax"] = f"{fmt(diff['tmax_c'])} °C"
    exp["pet"] = f"{fmt(diff['pet_mm'])} мм ({fmt(diff['pet_pct_of_first'], sign=True)} %)"
    exp["баланс"] = f"{fmt(abs(diff['balance_mm']))} мм"
    tr = c["trends"]
    exp["тренд опадів"] = f"{fmt(tr['ppt']['slope_per_decade'])} мм за 10 років (p = {fmt(tr['ppt']['p_value'], 3)})"
    exp["тренд tmax"] = f"{fmt(tr['tmax']['slope_per_decade'], sign=True)} °C"
    exp["тренд pet"] = f"{fmt(tr['pet']['slope_per_decade'], sign=True)} мм"

    # Урожайність: усі роки з обчисленою втратою і середні.
    with open(YIELDS, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["loss_pct"]]
    losses = []
    for r in rows:
        loss = float(r["loss_pct"])
        losses.append((int(r["year"]), loss))
        exp[f"втрата {r['year']}"] = f"| {r['year']} | {fmt(float(r['yield_c_ha']), 1)} |"
        exp[f"втрата {r['year']} %"] = fmt(loss, sign=True) + " |"
    mean_all = sum(v for _, v in losses) / len(losses)
    peace = [v for y, v in losses if y < 2022]   # 2022–2025 — роки війни
    exp["середня"] = f"{fmt(mean_all)} % (n = {len(losses)})"
    exp["без 2022"] = f"{fmt(sum(peace) / len(peace))} % (n = {len(peace)})"
    return exp


def check_numbers(text):
    """Повертає список відсутніх рядків (порожній список = усе збігається)."""
    missing = []
    for key, value in expected_strings().items():
        if value not in text:
            missing.append(f"{key}: «{value}»")
    return missing


def build_html(text):
    body = markdown.markdown(text, extensions=["tables"], output_format="html")
    # LibreOffice не бере рамки таблиць із CSS, тому задаємо їх атрибутами HTML.
    body = body.replace("<table>", '<table border="1" cellspacing="0" cellpadding="3" width="100%">')
    # Нерозривний пробіл, щоб «%» і «°C» не відривались від числа при переносі рядка.
    body = body.replace(" %", NBSP + "%").replace(" °C", NBSP + "°C")
    return ("<!DOCTYPE html><html lang='uk'><head><meta charset='utf-8'>"
            "<title>Методологія: посуха в Миколаївській області</title>"
            f"<style>{CSS}</style></head><body>{body}</body></html>")


def to_pdf(html):
    if shutil.which(SOFFICE) is None:
        sys.exit("Немає soffice у PATH: встановіть LibreOffice.")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "methodology.html"
        src.write_text(html, encoding="utf-8")
        cmd = [SOFFICE, "--headless", f"--infilter={SOFFICE_INFILTER}",
               "--convert-to", "pdf:writer_pdf_Export", "--outdir", tmp, str(src)]
        subprocess.run(cmd, check=True, capture_output=True, timeout=180)
        shutil.move(str(Path(tmp) / "methodology.pdf"), PDF_FILE)


def main():
    text = MD_FILE.read_text(encoding="utf-8")
    missing = check_numbers(text)
    if missing:
        print("Числа в docs/methodology.md не збігаються з даними:")
        print("\n".join("  " + m for m in missing))
        sys.exit(1)
    print(f"Звірка: {len(expected_strings())} чисел і параметрів збігаються з даними.")
    to_pdf(build_html(text))
    print(f"Готово: {PDF_FILE.relative_to(config.ROOT)}")


if __name__ == "__main__":
    main()
