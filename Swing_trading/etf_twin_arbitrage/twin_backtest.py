"""
Arbitrage entre ETF "jumeaux" (meme indice / meme metal physique).

Version accessible a un particulier de l'arbitrage ETF / panier propose par
l'utilisateur : le panier d'actions (impossible a vendre a decouvert pour un
particulier : 100-500 ordres par jambe, creation/rachat reserve aux
Authorized Participants) est remplace par un second ETF qui contient
exactement les memes titres. Chacun des deux ETF est rappele vers la meme
valeur liquidative par son propre mecanisme de creation/rachat, donc l'ecart
entre les deux doit revenir a zero. Protocole pre-enregistre dans
STRATEGIES.md ("Choix de #19") avant tout resultat.

Regles (aucune fuite de futur)
------------------------------
1. Ecart s(J) = ln(A ajuste dividendes, cloture J) - ln(B ajuste, cloture J).
   Les prix ajustes (ADJUSTED_LAST d'IB) evitent les faux ecarts aux dates
   de detachement de dividende, differentes d'un ETF a l'autre ; le facteur
   d'ajustement est constant sur toute periode sans detachement, donc il
   s'annule dans s - moyenne(s) : pas de fuite.
2. Valeur d'equilibre = moyenne de s sur les `lookback` clotures STRICTEMENT
   anterieures a J ; deviation d(J) = s(J) - equilibre, en points de base.
3. Si |d(J)| > k : a l'OUVERTURE de J+1, vente de l'ETF cher et achat de
   l'ETF bon marche, `notional` $ par jambe (neutre en dollars).
4. Sortie a l'ouverture qui suit la premiere cloture u >= jour d'entree ou
   d(u) a repasse zero, ou au plus tard apres `max_hold` jours de detention.
5. Couts : commission par action (min par ordre) et slippage en ticks sur
   les 4 executions (prix BRUTS, ceux reellement payes), frais d'emprunt de
   la jambe vendeuse au prorata des jours calendaires.

Usage
-----
    python twin_backtest.py --plot
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace

import numpy as np
import pandas as pd

from twin_universe import GROUP_A, GROUP_B

GRID_K = [3.0, 6.0, 12.0]
TRADE_COLS = ["date", "pair", "side", "d_signal_bps", "d_open_bps", "entry_date",
              "exit_date", "hold_days", "gross", "costs", "pnl", "gross_close_entry"]


@dataclass(frozen=True)
class Params:
    k_bps: float = 6.0
    lookback: int = 20
    max_hold: int = 10
    slippage_ticks: float = 1.0
    notional: float = 100_000.0
    tick: float = 0.01
    commission_per_share: float = 0.005
    commission_min: float = 1.0
    borrow_rate: float = 0.005


# --------------------------------------------------------------------------
# Donnees
# --------------------------------------------------------------------------
def load_ticker(t: str, data_dir: str = "data") -> pd.DataFrame:
    out = None
    for suffix in ("raw", "adj"):
        df = pd.read_csv(f"{data_dir}/{t}_{suffix}.csv")
        df["date"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_localize(None).dt.normalize()
        df = df[["date", "open", "close"]].rename(columns={"open": f"open_{suffix}", "close": f"close_{suffix}"})
        out = df if out is None else out.merge(df, on="date")
    return out


def load_pair(a: str, b: str, data_dir: str = "data") -> pd.DataFrame:
    da = load_ticker(a, data_dir).add_prefix("a_").rename(columns={"a_date": "date"})
    db = load_ticker(b, data_dir).add_prefix("b_").rename(columns={"b_date": "date"})
    return da.merge(db, on="date").sort_values("date").reset_index(drop=True)


# --------------------------------------------------------------------------
# Signal
# --------------------------------------------------------------------------
def spread(df: pd.DataFrame) -> pd.Series:
    return np.log(df["a_close_adj"]) - np.log(df["b_close_adj"])


def fair_value(df: pd.DataFrame, p: Params) -> pd.Series:
    return spread(df).shift(1).rolling(p.lookback).mean()


def deviation_bps(df: pd.DataFrame, p: Params) -> pd.Series:
    return (spread(df) - fair_value(df, p)) * 1e4


# --------------------------------------------------------------------------
# Couts
# --------------------------------------------------------------------------
def execution_cost(raw_price: float, p: Params) -> float:
    shares = p.notional / raw_price
    return p.slippage_ticks * p.tick * shares + max(p.commission_min, p.commission_per_share * shares)


# --------------------------------------------------------------------------
# Simulation d'une paire
# --------------------------------------------------------------------------
def simulate_pair(df: pd.DataFrame, p: Params, name: str = "") -> pd.DataFrame:
    d = deviation_bps(df, p).to_numpy()
    fair = fair_value(df, p).to_numpy()
    dates = df["date"].to_numpy()
    a_o, b_o = df["a_open_adj"].to_numpy(), df["b_open_adj"].to_numpy()
    a_c, b_c = df["a_close_adj"].to_numpy(), df["b_close_adj"].to_numpy()
    a_raw, b_raw = df["a_open_raw"].to_numpy(), df["b_open_raw"].to_numpy()
    n = len(df)
    rows = []
    i = 0
    while i < n - 2:
        if np.isnan(d[i]) or abs(d[i]) <= p.k_bps:
            i += 1
            continue
        sgn = np.sign(d[i])
        side = -int(sgn)  # +1 = long A / short B ; d>0 => A cher => side -1
        entry = i + 1
        last = min(entry + p.max_hold - 1, n - 2)
        u = entry
        while u < last and d[u] * sgn > 0:
            u += 1
        exit_ = u + 1

        ra = a_o[exit_] / a_o[entry] - 1.0
        rb = b_o[exit_] / b_o[entry] - 1.0
        gross = side * p.notional * (ra - rb)
        costs = (execution_cost(a_raw[entry], p) + execution_cost(a_raw[exit_], p)
                 + execution_cost(b_raw[entry], p) + execution_cost(b_raw[exit_], p))
        cal_days = (pd.Timestamp(dates[exit_]) - pd.Timestamp(dates[entry])).days
        costs += p.notional * p.borrow_rate * cal_days / 360.0
        d_open = (np.log(a_o[entry]) - np.log(b_o[entry]) - fair[i]) * 1e4
        # Borne haute NON tradable : entree au cours de cloture meme ou l'ecart est mesure.
        gross_close_entry = side * p.notional * (a_o[exit_] / a_c[i] - b_o[exit_] / b_c[i])
        rows.append({
            "date": dates[exit_], "pair": name, "side": side,
            "d_signal_bps": d[i], "d_open_bps": d_open,
            "entry_date": dates[entry], "exit_date": dates[exit_],
            "hold_days": exit_ - entry, "gross": gross, "costs": costs,
            "pnl": gross - costs, "gross_close_entry": gross_close_entry,
        })
        i = exit_
    return pd.DataFrame(rows, columns=TRADE_COLS)


def simulate_group(pairs_data: dict, p: Params) -> pd.DataFrame:
    parts = [simulate_pair(df, p, name) for name, df in pairs_data.items()]
    parts = [x for x in parts if len(x)]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=TRADE_COLS)


# --------------------------------------------------------------------------
# Metriques et robustesse (conventions du projet)
# --------------------------------------------------------------------------
def sel(trades: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    return trades[trades["date"].isin(dates)]


def metrics(trades: pd.DataFrame, dates: pd.DatetimeIndex) -> dict:
    daily = trades.groupby("date")["pnl"].sum().reindex(dates, fill_value=0.0)
    eq = np.concatenate([[0.0], daily.cumsum().to_numpy()])
    gains = trades.loc[trades["pnl"] > 0, "pnl"].sum()
    losses = -trades.loc[trades["pnl"] < 0, "pnl"].sum()
    sd = daily.std()
    n = len(trades)
    return {
        "n_trades": n,
        "win_rate": (trades["pnl"] > 0).mean() if n else np.nan,
        "exp_$": trades["pnl"].mean() if n else np.nan,
        "gross_bps": trades["gross"].mean() / Params.notional * 1e4 if n else np.nan,
        "cost_bps": trades["costs"].mean() / Params.notional * 1e4 if n else np.nan,
        "profit_factor": gains / losses if losses > 0 else np.inf,
        "total_$": trades["pnl"].sum(),
        "sharpe": daily.mean() / sd * np.sqrt(252) if sd > 0 else np.nan,
        "t_stat": daily.mean() / sd * np.sqrt(len(daily)) if sd > 0 else np.nan,
        "max_dd_$": (eq - np.maximum.accumulate(eq)).min(),
    }


def fmt(m: dict) -> str:
    out = []
    for k, v in m.items():
        out.append(f"{k}={v}" if k == "n_trades" else f"{k}={v:.2f}")
    return "  ".join(out)


def nan_to_floor(x: float) -> float:
    return -1e9 if pd.isna(x) else x


def random_direction_test(trades: pd.DataFrame, n_sims: int = 5000, seed: int = 0):
    actual = trades["pnl"].sum()
    if len(trades) == 0:
        return actual, 0.0, 0.0, 1.0
    rng = np.random.default_rng(seed)
    signs = rng.choice([-1.0, 1.0], size=(n_sims, len(trades)))
    sims = signs @ trades["gross"].to_numpy() - trades["costs"].sum()
    # Tolerance : le tirage "tous les signes = reel" doit compter comme >= reel
    # malgre l'arrondi flottant (decisif quand il y a tres peu de trades).
    pval = (np.sum(sims >= actual - 1e-6 * (1 + abs(actual))) + 1) / (n_sims + 1)
    return actual, sims.mean(), sims.std(), pval


def walk_forward(all_trades: dict, dates: pd.DatetimeIndex, train_months: int = 12, test_months: int = 3):
    parts, log, test_all = [], [], []
    t0 = dates.min()
    while True:
        t1 = t0 + pd.DateOffset(months=train_months)
        t2 = t1 + pd.DateOffset(months=test_months)
        train = dates[(dates >= t0) & (dates < t1)]
        test = dates[(dates >= t1) & (dates < t2)]
        if len(test) == 0:
            break
        best = max(all_trades, key=lambda k: nan_to_floor(metrics(sel(all_trades[k], train), train)["sharpe"]))
        parts.append(sel(all_trades[best], test))
        test_all.append(test)
        log.append((t1.date(), best))
        t0 = t0 + pd.DateOffset(months=test_months)
    oos = pd.concat(parts) if parts else pd.DataFrame(columns=TRADE_COLS)
    wf_dates = test_all[0].append(test_all[1:]) if test_all else dates[:0]
    return oos, log, wf_dates


# --------------------------------------------------------------------------
# Programme principal
# --------------------------------------------------------------------------
def load_group(pairs) -> dict:
    return {f"{a}/{b}": load_pair(a, b) for a, b in pairs}


def union_dates(pairs_data: dict) -> pd.DatetimeIndex:
    idx = None
    for df in pairs_data.values():
        d = pd.DatetimeIndex(df["date"])
        idx = d if idx is None else idx.union(d)
    return idx.sort_values()


def diagnostics(pairs_data: dict, p: Params) -> pd.DataFrame:
    rows = []
    for name, df in pairs_data.items():
        d = deviation_bps(df, p).dropna()
        t = simulate_pair(df, replace(p, k_bps=6.0), name)
        rem = (t["d_open_bps"] / t["d_signal_bps"]).median() if len(t) else np.nan
        px = min(df["a_close_raw"].iloc[-1], df["b_close_raw"].iloc[-1])
        rows.append({"pair": name, "start": df["date"].iloc[0].date(), "n_days": len(df),
                     "median_|d|_bps": d.abs().median(), "p90_|d|_bps": d.abs().quantile(0.9),
                     "%>3": (d.abs() > 3).mean() * 100, "%>6": (d.abs() > 6).mean() * 100,
                     "%>12": (d.abs() > 12).mean() * 100,
                     "reste_a_l_ouverture(k=6)": rem,
                     "cout_AR_bps": 4 * execution_cost(px, p) / p.notional * 1e4})
    return pd.DataFrame(rows)


def per_pair_mapping(pairs_data: dict, is_dates, oos_dates, n_tests: int, label: str) -> None:
    thr = 0.05 / n_tests
    print(f"\n=== {label} : cartographie par paire (meilleur k IS par paire, seuil {thr:.4f}) ===")
    rows = []
    for name, df in pairs_data.items():
        tr = {k: simulate_pair(df, Params(k_bps=k), name) for k in GRID_K}
        best = max(GRID_K, key=lambda k: nan_to_floor(metrics(sel(tr[k], is_dates), is_dates)["sharpe"]))
        m_is = metrics(sel(tr[best], is_dates), is_dates)
        m_oos = metrics(sel(tr[best], oos_dates), oos_dates)
        _, mu, sd, pval = random_direction_test(sel(tr[best], oos_dates))
        rows.append({"pair": name, "best_k": best, "n_IS": m_is["n_trades"], "sharpe_IS": m_is["sharpe"],
                     "gross_bps_IS": m_is["gross_bps"], "cost_bps": m_is["cost_bps"],
                     "n_OOS": m_oos["n_trades"], "sharpe_OOS": m_oos["sharpe"],
                     "total_OOS_$": m_oos["total_$"], "p_placebo_OOS": pval,
                     "passe": "OUI" if (pval < thr and nan_to_floor(m_oos["sharpe"]) > 0
                                        and nan_to_floor(m_is["sharpe"]) > 0) else "non"})
    print(pd.DataFrame(rows).round(3).to_string(index=False))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--oos-frac", type=float, default=0.3)
    ap.add_argument("--plot", action="store_true")
    a = ap.parse_args()

    group_a = load_group(GROUP_A)
    group_b = load_group(GROUP_B)
    dates = union_dates(group_a)
    k = int(len(dates) * (1 - a.oos_frac))
    is_dates, oos_dates = dates[:k], dates[k:]
    print(f"Groupe A : {len(group_a)} paires, {len(dates)} jours ({dates[0].date()} -> {dates[-1].date()})")
    print(f"In-sample : {is_dates[0].date()} -> {is_dates[-1].date()} | "
          f"Hors-echantillon : {oos_dates[0].date()} -> {oos_dates[-1].date()}")

    print("\n=== 0. Diagnostic des ecarts (avant tout trade) ===")
    print("median/p90 |d| = taille de l'ecart a la cloture ; %>k = part des jours au-dessus du seuil ;")
    print("reste_a_l_ouverture = part mediane de l'ecart encore presente a l'ouverture J+1 (k=6) ;")
    print("cout_AR_bps = cout aller-retour des 2 jambes (4 executions, 1 tick + commission), en pb du notionnel")
    diag = pd.concat([diagnostics(group_a, Params()).assign(groupe="A"),
                      diagnostics(group_b, Params()).assign(groupe="B")])
    print(diag.round(2).to_string(index=False))

    all_trades = {kk: simulate_group(group_a, Params(k_bps=kk)) for kk in GRID_K}
    print(f"\n=== 1. Grille portefeuille groupe A ({len(GRID_K)} configurations) ===")
    rows = []
    for kk in GRID_K:
        m_is = metrics(sel(all_trades[kk], is_dates), is_dates)
        m_oos = metrics(sel(all_trades[kk], oos_dates), oos_dates)
        rows.append({"k_bps": kk, "n_IS": m_is["n_trades"], "gross_bps_IS": m_is["gross_bps"],
                     "cost_bps_IS": m_is["cost_bps"], "sharpe_IS": m_is["sharpe"], "t_IS": m_is["t_stat"],
                     "n_OOS": m_oos["n_trades"], "sharpe_OOS": m_oos["sharpe"], "total_OOS_$": m_oos["total_$"]})
    print(pd.DataFrame(rows).round(3).to_string(index=False))

    best = max(GRID_K, key=lambda kk: nan_to_floor(metrics(sel(all_trades[kk], is_dates), is_dates)["sharpe"]))
    tr = all_trades[best]
    print(f"\n=== 2. Meilleure config in-sample : k={best} pb ===")
    print("IS  :", fmt(metrics(sel(tr, is_dates), is_dates)))
    print("OOS :", fmt(metrics(sel(tr, oos_dates), oos_dates)))

    oos_wf, log, wf_dates = walk_forward(all_trades, dates)
    print("\n=== 3. Walk-forward (train 12 mois, test 3 mois) ===")
    print("Concatenation des periodes de test :", fmt(metrics(oos_wf, wf_dates)))
    print("  k choisi par fenetre :", " ".join(f"{t1}:{kk:g}" for t1, kk in log))

    print("\n=== 4. Sensibilite au slippage (meilleure config, toute la periode) ===")
    for s in (0.0, 1.0, 2.0, 3.0):
        t = simulate_group(group_a, Params(k_bps=best, slippage_ticks=s))
        print(f"  slippage {s:.0f} tick(s)/execution :", fmt(metrics(t, dates)))
    t = simulate_group(group_a, Params(k_bps=best, slippage_ticks=0.0, commission_per_share=0.0,
                                       commission_min=0.0, borrow_rate=0.0))
    print("  SANS AUCUN COUT (reference theorique)  :", fmt(metrics(t, dates)))

    print("\n=== 4b. Vitesse ou couts ? Gain brut moyen par trade, en pb du notionnel (k retenu) ===")
    print("  entree_cloture_J = borne haute NON tradable (entree au cours meme ou l'ecart est mesure)")
    rows = []
    for name, g in tr.groupby("pair"):
        rows.append({"pair": name, "n": len(g),
                     "entree_cloture_J": g["gross_close_entry"].mean() / Params.notional * 1e4,
                     "entree_ouverture_J+1": g["gross"].mean() / Params.notional * 1e4,
                     "cout_AR": g["costs"].mean() / Params.notional * 1e4})
    rows.append({"pair": "TOTAL", "n": len(tr),
                 "entree_cloture_J": tr["gross_close_entry"].mean() / Params.notional * 1e4,
                 "entree_ouverture_J+1": tr["gross"].mean() / Params.notional * 1e4,
                 "cout_AR": tr["costs"].mean() / Params.notional * 1e4})
    print(pd.DataFrame(rows).round(2).to_string(index=False))

    print("\n=== 5. Placebo direction aleatoire (hors-echantillon, 5000 tirages) ===")
    actual, mu, sd, pval = random_direction_test(sel(tr, oos_dates))
    print(f"  reel : {actual:.0f}$ | hasard : {mu:.0f}$ +/- {sd:.0f}$ | p-value = {pval:.4f} "
          f"(seuil Bonferroni grid search 0.05/{len(GRID_K)} = {0.05 / len(GRID_K):.4f})")

    per_pair_mapping(group_a, is_dates, oos_dates, n_tests=len(GROUP_A) * len(GRID_K), label="Groupe A")
    dates_b = union_dates(group_b)
    kb = int(len(dates_b) * (1 - a.oos_frac))
    per_pair_mapping(group_b, dates_b[:kb], dates_b[kb:], n_tests=len(GROUP_B) * len(GRID_K),
                     label="Groupe B (exploratoire, hors verdict)")

    sel(tr, dates).to_csv("trades_best.csv", index=False)
    print("\nTrades ecrits dans trades_best.csv")

    if a.plot:
        import matplotlib.pyplot as plt
        daily = tr.groupby("date")["pnl"].sum().reindex(dates, fill_value=0.0)
        gross = tr.groupby("date")["gross"].sum().reindex(dates, fill_value=0.0)
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(dates, gross.cumsum(), color="#8a8a8a", lw=1.5, label="avant couts")
        ax.plot(dates, daily.cumsum(), color="#2a6fdb", lw=2, label="apres couts")
        ax.axvline(oos_dates[0], color="#c0392b", ls="--", lw=1, label="debut hors-echantillon")
        ax.axhline(0, color="#444", lw=0.6)
        ax.set_title(f"Portefeuille groupe A (11 paires, 100 000 $/jambe), k={best:g} pb : P&L cumule")
        ax.set_ylabel("$")
        ax.legend(frameon=False)
        ax.grid(alpha=0.25)
        plt.tight_layout()
        plt.savefig("examples/equity_best.png", dpi=120)
        print("Courbe ecrite dans examples/equity_best.png")


if __name__ == "__main__":
    main()
