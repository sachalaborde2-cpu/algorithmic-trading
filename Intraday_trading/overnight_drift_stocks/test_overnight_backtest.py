"""Tests unitaires : isolation correcte des fenetres overnight/intraday et
absence de fuite de futur."""
import numpy as np
import pandas as pd
import pytest

from overnight_backtest import (
    Day, Instrument, Params, run_backtest, simulate_pair, metrics,
    random_direction_test,
)

INST = Instrument(tick=0.01, point_value=100.0, commission_side=1.00)


def make_day(date, o, c, h=None, l=None):
    n = 3
    idx = pd.date_range(f"{date} 09:30", periods=n, freq="5min")
    h = h if h is not None else [max(o, c)] * n
    l = l if l is not None else [min(o, c)] * n
    return Day(pd.Timestamp(date), idx, [o] + [c] * (n - 1), h, l, [o] * (n - 1) + [c], [100] * n)


def test_overnight_leg_uses_prev_close_and_today_open():
    prev = make_day("2024-01-02", o=100.0, c=110.0)
    day = make_day("2024-01-03", o=112.0, c=108.0)
    p = Params(leg="overnight", direction=1, slippage_ticks=0.0)
    tr = simulate_pair(prev, day, p, INST)
    assert tr["entry"] == pytest.approx(110.0)
    assert tr["exit"] == pytest.approx(112.0)
    assert tr["pts"] == pytest.approx(2.0)


def test_intraday_leg_uses_today_open_and_today_close():
    prev = make_day("2024-01-02", o=100.0, c=110.0)
    day = make_day("2024-01-03", o=112.0, c=108.0)
    p = Params(leg="intraday", direction=1, slippage_ticks=0.0)
    tr = simulate_pair(prev, day, p, INST)
    assert tr["entry"] == pytest.approx(112.0)
    assert tr["exit"] == pytest.approx(108.0)
    assert tr["pts"] == pytest.approx(-4.0)


def test_short_direction_inverts_pnl_sign():
    prev = make_day("2024-01-02", o=100.0, c=110.0)
    day = make_day("2024-01-03", o=112.0, c=108.0)
    long_tr = simulate_pair(prev, day, Params(leg="overnight", direction=1, slippage_ticks=0.0), INST)
    short_tr = simulate_pair(prev, day, Params(leg="overnight", direction=-1, slippage_ticks=0.0), INST)
    assert long_tr["pts"] == pytest.approx(-short_tr["pts"])


def test_slippage_reduces_pnl_on_both_sides():
    prev = make_day("2024-01-02", o=100.0, c=110.0)
    day = make_day("2024-01-03", o=112.0, c=108.0)
    no_slip = simulate_pair(prev, day, Params(leg="overnight", direction=1, slippage_ticks=0.0), INST)
    with_slip = simulate_pair(prev, day, Params(leg="overnight", direction=1, slippage_ticks=1.0), INST)
    assert with_slip["pts"] < no_slip["pts"]


def test_entry_and_exit_prices_never_reference_future_bars_within_the_leg():
    """La fenetre intraday ne doit dependre que de o[0] et c[-1] du jour J,
    jamais d'une barre intermediaire (qui pourrait servir a "tricher" avec
    un plus haut/bas connu seulement en fin de journee)."""
    prev = make_day("2024-01-02", o=100.0, c=100.0)
    day = make_day("2024-01-03", o=100.0, c=100.0, h=[100.0, 999.0, 100.0], l=[100.0, -999.0, 100.0])
    p = Params(leg="intraday", direction=1, slippage_ticks=0.0)
    tr = simulate_pair(prev, day, p, INST)
    assert tr["pts"] == pytest.approx(0.0)


def test_run_backtest_produces_one_trade_per_day_pair():
    days = [make_day(f"2024-01-{d:02d}", o=100.0 + d, c=101.0 + d) for d in range(2, 10)]
    trades = run_backtest(days, Params(leg="overnight", direction=1, slippage_ticks=0.0), INST)
    assert len(trades) == len(days) - 1


def test_metrics_treats_all_days_present_since_one_trade_per_day():
    # o/c croissants avec un saut positif entre la cloture veille et l'open
    # du jour -> jambe overnight toujours gagnante en long.
    days = [make_day(f"2024-01-{d:02d}", o=100.0 + 2 * d, c=100.5 + 2 * d) for d in range(2, 12)]
    trades = run_backtest(days, Params(leg="overnight", direction=1, slippage_ticks=0.0), INST)
    dates = pd.DatetimeIndex([d.date for d in days[1:]])
    m = metrics(trades, dates)
    assert m["n_trades"] == len(dates)
    assert m["win_rate"] == pytest.approx(1.0)


def test_random_direction_test_is_deterministic_given_seed():
    business_days = pd.bdate_range("2024-01-02", periods=38)
    days = [make_day(dt.strftime("%Y-%m-%d"), o=100.0 + (i % 3), c=101.0 + (i % 2))
            for i, dt in enumerate(business_days)]
    dates = pd.DatetimeIndex([d.date for d in days[1:]])
    p = Params(leg="overnight", direction=1, slippage_ticks=1.0)
    r1 = random_direction_test(days, p, INST, dates, n_sims=20, seed=42)
    r2 = random_direction_test(days, p, INST, dates, n_sims=20, seed=42)
    assert r1 == r2


def test_random_direction_test_shuffles_direction_not_timing():
    """Le test placebo doit rejouer exactement les memes entrees/sorties
    (memes prix), seule la direction change -> |pts| identique en valeur
    absolue a la version reelle pour chaque jour, seul le signe varie."""
    days = [make_day(f"2024-01-{d:02d}", o=100.0 + d, c=99.0 + d) for d in range(2, 6)]
    p = Params(leg="overnight", direction=1, slippage_ticks=0.0)
    rng = np.random.default_rng(0)
    real = run_backtest(days, p, INST)
    randomized = run_backtest(days, p, INST, rng)
    assert (real["pts"].abs().to_numpy() == pytest.approx(randomized["pts"].abs().to_numpy()))


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
