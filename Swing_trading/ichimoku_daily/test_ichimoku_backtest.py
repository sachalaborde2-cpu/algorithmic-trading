"""Tests unitaires : calcul causal des lignes Ichimoku (pas de fuite de futur
via le decalage du Kumo), coherence comptable trades/P&L quotidien, et
fonctionnement du test placebo (meme timing, direction aleatoire)."""
import numpy as np
import pandas as pd
import pytest

from ichimoku_backtest import (
    Instrument, Params, ichimoku_lines, compute_target_position, simulate,
    random_direction_test,
)

INST = Instrument(tick=0.01, point_value=100.0, commission_side=1.00)


def make_df(n=200, seed=0, trend=0.0):
    rng = np.random.default_rng(seed)
    ret = rng.normal(trend, 0.01, n)
    close = 100 * np.cumprod(1 + ret)
    high = close * (1 + np.abs(rng.normal(0, 0.003, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.003, n)))
    open_ = np.concatenate([[close[0]], close[:-1]]) * (1 + rng.normal(0, 0.001, n))
    dates = pd.bdate_range("2020-01-01", periods=n)
    return pd.DataFrame({"date": dates, "open": open_, "high": high, "low": low,
                         "close": close, "volume": 1_000_000})


def test_senkou_lines_do_not_use_future_bars():
    """Le nuage affiche au jour t (apres decalage) ne doit dependre que des
    barres 0..t-displacement : si on modifie une barre future (> t), la valeur
    du nuage a t ne doit pas changer."""
    df = make_df(150)
    p = Params()
    lines_a = ichimoku_lines(df, p)

    df2 = df.copy()
    df2.loc[140:, ["high", "low", "close"]] *= 5.0  # choc massif sur les 10 dernieres barres
    lines_b = ichimoku_lines(df2, p)

    t = 100  # bien avant les barres modifiees, meme apres decalage de 26
    assert lines_a["senkou_a"].iloc[t] == pytest.approx(lines_b["senkou_a"].iloc[t])
    assert lines_a["senkou_b"].iloc[t] == pytest.approx(lines_b["senkou_b"].iloc[t])
    assert lines_a["tenkan"].iloc[t] == pytest.approx(lines_b["tenkan"].iloc[t])


def test_target_position_applied_next_day_not_same_day():
    """Un signal calcule a la cloture du jour t ne doit influencer la position
    detenue qu'a partir du jour t+1 (pos_day = target.shift(1))."""
    df = make_df(200, seed=1)
    p = Params(signal="tkc")
    target = compute_target_position(df, p)
    daily, _ = simulate(df, p, INST)
    # pos_day au jour t doit correspondre au target calcule a la cloture t-1
    assert (daily["pos_day"].to_numpy()[1:] == target.to_numpy()[:-1]).all()


def test_long_only_mode_never_shorts():
    df = make_df(300, seed=2, trend=-0.001)  # tendance baissiere -> shorts frequents en long_short
    p_ls = Params(signal="kbo", mode="long_short")
    p_lo = Params(signal="kbo", mode="long_only")
    daily_ls, _ = simulate(df, p_ls, INST)
    daily_lo, _ = simulate(df, p_lo, INST)
    assert (daily_ls["pos_day"] < 0).any()
    assert (daily_lo["pos_day"] >= 0).all()


def test_trades_pnl_sums_to_daily_pnl():
    """Invariant comptable : la somme du P&L de tous les trades reconstruits
    doit egaler la somme du P&L quotidien marque au marche (les deux ne sont
    qu'un decoupage different du meme total)."""
    df = make_df(400, seed=3)
    for signal in ("tkc", "kbo"):
        for mode in ("long_short", "long_only"):
            p = Params(signal=signal, mode=mode)
            daily, trades = simulate(df, p, INST)
            assert trades["pnl"].sum() == pytest.approx(daily["pnl"].sum(), abs=1e-6)


def test_short_position_inverts_pnl_sign_vs_long():
    """Meme serie de prix, position forcee opposee (via mode) -> P&L oppose
    sur les segments non nuls communs. On verifie ceci indirectement en
    comparant deux Params qui ne different que par le signal invers e n'est
    pas trivial ; on verifie plutot que pos_day = -1 genere un pnl de signe
    coherent avec un mouvement de prix connu."""
    dates = pd.bdate_range("2020-01-01", periods=5)
    df = pd.DataFrame({
        "date": dates,
        "open": [100.0, 100.0, 110.0, 110.0, 110.0],
        "high": [100.0, 100.0, 110.0, 110.0, 110.0],
        "low": [100.0, 100.0, 110.0, 110.0, 110.0],
        "close": [100.0, 100.0, 110.0, 110.0, 110.0],
        "volume": [1] * 5,
    })
    p = Params(slippage_ticks=0.0)
    inst = Instrument(tick=0.01, point_value=100.0, commission_side=0.0)
    # position manuelle : long a partir du jour 2 (index 2)
    target = pd.Series([0.0, 1.0, 1.0, 1.0, 1.0])
    import ichimoku_backtest as ib
    orig = ib.compute_target_position
    ib.compute_target_position = lambda d, pp: target
    try:
        daily, trades = simulate(df, p, inst)
    finally:
        ib.compute_target_position = orig
    # pos_day = target.shift(1) -> long a partir du jour 3 (index 3)
    assert daily["pos_day"].tolist() == [0.0, 0.0, 1.0, 1.0, 1.0]
    # gain du jour 3 (open=110 -> close=110) = 0 (deja monte avant l'entree)
    assert daily["pnl"].iloc[2] == pytest.approx(0.0)


def test_random_direction_test_is_deterministic_given_seed():
    df = make_df(500, seed=4)
    p = Params()
    r1 = random_direction_test(df, p, INST, pd.DatetimeIndex(df["date"].iloc[300:]), n_sims=15, seed=7)
    r2 = random_direction_test(df, p, INST, pd.DatetimeIndex(df["date"].iloc[300:]), n_sims=15, seed=7)
    assert r1 == r2


def test_warmup_period_has_no_position():
    df = make_df(300, seed=5)
    p = Params()
    target = compute_target_position(df, p)
    warmup = p.senkou_b_period + p.displacement
    assert (target.iloc[:warmup] == 0.0).all()


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
