"""
Backtest de selection cross-sectionnelle de l'instrument qui recoit chaque
nuit l'edge overnight structurel deja valide (voir Intraday_trading/overnight_drift/),
sur le sous-groupe des 4 indices/ETF larges US ou cet edge est etabli
(SPY/QQQ/IWM/DIA -- voir STRATEGIES.md #10). Pas de cartographie exploratoire
secondaire ici : l'edge overnight lui-meme est deja rejete sur les 16 autres
tickers cross-asset (overnight_drift_stocks #11, overnight_drift_baskets #15),
donc etendre la selection a ces instruments n'a pas de sens pour cette question.

Pourquoi cette combinaison (et pas un nouveau facteur academique isole)
-------------------------------------------------------------------------
Cinq filtres calendaires purs de l'edge overnight (#11, #14, #15, #16, #17)
ont deja ete rejetes -- cette dimension (QUAND trader un instrument fixe) est
epuisee. Ce backtest change de dimension : QUEL instrument trader une nuit
donnee, parmi les 4 ou l'edge est deja valide. Combine deux elements deja
etudies separement dans ce projet plutot que d'en importer un nouveau :
- le moteur de comparaison cross-sectionnelle construit pour le momentum
  (#13 -- comparer plusieurs instruments entre eux au meme instant, jamais un
  instrument a son propre passe) ;
- le regime de tendance Kumo Ichimoku deja backteste comme filtre en #14
  (rejete comme filtre TEMPOREL d'un instrument fixe -- ici il sert de
  CONFIRMATION dans une comparaison relative entre instruments, un role
  jamais teste).
Idee suggeree par l'utilisateur le 2026-09-25 : attendre que plusieurs
confirmations soient simultanement "au vert" sur un actif donne parmi
plusieurs suivis, l'actif qui declenche pouvant changer d'un soir a l'autre.

Mecanisme (pre-enregistre avant tout resultat OOS/placebo, voir plan)
----------------------------------------------------------------------
Chaque nuit, a la cloture du jour J, pour chacun des 4 instruments :
1. Score de force relative (convention momentum "6-1" : lookback 6 mois,
   skip 1 mois -- cause par construction, ne depend que de cloture <= J).
2. Regime de tendance Kumo Ichimoku (identique a overnight_drift_regime_filtered/,
   cause par construction, decalage 26 jours).

Grille a 3 configurations (baseline obligatoire pour trancher si la
selection ajoute quelque chose) :
- unfiltered_baseline           : trade les 4 instruments chaque nuit
                                   (reproduit exactement overnight_drift #10).
- cross_sectional_only          : trade seulement les n_top instruments les
                                   mieux classes par score cette nuit-la.
- cross_sectional_plus_regime   : trade seulement les instruments qui sont A
                                   LA FOIS dans le top ET en regime bullish
                                   (peut etre 0, 1 ou n_top instruments selon
                                   les nuits).
Si cross_sectional_plus_regime ne bat pas cross_sectional_only, le regime
n'ajoute rien : la valeur ajoutee attendue est la selection relative entre
instruments, pas un filtre de regime deguise (voir STRATEGIES.md, point de
vigilance #3 pour #18).

Regles d'execution (aucune fuite de futur)
---------------------------------------------
1. Le score et le regime du jour J sont calcules a partir de barres connues
   a la cloture de J uniquement (shift() vers le passe, Kumo decale de 26).
2. La selection ainsi decidee determine quels instruments recoivent la
   position overnight cloture(J) -> ouverture(J+1) -- jamais avant, jamais
   apres.
3. Position toujours LONGUE (la direction longue de l'edge overnight est
   deja validee par #10 ; ce backtest ne re-teste pas la direction, il ne
   teste que la selection de l'instrument).
4. Slippage/commission appliques a chaque entree/sortie reelle (instrument
   effectivement selectionne cette nuit-la), jamais sur les nuits/instruments
   ecartes.

Usage
-----
    python overnight_selection_backtest.py
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

TICKERS = ["SPY", "QQQ", "IWM", "DIA"]
TRADING_DAYS_PER_MONTH = 21


# --------------------------------------------------------------------------
# Parametres
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Instrument:
    tick: float
    point_value: float
    commission_side: float


INSTRUMENTS = {
    "SPY": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "QQQ": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "IWM": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "DIA": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
}


@dataclass(frozen=True)
class Params:
    config: str = "unfiltered_baseline"  # "unfiltered_baseline" | "cross_sectional_only" | "cross_sectional_plus_regime"
    lookback_months: int = 6
    skip_months: int = 1
    n_top: int = 2
    tenkan_period: int = 9
    kijun_period: int = 26
    senkou_b_period: int = 52
    displacement: int = 26
    slippage_ticks: float = 1.0


CONFIGS = ["unfiltered_baseline", "cross_sectional_only", "cross_sectional_plus_regime"]
TRADE_COLS = ["date", "ticker", "side", "entry_time", "exit_time", "entry", "exit",
              "pts", "r_mult", "pnl"]


# --------------------------------------------------------------------------
# Donnees : 4 instruments, calendrier commun verifie (voir load_universe)
# --------------------------------------------------------------------------
def load_daily(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_localize(None).dt.normalize()
    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    return df[["date", "open", "high", "low", "close"]]


def load_universe(tickers: list[str] = TICKERS) -> dict[str, pd.DataFrame]:
    """Charge les 4 instruments et verifie qu'ils partagent EXACTEMENT le
    meme calendrier de jours de bourse (deja confirme pour SPY/QQQ/IWM/DIA :
    2512 jours communs, 2016-09-27 -> 2026-09-24). Leve une erreur explicite
    si une future mise a jour des donnees desaligne les calendriers, plutot
    que de continuer silencieusement sur un decalage errone."""
    frames = {t: load_daily(f"data_{t.lower()}/{t}_daily_all.csv") for t in tickers}
    ref = frames[tickers[0]]["date"]
    for t in tickers[1:]:
        if not frames[t]["date"].equals(ref):
            raise ValueError(f"Calendrier de {t} desaligne avec {tickers[0]} : "
                             "reintersecter les dates avant de continuer.")
    return frames


# --------------------------------------------------------------------------
# Signal 1 : score de momentum cross-sectionnel (cause par construction)
# --------------------------------------------------------------------------
def momentum_score_series(df: pd.DataFrame, p: Params) -> pd.Series:
    skip = p.skip_months * TRADING_DAYS_PER_MONTH
    lookback = p.lookback_months * TRADING_DAYS_PER_MONTH
    close = df["close"]
    return close.shift(skip) / close.shift(skip + lookback) - 1.0


# --------------------------------------------------------------------------
# Signal 2 : regime Kumo Ichimoku (identique a overnight_drift_regime_filtered/)
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
    cloud_top, cloud_bottom = kumo_bounds(df, p)
    close = df["close"]
    regime = pd.Series("neutral", index=df.index)
    regime[close > cloud_top] = "bullish"
    regime[close < cloud_bottom] = "bearish"
    warmup = p.senkou_b_period + p.displacement
    regime.iloc[:warmup] = "neutral"
    return regime


def build_signals(frames: dict[str, pd.DataFrame], p: Params) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Renvoie (scores, regime, close, open_), 4 DataFrames alignes sur le
    meme index entier (positions 0..n-1), une colonne par instrument."""
    tickers = list(frames.keys())
    scores = pd.DataFrame({t: momentum_score_series(frames[t], p) for t in tickers})
    regime = pd.DataFrame({t: regime_series(frames[t], p) for t in tickers})
    close = pd.DataFrame({t: frames[t]["close"] for t in tickers})
    open_ = pd.DataFrame({t: frames[t]["open"] for t in tickers})
    return scores, regime, close, open_


