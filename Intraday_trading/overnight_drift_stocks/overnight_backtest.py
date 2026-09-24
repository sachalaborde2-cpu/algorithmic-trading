"""
Backtest de la derive "overnight vs intraday" sur actions individuelles US
(AAPL, JPM, JNJ, XOM, WMT).

Pourquoi des actions individuelles et pas des ETF (cf. overnight_drift/) :
---------------------------------------------------------------------------
Le paper trading de la derive overnight sur SPY/QQQ/IWM est bloque par la
reglementation europeenne PRIIPs (absence de KID sur les ETF domicilies aux
Etats-Unis pour un client retail IB). PRIIPs ne s'applique qu'aux produits
"packages" (composite investments) : un actionnaire qui detient directement
le sous-jacent (une action ordinaire) n'est PAS concerne, donc AAPL/JPM/JNJ/
XOM/WMT ne sont pas bloques (confirme par un ordre MOC reel accepte en
PendingSubmit sur AAPL, sans Error 201). Ce dossier reteste le meme edge sur
5 actions mega-cap de secteurs differents (tech, finance, sante, energie,
consommation) pour limiter la correlation inter-titres.

Idee
----
Ce n'est pas un signal technique bar-par-bar comme l'ORB/VWAP/pullback :
c'est un pari structurel sur la repartition du rendement d'une seance entre
deux fenetres fixes :
  - "overnight"  : de la cloture du jour J-1 a l'ouverture du jour J.
  - "intraday"   : de l'ouverture du jour J a sa cloture.
Anomalie documentee sur les indices actions US : la quasi-totalite du
rendement de long terme provient de la fenetre overnight, la fenetre
intraday etant historiquement quasi plate voire negative (effet lie aux flux
structurels : rachats d'actions executes a la cloture, ordres institutionnels
overnight, primes de risque liees a l'incertitude pendant la fermeture).

Contrairement aux strategies precedentes, il n'y a AUCUNE decision prise a
partir d'une barre intrajournaliere : la direction et la fenetre sont fixees
a l'avance (parametres de la grille), pas calculees a partir de donnees du
jour meme -> aucun risque de fuite de futur par construction. Le risque a
surveiller ici est plutot la simplicite du pari (peu de parametres, donc peu
de risque de data snooping, mais aussi peu de marge pour "forcer" un edge).

Regles
------
1. Fenetre "overnight" : entree a la CLOTURE du jour J-1 (+ slippage),
   sortie a l'OUVERTURE du jour J (+ slippage).
2. Fenetre "intraday" : entree a l'OUVERTURE du jour J (+ slippage), sortie a
   la CLOTURE du jour J (+ slippage).
3. Direction (long/short) et fenetre (overnight/intraday) sont les deux
   parametres de la grille, choisis en in-sample puis verifies hors-
   echantillon -- comme pour toutes les strategies precedentes.
4. Un trade par jour (le jour J-1 sert uniquement de reference de cloture
   pour le jour J).

Usage
-----
    python overnight_backtest.py data_aapl/AAPL_5min_all.csv --instrument AAPL

CSV attendu : datetime (UTC), open, high, low, close, volume [, contract]
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass

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
    point_value: float
    commission_side: float
    tz: str = TZ
    session_start: str = SESSION_START
    session_minutes: int = SESSION_MINUTES
    session_end: str = "15:59"  # dernier HH:MM inclus dans between_time


# point_value=100.0 => P&L exprime pour 100 actions (meme convention que
# SPY/QQQ/IWM dans overnight_drift/, pour rester comparable). tick=0.01 et
# commission_side=1.00 : memes conventions actions US deja utilisees dans
# orb_small_caps/ (tarif IB tiered ~0.0035$/action, 0.35$ minimum, arrondi a
# 1.00$/cote pour rester conservateur/comparable aux autres strategies).
INSTRUMENTS = {
    "AAPL": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "JPM": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "JNJ": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "XOM": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "WMT": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
}


@dataclass(frozen=True)
class Params:
    leg: str = "overnight"   # "overnight" ou "intraday"
    direction: int = 1        # +1 = long, -1 = short
    slippage_ticks: float = 1.0


# --------------------------------------------------------------------------
# Donnees (identique aux strategies precedentes : meme loader, meme
# conventions de seance)
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


def load_bars(path: str, bar_minutes: int = 5, inst: Instrument | None = None) -> tuple[list[Day], dict]:
    """Charge le CSV, passe dans le fuseau/la seance de `inst` (NY 09:30-16:00
    par defaut), garde la seance reguliere complete."""
    tz = inst.tz if inst else TZ
    session_start = inst.session_start if inst else SESSION_START
    session_end = inst.session_end if inst else "15:59"
    session_minutes = inst.session_minutes if inst else SESSION_MINUTES

    df = pd.read_csv(path)
    df["ts"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_convert(tz)
    df["date"] = df["ts"].dt.tz_localize(None).dt.normalize()

    df = df.set_index("ts").between_time(session_start, session_end).reset_index()

    if "contract" in df.columns:
        vol = df.groupby(["date", "contract"], as_index=False)["volume"].sum()
        best = vol.sort_values("volume").drop_duplicates("date", keep="last")
        df = df.merge(best[["date", "contract"]], on=["date", "contract"], how="inner")

    df = df.sort_values("ts").drop_duplicates("ts").set_index("ts")

    expected = session_minutes // bar_minutes
    days, dropped = [], 0
    for date, g in df.groupby("date"):
        if len(g) != expected or g.index[0].strftime("%H:%M") != session_start:
            dropped += 1
            continue
        days.append(Day(date, g.index, g["open"].tolist(), g["high"].tolist(),
                        g["low"].tolist(), g["close"].tolist(), g["volume"].tolist()))
    info = {"days": len(days), "dropped": dropped,
            "first": days[0].date.date() if days else None,
            "last": days[-1].date.date() if days else None}
    return days, info


# --------------------------------------------------------------------------
# Moteur : un jour = un trade au plus (le jour J-1 est requis comme reference
# pour la fenetre "overnight")
# --------------------------------------------------------------------------
TRADE_COLS = ["date", "side", "entry_time", "exit_time", "entry", "exit",
              "pts", "r_mult", "pnl", "reason"]


def simulate_pair(prev: Day, day: Day, p: Params, inst: Instrument,
                  side_override: int | None = None) -> dict:
    """Un trade sur la fenetre choisie (`p.leg`), entre `prev` (jour J-1) et
    `day` (jour J). Pas de fuite de futur possible : entree/sortie sont des
    prix deja connus (cloture J-1, ouverture/cloture J), la direction est
    fixee par le parametre (ou par le tirage aleatoire pour le test placebo),
    jamais calculee a partir d'une donnee future."""
    side = p.direction if side_override is None else side_override
    slip = inst.tick * p.slippage_ticks

    if p.leg == "overnight":
        entry_time, exit_time = prev.idx[-1], day.idx[0]
        entry_px, exit_px = prev.c[-1], day.o[0]
    else:  # "intraday"
        entry_time, exit_time = day.idx[0], day.idx[-1]
        entry_px, exit_px = day.o[0], day.c[-1]

    entry = entry_px + side * slip
    exit_ = exit_px - side * slip
    pts = (exit_ - entry) * side
    pnl = pts * inst.point_value - 2 * inst.commission_side
    risk_pts = 2 * slip if slip > 0 else 1.0  # reference de normalisation (pas de stop ici)

    return {"date": day.date, "side": side, "entry_time": entry_time, "exit_time": exit_time,
            "entry": entry, "exit": exit_, "pts": pts, "r_mult": pts / risk_pts,
            "pnl": pnl, "reason": p.leg}


