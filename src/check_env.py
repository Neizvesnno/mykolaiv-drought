"""Перевірка середовища: імпорт пакетів і доступність TerraClimate OPeNDAP.

Що робить: імпортує всі прямі залежності, друкує їхні версії, потім для кожної
змінної з config.VARIABLES відкриває річні файли THREDDS за першим (FIRST_YEAR)
і останнім (LAST_COMPLETE_YEAR) роком. Читаються лише метадані (масиви не
завантажуються). Саме ці файли використовує src/download.py.
Звідки дані: config.TERRACLIMATE_OPENDAP.
Код виходу: 0 усе гаразд; 1 якщо пакета немає, мережі немає або файл не відкрився.
Запуск з кореня репозиторію: .venv/bin/python src/check_env.py
"""
import sys
from importlib import import_module, metadata
from pathlib import Path

# Дозволяє запуск як `python src/check_env.py` (інакше src не в шляху імпорту).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import FIRST_YEAR, LAST_COMPLETE_YEAR, TERRACLIMATE_OPENDAP, VARIABLES

PACKAGES = [
    "xarray", "netCDF4", "pandas", "numpy", "geopandas", "shapely",
    "pyogrio", "regionmask", "matplotlib", "requests", "jsonschema",
]
MONTHS_PER_YEAR = 12  # у річному файлі має бути рівно 12 місяців


def check_packages() -> bool:
    ok = True
    print(f"Python {sys.version.split()[0]}")
    for name in PACKAGES:
        try:
            import_module(name)
            # Версію беремо з метаданих пакета: jsonschema прибрав __version__.
            print(f"{name:12s} {metadata.version(name)}")
        except ImportError as err:
            print(f"{name:12s} НЕ ВСТАНОВЛЕНО ({err})")
            ok = False
    return ok


def check_remote() -> bool:
    import xarray as xr

    ok = True
    for var in VARIABLES:
        for year in (FIRST_YEAR, LAST_COMPLETE_YEAR):
            url = TERRACLIMATE_OPENDAP.format(var=var, year=year)
            try:
                with xr.open_dataset(url, engine="netcdf4") as ds:
                    n_time = ds.sizes["time"]
                    first = str(ds["time"].values[0])[:7]
                    last = str(ds["time"].values[-1])[:7]
                    if var not in ds.data_vars:
                        raise KeyError(f"змінної {var} немає у файлі")
                    if n_time != MONTHS_PER_YEAR:
                        raise ValueError(f"місяців {n_time}, очікувалось {MONTHS_PER_YEAR}")
                print(f"OK   {var:5s} {year}: {first}..{last}, {n_time} міс.")
            except Exception as err:  # мережеві та серверні збої бувають різного типу
                print(f"FAIL {var:5s} {year}: {url}\n     {type(err).__name__}: {str(err)[:120]}")
                ok = False
    return ok


def main() -> int:
    ok = check_packages()
    print(f"\nTerraClimate THREDDS, лише метадані: {len(VARIABLES)} змінних x "
          f"роки {FIRST_YEAR} і {LAST_COMPLETE_YEAR}")
    ok = check_remote() and ok
    if not ok:
        print("\nПОМИЛКА: середовище не готове (див. FAIL вище). "
              "Без мережі до THREDDS download.py не завантажить дані.")
        return 1
    print("\nСередовище готове.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
