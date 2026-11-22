"""Перевірка середовища: імпорт пакетів і доступність TerraClimate OPeNDAP.

Що робить: імпортує всі прямі залежності, друкує їхні версії, відкриває
лише метадані PDSI з THREDDS (дані не завантажуються) і друкує розмір сітки,
перший та останній місяць у часовому вимірі.
Звідки дані: TERRACLIMATE_OPENDAP з src/config.py.
Запуск з кореня репозиторію: .venv/bin/python src/check_env.py
"""
import sys
from pathlib import Path
from importlib import import_module, metadata

# Дозволяє запуск як `python src/check_env.py` (інакше src не в шляху імпорту).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import TERRACLIMATE_OPENDAP, LAST_COMPLETE_YEAR, FIRST_YEAR

PACKAGES = [
    "xarray", "netCDF4", "pandas", "numpy", "geopandas", "shapely",
    "pyogrio", "regionmask", "matplotlib", "requests", "jsonschema",
]
CHECK_VAR = "pdsi"
# Річні файли THREDDS: ім'я змінної в них "PDSI" (регістр важливий).
YEARLY_URL = (
    "http://thredds.northwestknowledge.net:8080/thredds/dodsC/"
    "TERRACLIMATE_ALL/data/TerraClimate_{var}_{year}.nc"
)
YEARLY_VAR = "PDSI"


def version_of(name, module):
    # jsonschema прибирає __version__, тому беремо версію з метаданих пакета.
    return metadata.version(name)


def main() -> None:
    print(f"Python {sys.version.split()[0]}")
    for name in PACKAGES:
        module = import_module(name)
        print(f"{name:12s} {version_of(name, module)}")

    import xarray as xr

    # 1) Агрегований файл з config. Станом на перевірку сервер віддає для нього
    #    порожню відповідь (HTTP 200, 0 байт), тому очікуємо помилку.
    url = TERRACLIMATE_OPENDAP.format(var=CHECK_VAR)
    print(f"\nOPeNDAP (агрегований, з config): {url}")
    try:
        ds = xr.open_dataset(url, engine="netcdf4")
        da = ds[CHECK_VAR]
        print(f"Сітка: {dict(ds.sizes)}")
        print(f"Перший місяць: {str(ds['time'].values[0])[:7]}")
        print(f"Останній місяць: {str(ds['time'].values[-1])[:7]}")
        ds.close()
        return
    except OSError as err:
        print(f"НЕ ВІДКРИВАЄТЬСЯ: {str(err)[:90]}")

    # 2) Запасний варіант: окремі річні файли (змінна PDSI великими літерами).
    print("\nЗапасний варіант: річні файли")
    first_year, last_year = FIRST_YEAR, LAST_COMPLETE_YEAR
    ds_first = xr.open_dataset(YEARLY_URL.format(var=YEARLY_VAR, year=first_year), engine="netcdf4")
    ds_last = xr.open_dataset(YEARLY_URL.format(var=YEARLY_VAR, year=last_year), engine="netcdf4")
    print(f"Змінна {YEARLY_VAR}: dims={ds_last[YEARLY_VAR].dims}")
    print(f"Сітка (один рік): {dict(ds_last.sizes)}")
    print(f"Перший місяць: {str(ds_first['time'].values[0])[:7]}")
    print(f"Останній місяць: {str(ds_last['time'].values[-1])[:7]}")
    print(f"LAST_COMPLETE_YEAR у config = {LAST_COMPLETE_YEAR}")
    ds_first.close()
    ds_last.close()


if __name__ == "__main__":
    main()
