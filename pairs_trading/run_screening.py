"""
run_screening.py

Pipeline complet à lancer UNE FOIS IBKR Desktop ouvert et connecté à ton
compte paper trading, API activée (voir étapes données en chat).

Méthodologie anti-look-ahead:
1. On coupe l'historique en une fenêtre TRAIN (ex: 70%) et TEST (30%).
2. La cointégration ET le hedge ratio sont estimés UNIQUEMENT sur TRAIN.
3. Le backtest tourne sur TEST, avec le hedge ratio figé issu de TRAIN.

Si tu sélectionnes ta paire ET que tu la backtestes sur la même période,
tu ne mesures rien: tu as juste vérifié que la paire fonctionne sur les
données qui ont servi à la choisir. Le vrai test, c'est la performance
hors-échantillon (TEST).
"""

import time

import pandas as pd
from statsmodels.stats.multitest import multipletests

from ibkr_data_loader import connect, get_universe_bars
from universe import build_sectors, all_tickers, all_candidate_pairs
from cointegration import engle_granger_test, half_life
from backtest import backtest_pair

TRAIN_FRACTION = 0.7
FDR_ALPHA = 0.05  # taux de faux positifs toléré APRÈS correction (Benjamini-Hochberg)

# Choisis l'échelle ici. Estimations de temps de téléchargement (premier run,
# pacing IBKR ~1 req/10s): small ~17 min, medium ~38 min, full ~78 min.
UNIVERSE_PRESETS = {
    "small": dict(max_group_size=6, max_groups=15),
    "medium": dict(max_group_size=8, max_groups=30),
    "full": dict(max_group_size=12, max_groups=None),
}
UNIVERSE_SIZE = "small"  # <- change ici: "small", "medium" ou "full"


def split_train_test(price: pd.Series, train_fraction: float = TRAIN_FRACTION):
    cutoff = int(len(price) * train_fraction)
    return price.iloc[:cutoff], price.iloc[cutoff:]


def main():
    sectors = build_sectors(**UNIVERSE_PRESETS[UNIVERSE_SIZE])
    tickers = all_tickers(sectors)
    pairs = all_candidate_pairs(sectors)
    print(f"Univers '{UNIVERSE_SIZE}': {len(tickers)} tickers, {len(pairs)} paires candidates")

    print("\nConnexion à IBKR (TWS, paper trading)...")
    ib = connect()

    print(f"Téléchargement (avec cache, ~1 requête/10s pour respecter le pacing IBKR)...")
    t0 = time.time()
    bars = get_universe_bars(ib, tickers, duration="3 Y", bar_size="1 day", delay_between_requests=11.0)
    print(f"Téléchargement terminé en {(time.time()-t0)/60:.1f} min")

    ib.disconnect()

    closes = {sym: df["close"] for sym, df in bars.items()}

    # --- Phase 1: cointégration sur TRAIN pour toutes les paires (rapide) ---
    print(f"\nTest de cointégration sur {len(pairs)} paires (fenêtre train uniquement)...")
    raw_results = []
    for i, (sector, sym_a, sym_b) in enumerate(pairs):
        if i > 0 and i % 200 == 0:
            print(f"  ... {i}/{len(pairs)} paires testées")

        if sym_a not in closes or sym_b not in closes:
            continue

        df = pd.concat([closes[sym_a], closes[sym_b]], axis=1, keys=[sym_a, sym_b], sort=False).dropna()
        if len(df) < 250:
            continue

        train_a, test_a = split_train_test(df[sym_a])
        train_b, test_b = split_train_test(df[sym_b])

        try:
            eg = engle_granger_test(train_a, train_b)
            hl = half_life(eg["spread"])
        except Exception:
            continue

        raw_results.append({
            "sector": sector,
            "pair": f"{sym_a}/{sym_b}",
            "sym_a": sym_a,
            "sym_b": sym_b,
            "p_value_train": eg["p_value"],
            "half_life_train": hl,
            "hedge_ratio": eg["hedge_ratio"],
            "test_a": test_a,
            "test_b": test_b,
        })

    # --- Phase 2: correction pour tests multiples (Benjamini-Hochberg) ---
    # Sans ça, tester 1000+ paires à p<0.05 fait mécaniquement remonter ~50
    # "cointégrations" qui n'existent que par hasard statistique.
    pvals = [r["p_value_train"] for r in raw_results]
    if pvals:
        reject, pvals_corrected, _, _ = multipletests(pvals, alpha=FDR_ALPHA, method="fdr_bh")
    else:
        reject, pvals_corrected = [], []

    results = []
    for r, rej, p_corr in zip(raw_results, reject, pvals_corrected):
        hl = r["half_life_train"]
        tradable = bool(rej) and 1 <= hl <= 90

        row = {
            "sector": r["sector"],
            "pair": r["pair"],
            "p_value_train": round(r["p_value_train"], 4),
            "p_value_adj_bh": round(p_corr, 4),
            "half_life_train": round(hl, 1) if hl != float("inf") else None,
            "tradable": tradable,
            "sharpe_test": None,
            "cagr_test": None,
            "max_dd_test": None,
            "n_trades_test": None,
        }

        if tradable:
            bt = backtest_pair(r["test_a"], r["test_b"], beta=r["hedge_ratio"])
            row.update({
                "sharpe_test": round(bt["sharpe"], 2),
                "cagr_test": round(bt["cagr"], 3),
                "max_dd_test": round(bt["max_drawdown"], 3),
                "n_trades_test": bt["n_trades"],
            })

        results.append(row)

    results_df = pd.DataFrame(results).sort_values(
        "sharpe_test", ascending=False, na_position="last"
    )

    n_tradable = int(results_df["tradable"].sum())
    print("\n" + "=" * 70)
    print(f"RÉSULTATS — {n_tradable}/{len(results_df)} paires cointégrées après correction BH (FDR={FDR_ALPHA})")
    print("=" * 70)
    print(results_df.head(30).to_string(index=False))
    if n_tradable == 0:
        print("\nAucune paire ne survit à la correction pour tests multiples. Regarde")
        print("p_value_adj_bh dans le CSV: les moins mauvaises te disent où chercher")
        print("si tu veux élargir encore, ou passer à UNIVERSE_SIZE='full'.")

    results_df.to_csv("screening_results.csv", index=False)
    print(f"\n{len(results_df)} résultats complets sauvegardés dans screening_results.csv")


if __name__ == "__main__":
    main()
