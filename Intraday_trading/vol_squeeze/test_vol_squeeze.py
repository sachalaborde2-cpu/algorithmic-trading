"""Tests unitaires pour vol_squeeze_backtest.py : pas de fuite de futur sur les
bandes de Bollinger / le squeeze, detection correcte du breakout, priorite
stop > target, sortie forcee, plafond de trades/jour, bascule de direction."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from vol_squeeze_backtest import (Day, Instrument, Params, bollinger, load_bars,
                                  run_backtest, simulate_day, squeeze_flags)

INST = Instrument(tick=0.01, point_value=1.0, commission_side=0.0)
TZ = "America/New_York"


def _make_day(o, h, l, c, date="2024-01-02") -> Day:
    n = len(c)
    idx = pd.date_range(f"{date} 09:30", periods=n, freq="5min", tz=TZ)
    return Day(pd.Timestamp(date), idx, list(o), list(h), list(l), list(c), [100.0] * n)


# --------------------------------------------------------------------------
# Bollinger / bandwidth : pas de fuite de futur
# --------------------------------------------------------------------------
def test_bollinger_no_lookahead():
    c1 = [100.0 + i * 0.1 for i in range(30)]
    c2 = c1[:25] + [9999.0] * 5   # modifie seulement la fin
    _, u1, l1, bw1 = bollinger(c1, period=10, k=2.0)
    _, u2, l2, bw2 = bollinger(c2, period=10, k=2.0)
    # les 15 premieres valeurs (bien avant la modification, avec period=10) sont identiques
    assert np.allclose(u1[:15], u2[:15])
    assert np.allclose(l1[:15], l2[:15])
    assert np.allclose(bw1[:15], bw2[:15])


def test_bollinger_flat_price_zero_bandwidth():
    c = [100.0] * 20
    _, upper, lower, bandwidth = bollinger(c, period=10, k=2.0)
    assert np.allclose(upper, 100.0)
    assert np.allclose(lower, 100.0)
    assert np.allclose(bandwidth, 0.0)


def test_squeeze_flags_no_lookahead():
    # bandwidth construit a la main : compression (indices 10-19) puis expansion (20-24)
    bandwidth = np.array([5.0] * 10 + [0.1] * 10 + [8.0] * 5)
    sq = squeeze_flags(bandwidth, lookback=10, pctl=20.0)
    # avant d'avoir assez d'historique (i < lookback), jamais de squeeze
    assert not sq[:10].any()
    # on modifie uniquement la fin (expansion, indices 20+) : les flags 0..19 ne doivent pas bouger
    bandwidth2 = bandwidth.copy()
    bandwidth2[20:] = 999.0
    sq2 = squeeze_flags(bandwidth2, lookback=10, pctl=20.0)
    assert np.array_equal(sq[:20], sq2[:20])
    # une fois qu'on a accumule des valeurs basses dans la fenetre passee, le squeeze se detecte
    assert sq[19]


# --------------------------------------------------------------------------
# Squeeze + breakout -> trade dans le bon sens
# --------------------------------------------------------------------------
def test_squeeze_then_breakout_up_goes_long():
    # 20 barres plates (squeeze_lookback) puis compression proche de zero, puis
    # cassure nette vers le haut.
    n_flat = 20
    o = [100.0] * n_flat
    h = [100.05] * n_flat
    l = [99.95] * n_flat
    c = [100.0] * n_flat
    # phase de compression tres serree (alimente le squeeze_lookback avec du bas)
    for _ in range(10):
        o.append(100.0); h.append(100.01); l.append(99.99); c.append(100.0)
    # barre de breakout franche vers le haut
    o.append(100.0); h.append(103.0); l.append(100.0); c.append(103.0)
    # barres suivantes pour laisser le trade se derouler
    for _ in range(5):
        o.append(103.0); h.append(103.2); l.append(102.8); c.append(103.0)
    day = _make_day(o, h, l, c)
    p = Params(bb_period=10, bb_k=2.0, squeeze_lookback=20, squeeze_pctl=50.0,
              atr_stop_mult=0.5, atr_target_mult=1.0, slippage_ticks=0.0)
    trades = simulate_day(day, p, INST)
    assert len(trades) >= 1
    assert trades[0]["side"] == 1


def test_no_squeeze_no_trade():
    # Volatilite strictement croissante -> le bandwidth actuel n'est jamais dans
    # le bas percentile de sa fenetre passee -> jamais de squeeze arme.
    n = 60
    c = [100.0]
    for i in range(1, n):
        c.append(c[-1] + (0.05 if i % 2 == 0 else -0.02) * (1 + i * 0.05))
    o = c.copy()
    h = [x + 0.05 for x in c]
    l = [x - 0.05 for x in c]
    day = _make_day(o, h, l, c)
    p = Params(bb_period=10, bb_k=2.0, squeeze_lookback=20, squeeze_pctl=1.0,
              atr_stop_mult=0.5, atr_target_mult=1.0)
    trades = simulate_day(day, p, INST)
    assert trades == []


# --------------------------------------------------------------------------
# Priorite stop > target sur la meme barre
# --------------------------------------------------------------------------
def test_stop_wins_over_target_same_bar():
    n_flat = 20
    o = [100.0] * n_flat
    h = [100.05] * n_flat
    l = [99.95] * n_flat
    c = [100.0] * n_flat
    for _ in range(10):
        o.append(100.0); h.append(100.01); l.append(99.99); c.append(100.0)
    o.append(100.0); h.append(103.0); l.append(100.0); c.append(103.0)   # breakout haussier
    # barre suivante : touche largement stop ET target
    o.append(103.0); h.append(200.0); l.append(50.0); c.append(103.0)
    o.append(103.0); h.append(103.2); l.append(102.8); c.append(103.0)
    day = _make_day(o, h, l, c)
    p = Params(bb_period=10, bb_k=2.0, squeeze_lookback=20, squeeze_pctl=50.0,
              atr_stop_mult=0.1, atr_target_mult=5.0, slippage_ticks=0.0)
    trades = simulate_day(day, p, INST)
    assert len(trades) == 1
    assert trades[0]["reason"] == "stop"


# --------------------------------------------------------------------------
# Sortie forcee en fin de seance
# --------------------------------------------------------------------------
def test_forced_exit_at_session_close():
    n_flat = 20
    o = [100.0] * n_flat
    h = [100.05] * n_flat
    l = [99.95] * n_flat
    c = [100.0] * n_flat
    for _ in range(10):
        o.append(100.0); h.append(100.01); l.append(99.99); c.append(100.0)
    o.append(100.0); h.append(103.0); l.append(100.0); c.append(103.0)
    for _ in range(5):
        o.append(103.0); h.append(103.05); l.append(102.95); c.append(103.0)
    day = _make_day(o, h, l, c)
    p = Params(bb_period=10, bb_k=2.0, squeeze_lookback=20, squeeze_pctl=50.0,
              atr_stop_mult=10.0, atr_target_mult=10.0, slippage_ticks=0.0)
    trades = simulate_day(day, p, INST)
    assert len(trades) == 1
    assert trades[0]["reason"] == "time"
    assert trades[0]["exit_time"] == day.idx[-1]


# --------------------------------------------------------------------------
# Plafond de trades par jour
# --------------------------------------------------------------------------
def test_max_trades_per_day_respected():
    n_flat = 20
    o = [100.0] * n_flat
    h = [100.05] * n_flat
    l = [99.95] * n_flat
    c = [100.0] * n_flat
    # deux cycles compression -> breakout -> retour au calme, pour generer 2+ signaux
    for _ in range(2):
        for _ in range(10):
            o.append(100.0); h.append(100.01); l.append(99.99); c.append(100.0)
        o.append(100.0); h.append(103.0); l.append(100.0); c.append(103.0)
        for _ in range(3):
            o.append(103.0); h.append(103.05); l.append(102.95); c.append(103.0)
    day = _make_day(o, h, l, c)
    p = Params(bb_period=10, bb_k=2.0, squeeze_lookback=20, squeeze_pctl=90.0,
              atr_stop_mult=0.2, atr_target_mult=0.3, max_trades_per_day=1,
              slippage_ticks=0.0)
    trades = simulate_day(day, p, INST)
    assert len(trades) <= 1


# --------------------------------------------------------------------------
# run_backtest : direction au hasard
# --------------------------------------------------------------------------
def test_run_backtest_random_direction_flips_side():
    n_flat = 20
    o = [100.0] * n_flat
    h = [100.05] * n_flat
    l = [99.95] * n_flat
    c = [100.0] * n_flat
    for _ in range(10):
        o.append(100.0); h.append(100.01); l.append(99.99); c.append(100.0)
    o.append(100.0); h.append(103.0); l.append(100.0); c.append(103.0)   # signal logique = LONG
    for _ in range(5):
        o.append(103.0); h.append(103.2); l.append(102.8); c.append(103.0)
    day = _make_day(o, h, l, c)
    p = Params(bb_period=10, bb_k=2.0, squeeze_lookback=20, squeeze_pctl=50.0,
              atr_stop_mult=0.5, atr_target_mult=1.0, slippage_ticks=0.0)

    class FakeRng:
        def choice(self, opts):
            return -1  # force short, alors que le signal logique est long

    trades = run_backtest([day], p, INST, rng=FakeRng())
    assert len(trades) == 1
    assert trades.iloc[0]["side"] == -1


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
