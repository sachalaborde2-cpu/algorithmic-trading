"""
Backtest d'un Opening Range Breakout (ORB) intraday sur futures indice (MES / ES).

Conventions
-----------
- Barres IB : l'horodatage est le DEBUT de la barre (la barre 09:30 couvre 09:30-09:35).
- Tout est converti en heure de New York. Ca regle le decalage d'heure d'ete
  entre Paris, Chicago et New York.
- Le signal est calcule a la CLOTURE d'une barre, l'ordre est execute a
  l'OUVERTURE de la barre suivante. Aucune information future n'est utilisee.
- Un seul trade par jour, toujours flat avant la cloture (16:00 NY).

Usage
-----
    python orb_backtest.py data/MES_5min_all.csv --instrument MES

CSV attendu : datetime (UTC), open, high, low, close, volume [, contract]
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from itertools import product

import numpy as np
import pandas as pd

TZ = "America/New_York"
SESSION_START = "09:30"
SESSION_MINUTES = 390  # 09:30 -> 16:00


# --------------------------------------------------------------------------
# Parametres
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Instrument:
    tick: float
    point_value: float      # $ par point d'indice et par contrat
    commission_side: float  # $ par contrat et par cote, tout compris


# Valeurs prudentes, a verifier sur la grille tarifaire IBKR.
INSTRUMENTS = {
    "MES": Instrument(tick=0.25, point_value=5.0, commission_side=0.85),
    "ES": Instrument(tick=0.25, point_value=50.0, commission_side=2.10),
}


@dataclass(frozen=True)
class Params:
    or_minutes: int = 30              # duree de l'opening range
    stop_mode: str = "opposite"       # "opposite": autre bord du range, "mid": milieu du range
    target_r: float | None = None     # objectif en multiple du risque (None = pas d'objectif)
    slippage_ticks: float = 1.0       # par execution au marche (entree, stop, sortie horaire)
    limit_through_ticks: float = 1.0  # un objectif n'est rempli que si le prix le depasse de N ticks


# --------------------------------------------------------------------------
# Donnees
# --------------------------------------------------------------------------
@dataclass
class Day:
    date: pd.Timestamp
    idx: pd.DatetimeIndex
    o: list
    h: list
    l: list
    c: list


def load_bars(path: str, bar_minutes: int = 5) -> tuple[list[Day], dict]:
    """Charge le CSV, passe en heure de NY, garde la seance reguliere complete."""
    df = pd.read_csv(path)
    df["ts"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_convert(TZ)
    df["date"] = df["ts"].dt.tz_localize(None).dt.normalize()

    # Seance reguliere uniquement : barres qui demarrent entre 09:30 et 15:59 (heure de NY)
    df = df.set_index("ts").between_time(SESSION_START, "15:59").reset_index()

    # Un seul contrat par jour : celui qui a le plus de volume pendant la seance
    # (evite de gerer les rolls, possible parce que la strategie est flat chaque soir).
    if "contract" in df.columns:
        vol = df.groupby(["date", "contract"], as_index=False)["volume"].sum()
        best = vol.sort_values("volume").drop_duplicates("date", keep="last")
        df = df.merge(best[["date", "contract"]], on=["date", "contract"], how="inner")

    df = df.sort_values("ts").drop_duplicates("ts").set_index("ts")

    expected = SESSION_MINUTES // bar_minutes
    days, dropped = [], 0
    for date, g in df.groupby("date"):
        # jours incomplets (demi-seances, trous de donnees) : on les ecarte
        if len(g) != expected or g.index[0].strftime("%H:%M") != SESSION_START:
            dropped += 1
            continue
        days.append(Day(date, g.index, g["open"].tolist(), g["high"].tolist(),
                        g["low"].tolist(), g["close"].tolist()))
    info = {"days": len(days), "dropped": dropped,
            "first": days[0].date.date() if days else None,
            "last": days[-1].date.date() if days else None}
    return days, info


# --------------------------------------------------------------------------
# Moteur : un jour = un trade au plus
# --------------------------------------------------------------------------
TRADE_COLS = ["date", "side", "entry_time", "exit_time", "entry", "exit",
              "pts", "risk_pts", "r_mult", "pnl", "reason", "or_width"]


def simulate_day(day: Day, p: Params, inst: Instrument, bar_minutes: int = 5,
                 rng: np.random.Generator | None = None) -> dict | None:
    """
    Regles :
      1. Opening range = plus haut / plus bas des `or_minutes` premieres minutes.
      2. Apres le range, la premiere barre qui CLOTURE hors du range donne le signal
         (au-dessus = long, en dessous = short).
      3. Entree a l'ouverture de la barre suivante, plus slippage.
      4. Stop : autre bord du range (ou milieu). Objectif optionnel en multiple du risque.
      5. Si stop et objectif sont touches dans la meme barre, on suppose le stop d'abord.
      6. Sortie forcee a la cloture de la derniere barre de la seance.

    Si `rng` est fourni, la direction est tiree au hasard (meme timing, meme distance
    de stop) : sert de benchmark "pile ou face".
    """
    o, h, l, c = day.o, day.h, day.l, day.c
    n = len(c)
    n_or = p.or_minutes // bar_minutes
    or_hi, or_lo = max(h[:n_or]), min(l[:n_or])
    slip = p.slippage_ticks * inst.tick

    # 1-2. Signal : premiere cloture hors du range
    d_sig, k = 0, None
    for k in range(n_or, n - 1):
        if c[k] > or_hi:
            d_sig = 1
            break
        if c[k] < or_lo:
            d_sig = -1
            break
    if d_sig == 0:
        return None

    # 3. Entree a l'open de la barre suivante
    e = k + 1
    if p.stop_mode == "mid":
        stop_lvl = (or_hi + or_lo) / 2
    else:
        stop_lvl = or_lo if d_sig == 1 else or_hi
    r_gross = d_sig * (o[e] - stop_lvl)   # distance open -> stop, en points
    if r_gross <= inst.tick:
        return None                        # stop degenere, on ne trade pas

    d = d_sig if rng is None else int(rng.choice((-1, 1)))
    entry = o[e] + d * slip
    stop = o[e] - d * r_gross              # = stop_lvl quand d == d_sig
    risk = d * (entry - stop)
    target = None if p.target_r is None else entry + d * p.target_r * risk
    thr = p.limit_through_ticks * inst.tick

    # 4-6. Gestion de la position barre par barre
    exit_px, reason, x = None, "time", n - 1
    for j in range(e, n):
        adverse = l[j] if d == 1 else h[j]
        favorable = h[j] if d == 1 else l[j]
        if j > e and d * (o[j] - stop) <= 0:            # gap a travers le stop
            exit_px, reason, x = o[j] - d * slip, "stop_gap", j
            break
        if d * (adverse - stop) <= 0:                    # stop touche
            exit_px, reason, x = stop - d * slip, "stop", j
            break
        if target is not None and d * (favorable - (target + d * thr)) >= 0:
            exit_px, reason, x = target, "target", j     # ordre limite, pas de slippage
            break
        if j == n - 1:                                   # cloture de seance
            exit_px, reason, x = c[j] - d * slip, "time", j

    pts = d * (exit_px - entry)
    return {
        "date": day.date, "side": d, "entry_time": day.idx[e], "exit_time": day.idx[x],
        "entry": entry, "exit": exit_px, "pts": pts, "risk_pts": risk,
        "r_mult": pts / risk,
        "pnl": pts * inst.point_value - 2 * inst.commission_side,
        "reason": reason, "or_width": or_hi - or_lo,
    }


def run_backtest(days: list[Day], p: Params, inst: Instrument, bar_minutes: int = 5,
                 rng: np.random.Generator | None = None) -> pd.DataFrame:
    rows = [t for t in (simulate_day(d, p, inst, bar_minutes, rng) for d in days) if t]
    return pd.DataFrame(rows, columns=TRADE_COLS)


# --------------------------------------------------------------------------
# Metriques
# --------------------------------------------------------------------------
def sel(trades: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    return trades[trades["date"].isin(dates)]


def metrics(trades: pd.DataFrame, dates: pd.DatetimeIndex) -> dict:
    """`dates` = tous les jours de la periode (les jours sans trade comptent pour 0)."""
    if trades.empty:
        return {"n_trades": 0}
    daily = trades.groupby("date")["pnl"].sum().reindex(dates, fill_value=0.0)
    eq = np.concatenate([[0.0], daily.cumsum().to_numpy()])
    gains = trades.loc[trades["pnl"] > 0, "pnl"].sum()
    losses = -trades.loc[trades["pnl"] < 0, "pnl"].sum()
    sd = daily.std()
    return {
        "n_trades": len(trades),
        "win_rate": (trades["pnl"] > 0).mean(),
        "exp_$": trades["pnl"].mean(),
        "exp_R": trades["r_mult"].mean(),
        "profit_factor": gains / losses if losses > 0 else np.inf,
        "total_$": trades["pnl"].sum(),
        "sharpe": daily.mean() / sd * np.sqrt(252) if sd > 0 else np.nan,
        "t_stat": daily.mean() / sd * np.sqrt(len(daily)) if sd > 0 else np.nan,
        "max_dd_$": (eq - np.maximum.accumulate(eq)).min(),
    }


# --------------------------------------------------------------------------
# Tests de robustesse
# --------------------------------------------------------------------------
def walk_forward(all_trades: dict, dates: pd.DatetimeIndex, train_months: int = 12,
                 test_months: int = 3) -> tuple[pd.DataFrame, list, pd.DatetimeIndex]:
    """Chaque fenetre : on choisit les parametres sur `train`, on les applique sur `test`."""
    parts, log, test_all = [], [], []
    t0 = dates.min()
    while True:
        t1 = t0 + pd.DateOffset(months=train_months)
        t2 = t1 + pd.DateOffset(months=test_months)
        train = dates[(dates >= t0) & (dates < t1)]
        test = dates[(dates >= t1) & (dates < t2)]
        if len(test) == 0:
            break

        def score(p):
            s = metrics(sel(all_trades[p], train), train).get("sharpe", np.nan)
            return -1e9 if pd.isna(s) else s

        best = max(all_trades, key=score)
        parts.append(sel(all_trades[best], test))
        test_all.append(test)
        log.append((t1.date(), best))
        t0 = t0 + pd.DateOffset(months=test_months)
    oos = pd.concat(parts) if parts else pd.DataFrame(columns=TRADE_COLS)
    return oos, log, (test_all[0].append(test_all[1:]) if test_all else dates[:0])


def random_direction_test(days, p, inst, bar_minutes, dates, n_sims=300, seed=0):
    """Meme timing d'entree, meme distance de stop, direction tiree a pile ou face.
    Si l'ORB ne bat pas ca, la direction du breakout ne contient aucune information."""
    actual = sel(run_backtest(days, p, inst, bar_minutes), dates)["pnl"].sum()
    rng = np.random.default_rng(seed)
    sims = np.array([sel(run_backtest(days, p, inst, bar_minutes, rng), dates)["pnl"].sum()
                     for _ in range(n_sims)])
    pval = (np.sum(sims >= actual) + 1) / (n_sims + 1)
    return actual, sims.mean(), sims.std(), pval


