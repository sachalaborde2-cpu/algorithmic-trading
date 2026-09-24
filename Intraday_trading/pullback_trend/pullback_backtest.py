"""
Backtest d'un Pullback en tendance (trend pullback) intraday sur futures indice
(MES / ES) et ETF (SPY / QQQ).

Idee
----
Contrairement au VWAP reversion (parie sur un retournement) et a l'ORB (parie sur
la continuation de la premiere sortie de range), le pullback en tendance essaie de
capter une tendance intraday deja etablie, en entrant sur ses creux temporaires :
  - Tendance haussiere (EMA rapide > EMA lente depuis au moins `min_trend_bars`
    barres) : si le prix "pullback" sous l'EMA rapide puis y revient (cloture qui
    repasse au-dessus), on achete -> on parie que la tendance reprend.
  - Tendance baissiere : symetrique, on vend a decouvert sur un pullback qui
    echoue a percer l'EMA rapide vers le haut.

Conventions (identiques a l'ORB et au VWAP reversion, pour rester comparables)
-------------------------------------------------------------------------------
- Barres IB : l'horodatage est le DEBUT de la barre.
- Tout est converti en heure de New York.
- Le signal est calcule a la CLOTURE d'une barre, l'ordre est execute a
  l'OUVERTURE de la barre suivante. Aucune information future n'est utilisee :
  EMA/ATR ne dependent que des barres 0..j ; le niveau de stop/target est fige au
  moment du signal ; la sortie "rupture de tendance" compare les EMA de la barre
  PRECEDENTE (jamais celle en cours).
- Plusieurs trades par jour sont possibles (plusieurs pullbacks), plafonnes a
  `max_trades_per_day`, jamais de position simultanee. Toujours flat avant la
  cloture (16:00 NY).

Usage
-----
    python pullback_backtest.py data/MES_5min_all.csv --instrument MES

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


# Memes valeurs que vwap_reversion/vwap_backtest.py : actions/ETF a 100 actions
# de reference (comparable a 1 contrat MES en capital engage), pour eviter le
# biais deja identifie (a 1 action, le mouvement de prix est ecrase par le
# minimum de commission).
INSTRUMENTS = {
    "MES": Instrument(tick=0.25, point_value=5.0, commission_side=0.85),
    "ES": Instrument(tick=0.25, point_value=50.0, commission_side=2.10),
    "SPY": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "QQQ": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
}


@dataclass(frozen=True)
class Params:
    ema_fast: int = 9
    ema_slow: int = 21
    min_trend_bars: int = 3      # nb de barres consecutives EMA rapide/lente ordonnees pour valider une tendance
    atr_period: int = 14
    atr_stop_mult: float = 1.0   # buffer de stop au-dela du plus bas/haut du pullback, en ATR
    atr_target_mult: float = 2.0
    max_trades_per_day: int = 3
    slippage_ticks: float = 1.0


# --------------------------------------------------------------------------
# Donnees (identique a l'ORB/VWAP : meme loader, memes conventions de seance)
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

    # Seance reguliere uniquement : barres qui demarrent entre 09:30 et 15:59 (heure de NY)
    df = df.set_index("ts").between_time(SESSION_START, "15:59").reset_index()

    # Un seul contrat par jour : celui qui a le plus de volume pendant la seance
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
def ema_series(c: list, period: int) -> np.ndarray:
    """EMA classique, amorcee a la premiere cloture (ema[0] = c[0]).
    ema[i] ne depend que de c[0..i]."""
    alpha = 2.0 / (period + 1)
    out = np.empty(len(c))
    out[0] = c[0]
    for i in range(1, len(c)):
        out[i] = alpha * c[i] + (1 - alpha) * out[i - 1]
    return out


def atr_series(o: list, h: list, l: list, c: list, period: int) -> np.ndarray:
    """True range cumule en moyenne mobile simple depuis l'ouverture de seance
    (amorce a TR[0] = h[0]-l[0], pas de cloture veille disponible en intraday-only).
    atr[i] ne depend que des barres 0..i."""
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


# --------------------------------------------------------------------------
# Moteur : un jour = 0 a max_trades_per_day trades
# --------------------------------------------------------------------------
TRADE_COLS = ["date", "side", "entry_time", "exit_time", "entry", "exit",
              "pts", "risk_pts", "r_mult", "pnl", "reason"]


def simulate_day(day: Day, p: Params, inst: Instrument, bar_minutes: int = 5,
                 rng: np.random.Generator | None = None) -> list[dict]:
    """
    Regles :
      1. EMA rapide/lente et ATR cumules depuis l'ouverture (aucune donnee future).
      2. Tendance haussiere validee des que ema_fast > ema_slow sur >= min_trend_bars
         barres consecutives ; baissiere si l'inverse. Tendance "aucune" sinon.
      3. En tendance haussiere : un pullback s'ouvre a la premiere cloture sous
         ema_fast, se poursuit tant que la cloture reste sous ema_fast (on met a
         jour le plus bas du pullback), et se conclut en signal LONG a la premiere
         cloture qui repasse au-dessus de ema_fast. Symetrique pour le SHORT en
         tendance baissiere.
      4. Entree a l'ouverture de la barre suivante, plus slippage.
      5. Stop fige au signal : plus bas (long) / plus haut (short) du pullback,
         moins/plus atr_stop_mult * ATR au moment du signal.
      6. Target fige au signal : entry +/- atr_target_mult * ATR au moment du signal.
      7. Sortie "rupture de tendance" : si sur la barre PRECEDENTE (j-1) la tendance
         s'est inversee (ema_fast <= ema_slow pour un long, >= pour un short), sortie
         a l'ouverture de la barre j -- jamais sur la base de la barre en cours.
      8. Si stop et target sont touches dans la meme barre, le stop l'emporte.
      9. Sortie forcee a la cloture de la derniere barre de la seance.
      10. Au plus `max_trades_per_day` trades, jamais de position simultanee
          (on reprend la recherche de signal seulement apres avoir cloture le
          trade precedent).

    Si `rng` est fourni, la direction de chaque trade est tiree au hasard (meme
    timing d'entree, meme distance de stop) : sert de benchmark "pile ou face".
    """
    o, h, l, c, v = day.o, day.h, day.l, day.c, day.v
    n = len(c)
    ema_f = ema_series(c, p.ema_fast)
    ema_s = ema_series(c, p.ema_slow)
    atr = atr_series(o, h, l, c, p.atr_period)
    slip = p.slippage_ticks * inst.tick

    trades: list[dict] = []
    i = 0
    pullback_dir = 0     # +1 = pullback sous ema_fast en tendance haussiere, -1 = symetrique
    pullback_extreme = None
    trend_run = 0        # nb de barres consecutives ou ema_f/ema_s sont ordonnees dans le meme sens
    trend_sign_prev = 0

    while i < n - 1 and len(trades) < p.max_trades_per_day:
        # -- mise a jour de la tendance (a la cloture de la barre i) --
        sign = 1 if ema_f[i] > ema_s[i] else (-1 if ema_f[i] < ema_s[i] else 0)
        trend_run = trend_run + 1 if sign != 0 and sign == trend_sign_prev else (1 if sign != 0 else 0)
        trend_sign_prev = sign
        trend = sign if trend_run >= p.min_trend_bars else 0

        # -- suivi du pullback --
        if trend == 1:
            if c[i] < ema_f[i]:
                if pullback_dir != 1:
                    pullback_dir, pullback_extreme = 1, l[i]
                else:
                    pullback_extreme = min(pullback_extreme, l[i])
            elif pullback_dir == 1 and c[i] > ema_f[i]:
                d_sig = 1
                signal_atr, signal_extreme = atr[i], pullback_extreme
                pullback_dir, pullback_extreme = 0, None
                i = _open_trade(trades, o, h, l, c, ema_f, ema_s, i, n, d_sig,
                                signal_atr, signal_extreme, p, inst, slip, day, rng)
                continue
            else:
                pullback_dir, pullback_extreme = 0, None
        elif trend == -1:
            if c[i] > ema_f[i]:
                if pullback_dir != -1:
                    pullback_dir, pullback_extreme = -1, h[i]
                else:
                    pullback_extreme = max(pullback_extreme, h[i])
            elif pullback_dir == -1 and c[i] < ema_f[i]:
                d_sig = -1
                signal_atr, signal_extreme = atr[i], pullback_extreme
                pullback_dir, pullback_extreme = 0, None
                i = _open_trade(trades, o, h, l, c, ema_f, ema_s, i, n, d_sig,
                                signal_atr, signal_extreme, p, inst, slip, day, rng)
                continue
            else:
                pullback_dir, pullback_extreme = 0, None
        else:
            pullback_dir, pullback_extreme = 0, None

        i += 1

    return trades


def _open_trade(trades, o, h, l, c, ema_f, ema_s, k, n, d_sig, signal_atr,
                signal_extreme, p, inst, slip, day, rng) -> int:
    """Ouvre un trade signale a la barre k (entree a l'ouverture de k+1), le
    gere jusqu'a sa sortie, l'ajoute a `trades`. Renvoie l'indice de barre a
    partir duquel reprendre la recherche du prochain signal (= barre de sortie,
    jamais avant, pour interdire toute position simultanee)."""
    e = k + 1
    if e >= n:
        return n
    stop_lvl = signal_extreme - d_sig * p.atr_stop_mult * signal_atr
    r_gross = d_sig * (o[e] - stop_lvl)
    if r_gross <= inst.tick:
        return e                                # stop degenere, on ne trade pas, on reprend a e

    d = d_sig if rng is None else int(rng.choice((-1, 1)))
    entry = o[e] + d * slip
    stop = o[e] - d * r_gross                   # = stop_lvl quand d == d_sig
    target = entry + d * p.atr_target_mult * signal_atr
    risk = d * (entry - stop)

    exit_px, reason, x = None, "time", n - 1
    for j in range(e, n):
        prev = j - 1                            # reference "connue avant l'ouverture de j"
        trend_broken_prev = (d == 1 and ema_f[prev] <= ema_s[prev]) or \
                            (d == -1 and ema_f[prev] >= ema_s[prev])
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
        if j > e and trend_broken_prev:                     # rupture de tendance, sortie a l'open
            exit_px, reason, x = o[j] - d * slip, "trend_break", j
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
# Metriques (identique a l'ORB/VWAP)
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
# Tests de robustesse (identique a l'ORB/VWAP)
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
    Si le pullback ne bat pas ca, la direction du signal ne contient aucune information."""
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
    grid = [Params(ema_fast=ef, ema_slow=es, min_trend_bars=mt, atr_stop_mult=sm, atr_target_mult=tm)
            for ef, es, mt, sm, tm in product((9,), (21, 34), (2, 3, 5),
                                              (0.5, 1.0, 1.5), (1.5, 2.0, 3.0))]
    all_trades = {p: run_backtest(days, p, inst, bm) for p in grid}

    rows = []
    for p in grid:
        m_is = metrics(sel(all_trades[p], is_dates), is_dates)
        m_oos = metrics(sel(all_trades[p], oos_dates), oos_dates)
        rows.append({"ema_slow": p.ema_slow, "min_trend": p.min_trend_bars,
                     "stop_atr": p.atr_stop_mult, "target_atr": p.atr_target_mult,
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
            print(f"  test a partir de {t1} : ema_slow={p.ema_slow}, min_trend={p.min_trend_bars}, "
                  f"stop_atr={p.atr_stop_mult}, target_atr={p.atr_target_mult}")
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
    print(f"  Pullback reel : {actual:.0f}$ | pile ou face : {mu:.0f}$ +/- {sd:.0f}$ | p-value = {pval:.3f}")

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
