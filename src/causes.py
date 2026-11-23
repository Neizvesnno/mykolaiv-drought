"""Причини посухи: опади, спека (tmax) і випаровування (PET), квітень–вересень.

Що робить:
  1. Рахує сезонні значення по області (середнє з вагою cos(lat), лише суходіл — та
     сама маска land_mask, що в season.py): ppt — сума за сезон (мм), tmax — середнє
     за сезон (°C), pet — сума за сезон (мм), водний баланс = ppt - pet (мм).
  2. Аномалії відносно норми 1991–2020: tmax у °C (різниця), ppt і pet у мм і у %,
     баланс у мм (у % не рахуємо: норма балансу близька до нуля/від'ємна).
  3. Порівнює (а) періоди 1958–1990 і 1991–2025; (б) підтверджені посушливі роки,
     інерційні та роки без посухи (категорії з drought_years.csv); (в) лінійний тренд
     1958–2025 на десятиліття з p-value.
  4. Окремо для методології: частота посухи по районах за індексом (PDSI <= -2 у клітинці)
     і «підтверджена по клітинці» (PDSI <= -2 і (опади <= -20 % або ґрунт <= -20 %)).
  5. Малює figures/fig4_causes.png.
Звідки дані: data/raw/terraclimate_{ppt,tmax,pet}.nc, data/processed/season_cells.nc,
  data/processed/drought_years.csv, data/boundaries/mykolaiv_rayons.geojson.
Метод значущості тренду: scipy у проєкті немає, тому p-value — пермутаційний тест на numpy.
  Рахуємо нахил МНК, потім PERM_N разів випадково переставляємо значення по роках
  (фіксований seed) і дивимось, у якій частці перестановок |нахил| не менший за справжній.
  p = (кількість таких + 1) / (PERM_N + 1), двосторонній. Допущення: роки незалежні
  (автокореляцію не враховуємо — це спрощення, тому p-value орієнтовне).
Вихід: data/processed/causes.csv, data/processed/causes.json, figures/fig4_causes.png.
Запуск з кореня репозиторію: .venv/bin/python -m src.causes
"""

import json

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr
from matplotlib.lines import Line2D

from src import config
from src.season import weighted_mean

OUT_CSV = config.PROCESSED_DIR / "causes.csv"
OUT_JSON = config.PROCESSED_DIR / "causes.json"
OUT_FIG = config.FIGURES_DIR / "fig4_causes.png"

PERM_N = 100_000          # кількість перестановок для p-value
PERM_SEED = 20261123      # фіксований seed: результат відтворюється
CONFIRM_THRESHOLD_PCT = -20.0  # поріг «підтвердження» для опадів і ґрунту, як у drought_years.py
EXPECTED_MONTHS = 816     # 68 років x 12 місяців
SOURCE = "Дані: TerraClimate (1958–2025)"
# Палітра Okabe-Ito
C_PPT, C_TMAX, C_DROUGHT, C_MEAN = "#0072B2", "#D55E00", "#CC79A7", "#000000"
DPI = 300
FIGSIZE = (13, 12)


# ---------------------------------------------------------------- дані ----
def check_monthly(da, var):
    """Перевірка сирого файлу: 816 місяців підряд, без дублів."""
    t = pd.DatetimeIndex(da["time"].values)
    assert len(t) == EXPECTED_MONTHS, f"{var}: {len(t)} місяців"
    assert t.is_unique, f"{var}: дублі в часі"
    expected = pd.date_range(f"{config.FIRST_YEAR}-01-01", periods=EXPECTED_MONTHS, freq="MS")
    assert (t.year == expected.year).all() and (t.month == expected.month).all(), \
        f"{var}: час не йде підряд помісячно"


def season_aggregate(var, how, land):
    """Сезонна сума/середнє по клітинках; NaN лише поза сушею."""
    da = xr.open_dataset(config.RAW_DIR / f"terraclimate_{var}.nc")[var]
    check_monthly(da, var)
    # NaN дозволені лише на воді (поза land); усередині суші їх бути не повинно
    n_bad = int(da.where(land).isnull().where(land).sum())
    assert n_bad == 0, f"{var}: {n_bad} NaN на суходолі"
    da = da.sel(time=da.time.dt.month.isin(config.SEASON_MONTHS))
    g = da.groupby("time.year")
    return (g.sum(skipna=False) if how == "sum" else g.mean(skipna=False))


def oblast_series(cells_land):
    """Сезонні ряди по області (вага cos(lat), лише суходіл)."""
    w = np.cos(np.deg2rad(cells_land["lat"]))
    out = {}
    for var, how, name in [("ppt", "sum", "ppt_mm"), ("tmax", "mean", "tmax_c"),
                           ("pet", "sum", "pet_mm")]:
        agg = season_aggregate(var, how, cells_land)
        out[name] = pd.Series(weighted_mean(agg, cells_land, w).values,
                              index=agg["year"].values)
    df = pd.DataFrame(out)
    df.index.name = "year"
    df["balance_mm"] = df["ppt_mm"] - df["pet_mm"]
    return df.reset_index()


