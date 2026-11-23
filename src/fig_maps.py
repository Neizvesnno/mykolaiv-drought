"""Рисунок 2: карти чотирьох найсухіших сезонів (квітень–вересень).

Що робить: малює 2×2 карти індексу посухи Палмера (PDSI) по клітинках
TerraClimate для 4 років із найнижчим середнім PDSI по області
(summary.json -> worst_years), з межами районів і райцентрами.
Звідки дані: data/processed/season_cells.nc (pdsi, land_mask),
data/processed/summary.json, data/boundaries/mykolaiv_rayons.geojson.
Ріки й лимани: data/boundaries/mykolaiv_rivers.geojson, mykolaiv_water.geojson
(шляхи — константи RIVERS_FILE, WATER_FILE у src/rivers.py).
Вихід: figures/fig2_maps.png (300 dpi).
Запуск з кореня репозиторію: .venv/bin/python -m src.fig_maps
"""

import json
from math import cos, radians

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import numpy as np
import xarray as xr
from matplotlib.colors import TwoSlopeNorm
from shapely.geometry import Point, box
from shapely.ops import nearest_points, unary_union

from src.config import BOUNDARIES_DIR, FIGURES_DIR, PROCESSED_DIR
from src.rivers import RIVERS_FILE, WATER_FILE

N_PANELS = 4
VMIN, VCENTER, VMAX = -7.0, 0.0, 4.0
CMAP = "BrBG"                 # коричневий = сухо, бірюзовий = волого
EPS = 1e-6
CELL = 1 / 30                 # крок сітки TerraClimate, градуси
MEAN_LAT = 47.0               # для співвідношення сторін карти
COLORBAR_TICKS = [-7, -4, -2, 0, 2, 4]
CBAR_LABEL = ("індекс посухи Палмера (PDSI):\n"
              "нижче −2 — посуха, нижче −4 — екстремальна")
TITLE = "Найсухіші сезони: посуха накрила всю область"
SOURCE = "Дані: TerraClimate (1958–2025), межі й ріки © OpenStreetMap contributors"
RAYON_COLOR = "black"   # межі районів чорні (рішення 23.11)
RAYON_HALO = "white"    # тонкий білий ореол, щоб чорна лінія була видна на темно-коричневому
RAYON_LW = 1.3
HALO_LW = 3.0
WATER_COLOR = "#0072B2"  # ріки й лимани (палітра Окабе-Іто, безпечна для дальтоніків)
RIVER_LW = 1.4
RIVER_LABEL_FONT = 12
# Підписуємо лише головні ріки: орієнтовна точка (довгота, широта), де нема
# інших підписів; підпис ставиться в найближчій до неї точці лінії ріки.
# Далі зсув у точках і вирівнювання. Мертвовод і Висунь без підписів.
RIVER_LABELS = {
    "Південний Буг": ((31.90, 46.74), (-10, 0), "right"),
    "Інгул": ((32.36, 47.85), (-8, 0), "right"),
    "Інгулець": ((32.82, 47.70), (8, 0), "left"),
}
MARGIN = 0.05           # запас навколо суходолу, градуси
# Райцентри: координати перевіряються на належність своєму району.
CITIES = [
    ("Миколаїв", 31.99, 46.97, "Миколаївський район"),
    ("Первомайськ", 30.86, 48.05, "Первомайський район"),
    ("Вознесенськ", 31.33, 47.57, "Вознесенський район"),
    ("Баштанка", 32.44, 47.41, "Баштанський район"),
]
# Зсув підпису (точки), щоб підписи не виходили за карту й не лягали на сусідів.
LABEL_OFFSET = {"Миколаїв": (6, 4), "Первомайськ": (6, 4),
                "Вознесенськ": (6, 4), "Баштанка": (0, -20)}
LABEL_ALIGN = {"Миколаїв": "left", "Первомайськ": "left",
               "Вознесенськ": "left", "Баштанка": "center"}

plt.rcParams.update({
    "font.family": "DejaVu Sans", "axes.titlesize": 16,
    "axes.labelsize": 16, "xtick.labelsize": 14, "ytick.labelsize": 14,
    "axes.spines.top": False, "axes.spines.right": False,
    "figure.facecolor": "white", "savefig.facecolor": "white",
})


def fmt(x):
    """Число з комою і справжнім мінусом: -6.3412 -> «−6,34»."""
    return f"{x:.2f}".replace("-", "−").replace(".", ",")


def land_polygon(lon, lat, mask):
    """Суходіл як об'єднання квадратів клітинок land_mask == 1."""
    # Крихітне перекриття (EPS), щоб між квадратами не лишалось швів і
    # внутрішніх ліній у контурі після об'єднання.
    h = CELL / 2 + EPS
    squares = [box(x - h, y - h, x + h, y + h)
               for j, y in enumerate(lat) for i, x in enumerate(lon)
               if mask[j, i] == 1]
    return unary_union(squares)


def check_cities(rayons):
    """Point-in-polygon: чи лежить кожне місто у своєму районі."""
    res = {}
    for name, lon, lat, rayon in CITIES:
        p = Point(lon, lat)
        row = rayons[rayons["name"] == rayon].geometry.iloc[0]
        inside = [r["name"] for _, r in rayons.iterrows()
                  if r.geometry.contains(p)]
        res[name] = {"expected": rayon, "found": inside,
                     "ok": bool(row.contains(p))}
    return res