def run_backtest(days: list[Day], p: Params, inst: Instrument,
                 rng: np.random.Generator | None = None) -> pd.DataFrame:
    rows = []
    for i in range(1, len(days)):
        side_override = int(rng.choice([-1, 1])) if rng is not None else None
        rows.append(simulate_pair(days[i - 1], days[i], p, inst, side_override))
    return pd.DataFrame(rows, columns=TRADE_COLS)


# --------------------------------------------------------------------------
# Metriques et tests de robustesse (identique aux strategies precedentes)
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


def random_direction_test(days, p, inst, dates, n_sims=300, seed=0):
    """Meme fenetre (overnight ou intraday), meme timing, direction tiree a
    pile ou face. Si le sens reel (long ou short systematique) ne bat pas ca,
    la direction choisie n'apporte aucune information."""
    actual = sel(run_backtest(days, p, inst), dates)["pnl"].sum()
    rng = np.random.default_rng(seed)
    sims = np.array([sel(run_backtest(days, p, inst, rng), dates)["pnl"].sum()
                     for _ in range(n_sims)])
    pval = (np.sum(sims >= actual) + 1) / (n_sims + 1)
    return actual, sims.mean(), sims.std(), pval


def fmt(d: dict) -> str:
    keys = ["n_trades", "win_rate", "exp_$", "exp_R", "profit_factor",
            "total_$", "sharpe", "t_stat", "max_dd_$"]
    return "  ".join(f"{k}={d[k]:.2f}" if k in d and k != "n_trades" else f"{k}={d.get(k)}"
                     for k in keys)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--instrument", default="AAPL", choices=INSTRUMENTS)
    ap.add_argument("--bar-minutes", type=int, default=5)
    ap.add_argument("--oos-frac", type=float, default=0.3)
    ap.add_argument("--plot", action="store_true")
    a = ap.parse_args()

    inst = INSTRUMENTS[a.instrument]
    days, info = load_bars(a.csv, a.bar_minutes, inst)
    print(f"\nDonnees : {info['days']} jours ({info['first']} -> {info['last']}), "
          f"{info['dropped']} jours incomplets ecartes")
    if info["days"] < 250:
        print("ATTENTION : moins d'un an de donnees, les resultats seront peu fiables.")

    dates = pd.DatetimeIndex([d.date for d in days[1:]])  # le 1er jour sert de reference J-1
    k = int(len(dates) * (1 - a.oos_frac))
    is_dates, oos_dates = dates[:k], dates[k:]
    print(f"In-sample : {is_dates[0].date()} -> {is_dates[-1].date()} | "
          f"Hors-echantillon : {oos_dates[0].date()} -> {oos_dates[-1].date()}")

    grid = [Params(leg=leg, direction=d) for leg in ("overnight", "intraday") for d in (1, -1)]
    all_trades = {p: run_backtest(days, p, inst) for p in grid}

    rows = []
    for p in grid:
        m_is = metrics(sel(all_trades[p], is_dates), is_dates)
        m_oos = metrics(sel(all_trades[p], oos_dates), oos_dates)
        rows.append({"leg": p.leg, "dir": "long" if p.direction == 1 else "short",
                     "n_IS": m_is.get("n_trades"), "exp$_IS": m_is.get("exp_$"),
                     "sharpe_IS": m_is.get("sharpe"), "t_IS": m_is.get("t_stat"),
                     "sharpe_OOS": m_oos.get("sharpe"), "exp$_OOS": m_oos.get("exp_$")})
    table = pd.DataFrame(rows).sort_values("sharpe_IS", ascending=False)
    print(f"\n=== 1. Grille ({len(grid)} configurations testees) ===")
    print(table.round(2).to_string(index=False))

    best = max(grid, key=lambda p: (lambda s: -1e9 if pd.isna(s) else s)(
        metrics(sel(all_trades[p], is_dates), is_dates).get("sharpe", np.nan)))
    tr = all_trades[best]
    print(f"\n=== 2. Meilleure config in-sample : {best} ===")
    print("IS  :", fmt(metrics(sel(tr, is_dates), is_dates)))
    print("OOS :", fmt(metrics(sel(tr, oos_dates), oos_dates)))

    oos_wf, log, wf_dates = walk_forward(all_trades, dates)
    print("\n=== 3. Walk-forward (train 12 mois, test 3 mois) ===")
    if len(wf_dates):
        print("Concatenation des periodes de test :", fmt(metrics(oos_wf, wf_dates)))
        for t1, p in log:
            print(f"  test a partir de {t1} : leg={p.leg}, dir={'long' if p.direction == 1 else 'short'}")
    else:
        print("Pas assez d'historique pour un walk-forward 12+3 mois.")

    print("\n=== 4. Sensibilite au slippage (meilleure config, toute la periode) ===")
    for s in (0.0, 1.0, 2.0, 3.0):
        p = Params(**{**asdict(best), "slippage_ticks": s})
        print(f"  slippage {s:.0f} tick(s)/execution :", fmt(metrics(run_backtest(days, p, inst), dates)))

    print("\n=== 5. Direction au hasard (meme fenetre, meme timing), hors-echantillon ===")
    actual, mu, sd, pval = random_direction_test(days, best, inst, oos_dates)
    print(f"  reel : {actual:.0f}$ | pile ou face : {mu:.0f}$ +/- {sd:.0f}$ | p-value = {pval:.3f}")

    print("\n=== 6. Combo long-overnight / short-intraday (les 2 legs simultanement) ===")
    on_long = run_backtest(days, Params(leg="overnight", direction=1), inst)
    id_short = run_backtest(days, Params(leg="intraday", direction=-1), inst)
    combo = pd.concat([on_long, id_short])
    print("IS  :", fmt(metrics(sel(combo, is_dates), is_dates)))
    print("OOS :", fmt(metrics(sel(combo, oos_dates), oos_dates)))

    full = sel(tr, dates)
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
