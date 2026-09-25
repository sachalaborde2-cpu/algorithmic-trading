"""Tests unitaires : regime Ichimoku causal (pas de fuite de futur), filtre
d'entree overnight correctement applique, symetrie bullish/bearish, et
fonctionnement du test placebo (meme filtre, direction aleatoire)."""
import numpy as np
import pandas as pd
import pytest

from regime_filtered_backtest import (
    Instrument, Params, kumo_bounds, regime_series, run_backtest,
    random_direction_test,
)

INST = Instrument(tick=0.01, point_value=100.0, commission_side=1.00)


def make_df(n=200, seed=0, trend=0.0):
    rng = np.random.default_rng(seed)
    ret = rng.normal(trend, 0.01, n)
    close = 100 * np.cumprod(1 + ret)
    high = close * (1 + np.abs(rng.normal(0, 0.003, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.003, n)))
    open_ = np.concatenate([[close[0]], close[:-1]]) * (1 + rng.normal(0, 0.001, n))
    dates = pd.bdate_range("2020-01-01", periods=n)
    return pd.DataFrame({"date": dates, "open": open_, "high": high, "low": low,
                         "close": close, "volume": 1_000_000})


def test_kumo_bounds_do_not_use_future_bars():
    """Le nuage affiche au jour t (apres decalage) ne doit dependre que des
    barres 0..t-displacement : un choc sur des barres futures ne doit pas
    changer le regime deja calcule a t."""
    df = make_df(150)
    p = Params()
    top_a, bot_a = kumo_bounds(df, p)

    df2 = df.copy()
    df2.loc[140:, ["high", "low", "close"]] *= 5.0
    top_b, bot_b = kumo_bounds(df2, p)

    t = 100
    assert top_a.iloc[t] == pytest.approx(top_b.iloc[t])
    assert bot_a.iloc[t] == pytest.approx(bot_b.iloc[t])


def test_warmup_period_is_neutral():
    df = make_df(300, seed=5)
    p = Params()
    regime = regime_series(df, p)
    warmup = p.senkou_b_period + p.displacement
    assert (regime.iloc[:warmup] == "neutral").all()


def test_regime_labels_are_mutually_exclusive_and_exhaustive():
    df = make_df(400, seed=6)
    p = Params()
    regime = regime_series(df, p)
    assert set(regime.unique()) <= {"bullish", "bearish", "neutral"}


def test_unfiltered_trades_every_day():
    df = make_df(200, seed=1)
    p = Params(filter_regime="unfiltered")
    trades = run_backtest(df, p, INST)
    assert len(trades) == len(df) - 1  # un trade par transition J -> J+1


def test_bullish_filter_only_enters_on_bullish_days():
    df = make_df(400, seed=2, trend=0.001)
    p = Params(filter_regime="bullish")
    trades = run_backtest(df, p, INST)
    assert len(trades) > 0
    assert (trades["regime"] == "bullish").all()


def test_bearish_filter_only_enters_on_bearish_days():
    df = make_df(400, seed=3, trend=-0.001)
    p = Params(filter_regime="bearish")
    trades = run_backtest(df, p, INST)
    assert len(trades) > 0
    assert (trades["regime"] == "bearish").all()


def test_bullish_and_bearish_filters_are_symmetric_and_disjoint():
    """Aucun jour ne doit etre trade a la fois par le filtre bullish et le
    filtre bearish (regimes mutuellement exclusifs) -- verifie que le test
    ne privilegie structurellement aucun des deux sens."""
    df = make_df(500, seed=4)
    bull = run_backtest(df, Params(filter_regime="bullish"), INST)
    bear = run_backtest(df, Params(filter_regime="bearish"), INST)
    assert set(bull["entry_time"]).isdisjoint(set(bear["entry_time"]))


def test_entry_decided_before_close_no_lookahead():
    """Le regime utilise pour decider l'entree du jour i est celui calcule a
    la cloture du jour i (avant l'ouverture i+1) : un choc sur le prix
    d'ouverture i+1 ne doit jamais changer si le trade a ete pris."""
    df = make_df(300, seed=7)
    p = Params(filter_regime="bullish")
    trades_a = run_backtest(df, p, INST)

    df2 = df.copy()
    df2.loc[250:, "open"] *= 3.0  # choc sur les ouvertures futures
    trades_b = run_backtest(df2, p, INST)

    early_a = trades_a[trades_a["entry_time"] < df["date"].iloc[240]]
    early_b = trades_b[trades_b["entry_time"] < df["date"].iloc[240]]
    assert list(early_a["entry_time"]) == list(early_b["entry_time"])


def test_random_direction_test_is_deterministic_given_seed():
    df = make_df(500, seed=4)
    p = Params(filter_regime="unfiltered")
    dates = pd.DatetimeIndex(df["date"].iloc[300:])
    r1 = random_direction_test(df, p, INST, dates, n_sims=15, seed=7)
    r2 = random_direction_test(df, p, INST, dates, n_sims=15, seed=7)
    assert r1 == r2


def test_random_direction_test_preserves_filter_timing():
    """Le test placebo doit garder exactement les memes jours filtres
    (memes entry_time) que la config reelle -- seul le signe change."""
    df = make_df(400, seed=8)
    p = Params(filter_regime="bullish")
    real = run_backtest(df, p, INST)
    rng = np.random.default_rng(0)
    placebo = run_backtest(df, p, INST, rng)
    assert list(real["entry_time"]) == list(placebo["entry_time"])


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
