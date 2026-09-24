"""
Telecharge l'historique en barres de 5 minutes des futures MES / ES via l'API de TWS
et ecrit un CSV pour orb_backtest.py.

Prerequis
---------
- TWS ouvert et connecte (compte paper ou live).
- API activee : Fichier > Configuration globale > API > Parametres > "Activer les clients
  ActiveX et Socket". Port par defaut : 7497 (paper), 7496 (live).
- pip install ib_async pandas
- Abonnement de donnees CME cote IB. Sans lui, l'API renvoie souvent 0 barre.

Principe
--------
On telecharge chaque contrat trimestriel (H, M, U, Z) sur ~15 semaines avant son
expiration, 24h/24 (useRTH=False). Le filtre 09:30-16:00 heure de NY et le choix du
contrat le plus liquide de chaque jour sont faits dans orb_backtest.load_bars.

IB limite les requetes d'historique (environ 60 par 10 minutes) : le script attend
entre chaque appel, compte 30 a 40 minutes pour 3 ans. Les contrats deja telecharges
sont sautes si tu relances.

Usage
-----
    python download_ib.py --symbol MES --years 2
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from ib_async import IB, Future, util


def contract_months(years: int) -> list[str]:
    now = datetime.now(timezone.utc)
    return [f"{y}{m:02d}" for y in range(now.year - years, now.year + 2) for m in (3, 6, 9, 12)]


def fetch_contract(ib: IB, symbol: str, month: str, weeks: int, pause: float) -> pd.DataFrame | None:
    probe = Future(symbol=symbol, lastTradeDateOrContractMonth=month,
                   exchange="CME", currency="USD", includeExpired=True)
    details = ib.reqContractDetails(probe)
    details = [d for d in details if d.contract.tradingClass == symbol] or details
    if not details:
        print(f"  {symbol} {month} : contrat introuvable")
        return None
    con = details[0].contract
    expiry = datetime.strptime(con.lastTradeDateOrContractMonth, "%Y%m%d").replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if expiry - timedelta(weeks=weeks) > now:
        return None                                  # pas encore de donnees utiles
    end = min(expiry + timedelta(days=1), now)

    frames = []
    for _ in range(weeks):
        bars = ib.reqHistoricalData(con, endDateTime=end, durationStr="1 W",
                                    barSizeSetting="5 mins", whatToShow="TRADES",
                                    useRTH=False, formatDate=2)
        time.sleep(pause)
        if not bars:
            break
        df = util.df(bars)
        frames.append(df)
        end = pd.Timestamp(df["date"].min()).to_pydatetime()   # on remonte dans le temps
    if not frames:
        return None
    out = pd.concat(frames).drop_duplicates("date").sort_values("date")
    out = out.rename(columns={"date": "datetime"})[["datetime", "open", "high", "low", "close", "volume"]]
    out["contract"] = con.localSymbol
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="MES", choices=["MES", "ES"])
    ap.add_argument("--years", type=int, default=2)
    ap.add_argument("--weeks", type=int, default=15, help="semaines d'historique par contrat")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7497)
    ap.add_argument("--client-id", type=int, default=17)
    ap.add_argument("--pause", type=float, default=10.5, help="secondes entre deux requetes")
    ap.add_argument("--out-dir", default="data")
    a = ap.parse_args()

    out_dir = Path(a.out_dir)
    out_dir.mkdir(exist_ok=True)
    ib = IB()
    ib.connect(a.host, a.port, clientId=a.client_id)
    try:
        for month in contract_months(a.years):
            path = out_dir / f"{a.symbol}_{month}.csv"
            if path.exists():
                print(f"{path.name} deja present, saute")
                continue
            print(f"Telechargement {a.symbol} {month} ...")
            df = fetch_contract(ib, a.symbol, month, a.weeks, a.pause)
            if df is not None and not df.empty:
                df.to_csv(path, index=False)
                print(f"  {len(df)} barres -> {path.name}")
    finally:
        ib.disconnect()

    files = sorted(out_dir.glob(f"{a.symbol}_2*.csv"))
    if not files:
        print("Aucune donnee recuperee : verifie l'abonnement CME et les messages d'erreur de TWS.")
        return
    full = pd.concat(pd.read_csv(f) for f in files)
    full["datetime"] = pd.to_datetime(full["datetime"], utc=True).dt.strftime("%Y-%m-%d %H:%M:%S%z")
    full = full.drop_duplicates(["datetime", "contract"]).sort_values(["datetime", "contract"])
    target = out_dir / f"{a.symbol}_5min_all.csv"
    full.to_csv(target, index=False)
    print(f"\n{len(full)} barres au total -> {target}")


if __name__ == "__main__":
    main()
