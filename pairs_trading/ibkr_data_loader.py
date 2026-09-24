"""
ibkr_data_loader.py

Connexion à IBKR (via ib_async, le fork maintenu de ib_insync) et récupération
de données historiques, avec cache local pour ne pas re-télécharger à chaque run
et rester sous les limites de pacing d'IBKR:
  - pas plus de 60 requêtes historiques par tranche de 10 minutes
  - pas de requête identique dans un délai de 15 secondes
  - pas plus de 6 requêtes sur le même contrat/exchange en 2 secondes

Prérequis: IBKR Desktop (ou TWS) doit être ouvert, connecté à ton compte
paper trading, avec l'API activée (voir les étapes données en chat).
"""

import time
from pathlib import Path

import pandas as pd
from ib_async import IB, Stock, util

CACHE_DIR = Path(__file__).parent / "data" / "raw"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Port par défaut: 7497 = TWS paper trading, 7496 = TWS réel,
# 4002 = IB Gateway paper, 4001 = IB Gateway réel.
PAPER_PORT = 7497


def connect(port: int = PAPER_PORT, client_id: int = 7) -> IB:
    """
    Connexion à IBKR Desktop / TWS en local.
    client_id doit être unique si tu fais tourner plusieurs scripts en parallèle
    (chaque connexion active a besoin de son propre id, sinon IBKR la refuse).
    """
    ib = IB()
    ib.connect("127.0.0.1", port, clientId=client_id)
    return ib


def _cache_path(symbol: str, duration: str, bar_size: str) -> Path:
    safe_duration = duration.replace(" ", "")
    safe_bar = bar_size.replace(" ", "")
    return CACHE_DIR / f"{symbol}_{safe_duration}_{safe_bar}.parquet"


def get_bars(
    ib: IB,
    symbol: str,
    exchange: str = "SMART",
    currency: str = "USD",
    duration: str = "3 Y",
    bar_size: str = "1 day",
    what_to_show: str = "ADJUSTED_LAST",
    use_rth: bool = True,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Récupère les prix d'un ticker, depuis le cache local si disponible,
    sinon via l'API IBKR (et met à jour le cache).

    what_to_show='ADJUSTED_LAST' -> ajusté pour splits ET dividendes.
    C'est important pour la cointégration: un split non ajusté crée un faux
    saut dans le spread qui n'a rien à voir avec un signal de trading.
    """
    cache_file = _cache_path(symbol, duration, bar_size)

    if cache_file.exists() and not force_refresh:
        return pd.read_parquet(cache_file)

    contract = Stock(symbol, exchange, currency)
    ib.qualifyContracts(contract)

    bars = ib.reqHistoricalData(
        contract,
        endDateTime="",
        durationStr=duration,
        barSizeSetting=bar_size,
        whatToShow=what_to_show,
        useRTH=use_rth,
    )

    if not bars:
        raise ValueError(f"Aucune donnée retournée par IBKR pour {symbol}")

    df = util.df(bars)[["date", "open", "high", "low", "close", "volume"]]
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")

    df.to_parquet(cache_file)
    return df


def get_universe_bars(
    ib: IB,
    symbols: list[str],
    delay_between_requests: float = 11.0,
    **kwargs,
) -> dict[str, pd.DataFrame]:
    """
    Récupère les données pour une liste de tickers, en respectant le pacing.

    IBKR limite les requêtes historiques à 60 par tranche de 10 minutes
    (limite globale, pas juste pour des requêtes identiques). Avec
    delay_between_requests=11.0, on reste à ~54 requêtes/10min: sûr avec
    une marge raisonnable pour les retries en cas d'échec ponctuel.
    Sur un gros univers (300-500 tickers), ça representé 45-90 minutes
    au premier run, mais c'est un coût ponctuel grâce au cache local.
    """
    result = {}
    for i, symbol in enumerate(symbols):
        try:
            result[symbol] = get_bars(ib, symbol, **kwargs)
            print(f"  [{i+1}/{len(symbols)}] {symbol}: {len(result[symbol])} barres OK")
        except Exception as e:
            print(f"  [{i+1}/{len(symbols)}] {symbol}: ÉCHEC ({e})")
        time.sleep(delay_between_requests)
    return result
