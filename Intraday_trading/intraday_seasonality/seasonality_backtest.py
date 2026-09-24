"""
Etude de saisonnalite intraday + variante backtestable, sur MES/SPY/QQQ.

Idee
----
Contrairement aux strategies precedentes (signal bar-par-bar), on etudie ici
si certaines tranches horaires fixes de la seance (09:30-10:00, 10:00-10:30,
..., 15:30-16:00, avec des tranches de `slot_minutes` = 30 minutes -> 13
tranches) ont un rendement moyen directionnel statistiquement robuste sur la
periode in-sample, ET qui persiste hors-echantillon. Avec 13 tranches testees,
le risque de data snooping (multiple testing) est important : il faut un
t-stat nettement significatif en IS, PUIS verifier qu'il tient en OOS -- pas
seulement retenir "la meilleure des 13" et s'arreter la.

Deux volets :
  1. Analyse descriptive : rendement moyen par tranche (log-return open->close
     de la tranche), t-stat par tranche, sur IS puis sur OOS (meme tranche,
     jamais re-choisie sur OOS).
  2. Variante backtestable : on trade la tranche choisie en IS (deja
     directionnelle en IS) avec un stop/target optionnel en multiple d'ATR
     quotidien (ATR calcule sur les jours STRICTEMENT precedents), et on lui
     applique le meme protocole que les autres strategies (grille sur
     stop/target, IS/OOS, walk-forward avec re-selection de la tranche sur
     la fenetre d'entrainement uniquement, test placebo).

Conventions
-----------
- Session reguliere 09:30-16:00 NY (390 minutes), tranches de 30 minutes ->
  13 tranches ; jours incomplets ecartes.
- Rendement d'une tranche = log(clot ure de la derniere barre de la tranche)
  - log(ouverture de la premiere barre de la tranche) : ne depend que des
  barres de cette tranche, jamais d'une tranche future.
- Variante backtestable : entree a l'ouverture de la tranche (+ slippage),
  sortie a la clôture de la tranche (+ slippage), sauf stop touche avant (sur
  les clôtures des barres de la tranche) auquel cas sortie a l'ouverture de la
  barre suivante (+ slippage). ATR quotidien (max-min de la seance) moyenne
  sur les `atr_lookback` jours precedents, jamais le jour meme.
- Selection de la tranche a trader : toujours sur les dates d'ENTRAINEMENT
  uniquement (IS pour le split simple, fenetre train pour le walk-forward) --
  jamais sur les dates de test.

Usage
-----
    python seasonality_backtest.py --csv data/MES_5min_all.csv --symbol MES
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from itertools import product

import numpy as np
import pandas as pd
from scipy import stats

TZ = "America/New_York"
SESSION_START = "09:30"
SESSION_MINUTES = 390
SLOT_MINUTES = 30
N_SLOTS = SESSION_MINUTES // SLOT_MINUTES  # 13


@dataclass(frozen=True)
class Instrument:
    tick: float
    point_value: float
    commission_side: float


INSTRUMENTS = {
    "MES": Instrument(tick=0.25, point_value=5.0, commission_side=0.85),
    "SPY": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "QQQ": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
}


@dataclass
class Day:
    date: pd.Timestamp
    idx: pd.DatetimeIndex
    o: list
    h: list
    l: list
    c: list


def load_bars(path: str, bar_minutes: int = 5) -> tuple[list[Day], dict]:
    df = pd.read_csv(path)
    df["ts"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_convert(TZ)
    df["date"] = df["ts"].dt.tz_localize(None).dt.normalize()
    df = df.set_index("ts").between_time(SESSION_START, "15:59").sort_index()
    df = df[~df.index.duplicated(keep="first")]

    expected = SESSION_MINUTES // bar_minutes
    days, dropped = [], 0
    for date, g in df.groupby("date"):
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
# Volet 1 : rendements par tranche (analyse descriptive)
# --------------------------------------------------------------------------
def slot_returns(day: Day, slot_minutes: int, bar_minutes: int = 5) -> np.ndarray:
    """Rendement log open->close de chaque tranche de `slot_minutes` de la
    seance. La tranche s ne depend que des barres qui lui appartiennent
    (aucune fuite de tranche future ou passee)."""
    bars_per_slot = slot_minutes // bar_minutes
    n_slots = len(day.c) // bars_per_slot
    r = np.empty(n_slots)
    for s in range(n_slots):
        i0 = s * bars_per_slot
        i1 = i0 + bars_per_slot - 1
        r[s] = np.log(day.c[i1] / day.o[i0])
    return r


def slot_return_matrix(days: list[Day], slot_minutes: int, bar_minutes: int = 5) -> pd.DataFrame:
    """Une ligne par jour, une colonne par tranche."""
    rows = [slot_returns(d, slot_minutes, bar_minutes) for d in days]
    dates = [d.date for d in days]
    return pd.DataFrame(rows, index=dates)


def slot_stats(matrix: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    sub = matrix.loc[matrix.index.isin(dates)]
    mean = sub.mean()
    std = sub.std()
    n = sub.count()
    t = mean / std * np.sqrt(n)
    pval = 2 * (1 - stats.t.cdf(np.abs(t), df=n - 1))
    return pd.DataFrame({"n": n, "mean_bp": mean * 1e4, "std_bp": std * 1e4, "t_stat": t, "p_value": pval})


def select_best_slot(matrix: pd.DataFrame, train_dates: pd.DatetimeIndex) -> tuple[int, int]:
    """Choisit la tranche au |t-stat| le plus eleve sur les dates
    d'ENTRAINEMENT uniquement. Retourne (indice de tranche, direction
    +1/-1 selon le signe du rendement moyen en entrainement)."""
    st = slot_stats(matrix, train_dates)
    best = st["t_stat"].abs().idxmax()
    direction = 1 if st.loc[best, "mean_bp"] > 0 else -1
    return int(best), int(direction)


# --------------------------------------------------------------------------
# Volet 2 : variante backtestable (trade la tranche choisie)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Params:
    slot_minutes: int = 30
    chosen_slot: int = 0
    direction: int = 1
    atr_lookback: int = 20
    atr_stop_mult: float | None = None
    atr_target_mult: float | None = None
    slippage_ticks: float = 1.0


TRADE_COLS = ["date", "side", "entry_time", "exit_time", "pnl", "reason", "risk_dollar", "r_mult"]


def compute_daily_atr(days: list[Day], lookback: int) -> dict:
    """ATR quotidien simplifie (max-min de la seance), moyenne sur les
    `lookback` jours STRICTEMENT precedents (jamais le jour meme)."""
    ranges = np.array([max(d.h) - min(d.l) for d in days])
    atr_by_date = {}
    for i, day in enumerate(days):
        if i < lookback:
            continue
        atr_by_date[day.date] = ranges[i - lookback:i].mean()
    return atr_by_date


def simulate_day(day: Day, p: Params, atr: float | None, inst: Instrument,
                 bar_minutes: int = 5, rng: np.random.Generator | None = None) -> dict | None:
    bars_per_slot = p.slot_minutes // bar_minutes
    i0 = p.chosen_slot * bars_per_slot
    i1 = i0 + bars_per_slot - 1
    if i1 >= len(day.c):
        return None

    d = p.direction if rng is None else int(rng.choice((-1, 1)))
    slip = p.slippage_ticks * inst.tick

    entry_px = day.o[i0] + d * slip
    entry_time = day.idx[i0]

    stop_px = None
    if p.atr_stop_mult is not None and atr is not None:
        stop_px = entry_px - d * p.atr_stop_mult * atr

    exit_px, exit_time, reason = None, None, "time"
    for j in range(i0, i1 + 1):
        if stop_px is not None and d * (day.c[j] - stop_px) <= 0:
            nxt = j + 1
            if nxt <= i1:
                exit_px = day.o[nxt] - d * slip
                exit_time = day.idx[nxt]
            else:
                exit_px = day.c[j] - d * slip
                exit_time = day.idx[j]
            reason = "stop"
            break
        if p.atr_target_mult is not None and atr is not None:
            target_px = entry_px + d * p.atr_target_mult * atr
            if d * (day.c[j] - target_px) >= 0:
                nxt = j + 1
                if nxt <= i1:
                    exit_px = day.o[nxt] - d * slip
                    exit_time = day.idx[nxt]
                else:
                    exit_px = day.c[j] - d * slip
                    exit_time = day.idx[j]
                reason = "target"
                break

    if exit_px is None:
        exit_px = day.c[i1] - d * slip
        exit_time = day.idx[i1]
        reason = "time"

    pnl = d * inst.point_value * (exit_px - entry_px) - 2 * inst.commission_side
    risk_dollar = inst.point_value * p.atr_stop_mult * atr if (p.atr_stop_mult and atr) else abs(pnl) or 1.0
    r_mult = pnl / risk_dollar if risk_dollar > 1e-9 else np.nan

    return {"date": day.date, "side": d, "entry_time": entry_time, "exit_time": exit_time,
            "pnl": pnl, "reason": reason, "risk_dollar": risk_dollar, "r_mult": r_mult}


def run_backtest(days: list[Day], p: Params, atr_by_date: dict, inst: Instrument,
                 bar_minutes: int = 5, rng: np.random.Generator | None = None) -> pd.DataFrame:
    rows = []
    for d in days:
        t = simulate_day(d, p, atr_by_date.get(d.date), inst, bar_minutes, rng)
        if t:
            rows.append(t)
    return pd.DataFrame(rows, columns=TRADE_COLS)


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


def walk_forward_seasonality(days: list[Day], matrix: pd.DataFrame, atr_by_date: dict, inst: Instrument,
                             bar_minutes: int, dates: pd.DatetimeIndex, stop_grid: list,
                             train_months: int = 12, test_months: int = 3) -> tuple[pd.DataFrame, list]:
    """Walk-forward avec RE-SELECTION de la tranche a chaque fenetre
    d'entrainement (jamais sur les dates de test)."""
    parts, log = [], []
    t0 = dates.min()
    while True:
        t1 = t0 + pd.DateOffset(months=train_months)
        t2 = t1 + pd.DateOffset(months=test_months)
        train = dates[(dates >= t0) & (dates < t1)]
        test = dates[(dates >= t1) & (dates < t2)]
        if len(test) == 0:
            break
        slot, direction = select_best_slot(matrix, train)

        def score(sg):
            p = Params(slot_minutes=SLOT_MINUTES, chosen_slot=slot, direction=direction,
                      atr_stop_mult=sg[0], atr_target_mult=sg[1])
            tr = run_backtest(days, p, atr_by_date, inst, bar_minutes)
            s = metrics(sel(tr, train), train).get("sharpe", np.nan)
            return -1e9 if pd.isna(s) else s

        best_sg = max(stop_grid, key=score)
        p = Params(slot_minutes=SLOT_MINUTES, chosen_slot=slot, direction=direction,
                  atr_stop_mult=best_sg[0], atr_target_mult=best_sg[1])
        tr = run_backtest(days, p, atr_by_date, inst, bar_minutes)
        parts.append(sel(tr, test))
        log.append((t1.date(), slot, direction, best_sg))
        t0 = t0 + pd.DateOffset(months=test_months)
    oos = pd.concat(parts) if parts else pd.DataFrame(columns=TRADE_COLS)
    test_dates = dates[dates >= (dates.min() + pd.DateOffset(months=train_months))]
    return oos, log, test_dates


