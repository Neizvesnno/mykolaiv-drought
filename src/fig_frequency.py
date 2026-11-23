"""Рисунок 3: частота посух по 4 районах Миколаївської області (спрощена карта).

Що робить: заливає кожен район одним кольором (YlOrBr, 4 відтінки: чим
частіша посуха, тим темніше) і підписує район: назва, «1 рік із N»
(N = 100 / частка) та частку років із посухою. Метрика та сама, що раніше:
частота за індексом, PDSI <= -2 (summary.json -> spatial.rayons.*.mean_frequency_pct).
Клітинкової сітки немає: просторову деталь показує fig2.
Звідки дані: data/processed/summary.json, data/processed/season_cells.nc
(лише land_mask для контуру суходолу), data/boundaries/mykolaiv_rayons.geojson,
ріки й лимани: data/boundaries/mykolaiv_rivers.geojson, mykolaiv_water.geojson
(шляхи — константи у src/rivers.py), усе © OpenStreetMap contributors.
Як запустити з кореня репозиторію:  .venv/bin/python -m src.fig_frequency
Результат: figures/fig3_frequency.png (300 dpi).
"""

import json
from math import cos, radians

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import xarray as xr
from matplotlib.colors import Normalize

from src.config import BOUNDARIES_DIR, FIGURES_DIR, PROCESSED_DIR
from src.fig_maps import (RAYON_LW, draw_rayon_borders, draw_water,
                          land_polygon, load_water, without_holes)

OUT_PATH = FIGURES_DIR / "fig3_frequency.png"
FIG_SIZE = (10, 9.5)
DPI = 300
CMAP = "YlOrBr"  # послідовна палітра, безпечна для дальтоніків
# Фіксована шкала 0–50 %: колір залежить лише від самої частки, без рангів,
# тож різниця 29,1 проти 35,2 % виглядає такою малою, якою вона є.
FREQ_MIN, FREQ_MAX = 0.0, 50.0
# Позначки легенди: частка, % (підпис «1 рік із N» рахується як 100/частка).
LEGEND_TICKS = [(0.0, "0 %"), (25.0, "25,0 % = 1 рік із 4"),
                (50.0, "50,0 % = 1 рік із 2")]
TITLE = "Посуха — проблема всієї області"
SOURCE = "Дані: TerraClimate (1958–2025), межі й ріки © OpenStreetMap contributors"
EXPLANATION = ("Тут рахуються всі роки, коли індекс посухи нижче −2, разом із тими, коли "
               "сухо лише за індексом,\nтому частіше, ніж «1 рік із 4» для підтверджених посух.")
FONT_TITLE, FONT_RAYON, FONT_TEXT, FONT_SRC = 22, 18, 16, 12
MEAN_LAT = 47.0  # для співвідношення сторін карти
MARGIN = 0.05    # запас навколо суходолу, градуси
# Зсув підписів (градуси) від representative_point, де підписи надто близькі
LABEL_SHIFT = {"Первомайський район": (0.05, 0.12), "Вознесенський район": (0.05, -0.08)}


def fmt(x, digits):
    """Число з комою як десятковим роздільником: 35.177 -> «35,2»."""
    return f"{x:.{digits}f}".replace(".", ",")


def make_frequency_map():
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "figure.facecolor": "white",
        "savefig.facecolor": "white",
    })
    ds = xr.open_dataset(PROCESSED_DIR / "season_cells.nc")
    with open(PROCESSED_DIR / "summary.json", encoding="utf-8") as f:
        rayon_stats = json.load(f)["spatial"]["rayons"]

    land = land_polygon(ds["lon"].values, ds["lat"].values, ds["land_mask"].values)
    rayons = gpd.read_file(BOUNDARIES_DIR / "mykolaiv_rayons.geojson")
    rivers, water = load_water(land, rayons)
    rayons["geometry"] = rayons.geometry.intersection(land)

    # Колір за точним значенням частки на фіксованій шкалі.
    pcts = {n: rayon_stats[n]["mean_frequency_pct"] for n in rayons["name"]}
    cmap = plt.get_cmap(CMAP)
    norm = Normalize(FREQ_MIN, FREQ_MAX)
    colors = {n: cmap(norm(v)) for n, v in pcts.items()}

    fig = plt.figure(figsize=FIG_SIZE)
    ax = fig.add_axes([0.0, 0.17, 1.0, 0.75])
    rayons.plot(ax=ax, color=[colors[n] for n in rayons["name"]], edgecolor="none")
    draw_rayon_borders(ax, rayons)
    gpd.GeoSeries([without_holes(land)]).boundary.plot(ax=ax, color="black", linewidth=RAYON_LW)
    draw_water(ax, rivers, water)

    # Підписи районів: representative_point лежить гарантовано всередині району.
    halo = [pe.withStroke(linewidth=4, foreground="white")]
    for _, row in rayons.iterrows():
        pct = pcts[row["name"]]  # точне значення; округлюємо лише при показі
        n = 100 / pct
        short = row["name"].replace(" район", "")
        p = row.geometry.representative_point()
        dx, dy = LABEL_SHIFT.get(row["name"], (0, 0))
        ax.text(p.x + dx, p.y + dy, short, ha="center", va="bottom",
                fontsize=FONT_RAYON, fontweight="bold", color="black",
                path_effects=halo)
        ax.text(p.x + dx, p.y + dy, f"1 рік із {fmt(n, 2)}\n({fmt(pct, 1)} % років)",
                ha="center", va="top", fontsize=FONT_TEXT, color="black",
                path_effects=halo)

    minx, miny, maxx, maxy = land.bounds
    ax.set_aspect(1 / cos(radians(MEAN_LAT)))
    ax.set_xlim(minx - MARGIN, maxx + MARGIN)
    ax.set_ylim(miny - MARGIN, maxy + MARGIN)
    ax.set_axis_off()  # без осей координат

    # Проста легенда: одна неперервна смужка 0–50 % з трьома позначками.
    cax = fig.add_axes([0.25, 0.075, 0.5, 0.025])
    cb = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), cax=cax,
                      orientation="horizontal",
                      ticks=[t for t, _ in LEGEND_TICKS])
    cb.ax.set_xticklabels([lbl for _, lbl in LEGEND_TICKS])
    cb.ax.tick_params(labelsize=FONT_SRC + 2)

    fig.suptitle(TITLE, fontsize=FONT_TITLE, fontweight="bold", y=0.96)
    fig.text(0.5, 0.16, EXPLANATION, ha="center", va="top", fontsize=FONT_TEXT)
    fig.text(0.0, 0.0, SOURCE, fontsize=FONT_SRC, color="gray",
             ha="left", va="bottom")
    fig.savefig(OUT_PATH, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return OUT_PATH


if __name__ == "__main__":
    print(make_frequency_map())
