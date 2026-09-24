"""Tests unitaires du moteur VWAP Reversion. Lancer avec : pytest -q"""
import numpy as np
import pandas as pd
import pytest

from vwap_backtest import (INSTRUMENTS, TZ, Day, Params, _vwap_series, compute_daily_trend,
                          load_bars, simulate_day)

INST = INSTRUMENTS["MES"]
N = 78  # barres de 5 min entre 09:30 et 16:00


def make_day(overrides: dict[int, tuple], base=(100.0, 100.0, 100.0, 100.0, 100.0)) -> Day:
    """Journee plate a 100 (volume 100), avec des barres (o, h, l, c, v) imposees a certains index."""
    bars = [overrides.get(i, base) for i in range(N)]
    idx = pd.date_range("2024-03-04 09:30", periods=N, freq="5min", tz=TZ)
    o, h, l, c, v = (list(x) for x in zip(*bars))
    return Day(pd.Timestamp("2024-03-04"), idx, o, h, l, c, v)


# --------------------------------------------------------------------------
# _vwap_series : verification independante sur un cas calculable a la main
# --------------------------------------------------------------------------
def test_vwap_series_matches_hand_calculation():
    # 3 barres, volumes differents : VWAP et variance ponderes, calcules a la main.
    o = [100, 100, 100]
    h = [100, 100, 100]
    l = [100, 100, 100]
    c = [100, 104, 94]          # typical price = (h+l+c)/3 = 100, 101.333.., 98
    v = [10, 20, 30]
    tp, vwap, std, dev = _vwap_series(o, h, l, c, v)

    tp_expected = np.array([100.0, 101 + 1 / 3, 98.0])
    assert tp == pytest.approx(tp_expected)

    cum_v = np.cumsum(v)
    cum_pv = np.cumsum(tp_expected * np.array(v))
    vwap_expected = cum_pv / cum_v
    assert vwap == pytest.approx(vwap_expected)

    cum_pv2 = np.cumsum(np.array(v) * tp_expected ** 2)
    var_expected = np.maximum(cum_pv2 / cum_v - vwap_expected ** 2, 0.0)
    std_expected = np.sqrt(var_expected)
    assert std == pytest.approx(std_expected)

    safe_std_expected = np.where(std_expected > 1e-9, std_expected, 1.0)
    dev_expected = np.where(std_expected > 1e-9, (tp_expected - vwap_expected) / safe_std_expected, 0.0)
    assert dev == pytest.approx(dev_expected)


def test_vwap_no_lookahead_by_construction():
    """vwap[j] et std[j] ne doivent dependre que des barres 0..j : changer une barre
    future ne doit rien changer aux valeurs passees."""
    rng = np.random.default_rng(0)
    o = [100.0] * 10
    h = [100.5] * 10
    l = [99.5] * 10
    c = [100.0] * 10
    v = [100.0] * 10
    _, vwap1, std1, dev1 = _vwap_series(o, h, l, c, v)

    c2 = c.copy()
    c2[7] = 130.0  # modifie seulement une barre future (apres l'indice 5)
    _, vwap2, std2, dev2 = _vwap_series(o, h, l, c2, v)

    assert vwap1[:5] == pytest.approx(vwap2[:5])
    assert std1[:5] == pytest.approx(std2[:5])
    assert dev1[:5] == pytest.approx(dev2[:5])


# --------------------------------------------------------------------------
# Construction d'une journee avec un signal long controle :
# 9 barres plates a 100 (vol 100), puis une barre 9 qui chute a 90 (vol 100).
# --------------------------------------------------------------------------
def down_day(extra_after: dict | None = None) -> Day:
    ov = {9: (90.0, 90.0, 90.0, 90.0, 100.0)}
    ov.update(extra_after or {})
    return make_day(ov)


def _expected_signal(day: Day, p: Params = Params()):
    tp, vwap, std, dev = _vwap_series(day.o, day.h, day.l, day.c, day.v)
    n_warm = p.warmup_minutes // 5
    for k in range(max(n_warm, 1), N - 1):
        if std[k] <= 1e-9:
            continue
        if dev[k] <= -p.entry_std:
            return 1, k, vwap, std, dev
        if dev[k] >= p.entry_std:
            return -1, k, vwap, std, dev
    return 0, None, vwap, std, dev


def test_entry_is_next_bar_open_plus_slippage():
    day = down_day()
    d_exp, k_exp, vwap, std, dev = _expected_signal(day)
    assert d_exp == 1   # chute -> ecart negatif -> long

    t = simulate_day(day, Params(), INST)
    assert t is not None
    assert t["side"] == 1
    assert t["entry_time"] == day.idx[k_exp + 1]
    assert t["entry"] == pytest.approx(day.o[k_exp + 1] + 0.25)   # open + 1 tick de slippage
    assert t["entry_dev"] == pytest.approx(dev[k_exp])


