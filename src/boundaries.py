"""Межі Миколаївської області та її 4 районів після реформи 17.07.2020.

Що робить: завантажує з OpenStreetMap (Overpass API) relation області
(ISO3166-2=UA-48) і relation-и районів (admin_level=6) усередині неї,
збирає з ліній полігони, рахує площі в рівновеликій проєкції EPSG:6933
(до і після спрощення), зберігає GeoJSON (EPSG:4326) і контрольну картинку.

Чому не geoBoundaries: ADM2 для UKR у geoBoundaries має 495 одиниць і
рік представлення 2006, тобто це старі райони, а не 4 нові. GADM теж старий.

Звідки дані: © OpenStreetMap contributors, ліцензія ODbL 1.0
(https://www.openstreetmap.org/copyright). Endpoint: overpass-api.de.

Як запустити з кореня репозиторію:
    .venv/bin/python src/boundaries.py
Сирі відповіді кешуються в data/raw/overpass_*.json; щоб оновити, видаліть їх.
"""

import json
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import requests
from shapely.geometry import LineString, MultiPolygon
from shapely.ops import linemerge, polygonize, unary_union
import geopandas as gpd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import BOUNDARIES_DIR, FIGURES_DIR, RAW_DIR  # noqa: E402

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "mykolaiv-drought-student-project/1.0"
RETRIES = 6            # публічний сервер буває перевантажений
RETRY_WAIT_S = 20      # перша пауза; далі подвоюється (exponential backoff)
EQUAL_AREA_CRS = "EPSG:6933"
SIMPLIFY_TOL_DEG = 0.0005   # допуск спрощення з завдання, у градусах
EXPECTED_RAYONS = {"Баштанський район", "Вознесенський район",
                   "Миколаївський район", "Первомайський район"}
LICENSE = "ODbL 1.0, © OpenStreetMap contributors"
SOURCE = "OpenStreetMap via Overpass API (overpass-api.de)"

# Один запит: область + її райони (admin_level=6), геометрія в out geom.
QUERY = """
[out:json][timeout:180];
rel["ISO3166-2"="UA-48"]["boundary"="administrative"]->.oblast;
.oblast map_to_area ->.a;
(.oblast; rel(area.a)["boundary"="administrative"]["admin_level"="6"];);
out geom;
"""


def fetch_overpass() -> dict:
    """Повертає JSON Overpass; кешує у data/raw, повторює запит при помилках."""
    cache = RAW_DIR / "overpass_mykolaiv_boundaries.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    wait = RETRY_WAIT_S
    for attempt in range(1, RETRIES + 1):
        try:
            r = requests.post(OVERPASS_URL, data={"data": QUERY},
                              headers={"User-Agent": USER_AGENT}, timeout=240)
            if r.status_code == 200 and r.text.lstrip().startswith("{"):
                cache.write_text(r.text, encoding="utf-8")
                return r.json()
            print(f"спроба {attempt}: HTTP {r.status_code}")
        except requests.RequestException as e:
            print(f"спроба {attempt}: {e}")
        time.sleep(wait)
        wait *= 2
    raise RuntimeError("Overpass недоступний після кількох спроб")


def relation_to_geometry(rel: dict):
    """Збирає полігон із зовнішніх ліній (outer) relation-у.

    Внутрішні кільця (inner) віднімаємо: це анклави інших одиниць, але для
    області/району вони потрібні лише якщо справді діри. Якщо inner відсутні,
    результат просто об'єднання outer.
    """
    def lines(role):
        out = []
        for m in rel["members"]:
            if m["type"] == "way" and m.get("role") == role and "geometry" in m:
                out.append(LineString([(p["lon"], p["lat"]) for p in m["geometry"]]))
        return out

    outer = unary_union(list(polygonize(linemerge(lines("outer")))))
    inner_lines = lines("inner")
    if inner_lines:
        outer = outer.difference(unary_union(list(polygonize(linemerge(inner_lines)))))
    return outer


