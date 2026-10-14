import numpy as np
import pandas as pd
import pytest

from twin_backtest import (
    Params,
    deviation_bps,
    execution_cost,
    fair_value,
    random_direction_test,
    simulate_pair,
)


def make_pair(n=200, seed=0, shock_day=None, shock_bps=0.0):
    rng = np.random.default_rng(seed)
    base = 100 * np.cumprod(1 + rng.normal(0, 0.01, n))
    noise = rng.normal(0, 1e-4, n)
    a = base * np.exp(noise)
    b = base.copy()
    if shock_day is not None:
        a[shock_day] *= np.exp(shock_bps / 1e4)
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "date": dates,
        "a_open_raw": a, "a_close_raw": a, "a_open_adj": a, "a_close_adj": a,
        "b_open_raw": b, "b_close_raw": b, "b_open_adj": b, "b_close_adj": b,
    })


def test_fair_value_uses_only_strictly_past_closes():
    df = make_pair()
    p = Params(lookback=20)
    before = fair_value(df, p)
    shocked = df.copy()
    shocked.loc[100, "a_close_adj"] *= 1.5
    after = fair_value(shocked, p)
    # La valeur d'equilibre au jour 100 (et avant) ne voit pas la cloture du jour 100.
    pd.testing.assert_series_equal(before.loc[:100], after.loc[:100])


def test_deviation_unchanged_by_future_shock():
    df = make_pair()
    p = Params()
    before = deviation_bps(df, p)
    shocked = df.copy()
    shocked.loc[150:, ["a_close_adj", "a_open_adj"]] *= 3.0
    after = deviation_bps(shocked, p)
    pd.testing.assert_series_equal(before.loc[:149], after.loc[:149])


def test_deviation_cancels_constant_adjustment_factor():
    # Un facteur d'ajustement dividende constant (connu plus tard) multiplie
    # tout le passe : il doit s'annuler dans la deviation.
    df = make_pair()
    p = Params()
    scaled = df.copy()
    scaled["a_close_adj"] *= 0.97
    np.testing.assert_allclose(deviation_bps(df, p).dropna(), deviation_bps(scaled, p).dropna(), atol=1e-8)


def test_entry_next_open_and_direction_short_expensive_leg():
    df = make_pair(shock_day=60, shock_bps=50.0)  # A anormalement cher a la cloture 60
    p = Params(k_bps=20.0, slippage_ticks=0.0, commission_per_share=0.0, commission_min=0.0, borrow_rate=0.0)
    t = simulate_pair(df, p, "A/B")
    row = t[t["entry_date"] == df["date"].iloc[61]]
    assert len(row) == 1
    assert row["side"].iloc[0] == -1  # A cher => vente de A, achat de B
    assert row["d_signal_bps"].iloc[0] > 20


def test_no_trade_entered_on_signal_day_itself():
    df = make_pair(shock_day=60, shock_bps=50.0)
    t = simulate_pair(df, Params(k_bps=20.0), "A/B")
    assert not (t["entry_date"] == df["date"].iloc[60]).any()


def test_exit_after_entry_and_within_max_hold():
    df = make_pair(n=400, seed=3)
    p = Params(k_bps=1.0, max_hold=5)
    t = simulate_pair(df, p, "A/B")
    assert len(t) > 0
    assert (t["exit_date"] > t["entry_date"]).all()
    assert (t["hold_days"] >= 1).all() and (t["hold_days"] <= p.max_hold).all()
    # Pas de chevauchement : une seule position a la fois par paire.
    assert (t["entry_date"].iloc[1:].to_numpy() >= t["exit_date"].iloc[:-1].to_numpy()).all()


def test_gross_pnl_is_dollar_neutral_spread_return():
    df = make_pair(shock_day=60, shock_bps=50.0)
    p = Params(k_bps=20.0)
    t = simulate_pair(df, p, "A/B")
    r = t[t["entry_date"] == df["date"].iloc[61]].iloc[0]
    e = df.index[df["date"] == r["entry_date"]][0]
    x = df.index[df["date"] == r["exit_date"]][0]
    ra = df["a_open_adj"].iloc[x] / df["a_open_adj"].iloc[e] - 1
    rb = df["b_open_adj"].iloc[x] / df["b_open_adj"].iloc[e] - 1
    assert r["gross"] == pytest.approx(-1 * p.notional * (ra - rb))


def test_execution_cost_formula():
    p = Params(notional=100_000, slippage_ticks=1.0, tick=0.01, commission_per_share=0.005, commission_min=1.0)
    shares = 100_000 / 500.0
    assert execution_cost(500.0, p) == pytest.approx(0.01 * shares + max(1.0, 0.005 * shares))


def test_costs_include_four_executions_and_borrow():
    df = make_pair(shock_day=60, shock_bps=50.0)
    p = Params(k_bps=20.0)
    t = simulate_pair(df, p, "A/B")
    assert (t["costs"] > 4 * p.commission_min).all()
    assert (t["pnl"] == t["gross"] - t["costs"]).all()


def test_random_direction_deterministic_and_preserves_costs():
    df = make_pair(n=400, seed=5)
    t = simulate_pair(df, Params(k_bps=1.0), "A/B")
    r1 = random_direction_test(t, n_sims=500, seed=1)
    r2 = random_direction_test(t, n_sims=500, seed=1)
    assert r1 == r2
    # Moyenne du hasard ~ -couts totaux (le brut aleatoire est centre sur 0).
    assert r1[1] == pytest.approx(-t["costs"].sum(), abs=4 * r1[2] / np.sqrt(500) + 1e-6)
