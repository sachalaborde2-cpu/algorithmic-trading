import numpy as np
import pandas as pd
import pytest

from pairs_backtest import Params, PairDay, compute_beta_by_date, simulate_day

BM = 5  # minutes/barre


def make_day(c_spy, c_qqq, o_spy=None, o_qqq=None, date="2026-01-05"):
    n = len(c_spy)
    idx = pd.date_range(f"{date} 09:30", periods=n, freq=f"{BM}min")
    o_spy = o_spy if o_spy is not None else c_spy
    o_qqq = o_qqq if o_qqq is not None else c_qqq
    return PairDay(pd.Timestamp(date), idx, o_spy, c_spy, o_qqq, c_qqq)


def test_constant_spread_never_signals():
    n = 40
    day = make_day([500.0] * n, [400.0] * n)
    p = Params(warmup_minutes=10, entry_z=2.0, exit_z=0.5, stop_z=3.5)
    trade = simulate_day(day, p, beta=1.0, bar_minutes=BM)
    assert trade is None


def test_deviation_triggers_correct_direction_long_spread():
    n = 40
    # spread = log(spy) - beta*log(qqq), beta=1.0 -> log(spy/qqq)
    # ratio constant a 1.25 (spread ~constant) puis une chute nette de SPY seul
    # -> spread chute fortement -> z tres negatif -> signal LONG spread (d_sig=+1)
    c_spy = [500.0] * n
    c_qqq = [400.0] * n
    drop_bar = 25
    for i in range(drop_bar, n):
        c_spy[i] = 495.0  # SPY baisse, QQQ ne bouge pas -> spread baisse nettement
    day = make_day(c_spy, c_qqq)
    p = Params(warmup_minutes=10, entry_z=1.0, exit_z=0.2, stop_z=10.0)
    trade = simulate_day(day, p, beta=1.0, bar_minutes=BM)
    assert trade is not None
    assert trade["side"] == 1  # spread trop bas -> long spread (long SPY / short QQQ)


def test_deviation_triggers_correct_direction_short_spread():
    n = 40
    c_spy = [500.0] * n
    c_qqq = [400.0] * n
    jump_bar = 25
    for i in range(jump_bar, n):
        c_spy[i] = 505.0  # SPY monte -> spread monte nettement -> short spread
    day = make_day(c_spy, c_qqq)
    p = Params(warmup_minutes=10, entry_z=1.0, exit_z=0.2, stop_z=10.0)
    trade = simulate_day(day, p, beta=1.0, bar_minutes=BM)
    assert trade is not None
    assert trade["side"] == -1


def test_stop_triggers_when_spread_keeps_diverging_after_entry():
    """Le spread continue de s'ecarter (dans le sens defavorable) juste apres
    l'entree : le stop doit se declencher avant tout retour a la moyenne, sur
    la clôture qui suit immediatement le signal."""
    n = 40
    o_spy = [500.0] * n
    c_spy = [500.0] * n
    o_qqq = [400.0] * n
    c_qqq = [400.0] * n
    c_spy[20] = 499.8  # signal (spread trop bas) a la barre 20
    o_spy[21] = 499.8  # entree a l'ouverture de la barre 21 (= clôture du signal)
    c_spy[21] = 480.0  # la barre 21 clôture bien au-dela du stop -> divergence
    for i in range(22, n):
        o_spy[i] = 480.0
        c_spy[i] = 480.0
    day = make_day(c_spy, c_qqq, o_spy=o_spy, o_qqq=o_qqq)
    p_stop = Params(warmup_minutes=10, entry_z=2.0, exit_z=100.0, stop_z=6.0)
    trade_stop = simulate_day(day, p_stop, beta=1.0, bar_minutes=BM)
    assert trade_stop is not None
    assert trade_stop["reason"] == "stop"
    assert trade_stop["side"] == 1


