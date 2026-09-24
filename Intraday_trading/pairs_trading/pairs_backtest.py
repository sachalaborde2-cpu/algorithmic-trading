"""
Backtest d'un pairs trading intraday SPY / QQQ (arbitrage statistique).

Idee
----
SPY et QQQ sont deux ETF fortement correles (S&P 500 / Nasdaq-100). On construit
un spread log(SPY) - beta*log(QQQ), avec `beta` estime sur les clotures
quotidiennes des `beta_window` jours PRECEDENTS (jamais le jour trade lui-meme).
Intraday, on calcule un z-score de ce spread, cumule depuis l'ouverture (moyenne
et ecart-type cumules, comme le VWAP) : quand le spread s'ecarte de plus de
`entry_z` ecarts-types de sa propre moyenne du jour, on parie sur son retour
(mean-reversion) :
  - spread trop bas (z <= -entry_z) -> LONG SPY / SHORT QQQ (dollar-neutre)
  - spread trop haut (z >= entry_z) -> SHORT SPY / LONG QQQ
Sortie au retour a `exit_z`, ou stop si l'ecart continue de se creuser au-dela
de `stop_z` (fige au moment du signal).

Conventions (comme l'ORB / VWAP reversion, adaptees a 2 jambes)
-----------------------------------------------------------------
- Barres SPY et QQQ alignees sur les memes horodatages (jointure stricte) ;
  seance reguliere 09:30-16:00 NY, jours incomplets (sur l'un ou l'autre actif)
  ecartes.
- `beta` du jour J connu avant l'ouverture (estime sur les clotures J-beta_window
  a J-1 uniquement). Le z-score intraday a la barre j ne depend que des barres
  0..j du jour J (aucune fuite de futur).
- Signal calcule a la CLOTURE d'une barre (sur le spread, base sur les
  clotures des 2 jambes) ; execution des DEUX jambes a l'OUVERTURE de la barre
  suivante, plus slippage sur chaque jambe.
- Simplification assumee (a defaut de high/low combinables pour un spread
  synthetique a 2 jambes) : la detection stop/retour/sortie est evaluee sur les
  clotures uniquement (pas de precision intra-barre), et TOUTE sortie
  (stop, retour, ou fin de journee) est executee a l'ouverture de la barre
  suivante avec slippage sur les 2 jambes -- pas de fill "limite" idealise sans
  slippage comme pour les strategies a 1 jambe (plus conservateur).
- Position dollar-neutre : 100 actions SPY de reference, quantite QQQ ajustee
  au ratio de prix a l'entree pour egaliser les deux jambes en dollars (pas de
  ratio 1:1 en nombre d'actions).
- Un seul trade par jour, toujours flat avant la cloture (16:00 NY).

Usage
-----
    python pairs_backtest.py --spy data_spy/SPY_5min_all.csv --qqq data_qqq/QQQ_5min_all.csv

CSV attendus : datetime (UTC), open, high, low, close, volume
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
TICK = 0.01                  # SPY/QQQ
COMMISSION_SIDE = 1.00        # $ par jambe et par cote (comme SPY/QQQ ailleurs)
REF_SHARES_SPY = 100.0        # taille de reference sur la jambe SPY


# --------------------------------------------------------------------------
# Parametres
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Params:
    beta_window: int = 20       # jours de trading utilises pour estimer beta
    warmup_minutes: int = 30    # pas de signal avant que le z-score se stabilise
    entry_z: float = 2.0
    exit_z: float = 0.5
    stop_z: float = 3.5
    slippage_ticks: float = 1.0


# --------------------------------------------------------------------------
# Donnees
# --------------------------------------------------------------------------
@dataclass
class PairDay:
    date: pd.Timestamp
    idx: pd.DatetimeIndex
    o_spy: list
    c_spy: list
    o_qqq: list
    c_qqq: list


def _load_symbol(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["ts"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_convert(TZ)
    df["date"] = df["ts"].dt.tz_localize(None).dt.normalize()
    df = df.set_index("ts").between_time(SESSION_START, "15:59").reset_index()
    return df.sort_values("ts").drop_duplicates("ts")


def load_pair_bars(spy_csv: str, qqq_csv: str, bar_minutes: int = 5) -> tuple[list[PairDay], dict]:
    """Charge SPY et QQQ, aligne strictement sur les memes horodatages, garde
    les jours dont la seance est complete sur LES DEUX actifs."""
    spy = _load_symbol(spy_csv)
    qqq = _load_symbol(qqq_csv)
    m = spy.merge(qqq, on="ts", suffixes=("_spy", "_qqq"), how="inner")
    m["date"] = m["ts"].dt.tz_localize(None).dt.normalize()
    m = m.set_index("ts").sort_index()

    expected = SESSION_MINUTES // bar_minutes
    days, dropped = [], 0
    for date, g in m.groupby("date"):
        if len(g) != expected or g.index[0].strftime("%H:%M") != SESSION_START:
            dropped += 1
            continue
        days.append(PairDay(date, g.index, g["open_spy"].tolist(), g["close_spy"].tolist(),
                            g["open_qqq"].tolist(), g["close_qqq"].tolist()))
    info = {"days": len(days), "dropped": dropped,
            "first": days[0].date.date() if days else None,
            "last": days[-1].date.date() if days else None}
    return days, info


def compute_beta_by_date(days: list[PairDay], beta_window: int) -> dict:
    """Beta du jour i estime par regression log(SPY)~log(QQQ) sur les clotures
    de session des `beta_window` jours STRICTEMENT precedents (jamais le jour i
    lui-meme). Jours sans historique suffisant : pas de beta -> jour non trade."""
    closes_spy = np.array([d.c_spy[-1] for d in days])
    closes_qqq = np.array([d.c_qqq[-1] for d in days])
    beta_by_date = {}
    for i, day in enumerate(days):
        if i < beta_window:
            continue
        x = np.log(closes_qqq[i - beta_window:i])
        y = np.log(closes_spy[i - beta_window:i])
        xm, ym = x.mean(), y.mean()
        denom = ((x - xm) ** 2).sum()
        if denom <= 1e-12:
            continue
        beta_by_date[day.date] = ((x - xm) * (y - ym)).sum() / denom
    return beta_by_date


# --------------------------------------------------------------------------
# Moteur : un jour = un trade au plus
# --------------------------------------------------------------------------
TRADE_COLS = ["date", "side", "entry_time", "exit_time", "beta", "entry_dev",
              "qty_spy", "qty_qqq", "pnl", "reason", "risk_dollar", "r_mult"]


def _spread_stats(spread: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Moyenne et ecart-type cumules depuis l'ouverture (bar 0..j inclus, comme
    le VWAP) : aucune fuite de futur, mean[j]/std[j] ne dependent que du spread
    connu a la cloture de la barre j."""
    n = len(spread)
    idx = np.arange(1, n + 1)
    cs = np.cumsum(spread)
    cs2 = np.cumsum(spread * spread)
    mean = cs / idx
    var = np.maximum(cs2 / idx - mean * mean, 0.0)
    return mean, np.sqrt(var)


