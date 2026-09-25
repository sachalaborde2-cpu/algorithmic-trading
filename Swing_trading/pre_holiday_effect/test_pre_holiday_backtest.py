"""Tests unitaires : identification correcte des jours pre-feries (purement
calendaire, sans dependance au prix), pricing correct de la jambe INTRADAY
(ouverture[i] -> cloture[i], jamais cloture[i] -> ouverture[i+1]), absence de
fuite de futur, disjonction des sous-ensembles filtres, effet du slippage, et
determinisme/preservation du timing du test placebo."""
import numpy as np
import pandas as pd
import pytest

from pre_holiday_backtest import (Instrument, Params, run_backtest, metrics,
                                  random_direction_test, pre_holiday_membership)

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


def test_pre_holiday_flags_day_before_a_calendar_gap():
    """Un jour de bourse suivi d'un trou dans le calendrier des dates
    presentes (jour ouvre absent -> ferme, autre chose qu'un week-end) doit
    etre marque pre-ferie. Ici le vendredi 2024-11-08 est suivi du lundi
    2024-11-11 -- pas de trou (week-end normal) -- puis le mercredi
    2024-11-27 est suivi du vendredi 2024-11-29 en sautant jeudi 28
    (Thanksgiving, absent des donnees) -> 27 nov doit etre pre-ferie."""
    dates = ["2024-11-25", "2024-11-26", "2024-11-27", "2024-11-29", "2024-12-02"]
    df = make_df(dates, opens=[1.0] * 5, closes=[1.0] * 5)
    flags = pre_holiday_membership(df)
    assert bool(flags.iloc[2]) is True   # 27 nov -> trou avant le 29 (28 absent)
    assert bool(flags.iloc[0]) is False  # 25 nov -> 26 nov, jour ouvre suivant present
    assert bool(flags.iloc[3]) is False  # 29 nov -> lundi 2 dec, week-end normal


def test_pre_holiday_membership_is_purely_calendar_based_no_price_dependence():
    """Deux DataFrames avec les memes dates mais des prix totalement
    differents doivent produire exactement le meme marquage pre-ferie."""
    dates = pd.bdate_range("2024-01-02", "2024-04-30").tolist()
    del dates[10]  # simule un jour ferie au milieu de la serie
    df1 = pd.DataFrame({"date": dates})
    df2 = pd.DataFrame({"date": dates})
    df1_prices = df1.assign(open=1.0, close=1.0)
    df2_prices = df2.assign(open=999.0, close=-999.0)
    assert (pre_holiday_membership(df1_prices) == pre_holiday_membership(df2_prices)).all()


def test_last_day_in_series_is_never_flagged_pre_holiday():
    """Le dernier jour de la serie n'a pas de 'jour ouvre suivant' observable
    -- il ne doit jamais etre marque pre-ferie (pas d'extrapolation)."""
    dates = pd.bdate_range("2024-01-02", "2024-03-29")
    df = pd.DataFrame({"date": dates})
    flags = pre_holiday_membership(df)
    assert bool(flags.iloc[-1]) is False


def test_intraday_leg_uses_open_i_and_close_i_same_day():
    """Le trade doit utiliser open[i] comme entree et close[i] comme sortie
    du MEME jour -- jamais close[i] -> open[i+1] (jambe overnight, hors
    perimetre de cette strategie)."""
    df = make_df(["2024-01-02", "2024-01-03", "2024-01-04"],
                 opens=[100.0, 112.0, 105.0], closes=[110.0, 108.0, 107.0])
    p = Params(filter_holiday="unfiltered", slippage_ticks=0.0)
    trades = run_backtest(df, p, INST)
    row0 = trades.iloc[0]
    assert row0["entry"] == pytest.approx(100.0)  # open du jour 0
    assert row0["exit"] == pytest.approx(110.0)   # close du MEME jour 0
    assert row0["pts"] == pytest.approx(10.0)


def test_entry_and_exit_never_reference_intraday_extremes():
    df = make_df(["2024-01-02", "2024-01-03"], opens=[100.0, 100.0], closes=[100.0, 100.0],
                 highs=[999.0, 999.0], lows=[-999.0, -999.0])
    p = Params(filter_holiday="unfiltered", slippage_ticks=0.0)
    trades = run_backtest(df, p, INST)
    assert trades.iloc[0]["pts"] == pytest.approx(0.0)