def test_no_lookahead_deviation_only_from_past_and_current_bars():
    """Le z-score a la barre k ne doit pas dependre des barres futures : si on
    tronque la journee juste apres le signal, le meme signal doit apparaitre
    (memes deviations jusque-la)."""
    n = 40
    c_spy = [500.0] * n
    c_qqq = [400.0] * n
    for i in range(25, n):
        c_spy[i] = 495.0
    day_full = make_day(c_spy, c_qqq)
    day_truncated = make_day(c_spy[:30], c_qqq[:30])
    p = Params(warmup_minutes=10, entry_z=1.0, exit_z=0.2, stop_z=10.0)
    t_full = simulate_day(day_full, p, beta=1.0, bar_minutes=BM)
    t_trunc = simulate_day(day_truncated, p, beta=1.0, bar_minutes=BM)
    assert t_full is not None and t_trunc is not None
    assert t_full["entry_time"] == t_trunc["entry_time"]
    assert t_full["side"] == t_trunc["side"]


def test_forced_exit_at_session_close():
    n = 40
    c_spy = [500.0] * n
    c_qqq = [400.0] * n
    for i in range(35, n):
        c_spy[i] = 495.0  # signal tard, jamais le temps de revenir ou stopper
    day = make_day(c_spy, c_qqq)
    p = Params(warmup_minutes=10, entry_z=1.0, exit_z=0.01, stop_z=50.0)
    trade = simulate_day(day, p, beta=1.0, bar_minutes=BM)
    assert trade is not None
    assert trade["reason"] == "time"
    assert trade["exit_time"] == day.idx[-1]


def test_random_direction_override_changes_side_deterministically():
    n = 40
    c_spy = [500.0] * n
    c_qqq = [400.0] * n
    for i in range(25, n):
        c_spy[i] = 495.0
    day = make_day(c_spy, c_qqq)
    p = Params(warmup_minutes=10, entry_z=1.0, exit_z=0.2, stop_z=10.0)
    expected_side = int(np.random.default_rng(7).choice((-1, 1)))
    trade = simulate_day(day, p, beta=1.0, bar_minutes=BM, rng=np.random.default_rng(7))
    assert trade["side"] == expected_side


def test_compute_beta_by_date_uses_only_prior_days():
    days = []
    for i in range(25):
        c_spy = [500.0 + i] * 10
        c_qqq = [400.0 + i * 2] * 10  # relation lineaire changeant avec i
        days.append(make_day(c_spy, c_qqq, date=f"2026-01-{i + 1:02d}" if i < 9 else f"2026-02-{i - 8:02d}"))
    beta_by_date = compute_beta_by_date(days, beta_window=20)
    # les 20 premiers jours n'ont pas assez d'historique -> pas de beta
    for d in days[:20]:
        assert d.date not in beta_by_date
    for d in days[20:]:
        assert d.date in beta_by_date
    # le beta du jour 20 ne doit pas changer si on modifie les jours APRES lui
    days_altered = list(days)
    altered_last = make_day([9999.0] * 10, [1.0] * 10, date=days[-1].date.strftime("%Y-%m-%d"))
    days_altered[-1] = altered_last
    beta_by_date_altered = compute_beta_by_date(days_altered, beta_window=20)
    assert beta_by_date[days[20].date] == beta_by_date_altered[days[20].date]


def test_run_backtest_returns_dataframe_with_expected_columns():
    from pairs_backtest import TRADE_COLS, run_backtest

    n = 40
    c_spy = [500.0] * n
    c_qqq = [400.0] * n
    for i in range(25, n):
        c_spy[i] = 495.0
    days = [make_day(c_spy, c_qqq)]
    p = Params(warmup_minutes=10, entry_z=1.0, exit_z=0.2, stop_z=10.0)
    beta_by_date = {days[0].date: 1.0}
    df = run_backtest(days, p, beta_by_date, bar_minutes=BM)
    assert list(df.columns) == TRADE_COLS
    assert len(df) == 1