def simulate_day(day: PairDay, p: Params, beta: float, bar_minutes: int = 5,
                 rng: np.random.Generator | None = None) -> dict | None:
    """
    Regles :
      1. spread[j] = log(close_SPY[j]) - beta*log(close_QQQ[j]), moyenne/ecart-type
         cumules depuis l'ouverture.
      2. Premiere barre, apres `warmup_minutes`, dont le spread s'ecarte de plus de
         `entry_z` sigma de sa propre moyenne du jour -> signal (spread trop bas =
         long spread = LONG SPY/SHORT QQQ ; spread trop haut = short spread).
      3. Entree des 2 jambes a l'ouverture de la barre suivante, plus slippage.
      4. Stop fige au moment du signal (en unites de spread). Sortie "retour" a
         `exit_z` (recalculee chaque barre a partir des stats de la barre precedente,
         comme le VWAP). Stop prioritaire sur le retour si les deux sont vrais.
      5. Toute sortie (stop, retour ou fin de journee) est executee a l'ouverture
         de la barre SUIVANTE (ou a la cloture de la derniere barre si aucune
         barre suivante), plus slippage sur les 2 jambes.

    Si `rng` est fourni, la direction est tiree au hasard (meme timing, meme
    distance de stop en unites de spread) : sert de benchmark "pile ou face".
    """
    o_spy, c_spy, o_qqq, c_qqq = day.o_spy, day.c_spy, day.o_qqq, day.c_qqq
    n = len(c_spy)
    n_warm = p.warmup_minutes // bar_minutes
    spread = np.log(np.asarray(c_spy)) - beta * np.log(np.asarray(c_qqq))
    mean, std = _spread_stats(spread)
    slip = p.slippage_ticks * TICK

    d_sig, k = 0, None
    for k in range(max(n_warm, 1), n - 1):
        if std[k] <= 1e-9:
            continue
        dev = (spread[k] - mean[k]) / std[k]
        if dev <= -p.entry_z:
            d_sig = 1     # spread trop bas -> long spread (long SPY / short QQQ)
            break
        if dev >= p.entry_z:
            d_sig = -1    # spread trop haut -> short spread
            break
    if d_sig == 0:
        return None

    e = k + 1
    spread_entry_exec = np.log(o_spy[e]) - beta * np.log(o_qqq[e])
    stop_lvl_sig = mean[k] - d_sig * p.stop_z * std[k]
    r_gross = d_sig * (spread_entry_exec - stop_lvl_sig)   # magnitude, >0 si coherent
    if r_gross <= 1e-9:
        return None                                          # stop degenere

    d = d_sig if rng is None else int(rng.choice((-1, 1)))
    stop = spread_entry_exec - d * r_gross

    # Entree : 2 jambes, dollar-neutre (100 actions SPY de reference)
    entry_spy = o_spy[e] + d * slip
    entry_qqq = o_qqq[e] - d * slip
    qty_spy = REF_SHARES_SPY
    qty_qqq = qty_spy * o_spy[e] / o_qqq[e]

    # Recherche de la sortie (evaluee sur les clotures du spread)
    trigger_j, reason = n - 1, "time"
    for j in range(e, n):
        prev = j - 1 if j > e else k
        target_lvl = mean[prev] - d * p.exit_z * std[prev]
        if d * (spread[j] - stop) <= 0:
            trigger_j, reason = j, "stop"
            break
        if d * (spread[j] - target_lvl) >= 0:
            trigger_j, reason = j, "target"
            break
        if j == n - 1:
            trigger_j, reason = j, "time"

    if trigger_j < n - 1:
        x = trigger_j + 1
        exit_spy = o_spy[x] - d * slip
        exit_qqq = o_qqq[x] + d * slip
        exit_time = day.idx[x]
    else:
        exit_spy = c_spy[n - 1] - d * slip
        exit_qqq = c_qqq[n - 1] + d * slip
        exit_time = day.idx[n - 1]

    pnl_spy = d * qty_spy * (exit_spy - entry_spy)
    pnl_qqq = -d * qty_qqq * (exit_qqq - entry_qqq)
    pnl = pnl_spy + pnl_qqq - 4 * COMMISSION_SIDE  # 2 jambes x (entree + sortie)

    risk_dollar = qty_spy * o_spy[e] * abs(r_gross)  # approximation (voir README)
    r_mult = pnl / risk_dollar if risk_dollar > 1e-9 else np.nan

    return {
        "date": day.date, "side": d, "entry_time": day.idx[e], "exit_time": exit_time,
        "beta": beta, "entry_dev": (spread[k] - mean[k]) / std[k],
        "qty_spy": qty_spy, "qty_qqq": qty_qqq, "pnl": pnl, "reason": reason,
        "risk_dollar": risk_dollar, "r_mult": r_mult,
    }


