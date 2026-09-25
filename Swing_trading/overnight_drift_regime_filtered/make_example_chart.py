"""Graphique pedagogique : nuage Kumo + regime (bullish/bearish/neutral) +
entrees overnight reellement prises par le filtre bullish, sur des donnees
reelles (SPY, fenetre recente)."""
import argparse

import matplotlib.pyplot as plt
import pandas as pd

from regime_filtered_backtest import Params, kumo_bounds, regime_series, run_backtest, load_daily, INSTRUMENTS

SURFACE = "#fcfcfb"
CLOUD_UP = "#bfe3bf"
CLOUD_DOWN = "#f2c6c0"
GOOD = "#0ca30c"
BAD = "#d6362a"
GREY = "#9a9a9a"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="SPY")
    ap.add_argument("--window-days", type=int, default=260)
    ap.add_argument("--out", default="examples/regime_filter_logic.png")
    a = ap.parse_args()

    df = load_daily(f"data_{a.symbol.lower()}/{a.symbol}_daily_all.csv")
    p = Params(filter_regime="bullish")
    cloud_top, cloud_bottom = kumo_bounds(df, p)
    regime = regime_series(df, p)
    trades_bull = run_backtest(df, Params(filter_regime="bullish"), INSTRUMENTS[a.symbol])
    trades_all = run_backtest(df, Params(filter_regime="unfiltered"), INSTRUMENTS[a.symbol])

    win = df.iloc[-a.window_days:].copy()
    idx = win.index
    dates = win["date"]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True,
                                    gridspec_kw={"height_ratios": [3, 1]})
    fig.patch.set_facecolor(SURFACE)
    for ax in (ax1, ax2):
        ax.set_facecolor(SURFACE)
        ax.spines[["top", "right"]].set_visible(False)

    ct, cb = cloud_top.loc[idx], cloud_bottom.loc[idx]
    ax1.fill_between(dates, ct, cb, where=(ct >= cb), color=CLOUD_UP, alpha=0.6, interpolate=True, label="Kumo (nuage)")
    ax1.plot(dates, win["close"], color="#333", lw=1.3, label="Cloture")

    entries_taken = trades_bull[trades_bull["entry_time"].isin(win["date"])]
    entries_all = trades_all[trades_all["entry_time"].isin(win["date"])]
    entries_skipped = entries_all[~entries_all["entry_time"].isin(entries_taken["entry_time"])]

    ax1.scatter(entries_taken["entry_time"],
                win.set_index("date").loc[entries_taken["entry_time"], "close"],
                marker="^", color=GOOD, s=70, zorder=5,
                label="Entree overnight prise (regime bullish)")
    ax1.scatter(entries_skipped["entry_time"],
                win.set_index("date").loc[entries_skipped["entry_time"], "close"],
                marker="x", color=GREY, s=40, zorder=4, alpha=0.7,
                label="Entree overnight ecartee (filtre)")

    ax1.set_title(f"{a.symbol} : filtre de regime Kumo appliqué a l'edge overnight, "
                  f"{a.window_days} derniers jours")
    ax1.legend(loc="upper left", frameon=False, fontsize=9)

    colors = regime.loc[idx].map({"bullish": GOOD, "bearish": BAD, "neutral": GREY})
    ax2.bar(dates, [1] * len(idx), color=colors, width=1.0)
    ax2.set_yticks([])
    ax2.set_title("Regime du jour (vert=bullish, rouge=bearish, gris=neutre)", fontsize=9)

    fig.tight_layout()
    fig.savefig(a.out, dpi=120, facecolor=SURFACE)
    print(f"Graphique ecrit dans {a.out}")


if __name__ == "__main__":
    main()
