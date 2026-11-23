"""Перевірка даних: пропуски, діапазони, одиниці (data/raw і data/processed).

Що робить: читає data/raw/terraclimate_*.nc і перевіряє, що ряд місяців
суцільний, без дублів, що маска води (NaN-клітинки) однакова в кожному місяці,
що одиниці в атрибутах і діапазони значень правдоподібні. Потім перевіряє
data/processed: ключі summary.json, 68 років у drought_years.csv без пропусків,
yields.csv без від'ємних урожаїв і з джерелом у кожному рядку.
Звідки дані: лише локальні файли, мережі не потрібно (запускати після download).
Код виходу: 0 усе OK; 1 якщо є хоч один FAIL.
Запуск з кореня репозиторію: .venv/bin/python src/check_data.py
Для перевірки зіпсованої копії: --raw-dir <папка> з копіями terraclimate_*.nc.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config  # noqa: E402

# Очікувана кількість місяців: з FIRST_YEAR по LAST_COMPLETE_YEAR включно.
N_MONTHS = (config.LAST_COMPLETE_YEAR - config.FIRST_YEAR + 1) * 12
N_YEARS = config.LAST_COMPLETE_YEAR - config.FIRST_YEAR + 1

# Очікувані одиниці й межі значень (мін., макс.) для кожної змінної.
# Межі навмисно ширші за фізично можливе для регіону: ловимо збій одиниць
# (Кельвіни замість °C, метри замість мм), а не рідкісні екстремуми.
#   PDSI: шкала Палмера приблизно від -10 до +10, без одиниць.
#   ppt/pet: мм за місяць, не від'ємні; 1000 мм за місяць у степу неможливі.
#   soil: мм у шарі ґрунту, не від'ємна; TerraClimate обмежує 0..~1000 мм.
#   tmax: °C; від -60 до +60 покриває будь-яку помилку масштабу (К = +273).
EXPECTED = {
    "PDSI": {"units": "unitless", "min": -10.0, "max": 10.0},
    "ppt": {"units": "mm", "min": 0.0, "max": 1000.0},
    "soil": {"units": "mm", "min": 0.0, "max": 1000.0},
    "tmax": {"units": "degC", "min": -60.0, "max": 60.0},
    "pet": {"units": "mm", "min": 0.0, "max": 1000.0},
}

SUMMARY_KEYS = [
    "period", "n_years", "threshold_pdsi", "category_rule", "for_farmers",
    "categories", "periods", "cross_check", "sensitivity", "worst_years", "spatial",
]
DROUGHT_YEARS_COLUMNS = ["year", "pdsi", "ppt_anom_pct", "soil_anom_pct", "category"]
YIELDS_SOURCE_COLUMNS = ["source_title", "source_url"]

results = []  # (назва перевірки, True/False, деталі)


def record(name, ok, detail=""):
    results.append((name, bool(ok), detail))


def check_raw(raw_dir: Path) -> None:
    expected_months = pd.date_range(f"{config.FIRST_YEAR}-01-01", periods=N_MONTHS, freq="MS")
    for var, exp in EXPECTED.items():
        path = raw_dir / f"terraclimate_{var}.nc"
        if not path.exists():
            record(f"{var}: файл існує", False, str(path))
            continue
        with xr.open_dataset(path) as ds:
            if var not in ds.data_vars:
                record(f"{var}: змінна у файлі", False, f"є {list(ds.data_vars)}")
                continue
            da = ds[var].load()
        times = pd.DatetimeIndex(da["time"].values)
        record(f"{var}: без дублів місяців", times.is_unique,
               f"{int(times.duplicated().sum())} дублів")
        missing = expected_months.difference(times)
        record(f"{var}: місяці {expected_months[0]:%Y-%m}..{expected_months[-1]:%Y-%m} суцільні",
               len(times) == N_MONTHS and len(missing) == 0,
               f"{len(times)} з {N_MONTHS}, бракує {len(missing)}")
        # Вода (лиман, море) дає NaN в одних і тих самих клітинках щомісяця;
        # якщо кількість NaN коливається, десь випали дані.
        nan_per_month = da.isnull().sum(dim=("lat", "lon")).values
        record(f"{var}: NaN-клітинок на місяць стабільно", len(np.unique(nan_per_month)) == 1,
               f"унікальні значення: {np.unique(nan_per_month).tolist()}")
        record(f"{var}: одиниці '{exp['units']}'", da.attrs.get("units") == exp["units"],
               f"в атрибутах: {da.attrs.get('units')!r}")
        lo, hi = float(da.min()), float(da.max())
        record(f"{var}: діапазон {exp['min']}..{exp['max']}",
               lo >= exp["min"] and hi <= exp["max"], f"фактично {lo}..{hi}")


def check_processed(proc_dir: Path) -> None:
    summary = json.loads((proc_dir / "summary.json").read_text(encoding="utf-8"))
    absent = [k for k in SUMMARY_KEYS if k not in summary]
    record("summary.json: очікувані ключі", not absent, f"немає: {absent}")
    record(f"summary.json: n_years = {N_YEARS}", summary.get("n_years") == N_YEARS,
           f"є {summary.get('n_years')}")

    dy = pd.read_csv(proc_dir / "drought_years.csv")
    record(f"drought_years.csv: {N_YEARS} років", len(dy) == N_YEARS and dy["year"].is_unique,
           f"{len(dy)} рядків, унікальних {dy['year'].nunique()}")
    record("drought_years.csv: роки суцільні",
           dy["year"].tolist() == list(range(config.FIRST_YEAR, config.LAST_COMPLETE_YEAR + 1)))
    cols = [c for c in DROUGHT_YEARS_COLUMNS if c not in dy.columns]
    record("drought_years.csv: потрібні колонки", not cols, f"немає: {cols}")
    nulls = dy[[c for c in DROUGHT_YEARS_COLUMNS if c in dy.columns]].isnull().sum()
    record("drought_years.csv: без пропусків у ключових колонках", int(nulls.sum()) == 0,
           nulls[nulls > 0].to_dict())

    with open(proc_dir / "yields.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    yields = [float(r["yield_c_ha"]) for r in rows]
    record("yields.csv: є рядки", len(rows) > 0, f"{len(rows)} рядків")
    record("yields.csv: урожаї додатні", all(y > 0 for y in yields),
           f"мінімум {min(yields) if yields else None}")
    no_source = [r["year"] for r in rows if any(not r.get(c, "").strip() for c in YIELDS_SOURCE_COLUMNS)]
    record("yields.csv: джерело в кожному рядку", not no_source, f"без джерела: {no_source}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=config.RAW_DIR,
                        help="папка з terraclimate_*.nc (типово data/raw)")
    parser.add_argument("--processed-dir", type=Path, default=config.PROCESSED_DIR)
    args = parser.parse_args()

    check_raw(args.raw_dir)
    check_processed(args.processed_dir)

    for name, ok, detail in results:
        print(f"{'OK  ' if ok else 'FAIL'} {name}" + ("" if ok else f"  <- {detail}"))
    failed = sum(not ok for _, ok, _ in results)
    print(f"\nПеревірок {len(results)}, FAIL {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
