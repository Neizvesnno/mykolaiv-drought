"""Ріки та лимани Миколаївщини з OpenStreetMap для орієнтації на картах.

Що робить: одним запитом до Overpass API бере лінії великих рік (waterway=river)
і полігони лиманів (natural=water) у bbox області із запасом, об'єднує сегменти
за назвою, обрізає по контуру області (з буфером), спрощує геометрію (~100 м)
і зберігає два GeoJSON (EPSG:4326): mykolaiv_rivers.geojson та mykolaiv_water.geojson.
Наприкінці перевіряє, що Південний Буг проходить біля Первомайська, Вознесенська
і Миколаєва, а Інгул біля Баштанки (відстань від точки до лінії).

Звідки дані: © OpenStreetMap contributors, ліцензія ODbL 1.0
(https://www.openstreetmap.org/copyright). Endpoint: overpass-api.de.
Контур області береться з data/boundaries/mykolaiv_oblast.geojson (T03).

Як запустити з кореня репозиторію:
    .venv/bin/python src/rivers.py
Сира відповідь кешується в data/raw/overpass_mykolaiv_rivers.json; щоб
оновити, видаліть файл. Повторний запуск використовує кеш і дає той самий результат.

Другий запит (T23, дозволений окремо) шукає Бузький і Дніпровсько-Бузький лимани,
які в першому запиті не знайшлися як natural=water з точною назвою: в OSM вони
можуть бути natural=bay або water=lagoon/estuary. Кеш: overpass_mykolaiv_estuaries.json.
Якщо для лиману в OSM є лише точка (node) без контуру, полігон не вигадуємо.
"""

import json
import sys
import time
from pathlib import Path

import geopandas as gpd
import requests
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import linemerge, polygonize, unary_union

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
BOUNDARIES_DIR = ROOT / "data" / "boundaries"
# Шляхи тримаємо тут, а не в config.py (його паралельно змінює інша задача).
RAW_CACHE = RAW_DIR / "overpass_mykolaiv_rivers.json"
ESTUARY_CACHE = RAW_DIR / "overpass_mykolaiv_estuaries.json"
OBLAST_FILE = BOUNDARIES_DIR / "mykolaiv_oblast.geojson"
RIVERS_FILE = BOUNDARIES_DIR / "mykolaiv_rivers.geojson"
WATER_FILE = BOUNDARIES_DIR / "mykolaiv_water.geojson"

OVERPASS_URLS = ["https://overpass-api.de/api/interpreter",
                 "https://overpass.kumi.systems/api/interpreter"]  # запасний
USER_AGENT = "mykolaiv-drought-student-project/1.0"
RETRIES = 4
RETRY_WAIT_S = 20          # перша пауза; далі подвоюється
LICENSE = "ODbL 1.0, © OpenStreetMap contributors"
SOURCE = "OpenStreetMap via Overpass API"

# bbox (південь, захід, північ, схід) із запасом навколо області.
BBOX = (46.2, 30.2, 48.2, 33.3)
CLIP_BUFFER_DEG = 0.05     # невеликий запас навколо контуру, щоб лінії не різались впритул
SIMPLIFY_TOL_DEG = 0.001   # ~100 м по широті
EQUAL_AREA_CRS = "EPSG:6933"

RIVER_NAMES = ["Південний Буг", "Інгул", "Інгулець", "Дніпро", "Мертвовод", "Висунь"]
LAKE_NAMES = ["Дніпровсько-Бузький лиман", "Бузький лиман", "Тилігульський лиман"]

# Другий запит: шукаємо за підрядком, бо назва в OSM може відрізнятися (name:uk, апостроф).
ESTUARY_NAME_PART = "Бузьк"

# Контрольні точки для перевірки (lon, lat): міста з підписів fig2.
CHECK_POINTS = {
    "Південний Буг": {"Первомайськ": (30.85, 48.05), "Вознесенськ": (31.28, 47.57),
                      "Миколаїв": (31.99, 46.97)},
    "Інгул": {"Баштанка": (32.44, 47.40)},
}
CHECK_MAX_KM = 3.0


def build_query() -> str:
    s, w, n, e = BBOX
    rivers = "|".join(f"^{x}$" for x in RIVER_NAMES)
    lakes = "|".join(f"^{x}$" for x in LAKE_NAMES)
    return f"""
[out:json][timeout:180][bbox:{s},{w},{n},{e}];
(
  way["waterway"="river"]["name"~"{rivers}"];
  way["natural"="water"]["name"~"{lakes}"];
  relation["natural"="water"]["name"~"{lakes}"];
);
out geom;
"""


def build_estuary_query() -> str:
    s, w, n, e = BBOX
    p = ESTUARY_NAME_PART
    return f"""
[out:json][timeout:180][bbox:{s},{w},{n},{e}];
(
  nwr["natural"~"^(water|bay)$"]["name"~"{p}"];
  nwr["natural"~"^(water|bay)$"]["name:uk"~"{p}"];
  nwr["water"~"^(lagoon|estuary|river)$"]["name"~"{p}"];
  nwr["water"~"^(lagoon|estuary|river)$"]["name:uk"~"{p}"];
);
out geom;
"""


def fetch_overpass(cache: Path = RAW_CACHE, query: str = None) -> dict:
    """Один запит; кеш у data/raw; повтори з подвоєнням паузи, потім запасний endpoint."""
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    query = query or build_query()
    for url in OVERPASS_URLS:
        wait = RETRY_WAIT_S
        for attempt in range(1, RETRIES + 1):
            try:
                r = requests.post(url, data={"data": query},
                                  headers={"User-Agent": USER_AGENT}, timeout=240)
                if r.status_code == 200 and r.text.lstrip().startswith("{"):
                    cache.write_text(r.text, encoding="utf-8")
                    return r.json()
                print(f"{url} спроба {attempt}: HTTP {r.status_code}")
            except requests.RequestException as ex:
                print(f"{url} спроба {attempt}: {ex}")
            time.sleep(wait)
            wait *= 2
    raise RuntimeError("Overpass недоступний")


