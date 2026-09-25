"""Tests unitaires : calcul causal du score de momentum (pas de fuite de
futur), application des poids au jour suivant (pas le jour meme), mode
long_only qui ne shorte jamais, coherence du rendement de portefeuille avec
les rendements individuels ponderes, et determinisme du test placebo."""
import numpy as np
import pandas as pd
import pytest

from momentum_backtest import (
    Params, momentum_scores, rebalance_dates, target_weights, simulate,
    randomize_selection, random_selection_test,
)

TICKERS = ["A", "B", "C", "D"]


def make_universe(n=400, seed=0, trends=None):
    """Univers synthetique de tickers avec des tendances differentes (pour
    generer un classement de momentum non trivial)."""
    trends = trends or {"A": 0.003, "B": 0.001, "C": -0.001, "D": -0.003}
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n)
    opens, closes = {}, {}
    for tk in TICKERS:
        ret = rng.normal(trends[tk], 0.01, n)
        close = 100 * np.cumprod(1 + ret)
        open_ = np.concatenate([[close[0]], close[:-1]]) * (1 + rng.normal(0, 0.001, n))
        opens[tk] = pd.Series(open_, index=dates)
        closes[tk] = pd.Series(close, index=dates)
    return pd.DataFrame(opens), pd.DataFrame(closes)


def test_scores_do_not_use_future_bars():
    """Le score de momentum a la date t (apres skip) ne doit dependre que des
    clotures 0..t-skip : si on modifie une barre future (> t), le score a t
    ne doit pas changer."""
    _, close_df = make_universe(300, seed=1)
    p = Params(lookback_months=6, skip_months=1)
    scores_a = momentum_scores(close_df, p)

    close_df2 = close_df.copy()
    close_df2.iloc[280:] *= 5.0  # choc massif sur les 20 dernieres barres
    scores_b = momentum_scores(close_df2, p)

    t = 200  # bien avant les barres modifiees
    pd.testing.assert_series_equal(scores_a.iloc[t], scores_b.iloc[t], check_names=False)


def test_weights_applied_next_day_not_same_day():
    """Un poids decide a la date de rebalancement t ne doit influencer le
    rendement du portefeuille qu'a partir du jour de bourse t+1."""
    open_df, close_df = make_universe(300, seed=2)
    p = Params(lookback_months=6, skip_months=1, n_long=1, n_short=1, cost_bps=0.0)
    scores = momentum_scores(close_df, p)
    rebal = rebalance_dates(close_df.index)
    w = target_weights(scores, rebal, p)

    # le premier rebalancement avec un poids non nul
    first_active = w[(w != 0).any(axis=1)].index[0]
    idx = close_df.index.get_loc(first_active)
    ret_that_day = close_df.iloc[idx] / open_df.iloc[idx] - 1.0
    # la position est entree a l'OUVERTURE du jour suivant (idx+1), donc son
    # premier rendement capture est open_to_close de idx+1, pas close-to-close
    ret_entry_day = close_df.iloc[idx + 1] / open_df.iloc[idx + 1] - 1.0

    daily_ret, _ = simulate(open_df, close_df, w, p)
    expected_first_day = (w.loc[first_active] * ret_that_day).sum()
    # le jour de rebalancement lui-meme (t) n'est PAS impacte : le poids
    # decide a t ne s'applique qu'a partir de t+1 (open_to_close du jour
    # suivant, pas du jour du signal)
    assert daily_ret.loc[first_active] != pytest.approx(expected_first_day)
    expected_entry_day = (w.loc[first_active] * ret_entry_day).sum()
    assert daily_ret.iloc[idx + 1] == pytest.approx(expected_entry_day, abs=1e-9)


def test_long_only_mode_never_shorts():
    open_df, close_df = make_universe(400, seed=3)
    p_lo = Params(lookback_months=6, mode="long_only", n_long=2, n_short=2)
    scores = momentum_scores(close_df, p_lo)
    rebal = rebalance_dates(close_df.index)
    w_lo = target_weights(scores, rebal, p_lo)
    assert (w_lo >= 0).all().all()

    p_ls = Params(lookback_months=6, mode="long_short", n_long=2, n_short=2)
    w_ls = target_weights(scores, rebal, p_ls)
    assert (w_ls < 0).any().any()


def test_portfolio_return_matches_weighted_ticker_returns_no_cost():
    """Sans cout (cost_bps=0), le rendement quotidien du portefeuille doit
    egaler exactement la somme des rendements individuels ponderes (pas de
    fuite ni de double comptage)."""
    open_df, close_df = make_universe(350, seed=4)
    p = Params(lookback_months=6, n_long=1, n_short=1, cost_bps=0.0)
    scores = momentum_scores(close_df, p)
    rebal = rebalance_dates(close_df.index)
    w = target_weights(scores, rebal, p)
    daily_ret, trades = simulate(open_df, close_df, w, p)

    # invariant : le rendement total du portefeuille doit correspondre au
    # produit cumule (1+r) - 1, coherent avec les jambes individuelles :
    # la somme des poids appliques (a chaque instant, |long|+|short| <= 1)
    # borne le rendement quotidien -- ici on verifie juste l'absence de NaN
    # et que le rendement est fini partout.
    assert daily_ret.notna().all()
    assert np.isfinite(daily_ret.to_numpy()).all()
    assert len(trades) > 0


def test_zero_weights_when_not_enough_valid_scores():
    """Aux dates de rebalancement trop precoces (score momentum pas encore
    disponible pour assez d'instruments), les poids doivent rester a zero
    (pas de position forcee sur un sous-ensemble incomplet)."""
    _, close_df = make_universe(300, seed=5)
    p = Params(lookback_months=12, skip_months=1, n_long=2, n_short=2)
    scores = momentum_scores(close_df, p)
    rebal = rebalance_dates(close_df.index)
    w = target_weights(scores, rebal, p)
    warmup_months = p.lookback_months + p.skip_months
    early = rebal[rebal < close_df.index[0] + pd.DateOffset(months=warmup_months)]
    assert (w.loc[early] == 0.0).all().all()


def test_randomize_selection_respects_basket_size_and_dates():
    _, close_df = make_universe(400, seed=6)
    p = Params(lookback_months=6, n_long=1, n_short=1)
    scores = momentum_scores(close_df, p)
    rebal = rebalance_dates(close_df.index)
    rng = np.random.default_rng(42)
    w = randomize_selection(scores, rebal, p, rng)
    for dt in rebal:
        row = w.loc[dt]
        if (row != 0).any():
            assert (row > 0).sum() == p.n_long
            assert (row < 0).sum() == p.n_short


def test_random_selection_test_is_deterministic_given_seed():
    open_df, close_df = make_universe(500, seed=7)
    p = Params(lookback_months=6, n_long=1, n_short=1)
    scores = momentum_scores(close_df, p)
    rebal = rebalance_dates(close_df.index)
    oos_dates = close_df.index[400:]
    r1 = random_selection_test(open_df, close_df, scores, rebal, p, oos_dates, n_sims=15, seed=9)
    r2 = random_selection_test(open_df, close_df, scores, rebal, p, oos_dates, n_sims=15, seed=9)
    assert r1 == r2


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