def random_direction_test(days, p, atr_by_date, inst, bar_minutes, dates, n_sims=300, seed=0):
    actual = sel(run_backtest(days, p, atr_by_date, inst, bar_minutes), dates)["pnl"].sum()
    rng = np.random.default_rng(seed)
    sims = np.array([sel(run_backtest(days, p, atr_by_date, inst, bar_minutes, rng), dates)["pnl"].sum()
                     for _ in range(n_sims)])
    pval = (np.sum(sims >= actual) + 1) / (n_sims + 1)
    return actual, sims.mean(), sims.std(), pval


def fmt(d: dict) -> str:
    keys = ["n_trades", "win_rate", "exp_$", "exp_R", "profit_factor",
            "total_$", "sharpe", "t_stat", "max_dd_$"]
    return "  ".join(f"{k}={d[k]:.2f}" if k in d and k != "n_trades" else f"{k}={d.get(k)}"
                     for k in keys)


def slot_label(idx: int, slot_minutes: int = SLOT_MINUTES) -> str:
    start = pd.Timestamp("2000-01-01 09:30") + pd.Timedelta(minutes=idx * slot_minutes)
    end = start + pd.Timedelta(minutes=slot_minutes)
    return f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--symbol", required=True, choices=list(INSTRUMENTS))
    ap.add_argument("--bar-minutes", type=int, default=5)
    ap.add_argument("--oos-frac", type=float, default=0.3)
    a = ap.parse_args()

    bm = a.bar_minutes
    inst = INSTRUMENTS[a.symbol]
    days, info = load_bars(a.csv, bm)
    print(f"\nDonnees {a.symbol} : {info['days']} jours ({info['first']} -> {info['last']}), "
          f"{info['dropped']} jours incomplets ecartes")

    dates = pd.DatetimeIndex([d.date for d in days])
    k = int(len(dates) * (1 - a.oos_frac))
    is_dates, oos_dates = dates[:k], dates[k:]
    print(f"In-sample : {is_dates[0].date()} -> {is_dates[-1].date()} | "
          f"Hors-echantillon : {oos_dates[0].date()} -> {oos_dates[-1].date()}")

    matrix = slot_return_matrix(days, SLOT_MINUTES, bm)

    # 1. Analyse descriptive : rendement moyen par tranche, IS puis OOS (meme tranches)
    st_is = slot_stats(matrix, is_dates)
    st_oos = slot_stats(matrix, oos_dates)
    table = pd.DataFrame({
        "tranche": [slot_label(i) for i in range(N_SLOTS)],
        "mean_bp_IS": st_is["mean_bp"].round(2).values,
        "t_stat_IS": st_is["t_stat"].round(2).values,
        "p_value_IS": st_is["p_value"].round(3).values,
        "mean_bp_OOS": st_oos["mean_bp"].round(2).values,
        "t_stat_OOS": st_oos["t_stat"].round(2).values,
    }).sort_values("t_stat_IS", key=lambda s: s.abs(), ascending=False)
    print(f"\n=== 1. Rendement moyen par tranche de {SLOT_MINUTES} min ({N_SLOTS} tranches) ===")
    print(table.to_string(index=False))
    print("Avec 13 tranches testees, exiger |t-stat IS| nettement > 2 (Bonferroni : "
          f"seuil ajuste ~{stats.norm.isf(0.05 / (2 * N_SLOTS)):.2f} pour un test bilateral a 5%) "
          "ET une significativite qui persiste en OOS avant de conclure a un edge.")

    best_slot_is, direction_is = select_best_slot(matrix, is_dates)
    print(f"\nTranche la plus significative en IS : {slot_label(best_slot_is)} "
          f"(direction {'+1 (long)' if direction_is == 1 else '-1 (short)'})")

    # 2. Variante backtestable sur la tranche choisie en IS
    atr_by_date = compute_daily_atr(days, lookback=20)
    stop_grid = [(None, None), (1.0, 1.5), (1.0, 2.0), (1.5, 2.0), (1.5, None), (1.0, None)]
    rows = []
    for sm, tm in stop_grid:
        p = Params(slot_minutes=SLOT_MINUTES, chosen_slot=best_slot_is, direction=direction_is,
                  atr_stop_mult=sm, atr_target_mult=tm)
        tr = run_backtest(days, p, atr_by_date, inst, bm)
        m_is = metrics(sel(tr, is_dates), is_dates)
        m_oos = metrics(sel(tr, oos_dates), oos_dates)
        rows.append({"stop_atr": sm, "target_atr": tm, "n_IS": m_is.get("n_trades"),
                     "sharpe_IS": m_is.get("sharpe"), "sharpe_OOS": m_oos.get("sharpe"),
                     "exp$_IS": m_is.get("exp_$"), "exp$_OOS": m_oos.get("exp_$")})
    grid_table = pd.DataFrame(rows).sort_values("sharpe_IS", ascending=False)
    print(f"\n=== 2. Grille stop/target ATR sur la tranche {slot_label(best_slot_is)} ===")
    print(grid_table.round(3).to_string(index=False))

    best_row = grid_table.iloc[0]
    best_p = Params(slot_minutes=SLOT_MINUTES, chosen_slot=best_slot_is, direction=direction_is,
                    atr_stop_mult=best_row["stop_atr"], atr_target_mult=best_row["target_atr"])
    tr_best = run_backtest(days, best_p, atr_by_date, inst, bm)
    print(f"\n=== 3. Meilleure config : {best_p} ===")
    print("IS  :", fmt(metrics(sel(tr_best, is_dates), is_dates)))
    print("OOS :", fmt(metrics(sel(tr_best, oos_dates), oos_dates)))

    # 4. Walk-forward avec re-selection de la tranche sur la fenetre d'entrainement
    oos_wf, log, wf_dates = walk_forward_seasonality(days, matrix, atr_by_date, inst, bm, dates, stop_grid)
    print("\n=== 4. Walk-forward (train 12 mois, test 3 mois, tranche re-choisie a chaque fenetre) ===")
    if len(wf_dates):
        print("Concatenation des periodes de test :", fmt(metrics(oos_wf, wf_dates)))
        for t1, slot, direction, sg in log:
            print(f"  test a partir de {t1} : tranche={slot_label(slot)}, "
                  f"direction={'+1' if direction == 1 else '-1'}, stop/target_atr={sg}")
    else:
        print("Pas assez d'historique pour un walk-forward 12+3 mois.")

    # 5. Sensibilite au slippage
    print("\n=== 5. Sensibilite au slippage (meilleure config, toute la periode) ===")
    for s in (0.0, 1.0, 2.0, 3.0):
        p = Params(**{**best_p.__dict__, "slippage_ticks": s})
        print(f"  slippage {s:.0f} tick(s) :", fmt(metrics(run_backtest(days, p, atr_by_date, inst, bm), dates)))

    # 6. Test placebo
    print("\n=== 6. Direction au hasard (meme tranche, meme timing), hors-echantillon ===")
    actual, mu, sd, pval = random_direction_test(days, best_p, atr_by_date, inst, bm, oos_dates)
    print(f"  Saisonnalite reelle : {actual:.0f}$ | pile ou face : {mu:.0f}$ +/- {sd:.0f}$ | p-value = {pval:.3f}")

    full = sel(tr_best, dates)
    out = f"trades_{a.symbol}_best.csv"
    full.to_csv(out, index=False)
    print(f"\nTrades ecrits dans {out}")


if __name__ == "__main__":
    main()
