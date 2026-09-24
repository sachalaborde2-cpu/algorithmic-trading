"""Genere le graphique d'exemple Breakout confirme par volume (une journee MES reelle).

Choisit automatiquement, parmi les donnees MES deja telechargees, une journee ou
la strategie (config par defaut, avec filtre volume) a declenche un trade gagnant
sur target, puis trace prix + range d'ouverture + volume (barre de confirmation
mise en evidence) + entree/sortie.
"""
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from volume_breakout_backtest import INSTRUMENTS, Params, load_bars, simulate_day

days, _ = load_bars("data/MES_5min_all.csv")
p = Params(or_minutes=30, target_r=1.5, volume_lookback=12, volume_ratio_min=1.5)
inst = INSTRUMENTS["MES"]

chosen = None
for day in days:
    t = simulate_day(day, p, inst)
    if t and t["reason"] == "target":
        chosen = (day, t)
        break

if chosen is None:
    raise SystemExit("Aucune journee gagnante trouvee avec cette config.")

day, trade = chosen
o, h, l, c, v = day.o, day.h, day.l, day.c, day.v
times = day.idx.to_pydatetime()
n_or = p.or_minutes // 5
or_hi, or_lo = max(h[:n_or]), min(l[:n_or])
entry_i = list(day.idx).index(trade["entry_time"])
exit_i = list(day.idx).index(trade["exit_time"])
breakout_i = entry_i - 1  # barre de cassure confirmee (entree = ouverture de la barre suivante)

SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
BLUE = "#2a78d6"
ORANGE = "#eb6834"
PURPLE = "#7a52c9"
GOOD = "#0ca30c"
CRITICAL = "#d03b3b"

fig, (ax, ax2) = plt.subplots(2, 1, figsize=(11, 7), facecolor=SURFACE,
                              gridspec_kw={"height_ratios": [3, 1]}, sharex=True)
ax.set_facecolor(SURFACE)
ax2.set_facecolor(SURFACE)

ax.plot(times, c, color=BLUE, linewidth=1.8, label="Prix (cloture)", zorder=4)
ax.axhspan(or_lo, or_hi, color=PURPLE, alpha=0.08, zorder=1)
ax.axhline(or_hi, color=PURPLE, linewidth=1.1, linestyle="--", label="Range d'ouverture", zorder=2)
ax.axhline(or_lo, color=PURPLE, linewidth=1.1, linestyle="--", zorder=2)

side_label = "LONG" if trade["side"] == 1 else "SHORT"
ax.scatter([times[entry_i]], [c[entry_i]], color=CRITICAL, s=70, zorder=5,
          edgecolor="white", linewidth=1)
ax.annotate(f"Entree ({side_label}, cassure confirmee par volume)",
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

bar_colors = [ORANGE if i == breakout_i else INK_MUTED for i in range(len(v))]
ax2.bar(times, v, width=0.0032, color=bar_colors, zorder=3)
ax2.tick_params(colors=INK_MUTED, labelsize=9)
for spine in ("top", "right"):
    ax2.spines[spine].set_visible(False)
for spine in ("left", "bottom"):
    ax2.spines[spine].set_color(GRID)
ax2.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
ax2.set_ylabel("Volume", color=INK_SECONDARY, fontsize=10)
ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
ax2.xaxis.set_major_locator(mdates.MinuteLocator(interval=30))

fig.suptitle(f"Breakout confirme par volume -- exemple reel : MES, {day.date.date()}",
             color=INK_PRIMARY, fontsize=13, fontweight="bold", x=0.02, y=0.985, ha="left")
fig.text(0.02, 0.945,
         "Cassure du range d'ouverture (zone violette) accompagnee d'un pic de volume "
         f"(barre orange, ratio={trade['volume_ratio']:.1f}x) prise comme signal",
         fontsize=9.5, color=INK_SECONDARY, ha="left")

plt.tight_layout(rect=(0, 0, 1, 0.93))
plt.savefig("examples/mes_volume_breakout_example.png", dpi=140, facecolor=SURFACE)
print(f"Graphique ecrit dans examples/mes_volume_breakout_example.png (journee {day.date.date()})")
