"""Сезонні значення квітень–вересень по клітинках і по області.

Що робить:
  1. Маскує клітинки TerraClimate, центр яких лежить усередині контуру області
     (regionmask). NaN-клітинки (вода: лиман, море) виключає з маски і рахує.
  2. Для кожного повного року 1958..LAST_COMPLETE_YEAR рахує по клітинці:
     середній PDSI за сезон, суму опадів за сезон (мм), середню вологість ґрунту (мм).
  3. Аномалії опадів і вологості ґрунту — у % від норми NORMAL_PERIOD (1991–2020).
  4. Середнє по області з вагою cos(lat) (клітинки 1/30° на півночі менші за площею).
     Також частка площі (з тими ж вагами), де сезонний PDSI <= порогу посухи.
  5. Контроль: перерахунок одного року без regionmask (shapely, точка-в-полігоні).
Звідки дані: data/raw/terraclimate_{PDSI,ppt,soil}.nc (T04),
  data/boundaries/mykolaiv_oblast.geojson (T03). Параметри — з src/config.py.
Вихід: data/processed/season_cells.nc, data/processed/season_oblast.csv.
Запуск з кореня репозиторію: .venv/bin/python src/season.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import geopandas as gpd
import numpy as np
import pandas as pd
import regionmask
import shapely
import xarray as xr

from src import config

CONTROL_YEAR = 2025          # рік для контрольного перерахунку
CONTROL_TOLERANCE = 0.05     # допуск за критерієм приймання, одиниць PDSI
OUT_CELLS = config.PROCESSED_DIR / "season_cells.nc"
OUT_CSV = config.PROCESSED_DIR / "season_oblast.csv"
COL_SHARE = "area_share_pdsi_le_-2"  # ім'я колонки задано в завданні


def load_season():
    """Сезонні агрегати по клітинках: dims (year, lat, lon)."""
    out = {}
    for var, how in [("PDSI", "mean"), ("ppt", "sum"), ("soil", "mean")]:
        ds = xr.open_dataset(config.RAW_DIR / f"terraclimate_{var}.nc")[var]
        ds = ds.sel(time=ds.time.dt.month.isin(config.SEASON_MONTHS))
        ds = ds.sel(time=slice(f"{config.FIRST_YEAR}-01-01",
                               f"{config.LAST_COMPLETE_YEAR}-12-31"))
        grouped = ds.groupby("time.year")
        # min_count: якщо немає всіх 6 місяців чи є NaN, сезон не рахуємо
        # (NaN води лишається NaN, а не стає нулем опадів).
        agg = grouped.sum(skipna=False) if how == "sum" else grouped.mean(skipna=False)
        out[var] = agg
    return out


def anomaly_pct(da):
    """Аномалія у % від норми 1991–2020 (норма — середнє за ці сезони)."""
    y0, y1 = config.NORMAL_PERIOD
    norm = da.sel(year=slice(y0, y1)).mean("year")
    return (da - norm) / norm * 100.0


def oblast_mask(lat, lon):
    """Булева маска (lat, lon): центр клітинки у полігоні області."""
    gdf = gpd.read_file(config.BOUNDARIES_DIR / "mykolaiv_oblast.geojson")
    regions = regionmask.from_geopandas(gdf)
    # Передаємо чисті масиви numpy: з DataArray regionmask нічого не знаходить.
    m = regions.mask(lon.values, lat.values)  # NaN поза полігоном, 0 усередині
    return xr.DataArray(m.notnull().values, coords={"lat": lat, "lon": lon},
                        dims=("lat", "lon"))


def weighted_mean(da, mask, w):
    """Середнє по області з вагою cos(lat) лише по клітинках маски."""
    ww = w.where(mask)
    return (da * ww).sum(("lat", "lon")) / ww.where(da.notnull()).sum(("lat", "lon"))


def main():
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    s = load_season()
    pdsi, ppt, soil = s["PDSI"], s["ppt"], s["soil"]
    lat, lon = pdsi["lat"], pdsi["lon"]

    in_poly = oblast_mask(lat, lon)
    # Суша: є дані в усі роки. Вода (лиман, море) усередині контуру OSM — виключаємо.
    has_data = pdsi.notnull().all("year") & ppt.notnull().all("year") & soil.notnull().all("year")
    land = in_poly & has_data
    n_poly, n_land = int(in_poly.sum()), int(land.sum())
    n_water = n_poly - n_land
    print(f"Клітинок із центром у полігоні: {n_poly}; суша з даними: {n_land}; "
          f"вода (NaN) виключена: {n_water}")

    ppt_anom, soil_anom = anomaly_pct(ppt), anomaly_pct(soil)

    cells = xr.Dataset(
        {
            "pdsi": pdsi.where(land),
            "ppt_mm": ppt.where(land),
            "soil_mm": soil.where(land),
            "ppt_anom_pct": ppt_anom.where(land),
            "soil_anom_pct": soil_anom.where(land),
            "land_mask": land,
        },
        attrs={
            "title": f"Сезонні значення {config.SEASON_LABEL}, Миколаївська область",
            "n_cells_center_in_polygon": n_poly,
            "n_cells_land": n_land,
            "n_cells_water_excluded": n_water,
            "normal_period": f"{config.NORMAL_PERIOD[0]}-{config.NORMAL_PERIOD[1]}",
            "source": "TerraClimate; межі © OpenStreetMap contributors, ODbL 1.0",
        },
    )
    cells["pdsi"].attrs["units"] = "PDSI"
    cells["ppt_mm"].attrs["units"] = "mm per season (sum)"
    cells["soil_mm"].attrs["units"] = "mm (season mean)"
    cells["ppt_anom_pct"].attrs["units"] = "% of 1991-2020 normal"
    cells["soil_anom_pct"].attrs["units"] = "% of 1991-2020 normal"
    cells["land_mask"] = cells["land_mask"].astype("int8")
    cells.to_netcdf(OUT_CELLS)

    w = np.cos(np.deg2rad(lat))
    drought = (pdsi <= config.DROUGHT_THRESHOLD_PDSI).where(pdsi.notnull())
    table = pd.DataFrame({
        "year": pdsi["year"].values,
        "pdsi": weighted_mean(pdsi, land, w).values,
        "ppt_mm": weighted_mean(ppt, land, w).values,
        "soil_mm": weighted_mean(soil, land, w).values,
        "ppt_anom_pct": weighted_mean(ppt_anom, land, w).values,
        "soil_anom_pct": weighted_mean(soil_anom, land, w).values,
        COL_SHARE: weighted_mean(drought, land, w).values,
    })
    table.round(4).to_csv(OUT_CSV, index=False)
    print(table.tail(3).round(3).to_string(index=False))

    # --- Контроль без regionmask: точка-в-полігоні через shapely ---
    gdf = gpd.read_file(config.BOUNDARIES_DIR / "mykolaiv_oblast.geojson")
    geom = gdf.geometry.union_all() if hasattr(gdf.geometry, "union_all") else gdf.unary_union
    LON, LAT = np.meshgrid(lon.values, lat.values)
    inside = shapely.contains_xy(geom, LON, LAT)
    year_pdsi = pdsi.sel(year=CONTROL_YEAR).values
    ok = inside & ~np.isnan(year_pdsi)
    wt = np.cos(np.deg2rad(LAT))
    control = float((year_pdsi[ok] * wt[ok]).sum() / wt[ok].sum())
    main_val = float(table.loc[table.year == CONTROL_YEAR, "pdsi"].iloc[0])
    print(f"Контроль {CONTROL_YEAR}: основний {main_val:.4f}, shapely {control:.4f}, "
          f"|Δ|={abs(main_val - control):.5f}, клітинок {int(ok.sum())}")
    assert abs(main_val - control) < CONTROL_TOLERANCE, "контрольний перерахунок не збігся"

    # Перевірка A1: усередині маски немає NaN
    for v in ["pdsi", "ppt_mm", "soil_mm", "ppt_anom_pct", "soil_anom_pct"]:
        n_nan = int(cells[v].where(land).isnull().where(land).sum())
        print(f"NaN усередині маски, {v}: {n_nan}")


if __name__ == "__main__":
    main()
