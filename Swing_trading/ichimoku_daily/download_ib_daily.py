"""
Telecharge l'historique en barres JOURNALIERES d'une action/ETF via l'API de
TWS pour ichimoku_backtest.py.

Contrairement aux telechargements 5 min des strategies intraday, une barre
journaliere par jour de bourse suffit -- pas de fenetrage necessaire, IB
renvoie plusieurs annees d'un coup avec `durationStr="Y"`.

Prerequis
---------
- TWS ouvert et connecte (compte paper ou live), API activee (port 7497 paper).
- pip install ib_async pandas

Usage
-----
    python download_ib_daily.py --symbol SPY --years 8
    python download_ib_daily.py --symbol SPY --years 8 --out-dir data_spy
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from ib_async import IB, Stock, util


def fetch_symbol(ib: IB, symbol: str, exchange: str, currency: str, years: int) -> pd.DataFrame:
    con = Stock(symbol, exchange, currency)
    ib.qualifyContracts(con)
    bars = ib.reqHistoricalData(con, endDateTime="", durationStr=f"{years} Y",
                                barSizeSetting="1 day", whatToShow="TRADES",
                                useRTH=True, formatDate=2)
    if not bars:
        return pd.DataFrame()
    df = util.df(bars)
    return df.rename(columns={"date": "datetime"})[["datetime", "open", "high", "low", "close", "volume"]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True, help="ex: SPY, QQQ, AAPL")
    ap.add_argument("--exchange", default="SMART")
    ap.add_argument("--currency", default="USD")
    ap.add_argument("--years", type=int, default=8)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7497)
    ap.add_argument("--client-id", type=int, default=118)
    ap.add_argument("--out-dir", default="data")
    a = ap.parse_args()

    out_dir = Path(a.out_dir)
    out_dir.mkdir(exist_ok=True)
    target = out_dir / f"{a.symbol}_daily_all.csv"
    if target.exists():
        print(f"{target.name} deja present, supprime-le pour re-telecharger.")
        return

    ib = IB()
    ib.connect(a.host, a.port, clientId=a.client_id)
    try:
        print(f"Telechargement {a.symbol} ({a.years} ans, barres journalieres) ...")
        df = fetch_symbol(ib, a.symbol, a.exchange, a.currency, a.years)
    finally:
        ib.disconnect()

    if df.empty:
        print("Aucune donnee recuperee : verifie l'abonnement de donnees et les messages d'erreur de TWS.")
        return

    df["datetime"] = pd.to_datetime(df["datetime"]).dt.strftime("%Y-%m-%d") + " 00:00:00+0000"
    df.to_csv(target, index=False)
    print(f"\n{len(df)} barres au total -> {target}")


if __name__ == "__main__":
    main()