def test_pre_holiday_only_and_non_pre_holiday_only_are_disjoint_and_cover_unfiltered():
    df = make_random_df(150, seed=1)
    df = df.drop(df.index[[50, 100]]).reset_index(drop=True)  # cree des trous calendaires
    unfiltered = run_backtest(df, Params(filter_holiday="unfiltered", slippage_ticks=0.0), INST)
    pre_only = run_backtest(df, Params(filter_holiday="pre_holiday_only", slippage_ticks=0.0), INST)
    non_pre_only = run_backtest(df, Params(filter_holiday="non_pre_holiday_only", slippage_ticks=0.0), INST)
    assert len(pre_only) + len(non_pre_only) == len(unfiltered)
    assert set(pre_only["entry_time"]).isdisjoint(set(non_pre_only["entry_time"]))


def test_slippage_reduces_pnl():
    df = make_df(["2024-01-02", "2024-01-03"], opens=[100.0, 112.0], closes=[110.0, 108.0])
    no_slip = run_backtest(df, Params(filter_holiday="unfiltered", slippage_ticks=0.0), INST)
    with_slip = run_backtest(df, Params(filter_holiday="unfiltered", slippage_ticks=1.0), INST)
    assert with_slip.iloc[0]["pts"] < no_slip.iloc[0]["pts"]


def test_no_lookahead_shocking_future_bars_does_not_change_past_trades():
    """Un choc sur les barres futures ne doit jamais modifier les trades deja
    generes sur des jours anterieurs (chaque trade ne depend que de open[i],
    close[i], et du calendrier des dates -- jamais d'une barre future)."""
    df = make_random_df(150, seed=2)
    p = Params(filter_holiday="unfiltered", slippage_ticks=0.0)
    trades_a = run_backtest(df, p, INST)

    df2 = df.copy()
    df2.loc[140:, ["open", "high", "low", "close"]] *= 5.0
    trades_b = run_backtest(df2, p, INST)

    early_a = trades_a[trades_a["entry_time"] < df["date"].iloc[130]]
    early_b = trades_b[trades_b["entry_time"] < df["date"].iloc[130]]
    assert list(early_a["pts"]) == pytest.approx(list(early_b["pts"]))


def test_no_lookahead_removing_a_future_trading_day_does_not_change_past_flags():
    """Le marquage pre-ferie d'un jour passe ne doit jamais dependre de la
    suppression/ajout d'un jour de bourse loin dans le futur (seul le jour
    ouvre IMMEDIATEMENT suivant compte)."""
    dates = pd.bdate_range("2024-01-02", "2024-06-28").tolist()
    df_a = pd.DataFrame({"date": dates})
    flags_a = pre_holiday_membership(df_a)

    df_b = pd.DataFrame({"date": [d for i, d in enumerate(dates) if i != 100]})
    flags_b = pre_holiday_membership(df_b)

    common_dates = df_b["date"][df_b["date"] < dates[90]]
    a_aligned = flags_a[df_a["date"].isin(common_dates)].reset_index(drop=True)
    b_aligned = flags_b[df_b["date"].isin(common_dates)].reset_index(drop=True)
    assert (a_aligned == b_aligned).all()


def test_random_direction_test_is_deterministic_given_seed():
    df = make_random_df(200, seed=3)
    p = Params(filter_holiday="unfiltered")
    dates = pd.DatetimeIndex(df["date"].iloc[100:-1])
    r1 = random_direction_test(df, p, INST, dates, n_sims=20, seed=7)
    r2 = random_direction_test(df, p, INST, dates, n_sims=20, seed=7)
    assert r1 == r2


def test_random_direction_test_preserves_timing_changes_only_sign():
    df = make_random_df(100, seed=4)
    p = Params(filter_holiday="unfiltered", slippage_ticks=0.0)
    rng = np.random.default_rng(0)
    real = run_backtest(df, p, INST)
    placebo = run_backtest(df, p, INST, rng)
    assert list(real["entry_time"]) == list(placebo["entry_time"])
    assert real["pts"].abs().to_numpy() == pytest.approx(placebo["pts"].abs().to_numpy())


def test_metrics_all_winning_days():
    df = make_df([f"2024-01-{d:02d}" for d in range(2, 12)],
                 opens=[100.0 + 2 * d for d in range(10)],
                 closes=[100.5 + 2 * d for d in range(10)])
    trades = run_backtest(df, Params(filter_holiday="unfiltered", slippage_ticks=0.0), INST)
    dates = pd.DatetimeIndex(df["date"])
    m = metrics(trades, dates)
    assert m["n_trades"] == len(trades)
    assert m["win_rate"] == pytest.approx(1.0)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
