"""
Backtest d'un VWAP Reversion intraday sur futures indice (MES / ES).

Idee
----
Le VWAP (prix moyen pondere par le volume depuis l'ouverture) represente le
"juste prix" moyen de la seance. Quand le prix s'en ecarte de plus de
`entry_std` ecarts-types, on parie sur un retour vers le VWAP :
  - trop bas (prix <= VWAP - entry_std*sigma) -> LONG
  - trop haut (prix >= VWAP + entry_std*sigma) -> SHORT
Sortie quand le prix revient a `exit_std` du VWAP, ou stop si l'ecart continue
de se creuser au-dela de `stop_std` (le mouvement est peut-etre une vraie
tendance, pas un exces).

Conventions (identiques a l'ORB, pour rester comparables)
-----------------------------------------------------------
- Barres IB : l'horodatage est le DEBUT de la barre.
- Tout est converti en heure de New York.
- Le signal est calcule a la CLOTURE d'une barre, l'ordre est execute a
  l'OUVERTURE de la barre suivante. Aucune information future n'est utilisee :
  le niveau de stop est fixe au moment du signal, le niveau de "retour au VWAP"
  utilise le VWAP/sigma connus a la barre PRECEDENTE (jamais la barre en cours).
- Un seul trade par jour, toujours flat avant la cloture (16:00 NY).

Usage
-----
    python vwap_backtest.py data/MES_5min_all.csv --instrument MES

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
# Actions/ETF : taille de reference = 100 actions (comparable a 1 contrat MES en termes de
# capital engage), donc point_value=100.0 ($ par $ de mouvement du sous-jacent, x100 actions).
# A 1 action, le mouvement de prix est ecrase par le minimum de commission (1$/ordre) et rend
# tout trade mecaniquement perdant, quel que soit le signal.
# Commission IBKR Pro US stocks ~0.005$/action -> 100 actions = 0.50$, sous le minimum de 1$/ordre.
INSTRUMENTS = {
    "MES": Instrument(tick=0.25, point_value=5.0, commission_side=0.85),
    "ES": Instrument(tick=0.25, point_value=50.0, commission_side=2.10),
    "SPY": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "QQQ": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
}


@dataclass(frozen=True)
class Params:
    warmup_minutes: int = 30    # pas de signal avant que le VWAP se stabilise
    entry_std: float = 2.0      # ecart (en sigma) qui declenche l'entree
    exit_std: float = 0.5       # ecart residuel tolere pour considerer "retour au VWAP"
    stop_std: float = 3.5       # ecart (en sigma, fige au signal) qui invalide le trade
    slippage_ticks: float = 1.0
    limit_through_ticks: float = 1.0  # le retour au VWAP doit etre depasse de N ticks pour compter
    regime_filter: bool = False  # si True, ne trade que dans le sens de la tendance de fond
    regime_days: int = 20        # fenetre (jours) de la moyenne mobile de tendance


# --------------------------------------------------------------------------
# Donnees (identique a l'ORB : meme loader, meme conventions de seance)
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


def compute_daily_trend(days: list[Day], regime_days: int) -> dict:
    """Tendance de fond par jour, a partir des clotures quotidiennes UNIQUEMENT anterieures
    (jamais celle du jour meme, pour eviter toute fuite de futur) :
      trend[date] = +1 si la cloture de J-1 est au-dessus de la moyenne des `regime_days`
                    clotures precedentes (tendance haussiere) ; -1 si en dessous ; 0 si
                    l'historique est insuffisant (pas encore `regime_days` jours connus)."""
    closes = [d.c[-1] for d in days]
    trend = {}
    for i, day in enumerate(days):
        if i < regime_days:
            trend[day.date] = 0
            continue
        ma = sum(closes[i - regime_days:i]) / regime_days
        prior_close = closes[i - 1]
        trend[day.date] = 1 if prior_close > ma else (-1 if prior_close < ma else 0)
    return trend


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
# Moteur : un jour = un trade au plus
# --------------------------------------------------------------------------
TRADE_COLS = ["date", "side", "entry_time", "exit_time", "entry", "exit",
              "pts", "risk_pts", "r_mult", "pnl", "reason", "entry_dev"]


