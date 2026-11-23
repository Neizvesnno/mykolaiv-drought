"""Завантаження PDSI, опадів (ppt) і вологості ґрунту (soil) з TerraClimate.

Що робить: для кожної змінної з config.VARIABLES відкриває річні файли
TerraClimate через OPeNDAP (1958..LAST_COMPLETE_YEAR), вирізає рамку
BBOX_DOWNLOAD, склеює роки і зберігає data/raw/terraclimate_<var>.nc зі стисненням zlib.
Звідки: THREDDS-сервера Northwest Knowledge Network (config.TERRACLIMATE_OPENDAP).
Чому річні файли: агрегований файл на сервері віддає порожню відповідь (див. T02).
Як запустити (з кореня репозиторію):
    .venv/bin/python src/download.py            # пропускає вже наявні файли
    .venv/bin/python src/download.py --force    # перезавантажує все
    .venv/bin/python src/download.py --vars tmax pet   # лише вказані змінні
"""

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import config  # noqa: E402

MAX_WORKERS = 4      # обережно до чужого сервера: не більше 4 паралельних запитів
RETRIES = 4          # спроб на один рік
RETRY_PAUSE_S = 10   # пауза між спробами, секунд (множиться на номер спроби)
ZLIB_LEVEL = 4       # компроміс між розміром і швидкістю запису


def fetch_year(var, year):
    """Завантажує один рік однієї змінної, вирізаючи bbox. Повторює при помилці."""
    url = config.TERRACLIMATE_OPENDAP.format(var=var, year=year)
    b = config.BBOX_DOWNLOAD
    for attempt in range(1, RETRIES + 1):
        try:
            with xr.open_dataset(url) as ds:
                # lat на сервері спадна, тому slice(max, min); lon зростає
                part = ds[var].sel(
                    lat=slice(b["lat_max"], b["lat_min"]),
                    lon=slice(b["lon_min"], b["lon_max"]),
                ).load()
            if part.sizes["time"] != 12:
                raise ValueError(f"очікувалось 12 місяців, є {part.sizes['time']}")
            return part
        except Exception as exc:  # мережеві збої різного типу
            print(f"  [{var} {year}] спроба {attempt}/{RETRIES} невдала: {exc}", flush=True)
            if attempt == RETRIES:
                raise
            time.sleep(RETRY_PAUSE_S * attempt)


def download_variable(var, out_path):
    years = list(range(config.FIRST_YEAR, config.LAST_COMPLETE_YEAR + 1))
    parts = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {y: pool.submit(fetch_year, var, y) for y in years}
        for i, y in enumerate(years, 1):
            parts[y] = futures[y].result()
            print(f"[{var}] {y} готово ({i}/{len(years)})", flush=True)
    da = xr.concat([parts[y] for y in years], dim="time")
    da = da.astype("float32")  # значення вже з застосованими scale_factor/add_offset
    da.encoding = {}
    tmp = out_path.with_suffix(".nc.tmp")
    da.to_dataset(name=var).to_netcdf(
        tmp, encoding={var: {"zlib": True, "complevel": ZLIB_LEVEL, "_FillValue": np.float32(np.nan)}}
    )
    tmp.replace(out_path)  # атомарно: недописаний файл не вважатиметься готовим


def summarize(var, path):
    with xr.open_dataset(path) as ds:
        da = ds[var]
        dlat = float(np.abs(np.diff(ds["lat"].values)).mean())
        dlon = float(np.abs(np.diff(ds["lon"].values)).mean())
        t = ds["time"].values
        print(f"{var}: сітка {ds.sizes['lat']}x{ds.sizes['lon']}, крок lat={dlat:.5f} lon={dlon:.5f} "
              f"(1/30={1/30:.5f}), період {str(t[0])[:7]}..{str(t[-1])[:7]}, "
              f"min={float(da.min()):.2f} max={float(da.max()):.2f}, "
              f"NaN={float(da.isnull().mean()) * 100:.1f}%")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="перезавантажити, навіть якщо файл є")
    parser.add_argument("--vars", nargs="+", choices=list(config.VARIABLES),
                        help="обробити лише ці змінні (за замовчуванням усі з config.VARIABLES)")
    args = parser.parse_args()
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    for var in (args.vars or config.VARIABLES):
        out = config.RAW_DIR / f"terraclimate_{var}.nc"
        if out.exists() and not args.force:
            print(f"[{var}] {out.name} вже є, пропускаю (--force для перезавантаження)")
        else:
            download_variable(var, out)
        summarize(var, out)


if __name__ == "__main__":
    main()
