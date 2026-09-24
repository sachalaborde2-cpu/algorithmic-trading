"""Genere le graphique d'exemple VWAP reversion (une journee MES reelle)."""
import json
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

with open("examples/mes_2025-11-21.json") as f:
    bars = json.load(f)

times = [datetime.strptime(b["time"], "%H:%M") for b in bars]
close = [b["close"] for b in bars]
vwap = [b["vwap"] for b in bars]
upper = [b["upper2"] for b in bars]
lower = [b["lower2"] for b in bars]

# Palette (dataviz skill, mode clair)
SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
BLUE = "#2a78d6"      # prix
ORANGE = "#eb6834"    # VWAP
GOOD = "#0ca30c"       # entree / retour reussi
CRITICAL = "#d03b3b"   # zone d'ecart extreme

fig, ax = plt.subplots(figsize=(11, 5.5), facecolor=SURFACE)
ax.set_facecolor(SURFACE)

ax.fill_between(times, lower, upper, color=BLUE, alpha=0.08, linewidth=0, label="Bande +/-2 sigma")
ax.plot(times, vwap, color=ORANGE, linewidth=1.6, label="VWAP", zorder=3)
ax.plot(times, close, color=BLUE, linewidth=1.8, label="Prix (typical price)", zorder=4)

# Repere l'entree long (deviation ~ -2.4 std vers 10:35) et le retour vers 13:10
entry_i = 13   # 10:35, dev ~ -2.4
exit_i = 44    # 13:10, dev ~ 0.7 (retour proche du VWAP)
ax.scatter([times[entry_i]], [close[entry_i]], color=CRITICAL, s=70, zorder=5, edgecolor="white", linewidth=1)
ax.annotate("Entree LONG\n(prix <= VWAP - 2 sigma)", xy=(times[entry_i], close[entry_i]),
            xytext=(times[entry_i], close[entry_i] - 34),
            ha="center", va="top", fontsize=9, color=INK_SECONDARY,
            arrowprops=dict(arrowstyle="-", color=INK_MUTED, lw=0.8))

ax.scatter([times[exit_i]], [close[exit_i]], color=GOOD, s=70, zorder=5, edgecolor="white", linewidth=1)
ax.annotate("Sortie\n(retour vers le VWAP)", xy=(times[exit_i], close[exit_i]),
            xytext=(times[exit_i], close[exit_i] + 22),
            ha="center", va="bottom", fontsize=9, color=INK_SECONDARY,
            arrowprops=dict(arrowstyle="-", color=INK_MUTED, lw=0.8))

ax.set_ylim(6520, 6695)
ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=30))
ax.tick_params(colors=INK_MUTED, labelsize=9)
for spine in ("top", "right"):
    ax.spines[spine].set_visible(False)
for spine in ("left", "bottom"):
    ax.spines[spine].set_color(GRID)
ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
ax.set_ylabel("Prix (points MES)", color=INK_SECONDARY, fontsize=10)

fig.suptitle("VWAP Reversion -- exemple reel : MES, 21 novembre 2025",
              color=INK_PRIMARY, fontsize=13, fontweight="bold", x=0.02, y=0.985, ha="left")
fig.text(0.02, 0.945, "Le prix s'ecarte du VWAP de plus de 2 sigma vers 10h35, puis revient dessus en debut d'apres-midi",
          fontsize=9.5, color=INK_SECONDARY, ha="left")

legend = ax.legend(loc="upper left", frameon=False, fontsize=9, labelcolor=INK_SECONDARY)

plt.tight_layout(rect=(0, 0, 1, 0.92))
plt.savefig("examples/mes_2025-11-21_reversion.png", dpi=140, facecolor=SURFACE)
print("Graphique ecrit dans examples/mes_2025-11-21_reversion.png")
