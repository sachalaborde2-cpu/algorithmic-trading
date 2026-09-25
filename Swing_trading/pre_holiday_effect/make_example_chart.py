"""Graphique pedagogique : rendement intraday moyen (ouverture -> cloture,
meme jour) selon que le jour appartient a la fenetre pre-ferie ou non, sur
donnees journalieres reelles. Illustre la logique testee -- pas le resultat
du backtest (qui inclut couts/slippage et le protocole IS/OOS complet, voir
pre_holiday_backtest.py)."""
import argparse

import matplotlib.pyplot as plt
import numpy as np

from pre_holiday_backtest import INSTRUMENTS, load_daily, pre_holiday_membership

SURFACE = "#fcfcfb"
BLUE = "#2a78d6"
ORANGE = "#eb6834"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="SPY", choices=INSTRUMENTS)
    ap.add_argument("--out", default="examples/pre_holiday_vs_non_pre_holiday.png")
    a = ap.parse_args()

    df = load_daily(f"data_{a.symbol.lower()}/{a.symbol}_daily_all.csv")
    pre_holiday = pre_holiday_membership(df)
    open_, close = df["open"].to_numpy(), df["close"].to_numpy()

    intraday_ret = (close / open_ - 1) * 100
    is_pre = pre_holiday.to_numpy()

    pre_ret, non_pre_ret = intraday_ret[is_pre], intraday_ret[~is_pre]

    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    fig.patch.set_facecolor(SURFACE)

    ax = axes[0]
    ax.set_facecolor(SURFACE)
    means = [non_pre_ret.mean(), pre_ret.mean()]
    ax.bar(["Jours normaux", "Jours pre-feries"], means, color=[ORANGE, BLUE])
    ax.axhline(0, color="#888", lw=0.8)
    ax.set_title(f"{a.symbol} : rendement intraday moyen (%)\n(ouverture -> cloture, meme jour)")
    ax.spines[["top", "right"]].set_visible(False)

    ax2 = axes[1]
    ax2.set_facecolor(SURFACE)
    cum_pre = np.cumsum(np.where(is_pre, intraday_ret, 0.0))
    cum_non_pre = np.cumsum(np.where(~is_pre, intraday_ret, 0.0))
    ax2.plot(cum_pre, color=BLUE, lw=2, label="Cumul intraday, jours pre-feries uniquement")
    ax2.plot(cum_non_pre, color=ORANGE, lw=2, label="Cumul intraday, jours normaux uniquement")
    ax2.axhline(0, color="#888", lw=0.8)
    ax2.set_title(f"{a.symbol} : contribution cumulee au rendement intraday (brut, sans couts)")
    ax2.legend(loc="upper left", frameon=False, fontsize=8)
    ax2.spines[["top", "right"]].set_visible(False)

    fig.tight_layout()
    fig.savefig(a.out, dpi=120, facecolor=SURFACE)
    print(f"Graphique ecrit dans {a.out}")
    print(f"Rendement intraday moyen : pre-ferie={pre_ret.mean():.4f}% (n={len(pre_ret)}) | "
          f"normal={non_pre_ret.mean():.4f}% (n={len(non_pre_ret)})")


if __name__ == "__main__":
    main()
