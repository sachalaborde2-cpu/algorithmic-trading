"""
Backtest d'un Squeeze de volatilite (Bollinger) intraday sur futures indice
(MES / ES) et ETF (SPY / QQQ).

Idee
----
Des bandes de Bollinger (moyenne mobile +/- k * ecart-type, sur une fenetre
glissante de `bb_period` clotures) se resserrent (bandwidth = (bande haute -
bande basse) / moyenne, au plus bas de ses `squeeze_pctl` derniers percentiles
sur `squeeze_lookback` barres) quand la volatilite se comprime. La sortie de ce
squeeze -- une cloture qui depasse une des deux bandes -- est prise comme signal
de breakout dans le sens de la sortie : on parie que la compression de
volatilite precede un mouvement directionnel.

Conventions (identiques a l'ORB / VWAP reversion / pullback, pour rester comparables)
---------------------------------------------------------------------------------------
- Barres IB : l'horodatage est le DEBUT de la barre.
- Tout est converti en heure de New York.
- Le signal est calcule a la CLOTURE d'une barre (bandes/ATR ne dependent que des
  barres 0..i), l'ordre est execute a l'OUVERTURE de la barre suivante + slippage.
  Stop/target figes au moment du signal (distances ATR calculees comme des
  MAGNITUDES avant application de la direction, pour rester valides meme quand la
  direction est tiree au hasard dans le test placebo).
- Plusieurs trades par jour sont possibles (plusieurs squeezes), plafonnes a
  `max_trades_per_day`, jamais de position simultanee. Toujours flat avant la
  cloture (16:00 NY).

Usage
-----
    python vol_squeeze_backtest.py data/MES_5min_all.csv --instrument MES

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


# Memes valeurs que vwap_reversion/pullback_trend : actions/ETF a 100 actions de
# reference (comparable a 1 contrat MES en capital engage).
INSTRUMENTS = {
    "MES": Instrument(tick=0.25, point_value=5.0, commission_side=0.85),
    "ES": Instrument(tick=0.25, point_value=50.0, commission_side=2.10),
    "SPY": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "QQQ": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
}


@dataclass(frozen=True)
class Params:
    bb_period: int = 20
    bb_k: float = 2.0
    squeeze_lookback: int = 20   # fenetre passee sur laquelle on juge le bandwidth "resserre"
    squeeze_pctl: float = 20.0   # percentile : bandwidth actuel parmi les plus bas X% recents
    atr_period: int = 14
    atr_stop_mult: float = 1.0
    atr_target_mult: float = 2.0
    max_trades_per_day: int = 3
    slippage_ticks: float = 1.0


# --------------------------------------------------------------------------
# Donnees (identique a l'ORB/VWAP/pullback : meme loader, memes conventions)
# --------------------------------------------------------------------------
@dataclass
class Day:
    date: pd.Timestamp
    idx: pd.DatetimeIndex
    o: list
    h: list
    l: list
    c: list
    v: list


def load_bars(path: str, bar_minutes: int = 5) -> tuple[list[Day], dict]:
    """Charge le CSV, passe en heure de NY, garde la seance reguliere complete."""
    df = pd.read_csv(path)
    df["ts"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_convert(TZ)
    df["date"] = df["ts"].dt.tz_localize(None).dt.normalize()

    df = df.set_index("ts").between_time(SESSION_START, "15:59").reset_index()

    if "contract" in df.columns:
        vol = df.groupby(["date", "contract"], as_index=False)["volume"].sum()
        best = vol.sort_values("volume").drop_duplicates("date", keep="last")
        df = df.merge(best[["date", "contract"]], on=["date", "contract"], how="inner")

    df = df.sort_values("ts").drop_duplicates("ts").set_index("ts")

    expected = SESSION_MINUTES // bar_minutes
    days, dropped = [], 0
    for date, g in df.groupby("date"):
        if len(g) != expected or g.index[0].strftime("%H:%M") != SESSION_START:
            dropped += 1
            continue
        days.append(Day(date, g.index, g["open"].tolist(), g["high"].tolist(),
                        g["low"].tolist(), g["close"].tolist(), g["volume"].tolist()))
    info = {"days": len(days), "dropped": dropped,
            "first": days[0].date.date() if days else None,
            "last": days[-1].date.date() if days else None}
    return days, info


# --------------------------------------------------------------------------
# Indicateurs causaux (bar par bar, aucune fuite de futur)
# --------------------------------------------------------------------------
def bollinger(c: list, period: int, k: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Bandes de Bollinger sur fenetre glissante (expanding tant qu'on n'a pas
    `period` barres). mean[i]/std[i]/bandwidth[i] ne dependent que de c[0..i]."""
    n = len(c)
    c = np.asarray(c, dtype=float)
    mean = np.empty(n)
    std = np.empty(n)
    for i in range(n):
        lo = max(0, i - period + 1)
        window = c[lo:i + 1]
        mean[i] = window.mean()
        std[i] = window.std()
    upper = mean + k * std
    lower = mean - k * std
    bandwidth = np.where(mean != 0, (upper - lower) / np.abs(mean), 0.0)
    return mean, upper, lower, bandwidth