def _vwap_series(o, h, l, c, v):
    """VWAP et ecart-type cumules depuis l'ouverture, bar par bar (sans fuite de futur :
    vwap[j]/std[j] ne dependent que des barres 0..j)."""
    tp = np.array([(h[i] + l[i] + c[i]) / 3.0 for i in range(len(c))])
    vol = np.array(v, dtype=float)
    vol = np.where(vol <= 0, 1e-9, vol)  # garde-fou si une barre a un volume nul
    cum_v = np.cumsum(vol)
    cum_pv = np.cumsum(tp * vol)
    vwap = cum_pv / cum_v
    cum_pv2 = np.cumsum(vol * tp * tp)
    var = np.maximum(cum_pv2 / cum_v - vwap * vwap, 0.0)
    std = np.sqrt(var)
    safe_std = np.where(std > 1e-9, std, 1.0)
    dev = np.where(std > 1e-9, (tp - vwap) / safe_std, 0.0)
    return tp, vwap, std, dev


def simulate_day(day: Day, p: Params, inst: Instrument, bar_minutes: int = 5,
                 rng: np.random.Generator | None = None, trend: int = 0) -> dict | None:
    """
    Regles :
      1. VWAP et sigma cumules depuis l'ouverture (aucune donnee future).
      2. Premiere barre, apres `warmup_minutes`, dont la cloture s'ecarte du VWAP
         de plus de `entry_std` sigma -> signal (en dessous = long, au-dessus = short).
      3. Entree a l'ouverture de la barre suivante, plus slippage.
      4. Stop fige au moment du signal : VWAP_signal -/+ stop_std * sigma_signal.
      5. Sortie "retour au VWAP" : quand le prix atteint VWAP_(j-1) -/+ exit_std * sigma_(j-1)
         (le VWAP/sigma de la barre PRECEDENTE, jamais de la barre en cours -> pas de fuite).
      6. Si stop et retour sont touches dans la meme barre, on suppose le stop d'abord.
      7. Sortie forcee a la cloture de la derniere barre de la seance.

    Si `rng` est fourni, la direction est tiree au hasard (meme timing, meme distance
    de stop) : sert de benchmark "pile ou face".

    Si `p.regime_filter` est actif, `trend` (+1 haussier / -1 baissier / 0 inconnu, calcule
    UNIQUEMENT sur les clotures quotidiennes anterieures a ce jour) doit etre du meme sens
    que le trade "logique" (acheter les creux en tendance haussiere, vendre les pics en
    tendance baissiere) : sinon on ne prend pas ce signal.
    """
    o, h, l, c, v = day.o, day.h, day.l, day.c, day.v
    n = len(c)
    n_warm = p.warmup_minutes // bar_minutes
    tp, vwap, std, dev = _vwap_series(o, h, l, c, v)
    slip = p.slippage_ticks * inst.tick

    # 1-2. Signal : premiere cloture (apres warmup) qui s'ecarte de plus de entry_std sigma
    d_sig, k = 0, None
    for k in range(max(n_warm, 1), n - 1):
        if std[k] <= 1e-9:
            continue
        if dev[k] <= -p.entry_std:
            d_sig = 1     # prix trop bas -> long
            break
        if dev[k] >= p.entry_std:
            d_sig = -1    # prix trop haut -> short
            break
    if d_sig == 0:
        return None
    if p.regime_filter and trend != 0 and d_sig != trend:
        return None       # achat de creux hors tendance haussiere / vente de pic hors tendance baissiere

    # 3. Entree a l'open de la barre suivante
    e = k + 1
    stop_lvl = vwap[k] - d_sig * p.stop_std * std[k]
    r_gross = d_sig * (o[e] - stop_lvl)
    if r_gross <= inst.tick:
        return None                        # stop degenere, on ne trade pas

    d = d_sig if rng is None else int(rng.choice((-1, 1)))
    entry = o[e] + d * slip
    stop = o[e] - d * r_gross               # = stop_lvl quand d == d_sig
    risk = d * (entry - stop)
    thr = p.limit_through_ticks * inst.tick

    # 4-7. Gestion de la position barre par barre
    exit_px, reason, x = None, "time", n - 1
    for j in range(e, n):
        prev = j - 1 if j > e else k        # reference "connue avant l'ouverture de j"
        target_lvl = vwap[prev] - d * p.exit_std * std[prev]
        adverse = l[j] if d == 1 else h[j]
        favorable = h[j] if d == 1 else l[j]
        if j > e and d * (o[j] - stop) <= 0:            # gap a travers le stop
            exit_px, reason, x = o[j] - d * slip, "stop_gap", j
            break
        if d * (adverse - stop) <= 0:                    # stop touche
            exit_px, reason, x = stop - d * slip, "stop", j
            break
        if d * (favorable - (target_lvl - d * thr)) >= 0:  # retour au VWAP, ordre limite
            exit_px, reason, x = target_lvl, "target", j
            break
        if j == n - 1:                                   # cloture de seance
            exit_px, reason, x = c[j] - d * slip, "time", j

    pts = d * (exit_px - entry)
    return {
        "date": day.date, "side": d, "entry_time": day.idx[e], "exit_time": day.idx[x],
        "entry": entry, "exit": exit_px, "pts": pts, "risk_pts": risk,
        "r_mult": pts / risk,
        "pnl": pts * inst.point_value - 2 * inst.commission_side,
        "reason": reason, "entry_dev": dev[k],
    }


