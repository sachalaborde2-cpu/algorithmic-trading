"""Tests unitaires pour gap_backtest.py : pas de fuite de futur sur l'ATR
quotidien, detection du gap, modes fill/go, priorite stop > target, sortie
forcee."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from gap_backtest import Day, Instrument, Params, compute_daily_atr, load_bars, run_backtest, simulate_day

INST = Instrument(tick=0.01, point_value=1.0, commission_side=0.0)
TZ = "America/New_York"


def _make_day(o, h, l, c, date="2024-01-02") -> Day:
    n = len(c)
    idx = pd.date_range(f"{date} 09:30", periods=n, freq="5min", tz=TZ)
    return Day(pd.Timestamp(date), idx, list(o), list(h), list(l), list(c), [100.0] * n)


def _flat_day(price, n=10, date="2024-01-02") -> Day:
    return _make_day([price] * n, [price + 0.1] * n, [price - 0.1] * n, [price] * n, date)


# --------------------------------------------------------------------------
# ATR quotidien causal : pas de fuite de futur
# --------------------------------------------------------------------------
def test_daily_atr_no_lookahead():
    days = [_flat_day(100 + i, date=f"2024-01-{2+i:02d}") for i in range(20)]
    atr1 = compute_daily_atr(days, atr_period=5)
    days2 = [_flat_day(100 + i, date=f"2024-01-{2+i:02d}") for i in range(19)]
    days2.append(_flat_day(9999, date="2024-01-21"))  # dernier jour tres different
    atr2 = compute_daily_atr(days2, atr_period=5)
    # atr[i] pour i < 19 ne doit pas dependre du dernier jour modifie
    assert np.allclose(atr1[:19], atr2[:19], equal_nan=True)


def test_daily_atr_nan_until_enough_history():
    days = [_flat_day(100 + i, date=f"2024-01-{2+i:02d}") for i in range(10)]
    atr = compute_daily_atr(days, atr_period=5)
    # tr[0] est toujours nan (pas de cloture veille pour le jour 0), donc il
    # faut atr_period+1 jours connus avant d'obtenir atr_period valeurs de TR.
    assert all(np.isnan(a) for a in atr[:6])
    assert not np.isnan(atr[6])


# --------------------------------------------------------------------------
# Pas de gap significatif -> pas de trade
# --------------------------------------------------------------------------
def test_small_gap_no_trade():
    day = _flat_day(100.05, n=10)  # gap minuscule vs prev_close=100.0
    p = Params(gap_threshold_atr=0.5, direction="fill", confirm_bars=1)
    t = simulate_day(day, prev_close=100.0, daily_atr=1.0, p=p, inst=INST)
    assert t is None


def test_missing_atr_no_trade():
    day = _flat_day(105.0, n=10)
    p = Params(gap_threshold_atr=0.5, direction="fill", confirm_bars=1)
    t = simulate_day(day, prev_close=100.0, daily_atr=np.nan, p=p, inst=INST)
    assert t is None


# --------------------------------------------------------------------------
# Mode "fill" : gap up -> short, target = prev_close
# --------------------------------------------------------------------------
def test_fill_mode_gap_up_shorts_and_hits_target():
    prev_close = 100.0
    # Gap up a 105 (gap_atr = 5/2 = 2.5, largement > seuil). Le prix redescend
    # ensuite jusqu'a prev_close -> target touche.
    o = [105.0, 104.0, 100.0, 100.0, 100.0]
    h = [105.2, 104.2, 100.2, 100.2, 100.2]
    l = [104.8, 99.8, 99.8, 99.8, 99.8]
    c = [105.0, 104.0, 100.0, 100.0, 100.0]
    day = _make_day(o, h, l, c)
    p = Params(gap_threshold_atr=0.5, direction="fill", confirm_bars=1,
              atr_stop_mult=10.0, slippage_ticks=0.0)
    t = simulate_day(day, prev_close=prev_close, daily_atr=2.0, p=p, inst=INST)
    assert t is not None
    assert t["side"] == -1
    assert t["reason"] == "target"
    assert t["exit"] == pytest.approx(prev_close)


# --------------------------------------------------------------------------
# Mode "go" : gap up confirme par cassure du range de confirmation -> long
# --------------------------------------------------------------------------
def test_go_mode_gap_up_confirmed_goes_long():
    prev_close = 100.0
    # Gap up a 103. Range de confirmation (2 barres) : plafond 103.5. La barre
    # suivante casse ce plafond -> signal long.
    o = [103.0, 103.2, 104.0, 105.0, 105.0]
    h = [103.5, 103.5, 104.2, 105.2, 105.2]
    l = [102.8, 103.0, 103.9, 104.8, 104.8]
    c = [103.2, 103.4, 104.0, 105.0, 105.0]
    day = _make_day(o, h, l, c)
    p = Params(gap_threshold_atr=0.5, direction="go", confirm_bars=2,
              atr_stop_mult=10.0, atr_target_mult=10.0, slippage_ticks=0.0)
    t = simulate_day(day, prev_close=prev_close, daily_atr=1.0, p=p, inst=INST)
    assert t is not None
    assert t["side"] == 1


def test_go_mode_no_breakout_no_trade():
    prev_close = 100.0
    # Gap up a 103, mais le range de confirmation n'est jamais casse.
    o = [103.0, 103.2, 103.1, 103.0, 103.1]
    h = [103.5, 103.4, 103.3, 103.2, 103.3]
    l = [102.8, 103.0, 102.9, 102.8, 102.9]
    c = [103.2, 103.3, 103.1, 103.0, 103.1]
    day = _make_day(o, h, l, c)
    p = Params(gap_threshold_atr=0.5, direction="go", confirm_bars=2)
    t = simulate_day(day, prev_close=prev_close, daily_atr=1.0, p=p, inst=INST)
    assert t is None


# --------------------------------------------------------------------------
# Priorite stop > target sur la meme barre
# --------------------------------------------------------------------------
def test_stop_wins_over_target_same_bar():
    prev_close = 100.0
    # Gap up a 105 -> mode "fill" parie sur un SHORT (retour vers prev_close).
    # Entree a l'ouverture de la barre 1 (102, distincte de prev_close pour
    # que la distance au target soit non degeneree). La barre d'entree touche
    # largement le stop (h=200) ET le target (l=50) -> le stop doit gagner.
    o = [105.0, 102.0, 102.0]
    h = [105.2, 200.0, 102.2]
    l = [104.8, 50.0, 101.8]
    c = [105.0, 102.0, 102.0]
    day = _make_day(o, h, l, c)
    p = Params(gap_threshold_atr=0.5, direction="fill", confirm_bars=1,
              atr_stop_mult=0.1, slippage_ticks=0.0)
    t = simulate_day(day, prev_close=prev_close, daily_atr=2.0, p=p, inst=INST)
    assert t is not None
    assert t["reason"] == "stop"


# --------------------------------------------------------------------------
# Sortie forcee en fin de seance
# --------------------------------------------------------------------------
def test_forced_exit_at_session_close():
    prev_close = 100.0
    o = [105.0] + [102.0] * 5
    h = [105.2] + [102.2] * 5
    l = [104.8] + [101.8] * 5
    c = [105.0] + [102.0] * 5
    day = _make_day(o, h, l, c)
    p = Params(gap_threshold_atr=0.5, direction="fill", confirm_bars=1,
              atr_stop_mult=10.0, slippage_ticks=0.0)
    t = simulate_day(day, prev_close=prev_close, daily_atr=2.0, p=p, inst=INST)
    assert t is not None
    assert t["reason"] == "time"
    assert t["exit_time"] == day.idx[-1]


# --------------------------------------------------------------------------
# run_backtest : direction au hasard
# --------------------------------------------------------------------------
def test_run_backtest_random_direction_flips_side():
    days = []
    prev = _flat_day(100.0, n=10, date="2024-01-02")
    days.append(prev)
    o = [105.0] + [102.0] * 5
    h = [105.2] + [102.2] * 5
    l = [104.8] + [101.8] * 5
    c = [105.0] + [102.0] * 5
    days.append(_make_day(o, h, l, c, date="2024-01-03"))
    daily_atr = [np.nan, 2.0]
    p = Params(gap_threshold_atr=0.5, direction="fill", confirm_bars=1,
              atr_stop_mult=10.0, slippage_ticks=0.0)

    class FakeRng:
        def choice(self, opts):
            return 1  # force long, alors que le signal logique "fill" est short (gap up)

    trades = run_backtest(days, daily_atr, p, INST, rng=FakeRng())
    assert len(trades) == 1
    assert trades.iloc[0]["side"] == 1


# --------------------------------------------------------------------------
# Loader
# --------------------------------------------------------------------------
def test_load_bars_drops_incomplete_days(tmp_path):
    rows = []
    full_day = pd.date_range("2024-03-04 09:30", "2024-03-04 15:55", freq="5min", tz=TZ)
    for ts in full_day:
        rows.append({"datetime": ts.tz_convert("UTC").isoformat(), "open": 100, "high": 101,
                     "low": 99, "close": 100.5, "volume": 10})
    partial_day = pd.date_range("2024-03-05 09:30", "2024-03-05 10:00", freq="5min", tz=TZ)
    for ts in partial_day:
        rows.append({"datetime": ts.tz_convert("UTC").isoformat(), "open": 100, "high": 101,
                     "low": 99, "close": 100.5, "volume": 10})
    path = tmp_path / "bars.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    days, info = load_bars(str(path))
    assert info["days"] == 1
    assert info["dropped"] == 1
