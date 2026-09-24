import numpy as np
import pandas as pd
import pytest

from seasonality_backtest import (
    Day, Instrument, Params, compute_daily_atr, run_backtest, select_best_slot,
    simulate_day, slot_return_matrix, slot_returns, slot_stats,
)

BAR_MIN = 5
SLOT_MIN = 30  # 6 barres de 5 min par tranche
INST = Instrument(tick=0.25, point_value=5.0, commission_side=0.0)


def make_day(date: str, opens: list, highs: list, lows: list, closes: list) -> Day:
    idx = pd.date_range(f"{date} 09:30", periods=len(closes), freq="5min")
    return Day(pd.Timestamp(date), idx, opens, highs, lows, closes)


def test_slot_returns_known_values():
    # 2 tranches de 30 min = 12 barres. Tranche 0 : open=100 -> close barre 5 = 110.
    # Tranche 1 : open barre 6 = 110 -> close barre 11 = 99.
    closes = [101, 103, 105, 107, 109, 110, 108, 106, 104, 102, 100, 99]
    opens = [100] + closes[:-1]
    highs = [max(o, c) for o, c in zip(opens, closes)]
    lows = [min(o, c) for o, c in zip(opens, closes)]
    day = make_day("2024-01-02", opens, highs, lows, closes)

    r = slot_returns(day, SLOT_MIN, BAR_MIN)

    assert len(r) == 2
    assert r[0] == pytest.approx(np.log(closes[5] / opens[0]))
    assert r[1] == pytest.approx(np.log(closes[11] / opens[6]))


def test_slot_returns_only_uses_bars_within_the_slot():
    # Modifier la barre de CLOTURE de la 2e tranche ne doit pas changer le
    # rendement de la 1ere tranche (aucune fuite de tranche future), mais
    # doit bien changer le rendement de la 2e tranche elle-meme.
    closes = [101, 103, 105, 107, 109, 110, 108, 106, 104, 102, 100, 99]
    opens = [100] + closes[:-1]
    highs = [max(o, c) for o, c in zip(opens, closes)]
    lows = [min(o, c) for o, c in zip(opens, closes)]
    day = make_day("2024-01-02", opens, highs, lows, closes)
    r_before = slot_returns(day, SLOT_MIN, BAR_MIN)

    closes2 = list(closes)
    closes2[11] = 500.0  # derniere barre de la 2e tranche (indice de cloture)
    day2 = make_day("2024-01-02", opens, highs, lows, closes2)
    r_after = slot_returns(day2, SLOT_MIN, BAR_MIN)

    assert r_after[0] == pytest.approx(r_before[0])
    assert r_after[1] != pytest.approx(r_before[1])


def _flat_day(date: str, level: float, n_bars: int = 78) -> Day:
    o = [level] * n_bars
    c = [level] * n_bars
    h = [level] * n_bars
    l = [level] * n_bars
    return make_day(date, o, h, l, c)


def _biased_days(n: int, slot_up: int, up_amount: float = 1.0, n_bars: int = 78,
                 bars_per_slot: int = 6, start: str = "2024-01-01") -> list[Day]:
    """Construit n jours ou seule la tranche `slot_up` a un rendement positif
    net et fort ; les autres tranches oscillent autour de 0 (bruit)."""
    days = []
    rng = np.random.default_rng(42)
    business_days = pd.bdate_range(start, periods=n)
    for i in range(n):
        level = 100.0
        o, h, l, c = [], [], [], []
        for b in range(n_bars):
            slot = b // bars_per_slot
            if slot == slot_up:
                delta = up_amount + rng.normal(0, 0.01)
            else:
                delta = rng.normal(0, 0.01)
            newlevel = level + delta
            o.append(level)
            c.append(newlevel)
            h.append(max(level, newlevel))
            l.append(min(level, newlevel))
            level = newlevel
        days.append(make_day(business_days[i].strftime("%Y-%m-%d"), o, h, l, c))
    return days


def test_select_best_slot_finds_the_biased_slot_on_training_data():
    days = _biased_days(n=40, slot_up=4)
    matrix = slot_return_matrix(days, SLOT_MIN, BAR_MIN)
    dates = pd.DatetimeIndex([d.date for d in days])

    slot, direction = select_best_slot(matrix, dates)

    assert slot == 4
    assert direction == 1


def test_select_best_slot_uses_only_training_dates_never_test_dates():
    # Le train est biaise sur la tranche 2 ; le test (jamais vu par la
    # selection) est biaise sur une autre tranche. La selection doit rester
    # sur la tranche du train.
    train_days = _biased_days(n=40, slot_up=2, start="2024-01-01")
    test_days = _biased_days(n=10, slot_up=9, start="2024-03-01")

    all_days = train_days + test_days
    matrix = slot_return_matrix(all_days, SLOT_MIN, BAR_MIN)
    train_dates = pd.DatetimeIndex([d.date for d in train_days])

    slot, direction = select_best_slot(matrix, train_dates)

    assert slot == 2
    assert direction == 1


