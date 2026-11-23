"""Рисунок 1: сезонний індекс посухи по роках, 1958–2025.

Що робить: малює стовпчик на кожен рік (сезон квітень–вересень, середнє по області),
колір за категорією з drought_years.csv, лінію порогу -2, розділювач між періодами
1990/1991 і підписи трьох найсильніших посух.
Звідки: data/processed/drought_years.csv (pdsi, category), data/processed/summary.json
(periods, worst_years). Числа в підписах беруться з summary.json, не вписані вручну.
Запуск з кореня репозиторію: .venv/bin/python -m src.fig_timeline
Результат: figures/fig1_timeline.png
"""

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import Patch

from src.config import DROUGHT_THRESHOLD_PDSI, FIGURES_DIR, PROCESSED_DIR

OUT = FIGURES_DIR / "fig1_timeline.png"
SPLIT_AFTER = 1990  # межа періодів: 1958–1990 і 1991–2025
N_LABELLED = 3      # скільки найсильніших посух підписати роками
FIGSIZE = (13, 6)
# Палітра Okabe-Ito (безпечна для дальтоніків)
COLORS = {"підтверджена": "#D55E00", "інерційна": "#E69F00", "немає": "#8C8C8C"}
SOURCE = "Дані: TerraClimate (1958–2025), межі © OpenStreetMap contributors"


def _setup_style():
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "axes.titlesize": 22, "axes.labelsize": 16,
        "xtick.labelsize": 14, "ytick.labelsize": 14, "legend.fontsize": 14,
        "axes.spines.top": False, "axes.spines.right": False,
        "figure.facecolor": "white", "axes.facecolor": "white",
    })


def _plural(n, one, few, many):
    """Відмінок після числа: 1 посуха, 2–4 посухи, 5–20 посух (21 — знову «посуха»)."""
    if n % 100 in range(11, 15):
        return many
    if n % 10 == 1:
        return one
    if n % 10 in (2, 3, 4):
        return few
    return many


def _periods_text(summary):
    """Підписи періодів з summary.json (підтверджені посухи)."""
    out = []
    for p in summary["periods"].values():
        d, n = p["drought_years_confirmed"], p["n_years"]
        out.append(f"{p['years'].replace('-', '–')}: {d} {_plural(d, 'посуха', 'посухи', 'посух')} "
                   f"за {n} {_plural(n, 'рік', 'роки', 'років')}")
    return out


def make_timeline():
    _setup_style()
    df = pd.read_csv(PROCESSED_DIR / "drought_years.csv")
    summary = json.loads((PROCESSED_DIR / "summary.json").read_text(encoding="utf-8"))

    fig, ax = plt.subplots(figsize=FIGSIZE)
    for cat, color in COLORS.items():
        d = df[df["category"] == cat]
        ax.bar(d["year"], d["pdsi"], width=0.8, color=color, zorder=3,
               hatch="///" if cat == "інерційна" else None,
               edgecolor="white" if cat == "інерційна" else color, linewidth=0)

    ax.axhline(DROUGHT_THRESHOLD_PDSI, color="black", lw=1.5, ls="--", zorder=4)
    ax.axhline(0, color="black", lw=0.8, zorder=2)
    # підпис ставимо в порожню зону 1960–1974 під лінією, щоб не налазив на стовпчики
    ax.text(1960.4, DROUGHT_THRESHOLD_PDSI - 0.2, "нижче лінії —\nпосуха", ha="left",
            va="top", fontsize=15, zorder=5)

    ax.axvline(SPLIT_AFTER + 0.5, color="black", lw=1.2, zorder=1)
    ymin, ymax = -7.6, 4.6
    ax.set_ylim(ymin, ymax)
    ax.set_xlim(1957, 2027)
    t1, t2 = _periods_text(summary)
    ax.text(1957.5, ymax - 0.15, t1, ha="left", va="top", fontsize=15, fontweight="bold")
    ax.text(SPLIT_AFTER + 1.2, ymax - 0.15, t2, ha="left", va="top", fontsize=15,
            fontweight="bold")

    for w in summary["worst_years"][:N_LABELLED]:
        y, v = w["year"], w["pdsi"]
        ax.text(min(y, 2024.6), v - 0.2, str(y), ha="center", va="top", fontsize=14, fontweight="bold")

    ax.set_xticks(range(1960, 2026, 5))
    ax.set_ylabel("Наскільки сухий сезон\n(квітень–вересень)")
    ax.text(-0.075, 0.97, "вологіше ↑", transform=ax.transAxes, ha="right", va="top",
            fontsize=14, color="#444444")
    ax.text(-0.075, 0.03, "сухіше ↓", transform=ax.transAxes, ha="right", va="bottom",
            fontsize=14, color="#444444")
    ax.set_title("Посухи на Миколаївщині стали втричі частішими", loc="left", pad=14)
    ax.grid(axis="y", color="#E5E5E5", zorder=0)

    handles = [
        Patch(facecolor=COLORS["підтверджена"], label="посуха"),
        Patch(facecolor=COLORS["інерційна"], hatch="///", edgecolor="white",
              label="сухо лише за індексом: опадів і вологи в ґрунті достатньо"),
        Patch(facecolor=COLORS["немає"], label="без посухи"),
    ]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=3,
              frameon=False, fontsize=13, columnspacing=1.5, handletextpad=0.5)
    fig.text(0.01, -0.07, SOURCE, fontsize=12, color="#808080", ha="left")
    fig.text(0.01, -0.11, "PDSI — індекс посухи Палмера; поріг посухи: -2", fontsize=12,
             color="#808080", ha="left")

    FIGURES_DIR.mkdir(exist_ok=True)
    fig.savefig(OUT, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    for cat in ("підтверджена", "інерційна"):
        print(cat, int((df.category == cat).sum()), df.loc[df.category == cat, "year"].tolist())
    return OUT


if __name__ == "__main__":
    make_timeline()