def add_anomalies(df):
    y0, y1 = config.NORMAL_PERIOD
    norm = df[(df.year >= y0) & (df.year <= y1)].mean(numeric_only=True)
    for col, base in [("ppt", "ppt_mm"), ("pet", "pet_mm")]:
        df[f"{col}_anom_mm"] = df[base] - norm[base]
        df[f"{col}_anom_pct"] = df[f"{col}_anom_mm"] / norm[base] * 100.0
    df["tmax_anom_c"] = df["tmax_c"] - norm["tmax_c"]
    df["balance_anom_mm"] = df["balance_mm"] - norm["balance_mm"]
    return df, {k: float(v) for k, v in norm.items() if k != "year"}


# ------------------------------------------------------------ статистика ----
def trend_per_decade(years, values, rng):
    """Нахил МНК на десятиліття і пермутаційний p-value (двосторонній)."""
    x = years - years.mean()
    slope = float((x * (values - values.mean())).sum() / (x * x).sum())
    # PERM_N перестановок значень по роках: матриця (PERM_N, n_years)
    perm = rng.permuted(np.tile(values, (PERM_N, 1)), axis=1)
    slopes = (perm - perm.mean(axis=1, keepdims=True)) @ x / (x * x).sum()
    p = (int((np.abs(slopes) >= abs(slope) - 1e-15).sum()) + 1) / (PERM_N + 1)
    return slope * 10.0, p


VARS = {"ppt_mm": "ppt", "tmax_c": "tmax", "pet_mm": "pet", "balance_mm": "balance"}


def compute_trends(df):
    rng = np.random.default_rng(PERM_SEED)
    years = df["year"].to_numpy(float)
    res = {}
    for col, name in VARS.items():
        vals = df[col].to_numpy(float)
        slope, p = trend_per_decade(years, vals, rng)
        res[name] = {"slope_per_decade": slope, "p_value": p, "unit": "°C" if col == "tmax_c" else "мм",
                     "mean_1958_2025": float(vals.mean()),
                     "change_1958_2025_total": slope * (years[-1] - years[0]) / 10.0}
    return res


def compute_periods(df):
    out = {}
    for a, b in config.COMPARE_PERIODS:
        d = df[(df.year >= a) & (df.year <= b)]
        out[f"{a}-{b}"] = {"n_years": int(len(d)),
                           **{n: float(d[c].mean()) for c, n in
                              [("ppt_mm", "ppt_mm"), ("tmax_c", "tmax_c"), ("pet_mm", "pet_mm"),
                               ("balance_mm", "balance_mm")]}}
    k1, k2 = [f"{a}-{b}" for a, b in config.COMPARE_PERIODS]
    out["difference"] = {n: out[k2][n] - out[k1][n] for n in ["ppt_mm", "tmax_c", "pet_mm", "balance_mm"]}
    out["difference"]["ppt_pct_of_first"] = out["difference"]["ppt_mm"] / out[k1]["ppt_mm"] * 100.0
    out["difference"]["pet_pct_of_first"] = out["difference"]["pet_mm"] / out[k1]["pet_mm"] * 100.0
    return out


def compute_groups(df):
    cols = ["ppt_anom_mm", "ppt_anom_pct", "tmax_anom_c", "pet_anom_mm", "pet_anom_pct",
            "balance_anom_mm"]
    out = {}
    for cat in ["підтверджена", "інерційна", "немає"]:
        d = df[df.category == cat]
        out[cat] = {"n_years": int(len(d)), "years": [int(y) for y in d.year],
                    **{c: float(d[c].mean()) for c in cols}}
    return out


# ------------------------------------------------- частота по районах ----
def rayon_frequency():
    """Частота посухи по районах: за індексом і «підтверджена по клітинці»."""
    cells = xr.open_dataset(config.PROCESSED_DIR / "season_cells.nc")
    freq = xr.open_dataset(config.PROCESSED_DIR / "drought_frequency.nc")
    land = cells["land_mask"].astype(bool)
    idx = freq["rayon_index"]
    names = dict(kv.split("=", 1) for kv in freq.attrs["rayon_index_names"].split("; "))
    idx_drought = cells["pdsi"] <= config.DROUGHT_THRESHOLD_PDSI
    dry = (cells["ppt_anom_pct"] <= CONFIRM_THRESHOLD_PCT) | (cells["soil_anom_pct"] <= CONFIRM_THRESHOLD_PCT)
    confirmed = idx_drought & dry
    n_years = cells.sizes["year"]
    f_idx = idx_drought.where(land).sum("year") / n_years * 100.0
    f_conf = confirmed.where(land).sum("year") / n_years * 100.0
    out = {}
    for i, name in sorted(names.items(), key=lambda kv: int(kv[0])):
        m = (idx == int(i)) & land
        out[name] = {"n_cells": int(m.sum()),
                     "frequency_index_pct": float(f_idx.where(m).mean()),
                     "frequency_confirmed_pct": float(f_conf.where(m).mean())}
    vals = [v["frequency_index_pct"] for v in out.values()]
    valc = [v["frequency_confirmed_pct"] for v in out.values()]
    out["_spread_pp"] = {"index": max(vals) - min(vals), "confirmed": max(valc) - min(valc)}
    return out


