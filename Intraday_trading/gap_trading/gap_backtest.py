"""
Backtest d'un Gap Trading intraday sur futures indice (MES) et ETF (SPY/QQQ).

Idee
----
A l'ouverture de la seance, le prix "gap" par rapport a la cloture de la
veille (aucun echange entre les deux). Deux paris opposes sont testes dans la
meme grille :
  - "fill" (retour a la moyenne) : le gap est excessif par rapport a la
    volatilite quotidienne recente -> on parie qu'il se comble (retour vers la
    cloture de la veille).
  - "go" (continuation) : le gap est confirme par un franchissement du
    plus haut/bas des premieres minutes dans le sens du gap -> on parie que le
    mouvement continue (proche de l'ORB, mais la direction est imposee par le
    gap, pas par la premiere sortie de range).

Conventions (identiques a l'ORB / VWAP reversion / pullback en tendance)
-------------------------------------------------------------------------
- Barres IB : l'horodatage est le DEBUT de la barre. Tout est converti en heure
  de New York.
- Le gap et l'ATR quotidien (volatilite de reference) ne dependent que de
  cloture(s) de jour(s) anterieur(s) : aucune fuite de futur.
- Entree a l'ouverture d'une barre (jamais au prix d'ouverture "brut" de la
  seance : on attend au moins `confirm_bars` barres), plus slippage.
- Stop et target figes au moment du signal.
- Un seul trade par jour, toujours flat avant la cloture (16:00 NY).

Usage
-----
    python gap_backtest.py data/MES_5min_all.csv --instrument MES

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


INSTRUMENTS = {
    "MES": Instrument(tick=0.25, point_value=5.0, commission_side=0.85),
    "ES": Instrument(tick=0.25, point_value=50.0, commission_side=2.10),
    "SPY": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "QQQ": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
}


@dataclass(frozen=True)
class Params:
    atr_period: int = 14           # ATR quotidien, sur les jours PRECEDENTS
    gap_threshold_atr: float = 0.5  # gap minimum (en multiples d'ATR quotidien) pour trader
    direction: str = "fill"        # "fill" (retour a la moyenne) ou "go" (continuation)
    confirm_bars: int = 2          # nb de barres d'attente/confirmation avant l'entree
    atr_stop_mult: float = 1.0     # stop = entry -/+ atr_stop_mult * ATR quotidien
    atr_target_mult: float = 1.5   # target (mode "go" uniquement) = entry +/- atr_target_mult * ATR
    slippage_ticks: float = 1.0


# --------------------------------------------------------------------------
# Donnees (identique a l'ORB / VWAP reversion : meme loader)
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


def compute_daily_atr(days: list[Day], atr_period: int) -> list[float]:
    """ATR quotidien causal : atr[i] ne depend que des jours 0..i-1 (jamais du
    jour i lui-meme -> connu AVANT l'ouverture du jour i, utilisable pour la
    taille du gap et les niveaux de stop/target). np.nan tant que l'historique
    est insuffisant (moins de atr_period+1 jours connus)."""
    dO = [d.o[0] for d in days]
    dH = [max(d.h) for d in days]
    dL = [min(d.l) for d in days]
    dC = [d.c[-1] for d in days]
    n = len(days)
    tr = [np.nan] * n
    for i in range(1, n):
        tr[i] = max(dH[i] - dL[i], abs(dH[i] - dC[i - 1]), abs(dL[i] - dC[i - 1]))
    atr = [np.nan] * n
    for i in range(n):
        window = [t for t in tr[max(0, i - atr_period):i] if not np.isnan(t)]
        if len(window) >= atr_period:
            atr[i] = sum(window) / len(window)
    return atr


# --------------------------------------------------------------------------
# Moteur : un jour = un trade au plus
# --------------------------------------------------------------------------
TRADE_COLS = ["date", "side", "entry_time", "exit_time", "entry", "exit",
              "pts", "risk_pts", "r_mult", "pnl", "reason", "gap_atr", "mode"]


def simulate_day(day: Day, prev_close: float, daily_atr: float, p: Params,
                 inst: Instrument, bar_minutes: int = 5,
                 rng: np.random.Generator | None = None) -> dict | None:
    """
    Regles :
      1. gap = open[0] - prev_close ; gap_atr = gap / daily_atr (ATR calcule
         UNIQUEMENT sur les jours precedents). Si |gap_atr| < gap_threshold_atr,
         ou si l'ATR n'est pas encore disponible -> pas de trade.
      2. Mode "fill" : on attend `confirm_bars` barres completes (sans
         condition sur leur contenu, pour ne jamais entrer au prix d'ouverture
         brut), puis on entre a l'ouverture de la barre suivante, en pariant
         sur un retour vers `prev_close`.
         Mode "go" : range de confirmation = plus haut/bas des `confirm_bars`
         premieres barres ; signal a la premiere cloture, apres ces barres,
         qui casse ce range dans le sens du gap -> entree a l'ouverture de la
         barre suivante.
      3. Stop fige au signal : entry -/+ atr_stop_mult * daily_atr.
         Target : prev_close (mode "fill") ou entry +/- atr_target_mult *
         daily_atr (mode "go").
      4. Si stop et target sont touches sur la meme barre, le stop gagne.
      5. Sortie forcee a la cloture de la derniere barre de la seance.

    Si `rng` est fourni, la direction est tiree au hasard (meme timing, meme
    distance de stop) : sert de benchmark "pile ou face".
    """
    o, h, l, c = day.o, day.h, day.l, day.c
    n = len(c)
    cb = p.confirm_bars
    if np.isnan(daily_atr) or daily_atr <= 0 or cb >= n - 1:
        return None

    gap = o[0] - prev_close
    gap_atr = gap / daily_atr
    if abs(gap_atr) < p.gap_threshold_atr:
        return None
    gap_sign = 1 if gap > 0 else -1

    slip = p.slippage_ticks * inst.tick
    e = None
    d_sig = None

    if p.direction == "fill":
        d_sig = -gap_sign          # parie sur le retour vers prev_close
        e = cb                     # entree a l'ouverture de la barre apres confirmation
    elif p.direction == "go":
        range_hi = max(h[:cb])
        range_lo = min(l[:cb])
        for k in range(cb, n - 1):
            if gap_sign == 1 and c[k] > range_hi:
                d_sig = 1
                e = k + 1
                break
            if gap_sign == -1 and c[k] < range_lo:
                d_sig = -1
                e = k + 1
                break
        if d_sig is None:
            return None
    else:
        raise ValueError(f"direction inconnue : {p.direction}")

    if e is None or e >= n:
        return None

    # Distances (magnitudes, toujours positives) calculees a partir du signal
    # LOGIQUE (d_sig), puis appliquees selon `d` (reel ou tire au hasard) --
    # meme convention que le VWAP reversion : ca garantit que stop/target
    # restent coherents (du bon cote de l'entree) quelle que soit la direction
    # utilisee pour le test placebo.
    r_gross = p.atr_stop_mult * daily_atr
    if p.direction == "fill":
        target_dist = abs(prev_close - o[e])
    else:
        target_dist = p.atr_target_mult * daily_atr
    if r_gross <= inst.tick or target_dist <= inst.tick:
        return None                        # stop ou target degenere, pas de trade

    d = d_sig if rng is None else int(rng.choice((-1, 1)))
    entry = o[e] + d * slip
    stop = entry - d * r_gross
    target_lvl = entry + d * target_dist
    risk = d * (entry - stop)

    exit_px, reason, x = None, "time", n - 1
    for j in range(e, n):
        adverse = l[j] if d == 1 else h[j]
        favorable = h[j] if d == 1 else l[j]
        if j > e and d * (o[j] - stop) <= 0:
            exit_px, reason, x = o[j] - d * slip, "stop_gap", j
            break
        if d * (adverse - stop) <= 0:
            exit_px, reason, x = stop - d * slip, "stop", j
            break
        if d * (favorable - target_lvl) >= 0:
            exit_px, reason, x = target_lvl, "target", j
            break
        if j == n - 1:
            exit_px, reason, x = c[j] - d * slip, "time", j

    pts = d * (exit_px - entry)
    return {
        "date": day.date, "side": d, "entry_time": day.idx[e], "exit_time": day.idx[x],
        "entry": entry, "exit": exit_px, "pts": pts, "risk_pts": risk,
        "r_mult": pts / risk if risk > 0 else np.nan,
        "pnl": pts * inst.point_value - 2 * inst.commission_side,
        "reason": reason, "gap_atr": gap_atr, "mode": p.direction,
    }


def run_backtest(days: list[Day], daily_atr: list[float], p: Params, inst: Instrument,
                 bar_minutes: int = 5, rng: np.random.Generator | None = None) -> pd.DataFrame:
    rows = []
    for i in range(1, len(days)):
        t = simulate_day(days[i], days[i - 1].c[-1], daily_atr[i], p, inst, bar_minutes, rng)
        if t:
            rows.append(t)
    return pd.DataFrame(rows, columns=TRADE_COLS)


# --------------------------------------------------------------------------
# Metriques (identique aux strategies precedentes)
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
# Tests de robustesse (identique aux strategies precedentes)
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


def random_direction_test(days, daily_atr, p, inst, bar_minutes, dates, n_sims=300, seed=0):
    """Meme timing d'entree, meme distance de stop, direction tiree a pile ou face."""
    actual = sel(run_backtest(days, daily_atr, p, inst, bar_minutes), dates)["pnl"].sum()
    rng = np.random.default_rng(seed)
    sims = np.array([sel(run_backtest(days, daily_atr, p, inst, bar_minutes, rng), dates)["pnl"].sum()
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

    atr_period = 14
    daily_atr = compute_daily_atr(days, atr_period)

    dates = pd.DatetimeIndex([d.date for d in days])[1:]  # jour 0 n'a pas de gap (pas de veille)
    k = int(len(dates) * (1 - a.oos_frac))
    is_dates, oos_dates = dates[:k], dates[k:]
    print(f"In-sample : {is_dates[0].date()} -> {is_dates[-1].date()} | "
          f"Hors-echantillon : {oos_dates[0].date()} -> {oos_dates[-1].date()}")

    grid = [Params(atr_period=atr_period, gap_threshold_atr=g, direction=dr, confirm_bars=cb,
                   atr_stop_mult=s, atr_target_mult=t)
            for g, dr, cb, s, t in product((0.3, 0.5, 0.75), ("fill", "go"), (1, 2),
                                           (0.5, 1.0), (1.0, 2.0))]
    all_trades = {p: run_backtest(days, daily_atr, p, inst, bm) for p in grid}

    rows = []
    for p in grid:
        m_is = metrics(sel(all_trades[p], is_dates), is_dates)
        m_oos = metrics(sel(all_trades[p], oos_dates), oos_dates)
        rows.append({"mode": p.direction, "gap_thr": p.gap_threshold_atr, "confirm": p.confirm_bars,
                     "stop_atr": p.atr_stop_mult, "target_atr": p.atr_target_mult,
                     "n_IS": m_is.get("n_trades"), "exp$_IS": m_is.get("exp_$"),
                     "PF_IS": m_is.get("profit_factor"), "sharpe_IS": m_is.get("sharpe"),
                     "sharpe_OOS": m_oos.get("sharpe"), "exp$_OOS": m_oos.get("exp_$")})
    table = pd.DataFrame(rows).sort_values("sharpe_IS", ascending=False)
    print(f"\n=== 1. Grille ({len(grid)} configurations testees) ===")
    print(table.round(2).to_string(index=False))
    print(f"Le meilleur Sharpe in-sample sur {len(grid)} essais est biaise a la hausse : "
          "regarde surtout si le classement tient hors-echantillon.")

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
            print(f"  test a partir de {t1} : mode={p.direction}, gap_thr={p.gap_threshold_atr}, "
                  f"confirm={p.confirm_bars}, stop={p.atr_stop_mult}, target={p.atr_target_mult}")
    else:
        print("Pas assez d'historique pour un walk-forward 12+3 mois.")

    print("\n=== 4. Sensibilite au slippage (meilleure config, toute la periode) ===")
    for s in (0.0, 1.0, 2.0, 3.0):
        p = Params(**{**asdict(best), "slippage_ticks": s})
        print(f"  slippage {s:.0f} tick(s)/execution :",
              fmt(metrics(run_backtest(days, daily_atr, p, inst, bm), dates)))

    print("\n=== 5. Direction au hasard (meme timing, meme stop), hors-echantillon ===")
    actual, mu, sd, pval = random_direction_test(days, daily_atr, best, inst, bm, oos_dates)
    print(f"  Gap trading reel : {actual:.0f}$ | pile ou face : {mu:.0f}$ +/- {sd:.0f}$ | p-value = {pval:.3f}")

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
        plt.savefig(f"equity_{a.instrument}_best.png", dpi=120)
        print(f"Courbe ecrite dans equity_{a.instrument}_best.png")


if __name__ == "__main__":
    main()