def run_backtest(days: list[Day], p: Params, inst: Instrument, bar_minutes: int = 5,
                 rng: np.random.Generator | None = None,
                 trend_by_date: dict | None = None) -> pd.DataFrame:
    trend_by_date = trend_by_date or {}
    rows = [t for t in (simulate_day(d, p, inst, bar_minutes, rng, trend_by_date.get(d.date, 0))
                        for d in days) if t]
    return pd.DataFrame(rows, columns=TRADE_COLS)


# --------------------------------------------------------------------------
# Metriques (identique a l'ORB)
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
# Tests de robustesse (identique a l'ORB)
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


def random_direction_test(days, p, inst, bar_minutes, dates, n_sims=300, seed=0, trend_by_date=None):
    """Meme timing d'entree, meme distance de stop, direction tiree a pile ou face.
    Si le VWAP reversion ne bat pas ca, la direction du signal ne contient aucune information."""
    actual = sel(run_backtest(days, p, inst, bar_minutes, trend_by_date=trend_by_date), dates)["pnl"].sum()
    rng = np.random.default_rng(seed)
    sims = np.array([sel(run_backtest(days, p, inst, bar_minutes, rng, trend_by_date), dates)["pnl"].sum()
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
    # regime_filter=True : ne prendre le signal que dans le sens de la tendance de fond
    # (moyenne mobile `regime_days`, calculee sur les clotures quotidiennes anterieures).
    trend_by_date = compute_daily_trend(days, regime_days=20)
    grid = [Params(warmup_minutes=w, entry_std=e, exit_std=x, stop_std=s, regime_filter=rf)
            for w, e, x, s, rf in product((30, 60), (1.5, 2.0, 2.5), (0.25, 0.5), (3.0, 4.0), (False, True))]
    all_trades = {p: run_backtest(days, p, inst, bm, trend_by_date=trend_by_date) for p in grid}

    rows = []
    for p in grid:
        m_is = metrics(sel(all_trades[p], is_dates), is_dates)
        m_oos = metrics(sel(all_trades[p], oos_dates), oos_dates)
        rows.append({"warmup": p.warmup_minutes, "entry_std": p.entry_std, "exit_std": p.exit_std,
                     "stop_std": p.stop_std, "regime": p.regime_filter, "n_IS": m_is.get("n_trades"),
                     "exp$_IS": m_is.get("exp_$"), "PF_IS": m_is.get("profit_factor"),
                     "sharpe_IS": m_is.get("sharpe"), "sharpe_OOS": m_oos.get("sharpe"),
                     "exp$_OOS": m_oos.get("exp_$")})
    table = pd.DataFrame(rows).sort_values("sharpe_IS", ascending=False)
    print(f"\n=== 1. Grille ({len(grid)} configurations testees, avec/sans filtre de regime) ===")
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
            print(f"  test a partir de {t1} : entry={p.entry_std}, exit={p.exit_std}, "
                  f"stop={p.stop_std}, regime={p.regime_filter}")
    else:
        print("Pas assez d'historique pour un walk-forward 12+3 mois.")

    # 4. Sensibilite aux couts
    print("\n=== 4. Sensibilite au slippage (meilleure config, toute la periode) ===")
    for s in (0.0, 1.0, 2.0, 3.0):
        p = Params(**{**asdict(best), "slippage_ticks": s})
        print(f"  slippage {s:.0f} tick(s)/execution :",
              fmt(metrics(run_backtest(days, p, inst, bm, trend_by_date=trend_by_date), dates)))

    # 5. Benchmark pile ou face
    print("\n=== 5. Direction au hasard (meme timing, meme stop), hors-echantillon ===")
    actual, mu, sd, pval = random_direction_test(days, best, inst, bm, oos_dates, trend_by_date=trend_by_date)
    print(f"  VWAP reel : {actual:.0f}$ | pile ou face : {mu:.0f}$ +/- {sd:.0f}$ | p-value = {pval:.3f}")

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