def load_water(land, rayons):
    """Ріки (обрізані по суходолу) і лимани (обрізані по контуру області).

    Лимани обрізаємо по об'єднанню районів, а не по суходолу: клітинки води
    у land_mask замасковані, тож по суходолу лиман зник би повністю.
    """
    oblast = rayons.geometry.union_all()
    rivers = gpd.read_file(RIVERS_FILE)
    rivers["geometry"] = rivers.geometry.intersection(land)
    water = gpd.read_file(WATER_FILE)
    water["geometry"] = water.geometry.intersection(oblast)
    return rivers, water


def draw_water(ax, rivers, water, labels=True):
    """Лимани заливкою, ріки лініями одного синього; підпис головних рік."""
    water.plot(ax=ax, color=WATER_COLOR, edgecolor=WATER_COLOR, linewidth=0.5)
    rivers.plot(ax=ax, color=WATER_COLOR, linewidth=RIVER_LW)
    if not labels:
        return
    halo = [pe.withStroke(linewidth=3, foreground="white")]
    for name, (target, offset, ha) in RIVER_LABELS.items():
        geom = rivers.loc[rivers["name"] == name, "geometry"].iloc[0]
        # nearest_points: точка лінії, найближча до заданої цільової точки.
        pt = nearest_points(geom, Point(target))[0]
        ax.annotate(name, (pt.x, pt.y), xytext=offset, textcoords="offset points",
                    fontsize=RIVER_LABEL_FONT, color=WATER_COLOR, style="italic",
                    fontweight="bold", ha=ha, va="center", path_effects=halo)


def draw_rayon_borders(ax, geoms):
    """Чорні межі районів із тонким білим ореолом під лінією."""
    geoms.boundary.plot(ax=ax, color=RAYON_COLOR, linewidth=RAYON_LW,
                        path_effects=[pe.withStroke(linewidth=HALO_LW,
                                                    foreground=RAYON_HALO)])


def make_maps():
    ds = xr.open_dataset(PROCESSED_DIR / "season_cells.nc")
    summary = json.loads((PROCESSED_DIR / "summary.json").read_text())
    worst = summary["worst_years"][:N_PANELS]
    rayons = gpd.read_file(BOUNDARIES_DIR / "mykolaiv_rayons.geojson")

    lon, lat = ds["lon"].values, ds["lat"].values
    mask = ds["land_mask"].values
    land = land_polygon(lon, lat, mask)
    # Межі обрізаємо по суходолу, щоб лінії не йшли по лиману.
    clipped = rayons.copy()
    clipped["geometry"] = rayons.geometry.intersection(land)
    rivers, water = load_water(land, rayons)
    checks = check_cities(rayons)
    print("Райцентри:", checks)

    norm = TwoSlopeNorm(vmin=VMIN, vcenter=VCENTER, vmax=VMAX)
    # pcolormesh з ребрами клітинок, щоб клітинка лежала симетрично навколо центру.
    x_edges = np.append(lon - CELL / 2, lon[-1] + CELL / 2)
    y_edges = np.append(lat + CELL / 2, lat[-1] - CELL / 2)

    fig, axes = plt.subplots(2, 2, figsize=(11, 10))
    mesh = None
    minx, miny, maxx, maxy = land.bounds
    for ax, w in zip(axes.ravel(), worst):
        z = ds["pdsi"].sel(year=w["year"]).values.astype(float)
        z = np.ma.masked_where(mask != 1, z)
        mesh = ax.pcolormesh(x_edges, y_edges, z, cmap=CMAP, norm=norm,
                             shading="flat")
        draw_rayon_borders(ax, clipped)
        draw_water(ax, rivers, water)
        gpd.GeoSeries([land]).boundary.plot(ax=ax, color="black", linewidth=1.2)
        for name, x, y, _ in CITIES:
            ax.plot(x, y, "o", color="black", markersize=5,
                    markeredgecolor="white", markeredgewidth=1)
            ax.annotate(name, (x, y), xytext=LABEL_OFFSET[name],
                        textcoords="offset points", fontsize=14,
                        ha=LABEL_ALIGN[name],
                        path_effects=[pe.withStroke(linewidth=3,
                                                    foreground="white")])
        ax.set_aspect(1 / cos(radians(MEAN_LAT)))
        ax.set_xlim(minx - MARGIN, maxx + MARGIN)
        ax.set_ylim(miny - MARGIN, maxy + MARGIN)
        ax.axis("off")
        ax.set_title(f"{w['year']} — середнє по області {fmt(w['pdsi'])}",
                     fontsize=16)

    fig.suptitle(TITLE, fontsize=22, fontweight="bold")
    fig.subplots_adjust(hspace=0.1, wspace=-0.12, left=0.02, right=0.98, bottom=0.2, top=0.9)
    cax = fig.add_axes([0.2, 0.13, 0.6, 0.022])
    cb = fig.colorbar(mesh, cax=cax, orientation="horizontal",
                      ticks=COLORBAR_TICKS)
    cb.set_label(CBAR_LABEL, fontsize=16)
    cb.ax.tick_params(labelsize=14)
    fig.text(0.01, 0.0, SOURCE, fontsize=12, color="gray", ha="left")

    FIGURES_DIR.mkdir(exist_ok=True)
    out = FIGURES_DIR / "fig2_maps.png"
    fig.savefig(out, dpi=300, bbox_inches="tight")
    print("Збережено", out)
    return out


if __name__ == "__main__":
    make_maps()
