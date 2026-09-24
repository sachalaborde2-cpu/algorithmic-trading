"""Graphique pedagogique : rendement moyen par tranche horaire de 30 min sur
donnees reelles MES, avec barres d'erreur (+/- 1 erreur-standard) pour montrer
que la plupart des tranches ne se distinguent pas du bruit."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from seasonality_backtest import load_bars, slot_label, slot_return_matrix, slot_stats, N_SLOTS, SLOT_MINUTES

SURFACE = "#fcfcfb"
BLUE = "#2a78d6"
ORANGE = "#eb6834"
GOOD = "#0ca30c"
CRITICAL = "#d03b3b"
INK = "#1a1a1a"
MUTED = "#8a8a8a"

days, info = load_bars("data/MES_5min_all.csv", bar_minutes=5)
print(f"{info['days']} jours charges ({info['first']} -> {info['last']})")

dates = pd.DatetimeIndex([d.date for d in days])
k = int(len(dates) * 0.7)
is_dates = dates[:k]

matrix = slot_return_matrix(days, SLOT_MINUTES, bar_minutes=5)
st = slot_stats(matrix, is_dates)

labels = [slot_label(i) for i in range(N_SLOTS)]
mean_bp = st["mean_bp"].to_numpy()
se_bp = (st["std_bp"] / np.sqrt(st["n"])).to_numpy()
tstat = st["t_stat"].to_numpy()

fig, ax = plt.subplots(figsize=(11, 5.5))
fig.patch.set_facecolor(SURFACE)
ax.set_facecolor(SURFACE)

colors = [GOOD if t > 2 else CRITICAL if t < -2 else MUTED for t in tstat]
x = np.arange(N_SLOTS)
ax.bar(x, mean_bp, yerr=se_bp, color=colors, edgecolor="none", width=0.6,
      capsize=3, ecolor=INK, error_kw={"alpha": 0.5, "linewidth": 1})
ax.axhline(0, color=INK, linewidth=1)

ax.set_xticks(x)
ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8, color=INK)
ax.set_ylabel("Rendement moyen (points de base)", color=INK)
ax.set_title(f"MES — rendement moyen par tranche de {SLOT_MINUTES} min (in-sample, "
            f"{is_dates[0].date()} -> {is_dates[-1].date()}, barres = ±1 erreur-standard)",
            color=INK, fontsize=11)
for spine in ["top", "right"]:
    ax.spines[spine].set_visible(False)
for spine in ["left", "bottom"]:
    ax.spines[spine].set_color(MUTED)
ax.tick_params(colors=MUTED)

from matplotlib.patches import Patch
legend_elems = [
    Patch(facecolor=GOOD, label="t-stat > +2"),
    Patch(facecolor=CRITICAL, label="t-stat < -2"),
    Patch(facecolor=MUTED, label="|t-stat| <= 2 (bruit)"),
]
ax.legend(handles=legend_elems, loc="upper right", frameon=False, fontsize=8)

fig.tight_layout()
fig.savefig("examples/seasonality_slots_mes.png", dpi=150, facecolor=SURFACE)
print("Graphique ecrit dans examples/seasonality_slots_mes.png")

print("\nTableau complet (in-sample) :")
table = pd.DataFrame({"tranche": labels, "mean_bp": mean_bp.round(2), "t_stat": tstat.round(2)})
print(table.to_string(index=False))
