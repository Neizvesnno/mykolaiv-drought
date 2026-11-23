"""Посушливі роки, частота посухи по клітинках, перевірка опадами і ґрунтом.

Що робить:
  1. Посушливий рік: середній по області сезонний PDSI <= DROUGHT_THRESHOLD_PDSI,
     з класом за Палмером (помірна / сильна / екстремальна).
  2. Категорія кожного з 68 років (підтверджена / інерційна / немає) за правилом
     нижче: PDSI інерційний («пам'ять» попередніх сухих років), тому сам по собі
     може позначити рік посушливим, хоча опади були вищі за норму (2008, 1990).
  3. Частота посухи по клітинках (скільки років з N мали PDSI <= порогу) і
     середній PDSI посушливих років по клітинках -> drought_frequency.nc;
     середня частота по 4 районах і північ/південь.
  4. Порівняння 1958-1990 і 1991-останній рік: абсолютно і як «1 рік із N».
  5. Чутливість до порогу (-1,5 і -3).
Звідки дані: data/processed/season_oblast.csv і season_cells.nc (T05),
  data/boundaries/mykolaiv_rayons.geojson (T03). Спільні параметри: src/config.py.
Вихід: data/processed/drought_years.csv, drought_frequency.nc, summary.json.
Запуск з кореня репозиторію: .venv/bin/python src/drought_years.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import geopandas as gpd
import numpy as np
import pandas as pd
import regionmask
import xarray as xr

from src import config

# --- Правило категорії (config-стиль; змінюється лише тут) ---
# 'підтверджена': PDSI <= порогу І (аномалія опадів <= PPT_ANOM_MAX_PCT
#                 АБО аномалія вологості ґрунту <= SOIL_ANOM_MAX_PCT).
# 'інерційна':    PDSI <= порогу, але ні опади, ні ґрунт не показують посухи:
#                 індекс «пам'ятає» попередні сухі роки.
# 'немає':        PDSI > порогу.
# Обидва пороги однакові (-20 %). Спершу для опадів стояло «< 0 %», але тоді
# 2015 і 2023 вважались посухою лише через опади на 12–13 % нижче норми при
# нормальному ґрунті (рішення Павла 23.11.2026, див. prompts.md, сесія 3).
PPT_ANOM_MAX_PCT = -20.0    # опади сухі = на 20 % і більше нижче норми
SOIL_ANOM_MAX_PCT = -20.0   # ґрунт сухий = на 20 % і більше нижче норми
CAT_CONFIRMED, CAT_INERTIAL, CAT_NONE = "підтверджена", "інерційна", "немає"

# Пороги чутливості (з завдання).
SENSITIVITY_THRESHOLDS = [-1.5, -3.0]

# Межі класів Палмера (див. config.PDSI_CLASSES): екстремальна <= -4, сильна <= -3.
CLASS_EXTREME, CLASS_SEVERE = -4.0, -3.0

# Середня частота по клітинках: «північ» і «південь» — вище/нижче медіани широти.
OUT_CSV = config.PROCESSED_DIR / "drought_years.csv"
OUT_NC = config.PROCESSED_DIR / "drought_frequency.nc"
OUT_JSON = config.PROCESSED_DIR / "summary.json"


def pdsi_class(v):
    """Клас за Палмером; для років вище порогу -2 — 'немає посухи'."""
    if v <= CLASS_EXTREME:
        return "екстремальна"
    if v <= CLASS_SEVERE:
        return "сильна"
    if v <= config.DROUGHT_THRESHOLD_PDSI:
        return "помірна"
    return "немає посухи"


def categorize(row):
    if row.pdsi > config.DROUGHT_THRESHOLD_PDSI:
        return CAT_NONE
    if row.ppt_anom_pct <= PPT_ANOM_MAX_PCT or row.soil_anom_pct <= SOIL_ANOM_MAX_PCT:
        return CAT_CONFIRMED
    return CAT_INERTIAL


def one_in_n(k, n):
    """'1 рік із N' (N не округлюємо; округлення лише при показі); None, якщо k = 0."""
    return n / k if k else None


def fmt_one_in(x):
    """Показ «1 рік із N»: 2 знаки, кома (правило точності; у файлах число повне)."""
    return f"{x:.2f}".replace(".", ",")


def period_stats(table, y0, y1):
    sub = table[(table.year >= y0) & (table.year <= y1)]
    n = len(sub)
    k_pdsi = int(sub.drought_pdsi.sum())
    k_conf = int((sub.category == CAT_CONFIRMED).sum())
    return {
        "years": f"{y0}-{y1}", "n_years": n,
        "drought_years_pdsi": k_pdsi, "share_pdsi_pct": 100 * k_pdsi / n,
        "one_year_in_pdsi": one_in_n(k_pdsi, n),
        "drought_years_confirmed": k_conf,
        "share_confirmed_pct": 100 * k_conf / n,
        "one_year_in_confirmed": one_in_n(k_conf, n),
        "years_list_pdsi": [int(y) for y in sub[sub.drought_pdsi].year],
        "years_list_confirmed": [int(y) for y in sub[sub.category == CAT_CONFIRMED].year],
        # Найсуворіша перевірка: лише опади, бо тільки вони незалежні від PDSI.
        "drought_years_confirmed_by_ppt": int(sub.confirmed_by_ppt.sum()),
        "one_year_in_confirmed_by_ppt": one_in_n(int(sub.confirmed_by_ppt.sum()), n),
    }


def confirmed_by(row):
    """Яка ознака підтверджує посуху: 'опади', 'ґрунт', 'обидва' або '' (не підтверджена).

    Вологість ґрунту в TerraClimate рахується з тієї самої моделі водного балансу,
    що й PDSI (опади мінус випаровування). Тому «підтвердження лише ґрунтом» —
    частково той самий сигнал. Справді незалежна ознака тут тільки опади.
    """
    if row.category != CAT_CONFIRMED:
        return ""
    if row.ppt_dry and row.soil_dry:
        return "обидва"
    return "опади" if row.ppt_dry else "ґрунт"


def main():
    last = config.LAST_COMPLETE_YEAR
    ob = pd.read_csv(config.PROCESSED_DIR / "season_oblast.csv")
    thr = config.DROUGHT_THRESHOLD_PDSI

    # --- 1-2. Роки, класи, категорії ---
    t = ob[["year", "pdsi", "ppt_anom_pct", "soil_anom_pct",
            "area_share_pdsi_le_-2"]].copy()
    t["drought_pdsi"] = t.pdsi <= thr
    t["pdsi_class"] = t.pdsi.map(pdsi_class)
    t["ppt_negative"] = t.ppt_anom_pct < 0       # опис: опади нижче норми взагалі
    t["ppt_dry"] = t.ppt_anom_pct <= PPT_ANOM_MAX_PCT  # правило категорії
    t["soil_dry"] = t.soil_anom_pct <= SOIL_ANOM_MAX_PCT
    t["category"] = t.apply(categorize, axis=1)
    t["confirmed_by"] = t.apply(confirmed_by, axis=1)
    t["confirmed_by_ppt"] = t.confirmed_by.isin(["опади", "обидва"])
    for s in SENSITIVITY_THRESHOLDS:
        t[f"drought_le_{s}"] = t.pdsi <= s
    t.to_csv(OUT_CSV, index=False)

    # --- 3. Клітинки ---
    cells = xr.open_dataset(config.PROCESSED_DIR / "season_cells.nc")
    land = cells["land_mask"].astype(bool)
    pdsi = cells["pdsi"]
    dry = (pdsi <= thr).where(land)
    n_years = pdsi.sizes["year"]
    freq_years = dry.sum("year").where(land)                 # скільки років з N
    freq = freq_years / n_years
    mean_dry = pdsi.where(pdsi <= thr).mean("year").where(land)  # середній PDSI сухих років
    # Частота за категорією «підтверджена» (роки відомі по області, не по клітинці).
    conf_years = t[t.category == CAT_CONFIRMED].year.values
    freq_conf = (dry.sel(year=conf_years).sum("year") / n_years).where(land)

    # Райони: центр клітинки у полігоні району.
    rg = gpd.read_file(config.BOUNDARIES_DIR / "mykolaiv_rayons.geojson")
    reg = regionmask.from_geopandas(rg, names="name")
    idx = reg.mask(cells["lon"].values, cells["lat"].values)
    idx = xr.DataArray(idx.values, coords={"lat": cells["lat"], "lon": cells["lon"]},
                       dims=("lat", "lon"))
    rayons = {}
    for i, name in enumerate(rg["name"]):
        m = (idx == i) & land
        rayons[name] = {
            "n_cells": int(m.sum()),
            "mean_frequency_pct": float(freq.where(m).mean()) * 100,
            "mean_pdsi_dry_years": float(mean_dry.where(m).mean()),
        }
    # Північ/південь: клітинки вище/нижче медіани широти суші.
    lat2d = cells["lat"].broadcast_like(freq)
    med = float(lat2d.where(land).median())
    north, south = land & (lat2d >= med), land & (lat2d < med)
    ns = {
        "median_lat": med,
        "north_mean_frequency_pct": float(freq.where(north).mean()) * 100,
        "south_mean_frequency_pct": float(freq.where(south).mean()) * 100,
        "north_mean_pdsi_dry_years": float(mean_dry.where(north).mean()),
        "south_mean_pdsi_dry_years": float(mean_dry.where(south).mean()),
    }
    # Кореляція частоти з широтою по клітинках (знак > 0: на півночі частіше).
    ok = land.values & np.isfinite(freq.values)
    corr_lat = float(np.corrcoef(lat2d.values[ok], freq.values[ok])[0, 1])

    out = xr.Dataset(
        {
            "drought_years_count": freq_years,
            "drought_frequency": freq,
            "mean_pdsi_drought_years": mean_dry,
            "drought_frequency_confirmed_years": freq_conf,
            "rayon_index": idx.where(land),
            "land_mask": cells["land_mask"],
        },
        attrs={
            "title": "Частота посухи по клітинках, Миколаївська область",
            "threshold_pdsi": thr,
            "n_years": int(n_years),
            "years": f"{config.FIRST_YEAR}-{last}",
            "rayon_index_names": "; ".join(f"{i}={n}" for i, n in enumerate(rg["name"])),
            "source": "TerraClimate; межі © OpenStreetMap contributors, ODbL 1.0",
        },
    )
    out["drought_years_count"].attrs["long_name"] = "років із PDSI <= порогу"
    out["drought_frequency"].attrs["long_name"] = "частка років із PDSI <= порогу (0..1)"
    out["mean_pdsi_drought_years"].attrs["long_name"] = "середній PDSI у посушливі роки клітинки"
    out["drought_frequency_confirmed_years"].attrs["long_name"] = (
        "частка років, що є підтвердженими по області і мають PDSI <= порогу в клітинці")
    out.to_netcdf(OUT_NC)

    # --- 4. Періоди ---
    periods = {f"{a}-{b}": period_stats(t, a, b) for a, b in config.COMPARE_PERIODS}

    # --- 5. Чутливість ---
    sens = {}
    for s in [thr] + SENSITIVITY_THRESHOLDS:
        yrs = [int(y) for y in t[t.pdsi <= s].year]
        sens[str(s)] = {"n_years": len(yrs), "years": yrs}

    cat_lists = {c: [int(y) for y in t[t.category == c].year]
                 for c in (CAT_CONFIRMED, CAT_INERTIAL, CAT_NONE)}
    n_all = len(t)
    n_pdsi = int(t.drought_pdsi.sum())
    n_conf = len(cat_lists[CAT_CONFIRMED])

    # Перехресна перевірка: у скількох PDSI-посушливих роках опади / ґрунт від'ємні.
    d = t[t.drought_pdsi]
    cross = {
        "n_drought_years_pdsi": len(d),
        "ppt_anom_negative": int(d.ppt_negative.sum()),
        "soil_anom_negative": int((d.soil_anom_pct < 0).sum()),
        "soil_dry_le_minus20": int(d.soil_dry.sum()),
        "both_ppt_and_soil_negative": int((d.ppt_negative & (d.soil_anom_pct < 0)).sum()),
        "mean_ppt_anom_pct": float(d.ppt_anom_pct.mean()),
        "mean_soil_anom_pct": float(d.soil_anom_pct.mean()),
        "ppt_above_norm_years": [int(y) for y in d[~d.ppt_negative].year],
    }

    summary = {
        "period": f"{config.FIRST_YEAR}-{last}",
        "n_years": n_all,
        "threshold_pdsi": thr,
        "category_rule": {
            "confirmed": f"PDSI <= {thr} і (аномалія опадів <= {PPT_ANOM_MAX_PCT}% "
                         f"або аномалія вологості ґрунту <= {SOIL_ANOM_MAX_PCT}%)",
            "inertial": "PDSI <= порогу, але ні опади, ні ґрунт не сухі за правилом",
            "none": "PDSI > порогу",
        },
        "for_farmers": {
            "drought_years_pdsi": n_pdsi,
            "drought_years_confirmed": n_conf,
            "inertial_years": len(cat_lists[CAT_INERTIAL]),
            "text_pdsi": f"{n_pdsi} з {n_all} сезонів: 1 рік із {fmt_one_in(one_in_n(n_pdsi, n_all))} (за PDSI)",
            "text_confirmed": f"{n_conf} з {n_all} сезонів: 1 рік із {fmt_one_in(one_in_n(n_conf, n_all))} (підтверджені)",
        },
        "categories": cat_lists,
        "confirmed_by": {
            k: [int(y) for y in t[t.confirmed_by == k].year] for k in ["опади", "обидва", "ґрунт"]
        },
        "confirmed_by_note": ("Ґрунт і PDSI в TerraClimate — з однієї моделі водного балансу, "
                              "тому незалежне підтвердження дають лише опади ('опади' + 'обидва')."),
        "class_counts_pdsi_drought_years": {k: int(v) for k, v in d.pdsi_class.value_counts().items()},
        "periods": periods,
        "cross_check": cross,
        "sensitivity": sens,
        "worst_years": [{"year": int(r.year), "pdsi": float(r.pdsi)}
                        for r in t.nsmallest(5, "pdsi").itertuples()],
        "area_share_note": {
            "years_with_share_ge_0.95": int((t["area_share_pdsi_le_-2"] >= 0.95).sum()),
            "drought_years_with_share_1.0": int((d["area_share_pdsi_le_-2"] >= 0.999).sum()),
        },
        "spatial": {
            "rayons": rayons, **ns,
            "corr_frequency_vs_lat": float(corr_lat),
            "frequency_cells_min_max_pct": [float(freq.min()) * 100,
                                            float(freq.max()) * 100],
        },
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(t[t.drought_pdsi | t.pdsi.le(-1.5)][["year", "pdsi", "pdsi_class", "ppt_anom_pct",
                                              "soil_anom_pct", "category"]].round(1).to_string(index=False))


if __name__ == "__main__":
    main()
