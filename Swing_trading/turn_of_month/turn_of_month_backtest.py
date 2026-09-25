"""
Backtest de l'effet calendaire "turn-of-month" (TOM), en barres journalieres,
sur le sous-groupe des 4 indices larges US (SPY/QQQ/IWM/DIA) -- hypothese
principale -- puis sur les 16 instruments restants du panier cross-asset des
20 (secteurs, matieres premieres, obligataire, international, megacaps) --
cartographie exploratoire secondaire, jamais melangee au verdict principal
(voir STRATEGIES.md #15 -> #16).

Pourquoi cette strategie (et pas une nouvelle variante de #10/#14/#15)
-------------------------------------------------------------------------
`overnight_drift` (#10) est le seul edge structurel valide du projet ; ses
tentatives de generalisation ont toutes echoue (#11 actions individuelles,
#14 filtre de regime Kumo, #15 ETF-paniers hors indices actions larges). Ces
trois echecs partagent un point commun : ils cherchaient a ETENDRE le meme
edge (overnight sur indices US larges) a d'autres perimetres, sans jamais
tester un AUTRE biais structurel/calendaire independant. La litterature
academique documente un second biais calendaire bien distinct : l'effet
"turn-of-month" (Ariel 1987 ; Lakonishok & Smidt 1988) -- une part
disproportionnee du rendement moyen des actions se concentre sur les jours de
bourse autour du changement de mois, attribuee aux flux de rebalancement
institutionnels et aux cotisations mensuelles (plans d'epargne, fonds de
pension). C'est une piste NOUVELLE (Rule #3 : innovation plutot que
confirmer/infirmer indefiniment la meme piste), pas une variante de plus de
l'overnight drift deja teste.

Auto-critique actee AVANT codage (documentee dans STRATEGIES.md #15->#16,
Rule #4) : le turn-of-month et l'overnight drift ne sont pas necessairement
independants -- si l'edge overnight (deja valide sur SPY/QQQ/IWM/DIA) se
concentre en fait sur les jours de fin/debut de mois, un test qui mesurerait
juste le rendement overnight BRUT des jours TOM confondrait les deux effets
(on redecouvrirait #10, pas un nouveau biais). Le protocole ci-dessous isole
donc la composante TOM specifique en comparant, sur le MEME edge overnight
(entree cloture J -> sortie ouverture J+1, structure identique a #10), la
performance des jours TOM contre celle des jours non-TOM -- un grid a 3
configurations ("unfiltered" = overnight_drift original tel quel,
"tom_only" = ne trader QUE les jours TOM, "non_tom_only" = ne trader QUE les
jours hors TOM), selectionnees en in-sample sur le Sharpe, jamais choisies
apres coup (Rule #2). Si tom_only ne bat pas unfiltered ET/OU si non_tom_only
n'est pas nettement pire qu'unfiltered, l'edge overnight connu ne se
concentre PAS sur la fenetre TOM -- l'hypothese specifique testee ici est
alors distincte (et potentiellement fausse) independamment du sort de #10.

Definition operationnelle de la fenetre TOM (causale par construction, sans
aucune fuite de futur -- une date calendaire est connue a l'avance, ce n'est
pas une donnee de marche)
-------------------------------------------------------------------------
Definition academique standard (Lakonishok & Smidt 1988) : dernier jour de
bourse du mois + 3 premiers jours de bourse du mois suivant (fenetre de 4
jours de rendement close-to-close). Transposee a une strategie overnight-only
(positions cloture J -> ouverture J+1, jamais de rendement intrajournalier
mesure), la fenetre se traduit par les jambes overnight suivantes :
  - jambe overnight demarrant au DERNIER jour de bourse du mois (entree a sa
    cloture, sortie a l'ouverture du 1er jour du mois suivant) ;
  - jambe overnight demarrant au 1er jour de bourse du mois (entree a sa
    cloture, sortie a l'ouverture du 2e jour) ;
  - jambe overnight demarrant au 2e jour de bourse du mois (entree a sa
    cloture, sortie a l'ouverture du 3e jour).
Soit 3 jambes overnight "TOM" par transition de mois (couvrant exactement la
fenetre calendaire academique de 4 jours de bourse, comptee en transitions
overnight plutot qu'en rendements journaliers bruts). Un jour i est marque
TOM si son rang inverse dans le mois (0 = dernier jour du mois) vaut 0, OU si
le rang direct du jour i+1 dans son mois (0 = premier jour du mois) est <= 2.

Regles d'execution (aucune fuite de futur, memes conventions que
overnight_backtest.py et regime_filtered_backtest.py)
-------------------------------------------------------------------------
1. L'appartenance TOM du jour i ne depend que du calendrier (rang du jour
   dans son mois), jamais d'une donnee de marche -- connue avant meme le
   telechargement des prix, donc structurellement sans fuite de futur.
2. Un jour = un trade au plus (comme overnight_backtest.py), jamais de
   position tenue plus d'une nuit.
3. Slippage/commission appliques a chaque entree/sortie reelle (jours
   effectivement trades), jamais sur les jours filtres a plat.

Usage
-----
    python turn_of_month_backtest.py --instrument SPY
    python turn_of_month_backtest.py --instrument SPY --secondary  (panier des 16 restants)
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------
# Parametres
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Instrument:
    tick: float
    point_value: float
    commission_side: float


INSTRUMENTS = {
    # Hypothese principale : indices larges (sous-groupe Bonferroni deja
    # defini pour Ichimoku #12 / regime filter #14, seule classe avec une
    # legitimite a priori etablie pour l'edge overnight sous-jacent).
    "SPY": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "QQQ": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "IWM": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "DIA": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    # Cartographie exploratoire secondaire (memes 20 tickers qu'Ichimoku/
    # momentum/regime filter) -- jamais utilisee pour le verdict principal.
    "XLE": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "XLF": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "XLK": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "XLV": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "XLY": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "XLP": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "GLD": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "SLV": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "USO": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "TLT": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "IEF": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "EFA": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "EEM": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "AAPL": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "JPM": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "XOM": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
}

PRIMARY_GROUP = ["SPY", "QQQ", "IWM", "DIA"]
SECONDARY_GROUP = [t for t in INSTRUMENTS if t not in PRIMARY_GROUP]


@dataclass(frozen=True)
class Params:
    filter_tom: str = "unfiltered"  # "unfiltered", "tom_only", "non_tom_only"
    slippage_ticks: float = 1.0


# --------------------------------------------------------------------------
# Donnees : barres journalieres (memes fichiers que ichimoku_daily/)
# --------------------------------------------------------------------------
def load_daily(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_localize(None).dt.normalize()
    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    return df[["date", "open", "high", "low", "close", "volume"]]


# --------------------------------------------------------------------------
# Fenetre turn-of-month (purement calendaire, aucune fuite de futur possible)
# --------------------------------------------------------------------------
def tom_membership(df: pd.DataFrame) -> pd.Series:
    """True pour le jour i si la jambe overnight demarrant a sa cloture
    (cloture i -> ouverture i+1) appartient a la fenetre turn-of-month :
    dernier jour de bourse du mois, ou 1er/2e jour de bourse du mois (dont la
    sortie tombe alors sur le 2e/3e jour du mois)."""
    month = df["date"].dt.to_period("M")
    forward_rank = df.groupby(month).cumcount()
    reverse_rank = df.groupby(month).cumcount(ascending=False)
    next_forward_rank = forward_rank.shift(-1)
    return (reverse_rank == 0) | (next_forward_rank <= 2)


# --------------------------------------------------------------------------
# Moteur : un jour = un trade overnight au plus (entree filtree par TOM)
# --------------------------------------------------------------------------
TRADE_COLS = ["date", "side", "entry_time", "exit_time", "entry", "exit",
              "pts", "r_mult", "tom", "pnl", "reason"]


def run_backtest(df: pd.DataFrame, p: Params, inst: Instrument,
                 rng: np.random.Generator | None = None) -> pd.DataFrame:
    """Position overnight LONG (side=+1) prise entre la cloture du jour i et
    l'ouverture du jour i+1, restreinte selon `p.filter_tom` ("unfiltered" =
    tous les jours, "tom_only" = uniquement les jours TOM, "non_tom_only" =
    uniquement les jours hors TOM). Si `rng` est fourni (test placebo), le
    FILTRE (quels jours sont trades) est conserve a l'identique -- seul le
    SENS de la position (long/short) est tire au hasard, meme principe que
    overnight_backtest.py et regime_filtered_backtest.py."""
    tom = tom_membership(df)
    slip = inst.tick * p.slippage_ticks
    close = df["close"].to_numpy()
    open_ = df["open"].to_numpy()
    dates = df["date"].to_numpy()
    n = len(df)

    rows = []
    for i in range(n - 1):
        is_tom = bool(tom.iloc[i])
        if p.filter_tom == "tom_only" and not is_tom:
            continue
        if p.filter_tom == "non_tom_only" and is_tom:
            continue
        side = 1 if rng is None else int(rng.choice([-1, 1]))
        entry_px = close[i] + side * slip
        exit_px = open_[i + 1] - side * slip
        pts = (exit_px - entry_px) * side
        pnl = pts * inst.point_value - 2 * inst.commission_side
        risk_pts = 2 * slip if slip > 0 else 1.0
        rows.append({
            "date": dates[i + 1], "side": side,
            "entry_time": dates[i], "exit_time": dates[i + 1],
            "entry": entry_px, "exit": exit_px, "pts": pts,
            "r_mult": pts / risk_pts, "tom": is_tom,
            "pnl": pnl, "reason": p.filter_tom,
        })
    return pd.DataFrame(rows, columns=TRADE_COLS)


# --------------------------------------------------------------------------
# Metriques et tests de robustesse (memes conventions que les strategies
# precedentes)
# --------------------------------------------------------------------------
def sel(trades: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    return trades[trades["date"].isin(dates)]


def metrics(trades: pd.DataFrame, dates: pd.DatetimeIndex) -> dict:
    daily = trades.groupby("date")["pnl"].sum().reindex(dates, fill_value=0.0) if len(trades) else \
        pd.Series(0.0, index=dates)
    if len(trades) == 0:
        return {"n_trades": 0, "sharpe": np.nan, "t_stat": np.nan}
    eq = np.concatenate([[0.0], daily.cumsum().to_numpy()])
    gains = trades.loc[trades["pnl"] > 0, "pnl"].sum()
    losses = -trades.loc[trades["pnl"] < 0, "pnl"].sum()
    sd = daily.std()
    return {
        "n_trades": len(trades),
        "win_rate": (trades["pnl"] > 0).mean(),
        "exp_$": trades["pnl"].mean(),
        "exp_R": trades["r_mult"].mean(),
        "profit_factor": gains / losses if losses > 0 else np.inf,
        "total_$": trades["pnl"].sum(),
        "sharpe": daily.mean() / sd * np.sqrt(252) if sd > 0 else np.nan,
        "t_stat": daily.mean() / sd * np.sqrt(len(daily)) if sd > 0 else np.nan,
        "max_dd_$": (eq - np.maximum.accumulate(eq)).min(),
    }


def walk_forward(df: pd.DataFrame, inst: Instrument, grid: list[Params],
                 dates: pd.DatetimeIndex, train_months: int = 12,
                 test_months: int = 3) -> tuple[pd.DataFrame, list, pd.DatetimeIndex]:
    all_trades = {p: run_backtest(df, p, inst) for p in grid}
    parts, log, test_all = [], [], []
    t0 = dates.min()
    while True:
        t1 = t0 + pd.DateOffset(months=train_months)
        t2 = t1 + pd.DateOffset(months=test_months)
        train = dates[(dates >= t0) & (dates < t1)]
        test = dates[(dates >= t1) & (dates < t2)]
        if len(test) == 0:
            break

        def score(p):
            s = metrics(sel(all_trades[p], train), train).get("sharpe", np.nan)
            return -1e9 if pd.isna(s) else s

        best = max(grid, key=score)
        parts.append(sel(all_trades[best], test))
        test_all.append(test)
        log.append((t1.date(), best.filter_tom))
        t0 = t0 + pd.DateOffset(months=test_months)
    oos = pd.concat(parts) if parts else pd.DataFrame(columns=TRADE_COLS)
    wf_dates = test_all[0].append(test_all[1:]) if test_all else dates[:0]
    return oos, log, wf_dates


def random_direction_test(df, p, inst, dates, n_sims=300, seed=0):
    """Meme filtre TOM (memes jours retenus), direction tiree a pile ou
    face. Si le sens reel (long systematique) ne bat pas ca, la direction
    n'apporte aucune information -- teste separement du filtre de timing
    lui-meme (compare via la table de resultats tom_only vs unfiltered vs
    non_tom_only)."""
    actual = sel(run_backtest(df, p, inst), dates)["pnl"].sum()
    rng = np.random.default_rng(seed)
    sims = np.array([sel(run_backtest(df, p, inst, rng), dates)["pnl"].sum()
                     for _ in range(n_sims)])
    pval = (np.sum(sims >= actual) + 1) / (n_sims + 1)
    return actual, sims.mean(), sims.std(), pval


def fmt(d: dict) -> str:
    keys = ["n_trades", "win_rate", "exp_$", "exp_R", "profit_factor",
            "total_$", "sharpe", "t_stat", "max_dd_$"]
    return "  ".join(f"{k}={d[k]:.2f}" if k in d and k != "n_trades" else f"{k}={d.get(k)}"
                     for k in keys)


def run_instrument(symbol: str, oos_frac: float = 0.3) -> dict:
    """Execute le protocole complet pour un instrument et renvoie un resume
    (utilise a la fois par main() et par le script d'agregation cross-asset)."""
    inst = INSTRUMENTS[symbol]
    df = load_daily(f"data_{symbol.lower()}/{symbol}_daily_all.csv")
    dates = pd.DatetimeIndex(df["date"])[:-1]  # le dernier jour n'a pas d'ouverture J+1
    k = int(len(dates) * (1 - oos_frac))
    is_dates, oos_dates = dates[:k], dates[k:]

    grid = [Params(filter_tom=f) for f in ("unfiltered", "tom_only", "non_tom_only")]
    all_trades = {p: run_backtest(df, p, inst) for p in grid}

    rows = []
    for p in grid:
        m_is = metrics(sel(all_trades[p], is_dates), is_dates)
        m_oos = metrics(sel(all_trades[p], oos_dates), oos_dates)
        rows.append({"filter": p.filter_tom,
                     "n_IS": m_is.get("n_trades"), "sharpe_IS": m_is.get("sharpe"),
                     "t_IS": m_is.get("t_stat"), "n_OOS": m_oos.get("n_trades"),
                     "sharpe_OOS": m_oos.get("sharpe")})
    table = pd.DataFrame(rows)

    best = max(grid, key=lambda p: (lambda s: -1e9 if pd.isna(s) else s)(
        metrics(sel(all_trades[p], is_dates), is_dates).get("sharpe", np.nan)))
    tr = all_trades[best]
    m_is = metrics(sel(tr, is_dates), is_dates)
    m_oos = metrics(sel(tr, oos_dates), oos_dates)

    actual, mu, sd, pval = random_direction_test(df, best, inst, oos_dates)

    return {
        "symbol": symbol, "table": table, "best": best,
        "m_is": m_is, "m_oos": m_oos, "trades_best": tr,
        "placebo": {"actual": actual, "mu": mu, "sd": sd, "pval": pval},
        "dates": dates, "is_dates": is_dates, "oos_dates": oos_dates,
        "df": df, "all_trades": all_trades,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", default="SPY", choices=INSTRUMENTS)
    ap.add_argument("--oos-frac", type=float, default=0.3)
    ap.add_argument("--plot", action="store_true")
    a = ap.parse_args()

    res = run_instrument(a.instrument, a.oos_frac)
    df, dates = res["df"], res["dates"]
    is_dates, oos_dates = res["is_dates"], res["oos_dates"]

    print(f"\nDonnees : {len(df)} jours ({df['date'].iloc[0].date()} -> {df['date'].iloc[-1].date()})")
    print(f"In-sample : {is_dates[0].date()} -> {is_dates[-1].date()} | "
          f"Hors-echantillon : {oos_dates[0].date()} -> {oos_dates[-1].date()}")

    print(f"\n=== 1. Grille ({len(res['table'])} configurations testees) ===")
    print(res["table"].round(2).to_string(index=False))

    best = res["best"]
    print(f"\n=== 2. Meilleure config in-sample : filter={best.filter_tom} ===")
    print("IS  :", fmt(res["m_is"]))
    print("OOS :", fmt(res["m_oos"]))

    inst = INSTRUMENTS[a.instrument]
    grid = [Params(filter_tom=f) for f in ("unfiltered", "tom_only", "non_tom_only")]
    oos_wf, log, wf_dates = walk_forward(df, inst, grid, dates)
    print("\n=== 3. Walk-forward (train 12 mois, test 3 mois) ===")
    if len(wf_dates):
        print("Concatenation des periodes de test :", fmt(metrics(oos_wf, wf_dates)))
        for t1, filt in log:
            print(f"  test a partir de {t1} : filter={filt}")
    else:
        print("Pas assez d'historique pour un walk-forward 12+3 mois.")

    print("\n=== 4. Sensibilite au slippage (meilleure config, toute la periode) ===")
    for s in (0.0, 1.0, 2.0, 3.0):
        p = Params(**{**asdict(best), "slippage_ticks": s})
        print(f"  slippage {s:.0f} tick(s)/execution :", fmt(metrics(run_backtest(df, p, inst), dates)))

    print("\n=== 5. Direction au hasard (meme filtre TOM), hors-echantillon ===")
    pb = res["placebo"]
    print(f"  reel : {pb['actual']:.0f}$ | pile ou face : {pb['mu']:.0f}$ +/- {pb['sd']:.0f}$ "
          f"| p-value = {pb['pval']:.3f}")

    out = f"trades_{a.instrument}_best.csv"
    res["trades_best"].to_csv(out, index=False)
    print(f"\nTrades ecrits dans {out}")

    if a.plot:
        import matplotlib.pyplot as plt
        daily = res["trades_best"].groupby("date")["pnl"].sum().reindex(dates, fill_value=0.0)
        ax = daily.cumsum().plot(figsize=(10, 4), title="P&L cumule (100 actions, apres couts)")
        ax.axvline(oos_dates[0], color="red", ls="--", label="debut hors-echantillon")
        ax.legend()
        plt.tight_layout()
        plt.savefig("examples/equity_best.png", dpi=120)
        print("Courbe ecrite dans examples/equity_best.png")


if __name__ == "__main__":
    main()