# ------------------------------------------------------------- рисунок ----
def fmt(x, nd=1):
    return f"{x:.{nd}f}".replace(".", ",").replace("-", "−")


def draw_panel(ax, df, col, color, ylabel, title, unit, periods):
    conf = df[df.category == "підтверджена"]
    ax.bar(df["year"], df[col], width=0.8, color=color, alpha=0.45, zorder=2)
    for (a, b), key in zip(config.COMPARE_PERIODS, periods):
        mean = periods[key][col]
        ax.hlines(mean, a - 0.4, b + 0.4, color=C_MEAN, lw=3, zorder=4)
        # підпис у смузі над стовпчиками (відносні координати осі), щоб не налазив на дані
        ax.text((a + b) / 2, 0.93, f"середнє {a}–{b}: {fmt(mean)} {unit}", ha="center",
                va="center", fontsize=16, zorder=7, transform=ax.get_xaxis_transform(),
                bbox=dict(facecolor="white", edgecolor="black", pad=4))
    ax.scatter(conf["year"], conf[col], s=110, color=C_DROUGHT, edgecolor="black",
               linewidth=1.2, zorder=6)
    ax.axvline(config.COMPARE_PERIODS[0][1] + 0.5, color="black", lw=1, zorder=1)
    ax.set_title(title, fontsize=20, loc="left")
    ax.set_ylabel(ylabel)
    ax.set_xlim(config.FIRST_YEAR - 1, config.LAST_COMPLETE_YEAR + 1)


def make_figure(df, periods):
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "axes.titlesize": 22, "axes.labelsize": 16,
        "xtick.labelsize": 14, "ytick.labelsize": 14, "legend.fontsize": 14,
        "axes.spines.top": False, "axes.spines.right": False,
        "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
    })
    fig, (a1, a2) = plt.subplots(2, 1, figsize=FIGSIZE, sharex=True)
    draw_panel(a1, df, "ppt_mm", C_PPT, "мм за сезон", "Дощі за сезон (квітень–вересень)", "мм", periods)
    draw_panel(a2, df, "tmax_c", C_TMAX, "°C", "Денна спека: середній максимум за сезон", "°C", periods)
    a1.set_ylim(0, df["ppt_mm"].max() * 1.3)
    a2.set_ylim(df["tmax_c"].min() - 1.5, df["tmax_c"].max() + 2.0)
    a2.set_xlabel("Рік")
    handles = [Line2D([], [], marker="o", ls="", color=C_DROUGHT, markeredgecolor="black",
                      markersize=11, label="підтверджена посуха"),
               Line2D([], [], color=C_MEAN, lw=3, label="середнє за період")]
    a1.legend(handles=handles, loc="lower left", frameon=True, ncol=2)
    fig.suptitle("Дощів стало менше, а спеки більше", fontsize=22, x=0.02, ha="left", y=0.995)
    fig.text(0.02, 0.005, SOURCE, fontsize=12, color="#555555")
    fig.tight_layout(rect=(0, 0.02, 1, 0.97))
    fig.savefig(OUT_FIG, dpi=DPI, facecolor="white")
    plt.close(fig)


# ----------------------------------------------------------------- main ----
def main():
    cells = xr.open_dataset(config.PROCESSED_DIR / "season_cells.nc")
    land = cells["land_mask"].astype(bool)

    df = oblast_series(land)
    df, norm = add_anomalies(df)
    cat = pd.read_csv(config.PROCESSED_DIR / "drought_years.csv")[["year", "category"]]
    df = df.merge(cat, on="year", how="left")
    assert df["category"].notna().all() and len(df) == 68
    df.to_csv(OUT_CSV, index=False)   # повна точність, без округлення

    periods = compute_periods(df)
    result = {
        "method": {
            "season": config.SEASON_LABEL, "normal_period": list(config.NORMAL_PERIOD),
            "aggregation": "ppt, pet — сума за сезон; tmax — середнє за сезон; середнє по області з вагою cos(lat), лише суходіл",
            "trend_test": f"пермутаційний тест на numpy, {PERM_N} перестановок, seed {PERM_SEED}, двосторонній; нахил МНК на десятиліття",
        },
        "normal": norm,
        "periods": periods,
        "drought_vs_not": compute_groups(df),
        "trends": compute_trends(df),
        "rayons_frequency": rayon_frequency(),
    }
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    make_figure(df, periods)
    print(json.dumps({k: result[k] for k in ["periods", "trends"]}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
