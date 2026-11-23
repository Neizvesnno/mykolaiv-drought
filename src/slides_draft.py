"""Чернетка презентації на 4 слайди (16:9) -> slides/presentation_draft.pdf.

Що робить: збирає PDF через matplotlib PdfPages. Рисунки беруться з figures/*.png
(їх не змінюємо; у пам'яті зменшуємо до ~2000 px, щоб PDF був легким).
Звідки дані: data/processed/summary.json і data/processed/yields.csv.
Усі числа на слайдах читаються з цих файлів і форматуються функціями fmt/fmt_int
(кома, типографський мінус), тож тексти не можуть розійтися з даними.
Тексти чорнові: їх замінює T13 у словниках SLIDES нижче (title, bullets, figure, note).
Запуск з кореня репо: .venv/bin/python -m src.slides_draft
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SUMMARY = ROOT / "data/processed/summary.json"
YIELDS = ROOT / "data/processed/yields.csv"
OUT = ROOT / "slides/presentation_draft.pdf"

PAGE = (13.333, 7.5)          # 16:9, дюйми
MAX_PX = 2000                 # довша сторона рисунка в PDF, щоб файл ≤ 10 МБ
TITLE_PT, BODY_PT, SOURCE_PT = 30, 20, 12   # основний текст ≥ 18 pt
SOURCE = "Дані: TerraClimate (1958–2025), межі © OpenStreetMap contributors"
SOURCE_YIELD = SOURCE + "; урожайність: Держстат"
COLOR_TEXT, COLOR_GREY = "#1a1a1a", "#6b6b6b"

plt.rcParams.update({"pdf.fonttype": 42, "font.family": "DejaVu Sans"})


def fmt(x, digits=1):
    """Число -> рядок з комою і типографським мінусом; округлення лише тут."""
    s = f"{x:.{digits}f}".replace(".", ",")
    return s.replace("-", "−")


def fmt_int(x):
    return str(int(x))


S = json.loads(SUMMARY.read_text(encoding="utf-8"))
Y = pd.read_csv(YIELDS).set_index("year")

# --- числа зі summary.json / yields.csv ---
n_years = fmt_int(S["n_years"])
n_conf = fmt_int(S["for_farmers"]["drought_years_confirmed"])
one_in = fmt(S["n_years"] / S["for_farmers"]["drought_years_confirmed"], 2)
p1, p2 = S["periods"]["1958-1990"], S["periods"]["1991-2025"]
worst = {w["year"]: w["pdsi"] for w in S["worst_years"]}
ray = S["spatial"]["rayons"]
ray_sorted = sorted(ray.items(), key=lambda kv: -kv[1]["mean_frequency_pct"])


def rayon(name):
    key = next(k for k in ray if k.startswith(name))
    return fmt(ray[key]["mean_frequency_pct"], 1)


y2020, y2021 = Y.loc[2020, "yield_c_ha"], Y.loc[2021, "yield_c_ha"]

# --- чорнові тексти: по одному словнику на слайд ---
SLIDES = [
    {
        "title": "Посуха на Миколаївщині стає частішою",
        "bullets": [
            f"{n_conf} підтверджених посух із {n_years} сезонів: 1 рік із {one_in}",
            f"1958–1990: {fmt_int(p1['drought_years_confirmed'])} із {fmt_int(p1['n_years'])} років",
            f"1991–2025: {fmt_int(p2['drought_years_confirmed'])} із {fmt_int(p2['n_years'])} років",
        ],
        "figure": "figures/fig1_timeline.png",
        "note": SOURCE,
    },
    {
        "title": "Найгірші роки накривають усю область",
        "bullets": [
            f"2025: індекс {fmt(worst[2025], 2)}",
            f"2007: {fmt(worst[2007], 2)}",
            f"2020: {fmt(worst[2020], 2)}",
            f"2024: {fmt(worst[2024], 2)}",
            "Темніше — сухіше",
        ],
        "figure": "figures/fig2_maps.png",
        "note": SOURCE,
    },
    {
        "title": "Посуха всієї області, на півночі трохи частіше",
        "bullets": [
            "Частка років із посухою, %:",
            f"Первомайський: {rayon('Первомайський')} %",
            f"Вознесенський: {rayon('Вознесенський')} %",
            f"Миколаївський: {rayon('Миколаївський')} %",
            f"Баштанський: {rayon('Баштанський')} %",
        ],
        "figure": "figures/fig3_frequency.png",
        "note": SOURCE,
    },
    {
        "title": "Ризики і що з цим робити",
        "columns": [
            ("Ризики", [
                f"Підтверджена посуха: 1 рік із {one_in}",
                f"2020 — {fmt(y2020, 1)} ц/га пшениці",
                f"2021 — {fmt(y2021, 1)} ц/га (Держстат)",
            ]),
            ("Що з цим робити", [
                "Враховувати частоту посух у планах",
                "Стежити за вологою ґрунту в сезоні",
                "[чернетка: текст напише T13]",
            ]),
        ],
        "figure": None,
        "note": SOURCE_YIELD,
    },
]


def load_small(path):
    """Зменшує PNG у пам'яті (файл у figures/ не змінюється)."""
    im = Image.open(ROOT / path).convert("RGB")
    k = MAX_PX / max(im.size)
    if k < 1:
        im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    return im


