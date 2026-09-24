"""Genere le graphique d'exemple ORB sur une journee reelle d'un des tickers
small/mid-cap (IWM, SOFI, PLUG, MARA, RIOT, AFRM, UPST, KRE).

Choisit automatiquement, parmi les donnees deja telechargees, une journee ou
la config par defaut a declenche un trade gagnant, puis trace prix + range
d'ouverture + entree/sortie.

Usage
-----
    python make_example_chart.py --symbol SOFI
"""
import argparse

import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from orb_backtest import INSTRUMENTS, Params, load_bars, simulate_day

SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
BLUE = "#2a78d6"
PURPLE = "#7a52c9"
GOOD = "#0ca30c"
CRITICAL = "#d03b3b"

ap = argparse.ArgumentParser()
ap.add_argument("--symbol", required=True, choices=list(INSTRUMENTS))
a = ap.parse_args()

days, _ = load_bars(f"data/{a.symbol}_5min_all.csv")
p = Params(or_minutes=30, stop_mode="opposite", target_r=1.5)
inst = INSTRUMENTS[a.symbol]

chosen = None
for day in days:
    t = simulate_day(day, p, inst)
    if t and t["reason"] == "target":
        chosen = (day, t)
        break
if chosen is None:
    raise SystemExit(f"Aucune journee gagnante trouvee pour {a.symbol} avec cette config.")

day, trade = chosen
o, h, l, c = day.o, day.h, day.l, day.c
times = day.idx.to_pydatetime()
n_or = p.or_minutes // 5
or_hi, or_lo = max(h[:n_or]), min(l[:n_or])
entry_i = list(day.idx).index(trade["entry_time"])
exit_i = list(day.idx).index(trade["exit_time"])

fig, ax = plt.subplots(figsize=(11, 5.5), facecolor=SURFACE)
ax.set_facecolor(SURFACE)

ax.plot(times, c, color=BLUE, linewidth=1.8, label="Prix (cloture)", zorder=4)
ax.axhspan(or_lo, or_hi, color=PURPLE, alpha=0.08, zorder=1)
ax.axhline(or_hi, color=PURPLE, linewidth=1.1, linestyle="--", label="Range d'ouverture", zorder=2)
ax.axhline(or_lo, color=PURPLE, linewidth=1.1, linestyle="--", zorder=2)

side_label = "LONG" if trade["side"] == 1 else "SHORT"
ax.scatter([times[entry_i]], [c[entry_i]], color=CRITICAL, s=70, zorder=5,
          edgecolor="white", linewidth=1)
ax.annotate(f"Entree ({side_label}, cassure du range)",
           xy=(times[entry_i], c[entry_i]),
           xytext=(times[entry_i], max(c) + (max(c) - min(c)) * 0.12),
           ha="center", va="bottom", fontsize=9, color=INK_SECONDARY,
           arrowprops=dict(arrowstyle="-", color=INK_MUTED, lw=0.8))

ax.scatter([times[exit_i]], [c[exit_i]], color=GOOD, s=70, zorder=5,
          edgecolor="white", linewidth=1)
ax.annotate("Sortie (target atteint)",
           xy=(times[exit_i], c[exit_i]),
           xytext=(times[exit_i], min(c) - (max(c) - min(c)) * 0.15),
           ha="center", va="top", fontsize=9, color=INK_SECONDARY,
           arrowprops=dict(arrowstyle="-", color=INK_MUTED, lw=0.8))

ax.tick_params(colors=INK_MUTED, labelsize=9)
for spine in ("top", "right"):
    ax.spines[spine].set_visible(False)
for spine in ("left", "bottom"):
    ax.spines[spine].set_color(GRID)
ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
ax.set_ylabel("Prix ($)", color=INK_SECONDARY, fontsize=10)
ax.legend(loc="upper left", frameon=False, fontsize=9, labelcolor=INK_SECONDARY)
ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=30))

fig.suptitle(f"ORB -- exemple reel : {a.symbol}, {day.date.date()}",
             color=INK_PRIMARY, fontsize=13, fontweight="bold", x=0.02, y=0.98, ha="left")

plt.tight_layout(rect=(0, 0, 1, 0.94))
out = f"examples/{a.symbol.lower()}_orb_example.png"
plt.savefig(out, dpi=140, facecolor=SURFACE)
print(f"Graphique ecrit dans {out} (journee {day.date.date()})")
