"""Genere un graphique pedagogique du pairs trading SPY/QQQ sur une journee
reelle : prix normalises des deux jambes en haut, z-score du spread (avec les
seuils d'entree/sortie/stop et le trade) en bas."""
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np

from pairs_backtest import Params, compute_beta_by_date, load_pair_bars, simulate_day, _spread_stats

SURFACE = "#fcfcfb"
BLUE = "#2a78d6"
ORANGE = "#eb6834"
PURPLE = "#7a52c9"
GOOD = "#0ca30c"
CRITICAL = "#d03b3b"
INK = "#1a1a1a"
MUTED = "#8a8a8a"


def main():
    days, _ = load_pair_bars("data_spy/SPY_5min_all.csv", "data_qqq/QQQ_5min_all.csv")
    beta_by_date = compute_beta_by_date(days, beta_window=20)
    p = Params()

    chosen = None
    for d in days:
        beta = beta_by_date.get(d.date)
        if beta is None:
            continue
        t = simulate_day(d, p, beta)
        if t and t["reason"] == "target" and t["pnl"] > 0 and abs(t["entry_dev"]) > 2.2:
            chosen = (d, beta, t)
            if d.date.year >= 2025:
                break
    day, beta, trade = chosen
    print(f"Jour choisi : {day.date.date()}  beta={beta:.3f}  trade={trade}")

    spread = np.log(np.asarray(day.c_spy)) - beta * np.log(np.asarray(day.c_qqq))
    mean, std = _spread_stats(spread)
    z = np.divide(spread - mean, std, out=np.zeros_like(spread), where=std > 1e-9)

    times = day.idx.tz_localize(None)  # affichage en heure NY naive (evite la conversion UTC de matplotlib)
    entry_t, exit_t = trade["entry_time"].tz_localize(None), trade["exit_time"].tz_localize(None)
    spy_n = np.asarray(day.c_spy) / day.c_spy[0] * 100
    qqq_n = np.asarray(day.c_qqq) / day.c_qqq[0] * 100

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7), sharex=True,
                                   gridspec_kw={"height_ratios": [1, 1.2]})
    fig.patch.set_facecolor(SURFACE)
    for ax in (ax1, ax2):
        ax.set_facecolor(SURFACE)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        for spine in ("left", "bottom"):
            ax.spines[spine].set_color(MUTED)
        ax.tick_params(colors=INK, labelsize=8)

    ax1.plot(times, spy_n, color=BLUE, lw=1.6, label="SPY (base 100)")
    ax1.plot(times, qqq_n, color=ORANGE, lw=1.6, label="QQQ (base 100)")
    ax1.set_title(f"Pairs trading SPY/QQQ — exemple réel du {day.date.date()}",
                  color=INK, fontsize=12, loc="left")
    ax1.set_ylabel("Prix normalisé (base 100)", color=INK, fontsize=9)
    ax1.legend(loc="upper left", frameon=False, fontsize=8)

    ax2.plot(times, z, color=PURPLE, lw=1.6, label="Z-score du spread")
    ax2.axhline(0, color=MUTED, lw=0.8)
    ax2.axhline(p.entry_z, color=CRITICAL, lw=1.0, ls="--", label=f"entry_z = ±{p.entry_z}")
    ax2.axhline(-p.entry_z, color=CRITICAL, lw=1.0, ls="--")
    ax2.axhline(p.exit_z, color=GOOD, lw=1.0, ls=":", label=f"exit_z = ±{p.exit_z}")
    ax2.axhline(-p.exit_z, color=GOOD, lw=1.0, ls=":")

    ax2.axvline(entry_t, color=INK, lw=1.0, ls="-")
    ax2.axvline(exit_t, color=INK, lw=1.0, ls="-")
    ax2.annotate("entrée\n(long spread)" if trade["side"] == 1 else "entrée\n(short spread)",
                 xy=(entry_t, trade["side"] * p.entry_z),
                 xytext=(entry_t, -3.2 if trade["side"] == 1 else 3.0),
                 color=INK, fontsize=8, ha="center")
    ax2.annotate("sortie\n(target)", xy=(exit_t, 0), xytext=(exit_t, 1.6 if trade["side"] == 1 else -1.6),
                 color=GOOD, fontsize=8, ha="center")

    ax2.set_ylabel("Z-score (spread vs moyenne du jour)", color=INK, fontsize=9)
    ax2.set_xlabel("Heure (NY)", color=INK, fontsize=9)
    ax2.legend(loc="upper right", frameon=False, fontsize=8)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

    fig.tight_layout()
    out = "examples/spyqqq_pairs_example.png"
    fig.savefig(out, dpi=140, facecolor=SURFACE)
    print(f"Graphique ecrit dans {out}")


if __name__ == "__main__":
    main()
