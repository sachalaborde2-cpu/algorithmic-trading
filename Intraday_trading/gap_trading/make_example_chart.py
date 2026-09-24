"""Genere le graphique d'exemple Gap Trading (une journee MES reelle).

Choisit automatiquement, parmi les donnees MES deja telechargees, une journee
avec un gap significatif ou la strategie (config par defaut, mode "fill") a
declenche un trade gagnant, puis trace prix + gap + entree/sortie.
"""
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from gap_backtest import INSTRUMENTS, Params, compute_daily_atr, load_bars, simulate_day

days, _ = load_bars("data/MES_5min_all.csv")
daily_atr = compute_daily_atr(days, atr_period=14)
p = Params(atr_period=14, gap_threshold_atr=0.5, direction="fill", confirm_bars=2,
          atr_stop_mult=1.0, atr_target_mult=1.5)
inst = INSTRUMENTS["MES"]

chosen = None
for i in range(1, len(days)):
    if daily_atr[i] != daily_atr[i]:  # nan
        continue
    t = simulate_day(days[i], days[i - 1].c[-1], daily_atr[i], p, inst)
    if t and t["reason"] == "target":
        chosen = (days[i], days[i - 1].c[-1], t)
        break

if chosen is None:
    raise SystemExit("Aucune journee gap-fill gagnante trouvee avec cette config.")

day, prev_close, trade = chosen
c = day.c
times = day.idx.to_pydatetime()
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

fig, ax = plt.subplots(figsize=(11, 5.5), facecolor=SURFACE)
ax.set_facecolor(SURFACE)

ax.plot(times, c, color=BLUE, linewidth=1.8, label="Prix (cloture)", zorder=4)
ax.axhline(prev_close, color=PURPLE, linewidth=1.4, linestyle="--",
          label="Cloture de la veille (cible du gap-fill)", zorder=3)

ax.scatter([times[entry_i]], [c[entry_i]], color=CRITICAL, s=70, zorder=5,
          edgecolor="white", linewidth=1)
ax.annotate(f"Entree (gap={trade['gap_atr']:.2f} x ATR)\nconfirmation apres {p.confirm_bars} barres",
           xy=(times[entry_i], c[entry_i]),
           xytext=(times[entry_i], max(c) + 3),
           ha="center", va="bottom", fontsize=9, color=INK_SECONDARY,
           arrowprops=dict(arrowstyle="-", color=INK_MUTED, lw=0.8))

ax.scatter([times[exit_i]], [c[exit_i]], color=GOOD, s=70, zorder=5,
          edgecolor="white", linewidth=1)
ax.annotate("Sortie (target atteint : retour a la cloture veille)",
           xy=(times[exit_i], c[exit_i]),
           xytext=(times[exit_i], min(c) - 4),
           ha="center", va="top", fontsize=9, color=INK_SECONDARY,
           arrowprops=dict(arrowstyle="-", color=INK_MUTED, lw=0.8))

ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=30))
ax.tick_params(colors=INK_MUTED, labelsize=9)
for spine in ("top", "right"):
    ax.spines[spine].set_visible(False)
for spine in ("left", "bottom"):
    ax.spines[spine].set_color(GRID)
ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
ax.set_ylabel("Prix (points MES)", color=INK_SECONDARY, fontsize=10)

fig.suptitle(f"Gap trading (mode fill) -- exemple reel : MES, {day.date.date()}",
             color=INK_PRIMARY, fontsize=13, fontweight="bold", x=0.02, y=0.985, ha="left")
fig.text(0.02, 0.945,
         "Gap d'ouverture excessif vs cloture de la veille : on parie sur un retour "
         "vers cette cloture",
         fontsize=9.5, color=INK_SECONDARY, ha="left")

ax.legend(loc="upper left", frameon=False, fontsize=9, labelcolor=INK_SECONDARY)

plt.tight_layout(rect=(0, 0, 1, 0.92))
plt.savefig("examples/mes_gap_example.png", dpi=140, facecolor=SURFACE)
print(f"Graphique ecrit dans examples/mes_gap_example.png (journee {day.date.date()})")