def area_km2(geoms: gpd.GeoSeries) -> gpd.GeoSeries:
    """Площа в км² у рівновеликій проєкції (градуси для площі непридатні)."""
    return geoms.to_crs(EQUAL_AREA_CRS).area / 1e6


def main():
    data = fetch_overpass()
    rels = [e for e in data["elements"] if e["type"] == "relation"]
    oblast_rel = next(r for r in rels if r["tags"].get("ISO3166-2") == "UA-48")
    rayon_rels = [r for r in rels if r["tags"].get("admin_level") == "6"]
    print("знайдено районів admin_level=6:",
          sorted(r["tags"].get("name", "?") for r in rayon_rels))

    BOUNDARIES_DIR.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    common = {"source": SOURCE, "license": LICENSE}
    oblast = gpd.GeoDataFrame(
        [{"name": oblast_rel["tags"].get("name"), "osm_id": oblast_rel["id"], **common}],
        geometry=[relation_to_geometry(oblast_rel)], crs="EPSG:4326")
    rayons = gpd.GeoDataFrame(
        [{"name": r["tags"].get("name"), "osm_id": r["id"], **common} for r in rayon_rels],
        geometry=[relation_to_geometry(r) for r in rayon_rels], crs="EPSG:4326")
    rayons = rayons.sort_values("name").reset_index(drop=True)

    # Площі до спрощення (точні) і після.
    oblast["area_km2_full"] = area_km2(oblast.geometry)
    rayons["area_km2_full"] = area_km2(rayons.geometry)
    oblast["geometry"] = oblast.geometry.simplify(SIMPLIFY_TOL_DEG, preserve_topology=True)
    rayons["geometry"] = rayons.geometry.simplify(SIMPLIFY_TOL_DEG, preserve_topology=True)
    oblast["area_km2_simplified"] = area_km2(oblast.geometry)
    rayons["area_km2_simplified"] = area_km2(rayons.geometry)

    oblast.to_file(BOUNDARIES_DIR / "mykolaiv_oblast.geojson", driver="GeoJSON")
    rayons.to_file(BOUNDARIES_DIR / "mykolaiv_rayons.geojson", driver="GeoJSON")

    # Перевірки з критеріїв приймання.
    union_area = area_km2(gpd.GeoSeries([unary_union(rayons.geometry)], crs="EPSG:4326")).iloc[0]
    diff_pct = abs(union_area - oblast.area_km2_simplified.iloc[0]) / oblast.area_km2_simplified.iloc[0] * 100
    print(oblast[["name", "area_km2_full", "area_km2_simplified"]])
    print(rayons[["name", "area_km2_full", "area_km2_simplified"]])
    print(f"площа об'єднання районів: {union_area:.1f} км², різниця з областю {diff_pct:.2f}%")
    print("назви збігаються з очікуваними:", set(rayons.name) == EXPECTED_RAYONS)
    kinburn = unary_union(oblast.geometry).contains(gpd.points_from_xy([31.6], [46.55])[0])
    print("точка Кінбурнської коси (31.6E, 46.55N) в контурі:", kinburn)

    # Контрольна картинка.
    fig, ax = plt.subplots(figsize=(9, 7))
    rayons.plot(ax=ax, column="name", cmap="Pastel1", edgecolor="k", linewidth=0.6)
    oblast.boundary.plot(ax=ax, color="red", linewidth=1.5)
    for _, row in rayons.iterrows():
        c = row.geometry.representative_point()
        ax.annotate(f"{row['name']}\n{row['area_km2_full']:.0f} км²", (c.x, c.y),
                    ha="center", fontsize=8)
    ax.set_title("Миколаївська область: райони після реформи 2020 (OSM)")
    ax.set_xlabel("довгота, °"); ax.set_ylabel("широта, °")
    fig.savefig(FIGURES_DIR / "check_boundaries.png", dpi=150, bbox_inches="tight")


if __name__ == "__main__":
    main()
