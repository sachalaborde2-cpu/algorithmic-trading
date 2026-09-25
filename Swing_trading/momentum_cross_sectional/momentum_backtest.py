"""
Backtest de momentum cross-sectionnel (swing, rebalancement mensuel) sur le
meme panier cross-asset de 20 ETF/actions US que ichimoku_daily/ (indices,
secteurs, matieres premieres, obligataire, international, megacaps).

Difference d'architecture avec les strategies precedentes du projet
---------------------------------------------------------------------
Toutes les strategies precedentes (y compris Ichimoku) comparent un
instrument a son propre passe et tradent chaque instrument independamment
(P&L par instrument, notionnel fixe en actions/contrats). Le momentum
cross-sectionnel compare les 20 instruments ENTRE EUX a chaque date de
rebalancement et construit un portefeuille (long les plus forts, short les
plus faibles). Consequence :
- Le P&L est mesure au niveau du PORTEFEUILLE (rendement quotidien en %,
  pas en $ par instrument) -- Sharpe/t-stat/rendement total/max drawdown se
  calculent sur cette serie de rendements.
- Le cout dominant est le TURNOVER au rebalancement mensuel (pas le
  slippage intraday au jour pres) : le modele applique un cout en bps du
  notionnel echange a chaque rebalancement plutot qu'une decomposition
  overnight/intraday comme Ichimoku.
- Un "trade" ici est une position sur UN instrument entre deux dates de
  rebalancement consecutives (une "jambe"), utilise seulement a titre
  diagnostique (n_trades/win_rate/profit_factor) -- la decision reste basee
  sur le rendement quotidien du portefeuille, comme pour Ichimoku.

Signal (convention academique Jegadeesh-Titman "12-1")
---------------------------------------------------------
score_i(t) = close_i(t - skip) / close_i(t - skip - lookback) - 1
Le dernier mois (skip) est exclu du calcul pour eviter l'effet de reversion
court terme documente dans la litterature. Grille testee (2x2, meme esprit
que la grille Ichimoku -- peu de parametres, peu de risque de data-snooping) :
- lookback 12 mois (12-1, la convention academique standard) vs 6 mois (6-1,
  momentum plus rapide, egalement teste dans la litterature, ex. AQR).
- long_short (long le quintile haut, short le quintile bas) vs long_only.

Regles d'execution (aucune fuite de futur)
---------------------------------------------
1. Le score de chaque instrument a la date de rebalancement t est calcule a
   partir des clotures disponibles jusqu'a t inclus (shift() uniquement vers
   le passe).
2. Les poids cibles ainsi determines sont appliques a partir de l'OUVERTURE
   du jour de bourse suivant t (jamais avant, jamais le jour meme).
3. Position tenue (buy-and-hold, pas de re-rebalancement quotidien au poids
   cible) jusqu'au rebalancement suivant.
4. Jour de transition d'un instrument (poids qui change) : le rendement
   capture ce jour-la est OUVERTURE->CLOTURE (position entree a l'ouverture),
   pas CLOTURE(t-1)->CLOTURE(t) -- pas de fuite de futur sur le point
   d'entree. Jour sans changement : rendement CLOTURE->CLOTURE normal.

Usage
-----
    python momentum_backtest.py
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

TICKERS = ["SPY", "QQQ", "IWM", "DIA", "XLE", "XLF", "XLK", "XLV", "XLY", "XLP",
           "GLD", "SLV", "USO", "TLT", "IEF", "EFA", "EEM", "AAPL", "JPM", "XOM"]

TRADING_DAYS_PER_MONTH = 21


@dataclass(frozen=True)
class Params:
    lookback_months: int = 12
    skip_months: int = 1
    mode: str = "long_short"   # "long_short" ou "long_only"
    n_long: int = 4
    n_short: int = 4
    cost_bps: float = 2.0      # cout (commission + slippage) par unite de turnover, en bps du notionnel


# --------------------------------------------------------------------------
# Donnees : chargement des 20 instruments, alignes sur un calendrier commun
# --------------------------------------------------------------------------
def load_daily(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_localize(None).dt.normalize()
    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    return df[["date", "open", "close"]]


def load_universe(tickers: list[str] = TICKERS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Charge tous les tickers et aligne sur l'intersection des dates ou TOUS
    les instruments ont une barre (IEF a un historique plus court -> le
    calendrier commun demarre a la premiere date IEF, ~aout 2017)."""
    opens, closes = {}, {}
    for t in tickers:
        d = load_daily(f"data_{t.lower()}/{t}_daily_all.csv")
        opens[t] = d.set_index("date")["open"]
        closes[t] = d.set_index("date")["close"]
    open_df = pd.DataFrame(opens).dropna(how="any").sort_index()
    close_df = pd.DataFrame(closes).dropna(how="any").sort_index()
    common = open_df.index.intersection(close_df.index)
    return open_df.loc[common], close_df.loc[common]