# --------------------------------------------------------------------------
# Rapport
# --------------------------------------------------------------------------
def fmt(d: dict) -> str:
    keys = ["n_trades", "win_rate", "exp_$", "exp_R", "profit_factor",
            "total_$", "sharpe", "t_stat", "max_dd_$"]
    return "  ".join(f"{k}={d[k]:.2f}" if k in d and k != "n_trades" else f"{k}={d.get(k)}"
                     for k in keys)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--instrument", default="MES", choices=INSTRUMENTS)
    ap.add_argument("--bar-minutes", type=int, default=5)
    ap.add_argument("--oos-frac", type=float, default=0.3, help="part finale reservee au hors-echantillon")
    ap.add_argument("--plot", action="store_true")
    a = ap.parse_args()

    inst, bm = INSTRUMENTS[a.instrument], a.bar_minutes
    days, info = load_bars(a.csv, bm)
    print(f"\nDonnees : {info['days']} jours ({info['first']} -> {info['last']}), "
          f"{info['dropped']} jours incomplets ecartes")
    if info["days"] < 250:
        print("ATTENTION : moins d'un an de donnees, les resultats seront peu fiables.")

    dates = pd.DatetimeIndex([d.date for d in days])
    k = int(len(dates) * (1 - a.oos_frac))
    is_dates, oos_dates = dates[:k], dates[k:]
    print(f"In-sample : {is_dates[0].date()} -> {is_dates[-1].date()} | "
          f"Hors-echantillon : {oos_dates[0].date()} -> {oos_dates[-1].date()}")

    # 1. Grille de parametres, evaluee en in-sample ET hors-echantillon
    grid = [Params(or_minutes=o, stop_mode=s, target_r=t)
            for o, s, t in product((15, 30, 60), ("opposite", "mid"), (None, 1.0, 1.5, 2.0))]
    all_trades = {p: run_backtest(days, p, inst, bm) for p in grid}

    rows = []
    for p in grid:
        m_is = metrics(sel(all_trades[p], is_dates), is_dates)
        m_oos = metrics(sel(all_trades[p], oos_dates), oos_dates)
        rows.append({"or_min": p.or_minutes, "stop": p.stop_mode, "target_R": p.target_r,
                     "n_IS": m_is.get("n_trades"), "exp$_IS": m_is.get("exp_$"),
                     "PF_IS": m_is.get("profit_factor"), "sharpe_IS": m_is.get("sharpe"),
                     "sharpe_OOS": m_oos.get("sharpe"), "exp$_OOS": m_oos.get("exp_$")})
    table = pd.DataFrame(rows).sort_values("sharpe_IS", ascending=False)
    print(f"\n=== 1. Grille ({len(grid)} configurations testees) ===")
    print(table.round(2).to_string(index=False))
    print(f"Le meilleur Sharpe in-sample sur {len(grid)} essais est biaise a la hausse : "
          "regarde surtout si le classement tient hors-echantillon.")

    # 2. Meilleure config in-sample, evaluee UNE fois hors-echantillon
    best = max(grid, key=lambda p: (lambda s: -1e9 if pd.isna(s) else s)(
        metrics(sel(all_trades[p], is_dates), is_dates).get("sharpe", np.nan)))
    tr = all_trades[best]
    print(f"\n=== 2. Meilleure config in-sample : {best} ===")
    print("IS  :", fmt(metrics(sel(tr, is_dates), is_dates)))
    print("OOS :", fmt(metrics(sel(tr, oos_dates), oos_dates)))

    # 3. Walk-forward sur toute la grille
    oos_wf, log, wf_dates = walk_forward(all_trades, dates)
    print("\n=== 3. Walk-forward (train 12 mois, test 3 mois) ===")
    if len(wf_dates):
        print("Concatenation des periodes de test :", fmt(metrics(oos_wf, wf_dates)))
        for t1, p in log:
            print(f"  test a partir de {t1} : OR={p.or_minutes}, stop={p.stop_mode}, target={p.target_r}")
    else:
        print("Pas assez d'historique pour un walk-forward 12+3 mois.")

    # 4. Sensibilite aux couts
    print("\n=== 4. Sensibilite au slippage (meilleure config, toute la periode) ===")
    for s in (0.0, 1.0, 2.0, 3.0):
        p = Params(**{**asdict(best), "slippage_ticks": s})
        print(f"  slippage {s:.0f} tick(s)/execution :",
              fmt(metrics(run_backtest(days, p, inst, bm), dates)))

    # 5. Benchmark pile ou face
    print("\n=== 5. Direction au hasard (meme timing, meme stop), hors-echantillon ===")
    actual, mu, sd, pval = random_direction_test(days, best, inst, bm, oos_dates)
    print(f"  ORB reel : {actual:.0f}$ | pile ou face : {mu:.0f}$ +/- {sd:.0f}$ | p-value = {pval:.3f}")

    # 6. Decompositions
    full = sel(tr, dates)
    print("\n=== 6. Decompositions (meilleure config, toute la periode) ===")
    print(full.groupby("side")["pnl"].agg(n="count", moyenne="mean", total="sum").round(1).rename(index={1: "long", -1: "short"}))
    print(full.groupby("reason")["pnl"].agg(n="count", moyenne="mean").round(1))
    print(full.groupby(full["date"].dt.year)["pnl"].agg(n="count", moyenne="mean", total="sum").round(1))

    out = f"trades_{a.instrument}_best.csv"
    full.to_csv(out, index=False)
    print(f"\nTrades ecrits dans {out}")

    if a.plot:
        import matplotlib.pyplot as plt
        daily = full.groupby("date")["pnl"].sum().reindex(dates, fill_value=0.0)
        ax = daily.cumsum().plot(figsize=(10, 4), title="P&L cumule (1 contrat, apres couts)")
        ax.axvline(oos_dates[0], color="red", ls="--", label="debut hors-echantillon")
        ax.legend()
        plt.tight_layout()
        plt.savefig("equity_best.png", dpi=120)
        print("Courbe ecrite dans equity_best.png")


if __name__ == "__main__":
    main()
