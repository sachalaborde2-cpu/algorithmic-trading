import numpy as np
import pandas as pd
import pytest

from overnight_selection_backtest import (
    Params,
    build_signals,
    kumo_bounds,
    momentum_score_series,
    randomize_selection,
    regime_series,
    select_tickers,
    selections_for_config,
    simulate,
)


def make_df(n=400, seed=0, start_price=100.0):
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0003, 0.01, n)
    close = start_price * np.cumprod(1 + rets)
    open_ = close * (1 + rng.normal(0, 0.001, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.002, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.002, n)))
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.DataFrame({"date": dates, "open": open_, "high": high, "low": low, "close": close})


def make_frames(n=400, tickers=("SPY", "QQQ", "IWM", "DIA")):
    return {t: make_df(n=n, seed=i, start_price=100 + 10 * i) for i, t in enumerate(tickers)}


# --------------------------------------------------------------------------
# Causalite : score momentum
# --------------------------------------------------------------------------
def test_momentum_score_no_lookahead():
    df = make_df(n=300, seed=1)
    p = Params()
    score_before = momentum_score_series(df, p).copy()

    shocked = df.copy()
    shocked.loc[250:, "close"] = shocked.loc[250:, "close"] * 5.0
    score_after = momentum_score_series(shocked, p)

    # Les valeurs du score a des indices < 250 (calculees uniquement a partir
    # de barres < 250) ne doivent pas bouger quand on choque des barres >= 250.
    idx = score_before.index[score_before.index < 250]
    pd.testing.assert_series_equal(score_before.loc[idx], score_after.loc[idx])


def test_momentum_score_formula():
    df = make_df(n=200, seed=2)
    p = Params(lookback_months=6, skip_months=1)
    score = momentum_score_series(df, p)
    skip, lookback = 21, 126
    i = 180
    expected = df["close"].iloc[i - skip] / df["close"].iloc[i - skip - lookback] - 1.0
    assert score.iloc[i] == pytest.approx(expected)


# --------------------------------------------------------------------------
# Causalite : regime Kumo (adapte de test_regime_filtered_backtest.py)
# --------------------------------------------------------------------------
def test_kumo_bounds_do_not_use_future_bars():
    df = make_df(n=300, seed=3)
    p = Params()
    top_before, bottom_before = kumo_bounds(df, p)

    shocked = df.copy()
    shocked.loc[250:, ["high", "low"]] = shocked.loc[250:, ["high", "low"]] * 5.0
    top_after, bottom_after = kumo_bounds(shocked, p)

    cutoff = 250 - p.displacement  # au-dela, le decalage(26) peut deja voir les barres choquees
    idx = top_before.index[top_before.index < cutoff]
    pd.testing.assert_series_equal(top_before.loc[idx], top_after.loc[idx])
    pd.testing.assert_series_equal(bottom_before.loc[idx], bottom_after.loc[idx])


def test_regime_mutually_exclusive_and_exhaustive():
    df = make_df(n=300, seed=4)
    regime = regime_series(df, Params())
    assert set(regime.unique()) <= {"bullish", "bearish", "neutral"}
    assert regime.isna().sum() == 0


def test_regime_warmup_is_neutral():
    df = make_df(n=100, seed=5)
    p = Params()
    regime = regime_series(df, p)
    warmup = p.senkou_b_period + p.displacement
    assert (regime.iloc[:warmup] == "neutral").all()


# --------------------------------------------------------------------------
# Selection par config
# --------------------------------------------------------------------------
def test_unfiltered_baseline_always_selects_all_four():
    frames = make_frames(n=300)
    p = Params(config="unfiltered_baseline")
    scores, regime, close, open_ = build_signals(frames, p)
    sels = selections_for_config(scores, regime, p)
    for s in sels:
        assert sorted(s) == sorted(frames.keys())


def test_cross_sectional_only_never_exceeds_n_top_and_picks_best():
    frames = make_frames(n=300)
    p = Params(config="cross_sectional_only", n_top=2)
    scores, regime, close, open_ = build_signals(frames, p)
    sels = selections_for_config(scores, regime, p)
    for i, s in enumerate(sels):
        assert len(s) <= p.n_top
        if len(s) == p.n_top:
            row = scores.iloc[i].dropna().sort_values(ascending=False)
            assert sorted(s) == sorted(row.index[:p.n_top].tolist())


