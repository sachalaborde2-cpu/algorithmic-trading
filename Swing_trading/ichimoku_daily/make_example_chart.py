"""Graphique pedagogique : prix + nuage Ichimoku (Tenkan/Kijun/Senkou A-B) +
marqueurs des signaux TKC et KBO, sur une fenetre de donnees reelles."""
import argparse

import matplotlib.pyplot as plt
import pandas as pd

from ichimoku_backtest import Params, ichimoku_lines, compute_target_position, load_daily

SURFACE = "#fcfcfb"
BLUE = "#2a78d6"
ORANGE = "#eb6834"
GOOD = "#0ca30c"
BAD = "#d6362a"
CLOUD_UP = "#bfe3bf"
CLOUD_DOWN = "#f2c6c0"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--symbol", default="SPY")
    ap.add_argument("--signal", default="kbo", choices=("tkc", "kbo"))
    ap.add_argument("--window-days", type=int, default=260, help="nb de jours affiches (fenetre recente)")
    ap.add_argument("--out", default="examples/ichimoku_logic.png")
    a = ap.parse_args()

    df = load_daily(a.csv)
    print(f"{len(df)} jours charges ({df['date'].iloc[0].date()} -> {df['date'].iloc[-1].date()})")

    p = Params(signal=a.signal, mode="long_short")
    lines = ichimoku_lines(df, p)
    target = compute_target_position(df, p)

    win = df.iloc[-a.window_days:].copy()
    idx = win.index
    dates = win["date"]

    fig, ax = plt.subplots(figsize=(12, 6))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    sa, sb = lines["senkou_a"].loc[idx], lines["senkou_b"].loc[idx]
    ax.fill_between(dates, sa, sb, where=(sa >= sb), color=CLOUD_UP, alpha=0.6, interpolate=True, label="Kumo haussier")
    ax.fill_between(dates, sa, sb, where=(sa < sb), color=CLOUD_DOWN, alpha=0.6, interpolate=True, label="Kumo baissier")

    ax.plot(dates, win["close"], color="#333", lw=1.3, label="Cloture")
    ax.plot(dates, lines["tenkan"].loc[idx], color=BLUE, lw=1.0, label="Tenkan-sen (9)")
    ax.plot(dates, lines["kijun"].loc[idx], color=ORANGE, lw=1.0, label="Kijun-sen (26)")

    # marqueurs de signal : changement de position dans la fenetre affichee
    tgt_win = target.loc[idx]
    changes = tgt_win.ne(tgt_win.shift(1).fillna(0.0)) & (tgt_win != 0)
    longs = dates[changes & (tgt_win == 1)]
    shorts = dates[changes & (tgt_win == -1)]
    ax.scatter(longs, win.loc[changes & (tgt_win == 1), "close"], marker="^", color=GOOD, s=90,
              zorder=5, label="Signal long")
    ax.scatter(shorts, win.loc[changes & (tgt_win == -1), "close"], marker="v", color=BAD, s=90,
              zorder=5, label="Signal short")

    label = "Kumo Breakout (KBO)" if a.signal == "kbo" else "Tenkan-Kijun Cross (TKC)"
    ax.set_title(f"{a.symbol} : logique Ichimoku ({label}), {a.window_days} derniers jours")
    ax.legend(loc="upper left", frameon=False, ncol=2, fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(a.out, dpi=120, facecolor=SURFACE)
    print(f"Graphique ecrit dans {a.out}")


if __name__ == "__main__":
    main()