def atr_series(o: list, h: list, l: list, c: list, period: int) -> np.ndarray:
    """True range cumule en moyenne mobile depuis l'ouverture de seance (identique
    a pullback_backtest.py). atr[i] ne depend que des barres 0..i."""
    n = len(c)
    tr = np.empty(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    atr = np.empty(n)
    for i in range(n):
        lo = max(0, i - period + 1)
        atr[i] = tr[lo:i + 1].mean()
    return atr


def squeeze_flags(bandwidth: np.ndarray, lookback: int, pctl: float) -> np.ndarray:
    """squeeze[i] = True si bandwidth[i] est au plus bas percentile `pctl` des
    `lookback` bandwidth PRECEDENTS (bandwidth[i-lookback:i], jamais i lui-meme
    ni le futur). Necessite i >= lookback pour etre evalue."""
    n = len(bandwidth)
    out = np.zeros(n, dtype=bool)
    for i in range(lookback, n):
        past = bandwidth[i - lookback:i]
        threshold = np.percentile(past, pctl)
        out[i] = bandwidth[i] <= threshold
    return out


# --------------------------------------------------------------------------
# Moteur : un jour = 0 a max_trades_per_day trades
# --------------------------------------------------------------------------
TRADE_COLS = ["date", "side", "entry_time", "exit_time", "entry", "exit",
              "pts", "risk_pts", "r_mult", "pnl", "reason"]


def simulate_day(day: Day, p: Params, inst: Instrument, bar_minutes: int = 5,
                 rng: np.random.Generator | None = None) -> list[dict]:
    """
    Regles :
      1. Bandes de Bollinger (fenetre glissante `bb_period`) et bandwidth calcules
         a chaque cloture, ATR cumule depuis l'ouverture -- aucune donnee future.
      2. Squeeze detecte a la barre i si bandwidth[i] est au plus bas
         `squeeze_pctl` percentile des `squeeze_lookback` bandwidth precedents.
      3. Une fois un squeeze detecte (etat "en attente de breakout"), le premier
         signal se declenche a la cloture qui depasse la bande haute (LONG) ou la
         bande basse (SHORT). L'etat squeeze est alors reinitialise.
      4. Entree a l'ouverture de la barre suivante, plus slippage.
      5. Stop/target figes au signal comme des MAGNITUDES (distance = mult * ATR
         au moment du signal), appliques ensuite selon la direction reelle du
         trade (utile pour le test placebo a direction aleatoire).
      6. Si stop et target sont touches dans la meme barre, le stop l'emporte.
         Un gap qui traverse le stop des l'ouverture sort au prix d'ouverture.
      7. Sortie forcee a la cloture de la derniere barre de la seance.
      8. Au plus `max_trades_per_day` trades, jamais de position simultanee.

    Si `rng` est fourni, la direction de chaque trade est tiree au hasard (meme
    timing d'entree, meme distance de stop) : sert de benchmark "pile ou face".
    """
    o, h, l, c = day.o, day.h, day.l, day.c
    n = len(c)
    _, upper, lower, bandwidth = bollinger(c, p.bb_period, p.bb_k)
    atr = atr_series(o, h, l, c, p.atr_period)
    sq = squeeze_flags(bandwidth, p.squeeze_lookback, p.squeeze_pctl)
    slip = p.slippage_ticks * inst.tick

    trades: list[dict] = []
    i = p.squeeze_lookback
    armed = False

    while i < n - 1 and len(trades) < p.max_trades_per_day:
        if sq[i]:
            armed = True
        if armed and c[i] > upper[i]:
            armed = False
            i = _open_trade(trades, o, h, l, c, atr, i, n, 1, p, inst, slip, day, rng)
            continue
        if armed and c[i] < lower[i]:
            armed = False
            i = _open_trade(trades, o, h, l, c, atr, i, n, -1, p, inst, slip, day, rng)
            continue
        i += 1

    return trades


def _open_trade(trades, o, h, l, c, atr, k, n, d_sig, p, inst, slip, day, rng) -> int:
    """Ouvre un trade signale a la barre k (entree a l'ouverture de k+1). Renvoie
    l'indice de barre a partir duquel reprendre la recherche du prochain signal
    (= barre de sortie, jamais avant, pour interdire toute position simultanee)."""
    e = k + 1
    if e >= n:
        return n
    signal_atr = atr[k]
    r_gross = p.atr_stop_mult * signal_atr
    target_dist = p.atr_target_mult * signal_atr
    if r_gross <= inst.tick or target_dist <= inst.tick:
        return e                                # distances degenerees, pas de trade

    d = d_sig if rng is None else int(rng.choice((-1, 1)))
    entry = o[e] + d * slip
    stop = entry - d * r_gross
    target = entry + d * target_dist
    risk = d * (entry - stop)

    exit_px, reason, x = None, "time", n - 1
    for j in range(e, n):
        adverse = l[j] if d == 1 else h[j]
        favorable = h[j] if d == 1 else l[j]
        if j > e and d * (o[j] - stop) <= 0:               # gap a travers le stop
            exit_px, reason, x = o[j] - d * slip, "stop_gap", j
            break
        if d * (adverse - stop) <= 0:                       # stop touche
            exit_px, reason, x = stop - d * slip, "stop", j
            break
        if d * (favorable - target) >= 0:                   # target touche
            exit_px, reason, x = target, "target", j
            break
        if j == n - 1:                                       # cloture de seance
            exit_px, reason, x = c[j] - d * slip, "time", j

    pts = d * (exit_px - entry)
    trades.append({
        "date": day.date, "side": d, "entry_time": day.idx[e], "exit_time": day.idx[x],
        "entry": entry, "exit": exit_px, "pts": pts, "risk_pts": risk,
        "r_mult": pts / risk,
        "pnl": pts * inst.point_value - 2 * inst.commission_side,
        "reason": reason,
    })
    return x


def run_backtest(days: list[Day], p: Params, inst: Instrument, bar_minutes: int = 5,
                 rng: np.random.Generator | None = None) -> pd.DataFrame:
    rows = [t for d in days for t in simulate_day(d, p, inst, bar_minutes, rng)]
    return pd.DataFrame(rows, columns=TRADE_COLS)


# --------------------------------------------------------------------------
# Metriques (identique a l'ORB/VWAP/pullback)
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
# Tests de robustesse (identique a l'ORB/VWAP/pullback)
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


def random_direction_test(days, p, inst, bar_minutes, dates, n_sims=300, seed=0):
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
    ap.add_argument("--oos-frac", type=float, default=0.3)
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
    grid = [Params(bb_period=bp, bb_k=bk, squeeze_lookback=sl, squeeze_pctl=sp,
                   atr_stop_mult=sm, atr_target_mult=tm)
            for bp, bk, sl, sp, sm, tm in product(
                (14, 20), (1.5, 2.0), (20, 40), (15.0, 25.0), (0.5, 1.0), (1.5, 2.5))]
    all_trades = {p: run_backtest(days, p, inst, bm) for p in grid}

    rows = []
    for p in grid:
        m_is = metrics(sel(all_trades[p], is_dates), is_dates)
        m_oos = metrics(sel(all_trades[p], oos_dates), oos_dates)
        rows.append({"bb_period": p.bb_period, "bb_k": p.bb_k, "lookback": p.squeeze_lookback,
                     "pctl": p.squeeze_pctl, "stop_atr": p.atr_stop_mult, "target_atr": p.atr_target_mult,
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
            print(f"  test a partir de {t1} : bb_period={p.bb_period}, bb_k={p.bb_k}, "
                  f"lookback={p.squeeze_lookback}, pctl={p.squeeze_pctl}, "
                  f"stop={p.atr_stop_mult}, target={p.atr_target_mult}")
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
    print(f"  Squeeze reel : {actual:.0f}$ | pile ou face : {mu:.0f}$ +/- {sd:.0f}$ | p-value = {pval:.3f}")

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
        ax = daily.cumsum().plot(figsize=(10, 4), title="P&L cumule (1 contrat/100 actions, apres couts)")
        ax.axvline(oos_dates[0], color="red", ls="--", label="debut hors-echantillon")
        ax.legend()
        plt.tight_layout()
        plt.savefig(f"equity_{a.instrument}_best.png", dpi=120)
        print(f"Courbe ecrite dans equity_{a.instrument}_best.png")


if __name__ == "__main__":
    main()
