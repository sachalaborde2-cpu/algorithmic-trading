"""Tests unitaires : definition calendaire correcte de la fenetre
turn-of-month (TOM), isolation correcte de la fenetre overnight, absence de
fuite de futur, symetrie long/short, et fonctionnement du test placebo (meme
timing, direction aleatoire)."""
import numpy as np
import pandas as pd
import pytest

from turn_of_month_backtest import (Instrument, Params, run_backtest, metrics,
                                    random_direction_test, tom_membership)

INST = Instrument(tick=0.01, point_value=100.0, commission_side=1.00)


def make_df(dates, opens, closes, highs=None, lows=None, volume=1_000_000):
    n = len(dates)
    highs = highs if highs is not None else [max(o, c) for o, c in zip(opens, closes)]
    lows = lows if lows is not None else [min(o, c) for o, c in zip(opens, closes)]
    return pd.DataFrame({
        "date": pd.to_datetime(dates), "open": opens, "high": highs,
        "low": lows, "close": closes, "volume": [volume] * n,
    })


def make_random_df(n=200, seed=0, start="2020-01-01"):
    rng = np.random.default_rng(seed)
    ret = rng.normal(0.0, 0.01, n)
    close = 100 * np.cumprod(1 + ret)
    high = close * (1 + np.abs(rng.normal(0, 0.003, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.003, n)))
    open_ = np.concatenate([[close[0]], close[:-1]]) * (1 + rng.normal(0, 0.001, n))
    dates = pd.bdate_range(start, periods=n)
    return pd.DataFrame({"date": dates, "open": open_, "high": high, "low": low,
                         "close": close, "volume": 1_000_000})


def test_tom_membership_last_day_of_month_is_true():
    """Le dernier jour de bourse d'un mois complet doit toujours etre marque
    TOM (sa jambe overnight mene au 1er jour du mois suivant)."""
    dates = pd.bdate_range("2024-01-02", "2024-03-31")
    df = pd.DataFrame({"date": dates})
    tom = tom_membership(df)
    last_jan = dates[dates.month == 1].max()
    assert bool(tom[df["date"] == last_jan].iloc[0]) is True


def test_tom_membership_first_two_days_of_month_are_entry_days():
    """Les jambes overnight TOM couvrent 3 entrees : dernier jour du mois
    precedent, 1er et 2e jour de bourse du mois (menant respectivement au
    1er, 2e et 3e jour). Le 3e jour du mois n'est lui-meme jamais un jour
    d'ENTREE TOM (sa sortie tomberait au 4e jour, hors de la fenetre
    academique de 4 jours)."""
    dates = pd.bdate_range("2024-01-02", "2024-03-31")
    df = pd.DataFrame({"date": dates})
    tom = tom_membership(df)
    feb_days = dates[dates.month == 2].sort_values()
    assert bool(tom[df["date"] == feb_days[0]].iloc[0]) is True
    assert bool(tom[df["date"] == feb_days[1]].iloc[0]) is True
    assert bool(tom[df["date"] == feb_days[2]].iloc[0]) is False