# --------------------------------------------------------------------------
# Selection : quel(s) instrument(s) recoivent la position overnight ce soir
# --------------------------------------------------------------------------
def select_tickers(scores_row: pd.Series, regime_row: pd.Series, p: Params) -> list[str]:
    """Decide, a partir des donnees connues a la cloture du jour i, quels
    instruments recoivent la position overnight de ce soir. `unfiltered_baseline`
    ne depend jamais des scores/regime (reproduit exactement overnight_drift,
    y compris pendant le warmup du momentum/Kumo)."""
    if p.config == "unfiltered_baseline":
        return list(scores_row.index)

    valid = scores_row.dropna()
    if len(valid) < p.n_top:
        return []
    top = valid.sort_values(ascending=False).index[:p.n_top].tolist()

    if p.config == "cross_sectional_only":
        return top
    if p.config == "cross_sectional_plus_regime":
        return [t for t in top if regime_row[t] == "bullish"]
    raise ValueError(f"config inconnue : {p.config}")


def selections_for_config(scores: pd.DataFrame, regime: pd.DataFrame, p: Params) -> list[list[str]]:
    return [select_tickers(scores.iloc[i], regime.iloc[i], p) for i in range(len(scores))]


def randomize_selection(scores: pd.DataFrame, regime: pd.DataFrame, p: Params,
                        rng: np.random.Generator) -> list[list[str]]:
    """Meme nombre d'instruments retenus chaque nuit que la config reelle,
    mais choisis AU HASARD parmi le pool eligible (les 4 instruments pour
    unfiltered_baseline, ceux avec un score valide sinon) au lieu d'etre
    classes par le critere. Teste si la SELECTION apporte une info au-dela
    du simple fait de trader ce nombre d'instruments cette nuit-la."""
    tickers = list(scores.columns)
    out = []
    for i in range(len(scores)):
        real = select_tickers(scores.iloc[i], regime.iloc[i], p)
        k = len(real)
        if k == 0:
            out.append([])
            continue
        pool = tickers if p.config == "unfiltered_baseline" else scores.iloc[i].dropna().index.to_numpy()
        if len(pool) < k:
            out.append([])
            continue
        out.append(rng.choice(pool, size=k, replace=False).tolist())
    return out