def test_cross_sectional_plus_regime_is_subset_of_cross_sectional_only():
    frames = make_frames(n=300)
    scores, regime, close, open_ = build_signals(frames, Params())
    p_only = Params(config="cross_sectional_only")
    p_regime = Params(config="cross_sectional_plus_regime")
    sel_only = selections_for_config(scores, regime, p_only)
    sel_regime = selections_for_config(scores, regime, p_regime)
    for a, b in zip(sel_only, sel_regime):
        assert set(b) <= set(a)


def test_select_tickers_empty_when_scores_all_nan():
    scores_row = pd.Series({"SPY": np.nan, "QQQ": np.nan, "IWM": np.nan, "DIA": np.nan})
    regime_row = pd.Series({"SPY": "bullish", "QQQ": "bullish", "IWM": "bullish", "DIA": "bullish"})
    p = Params(config="cross_sectional_only", n_top=2)
    assert select_tickers(scores_row, regime_row, p) == []


# --------------------------------------------------------------------------
# Pas de fuite de futur sur le point d'entree (decision a J, execution J->J+1)
# --------------------------------------------------------------------------
def test_entry_uses_close_j_and_open_j_plus_1_only():
    frames = make_frames(n=300)
    p = Params(config="unfiltered_baseline")
    scores, regime, close, open_ = build_signals(frames, p)
    sels = selections_for_config(scores, regime, p)
    trades = simulate(frames, close, open_, sels, p)

    dates = frames["SPY"]["date"].to_numpy()
    row = trades[(trades["ticker"] == "SPY") & (trades["entry_time"] == dates[10])].iloc[0]
    slip = 0.01 * p.slippage_ticks
    assert row["entry"] == pytest.approx(close["SPY"].iloc[10] + slip)
    assert row["exit"] == pytest.approx(open_["SPY"].iloc[11] - slip)
    assert row["exit_time"] == dates[11]


def test_no_trade_uses_last_day_as_entry_no_next_bar_available():
    frames = make_frames(n=50)
    p = Params(config="unfiltered_baseline")
    scores, regime, close, open_ = build_signals(frames, p)
    sels = selections_for_config(scores, regime, p)
    trades = simulate(frames, close, open_, sels, p)
    last_date = frames["SPY"]["date"].iloc[-1]
    assert not (trades["entry_time"] == last_date).any()


# --------------------------------------------------------------------------
# Placebo de selection aleatoire
# --------------------------------------------------------------------------
def test_randomize_selection_preserves_count_per_night():
    frames = make_frames(n=300)
    p = Params(config="cross_sectional_only", n_top=2)
    scores, regime, close, open_ = build_signals(frames, p)
    real = selections_for_config(scores, regime, p)
    rng = np.random.default_rng(42)
    rand = randomize_selection(scores, regime, p, rng)
    assert len(real) == len(rand)
    for r, rr in zip(real, rand):
        assert len(r) == len(rr)


def test_randomize_selection_is_deterministic_given_seed():
    frames = make_frames(n=300)
    p = Params(config="cross_sectional_plus_regime", n_top=2)
    scores, regime, close, open_ = build_signals(frames, p)
    rand1 = randomize_selection(scores, regime, p, np.random.default_rng(7))
    rand2 = randomize_selection(scores, regime, p, np.random.default_rng(7))
    assert rand1 == rand2


def test_randomize_selection_changes_which_tickers_on_average():
    frames = make_frames(n=300)
    p = Params(config="unfiltered_baseline")
    scores, regime, close, open_ = build_signals(frames, p)
    real = selections_for_config(scores, regime, p)
    rng = np.random.default_rng(1)
    rand = randomize_selection(scores, regime, p, rng)
    # unfiltered_baseline: le pool == la selection reelle (4/4), donc le hasard
    # doit reproduire exactement le meme ensemble (pas de place pour varier).
    for r, rr in zip(real, rand):
        assert sorted(r) == sorted(rr)