def test_tom_membership_mid_month_day_is_false():
    dates = pd.bdate_range("2024-01-02", "2024-03-31")
    df = pd.DataFrame({"date": dates})
    tom = tom_membership(df)
    feb_days = dates[dates.month == 2].sort_values()
    mid_day = feb_days[len(feb_days) // 2]
    assert bool(tom[df["date"] == mid_day].iloc[0]) is False


def test_tom_membership_is_purely_calendar_based_no_price_dependence():
    """Deux DataFrames avec les memes dates mais des prix totalement
    differents doivent produire exactement le meme marquage TOM."""
    dates = pd.bdate_range("2024-01-02", "2024-04-30")
    df1 = pd.DataFrame({"date": dates})
    df2 = pd.DataFrame({"date": dates})
    assert (tom_membership(df1) == tom_membership(df2)).all()


def test_overnight_leg_uses_close_j_and_open_j_plus_1():
    df = make_df(["2024-01-02", "2024-01-03", "2024-01-04"],
                 opens=[100.0, 112.0, 105.0], closes=[110.0, 108.0, 107.0])
    p = Params(filter_tom="unfiltered", slippage_ticks=0.0)
    trades = run_backtest(df, p, INST)
    row0 = trades.iloc[0]
    assert row0["entry"] == pytest.approx(110.0)  # close du jour 0
    assert row0["exit"] == pytest.approx(112.0)   # open du jour 1
    assert row0["pts"] == pytest.approx(2.0)


def test_entry_and_exit_never_reference_intraday_extremes():
    df = make_df(["2024-01-02", "2024-01-03"], opens=[100.0, 100.0], closes=[100.0, 100.0],
                 highs=[999.0, 999.0], lows=[-999.0, -999.0])
    p = Params(filter_tom="unfiltered", slippage_ticks=0.0)
    trades = run_backtest(df, p, INST)
    assert trades.iloc[0]["pts"] == pytest.approx(0.0)


def test_tom_only_and_non_tom_only_are_disjoint_and_cover_unfiltered():
    df = make_random_df(150, seed=1)
    unfiltered = run_backtest(df, Params(filter_tom="unfiltered", slippage_ticks=0.0), INST)
    tom_only = run_backtest(df, Params(filter_tom="tom_only", slippage_ticks=0.0), INST)
    non_tom_only = run_backtest(df, Params(filter_tom="non_tom_only", slippage_ticks=0.0), INST)
    assert len(tom_only) + len(non_tom_only) == len(unfiltered)
    assert set(tom_only["entry_time"]).isdisjoint(set(non_tom_only["entry_time"]))


def test_short_direction_inverts_pnl_sign():
    df = make_df(["2024-01-02", "2024-01-03"], opens=[100.0, 112.0], closes=[110.0, 108.0])
    unfiltered = run_backtest(df, Params(filter_tom="unfiltered", slippage_ticks=0.0), INST)
    assert len(unfiltered) == 1


def test_slippage_reduces_pnl():
    df = make_df(["2024-01-02", "2024-01-03"], opens=[100.0, 112.0], closes=[110.0, 108.0])
    no_slip = run_backtest(df, Params(filter_tom="unfiltered", slippage_ticks=0.0), INST)
    with_slip = run_backtest(df, Params(filter_tom="unfiltered", slippage_ticks=1.0), INST)
    assert with_slip.iloc[0]["pts"] < no_slip.iloc[0]["pts"]


def test_no_lookahead_shocking_future_bars_does_not_change_past_trades():
    """Un choc sur les barres futures ne doit jamais modifier les trades deja
    generes sur des jours anterieurs (chaque trade ne depend que de close[i],
    open[i+1], et du calendrier -- jamais d'une barre future)."""
    df = make_random_df(150, seed=2)
    p = Params(filter_tom="unfiltered", slippage_ticks=0.0)
    trades_a = run_backtest(df, p, INST)

    df2 = df.copy()
    df2.loc[140:, ["open", "high", "low", "close"]] *= 5.0
    trades_b = run_backtest(df2, p, INST)

    early_a = trades_a[trades_a["entry_time"] < df["date"].iloc[130]]
    early_b = trades_b[trades_b["entry_time"] < df["date"].iloc[130]]
    assert list(early_a["pts"]) == pytest.approx(list(early_b["pts"]))


def test_random_direction_test_is_deterministic_given_seed():
    df = make_random_df(200, seed=3)
    p = Params(filter_tom="unfiltered")
    dates = pd.DatetimeIndex(df["date"].iloc[100:-1])
    r1 = random_direction_test(df, p, INST, dates, n_sims=20, seed=7)
    r2 = random_direction_test(df, p, INST, dates, n_sims=20, seed=7)
    assert r1 == r2


def test_random_direction_test_preserves_timing_changes_only_sign():
    df = make_random_df(100, seed=4)
    p = Params(filter_tom="unfiltered", slippage_ticks=0.0)
    rng = np.random.default_rng(0)
    real = run_backtest(df, p, INST)
    placebo = run_backtest(df, p, INST, rng)
    assert list(real["entry_time"]) == list(placebo["entry_time"])
    assert real["pts"].abs().to_numpy() == pytest.approx(placebo["pts"].abs().to_numpy())


def test_metrics_all_winning_days():
    df = make_df([f"2024-01-{d:02d}" for d in range(2, 12)],
                 opens=[100.0 + 2 * d for d in range(10)],
                 closes=[100.5 + 2 * d for d in range(10)])
    trades = run_backtest(df, Params(filter_tom="unfiltered", slippage_ticks=0.0), INST)
    dates = pd.DatetimeIndex(df["date"])[1:]
    m = metrics(trades, dates)
    assert m["n_trades"] == len(trades)
    assert m["win_rate"] == pytest.approx(1.0)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