# --------------------------------------------------------------------------
# Signal : score de momentum cross-sectionnel (causal par construction)
# --------------------------------------------------------------------------
def momentum_scores(close_df: pd.DataFrame, p: Params) -> pd.DataFrame:
    skip = p.skip_months * TRADING_DAYS_PER_MONTH
    lookback = p.lookback_months * TRADING_DAYS_PER_MONTH
    far = close_df.shift(skip + lookback)
    near = close_df.shift(skip)
    return near / far - 1.0


def rebalance_dates(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Premier jour de bourse de chaque mois calendaire present dans l'index."""
    s = pd.Series(dates, index=dates)
    first = s.groupby(dates.to_period("M")).min()
    return pd.DatetimeIndex(first.values).sort_values()


def target_weights(scores: pd.DataFrame, rebal_dates: pd.DatetimeIndex, p: Params) -> pd.DataFrame:
    """Poids cibles decides A la date de rebalancement (a appliquer a partir
    du jour de bourse suivant, voir apply logic dans simulate())."""
    w = pd.DataFrame(0.0, index=rebal_dates, columns=scores.columns)
    need = p.n_long + (p.n_short if p.mode == "long_short" else 0)
    for dt in rebal_dates:
        row = scores.loc[dt].dropna()
        if len(row) < need:
            continue  # warmup : pas encore assez d'instruments avec un score valide
        ranked = row.sort_values(ascending=False)
        w.loc[dt, ranked.index[:p.n_long]] = 1.0 / p.n_long
        if p.mode == "long_short":
            w.loc[dt, ranked.index[-p.n_short:]] = -1.0 / p.n_short
    return w


# --------------------------------------------------------------------------
# Moteur : rendement quotidien du portefeuille + jambes par instrument
# --------------------------------------------------------------------------
def simulate(open_df: pd.DataFrame, close_df: pd.DataFrame, weights_at_rebal: pd.DataFrame,
            p: Params) -> tuple[pd.Series, pd.DataFrame]:
    """Renvoie (daily_ret, trades) :
      - daily_ret : rendement simple quotidien du portefeuille (apres couts).
      - trades : une ligne par jambe instrument (poids constant entre deux
        rebalancements), pnl en rendement brut (avant couts, diagnostique
        uniquement -- les couts restent au niveau portefeuille)."""
    dates = close_df.index
    tickers = close_df.columns

    w_signal = weights_at_rebal.reindex(dates).ffill().fillna(0.0)  # connu a la cloture du jour
    w_applied = w_signal.shift(1).fillna(0.0)                        # applique a partir du jour suivant (open)

    o = open_df.to_numpy()
    c = close_df.to_numpy()
    prev_c = np.vstack([np.full((1, len(tickers)), np.nan), c[:-1]])
    close_to_close = c / prev_c - 1.0
    open_to_close = c / o - 1.0

    w_arr = w_applied.to_numpy()
    w_prev_arr = np.vstack([np.zeros((1, len(tickers))), w_arr[:-1]])
    changed = w_arr != w_prev_arr
    ret_per_ticker = np.where(changed, open_to_close, close_to_close)
    ret_per_ticker = np.nan_to_num(ret_per_ticker, nan=0.0)

    gross_contrib = w_arr * ret_per_ticker
    turnover = np.abs(w_arr - w_prev_arr).sum(axis=1)
    cost = turnover * (p.cost_bps / 1e4)
    port_ret = gross_contrib.sum(axis=1) - cost
    daily_ret = pd.Series(port_ret, index=dates)

    trades_rows = []
    for j, tk in enumerate(tickers):
        col = w_arr[:, j]
        i = 0
        n = len(dates)
        while i < n:
            if col[i] == 0.0:
                i += 1
                continue
            side = col[i]
            k = i
            while k + 1 < n and col[k + 1] == side:
                k += 1
            leg_ret = float(np.prod(1.0 + ret_per_ticker[i:k + 1, j]) - 1.0)
            trades_rows.append({
                "ticker": tk, "side": 1 if side > 0 else -1,
                "entry_time": dates[i], "exit_time": dates[k],
                "weight": side, "pnl": leg_ret,
            })
            i = k + 1
    trades = pd.DataFrame(trades_rows, columns=["ticker", "side", "entry_time", "exit_time", "weight", "pnl"])
    return daily_ret, trades


def randomize_selection(scores: pd.DataFrame, rebal_dates: pd.DatetimeIndex, p: Params,
                        rng: np.random.Generator) -> pd.DataFrame:
    """Meme dates de rebalancement, meme taille de panier (n_long/n_short),
    mais instruments choisis AU HASARD parmi ceux qui ont un score valide a
    cette date (au lieu d'etre classes par momentum). Teste si le CLASSEMENT
    par momentum apporte de la valeur par rapport a un choix aleatoire du
    meme nombre d'instruments, au meme rythme de rebalancement."""
    w = pd.DataFrame(0.0, index=rebal_dates, columns=scores.columns)
    need = p.n_long + (p.n_short if p.mode == "long_short" else 0)
    for dt in rebal_dates:
        valid = scores.loc[dt].dropna().index.to_numpy()
        if len(valid) < need:
            continue
        pick = rng.choice(valid, size=need, replace=False)
        longs, shorts = pick[:p.n_long], pick[p.n_long:p.n_long + p.n_short]
        w.loc[dt, longs] = 1.0 / p.n_long
        if p.mode == "long_short":
            w.loc[dt, shorts] = -1.0 / p.n_short
    return w


# --------------------------------------------------------------------------
# Metriques (rendements de portefeuille, pas de $ par instrument)
# --------------------------------------------------------------------------
def sel_daily(daily_ret: pd.Series, dates: pd.DatetimeIndex) -> pd.Series:
    return daily_ret.reindex(dates, fill_value=0.0)


def sel_trades(trades: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    return trades[trades["exit_time"].isin(dates)]


def metrics(daily_ret: pd.Series, trades: pd.DataFrame) -> dict:
    if len(daily_ret) == 0:
        return {"n_trades": len(trades)}
    eq = np.concatenate([[1.0], (1.0 + daily_ret).cumprod().to_numpy()])
    gains = trades.loc[trades["pnl"] > 0, "pnl"].sum() if len(trades) else 0.0
    losses = -trades.loc[trades["pnl"] < 0, "pnl"].sum() if len(trades) else 0.0
    sd = daily_ret.std()
    return {
        "n_trades": len(trades),
        "win_rate": (trades["pnl"] > 0).mean() if len(trades) else np.nan,
        "exp_ret": trades["pnl"].mean() if len(trades) else np.nan,
        "profit_factor": gains / losses if losses > 0 else np.inf,
        "total_ret": eq[-1] - 1.0,
        "sharpe": daily_ret.mean() / sd * np.sqrt(252) if sd > 0 else np.nan,
        "t_stat": daily_ret.mean() / sd * np.sqrt(len(daily_ret)) if sd > 0 else np.nan,
        "max_dd": (eq / np.maximum.accumulate(eq) - 1.0).min(),
    }


def fmt(d: dict) -> str:
    keys = ["n_trades", "win_rate", "exp_ret", "profit_factor", "total_ret", "sharpe", "t_stat", "max_dd"]
    return "  ".join(f"{k}={d[k]:.4f}" if k in d and k != "n_trades" else f"{k}={d.get(k)}" for k in keys)


def walk_forward(all_sims: dict, dates: pd.DatetimeIndex, train_months: int = 12,
                 test_months: int = 3) -> tuple[pd.Series, pd.DataFrame, list, pd.DatetimeIndex]:
    parts, trade_parts, log, test_all = [], [], [], []
    t0 = dates.min()
    while True:
        t1 = t0 + pd.DateOffset(months=train_months)
        t2 = t1 + pd.DateOffset(months=test_months)
        train = dates[(dates >= t0) & (dates < t1)]
        test = dates[(dates >= t1) & (dates < t2)]
        if len(test) == 0:
            break

        def score(p):
            daily, _ = all_sims[p]
            s = metrics(sel_daily(daily, train), pd.DataFrame()).get("sharpe", np.nan)
            return -1e9 if pd.isna(s) else s

        best = max(all_sims, key=score)
        best_daily, best_trades = all_sims[best]
        parts.append(sel_daily(best_daily, test))
        trade_parts.append(sel_trades(best_trades, test))
        test_all.append(test)
        log.append((t1.date(), best))
        t0 = t0 + pd.DateOffset(months=test_months)
    oos_daily = pd.concat(parts) if parts else pd.Series(dtype=float)
    oos_trades = pd.concat(trade_parts) if trade_parts else pd.DataFrame()
    wf_dates = test_all[0].append(test_all[1:]) if test_all else dates[:0]
    return oos_daily, oos_trades, log, wf_dates


def random_selection_test(open_df, close_df, scores, rebal_dates, p, dates, n_sims=300, seed=0):
    real_w = target_weights(scores, rebal_dates, p)
    real_daily, _ = simulate(open_df, close_df, real_w, p)
    actual = sel_daily(real_daily, dates).sum()
    rng = np.random.default_rng(seed)
    sims = []
    for _ in range(n_sims):
        w = randomize_selection(scores, rebal_dates, p, rng)
        d, _ = simulate(open_df, close_df, w, p)
        sims.append(sel_daily(d, dates).sum())
    sims = np.array(sims)
    pval = (np.sum(sims >= actual) + 1) / (n_sims + 1)
    return actual, sims.mean(), sims.std(), pval


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--oos-frac", type=float, default=0.3)
    ap.add_argument("--plot", action="store_true")
    a = ap.parse_args()

    open_df, close_df = load_universe()
    dates = close_df.index
    print(f"\nDonnees : {len(dates)} jours communs aux 20 instruments "
          f"({dates[0].date()} -> {dates[-1].date()})")

    rebal_dates = rebalance_dates(dates)
    print(f"Rebalancements mensuels : {len(rebal_dates)} dates")

    k = int(len(dates) * (1 - a.oos_frac))
    is_dates, oos_dates = dates[:k], dates[k:]
    print(f"In-sample : {is_dates[0].date()} -> {is_dates[-1].date()} | "
          f"Hors-echantillon : {oos_dates[0].date()} -> {oos_dates[-1].date()}")

    grid = [Params(lookback_months=lb, mode=m) for lb in (12, 6) for m in ("long_short", "long_only")]
    all_scores = {lb: momentum_scores(close_df, Params(lookback_months=lb)) for lb in (12, 6)}
    all_weights = {p: target_weights(all_scores[p.lookback_months], rebal_dates, p) for p in grid}
    all_sims = {p: simulate(open_df, close_df, all_weights[p], p) for p in grid}

    rows = []
    for p in grid:
        daily, trades = all_sims[p]
        m_is = metrics(sel_daily(daily, is_dates), sel_trades(trades, is_dates))
        m_oos = metrics(sel_daily(daily, oos_dates), sel_trades(trades, oos_dates))
        rows.append({"lookback": p.lookback_months, "mode": p.mode,
                     "sharpe_IS": m_is.get("sharpe"), "t_IS": m_is.get("t_stat"),
                     "sharpe_OOS": m_oos.get("sharpe"), "total_ret_OOS": m_oos.get("total_ret")})
    table = pd.DataFrame(rows).sort_values("sharpe_IS", ascending=False)
    print(f"\n=== 1. Grille ({len(grid)} configurations testees) ===")
    print(table.round(4).to_string(index=False))

    best = max(grid, key=lambda p: (lambda s: -1e9 if pd.isna(s) else s)(
        metrics(sel_daily(all_sims[p][0], is_dates), pd.DataFrame()).get("sharpe", np.nan)))
    best_daily, best_trades = all_sims[best]
    print(f"\n=== 2. Meilleure config in-sample : {best} ===")
    print("IS  :", fmt(metrics(sel_daily(best_daily, is_dates), sel_trades(best_trades, is_dates))))
    print("OOS :", fmt(metrics(sel_daily(best_daily, oos_dates), sel_trades(best_trades, oos_dates))))

    wf_daily, wf_trades, log, wf_dates = walk_forward(all_sims, dates)
    print("\n=== 3. Walk-forward (train 12 mois, test 3 mois) ===")
    if len(wf_dates):
        print("Concatenation des periodes de test :", fmt(metrics(wf_daily, wf_trades)))
        for t1, p in log:
            print(f"  test a partir de {t1} : lookback={p.lookback_months}, mode={p.mode}")
    else:
        print("Pas assez d'historique pour un walk-forward 12+3 mois.")

    print("\n=== 4. Sensibilite au cout (meilleure config, toute la periode) ===")
    for cb in (0.0, 2.0, 5.0, 10.0):
        p = Params(**{**asdict(best), "cost_bps": cb})
        w = target_weights(all_scores[p.lookback_months], rebal_dates, p)
        d, t = simulate(open_df, close_df, w, p)
        print(f"  cout {cb:.0f} bps/turnover :", fmt(metrics(sel_daily(d, dates), t)))

    print("\n=== 5. Selection aleatoire (meme timing/taille de panier), hors-echantillon ===")
    actual, mu, sd, pval = random_selection_test(open_df, close_df, all_scores[best.lookback_months],
                                                  rebal_dates, best, oos_dates)
    print(f"  reel : {actual:.4f} | selection aleatoire : {mu:.4f} +/- {sd:.4f} | p-value = {pval:.3f}")

    best_trades.to_csv("trades_best.csv", index=False)
    print("\nTrades ecrits dans trades_best.csv")

    if a.plot:
        import matplotlib.pyplot as plt
        eq = (1.0 + sel_daily(best_daily, dates)).cumprod()
        ax = eq.plot(figsize=(10, 4), title="Valeur du portefeuille (base 1.0, apres couts)")
        ax.axvline(oos_dates[0], color="red", ls="--", label="debut hors-echantillon")
        ax.legend()
        plt.tight_layout()
        plt.savefig("examples/equity_best.png", dpi=120)
        print("Courbe ecrite dans examples/equity_best.png")


if __name__ == "__main__":
    main()
