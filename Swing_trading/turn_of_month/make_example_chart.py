"""Graphique pedagogique : rendement overnight moyen (cloture J -> ouverture
J+1) selon que le jour J appartient a la fenetre turn-of-month (TOM) ou non,
sur donnees journalieres reelles. Illustre la logique testee -- pas le
resultat du backtest (qui inclut couts/slippage et le protocole IS/OOS
complet, voir turn_of_month_backtest.py)."""
import argparse

import matplotlib.pyplot as plt
import numpy as np

from turn_of_month_backtest import INSTRUMENTS, load_daily, tom_membership

SURFACE = "#fcfcfb"
BLUE = "#2a78d6"
ORANGE = "#eb6834"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="SPY", choices=INSTRUMENTS)
    ap.add_argument("--out", default="examples/tom_vs_non_tom.png")
    a = ap.parse_args()

    df = load_daily(f"data_{a.symbol.lower()}/{a.symbol}_daily_all.csv")
    tom = tom_membership(df)
    close, open_ = df["close"].to_numpy(), df["open"].to_numpy()

    overnight_ret = (open_[1:] / close[:-1] - 1) * 100
    is_tom = tom.iloc[:-1].to_numpy()

    tom_ret, non_tom_ret = overnight_ret[is_tom], overnight_ret[~is_tom]

    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    fig.patch.set_facecolor(SURFACE)

    ax = axes[0]
    ax.set_facecolor(SURFACE)
    means = [non_tom_ret.mean(), tom_ret.mean()]
    ax.bar(["Jours non-TOM", "Jours TOM"], means, color=[ORANGE, BLUE])
    ax.axhline(0, color="#888", lw=0.8)
    ax.set_title(f"{a.symbol} : rendement overnight moyen (%)")
    ax.spines[["top", "right"]].set_visible(False)

    ax2 = axes[1]
    ax2.set_facecolor(SURFACE)
    cum_tom = np.cumsum(np.where(is_tom, overnight_ret, 0.0))
    cum_non_tom = np.cumsum(np.where(~is_tom, overnight_ret, 0.0))
    ax2.plot(cum_tom, color=BLUE, lw=2, label="Cumul overnight, jours TOM uniquement")
    ax2.plot(cum_non_tom, color=ORANGE, lw=2, label="Cumul overnight, jours non-TOM uniquement")
    ax2.axhline(0, color="#888", lw=0.8)
    ax2.set_title(f"{a.symbol} : contribution cumulee au rendement overnight (brut, sans couts)")
    ax2.legend(loc="upper left", frameon=False, fontsize=8)
    ax2.spines[["top", "right"]].set_visible(False)

    fig.tight_layout()
    fig.savefig(a.out, dpi=120, facecolor=SURFACE)
    print(f"Graphique ecrit dans {a.out}")
    print(f"Rendement overnight moyen : TOM={tom_ret.mean():.4f}% (n={len(tom_ret)}) | "
          f"non-TOM={non_tom_ret.mean():.4f}% (n={len(non_tom_ret)})")


if __name__ == "__main__":
    main()
