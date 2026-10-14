"""
Telecharge, pour chaque ETF de l'univers "jumeaux", 10 ans de barres
journalieres via l'API TWS, en deux versions :
- TRADES        : prix bruts (servent a convertir le slippage en ticks et la
                  commission par action en $ -- les couts dependent du prix
                  reellement paye, pas du prix ajuste).
- ADJUSTED_LAST : prix ajustes des dividendes (servent a mesurer l'ecart
                  entre deux ETF et le P&L en rendement total : deux ETF sur
                  le meme indice detachent leurs dividendes a des dates
                  differentes, ce qui creerait sinon de faux ecarts).

La barre du jour en cours (seance non terminee) est exclue.

Prerequis : TWS ouvert, API activee (port 7497 paper), pip install ib_async pandas

Usage :
    python download_ib_twins.py            # tous les tickers manquants
    python download_ib_twins.py --symbols SPY IVV
"""
from __future__ import annotations

import argparse
import time
from datetime import date
from pathlib import Path

import pandas as pd
from ib_async import IB, Stock, util

from twin_universe import all_tickers


def fetch(ib: IB, symbol: str, what: str, years: int) -> pd.DataFrame:
    con = Stock(symbol, "SMART", "USD")
    ib.qualifyContracts(con)
    bars = ib.reqHistoricalData(con, endDateTime="", durationStr=f"{years} Y",
                                barSizeSetting="1 day", whatToShow=what,
                                useRTH=True, formatDate=2)
    if not bars:
        return pd.DataFrame()
    df = util.df(bars).rename(columns={"date": "datetime"})
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df[df["datetime"].dt.date < date.today()]
    df["datetime"] = df["datetime"].dt.strftime("%Y-%m-%d") + " 00:00:00+0000"
    return df[["datetime", "open", "high", "low", "close", "volume"]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--port", type=int, default=7497)
    ap.add_argument("--client-id", type=int, default=132)
    a = ap.parse_args()

    out = Path("data")
    out.mkdir(exist_ok=True)
    symbols = a.symbols or all_tickers()

    ib = IB()
    ib.connect("127.0.0.1", a.port, clientId=a.client_id)
    try:
        for sym in symbols:
            for what, suffix in (("TRADES", "raw"), ("ADJUSTED_LAST", "adj")):
                target = out / f"{sym}_{suffix}.csv"
                if target.exists():
                    continue
                df = fetch(ib, sym, what, a.years)
                if df.empty:
                    print(f"{sym} {what} : aucune donnee")
                    continue
                df.to_csv(target, index=False)
                print(f"{sym} {what} : {len(df)} barres ({df['datetime'].iloc[0][:10]} -> {df['datetime'].iloc[-1][:10]})")
                time.sleep(1)
    finally:
        ib.disconnect()


if __name__ == "__main__":
    main()