# --------------------------------------------------------------------------
# Moteur : simule les trades overnight resultant d'une selection donnee
# --------------------------------------------------------------------------
def simulate(frames: dict[str, pd.DataFrame], close: pd.DataFrame, open_: pd.DataFrame,
            selections: list[list[str]], p: Params, instruments: dict[str, Instrument] = INSTRUMENTS) -> pd.DataFrame:
    tickers = list(frames.keys())
    dates = frames[tickers[0]]["date"].to_numpy()
    n = len(dates)
    rows = []
    for i in range(n - 1):
        for t in selections[i]:
            inst = instruments[t]
            slip = inst.tick * p.slippage_ticks
            entry_px = close[t].iloc[i] + slip
            exit_px = open_[t].iloc[i + 1] - slip
            pts = exit_px - entry_px
            pnl = pts * inst.point_value - 2 * inst.commission_side
            risk_pts = 2 * slip if slip > 0 else 1.0
            rows.append({
                "date": dates[i + 1], "ticker": t, "side": 1,
                "entry_time": dates[i], "exit_time": dates[i + 1],
                "entry": entry_px, "exit": exit_px, "pts": pts,
                "r_mult": pts / risk_pts, "pnl": pnl,
            })
    return pd.DataFrame(rows, columns=TRADE_COLS)


def run_config(frames, close, open_, scores, regime, p, instruments=INSTRUMENTS) -> pd.DataFrame:
    return simulate(frames, close, open_, selections_for_config(scores, regime, p), p, instruments)


