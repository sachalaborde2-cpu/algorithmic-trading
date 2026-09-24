"""
backtest.py

Moteur de backtest pour une stratégie de pairs trading basée sur le z-score
du spread. Logique volontairement proche de ton infra Golden Cross:
signaux -> positions -> P&L -> métriques (CAGR, Sharpe, max drawdown).

Règles de trading:
- z-score > entry_z  -> spread trop haut -> short A, long B (short le spread)
- z-score < -entry_z -> spread trop bas  -> long A, short B (long le spread)
- |z-score| < exit_z -> on débouclé la position (retour à la moyenne atteint)
- |z-score| > stop_z -> stop-loss: la cointégration est peut-être cassée,
  on sort en perte plutôt que d'attendre un retour qui n'arrivera jamais
"""

import numpy as np
import pandas as pd


def zscore(spread: pd.Series, lookback: int = 20) -> pd.Series:
    """Z-score glissant du spread (rolling mean/std), pas z-score sur tout l'historique
    pour éviter le look-ahead bias."""
    mean = spread.rolling(lookback).mean()
    std = spread.rolling(lookback).std()
    return (spread - mean) / std


def generate_signals(
    z: pd.Series,
    entry_z: float = 2.0,
    exit_z: float = 0.5,
    stop_z: float = 4.0,
) -> pd.Series:
    """
    Retourne une série de positions sur le SPREAD:
     +1 = long le spread (long A, short B*beta)
     -1 = short le spread (short A, long B*beta)
      0 = flat

    Implémentation stateful (pas vectorisée) volontairement, pour rester
    lisible et facile à auditer avant de brancher sur de l'argent réel.
    """
    position = 0
    positions = []

    for zi in z:
        if np.isnan(zi):
            positions.append(0)
            continue

        if position == 0:
            if zi > entry_z:
                position = -1
            elif zi < -entry_z:
                position = 1
        else:
            # stop-loss: la divergence s'aggrave au lieu de revenir
            if abs(zi) > stop_z:
                position = 0
            # sortie normale: retour à la moyenne
            elif abs(zi) < exit_z:
                position = 0

        positions.append(position)

    return pd.Series(positions, index=z.index)


def backtest_pair(
    price_a: pd.Series,
    price_b: pd.Series,
    beta: float,
    lookback: int = 20,
    entry_z: float = 2.0,
    exit_z: float = 0.5,
    stop_z: float = 4.0,
    capital: float = 100_000.0,
    cost_bps: float = 5.0,
) -> dict:
    """
    Backtest complet. cost_bps = coûts de transaction en basis points
    appliqués à chaque changement de position (slippage + commissions).
    """
    log_a = np.log(price_a)
    log_b = np.log(price_b)
    spread = log_a - beta * log_b

    z = zscore(spread, lookback)
    positions = generate_signals(z, entry_z, exit_z, stop_z)

    # P&L: variation du spread * position de la veille (pas de look-ahead)
    spread_ret = spread.diff()
    strat_ret = positions.shift(1) * spread_ret

    # coûts de transaction à chaque changement de position
    turnover = positions.diff().abs().fillna(0)
    costs = turnover * (cost_bps / 10_000)
    strat_ret_net = strat_ret - costs

    equity = capital * (1 + strat_ret_net.fillna(0)).cumprod()

    # métriques
    daily_ret = strat_ret_net.dropna()
    n_years = len(daily_ret) / 252
    cagr = (equity.iloc[-1] / capital) ** (1 / n_years) - 1 if n_years > 0 else np.nan
    sharpe = (daily_ret.mean() / daily_ret.std()) * np.sqrt(252) if daily_ret.std() > 0 else np.nan
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    max_dd = drawdown.min()
    n_trades = int((turnover > 0).sum())

    return {
        "equity_curve": equity,
        "positions": positions,
        "zscore": z,
        "spread": spread,
        "cagr": cagr,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "n_trades": n_trades,
        "final_equity": equity.iloc[-1],
    }
