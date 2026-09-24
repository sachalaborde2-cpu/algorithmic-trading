"""Graphique pedagogique : decomposition du rendement cumule en jambe
overnight (cloture -> ouverture) vs jambe intraday (ouverture -> cloture)."""
import argparse

import matplotlib.pyplot as plt
import pandas as pd

from overnight_backtest import INSTRUMENTS, load_bars

SURFACE = "#fcfcfb"
BLUE = "#2a78d6"
ORANGE = "#eb6834"
GOOD = "#0ca30c"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--symbol", default="SPY")
    ap.add_argument("--instrument", default=None, choices=INSTRUMENTS,
                     help="par defaut = --symbol si c'est une cle valide de INSTRUMENTS")
    ap.add_argument("--bar-minutes", type=int, default=5)
    ap.add_argument("--out", default="examples/overnight_vs_intraday.png")
    a = ap.parse_args()

    inst = INSTRUMENTS.get(a.instrument or a.symbol)
    days, info = load_bars(a.csv, a.bar_minutes, inst)
    print(f"{info['days']} jours charges ({info['first']} -> {info['last']})")

    dates, overnight_ret, intraday_ret = [], [], []
    for prev, day in zip(days[:-1], days[1:]):
        dates.append(day.date)
        overnight_ret.append((day.o[0] / prev.c[-1] - 1) * 100)
        intraday_ret.append((day.c[-1] / day.o[0] - 1) * 100)

    df = pd.DataFrame({"date": dates, "overnight": overnight_ret, "intraday": intraday_ret}).set_index("date")
    cum = (1 + df / 100).cumprod() - 1

    fig, ax = plt.subplots(figsize=(11, 5))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ax.plot(cum.index, cum["overnight"] * 100, color=BLUE, lw=2,
            label="Overnight cumule (cloture J-1 -> ouverture J)")
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