def new_page():
    fig = plt.figure(figsize=PAGE)
    fig.patch.set_facecolor("white")
    return fig


def put_text(fig, x, y, s, size, color=COLOR_TEXT, weight="normal", **kw):
    fig.text(x, y, s, fontsize=size, color=color, fontweight=weight, **kw)


def put_bullets(fig, x, y_top, items, width_chars=None, step=0.075):
    for i, t in enumerate(items):
        put_text(fig, x, y_top - i * step, "•  " + t, BODY_PT, va="top")


def put_image(fig, rect, path):
    """Рисунок у прямокутнику rect (в частках сторінки), зберігає пропорції."""
    ax = fig.add_axes(rect)
    ax.imshow(load_small(path), interpolation="lanczos")
    ax.axis("off")


def build_slide(pdf, i, d):
    fig = new_page()
    put_text(fig, 0.04, 0.94, d["title"], TITLE_PT, weight="bold", va="top")
    if "columns" in d:
        for c, (head, items) in enumerate(d["columns"]):
            x = 0.04 + c * 0.50
            put_text(fig, x, 0.76, head, BODY_PT + 4, weight="bold", va="top")
            put_bullets(fig, x, 0.66, items, step=0.11)
    elif i == 0:  # широкий рисунок зверху, текст під ним
        put_image(fig, (0.04, 0.30, 0.92, 0.58), d["figure"])
        put_bullets(fig, 0.04, 0.26, d["bullets"], step=0.065)
    else:         # текст ліворуч, рисунок праворуч
        put_bullets(fig, 0.04, 0.80, d["bullets"], step=0.10)
        w, h = Image.open(ROOT / d["figure"]).size
        box_w, box_h = 0.54 * PAGE[0], 0.74 * PAGE[1]
        k = min(box_w / w, box_h / h)
        fw, fh = w * k / PAGE[0], h * k / PAGE[1]
        put_image(fig, (0.43 + (0.54 - fw) / 2, 0.07 + (0.74 - fh) / 2, fw, fh), d["figure"])
    put_text(fig, 0.04, 0.025, d["note"], SOURCE_PT, color=COLOR_GREY, va="bottom")
    pdf.savefig(fig)
    return fig


def main():
    OUT.parent.mkdir(exist_ok=True)
    with PdfPages(OUT) as pdf:
        for i, d in enumerate(SLIDES):
            fig = build_slide(pdf, i, d)
            plt.close(fig)
    print(f"Збережено {OUT} ({OUT.stat().st_size / 1e6:.2f} МБ)")


if __name__ == "__main__":
    main()
