"""
Graphiques pedagogiques sur donnees reelles :
1. examples/twin_logic.png : ecart GLD/IAU (deux ETF d'or physique), sa
   valeur d'equilibre glissante, la deviation et les seuils, avec les
   entrees/sorties de la regle (k=12 pb, config retenue en IS).
2. examples/speed_vs_costs.png : par paire, gain brut moyen si l'on pouvait
   entrer au cours de cloture meme ou l'ecart est mesure (borne haute non
   tradable) vs a l'ouverture suivante (realiste), compare au cout
   aller-retour -- montre que l'ecart disparait pendant la nuit.
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from twin_backtest import Params, deviation_bps, fair_value, load_pair, simulate_pair, spread

INK, MUTED, GRID = "#1f2328", "#6e7781", "#d0d7de"
BLUE, ORANGE, GRAY = "#2a6fdb", "#e8803a", "#9aa4ae"
WINDOW = 500


def logic_chart() -> None:
    df = load_pair("GLD", "IAU")
    p = Params(k_bps=12.0)
    s = spread(df) * 1e4
    fair = fair_value(df, p) * 1e4
    d = deviation_bps(df, p)
    t = simulate_pair(df, p, "GLD/IAU")
    start = len(df) - WINDOW
    x = df["date"].iloc[start:]
    ref = s.iloc[start]
    t = t[t["entry_date"] >= x.iloc[0]]

    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(12, 7), sharex=True, gridspec_kw={"height_ratios": [1, 1]})
    ax0.plot(x, s.iloc[start:] - ref, color=BLUE, lw=1.2, label="ecart ln(GLD) - ln(IAU) a la cloture")
    ax0.plot(x, fair.iloc[start:] - ref, color=ORANGE, lw=2, label="equilibre (moyenne des 20 clotures precedentes)")
    ax0.set_ylabel("pb (base 0 au debut)")
    ax0.set_title("GLD vs IAU (or physique) : l'ecart oscille autour d'un equilibre qui derive lentement (frais de gestion)",
                  color=INK, fontsize=11)
    ax0.legend(frameon=False, loc="upper right", fontsize=9)

    ax1.plot(x, d.iloc[start:], color=GRAY, lw=1, label="deviation d = ecart - equilibre")
    for lvl in (p.k_bps, -p.k_bps):
        ax1.axhline(lvl, color=MUTED, ls="--", lw=1)
    ax1.axhline(0, color=INK, lw=0.6)
    ent = df.set_index("date").index
    for _, r in t.iterrows():
        sig_date = ent[ent.get_loc(r["entry_date"]) - 1]
        ax1.scatter(sig_date, r["d_signal_bps"], marker="o", s=36, color=BLUE, zorder=3)
        ax1.axvspan(r["entry_date"], r["exit_date"], color=BLUE, alpha=0.08, lw=0)
    ax1.scatter([], [], marker="o", s=36, color=BLUE, label=f"signal |d| > {p.k_bps:g} pb (entree a l'ouverture suivante)")
    ax1.fill_between([], [], color=BLUE, alpha=0.15, label="position ouverte")
    ax1.set_ylabel("pb")
    ax1.set_xlabel("date")
    ax1.legend(frameon=True, facecolor="white", edgecolor=GRID, loc="lower right", fontsize=9)
    for ax in (ax0, ax1):
        ax.grid(color=GRID, lw=0.6)
        ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    plt.savefig("examples/twin_logic.png", dpi=120)
    print("examples/twin_logic.png")


def speed_chart() -> None:
    tr = pd.read_csv("trades_best.csv")
    g = tr.groupby("pair").agg(close=("gross_close_entry", "mean"), open_=("gross", "mean"),
                               cost=("costs", "mean"), n=("pnl", "size")) / np.array([1e1, 1e1, 1e1, 1])
    g = g.sort_values("close")
    y = np.arange(len(g))
    h = 0.26
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.barh(y + h, g["close"], height=h - 0.04, color=GRAY, label="gain brut si entree a la cloture J (borne haute, non tradable)")
    ax.barh(y, g["open_"], height=h - 0.04, color=BLUE, label="gain brut avec entree a l'ouverture J+1 (realiste)")
    ax.barh(y - h, g["cost"], height=h - 0.04, color=ORANGE, label="cout aller-retour (2 jambes, 1 tick + commission + emprunt)")
    ax.set_yticks(y)
    ax.set_yticklabels([f"{p} ({int(n)} trades)" for p, n in zip(g.index, g["n"])])
    ax.axvline(0, color=INK, lw=0.6)
    ax.set_xlabel("pb du notionnel, moyenne par trade (k = 12 pb)")
    ax.set_title("L'ecart existe a la cloture, mais il a presque disparu a l'ouverture suivante", color=INK, fontsize=11)
    ax.legend(frameon=False, loc="lower right", fontsize=9)
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    plt.savefig("examples/speed_vs_costs.png", dpi=120)
    print("examples/speed_vs_costs.png")


if __name__ == "__main__":
    logic_chart()
    speed_chart()
