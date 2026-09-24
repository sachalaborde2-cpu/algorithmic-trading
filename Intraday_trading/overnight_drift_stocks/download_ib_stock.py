"""
Telecharge l'historique en barres de 5 minutes d'une action/ETF via l'API de TWS
et ecrit un CSV pour vwap_backtest.py.

Pourquoi un script separe de download_ib.py (futures) :
--------------------------------------------------------
Une action/ETF n'a pas de contrat trimestriel qui expire (pas de roll a gerer,
pas de colonne "contract"), donc le telechargement est plus simple : on
remonte semaine par semaine depuis aujourd'hui jusqu'a `--years` ans en arriere.

Prerequis
---------
- TWS ouvert et connecte (compte paper ou live).
- API activee : Fichier > Configuration globale > API > Parametres > "Activer les
  clients ActiveX et Socket". Port par defaut : 7497 (paper), 7496 (live).
- pip install ib_async pandas

IB limite les requetes d'historique (environ 60 par 10 minutes) : le script attend
entre chaque appel. Compte ~1-2 minutes par annee d'historique (heures de marche
regulieres uniquement, ~78 barres/jour).

Usage
-----
    python download_ib_stock.py --symbol SPY --years 3
    python download_ib_stock.py --symbol QQQ --years 3 --out-dir data_qqq
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from ib_async import IB, Stock, util


def fetch_symbol(ib: IB, symbol: str, exchange: str, currency: str, years: int,
                 pause: float, duration: str = "1 M") -> pd.DataFrame:
    con = Stock(symbol, exchange, currency)
    ib.qualifyContracts(con)
    cutoff = datetime.now(timezone.utc) - timedelta(days=365 * years + 14)

    frames, end = [], ""
    while True:
        bars = ib.reqHistoricalData(con, endDateTime=end, durationStr=duration,
                                    barSizeSetting="5 mins", whatToShow="TRADES",
                                    useRTH=True, formatDate=2)
        time.sleep(pause)
        if not bars:
            break
        df = util.df(bars)
        frames.append(df)
        oldest = pd.Timestamp(df["date"].min())
        if oldest.tz is None:
            oldest = oldest.tz_localize("UTC")
        print(f"  {symbol} : {oldest.date()} -> {pd.Timestamp(df['date'].max()).date()} "
              f"({len(df)} barres)")
        if oldest.to_pydatetime() <= cutoff:
            break
        end = oldest.to_pydatetime()

    out = pd.concat(frames).drop_duplicates("date").sort_values("date")
    return out.rename(columns={"date": "datetime"})[["datetime", "open", "high", "low", "close", "volume"]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True, help="ex: SPY, QQQ, AAPL")
    ap.add_argument("--exchange", default="SMART")
    ap.add_argument("--currency", default="USD")
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7497)
    ap.add_argument("--client-id", type=int, default=18)
    ap.add_argument("--pause", type=float, default=10.5, help="secondes entre deux requetes")
    ap.add_argument("--duration", default="1 M", help="taille de fenetre par requete IB (ex: '1 W', '1 M')")
    ap.add_argument("--out-dir", default="data")
    a = ap.parse_args()

    out_dir = Path(a.out_dir)
    out_dir.mkdir(exist_ok=True)
    target = out_dir / f"{a.symbol}_5min_all.csv"
    if target.exists():
        print(f"{target.name} deja present, supprime-le pour re-telecharger.")
        return

    ib = IB()
    ib.connect(a.host, a.port, clientId=a.client_id)
    try:
        print(f"Telechargement {a.symbol} ({a.years} ans) ...")
        df = fetch_symbol(ib, a.symbol, a.exchange, a.currency, a.years, a.pause, a.duration)
    finally:
        ib.disconnect()

    if df.empty:
        print("Aucune donnee recuperee : verifie l'abonnement de donnees et les messages d'erreur de TWS.")
        return

    df["datetime"] = pd.to_datetime(df["datetime"], utc=True).dt.strftime("%Y-%m-%d %H:%M:%S%z")
    df.to_csv(target, index=False)
    print(f"\n{len(df)} barres au total -> {target}")


if __name__ == "__main__":
    main()
