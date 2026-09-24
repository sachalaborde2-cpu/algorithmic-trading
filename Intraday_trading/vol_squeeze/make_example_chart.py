"""Genere le graphique d'exemple Squeeze de volatilite (une journee MES reelle).

Choisit automatiquement, parmi les donnees MES deja telechargees, une journee ou
la strategie (config par defaut) a declenche un trade gagnant sur target, puis
trace prix + bandes de Bollinger + entree/sortie.
"""
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from vol_squeeze_backtest import INSTRUMENTS, Params, bollinger, load_bars, simulate_day

days, _ = load_bars("data/MES_5min_all.csv")
p = Params(bb_period=14, bb_k=2.0, squeeze_lookback=20, squeeze_pctl=20.0,
          atr_stop_mult=1.0, atr_target_mult=2.0)
inst = INSTRUMENTS["MES"]

chosen = None
for day in days:
    trades = simulate_day(day, p, inst)
    for t in trades:
        if t["reason"] == "target":
            chosen = (day, t)
            break
    if chosen:
        break

if chosen is None:
    raise SystemExit("Aucune journee squeeze gagnante trouvee avec cette config.")

day, trade = chosen
c = day.c
times = day.idx.to_pydatetime()
_, upper, lower, bandwidth = bollinger(c, p.bb_period, p.bb_k)
entry_i = list(day.idx).index(trade["entry_time"])
exit_i = list(day.idx).index(trade["exit_time"])

SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
BLUE = "#2a78d6"
PURPLE = "#7a52c9"
GOOD = "#0ca30c"
CRITICAL = "#d03b3b"

fig, (ax, ax2) = plt.subplots(2, 1, figsize=(11, 7), facecolor=SURFACE,
                              gridspec_kw={"height_ratios": [3, 1]}, sharex=True)
ax.set_facecolor(SURFACE)
ax2.set_facecolor(SURFACE)

ax.plot(times, c, color=BLUE, linewidth=1.8, label="Prix (cloture)", zorder=4)
ax.plot(times, upper, color=PURPLE, linewidth=1.1, linestyle="--", label="Bande haute", zorder=3)
ax.plot(times, lower, color=PURPLE, linewidth=1.1, linestyle="--", label="Bande basse", zorder=3)
ax.fill_between(times, lower, upper, color=PURPLE, alpha=0.06, zorder=1)

side_label = "LONG" if trade["side"] == 1 else "SHORT"
ax.scatter([times[entry_i]], [c[entry_i]], color=CRITICAL, s=70, zorder=5,
          edgecolor="white", linewidth=1)
ax.annotate(f"Entree ({side_label}, sortie du squeeze)",
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
ax.set_ylabel("Prix (points MES)", color=INK_SECONDARY, fontsize=10)
ax.legend(loc="upper left", frameon=False, fontsize=9, labelcolor=INK_SECONDARY)

ax2.plot(times, bandwidth, color=BLUE, linewidth=1.4)
ax2.axvspan(times[max(0, entry_i - p.squeeze_lookback)], times[entry_i], color=GOOD, alpha=0.08)
ax2.tick_params(colors=INK_MUTED, labelsize=9)
for spine in ("top", "right"):
    ax2.spines[spine].set_visible(False)
for spine in ("left", "bottom"):
    ax2.spines[spine].set_color(GRID)
ax2.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
ax2.set_ylabel("Bandwidth", color=INK_SECONDARY, fontsize=10)
ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
ax2.xaxis.set_major_locator(mdates.MinuteLocator(interval=30))

fig.suptitle(f"Squeeze de volatilite -- exemple reel : MES, {day.date.date()}",
             color=INK_PRIMARY, fontsize=13, fontweight="bold", x=0.02, y=0.985, ha="left")
fig.text(0.02, 0.945,
         "Compression des bandes de Bollinger (zone verte, bandwidth au plus bas) suivie "
         "d'une sortie de bande prise comme signal de breakout",
         fontsize=9.5, color=INK_SECONDARY, ha="left")

plt.tight_layout(rect=(0, 0, 1, 0.93))
plt.savefig("examples/mes_vol_squeeze_example.png", dpi=140, facecolor=SURFACE)
print(f"Graphique ecrit dans examples/mes_vol_squeeze_example.png (journee {day.date.date()})")
