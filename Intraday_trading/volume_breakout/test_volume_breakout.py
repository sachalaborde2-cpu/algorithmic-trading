import numpy as np
import pandas as pd
import pytest

from volume_breakout_backtest import (
    Day, Instrument, Params, _volume_ratio, run_backtest, simulate_day,
)

INST = Instrument(tick=0.25, point_value=5.0, commission_side=0.0)


def make_day(o, h, l, c, v, date="2026-01-05"):
    n = len(c)
    idx = pd.date_range(f"{date} 09:30", periods=n, freq="5min")
    return Day(pd.Timestamp(date), idx, list(o), list(h), list(l), list(c), list(v))


def flat_range_day(n_or=6, n_total=20, or_hi=100.5, or_lo=99.5, vol_or=1000):
    """n_or premieres barres dans [or_lo, or_hi], barres suivantes plates a la valeur mediane."""
    mid = (or_hi + or_lo) / 2
    o = [mid] * n_total
    h = [or_hi] * n_or + [mid] * (n_total - n_or)
    l = [or_lo] * n_or + [mid] * (n_total - n_or)
    c = [mid] * n_total
    v = [vol_or] * n_total
    return o, h, l, c, v


# --------------------------------------------------------------------------
def test_volume_ratio_no_lookahead():
    v = [10, 10, 10, 10, 100]
    # ratio de la barre 4 : vs moyenne des barres 0-3 (10), pas influence par elle-meme
    r = _volume_ratio(v, 4, lookback=4)
    assert r == pytest.approx(10.0)
    # pas assez d'historique -> pas de filtre possible (inf, jamais rejete)
    assert _volume_ratio(v, 0, lookback=4) == np.inf


def test_low_volume_breakout_filtered_out():
    o, h, l, c, v = flat_range_day(n_or=6, n_total=20)
    # barre 6 casse au-dessus du range mais avec un volume faible (pas confirme)
    c[6], h[6] = 101.0, 101.0
    v[6] = 50  # << moyenne des barres precedentes (1000)
    day = make_day(o, h, l, c, v)
    p = Params(or_minutes=30, target_r=None, slippage_ticks=0.0,
               volume_lookback=6, volume_ratio_min=1.5)
    trade = simulate_day(day, p, INST)
    assert trade is None  # cassure a faible volume -> ignoree, pas de trade


def test_high_volume_breakout_confirmed_like_base_orb():
    o, h, l, c, v = flat_range_day(n_or=6, n_total=20)
    c[6], h[6] = 101.0, 101.0
    v[6] = 5000  # >> moyenne des barres precedentes (1000) -> confirme
    day = make_day(o, h, l, c, v)
    p = Params(or_minutes=30, target_r=None, slippage_ticks=0.0,
               volume_lookback=6, volume_ratio_min=1.5)
    trade = simulate_day(day, p, INST)
    assert trade is not None
    assert trade["side"] == 1
    assert trade["entry_time"] == day.idx[7]  # entree a l'open de la barre suivante


def test_no_filter_behaves_like_base_orb():
    o, h, l, c, v = flat_range_day(n_or=6, n_total=20)
    c[6], h[6] = 101.0, 101.0
    v[6] = 50  # volume faible, mais pas de filtre applique
    day = make_day(o, h, l, c, v)
    p = Params(or_minutes=30, target_r=None, slippage_ticks=0.0,
               volume_ratio_min=None)
    trade = simulate_day(day, p, INST)
    assert trade is not None
    assert trade["side"] == 1


def test_filter_skips_unconfirmed_and_takes_later_confirmed_breakout():
    o, h, l, c, v = flat_range_day(n_or=6, n_total=20)
    c[6], h[6] = 101.0, 101.0  # cassure faible volume, doit etre ignoree
    v[6] = 50
    c[10], h[10] = 101.5, 101.5  # cassure suivante, volume confirme
    v[10] = 5000
    day = make_day(o, h, l, c, v)
    p = Params(or_minutes=30, target_r=None, slippage_ticks=0.0,
               volume_lookback=6, volume_ratio_min=1.5)
    trade = simulate_day(day, p, INST)
    assert trade is not None
    assert trade["entry_time"] == day.idx[11]


def test_no_breakout_no_trade():
    o, h, l, c, v = flat_range_day(n_or=6, n_total=20)
    day = make_day(o, h, l, c, v)
    p = Params(or_minutes=30, volume_ratio_min=1.5)
    assert simulate_day(day, p, INST) is None


def test_stop_wins_over_target_same_bar():
    o, h, l, c, v = flat_range_day(n_or=6, n_total=20, or_hi=100.5, or_lo=99.5)
    c[6], h[6] = 101.0, 101.0
    v[6] = 5000
    # barre d'entree (7) touche a la fois le stop (99.5) et un objectif tres proche
    o[7], h[7], l[7], c[7] = 101.0, 101.6, 99.0, 100.8
    day = make_day(o, h, l, c, v)
    p = Params(or_minutes=30, target_r=0.1, slippage_ticks=0.0,
               volume_ratio_min=1.5, volume_lookback=6)
    trade = simulate_day(day, p, INST)
    assert trade is not None
    assert trade["reason"] == "stop"


def test_forced_exit_at_session_close():
    o, h, l, c, v = flat_range_day(n_or=6, n_total=20)
    c[6], h[6] = 101.0, 101.0
    v[6] = 5000
    day = make_day(o, h, l, c, v)
    p = Params(or_minutes=30, target_r=None, slippage_ticks=0.0,
               volume_ratio_min=1.5, volume_lookback=6)
    trade = simulate_day(day, p, INST)
    assert trade["reason"] == "time"
    assert trade["exit_time"] == day.idx[-1]


def test_random_direction_flips_side():
    o, h, l, c, v = flat_range_day(n_or=6, n_total=20)
    c[6], h[6] = 101.0, 101.0
    v[6] = 5000
    day = make_day(o, h, l, c, v)
    p = Params(or_minutes=30, target_r=None, slippage_ticks=0.0,
               volume_ratio_min=1.5, volume_lookback=6)
    expected_side = int(np.random.default_rng(1).choice((-1, 1)))
    trade = simulate_day(day, p, INST, rng=np.random.default_rng(1))
    assert trade["side"] == expected_side


def test_run_backtest_returns_dataframe_with_expected_columns():
    o, h, l, c, v = flat_range_day(n_or=6, n_total=20)
    c[6], h[6] = 101.0, 101.0
    v[6] = 5000
    day = make_day(o, h, l, c, v)
    p = Params(or_minutes=30, volume_ratio_min=1.5, volume_lookback=6)
    trades = run_backtest([day], p, INST)
    assert list(trades.columns) == [
        "date", "side", "entry_time", "exit_time", "entry", "exit",
        "pts", "risk_pts", "r_mult", "pnl", "reason", "or_width", "volume_ratio",
    ]
    assert len(trades) == 1
    assert trades.iloc[0]["side"] == 1
