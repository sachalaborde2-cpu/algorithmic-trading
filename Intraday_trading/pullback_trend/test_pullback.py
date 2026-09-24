"""Tests unitaires pour pullback_backtest.py : pas de fuite de futur, logique de
tendance/pullback, priorite stop > target, sortie forcee, plafond de trades/jour."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pullback_backtest import (
    Day, Instrument, Params, atr_series, ema_series, load_bars, run_backtest,
    simulate_day,
)

INST = Instrument(tick=0.01, point_value=1.0, commission_side=0.0)
TZ = "America/New_York"


def _make_day(o, h, l, c, v=None, date="2024-01-02") -> Day:
    n = len(c)
    v = v or [100.0] * n
    idx = pd.date_range(f"{date} 09:30", periods=n, freq="5min", tz=TZ)
    return Day(pd.Timestamp(date), idx, list(o), list(h), list(l), list(c), list(v))


# --------------------------------------------------------------------------
# Indicateurs causaux : pas de fuite de futur
# --------------------------------------------------------------------------
def test_ema_series_no_lookahead():
    closes = [100.0, 101.0, 99.0, 102.0, 103.0, 101.0, 104.0]
    ema1 = ema_series(closes, period=3)
    closes2 = closes[:-1] + [9999.0]
    ema2 = ema_series(closes2, period=3)
    assert np.allclose(ema1[:-1], ema2[:-1])


def test_atr_series_no_lookahead():
    o = [100, 101, 99, 102, 103, 101, 104]
    h = [101, 102, 100, 103, 104, 102, 106]
    l = [99, 100, 98, 101, 102, 100, 103]
    c = [100.5, 101.5, 99.5, 102.5, 103.5, 101.5, 104.5]
    atr1 = atr_series(o, h, l, c, period=3)
    h2 = h[:-1] + [9999.0]
    atr2 = atr_series(o, h2, l, c, period=3)
    assert np.allclose(atr1[:-1], atr2[:-1])


# --------------------------------------------------------------------------
# Pas de pullback -> pas de trade
# --------------------------------------------------------------------------
def test_straight_uptrend_no_pullback_no_trade():
    """Tendance haussiere ininterrompue : la cloture ne repasse jamais sous
    ema_fast, donc aucun pullback ne s'ouvre -> 0 trade."""
    n = 30
    c = [100.0 + i for i in range(n)]        # montee stricte, sans creux
    o = [100.0] + c[:-1]
    h = [x + 0.1 for x in c]
    l = [x - 0.1 for x in c]
    day = _make_day(o, h, l, c)
    p = Params(ema_fast=3, ema_slow=6, min_trend_bars=2, atr_period=3)
    trades = simulate_day(day, p, INST)
    assert trades == []


def test_flat_prices_no_trend_no_trade():
    """Prix constant : ema_fast == ema_slow partout, aucune tendance -> 0 trade."""
    n = 30
    c = [100.0] * n
    o, h, l = c[:], c[:], c[:]
    day = _make_day(o, h, l, c)
    p = Params(ema_fast=3, ema_slow=6, min_trend_bars=2, atr_period=3)
    trades = simulate_day(day, p, INST)
    assert trades == []


def test_insufficient_trend_history_blocks_signal():
    """min_trend_bars tres eleve (jamais atteint sur la journee) -> aucune
    tendance n'est jamais validee -> 0 trade, meme si un pullback existe."""
    c = [100, 101, 102, 103, 104, 103, 105, 106, 107, 108]
    o = [100.0] + [float(x) for x in c[:-1]]
    h = [x + 0.5 for x in c]
    l = [x - 0.5 for x in c]
    day = _make_day(o, h, l, c)
    p = Params(ema_fast=2, ema_slow=4, min_trend_bars=50, atr_period=3)
    trades = simulate_day(day, p, INST)
    assert trades == []


# --------------------------------------------------------------------------
# Signal de pullback long : verifie sur des cas construits a la main
# --------------------------------------------------------------------------
def test_pullback_long_signal_fires_and_exits_by_time():
    """Tendance haussiere etablie, un pullback (cloture sous ema_fast) suivi
    d'une reprise (cloture au-dessus) doit generer un signal LONG. Les barres
    suivantes sont plates (ni stop ni target touches) -> sortie forcee en fin
    de seance."""
    c = [100, 101, 102, 103, 104, 103, 105]   # pullback a l'indice 5, reprise a l'indice 6
    c += [105.0] * 5                           # plat ensuite : ni stop ni target
    o = [100.0] + [float(x) for x in c[:-1]]
    h = [x + 0.2 for x in c]
    l = [x - 0.2 for x in c]
    day = _make_day(o, h, l, c)
    p = Params(ema_fast=2, ema_slow=4, min_trend_bars=1, atr_period=3,
              atr_stop_mult=5.0, atr_target_mult=5.0, slippage_ticks=0.0)
    trades = simulate_day(day, p, INST)
    assert len(trades) == 1
    t = trades[0]
    assert t["side"] == 1
    assert t["reason"] == "time"
    assert t["entry_time"] == day.idx[7]


