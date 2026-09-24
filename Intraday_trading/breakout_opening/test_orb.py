"""Tests unitaires du moteur ORB. Lancer avec : pytest -q"""
import numpy as np
import pandas as pd
import pytest

from orb_backtest import INSTRUMENTS, TZ, Day, Params, load_bars, simulate_day

INST = INSTRUMENTS["MES"]
N = 78  # barres de 5 min entre 09:30 et 16:00


def make_day(overrides: dict[int, tuple], base=(100.0, 100.5, 99.5, 100.0)) -> Day:
    """Journee plate autour de 100, avec des barres (o, h, l, c) imposees a certains index."""
    bars = [overrides.get(i, base) for i in range(N)]
    idx = pd.date_range("2024-03-04 09:30", periods=N, freq="5min", tz=TZ)
    o, h, l, c = (list(x) for x in zip(*bars))
    return Day(pd.Timestamp("2024-03-04"), idx, o, h, l, c)


# Opening range 30 min = barres 0 a 5 : high 100.5, low 99.5.
# Barre 7 cloture a 101 (> 100.5) : signal. Entree a l'open de la barre 8.
BREAKOUT_UP = {7: (100.0, 101.2, 100.0, 101.0), 8: (101.0, 101.3, 100.8, 101.1)}
FLAT_AFTER = (101.1, 101.4, 100.9, 101.1)


def up_day(extra=None) -> Day:
    ov = {**BREAKOUT_UP, **{i: FLAT_AFTER for i in range(9, N)}}
    ov.update(extra or {})
    return make_day(ov)


def test_entry_is_next_bar_open_plus_slippage():
    day = up_day()
    t = simulate_day(day, Params(), INST)
    assert t["side"] == 1
    assert t["entry_time"] == day.idx[8]                # barre suivant le signal
    assert t["entry"] == pytest.approx(101.0 + 0.25)    # open + 1 tick
    assert t["reason"] == "time"
    assert t["exit_time"] == day.idx[N - 1]


def test_no_trade_when_range_never_broken():
    assert simulate_day(make_day({}), Params(), INST) is None


def test_no_lookahead_on_entry():
    """Changer tout ce qui suit l'open de la barre d'entree ne doit pas changer l'entree."""
    rng = np.random.default_rng(1)
    ref = simulate_day(up_day(), Params(), INST)
    for _ in range(20):
        noise = {}
        for i in range(9, N):
            o = 101.0 + rng.normal(0, 0.3)
            noise[i] = (o, o + abs(rng.normal(0, 0.3)), o - abs(rng.normal(0, 0.3)), o + rng.normal(0, 0.2))
        # on change aussi high/low/close de la barre d'entree (mais pas son open)
        noise[8] = (101.0, 101.0 + rng.uniform(0.1, 2), 100.9, 101.0 + rng.normal(0, 0.3))
        t = simulate_day(up_day(noise), Params(), INST)
        if t is None:
            continue
        assert t["entry_time"] == ref["entry_time"]
        assert t["entry"] == ref["entry"]


def test_signal_needs_a_close_outside_the_range():
    """Une meche au-dessus du range sans cloture au-dessus ne declenche rien."""
    day = make_day({7: (100.0, 102.0, 99.9, 100.2)})
    assert simulate_day(day, Params(), INST) is None


def test_stop_has_priority_when_stop_and_target_hit_same_bar():
    # entree 101.25, stop 99.5 -> risque 1.75, target 1R = 103.0
    wild = (101.1, 110.0, 90.0, 101.1)   # touche le stop ET la cible
    t = simulate_day(up_day({9: wild}), Params(target_r=1.0), INST)
    assert t["reason"] == "stop"
    assert t["exit"] == pytest.approx(99.5 - 0.25)      # stop moins slippage


def test_target_fills_only_if_price_trades_through():
    # target 1R = 103.0 ; un high a 103.0 exactement ne suffit pas (il faut 103.25)
    touch = (101.1, 103.0, 101.0, 101.5)
    t = simulate_day(up_day({9: touch}), Params(target_r=1.0), INST)
    assert t["reason"] == "time"
    through = (101.1, 103.25, 101.0, 101.5)
    t = simulate_day(up_day({9: through}), Params(target_r=1.0), INST)
    assert t["reason"] == "target" and t["exit"] == pytest.approx(103.0)


def test_gap_through_stop_exits_at_open_not_at_stop():
    gap = (98.0, 98.5, 97.5, 98.0)       # ouvre sous le stop (99.5)
    t = simulate_day(up_day({9: gap}), Params(), INST)
    assert t["reason"] == "stop_gap"
    assert t["exit"] == pytest.approx(98.0 - 0.25)


def test_short_side_is_symmetric():
    ov = {7: (100.0, 100.0, 98.8, 99.0), 8: (99.0, 99.2, 98.7, 98.9)}
    ov.update({i: (98.9, 99.1, 98.6, 98.9) for i in range(9, N)})
    t = simulate_day(make_day(ov), Params(), INST)
    assert t["side"] == -1
    assert t["entry"] == pytest.approx(99.0 - 0.25)      # short : slippage defavorable
    assert t["pnl"] == pytest.approx(t["pts"] * 5.0 - 2 * INST.commission_side)


def test_costs_are_applied():
    p = Params(slippage_ticks=0.0)
    t = simulate_day(up_day(), p, INST)
    assert t["pts"] == pytest.approx(101.1 - 101.0)
    assert t["pnl"] == pytest.approx(0.1 * 5.0 - 2 * 0.85)


def test_random_direction_keeps_timing():
    rng = np.random.default_rng(0)
    ref = simulate_day(up_day(), Params(), INST)
    seen = set()
    for _ in range(30):
        t = simulate_day(up_day(), Params(), INST, rng=rng)
        assert t["entry_time"] == ref["entry_time"]
        seen.add(t["side"])
    assert seen == {1, -1}


# --------------------------------------------------------------------------
# Chargement des donnees : heure d'ete / heure d'hiver
# --------------------------------------------------------------------------
def _csv(tmp_path, blocks):
    frames = []
    for start_utc, contract, vol in blocks:
        ts = pd.date_range(start_utc, periods=N, freq="5min", tz="UTC")
        frames.append(pd.DataFrame({"datetime": ts.strftime("%Y-%m-%d %H:%M:%S%z"),
                                    "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0,
                                    "volume": vol, "contract": contract}))
    path = tmp_path / "bars.csv"
    pd.concat(frames).to_csv(path, index=False)
    return str(path)


def test_dst_sessions_are_aligned(tmp_path):
    # 09:30 New York = 13:30 UTC en ete, 14:30 UTC en hiver
    path = _csv(tmp_path, [("2024-07-01 13:30", "MESU4", 100), ("2024-01-02 14:30", "MESH4", 100)])
    days, info = load_bars(path)
    assert info["days"] == 2 and info["dropped"] == 0
    assert all(d.idx[0].strftime("%H:%M") == "09:30" for d in days)


def test_wrong_utc_offset_day_is_dropped(tmp_path):
    # Session hivernale decalee d'une heure : ne doit pas etre acceptee comme complete
    path = _csv(tmp_path, [("2024-01-02 13:30", "MESH4", 100)])
    days, info = load_bars(path)
    assert info["days"] == 0 and info["dropped"] == 1


def test_front_contract_is_the_most_traded_one(tmp_path):
    path = _csv(tmp_path, [("2024-03-04 14:30", "OLD", 10), ("2024-03-04 14:30", "NEW", 500)])
    days, info = load_bars(path)
    assert info["days"] == 1   # un seul contrat retenu, pas de barres en double
    assert len(days[0].c) == N
