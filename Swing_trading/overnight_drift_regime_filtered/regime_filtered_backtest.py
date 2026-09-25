"""
Backtest de l'edge overnight structurel (voir Intraday_trading/overnight_drift/)
FILTRE par le regime de tendance Ichimoku (position du prix par rapport au
Kumo/nuage), en barres journalieres, sur le sous-groupe des 4 indices larges
US (SPY/QQQ/IWM/DIA) -- hypothese principale -- puis sur les 16 instruments
restants du panier cross-asset des 20 (secteurs, matieres premieres,
obligataire, international, megacaps) -- cartographie exploratoire
secondaire, jamais melangee au verdict principal (voir STRATEGIES.md #14).

Pourquoi cette combinaison (et pas un nouveau facteur academique isole)
-------------------------------------------------------------------------
`overnight_drift` (#10) est le seul edge valide du projet, mais UNIQUEMENT
sur des paniers larges indices/ETF -- rejete sur les actions individuelles
(#11). Ichimoku (#12), teste comme signal directionnel autonome (croisement
Tenkan/Kijun ou cassure du Kumo), a echoue la correction multiple-testing
meme sur son sous-groupe le plus favorable (les 4 indices). Mais le rejet de
#12 porte sur Ichimoku comme SIGNAL D'ENTREE -- sa legitimite comme simple
FILTRE DE REGIME (rester a l'ecart d'un edge existant quand la tendance de
fond est defavorable) n'a jamais ete testee separement. C'est la combinaison
inedite proposee ici : le filtre ne cree aucune position, il ne fait que
conditionner l'entree deja definie par overnight_drift.

Regle du filtre (symetrique, aucun sens privilegie a priori)
----------------------------------------------------------------
Le nuage (Kumo) du jour J (clos, decale de 26 jours, donc aucune fuite de
futur) definit le regime :
  - "bullish" si close(J) > haut du nuage.
  - "bearish" si close(J) < bas du nuage.
  - "neutral" (dans le nuage) sinon.
Deux configurations testees, strictement symetriques (aucune ne privilegie
"bullish" a priori, conformement a l'auto-critique documentee dans
STRATEGIES.md) :
  - filter_regime="bullish" : n'entre en position overnight LONG que si le
    regime du jour J (jour de la cloture d'entree) est bullish, reste a
    plat sinon.
  - filter_regime="bearish" : meme logique, mais entre uniquement si le
    regime est bearish (hypothese symetrique : "fuite vers la securite"
    overnight en tendance baissiere).
Une config "unfiltered" (= overnight_drift original, aucun filtre) sert de
reference directe pour mesurer si le filtre ameliore ou degrade le brut.

Regles d'execution (aucune fuite de futur, memes conventions que
ichimoku_backtest.py et overnight_backtest.py)
-------------------------------------------------------------------------
1. Le regime du jour J est calcule a la CLOTURE de J (Kumo decale de 26
   jours -> ne depend que de barres 0..J-26).
2. La position overnight (clotureJ -> ouvertureJ+1) n'est prise QUE si le
   regime a la cloture de J correspond au filtre -- decision prise avant la
   cloture, donc avant l'entree, aucune fuite de futur.
3. Un jour = un trade au plus (comme overnight_backtest.py), jamais de
   position tenue plus d'une nuit.
4. Slippage/commission appliques a chaque entree/sortie reelle (jours ou une
   position overnight est effectivement prise), jamais sur les jours filtres
   a plat.

Usage
-----
    python regime_filtered_backtest.py --instrument SPY
    python regime_filtered_backtest.py --instrument SPY --secondary  (panier des 16 restants)
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
    # Hypothese principale : indices larges (sous-groupe Bonferroni deja
    # defini pour Ichimoku #12, seule classe avec une legitimite a priori
    # a la fois pour overnight_drift et pour un filtre de tendance Ichimoku).
    "SPY": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "QQQ": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "IWM": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "DIA": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    # Cartographie exploratoire secondaire (memes 20 tickers qu'Ichimoku/
    # momentum) -- jamais utilisee pour le verdict principal.
    "XLE": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "XLF": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "XLK": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "XLV": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "XLY": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "XLP": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "GLD": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "SLV": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "USO": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "TLT": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "IEF": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "EFA": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "EEM": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "AAPL": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "JPM": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "XOM": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
}

PRIMARY_GROUP = ["SPY", "QQQ", "IWM", "DIA"]
SECONDARY_GROUP = [t for t in INSTRUMENTS if t not in PRIMARY_GROUP]


@dataclass(frozen=True)
class Params:
    filter_regime: str = "unfiltered"  # "unfiltered", "bullish", "bearish"
    tenkan_period: int = 9
    kijun_period: int = 26
    senkou_b_period: int = 52
    displacement: int = 26
    slippage_ticks: float = 1.0


# --------------------------------------------------------------------------
# Donnees : barres journalieres (memes fichiers que ichimoku_daily/)
# --------------------------------------------------------------------------
def load_daily(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_localize(None).dt.normalize()
    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    return df[["date", "open", "high", "low", "close", "volume"]]


# --------------------------------------------------------------------------
# Kumo Ichimoku (identique a ichimoku_backtest.py -- causal par construction)
# --------------------------------------------------------------------------
def kumo_bounds(df: pd.DataFrame, p: Params) -> tuple[pd.Series, pd.Series]:
    high, low = df["high"], df["low"]
    tenkan = (high.rolling(p.tenkan_period).max() + low.rolling(p.tenkan_period).min()) / 2
    kijun = (high.rolling(p.kijun_period).max() + low.rolling(p.kijun_period).min()) / 2
    senkou_a_raw = (tenkan + kijun) / 2
    senkou_b_raw = (high.rolling(p.senkou_b_period).max() + low.rolling(p.senkou_b_period).min()) / 2
    senkou_a = senkou_a_raw.shift(p.displacement)
    senkou_b = senkou_b_raw.shift(p.displacement)
    cloud_top = pd.concat([senkou_a, senkou_b], axis=1).max(axis=1)
    cloud_bottom = pd.concat([senkou_a, senkou_b], axis=1).min(axis=1)
    return cloud_top, cloud_bottom


def regime_series(df: pd.DataFrame, p: Params) -> pd.Series:
    """Regime a la CLOTURE de chaque jour : "bullish"/"bearish"/"neutral".
    Warmup (avant que le Kumo soit disponible) -> "neutral" (aucune entree
    filtree possible tant que le nuage n'est pas defini)."""
    cloud_top, cloud_bottom = kumo_bounds(df, p)
    close = df["close"]
    regime = pd.Series("neutral", index=df.index)
    regime[close > cloud_top] = "bullish"
    regime[close < cloud_bottom] = "bearish"
    warmup = p.senkou_b_period + p.displacement
    regime.iloc[:warmup] = "neutral"
    return regime


# --------------------------------------------------------------------------
# Moteur : un jour = un trade overnight au plus (entree filtree par regime)
# --------------------------------------------------------------------------
TRADE_COLS = ["date", "side", "entry_time", "exit_time", "entry", "exit",
              "pts", "r_mult", "regime", "pnl", "reason"]


def run_backtest(df: pd.DataFrame, p: Params, inst: Instrument,
                 rng: np.random.Generator | None = None) -> pd.DataFrame:
    """Position overnight LONG (side=+1) prise entre la cloture du jour i et
    l'ouverture du jour i+1, uniquement si le regime a la cloture du jour i
    correspond a `p.filter_regime` ("unfiltered" = toujours). Si `rng` est
    fourni (test placebo), le FILTRE (quels jours sont trades) est conserve
    a l'identique -- seul le SENS de la position (long/short) est tire au
    hasard, exactement le principe de overnight_backtest.py : on isole si la
    DIRECTION choisie (long) apporte une info, pas si le filtre de timing
    apporte une info (deja teste separement via la comparaison filtre vs
    unfiltered)."""
    regime = regime_series(df, p)
    slip = inst.tick * p.slippage_ticks
    close = df["close"].to_numpy()
    open_ = df["open"].to_numpy()
    dates = df["date"].to_numpy()
    n = len(df)

    rows = []
    for i in range(n - 1):
        if p.filter_regime != "unfiltered" and regime.iloc[i] != p.filter_regime:
            continue
        side = 1 if rng is None else int(rng.choice([-1, 1]))
        entry_px = close[i] + side * slip
        exit_px = open_[i + 1] - side * slip
        pts = (exit_px - entry_px) * side
        pnl = pts * inst.point_value - 2 * inst.commission_side
        risk_pts = 2 * slip if slip > 0 else 1.0
        rows.append({
            "date": dates[i + 1], "side": side,
            "entry_time": dates[i], "exit_time": dates[i + 1],
            "entry": entry_px, "exit": exit_px, "pts": pts,
            "r_mult": pts / risk_pts, "regime": regime.iloc[i],
            "pnl": pnl, "reason": p.filter_regime,
        })
    return pd.DataFrame(rows, columns=TRADE_COLS)


# --------------------------------------------------------------------------
# Metriques et tests de robustesse (memes conventions que les strategies
# precedentes)
# --------------------------------------------------------------------------
def sel(trades: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    return trades[trades["date"].isin(dates)]


def metrics(trades: pd.DataFrame, dates: pd.DatetimeIndex) -> dict:
    daily = trades.groupby("date")["pnl"].sum().reindex(dates, fill_value=0.0) if len(trades) else \
        pd.Series(0.0, index=dates)
    if len(trades) == 0:
        return {"n_trades": 0, "sharpe": np.nan, "t_stat": np.nan}
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
        log.append((t1.date(), best.filter_regime))
        t0 = t0 + pd.DateOffset(months=test_months)
    oos = pd.concat(parts) if parts else pd.DataFrame(columns=TRADE_COLS)
    wf_dates = test_all[0].append(test_all[1:]) if test_all else dates[:0]
    return oos, log, wf_dates


def random_direction_test(df, p, inst, dates, n_sims=300, seed=0):
    """Meme filtre de regime (memes jours retenus), direction tiree a pile
    ou face. Si le sens reel (long systematique) ne bat pas ca, la
    direction n'apporte aucune information -- teste separement du filtre de
    timing lui-meme (compare via la table de resultats filtre vs
    unfiltered)."""
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

    grid = [Params(filter_regime=r) for r in ("unfiltered", "bullish", "bearish")]
    all_trades = {p: run_backtest(df, p, inst) for p in grid}

    rows = []
    for p in grid:
        m_is = metrics(sel(all_trades[p], is_dates), is_dates)
        m_oos = metrics(sel(all_trades[p], oos_dates), oos_dates)
        rows.append({"filter": p.filter_regime,
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
    ap.add_argument("--instrument", default="SPY", choices=INSTRUMENTS)
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
    print(f"\n=== 2. Meilleure config in-sample : filter={best.filter_regime} ===")
    print("IS  :", fmt(res["m_is"]))
    print("OOS :", fmt(res["m_oos"]))

    inst = INSTRUMENTS[a.instrument]
    grid = [Params(filter_regime=r) for r in ("unfiltered", "bullish", "bearish")]
    oos_wf, log, wf_dates = walk_forward(df, inst, grid, dates)
    print("\n=== 3. Walk-forward (train 12 mois, test 3 mois) ===")
    if len(wf_dates):
        print("Concatenation des periodes de test :", fmt(metrics(oos_wf, wf_dates)))
        for t1, filt in log:
            print(f"  test a partir de {t1} : filter={filt}")
    else:
        print("Pas assez d'historique pour un walk-forward 12+3 mois.")

    print("\n=== 4. Sensibilite au slippage (meilleure config, toute la periode) ===")
    for s in (0.0, 1.0, 2.0, 3.0):
        p = Params(**{**asdict(best), "slippage_ticks": s})
        print(f"  slippage {s:.0f} tick(s)/execution :", fmt(metrics(run_backtest(df, p, inst), dates)))

    print("\n=== 5. Direction au hasard (meme filtre de regime), hors-echantillon ===")
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