def test_pullback_short_signal_symmetric():
    """Symetrique a la baisse : tendance baissiere, pullback (cloture au-dessus
    de ema_fast) puis reprise baissiere (cloture en dessous) -> signal SHORT."""
    c = [200, 199, 198, 197, 196, 197, 195]
    c += [195.0] * 5
    o = [200.0] + [float(x) for x in c[:-1]]
    h = [x + 0.2 for x in c]
    l = [x - 0.2 for x in c]
    day = _make_day(o, h, l, c)
    p = Params(ema_fast=2, ema_slow=4, min_trend_bars=1, atr_period=3,
              atr_stop_mult=5.0, atr_target_mult=5.0, slippage_ticks=0.0)
    trades = simulate_day(day, p, INST)
    assert len(trades) == 1
    assert trades[0]["side"] == -1


# --------------------------------------------------------------------------
# Priorite stop > target si les deux sont touches sur la meme barre
# --------------------------------------------------------------------------
def test_stop_wins_over_target_same_bar():
    c = [100, 101, 102, 103, 104, 103, 105]
    o = [100.0] + [float(x) for x in c[:-1]]
    h = [x + 0.2 for x in c]
    l = [x - 0.2 for x in c]
    # Barre d'entree (indice 7) : range large qui touche a la fois le stop
    # (tres proche, bas) et le target (tres large, haut) -> le stop doit gagner.
    o += [105.0]
    h += [200.0]     # touche largement le target
    l += [50.0]      # touche largement le stop
    c += [105.0]
    day = _make_day(o, h, l, c)
    p = Params(ema_fast=2, ema_slow=4, min_trend_bars=1, atr_period=3,
              atr_stop_mult=0.1, atr_target_mult=50.0, slippage_ticks=0.0)
    trades = simulate_day(day, p, INST)
    assert len(trades) == 1
    assert trades[0]["reason"] == "stop"


# --------------------------------------------------------------------------
# Plafond de trades par jour
# --------------------------------------------------------------------------
def test_max_trades_per_day_cap():
    """Motif pullback->reprise repete plusieurs fois dans la journee : le nombre
    de trades ne doit jamais depasser max_trades_per_day."""
    pattern = [100, 101, 102, 103, 104, 103, 105]
    c = pattern * 4  # motif repete -> plusieurs signaux potentiels
    o = [100.0] + [float(x) for x in c[:-1]]
    h = [x + 0.2 for x in c]
    l = [x - 0.2 for x in c]
    day = _make_day(o, h, l, c)
    p = Params(ema_fast=2, ema_slow=4, min_trend_bars=1, atr_period=3,
              atr_stop_mult=0.5, atr_target_mult=0.5, max_trades_per_day=2,
              slippage_ticks=0.0)
    trades = simulate_day(day, p, INST)
    assert len(trades) <= 2


# --------------------------------------------------------------------------
# Sortie forcee en fin de seance
# --------------------------------------------------------------------------
def test_forced_exit_at_session_close():
    c = [100, 101, 102, 103, 104, 103, 105] + [105.0] * 5
    o = [100.0] + [float(x) for x in c[:-1]]
    h = [x + 0.2 for x in c]
    l = [x - 0.2 for x in c]
    day = _make_day(o, h, l, c)
    p = Params(ema_fast=2, ema_slow=4, min_trend_bars=1, atr_period=3,
              atr_stop_mult=10.0, atr_target_mult=10.0, slippage_ticks=0.0)
    trades = simulate_day(day, p, INST)
    assert len(trades) == 1
    assert trades[0]["reason"] == "time"
    assert trades[0]["exit_time"] == day.idx[-1]


# --------------------------------------------------------------------------
# Loader : reutilisation du meme schema que l'ORB / VWAP reversion
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


def test_run_backtest_random_direction_flips_side(monkeypatch):
    """Avec un rng fourni, la direction du trade est tiree au hasard, pas
    forcement celle du signal detecte."""
    c = [100, 101, 102, 103, 104, 103, 105] + [105.0] * 5
    o = [100.0] + [float(x) for x in c[:-1]]
    h = [x + 0.2 for x in c]
    l = [x - 0.2 for x in c]
    day = _make_day(o, h, l, c)
    p = Params(ema_fast=2, ema_slow=4, min_trend_bars=1, atr_period=3,
              atr_stop_mult=10.0, atr_target_mult=10.0, slippage_ticks=0.0)
    # rng qui force toujours -1, alors que le signal logique est +1 (long)
    class FakeRng:
        def choice(self, opts):
            return -1
    trades = simulate_day(day, p, INST, rng=FakeRng())
    assert len(trades) == 1
    assert trades[0]["side"] == -1
