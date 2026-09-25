"""
Backtest de l'edge overnight structurel (voir Intraday_trading/overnight_drift/),
SANS FILTRE NI INDICATEUR, generalise du sous-groupe des indices actions larges
(SPY/QQQ/IWM/DIA, deja valide) a 13 ETF-paniers hors indices actions larges :
secteurs SPDR (XLE, XLF, XLK, XLV, XLY, XLP), matieres premieres (GLD, SLV,
USO), obligataire (TLT, IEF), international (EFA, EEM).

Pourquoi cette strategie (voir STRATEGIES.md #14 -> #15)
---------------------------------------------------------
`overnight_drift` (#10) survit au protocole complet sur indices/ETF larges
actions, mais est REJETE sur actions individuelles (#11, `overnight_drift_stocks`).
La frontiere tracee par #11 opposait "indice/ETF large" a "action individuelle",
mais melangeait implicitement deux dimensions distinctes : la classe d'actif
(actions vs autre) ET la structure de produit (panier diversifie vs titre
unique). Auto-critique (Rule #4, documentee dans STRATEGIES.md) : si l'edge
overnight tient a la structure de PANIER (flux de rebalancement / creation-
rachat de parts, primes de risque liees a la fermeture des marches, plutot
qu'a un phenomene specifique aux indices actions), alors il devrait aussi
apparaitre sur des ETF-paniers d'autres classes d'actifs (secteurs, matieres
premieres, obligataire, international). C'est l'hypothese testee ici -- une
generalisation, pas une repetition (Rule #3).

Design (Rule #2 : aucune approximation, aucun biais de confirmation)
----------------------------------------------------------------------
Contrairement a #14 (filtre de regime Kumo), aucun indicateur technique n'est
utilise ici : c'est la forme la plus simple de la strategie, identique dans
son principe a `Intraday_trading/overnight_drift/overnight_backtest.py`
d'origine, mais en barres JOURNALIERES (les CSV disponibles pour ces 13
tickers sont journaliers, pas 5 minutes) et restreinte a la fenetre
"overnight" (cloture J -> ouverture J+1) -- la fenetre "intraday" n'est pas
re-testee ici car elle ne fait pas partie de l'hypothese de generalisation
(l'edge deja valide sur indices est specifiquement l'edge overnight, pas la
comparaison overnight/intraday, deja tranchee par #10).

Seul parametre de grille : la DIRECTION (long/short), choisie en in-sample
sur le Sharpe le plus eleve, puis verifiee hors-echantillon -- jamais
l'inverse (Rule #2). Ceci permet de detecter un edge overnight de signe
oppose (short) sans le supposer a priori.

Regles d'execution (aucune fuite de futur, memes conventions que les
strategies precedentes)
-------------------------------------------------------------------------
1. Entree a la CLOTURE du jour J (+ slippage), sortie a l'OUVERTURE du jour
   J+1 (+ slippage) -- prix deja connus au moment de la decision, la
   direction est un parametre fixe (ou tire au hasard pour le test placebo),
   jamais calculee a partir d'une donnee future.
2. Un jour = un trade au plus, jamais de position tenue plus d'une nuit.
3. Slippage/commission appliques a chaque entree/sortie reelle.

Correction multiple-testing (voir STRATEGIES.md #15)
-------------------------------------------------------
Seuil de Bonferroni hierarchique = 0.05/13 ~ 0.00385 sur ce sous-groupe des
13 ETF-paniers (pooling justifie par l'hypothese commune de structure de
produit -- panier vs titre unique -- explicitement heterogene sur le plan
economique ; caveat pre-enregistre : si l'edge ne se manifeste que dans une
des 4 sous-classes economiques -- secteurs / matieres premieres / obligataire
/ international -- un second test hierarchique plus etroit sur cette
sous-classe sera necessaire avant de conclure, a l'image du precedent
Ichimoku #12).

Usage
-----
    python basket_backtest.py --instrument XLE
    python basket_backtest.py --instrument XLE --plot
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------
# Parametres
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Instrument:
    tick: float
    point_value: float
    commission_side: float


INSTRUMENTS = {
    # Secteurs SPDR
    "XLE": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "XLF": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "XLK": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "XLV": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "XLY": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "XLP": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    # Matieres premieres
    "GLD": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "SLV": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "USO": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    # Obligataire
    "TLT": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "IEF": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    # International
    "EFA": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "EEM": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
}

SUB_CLASSES = {
    "secteurs": ["XLE", "XLF", "XLK", "XLV", "XLY", "XLP"],
    "matieres_premieres": ["GLD", "SLV", "USO"],
    "obligataire": ["TLT", "IEF"],
    "international": ["EFA", "EEM"],
}


@dataclass(frozen=True)
class Params:
    direction: int = 1  # +1 = long, -1 = short
    slippage_ticks: float = 1.0


# --------------------------------------------------------------------------
# Donnees : barres journalieres (memes fichiers que ichimoku_daily/ et
# overnight_drift_regime_filtered/)
# --------------------------------------------------------------------------
def load_daily(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_localize(None).dt.normalize()
    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    return df[["date", "open", "high", "low", "close", "volume"]]


# --------------------------------------------------------------------------
# Moteur : un jour = un trade overnight au plus (aucun filtre)
# --------------------------------------------------------------------------
TRADE_COLS = ["date", "side", "entry_time", "exit_time", "entry", "exit",
              "pts", "r_mult", "pnl", "reason"]


def run_backtest(df: pd.DataFrame, p: Params, inst: Instrument,
                 rng: np.random.Generator | None = None) -> pd.DataFrame:
    """Position overnight (cloture du jour i -> ouverture du jour i+1) prise
    tous les jours, direction fixee par `p.direction` (ou tiree au hasard si
    `rng` est fourni, pour le test placebo -- meme timing, seul le signe
    change)."""
    slip = inst.tick * p.slippage_ticks
    close = df["close"].to_numpy()
    open_ = df["open"].to_numpy()
    dates = df["date"].to_numpy()
    n = len(df)

    rows = []
    for i in range(n - 1):
        side = p.direction if rng is None else int(rng.choice([-1, 1]))
        entry_px = close[i] + side * slip
        exit_px = open_[i + 1] - side * slip
        pts = (exit_px - entry_px) * side
        pnl = pts * inst.point_value - 2 * inst.commission_side
        risk_pts = 2 * slip if slip > 0 else 1.0
        rows.append({
            "date": dates[i + 1], "side": side,
            "entry_time": dates[i], "exit_time": dates[i + 1],
            "entry": entry_px, "exit": exit_px, "pts": pts,
            "r_mult": pts / risk_pts, "pnl": pnl,
            "reason": "long" if side == 1 else "short",
        })
    return pd.DataFrame(rows, columns=TRADE_COLS)


# --------------------------------------------------------------------------
# Metriques et tests de robustesse (memes conventions que les strategies
# precedentes)
# --------------------------------------------------------------------------
def sel(trades: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    return trades[trades["date"].isin(dates)]


def metrics(trades: pd.DataFrame, dates: pd.DatetimeIndex) -> dict:
    if len(trades) == 0:
        return {"n_trades": 0, "sharpe": np.nan, "t_stat": np.nan}
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


def walk_forward(df: pd.DataFrame, inst: Instrument, grid: list[Params],
                 dates: pd.DatetimeIndex, train_months: int = 12,
                 test_months: int = 3) -> tuple[pd.DataFrame, list, pd.DatetimeIndex]:
    all_trades = {p: run_backtest(df, p, inst) for p in grid}
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

        best = max(grid, key=score)
        parts.append(sel(all_trades[best], test))
        test_all.append(test)
        log.append((t1.date(), "long" if best.direction == 1 else "short"))
        t0 = t0 + pd.DateOffset(months=test_months)
    oos = pd.concat(parts) if parts else pd.DataFrame(columns=TRADE_COLS)
    wf_dates = test_all[0].append(test_all[1:]) if test_all else dates[:0]
    return oos, log, wf_dates


def random_direction_test(df, p, inst, dates, n_sims=300, seed=0):
    """Meme timing (tous les jours), direction tiree a pile ou face. Si le
    sens reel (choisi en in-sample) ne bat pas ca, la direction n'apporte
    aucune information."""
    actual = sel(run_backtest(df, p, inst), dates)["pnl"].sum()
    rng = np.random.default_rng(seed)
    sims = np.array([sel(run_backtest(df, p, inst, rng), dates)["pnl"].sum()
                     for _ in range(n_sims)])
    pval = (np.sum(sims >= actual) + 1) / (n_sims + 1)
    return actual, sims.mean(), sims.std(), pval


def fmt(d: dict) -> str:
    keys = ["n_trades", "win_rate", "exp_$", "exp_R", "profit_factor",
            "total_$", "sharpe", "t_stat", "max_dd_$"]
    return "  ".join(f"{k}={d[k]:.2f}" if k in d and k != "n_trades" else f"{k}={d.get(k)}"
                     for k in keys)


def run_instrument(symbol: str, oos_frac: float = 0.3) -> dict:
    """Execute le protocole complet pour un instrument et renvoie un resume
    (utilise a la fois par main() et par le script d'agregation cross-asset)."""
    inst = INSTRUMENTS[symbol]
    df = load_daily(f"data_{symbol.lower()}/{symbol}_daily_all.csv")
    dates = pd.DatetimeIndex(df["date"])[:-1]  # le dernier jour n'a pas d'ouverture J+1
    k = int(len(dates) * (1 - oos_frac))
    is_dates, oos_dates = dates[:k], dates[k:]

    grid = [Params(direction=d) for d in (1, -1)]
    all_trades = {p: run_backtest(df, p, inst) for p in grid}

    rows = []
    for p in grid:
        m_is = metrics(sel(all_trades[p], is_dates), is_dates)
        m_oos = metrics(sel(all_trades[p], oos_dates), oos_dates)
        rows.append({"direction": "long" if p.direction == 1 else "short",
                     "n_IS": m_is.get("n_trades"), "sharpe_IS": m_is.get("sharpe"),
                     "t_IS": m_is.get("t_stat"), "n_OOS": m_oos.get("n_trades"),
                     "sharpe_OOS": m_oos.get("sharpe")})
    table = pd.DataFrame(rows)

    best = max(grid, key=lambda p: (lambda s: -1e9 if pd.isna(s) else s)(
        metrics(sel(all_trades[p], is_dates), is_dates).get("sharpe", np.nan)))
    tr = all_trades[best]
    m_is = metrics(sel(tr, is_dates), is_dates)
    m_oos = metrics(sel(tr, oos_dates), oos_dates)

    actual, mu, sd, pval = random_direction_test(df, best, inst, oos_dates)

    return {
        "symbol": symbol, "table": table, "best": best,
        "m_is": m_is, "m_oos": m_oos, "trades_best": tr,
        "placebo": {"actual": actual, "mu": mu, "sd": sd, "pval": pval},
        "dates": dates, "is_dates": is_dates, "oos_dates": oos_dates,
        "df": df, "all_trades": all_trades,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", default="XLE", choices=INSTRUMENTS)
    ap.add_argument("--oos-frac", type=float, default=0.3)
    ap.add_argument("--plot", action="store_true")
    a = ap.parse_args()

    res = run_instrument(a.instrument, a.oos_frac)
    df, dates = res["df"], res["dates"]
    is_dates, oos_dates = res["is_dates"], res["oos_dates"]

    print(f"\nDonnees : {len(df)} jours ({df['date'].iloc[0].date()} -> {df['date'].iloc[-1].date()})")
    print(f"In-sample : {is_dates[0].date()} -> {is_dates[-1].date()} | "
          f"Hors-echantillon : {oos_dates[0].date()} -> {oos_dates[-1].date()}")

    print(f"\n=== 1. Grille ({len(res['table'])} configurations testees) ===")
    print(res["table"].round(2).to_string(index=False))

    best = res["best"]
    print(f"\n=== 2. Meilleure config in-sample : direction={'long' if best.direction == 1 else 'short'} ===")
    print("IS  :", fmt(res["m_is"]))
    print("OOS :", fmt(res["m_oos"]))

    inst = INSTRUMENTS[a.instrument]
    grid = [Params(direction=d) for d in (1, -1)]
    oos_wf, log, wf_dates = walk_forward(df, inst, grid, dates)
    print("\n=== 3. Walk-forward (train 12 mois, test 3 mois) ===")
    if len(wf_dates):
        print("Concatenation des periodes de test :", fmt(metrics(oos_wf, wf_dates)))
        for t1, direction in log:
            print(f"  test a partir de {t1} : direction={direction}")
    else:
        print("Pas assez d'historique pour un walk-forward 12+3 mois.")

    print("\n=== 4. Sensibilite au slippage (meilleure config, toute la periode) ===")
    for s in (0.0, 1.0, 2.0, 3.0):
        p = Params(**{**asdict(best), "slippage_ticks": s})
        print(f"  slippage {s:.0f} tick(s)/execution :", fmt(metrics(run_backtest(df, p, inst), dates)))

    print("\n=== 5. Direction au hasard (meme timing), hors-echantillon ===")
    pb = res["placebo"]
    print(f"  reel : {pb['actual']:.0f}$ | pile ou face : {pb['mu']:.0f}$ +/- {pb['sd']:.0f}$ "
          f"| p-value = {pb['pval']:.3f}")

    out = f"trades_{a.instrument}_best.csv"
    res["trades_best"].to_csv(out, index=False)
    print(f"\nTrades ecrits dans {out}")

    if a.plot:
        import matplotlib.pyplot as plt
        daily = res["trades_best"].groupby("date")["pnl"].sum().reindex(dates, fill_value=0.0)
        ax = daily.cumsum().plot(figsize=(10, 4), title="P&L cumule (100 actions, apres couts)")
        ax.axvline(oos_dates[0], color="red", ls="--", label="debut hors-echantillon")
        ax.legend()
        plt.tight_layout()
        plt.savefig("examples/equity_best.png", dpi=120)
        print("Courbe ecrite dans examples/equity_best.png")


if __name__ == "__main__":
    main()
