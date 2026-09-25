"""
Graphique pedagogique : illustre, nuit par nuit sur une fenetre recente reelle,
quel(s) instrument(s) parmi SPY/QQQ/IWM/DIA avaient les confirmations reunies
(top-2 par score de momentum 6-1 ET regime Kumo bullish) et ont donc recu le
trade overnight ce soir-la -- rend visible le mecanisme decrit par
l'utilisateur : l'instrument qui "s'allume" change d'un soir a l'autre.
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from overnight_selection_backtest import (
    TICKERS,
    Params,
    build_signals,
    load_universe,
    selections_for_config,
)

WINDOW_DAYS = 90


def main() -> None:
    frames = load_universe()
    p = Params(config="cross_sectional_plus_regime")
    scores, regime, close, open_ = build_signals(frames, p)
    sels = selections_for_config(scores, regime, p)

    dates = frames[TICKERS[0]]["date"]
    n = len(dates)
    start = n - WINDOW_DAYS

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True,
                             gridspec_kw={"height_ratios": [2, 1]})

    ax0 = axes[0]
    for t in TICKERS:
        norm = close[t].iloc[start:n] / close[t].iloc[start]
        ax0.plot(dates.iloc[start:n], norm, label=t, linewidth=1.3)
    ax0.set_ylabel("Prix normalise (base 1.0)")
    ax0.set_title(f"Selection cross-sectionnelle overnight -- {WINDOW_DAYS} derniers jours "
                  f"({dates.iloc[start].date()} -> {dates.iloc[n - 1].date()})")
    ax0.legend(loc="upper left", ncol=4)
    ax0.grid(alpha=0.3)

    ax1 = axes[1]
    y_pos = {t: i for i, t in enumerate(TICKERS)}
    for i in range(start, n - 1):
        for t in sels[i]:
            ax1.scatter(dates.iloc[i], y_pos[t], marker="s", s=40, color="tab:green")
    ax1.set_yticks(list(y_pos.values()))
    ax1.set_yticklabels(list(y_pos.keys()))
    ax1.set_ylabel("Instrument trade\ncette nuit-la")
    ax1.set_xlabel("Date (decision prise a la cloture)")
    ax1.grid(alpha=0.3, axis="x")

    plt.tight_layout()
    plt.savefig("examples/selection_logic.png", dpi=120)
    print("Graphique ecrit dans examples/selection_logic.png")

    n_nights_with_signal = sum(1 for i in range(start, n - 1) if len(sels[i]) > 0)
    print(f"Sur les {WINDOW_DAYS} derniers jours : {n_nights_with_signal} nuits avec au moins "
          f"un instrument selectionne (sur {n - 1 - start} nuits tradables).")


if __name__ == "__main__":
    main()