# --------------------------------------------------------------------------
# Metriques et tests de robustesse (memes conventions que les strategies
# precedentes du projet)
# --------------------------------------------------------------------------
def sel(trades: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    return trades[trades["date"].isin(dates)]


def metrics(trades: pd.DataFrame, dates: pd.DatetimeIndex) -> dict:
    if len(dates) == 0:
        return {"n_trades": len(trades)}
    daily = trades.groupby("date")["pnl"].sum().reindex(dates, fill_value=0.0) if len(trades) else \
        pd.Series(0.0, index=dates)
    eq = np.concatenate([[0.0], daily.cumsum().to_numpy()])
    gains = trades.loc[trades["pnl"] > 0, "pnl"].sum() if len(trades) else 0.0
    losses = -trades.loc[trades["pnl"] < 0, "pnl"].sum() if len(trades) else 0.0
    sd = daily.std()
    return {
        "n_trades": len(trades),
        "avg_selected": trades.groupby("date").size().mean() if len(trades) else 0.0,
        "win_rate": (trades["pnl"] > 0).mean() if len(trades) else np.nan,
        "exp_$": trades["pnl"].mean() if len(trades) else np.nan,
        "profit_factor": gains / losses if losses > 0 else np.inf,
        "total_$": trades["pnl"].sum() if len(trades) else 0.0,
        "sharpe": daily.mean() / sd * np.sqrt(252) if sd > 0 else np.nan,
        "t_stat": daily.mean() / sd * np.sqrt(len(daily)) if sd > 0 else np.nan,
        "max_dd_$": (eq - np.maximum.accumulate(eq)).min(),
    }


def fmt(d: dict) -> str:
    keys = ["n_trades", "avg_selected", "win_rate", "exp_$", "profit_factor",
            "total_$", "sharpe", "t_stat", "max_dd_$"]
    return "  ".join(f"{k}={d[k]:.2f}" if k in d and k != "n_trades" else f"{k}={d.get(k)}"
                     for k in keys)


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
        log.append((t1.date(), best.config))
        t0 = t0 + pd.DateOffset(months=test_months)
    oos = pd.concat(parts) if parts else pd.DataFrame(columns=TRADE_COLS)
    wf_dates = test_all[0].append(test_all[1:]) if test_all else dates[:0]
    return oos, log, wf_dates


def random_selection_test(frames, close, open_, scores, regime, p, dates,
                          n_sims: int = 300, seed: int = 0):
    real_trades = run_config(frames, close, open_, scores, regime, p)
    actual = sel(real_trades, dates)["pnl"].sum()
    rng = np.random.default_rng(seed)
    sims = []
    for _ in range(n_sims):
        rand_sel = randomize_selection(scores, regime, p, rng)
        t = simulate(frames, close, open_, rand_sel, p)
        sims.append(sel(t, dates)["pnl"].sum())
    sims = np.array(sims)
    pval = (np.sum(sims >= actual) + 1) / (n_sims + 1)
    return actual, sims.mean(), sims.std(), pval


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--oos-frac", type=float, default=0.3)
    ap.add_argument("--plot", action="store_true")
    a = ap.parse_args()

    frames = load_universe()
    p_ref = Params()
    scores, regime, close, open_ = build_signals(frames, p_ref)
    all_dates = frames[TICKERS[0]]["date"]
    dates = pd.DatetimeIndex(all_dates)[:-1]  # jour de decision (pas d'ouverture J+1 pour le dernier)
    print(f"\nDonnees : {len(all_dates)} jours communs aux 4 instruments "
          f"({all_dates.iloc[0].date()} -> {all_dates.iloc[-1].date()})")

    k = int(len(dates) * (1 - a.oos_frac))
    is_dates, oos_dates = dates[:k], dates[k:]
    print(f"In-sample : {is_dates[0].date()} -> {is_dates[-1].date()} | "
          f"Hors-echantillon : {oos_dates[0].date()} -> {oos_dates[-1].date()}")

    grid = [Params(config=c) for c in CONFIGS]
    all_trades = {p: run_config(frames, close, open_, scores, regime, p) for p in grid}

    rows = []
    for p in grid:
        m_is = metrics(sel(all_trades[p], is_dates), is_dates)
        m_oos = metrics(sel(all_trades[p], oos_dates), oos_dates)
        rows.append({"config": p.config,
                     "n_IS": m_is.get("n_trades"), "avg_sel_IS": m_is.get("avg_selected"),
                     "sharpe_IS": m_is.get("sharpe"), "t_IS": m_is.get("t_stat"),
                     "n_OOS": m_oos.get("n_trades"), "sharpe_OOS": m_oos.get("sharpe")})
    table = pd.DataFrame(rows)
    print(f"\n=== 1. Grille ({len(grid)} configurations testees) ===")
    print(table.round(3).to_string(index=False))

    best = max(grid, key=lambda p: (lambda s: -1e9 if pd.isna(s) else s)(
        metrics(sel(all_trades[p], is_dates), is_dates).get("sharpe", np.nan)))
    tr = all_trades[best]
    print(f"\n=== 2. Meilleure config in-sample : {best.config} ===")
    print("IS  :", fmt(metrics(sel(tr, is_dates), is_dates)))
    print("OOS :", fmt(metrics(sel(tr, oos_dates), oos_dates)))

    oos_wf, log, wf_dates = walk_forward(all_trades, dates)
    print("\n=== 3. Walk-forward (train 12 mois, test 3 mois) ===")
    if len(wf_dates):
        print("Concatenation des periodes de test :", fmt(metrics(oos_wf, wf_dates)))
        for t1, cfg in log:
            print(f"  test a partir de {t1} : config={cfg}")
    else:
        print("Pas assez d'historique pour un walk-forward 12+3 mois.")

    print("\n=== 4. Sensibilite au slippage (meilleure config, toute la periode) ===")
    for s in (0.0, 1.0, 2.0, 3.0):
        p = Params(**{**asdict(best), "slippage_ticks": s})
        t = run_config(frames, close, open_, scores, regime, p)
        print(f"  slippage {s:.0f} tick(s)/execution :", fmt(metrics(t, dates)))

    print("\n=== 5. Selection aleatoire (meme nombre d'instruments/nuit), hors-echantillon ===")
    actual, mu, sd, pval = random_selection_test(frames, close, open_, scores, regime, best, oos_dates)
    print(f"  reel : {actual:.0f}$ | selection aleatoire : {mu:.0f}$ +/- {sd:.0f}$ | p-value = {pval:.3f}")
    if best.config == "unfiltered_baseline":
        print("  NB : la config gagnante ne selectionne rien (4/4 chaque nuit) -- "
              "le test de selection aleatoire est degenere (sd=0), la sequence de la "
              "grille elle-meme (baseline gagne) suffit deja a repondre a la question.")

    full = sel(tr, dates)
    full.to_csv("trades_best.csv", index=False)
    print("\nTrades ecrits dans trades_best.csv")

    if a.plot:
        import matplotlib.pyplot as plt
        daily = full.groupby("date")["pnl"].sum().reindex(dates, fill_value=0.0)
        ax = daily.cumsum().plot(figsize=(10, 4), title="P&L cumule (100 actions/instrument, apres couts)")
        ax.axvline(oos_dates[0], color="red", ls="--", label="debut hors-echantillon")
        ax.legend()
        plt.tight_layout()
        plt.savefig("examples/equity_best.png", dpi=120)
        print("Courbe ecrite dans examples/equity_best.png")


if __name__ == "__main__":
    main()
