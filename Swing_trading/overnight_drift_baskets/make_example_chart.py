"""Graphique pedagogique : decomposition du rendement cumule en jambe
overnight (cloture J -> ouverture J+1) vs jambe intraday (ouverture J ->
cloture J), sur donnees journalieres reelles. Meme principe que
Intraday_trading/overnight_drift/make_example_chart.py, adapte aux barres
journalieres (pas de barres 5 minutes disponibles pour ces 13 ETF-paniers)."""
import argparse

import matplotlib.pyplot as plt
import pandas as pd

from basket_backtest import INSTRUMENTS, load_daily

SURFACE = "#fcfcfb"
BLUE = "#2a78d6"
ORANGE = "#eb6834"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="GLD", choices=INSTRUMENTS)
    ap.add_argument("--out", default="examples/overnight_vs_intraday.png")
    a = ap.parse_args()

    df = load_daily(f"data_{a.symbol.lower()}/{a.symbol}_daily_all.csv")
    close, open_, dates = df["close"].to_numpy(), df["open"].to_numpy(), df["date"]

    overnight_ret = [(open_[i + 1] / close[i] - 1) * 100 for i in range(len(df) - 1)]
    intraday_ret = [(close[i] / open_[i] - 1) * 100 for i in range(len(df) - 1)]
    plot_dates = dates.iloc[1:]

    out = pd.DataFrame({"date": plot_dates, "overnight": overnight_ret,
                        "intraday": intraday_ret}).set_index("date")
    cum = (1 + out / 100).cumprod() - 1

    fig, ax = plt.subplots(figsize=(11, 5))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ax.plot(cum.index, cum["overnight"] * 100, color=BLUE, lw=2,
            label="Overnight cumule (cloture J -> ouverture J+1)")
    ax.plot(cum.index, cum["intraday"] * 100, color=ORANGE, lw=2,
            label="Intraday cumule (ouverture J -> cloture J)")
    ax.axhline(0, color="#888", lw=0.8)
    ax.set_title(f"{a.symbol} : rendement cumule, overnight vs intraday (brut, sans couts)")
    ax.set_ylabel("Rendement cumule (%)")
    ax.legend(loc="upper left", frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(a.out, dpi=120, facecolor=SURFACE)
    print(f"Graphique ecrit dans {a.out}")
    print(f"Rendement cumule final : overnight={cum['overnight'].iloc[-1] * 100:.1f}% | "
          f"intraday={cum['intraday'].iloc[-1] * 100:.1f}%")


if __name__ == "__main__":
    main()