def run_backtest(days: list[PairDay], p: Params, beta_by_date: dict, bar_minutes: int = 5,
                 rng: np.random.Generator | None = None) -> pd.DataFrame:
    rows = []
    for d in days:
        beta = beta_by_date.get(d.date)
        if beta is None:
            continue
        t = simulate_day(d, p, beta, bar_minutes, rng)
        if t:
            rows.append(t)
    return pd.DataFrame(rows, columns=TRADE_COLS)


# --------------------------------------------------------------------------
# Metriques (identique aux autres strategies)
# --------------------------------------------------------------------------
def sel(trades: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    return trades[trades["date"].isin(dates)]


def metrics(trades: pd.DataFrame, dates: pd.DatetimeIndex) -> dict:
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


def random_direction_test(days, p, beta_by_date, bar_minutes, dates, n_sims=300, seed=0):
    actual = sel(run_backtest(days, p, beta_by_date, bar_minutes), dates)["pnl"].sum()
    rng = np.random.default_rng(seed)
    sims = np.array([sel(run_backtest(days, p, beta_by_date, bar_minutes, rng), dates)["pnl"].sum()
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
    ap.add_argument("--spy", default="data_spy/SPY_5min_all.csv")
    ap.add_argument("--qqq", default="data_qqq/QQQ_5min_all.csv")
    ap.add_argument("--bar-minutes", type=int, default=5)
    ap.add_argument("--oos-frac", type=float, default=0.3)
    ap.add_argument("--plot", action="store_true")
    a = ap.parse_args()

    bm = a.bar_minutes
    days, info = load_pair_bars(a.spy, a.qqq, bm)
    print(f"\nDonnees : {info['days']} jours ({info['first']} -> {info['last']}), "
          f"{info['dropped']} jours incomplets/non-alignes ecartes")
    if info["days"] < 250:
        print("ATTENTION : moins d'un an de donnees, les resultats seront peu fiables.")

    dates = pd.DatetimeIndex([d.date for d in days])
    k = int(len(dates) * (1 - a.oos_frac))
    is_dates, oos_dates = dates[:k], dates[k:]
    print(f"In-sample : {is_dates[0].date()} -> {is_dates[-1].date()} | "
          f"Hors-echantillon : {oos_dates[0].date()} -> {oos_dates[-1].date()}")

    # 1. Grille de parametres
    grid = [Params(beta_window=bw, warmup_minutes=w, entry_z=ez, exit_z=xz, stop_z=sz)
            for bw, w, ez, xz, sz in product((20, 40), (30, 60), (1.5, 2.0, 2.5), (0.25, 0.5), (3.0, 4.0))]
    beta_by_date_by_window = {bw: compute_beta_by_date(days, bw) for bw in (20, 40)}
    all_trades = {p: run_backtest(days, p, beta_by_date_by_window[p.beta_window], bm) for p in grid}

    rows = []
    for p in grid:
        m_is = metrics(sel(all_trades[p], is_dates), is_dates)
        m_oos = metrics(sel(all_trades[p], oos_dates), oos_dates)
        rows.append({"beta_w": p.beta_window, "warmup": p.warmup_minutes, "entry_z": p.entry_z,
                     "exit_z": p.exit_z, "stop_z": p.stop_z, "n_IS": m_is.get("n_trades"),
                     "exp$_IS": m_is.get("exp_$"), "PF_IS": m_is.get("profit_factor"),
                     "sharpe_IS": m_is.get("sharpe"), "sharpe_OOS": m_oos.get("sharpe"),
                     "exp$_OOS": m_oos.get("exp_$")})
    table = pd.DataFrame(rows).sort_values("sharpe_IS", ascending=False)
    print(f"\n=== 1. Grille ({len(grid)} configurations testees) ===")
    print(table.round(2).to_string(index=False))
    print(f"Le meilleur Sharpe in-sample sur {len(grid)} essais est biaise a la hausse : "
          "regarde surtout si le classement tient hors-echantillon.")

    # 2. Meilleure config in-sample
    best = max(grid, key=lambda p: (lambda s: -1e9 if pd.isna(s) else s)(
        metrics(sel(all_trades[p], is_dates), is_dates).get("sharpe", np.nan)))
    tr = all_trades[best]
    print(f"\n=== 2. Meilleure config in-sample : {best} ===")
    print("IS  :", fmt(metrics(sel(tr, is_dates), is_dates)))
    print("OOS :", fmt(metrics(sel(tr, oos_dates), oos_dates)))

    # 3. Walk-forward
    beta_bw = beta_by_date_by_window[best.beta_window]
    oos_wf, log, wf_dates = walk_forward(all_trades, dates)
    print("\n=== 3. Walk-forward (train 12 mois, test 3 mois) ===")
    if len(wf_dates):
        print("Concatenation des periodes de test :", fmt(metrics(oos_wf, wf_dates)))
        for t1, p in log:
            print(f"  test a partir de {t1} : beta_w={p.beta_window}, entry_z={p.entry_z}, "
                  f"exit_z={p.exit_z}, stop_z={p.stop_z}")
    else:
        print("Pas assez d'historique pour un walk-forward 12+3 mois.")

    # 4. Sensibilite aux couts
    print("\n=== 4. Sensibilite au slippage (meilleure config, toute la periode) ===")
    for s in (0.0, 1.0, 2.0, 3.0):
        p = Params(**{**asdict(best), "slippage_ticks": s})
        print(f"  slippage {s:.0f} tick(s)/execution :",
              fmt(metrics(run_backtest(days, p, beta_bw, bm), dates)))

    # 5. Benchmark pile ou face
    print("\n=== 5. Direction au hasard (meme timing, meme stop), hors-echantillon ===")
    actual, mu, sd, pval = random_direction_test(days, best, beta_bw, bm, oos_dates)
    print(f"  Pairs reel : {actual:.0f}$ | pile ou face : {mu:.0f}$ +/- {sd:.0f}$ | p-value = {pval:.3f}")

    # 6. Decompositions
    full = sel(tr, dates)
    print("\n=== 6. Decompositions (meilleure config, toute la periode) ===")
    print(full.groupby("side")["pnl"].agg(n="count", moyenne="mean", total="sum").round(1).rename(index={1: "long_spread", -1: "short_spread"}))
    print(full.groupby("reason")["pnl"].agg(n="count", moyenne="mean").round(1))
    print(full.groupby(full["date"].dt.year)["pnl"].agg(n="count", moyenne="mean", total="sum").round(1))

    out = "trades_pairs_best.csv"
    full.to_csv(out, index=False)
    print(f"\nTrades ecrits dans {out}")

    if a.plot:
        import matplotlib.pyplot as plt
        daily = full.groupby("date")["pnl"].sum().reindex(dates, fill_value=0.0)
        ax = daily.cumsum().plot(figsize=(10, 4), title="P&L cumule (apres couts)")
        ax.axvline(oos_dates[0], color="red", ls="--", label="debut hors-echantillon")
        ax.legend()
        plt.tight_layout()
        plt.savefig("equity_pairs_best.png", dpi=120)
        print("Courbe ecrite dans equity_pairs_best.png")


if __name__ == "__main__":
    main()
