"""
cointegration.py

Sélection et validation statistique de paires pour du stat arb.

Méthodologie:
1. Régression OLS log(prix_A) ~ log(prix_B) pour obtenir le hedge ratio (beta)
2. Test ADF (Augmented Dickey-Fuller) sur les résidus de la régression
   -> si les résidus sont stationnaires, la paire est cointégrée (Engle-Granger)
3. Calcul de la half-life de retour à la moyenne du spread (utile pour
   dimensionner la fenêtre de lookback et vérifier que la vitesse de
   réversion est compatible avec ton horizon de trading)

Limite connue: Engle-Granger suppose une direction de régression (A~B),
ce qui peut donner des résultats différents de B~A. Pour un usage sérieux,
tester les deux sens ou passer à Johansen (statsmodels.tsa.vector_ar.vecm)
si tu générralises à plus de 2 actifs.
"""

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller, coint
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant


def hedge_ratio(price_a: pd.Series, price_b: pd.Series) -> float:
    """
    Régression OLS log(A) = alpha + beta * log(B) + epsilon
    Retourne beta, le ratio de couverture: pour 1 unité de A,
    on shorte/achète beta unités de B.
    """
    log_a = np.log(price_a)
    log_b = add_constant(np.log(price_b))
    model = OLS(log_a, log_b).fit()
    return model.params.iloc[1]


def compute_spread(price_a: pd.Series, price_b: pd.Series, beta: float) -> pd.Series:
    """Spread = log(A) - beta * log(B). C'est ce spread qu'on trade."""
    return np.log(price_a) - beta * np.log(price_b)


def adf_test(series: pd.Series) -> dict:
    """
    Test de stationnarité sur une série (typiquement le spread).
    H0: la série a une racine unitaire (non stationnaire, PAS de retour à la moyenne)
    On veut REJETER H0 -> p-value faible (< 0.05 en général)
    """
    result = adfuller(series.dropna(), autolag="AIC")
    return {
        "adf_stat": result[0],
        "p_value": result[1],
        "n_lags": result[2],
        "critical_values": result[4],
        "is_stationary_5pct": result[1] < 0.05,
    }


def engle_granger_test(price_a: pd.Series, price_b: pd.Series) -> dict:
    """
    Test de cointégration Engle-Granger complet.
    Utilise directement statsmodels.tsa.stattools.coint (plus robuste que
    de refaire l'ADF à la main sur les résidus, car coint() ajuste les
    valeurs critiques pour tenir compte de l'étape de régression préalable).
    """
    score, p_value, crit_values = coint(price_a, price_b)
    beta = hedge_ratio(price_a, price_b)
    spread = compute_spread(price_a, price_b, beta)
    return {
        "coint_score": score,
        "p_value": p_value,
        "critical_values": {"1%": crit_values[0], "5%": crit_values[1], "10%": crit_values[2]},
        "is_cointegrated_5pct": p_value < 0.05,
        "hedge_ratio": beta,
        "spread": spread,
    }


def half_life(spread: pd.Series) -> float:
    """
    Half-life de retour à la moyenne via un modèle AR(1) sur le spread:
        delta_spread(t) = lambda * spread(t-1) + epsilon
    Half-life = -ln(2) / lambda

    Interprétation: nombre de périodes (en unités de ta série, ex: jours)
    pour que la moitié d'un écart à la moyenne se résorbe. Une half-life
    de 5-20 jours est en général exploitable pour du swing trading;
    au-delà de 60-90 jours, le capital immobilisé pénalise le Sharpe.
    """
    spread_lag = spread.shift(1).dropna()
    spread_ret = spread.diff().dropna()
    spread_lag = spread_lag.loc[spread_ret.index]

    X = add_constant(spread_lag)
    model = OLS(spread_ret, X).fit()
    lam = model.params.iloc[1]

    if lam >= 0:
        # pas de retour à la moyenne détecté (lambda positif = série explosive)
        return np.inf
    return -np.log(2) / lam


def screen_pair(price_a: pd.Series, price_b: pd.Series, name_a: str = "A", name_b: str = "B") -> dict:
    """Résumé complet pour décider si une paire est tradable."""
    eg = engle_granger_test(price_a, price_b)
    hl = half_life(eg["spread"])
    verdict = eg["is_cointegrated_5pct"] and 1 <= hl <= 90

    return {
        "pair": f"{name_a}/{name_b}",
        "p_value": round(eg["p_value"], 4),
        "hedge_ratio": round(eg["hedge_ratio"], 4),
        "half_life_days": round(hl, 1) if np.isfinite(hl) else float("inf"),
        "tradable": verdict,
    }
