"""Врожайність пшениці в Миколаївській області і втрата в посушливі роки.

Що робить:
  1. Бере офіційні числа Держстату (врожайність пшениці, ц з 1 га площі, з якої
     зібрано врожай, усі категорії господарств) для Миколаївської області.
     Роки зі збірників 2010-2020 розбирає src/yield_tables.py з текстів у
     data/raw/statgov/text/ (для року береться найновіший випуск); 2021 і 2022 введено
     вручну зі збірників 2021 і 2022 (MANUAL_ROWS). URL і назва джерела (випуск) записуються
     в кожен рядок CSV.
  2. Підтягує категорію року з data/processed/drought_years.csv (T06).
  3. Для кожного підтвердженого посушливого року з даними бере базу: середню
     врожайність сусідніх непосушливих років у вікні ±BASELINE_WINDOW_YEARS.
     Урожайність має технологічний тренд угору, тому порівняння із середнім за
     весь ряд завищило б втрату; сусідні роки мають близький технологічний рівень.
  4. Втрата, % = (врожайність - база) / база * 100 (від'ємна = недобір).
  5. Середня втрата за всі роки з базою і окремо без воєнних років 2022-2025.
Вихід: data/processed/yields.csv (повна точність, без округлення).
Запуск з кореня репозиторію: .venv/bin/python -m src.yields
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from src import config, yield_tables

# --- Параметри методу ---
BASELINE_WINDOW_YEARS = 3                 # база: сусідні роки в межах ±3
EXCLUDED_BASELINE_CATEGORIES = ("підтверджена", "інерційна")  # такі роки не в базу
LOSS_CATEGORY = "підтверджена"            # втрату рахуємо лише для цих років
WAR_YEARS = (2022, 2023, 2024, 2025)      # окремий розрахунок без цих років
ACCESSED = "2026-11-23"
DROUGHT_CSV = config.PROCESSED_DIR / "drought_years.csv"
OUT_CSV = config.PROCESSED_DIR / "yields.csv"

# --- Джерела (Держстат, Рослинництво України) ---
SRC_2021 = ("Держстат, збірник «Рослинництво України» (1990-2021), табл. 2.6 "
            "«Урожайність пшениці», Миколаївська; усі категорії господарств",
            "https://stat.gov.ua/sites/default/files/2026-09/zb_rosl_21.pdf")
SRC_2022 = ("Держстат, збірник «Рослинництво України» (1990-2022), табл. 2.6 "
            "«Урожайність пшениці», Миколаївська; усі категорії господарств",
            "https://stat.gov.ua/sites/default/files/2024-04/%D0%A1%D1%82%D0%B0%D1%82"
            "%D0%B8%D1%81%D1%82%D0%B8%D1%87%D0%BD%D0%B8%D0%B9%20%D0%B7%D0%B1%D1%96%D1%80"
            "%D0%BD%D0%B8%D0%BA%20%C2%AB%D0%A0%D0%BE%D1%81%D0%BB%D0%B8%D0%BD%D0%BD%D0%B8"
            "%D1%86%D1%82%D0%B2%D0%BE%20%D0%A3%D0%BA%D1%80%D0%B0%D1%97%D0%BD%D0%B8%C2%BB"
            "%20%D0%B7%D0%B0%202022%20%D1%80%D1%96%D0%BA.pdf")
URL_ISSUE = "https://stat.gov.ua/sites/default/files/2026-10/zb_rosl_{yy:02d}.pdf"


def src_issue(issue: int) -> tuple[str, str]:
    """Джерело для року, взятого з випуску 2010-2020 (текст розібрано в src/yield_tables.py)."""
    return (f"Держстат, збірник «Рослинництво України» {issue}, табл. 2.6 "
            "«Урожайність пшениці», Миколаївська; усі категорії господарств",
            URL_ISSUE.format(yy=issue % 100))


# Роки зі збірників 2021 і 2022 (їх тексту в data/raw немає, числа введено вручну раніше):
# 2019 є лише в 2021 (у 2022 колонки 2019 немає). Це найновіші випуски, тому для років, що
# збігаються з випусками 2010-2020, лишаємо ці значення (розбіжність build_rows() друкує).
MANUAL_ROWS = [
    (1990, 39.5, SRC_2021), (2000, 16.4, SRC_2021), (2010, 28.5, SRC_2021),
    (2015, 34.2, SRC_2021), (2019, 36.3, SRC_2021), (2020, 27.0, SRC_2021),
    (2021, 42.3, SRC_2021), (2022, 32.0, SRC_2022),
]
NOTE = ("пшениця загалом (озима окремо по області в збірнику не наведена; в області "
        "переважає озима); ц/га, перерахунку не потрібно")
NOTE_FOOTNOTE = (NOTE + "; у цьому випуску колонка року має виноску ¹ «Див. другу виноску до "
                 "табл. 1.8» (посилання на виноску іншої таблиці; її вміст у витягнутому тексті "
                 "однозначно не знайдено)")


def build_rows() -> list[tuple]:
    """(рік, ц/га, джерело, примітка): роки з випусків 2010-2020, поверх них 2021-2022 вручну."""
    series = yield_tables.build_series()
    rows = {}
    for y, r in series.items():
        rows[y] = (y, r["value"], src_issue(r["issue"]), NOTE_FOOTNOTE if r["footnote"] else NOTE)
    for y, v, src in MANUAL_ROWS:
        if y in series and series[y]["value"] != v:
            print(f"Увага: {y}: випуски 2010-2020 дають {series[y]['value']}, 2021/2022 дають {v}; беремо новіший")
        rows[y] = (y, v, src, NOTE)
    return [rows[y] for y in sorted(rows)]


def build_table() -> pd.DataFrame:
    y = pd.DataFrame(
        [(yr, v, note, src[0], src[1], ACCESSED) for yr, v, src, note in build_rows()],
        columns=["year", "yield_c_ha", "note", "source_title", "source_url", "accessed"],
    ).sort_values("year", ignore_index=True)
    cat = pd.read_csv(DROUGHT_CSV)[["year", "category"]]
    return y.merge(cat, on="year", how="left")


def add_losses(t: pd.DataFrame) -> pd.DataFrame:
    base_pool = t[~t["category"].isin(EXCLUDED_BASELINE_CATEGORIES)]
    baselines, n_base = [], []
    for _, r in t.iterrows():
        near = base_pool[(base_pool["year"] - r["year"]).abs().between(1, BASELINE_WINDOW_YEARS)]
        n_base.append(len(near))
        baselines.append(near["yield_c_ha"].mean() if len(near) else float("nan"))
    t = t.assign(baseline_c_ha=baselines, baseline_n_years=n_base)
    t["loss_pct"] = (t["yield_c_ha"] - t["baseline_c_ha"]) / t["baseline_c_ha"] * 100
    t.loc[t["category"] != LOSS_CATEGORY, "loss_pct"] = float("nan")
    return t


def main() -> None:
    t = add_losses(build_table())
    t.to_csv(OUT_CSV, index=False)
    d = t[t["loss_pct"].notna()]
    print(t[["year", "yield_c_ha", "category", "baseline_c_ha", "baseline_n_years", "loss_pct"]])
    print("Середня втрата, усі роки з базою:", d["loss_pct"].mean(), "n =", len(d))
    peace = d[~d["year"].isin(WAR_YEARS)]
    print("Середня втрата без 2022-2025:", peace["loss_pct"].mean(), "n =", len(peace))


if __name__ == "__main__":
    main()