def test_no_trade_when_never_deviates():
    assert simulate_day(make_day({}), Params(), INST) is None


def test_no_signal_before_warmup():
    """Un ecart brutal pendant la periode de chauffe ne doit pas declencher de trade."""
    day = make_day({2: (90.0, 90.0, 90.0, 90.0, 100.0)})
    t = simulate_day(day, Params(warmup_minutes=60), INST)  # n_warm = 12 > barre 2
    assert t is None or t["entry_time"] > day.idx[3]


def test_no_lookahead_on_entry():
    """Changer tout ce qui suit l'open de la barre d'entree ne doit pas changer l'entree."""
    rng = np.random.default_rng(1)
    ref = simulate_day(down_day(), Params(), INST)
    for _ in range(20):
        noise = {}
        for i in range(11, N):
            px = 90.0 + rng.normal(0, 1.0)
            noise[i] = (px, px + abs(rng.normal(0, 0.5)), px - abs(rng.normal(0, 0.5)),
                        px + rng.normal(0, 0.3), 100.0)
        t = simulate_day(down_day(extra_after=noise), Params(), INST)
        if t is None:
            continue
        assert t["entry_time"] == ref["entry_time"]
        assert t["entry"] == ref["entry"]


def test_stop_has_priority_when_stop_and_target_hit_same_bar():
    p = Params()
    day = down_day({10: (90.0, 130.0, 50.0, 90.0, 100.0)})  # touche stop ET retour au VWAP
    d_exp, k_exp, vwap, std, dev = _expected_signal(day, p)
    stop_lvl = vwap[k_exp] - d_exp * p.stop_std * std[k_exp]

    t = simulate_day(day, p, INST)
    assert t["reason"] == "stop"
    assert t["exit"] == pytest.approx(stop_lvl - 0.25)


def test_target_fills_only_if_price_trades_through():
    p = Params()
    day_flat = down_day({10: (90.0, 90.5, 89.5, 90.0, 100.0)})
    d_exp, k_exp, vwap, std, dev = _expected_signal(day_flat, p)
    target_lvl = vwap[k_exp] - d_exp * p.exit_std * std[k_exp]
    thr = p.limit_through_ticks * INST.tick

    # High juste sous le seuil de declenchement -> pas de sortie sur objectif
    just_under = target_lvl - thr - 0.01
    day1 = down_day({10: (90.0, just_under, 89.5, 90.0, 100.0)})
    t1 = simulate_day(day1, p, INST)
    assert t1["reason"] != "target" or t1["exit_time"] != day1.idx[10]

    # High qui depasse le seuil -> sortie sur objectif, au niveau target_lvl exact
    through = target_lvl + thr + 0.01
    day2 = down_day({10: (90.0, through, 89.5, 90.0, 100.0)})
    t2 = simulate_day(day2, p, INST)
    assert t2["reason"] == "target"
    assert t2["exit"] == pytest.approx(target_lvl)


def test_gap_through_stop_exits_at_open_not_at_stop():
    p = Params()
    ref_day = down_day()
    d_exp, k_exp, vwap, std, dev = _expected_signal(ref_day, p)
    stop_lvl = vwap[k_exp] - d_exp * p.stop_std * std[k_exp]
    target_lvl = vwap[k_exp] - d_exp * p.exit_std * std[k_exp]
    entry_bar = k_exp + 1        # barre d'entree : entre stop et target, ne declenche rien
    hold_px = (stop_lvl + target_lvl) / 2
    gap_bar = entry_bar + 1      # barre SUIVANTE : ouvre nettement sous le stop
    gap_open = stop_lvl - 5.0
    day = down_day({entry_bar: (hold_px, hold_px + 0.1, hold_px - 0.1, hold_px, 100.0),
                    gap_bar: (gap_open, gap_open + 0.5, gap_open - 0.5, gap_open, 100.0)})

    t = simulate_day(day, p, INST)
    assert t["reason"] == "stop_gap"
    assert t["exit"] == pytest.approx(gap_open - 0.25)


def test_short_side_is_symmetric():
    up_day = make_day({9: (110.0, 110.0, 110.0, 110.0, 100.0)})
    t = simulate_day(up_day, Params(), INST)
    assert t["side"] == -1
    assert t["entry"] == pytest.approx(up_day.o[10] - 0.25)   # short : slippage defavorable
    assert t["pnl"] == pytest.approx(t["pts"] * 5.0 - 2 * INST.commission_side)


