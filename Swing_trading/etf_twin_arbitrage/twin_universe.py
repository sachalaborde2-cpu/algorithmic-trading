"""
Univers pre-enregistre (avant tout resultat) des paires d'ETF "jumeaux".

Groupe A -- jumeaux STRICTS : les deux ETF repliquent exactement le meme
indice (ou le meme metal physique). Chacun est rappele vers la meme valeur
liquidative par son propre mecanisme de creation/rachat : c'est le test
direct de l'hypothese. Verdict principal = portefeuille equipondere des
paires du groupe A.

Groupe B -- quasi-jumeaux : indices differents mais quasi identiques
(meme univers, methodologie de ponderation/composition legerement
differente). Cartographie exploratoire, hors verdict : l'ecart y contient
une vraie difference de composition, pas seulement une erreur de prix.
"""

GROUP_A = [
    ("SPY", "IVV"),    # S&P 500
    ("SPY", "VOO"),    # S&P 500
    ("IVV", "VOO"),    # S&P 500
    ("SPY", "SPYM"),   # S&P 500 (SPYM = ex-SPLG)
    ("QQQ", "QQQM"),   # Nasdaq-100
    ("IWM", "VTWO"),   # Russell 2000
    ("MDY", "IJH"),    # S&P MidCap 400
    ("IJR", "SPSM"),   # S&P SmallCap 600
    ("GLD", "IAU"),    # or physique
    ("GLD", "GLDM"),   # or physique
    ("SLV", "SIVR"),   # argent physique
]

GROUP_B = [
    ("VTI", "ITOT"),   # marche US total (CRSP vs S&P Total Market)
    ("VTI", "SCHB"),   # marche US total (CRSP vs Dow Jones US Broad)
    ("AGG", "BND"),    # obligataire agrege US (Bloomberg Agg vs Agg Float Adjusted)
    ("IEFA", "VEA"),   # actions developpees hors US (MSCI EAFE IMI vs FTSE Developed ex-US)
    ("IEMG", "VWO"),   # emergents (MSCI EM IMI vs FTSE Emerging)
]


def all_tickers() -> list[str]:
    seen = []
    for a, b in GROUP_A + GROUP_B:
        for t in (a, b):
            if t not in seen:
                seen.append(t)
    return seen
