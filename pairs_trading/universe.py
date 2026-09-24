"""
universe.py

Univers de tickers basé sur la vraie classification sectorielle du S&P 500
(GICS Sub-Industry, ~127 groupes, plus fin que les 11 secteurs GICS
génériques). "Semiconductors" ou "Asset Management & Custody Banks" sont
des groupes bien plus homogènes économiquement que "Information Technology"
ou "Financials" pris au sens large.

Source des constituants: dataset public GitHub, mis en cache localement
dans data/sp500_constituents.csv au premier lancement (pas besoin de
retélécharger à chaque run, et ça marche même sans connexion ensuite).

ATTENTION TESTS MULTIPLES: plus tu élargis l'univers, plus tu testes de
paires, plus le risque de faux positifs augmente mécaniquement à p<0.05.
run_screening.py applique une correction (Benjamini-Hochberg) pour ça,
mais ça vaut aussi le coup de garder max_group_size raisonnable ici pour
éviter l'explosion combinatoire dans les gros groupes (16 tickers dans un
groupe = 120 paires rien que pour ce groupe).
"""

from itertools import combinations
from pathlib import Path

import pandas as pd

CACHE_DIR = Path(__file__).parent / "data"
CACHE_DIR.mkdir(exist_ok=True)
SP500_CACHE = CACHE_DIR / "sp500_constituents.csv"
SP500_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"

# Paires explicites: relations structurelles connues, pas de la pure
# corrélation statistique. (categorie, ticker_a, ticker_b)
EXPLICIT_PAIRS = [
    ("dual_class", "GOOGL", "GOOG"),        # Alphabet Classe A / Classe C
    ("etf_vs_holding", "XLE", "XOM"),       # Energy Select Sector SPDR / ExxonMobil
    ("etf_vs_holding", "XLF", "JPM"),       # Financial Select Sector SPDR / JPMorgan
    ("etf_vs_holding", "XLK", "AAPL"),      # Technology Select Sector SPDR / Apple
    ("etf_vs_holding", "XLV", "UNH"),       # Health Care Select Sector SPDR / UnitedHealth
    ("etf_vs_holding", "XLY", "AMZN"),      # Consumer Discretionary SPDR / Amazon
]


def _load_constituents(force_refresh: bool = False) -> pd.DataFrame:
    if SP500_CACHE.exists() and not force_refresh:
        return pd.read_csv(SP500_CACHE)

    df = pd.read_csv(SP500_URL)
    df.to_csv(SP500_CACHE, index=False)
    return df


def build_sectors(
    min_group_size: int = 2,
    max_group_size: int = 12,
    max_groups: int | None = None,
) -> dict[str, list[str]]:
    """
    Construit le dict {sous-secteur: [tickers]} à partir de la classification
    GICS Sub-Industry réelle du S&P 500.

    min_group_size: ignore les groupes trop petits pour former une paire
    max_group_size: PLAFONNE le nombre de tickers gardés par groupe (les
        premiers dans l'ordre du fichier), pour éviter qu'un groupe de 16
        génère 120 paires à lui seul. Avec max_group_size=12, un groupe
        plein donne C(12,2)=66 paires, déjà beaucoup pour un seul secteur.
    max_groups: limite le nombre de groupes utilisés au total, pour
        contrôler la taille globale de l'univers (et le temps de
        téléchargement). None = tous les groupes.
    """
    df = _load_constituents()
    counts = df["GICS Sub-Industry"].value_counts()
    eligible = counts[counts >= min_group_size].index.tolist()

    if max_groups is not None:
        eligible = eligible[:max_groups]

    sectors = {}
    for sub_industry in eligible:
        tickers = df.loc[df["GICS Sub-Industry"] == sub_industry, "Symbol"].tolist()
        # nettoyage: IBKR utilise des points pas des tirets pour les classes d'actions (BRK.B)
        tickers = [t.replace(".", " ") if "." in t else t for t in tickers]
        key = sub_industry.lower().replace(" ", "_").replace("&", "and").replace(",", "")
        sectors[key] = tickers[:max_group_size]

    return sectors


def all_tickers(sectors: dict[str, list[str]]) -> list[str]:
    seen = []
    for tickers in sectors.values():
        for t in tickers:
            if t not in seen:
                seen.append(t)
    for _, a, b in EXPLICIT_PAIRS:
        for t in (a, b):
            if t not in seen:
                seen.append(t)
    return seen


def candidate_pairs(sectors: dict[str, list[str]], sector: str) -> list[tuple[str, str]]:
    return list(combinations(sectors[sector], 2))


def all_candidate_pairs(sectors: dict[str, list[str]]) -> list[tuple[str, str, str]]:
    out = []
    for sector in sectors:
        for a, b in candidate_pairs(sectors, sector):
            out.append((sector, a, b))
    out.extend(EXPLICIT_PAIRS)
    return out


def summarize(sectors: dict[str, list[str]]) -> None:
    """Affiche la taille de l'univers avant de lancer quoi que ce soit,
    pour décider si c'est raisonnable ou s'il faut réduire max_group_size/max_groups."""
    n_tickers = len(all_tickers(sectors))
    n_pairs = len(all_candidate_pairs(sectors))
    est_minutes = n_tickers * 10 / 60  # pacing IBKR: ~1 requête/10s en continu
    print(f"Groupes: {len(sectors)}")
    print(f"Tickers: {n_tickers}")
    print(f"Paires à tester: {n_pairs}")
    print(f"Temps de téléchargement estimé (premier run): ~{est_minutes:.0f} min")


if __name__ == "__main__":
    # petit aperçu de la taille selon les réglages, sans rien télécharger
    for max_grp, max_size in [(None, 12), (30, 8), (15, 6)]:
        print(f"\n--- max_groups={max_grp}, max_group_size={max_size} ---")
        s = build_sectors(max_group_size=max_size, max_groups=max_grp)
        summarize(s)
