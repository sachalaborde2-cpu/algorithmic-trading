"""Graphique pedagogique : prix normalise des 20 instruments + zoom sur le
classement de momentum (score 12-1) a une date de rebalancement reelle,
montrant le panier long (haut du classement) et le panier short (bas du
classement)."""
import argparse

import matplotlib.pyplot as plt
import pandas as pd

from momentum_backtest import Params, load_universe, momentum_scores, rebalance_dates, TICKERS

SURFACE = "#fcfcfb"
GOOD = "#0ca30c"
BAD = "#d6362a"
NEUTRAL = "#c9c9c4"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookback", type=int, default=12, choices=(6, 12))
    ap.add_argument("--rebal-index", type=int, default=-6,
                     help="index (negatif = depuis la fin) de la date de rebalancement illustree")
    ap.add_argument("--n-long", type=int, default=4)
    ap.add_argument("--n-short", type=int, default=4)
    ap.add_argument("--out", default="examples/momentum_logic.png")
    a = ap.parse_args()

    open_df, close_df = load_universe()
    p = Params(lookback_months=a.lookback, n_long=a.n_long, n_short=a.n_short)
    scores = momentum_scores(close_df, p)
    rebal = rebalance_dates(close_df.index)
    dt = rebal[a.rebal_index]
    row = scores.loc[dt].dropna().sort_values(ascending=False)
    longs = set(row.index[:a.n_long])
    shorts = set(row.index[-a.n_short:])
    print(f"Rebalancement illustre : {dt.date()} | long={sorted(longs)} | short={sorted(shorts)}")

    win_start = dt - pd.DateOffset(months=a.lookback + 3)
    win = close_df.loc[(close_df.index >= win_start) & (close_df.index <= dt)]
    norm = win / win.iloc[0] * 100

    fig, axes = plt.subplots(1, 2, figsize=(14, 6), gridspec_kw={"width_ratios": [3, 2]})
    fig.patch.set_facecolor(SURFACE)

    ax = axes[0]
    ax.set_facecolor(SURFACE)
    for tk in TICKERS:
        if tk in longs:
            ax.plot(norm.index, norm[tk], color=GOOD, lw=1.6, zorder=5)
        elif tk in shorts:
            ax.plot(norm.index, norm[tk], color=BAD, lw=1.6, zorder=5)
        else:
            ax.plot(norm.index, norm[tk], color=NEUTRAL, lw=0.8, alpha=0.7, zorder=1)
    ax.axvline(dt, color="#333", ls="--", lw=1, label=f"Rebalancement ({dt.date()})")
    ax.set_title(f"Prix normalises (base 100), fenetre de lookback {a.lookback}-1 mois")
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)

    ax2 = axes[1]
    ax2.set_facecolor(SURFACE)
    colors = [GOOD if tk in longs else BAD if tk in shorts else NEUTRAL for tk in row.index]
    ax2.barh(row.index[::-1], (row.values * 100)[::-1], color=colors[::-1])
    ax2.axvline(0, color="#333", lw=0.8)
    ax2.set_title(f"Classement momentum au {dt.date()}\n(score {a.lookback}-1, %)")
    ax2.spines[["top", "right"]].set_visible(False)

    fig.tight_layout()
    fig.savefig(a.out, dpi=120, facecolor=SURFACE)
    print(f"Graphique ecrit dans {a.out}")


if __name__ == "__main__":
    main()
