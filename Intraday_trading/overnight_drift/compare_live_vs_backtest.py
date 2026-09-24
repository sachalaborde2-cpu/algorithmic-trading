"""
Comparaison hebdomadaire : P&L reel (logs/trades.csv, fills IB) vs P&L
theorique recalcule avec le moteur de backtest (overnight_backtest.py) sur les
memes dates.

Reutilise directement Instrument/Params/simulate_pair/INSTRUMENTS/Day depuis
overnight_backtest.py (meme dossier, pas de sys.path hack) pour eviter toute
divergence de logique entre paper trading et backtest.

Usage
-----
    python compare_live_vs_backtest.py --csv data_spy/SPY_5min_all.csv

Necessite que data_spy/SPY_5min_all.csv couvre au moins les dates presentes
dans logs/trades.csv (le re-telecharger via download_ib_stock.py si besoin).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from overnight_backtest import INSTRUMENTS, Params, load_bars, simulate_pair

HERE = Path(__file__).parent
TRADE_LOG_PATH = HERE / "logs" / "trades.csv"


def load_live_trades(path: Path = TRADE_LOG_PATH) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["timestamp_ny"])
    df = df[df["status"] != "DryRun"]
    return df


def pair_entries_exits(live: pd.DataFrame) -> pd.DataFrame:
    """Associe chaque BUY (entree du soir) au SELL suivant (sortie du
    lendemain) pour reconstruire les paires de trades reels."""
    buys = live[live["action"] == "BUY"].sort_values("timestamp_ny").reset_index(drop=True)
    sells = live[live["action"] == "SELL"].sort_values("timestamp_ny").reset_index(drop=True)
    n = min(len(buys), len(sells))
    rows = []
    for i in range(n):
        rows.append({
            "entry_time": buys.loc[i, "timestamp_ny"],
            "exit_time": sells.loc[i, "timestamp_ny"],
            "quantity": buys.loc[i, "quantity"],
            "entry_fill": buys.loc[i, "fill_price"],
            "exit_fill": sells.loc[i, "fill_price"],
        })
    return pd.DataFrame(rows)


def theoretical_pnl_for_date(days_by_date: dict, date: pd.Timestamp, inst, quantity: float) -> float | None:
    prev_date = date - pd.Timedelta(days=1)
    while prev_date not in days_by_date and (date - prev_date).days < 10:
        prev_date -= pd.Timedelta(days=1)
    if date not in days_by_date or prev_date not in days_by_date:
        return None
    trade = simulate_pair(days_by_date[prev_date], days_by_date[date],
                          Params(leg="overnight", direction=1), inst)
    return trade["pnl"] * (quantity / 100.0)  # pnl de simulate_pair est par 100 actions (point_value=100)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data_spy/SPY_5min_all.csv")
    ap.add_argument("--instrument", default="SPY", choices=INSTRUMENTS)
    ap.add_argument("--trades", default=str(TRADE_LOG_PATH))
    a = ap.parse_args()

    live_path = Path(a.trades)
    if not live_path.exists():
        print(f"Aucun fichier {live_path} : pas encore de trades reels a comparer.")
        return

    live = load_live_trades(live_path)
    if live.empty:
        print("logs/trades.csv est vide (que des DryRun) : rien a comparer.")
        return

    pairs = pair_entries_exits(live)
    if pairs.empty:
        print("Pas encore de paire entree/sortie complete.")
        return

    inst = INSTRUMENTS[a.instrument]
    days, info = load_bars(a.csv, inst=inst)
    days_by_date = {d.date: d for d in days}

    print(f"Donnees backtest : {info['days']} jours ({info['first']} -> {info['last']})")
    print(f"\n{len(pairs)} paire(s) entree/sortie reelle(s) trouvee(s) dans {live_path.name}\n")

    rows = []
    for _, r in pairs.iterrows():
        exit_date = pd.Timestamp(r["exit_time"]).normalize()
        theo = theoretical_pnl_for_date(days_by_date, exit_date, inst, r["quantity"])
        real_pnl = None
        if pd.notna(r["entry_fill"]) and pd.notna(r["exit_fill"]):
            real_pnl = (r["exit_fill"] - r["entry_fill"]) * r["quantity"]
        rows.append({
            "date": exit_date.date(),
            "entry_fill": r["entry_fill"],
            "exit_fill": r["exit_fill"],
            "pnl_reel": real_pnl,
            "pnl_theorique": theo,
            "ecart_$": (real_pnl - theo) if (real_pnl is not None and theo is not None) else None,
        })

    out = pd.DataFrame(rows)
    print(out.to_string(index=False))

    valid = out.dropna(subset=["ecart_$"])
    if not valid.empty:
        print(f"\nEcart moyen reel-theorique : {valid['ecart_$'].mean():.2f}$ "
              f"(std={valid['ecart_$'].std():.2f}$, n={len(valid)})")
    else:
        print("\nPas assez de fill_price renseignes pour calculer l'ecart "
              "(remplir fill_price via ib.trade().fills apres execution).")


if __name__ == "__main__":
    main()