def way_line(el: dict) -> LineString:
    return LineString([(p["lon"], p["lat"]) for p in el["geometry"]])


def rings_to_polygon(lines: list):
    """Збирає полігон із незамкнених ліній (так влаштовані relation-и OSM)."""
    return unary_union(list(polygonize(linemerge(lines))))


def build_rivers(elements: list, clip) -> gpd.GeoDataFrame:
    rows = []
    for name in RIVER_NAMES:
        lines = [way_line(e) for e in elements
                 if e["type"] == "way" and e.get("tags", {}).get("waterway") == "river"
                 and e["tags"].get("name") == name and "geometry" in e]
        if not lines:
            print("УВАГА: немає ліній для", name)
            continue
        geom = linemerge(unary_union(lines)).intersection(clip)
        if geom.is_empty:  # напр. Дніпро лежить у Херсонській обл., поза контуром
            print("УВАГА:", name, "не перетинає область, пропущено")
            continue
        rows.append({"name": name, "source": SOURCE, "license": LICENSE, "geometry": geom})
    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    gdf["geometry"] = gdf.geometry.simplify(SIMPLIFY_TOL_DEG, preserve_topology=True)
    gdf["length_km_in_area"] = gdf.to_crs(EQUAL_AREA_CRS).length / 1000
    return gdf


def element_polygon(e: dict):
    """Полігон з way (кільце) або relation (outer/inner); node без контуру дає None."""
    if e["type"] == "way" and "geometry" in e:
        ln = way_line(e)
        return Polygon(ln) if ln.is_ring else rings_to_polygon([ln])
    if e["type"] == "relation":
        outer = [LineString([(p["lon"], p["lat"]) for p in m["geometry"]])
                 for m in e["members"]
                 if m["type"] == "way" and m.get("role") == "outer" and "geometry" in m]
        inner = [LineString([(p["lon"], p["lat"]) for p in m["geometry"]])
                 for m in e["members"]
                 if m["type"] == "way" and m.get("role") == "inner" and "geometry" in m]
        g = rings_to_polygon(outer)
        if inner:
            g = g.difference(rings_to_polygon(inner))
        return g
    return None


def build_water(elements: list, clip, estuary_elements: list = ()) -> gpd.GeoDataFrame:
    rows = []
    for name in LAKE_NAMES:
        polys = []
        for e in elements:
            if e.get("tags", {}).get("name") != name or e["tags"].get("natural") != "water":
                continue
            g = element_polygon(e)
            if g is not None:
                polys.append(g)
        if not polys:
            print("УВАГА: немає полігона для", name)
            continue
        geom = unary_union(polys).intersection(clip)
        rows.append({"name": name, "source": SOURCE, "license": LICENSE, "geometry": geom})

    # Лимани з другого запиту: назва береться з тегу name (або name:uk), не вигадується.
    by_name = {}
    for e in estuary_elements:
        tags = e.get("tags", {})
        name = tags.get("name") or tags.get("name:uk")
        g = element_polygon(e)
        kind = f'{e["type"]} {e["id"]} natural={tags.get("natural")} water={tags.get("water")}'
        if g is None or g.is_empty:
            print("УВАГА: без полігона (лише точка або порожньо):", name, kind)
            continue
        print("Полігон лиману:", name, kind)
        by_name.setdefault(name, []).append(g)
    for name, polys in by_name.items():
        if any(r["name"] == name for r in rows):
            continue
        geom = unary_union(polys).intersection(clip)
        rows.append({"name": name, "source": SOURCE, "license": LICENSE, "geometry": geom})
    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    gdf["geometry"] = gdf.geometry.simplify(SIMPLIFY_TOL_DEG, preserve_topology=True)
    gdf["area_km2_in_area"] = gdf.to_crs(EQUAL_AREA_CRS).area / 1e6
    return gdf


def check_cities(rivers: gpd.GeoDataFrame):
    """Відстань від міста до лінії ріки в км (EPSG:6933 дає метри)."""
    for river, cities in CHECK_POINTS.items():
        line = rivers[rivers.name == river].to_crs(EQUAL_AREA_CRS).geometry.iloc[0]
        for city, (lon, lat) in cities.items():
            pt = gpd.GeoSeries([Point(lon, lat)], crs="EPSG:4326").to_crs(EQUAL_AREA_CRS).iloc[0]
            d = line.distance(pt) / 1000
            print(f"{river} — {city}: {d} км", "OK" if d < CHECK_MAX_KM else "ПОЗА ДОПУСКОМ")


def main():
    data = fetch_overpass()
    elements = data["elements"]
    oblast = gpd.read_file(OBLAST_FILE).geometry.iloc[0]
    clip = oblast.buffer(CLIP_BUFFER_DEG)

    rivers = build_rivers(elements, clip)
    estuaries = fetch_overpass(ESTUARY_CACHE, build_estuary_query())["elements"]
    print("Елементів у відповіді про лимани:",
          [(e["type"], e["id"], e.get("tags", {}).get("name")) for e in estuaries])
    water = build_water(elements, clip, estuaries)
    rivers.to_file(RIVERS_FILE, driver="GeoJSON")
    water.to_file(WATER_FILE, driver="GeoJSON")

    print(rivers[["name", "length_km_in_area"]])
    print(water[["name", "area_km2_in_area"]])
    for f in (RIVERS_FILE, WATER_FILE):
        print(f.name, f.stat().st_size, "байт")
    check_cities(rivers)


if __name__ == "__main__":
    main()