def test_costs_are_applied():
    p = Params(slippage_ticks=0.0)
    day = down_day({10: (90.0, 90.0, 90.0, 90.0, 100.0), 77: (90.0, 90.0, 90.0, 91.0, 100.0)})
    t = simulate_day(day, p, INST)
    assert t["pnl"] == pytest.approx(t["pts"] * 5.0 - 2 * 0.85)


def test_random_direction_keeps_timing():
    rng = np.random.default_rng(0)
    ref = simulate_day(down_day(), Params(), INST)
    seen = set()
    for _ in range(30):
        t = simulate_day(down_day(), Params(), INST, rng=rng)
        assert t["entry_time"] == ref["entry_time"]
        seen.add(t["side"])
    assert seen == {1, -1}


# --------------------------------------------------------------------------
# Chargement des donnees : heure d'ete / heure d'hiver (identique a l'ORB,
# meme fonction load_bars)
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
    path = _csv(tmp_path, [("2024-07-01 13:30", "MESU4", 100), ("2024-01-02 14:30", "MESH4", 100)])
    days, info = load_bars(path)
    assert info["days"] == 2 and info["dropped"] == 0
    assert all(d.idx[0].strftime("%H:%M") == "09:30" for d in days)


def test_wrong_utc_offset_day_is_dropped(tmp_path):
    path = _csv(tmp_path, [("2024-01-02 13:30", "MESH4", 100)])
    days, info = load_bars(path)
    assert info["days"] == 0 and info["dropped"] == 1


def test_front_contract_is_the_most_traded_one(tmp_path):
    path = _csv(tmp_path, [("2024-03-04 14:30", "OLD", 10), ("2024-03-04 14:30", "NEW", 500)])
    days, info = load_bars(path)
    assert info["days"] == 1
    assert len(days[0].c) == N


# --------------------------------------------------------------------------
# Filtre de regime : tendance de fond calculee sur les clotures anterieures
# --------------------------------------------------------------------------
def _make_days(closes: list[float]) -> list[Day]:
    idx = pd.date_range("2024-03-04 09:30", periods=N, freq="5min", tz=TZ)
    out = []
    for i, close in enumerate(closes):
        date = pd.Timestamp("2024-01-01") + pd.Timedelta(days=i)
        out.append(Day(date, idx, [close] * N, [close] * N, [close] * N, [close] * N, [100.0] * N))
    return out


def test_compute_daily_trend_no_lookahead():
    """trend[i] ne doit dependre que des clotures 0..i-1 (jamais celle du jour i)."""
    closes = [100.0] * 25
    days = _make_days(closes)
    trend1 = compute_daily_trend(days, regime_days=20)

    days2 = _make_days(closes[:24] + [9999.0])  # change seulement la cloture du dernier jour
    trend2 = compute_daily_trend(days2, regime_days=20)

    for d in days[:-1]:
        assert trend1[d.date] == trend2[d.date]


def test_compute_daily_trend_unknown_before_window():
    closes = [100.0] * 10
    days = _make_days(closes)
    trend = compute_daily_trend(days, regime_days=20)
    assert all(v == 0 for v in trend.values())


def test_compute_daily_trend_up_and_down():
    # 20 jours plats a 100, un jour a 110 (indice 20) : le jour SUIVANT (21) doit voir cette
    # hausse dans sa cloture-de-reference (J-1) et sa moyenne mobile -> tendance haussiere.
    closes_up = [100.0] * 20 + [110.0, 110.0]
    days_up = _make_days(closes_up)
    trend_up = compute_daily_trend(days_up, regime_days=20)
    assert trend_up[days_up[21].date] == 1

    closes_down = [100.0] * 20 + [90.0, 90.0]
    days_down = _make_days(closes_down)
    trend_down = compute_daily_trend(days_down, regime_days=20)
    assert trend_down[days_down[21].date] == -1


def test_regime_filter_blocks_counter_trend_signal():
    """Signal long (prix trop bas) mais tendance de fond baissiere -> pas de trade."""
    day = down_day()  # chute -> signal long (d_sig = 1)
    p = Params(regime_filter=True)
    assert simulate_day(day, p, INST, trend=1) is not None    # tendance haussiere : signal garde
    assert simulate_day(day, p, INST, trend=-1) is None       # tendance baissiere : signal bloque
    assert simulate_day(day, p, INST, trend=0) is not None    # tendance inconnue : signal garde


def test_regime_filter_off_ignores_trend():
    day = down_day()
    p = Params(regime_filter=False)
    assert simulate_day(day, p, INST, trend=-1) is not None   # filtre desactive : trade quand meme
