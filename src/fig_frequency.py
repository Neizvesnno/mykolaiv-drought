"""Рисунок 3: карта частоти посух по Миколаївській області.

Що робить: малює, у якій частці років (1958–2025) кожна клітинка сітки
TerraClimate була в посусі (PDSI <= -2), і підписує середню частоту по 4 районах.
Звідки дані: data/processed/drought_frequency.nc (змінні drought_frequency,
land_mask), data/processed/summary.json (spatial.rayons),
data/boundaries/mykolaiv_rayons.geojson (межі © OpenStreetMap contributors).
Як запустити з кореня репозиторію:  .venv/bin/python -m src.fig_frequency
Результат: figures/fig3_frequency.png (300 dpi).

Чесність шкали: значення лише 26–37 %, тому шкала дискретна 0–50 % кроком 5 %.
Якщо її розтягнути на 26–37 %, різниця в 6 в.п. виглядала б драматично.
"""

import json

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
from matplotlib.colors import BoundaryNorm
from shapely.geometry import box
from shapely.ops import unary_union

from src.config import BOUNDARIES_DIR, FIGURES_DIR, PROCESSED_DIR

OUT_PATH = FIGURES_DIR / "fig3_frequency.png"
FIG_SIZE = (10, 9)
DPI = 300
CMAP = "YlOrBr"  # послідовна палітра, безпечна для дальтоніків
LEVELS = np.arange(0, 55, 5)  # межі класів, %
# Підписи «1 рік із N» біля відповідних частот (частка = 100/N).
ONE_IN_N = {50: "1 рік із 2", 100 / 3: "1 рік із 3", 25: "1 рік із 4"}
SOURCE = "Дані: TerraClimate (1958–2025), межі © OpenStreetMap contributors"
FONT_TITLE, FONT_LABEL, FONT_TICK, FONT_SRC = 22, 16, 14, 12
FONT_RAYON = 16
# Зсув підписів (градуси) там, де representative_point двох районів надто близькі
LABEL_SHIFT = {"Первомайський район": (0.05, 0.14), "Вознесенський район": (0.05, -0.08)}
# Райони в підзаголовку: північ і південь (за summary.json / T06)
NORTH = ["Первомайський", "Вознесенський"]
SOUTH = ["Миколаївський", "Баштанський"]


def land_polygon(ds):
    """Полігон суходолу: об'єднання квадратів сітки, де land_mask == 1."""
    dlat = abs(float(ds.lat[1] - ds.lat[0]))
    dlon = abs(float(ds.lon[1] - ds.lon[0]))
    sq = [
        box(lo - dlon / 2, la - dlat / 2, lo + dlon / 2, la + dlat / 2)
        for la in ds.lat.values
        for lo in ds.lon.values
        if ds.land_mask.sel(lat=la, lon=lo) == 1
    ]
    # Невеликий buffer склеює квадрати без швів: без нього через похибки
    # float усередині контуру з'являються зайві лінії.
    return unary_union(sq).buffer(1e-6).buffer(-1e-6)


def make_frequency_map():
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "figure.facecolor": "white",
        "savefig.facecolor": "white",
    })
    ds = xr.open_dataset(PROCESSED_DIR / "drought_frequency.nc")
    with open(PROCESSED_DIR / "summary.json", encoding="utf-8") as f:
        rayon_stats = json.load(f)["spatial"]["rayons"]

    land = land_polygon(ds)
    rayons = gpd.read_file(BOUNDARIES_DIR / "mykolaiv_rayons.geojson")
    rayons["geometry"] = rayons.geometry.intersection(land)

    freq = ds.drought_frequency.where(ds.land_mask == 1) * 100  # у %
    norm = BoundaryNorm(LEVELS, plt.get_cmap(CMAP).N)

    fig = plt.figure(figsize=FIG_SIZE)
    ax = fig.add_axes([0.0, 0.17, 0.72, 0.75])
    cax = fig.add_axes([0.74, 0.22, 0.04, 0.62])
    mesh = ax.pcolormesh(ds.lon, ds.lat, freq, cmap=CMAP, norm=norm,
                         shading="nearest")
    rayons.boundary.plot(ax=ax, color="#333333", linewidth=1.2)
    gpd.GeoSeries([land]).boundary.plot(ax=ax, color="black", linewidth=1.6)

    # Підписи районів: representative_point лежить гарантовано всередині району.
    halo = [pe.withStroke(linewidth=4, foreground="white")]
    for _, row in rayons.iterrows():
        st = rayon_stats[row["name"]]
        pct = round(st["mean_frequency_pct"])
        n = round(100 / pct)
        short = row["name"].replace(" район", "")
        p = row.geometry.representative_point()
        dx, dy = LABEL_SHIFT.get(row["name"], (0, 0))
        ax.text(p.x + dx, p.y + dy, f"{short}\n{pct} % років\n≈1 рік із {n}",
                ha="center", va="center", fontsize=FONT_RAYON,
                fontweight="bold", color="black", path_effects=halo)

    ax.set_aspect(1 / np.cos(np.deg2rad(float(ds.lat.mean()))))
    ax.set_axis_off()  # без осей координат

    cb = fig.colorbar(mesh, cax=cax, ticks=LEVELS, spacing="proportional")
    cb.set_label("частка років із посухою, %", fontsize=FONT_LABEL)
    cb.ax.yaxis.set_label_position("left")
    cb.ax.yaxis.labelpad = 12
    cb.ax.tick_params(labelsize=FONT_TICK)
    # Додаткові підписи праворуч від шкали: «1 рік із N»
    for pct, text in ONE_IN_N.items():
        cb.ax.annotate(f"{text} ({pct:.0f} %)", xy=(1.0, pct / LEVELS[-1]),
                       xycoords="axes fraction", xytext=(48, 0),
                       textcoords="offset points", fontsize=FONT_TICK,
                       va="center", annotation_clip=False)
        cb.ax.axhline(pct, color="gray", linewidth=1)

    fig.suptitle("Посуха — проблема всієї області", fontsize=FONT_TITLE,
                 fontweight="bold", y=0.96)
    def pct_of(name):
        return round(rayon_stats[f"{name} район"]["mean_frequency_pct"])
    n1, n2 = (pct_of(x) for x in NORTH)
    s1, s2 = (pct_of(x) for x in SOUTH)
    fig.text(0.36, 0.13,
             f"На півночі ({NORTH[0]}, {NORTH[1]}) — трохи частіше: "
             f"{n1} % і {n2} % років\nпроти {s1} % і {s2} % на півдні.",
             ha="center", va="top", fontsize=FONT_LABEL)
    fig.text(0.0, 0.0, SOURCE, fontsize=FONT_SRC, color="gray",
             ha="left", va="bottom")
    fig.savefig(OUT_PATH, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return OUT_PATH


if __name__ == "__main__":
    print(make_frequency_map())
