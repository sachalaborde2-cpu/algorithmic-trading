"""Genere le graphique d'exemple Pullback en tendance (une journee MES reelle).

Choisit automatiquement, parmi les donnees MES deja telechargees, une journee ou
la strategie (config par defaut) a effectivement declenche un trade LONG net et
lisible, puis trace prix + EMA rapide/lente + zone de pullback + entree/sortie.
"""
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from pullback_backtest import INSTRUMENTS, Params, ema_series, load_bars, simulate_day

days, _ = load_bars("data/MES_5min_all.csv")
p = Params(ema_fast=9, ema_slow=21, min_trend_bars=3, atr_period=14,
          atr_stop_mult=1.0, atr_target_mult=2.0, max_trades_per_day=3)
inst = INSTRUMENTS["MES"]

# Cherche une journee avec exactement un trade LONG gagnant (target), pour un
# exemple pedagogique propre.
chosen = None
for day in days:
    trades = simulate_day(day, p, inst)
    longs = [t for t in trades if t["side"] == 1 and t["reason"] == "target"]
    if longs:
        chosen = (day, trades, longs[0])
        break

if chosen is None:
    raise SystemExit("Aucune journee LONG gagnante trouvee avec cette config.")

day, trades, trade = chosen
c = day.c
ema_f = ema_series(c, p.ema_fast)
ema_s = ema_series(c, p.ema_slow)
times = day.idx.to_pydatetime()

entry_time, exit_time = trade["entry_time"].to_pydatetime(), trade["exit_time"].to_pydatetime()
entry_i = list(day.idx).index(trade["entry_time"])
exit_i = list(day.idx).index(trade["exit_time"])

# Palette (dataviz skill, mode clair) -- reprend celle du VWAP reversion
SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
BLUE = "#2a78d6"       # prix
ORANGE = "#eb6834"     # EMA rapide
PURPLE = "#7a52c9"     # EMA lente
GOOD = "#0ca30c"        # entree / sortie gagnante
CRITICAL = "#d03b3b"    # zone de pullback

fig, ax = plt.subplots(figsize=(11, 5.5), facecolor=SURFACE)
ax.set_facecolor(SURFACE)

ax.plot(times, c, color=BLUE, linewidth=1.8, label="Prix (cloture)", zorder=4)
ax.plot(times, ema_f, color=ORANGE, linewidth=1.4, label=f"EMA{p.ema_fast} (rapide)", zorder=3)
ax.plot(times, ema_s, color=PURPLE, linewidth=1.4, label=f"EMA{p.ema_slow} (lente)", zorder=3)

ax.scatter([times[entry_i]], [c[entry_i - 1]], color=CRITICAL, s=70, zorder=5,
          edgecolor="white", linewidth=1)
ax.annotate("Signal : pullback puis reprise\n(cloture repasse au-dessus de l'EMA rapide)",
           xy=(times[entry_i - 1], c[entry_i - 1]),
           xytext=(times[entry_i - 1], min(c) - 6),
           ha="center", va="top", fontsize=9, color=INK_SECONDARY,
           arrowprops=dict(arrowstyle="-", color=INK_MUTED, lw=0.8))

ax.scatter([times[exit_i]], [c[exit_i]], color=GOOD, s=70, zorder=5,
          edgecolor="white", linewidth=1)
ax.annotate("Sortie (target atteint)", xy=(times[exit_i], c[exit_i]),
           xytext=(times[exit_i], max(c) + 4),
           ha="center", va="bottom", fontsize=9, color=INK_SECONDARY,
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

fig.suptitle(f"Pullback en tendance -- exemple reel : MES, {day.date.date()}",
             color=INK_PRIMARY, fontsize=13, fontweight="bold", x=0.02, y=0.985, ha="left")
fig.text(0.02, 0.945,
         "Tendance haussiere (EMA rapide > EMA lente) : le prix pullback sous l'EMA rapide, "
         "puis y revient -> entree",
         fontsize=9.5, color=INK_SECONDARY, ha="left")

ax.legend(loc="upper left", frameon=False, fontsize=9, labelcolor=INK_SECONDARY)

plt.tight_layout(rect=(0, 0, 1, 0.92))
plt.savefig("examples/mes_pullback_example.png", dpi=140, facecolor=SURFACE)
print(f"Graphique ecrit dans examples/mes_pullback_example.png (journee {day.date.date()})")