def test_slot_stats_matches_manual_mean_and_tstat():
    days = _biased_days(n=30, slot_up=1)
    matrix = slot_return_matrix(days, SLOT_MIN, BAR_MIN)
    dates = pd.DatetimeIndex([d.date for d in days])

    stats_df = slot_stats(matrix, dates)
    col1 = matrix.loc[matrix.index.isin(dates), 1]

    expected_mean_bp = col1.mean() * 1e4
    expected_t = col1.mean() / col1.std() * np.sqrt(len(col1))

    assert stats_df.loc[1, "mean_bp"] == pytest.approx(expected_mean_bp)
    assert stats_df.loc[1, "t_stat"] == pytest.approx(expected_t)


def test_simulate_day_enters_at_slot_open_and_exits_at_slot_close_without_stop():
    closes = [101, 103, 105, 107, 109, 110, 108, 106, 104, 102, 100, 99]
    opens = [100] + closes[:-1]
    highs = [max(o, c) for o, c in zip(opens, closes)]
    lows = [min(o, c) for o, c in zip(opens, closes)]
    day = make_day("2024-01-02", opens, highs, lows, closes)

    p = Params(slot_minutes=SLOT_MIN, chosen_slot=0, direction=1,
              atr_stop_mult=None, atr_target_mult=None, slippage_ticks=0.0)
    trade = simulate_day(day, p, atr=None, inst=INST, bar_minutes=BAR_MIN)

    assert trade is not None
    assert trade["entry_time"] == day.idx[0]
    assert trade["exit_time"] == day.idx[5]
    assert trade["reason"] == "time"
    assert trade["pnl"] == pytest.approx(INST.point_value * (closes[5] - opens[0]))


def test_simulate_day_stop_triggers_on_adverse_move_within_slot():
    # Slot 0 = barres 0..5, direction longue. Prix chute fortement des la
    # barre 1 -> le stop (calcule a partir de l'ATR) doit se declencher avant
    # la fin de la tranche.
    opens = [100, 90, 70, 70, 70, 70] + [70] * 6
    closes = [90, 70, 70, 70, 70, 70] + [70] * 6
    highs = [max(o, c) for o, c in zip(opens, closes)]
    lows = [min(o, c) for o, c in zip(opens, closes)]
    day = make_day("2024-01-02", opens, highs, lows, closes)

    p = Params(slot_minutes=SLOT_MIN, chosen_slot=0, direction=1,
              atr_stop_mult=1.0, atr_target_mult=None, slippage_ticks=0.0)
    trade = simulate_day(day, p, atr=5.0, inst=INST, bar_minutes=BAR_MIN)

    assert trade is not None
    assert trade["reason"] == "stop"
    assert trade["side"] == 1


def test_simulate_day_random_direction_override_is_deterministic_with_seed():
    closes = [101, 103, 105, 107, 109, 110] + [110] * 6
    opens = [100] + closes[:-1]
    highs = [max(o, c) for o, c in zip(opens, closes)]
    lows = [min(o, c) for o, c in zip(opens, closes)]
    day = make_day("2024-01-02", opens, highs, lows, closes)

    p = Params(slot_minutes=SLOT_MIN, chosen_slot=0, direction=1)
    rng1 = np.random.default_rng(7)
    rng2 = np.random.default_rng(7)
    t1 = simulate_day(day, p, atr=None, inst=INST, bar_minutes=BAR_MIN, rng=rng1)
    t2 = simulate_day(day, p, atr=None, inst=INST, bar_minutes=BAR_MIN, rng=rng2)

    assert t1["side"] == t2["side"]


def test_compute_daily_atr_uses_only_prior_days():
    days = [_flat_day(f"2024-01-{i + 1:02d}", 100.0) for i in range(25)]
    for d in days:
        for j in range(len(d.h)):
            d.h[j] = 100.0 + 1.0
            d.l[j] = 100.0 - 1.0

    atr_before = compute_daily_atr(days, lookback=20)
    reference_atr = atr_before[days[20].date]

    days[24].h = [500.0] * len(days[24].h)
    days[24].l = [0.0] * len(days[24].l)
    atr_after = compute_daily_atr(days, lookback=20)

    assert atr_after[days[20].date] == pytest.approx(reference_atr)


def test_run_backtest_returns_dataframe_with_expected_columns():
    days = _biased_days(n=10, slot_up=0)
    p = Params(slot_minutes=SLOT_MIN, chosen_slot=0, direction=1)
    atr_by_date = compute_daily_atr(days, lookback=2)

    trades = run_backtest(days, p, atr_by_date, INST, BAR_MIN)

    expected_cols = ["date", "side", "entry_time", "exit_time", "pnl", "reason",
                     "risk_dollar", "r_mult"]
    assert list(trades.columns) == expected_cols
    assert len(trades) == 10
