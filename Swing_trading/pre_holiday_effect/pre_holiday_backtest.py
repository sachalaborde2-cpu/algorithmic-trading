"""
Backtest de l'effet pre-jour-ferie ("pre-holiday effect", Ariel 1990) sur le
rendement INTRADAY (ouverture -> cloture, seance ouverte), en barres
journalieres, sur le panier complet des 20 instruments cross-asset -- avec
un sous-groupe primaire (SPY/QQQ/IWM/DIA) rapporte separement par souci de
comparabilite avec les strategies precedentes (#10, #14, #15, #16), sans que
l'hypothese testee ici soit a priori restreinte a ce sous-groupe (voir
STRATEGIES.md #16 -> #17).

Pourquoi cette piste (et pas un 5e filtre du meme edge overnight)
-------------------------------------------------------------------------
Quatre tentatives d'etendre/filtrer l'edge overnight (#11, #14, #15, #16) ont
toutes echoue -- la question est close pour ce projet (voir STRATEGIES.md).
Deux pistes alternatives ont ete envisagees puis rejetees en auto-critique
avant codage (Rule #4, documente dans STRATEGIES.md #16->#17) : le
retournement a court terme (utilise un indicateur de magnitude de prix, classe
deja rejetee par Ichimoku/momentum) et l'effet jour-de-la-semaine applique en
FILTRE de l'entree overnight (un 5e filtre du meme edge, deja conclu comme
non prometteur). La piste retenue ici est structurellement differente : elle
porte sur la jambe INTRADAY (ouverture->cloture), jamais testee comme source
d'edge dans ce projet -- l'edge overnight (#10) porte exclusivement sur la
jambe cloture->ouverture. Purement calendaire (calendrier des jours de
fermeture du marche, connu a l'avance, aucun indicateur ni classement de
prix), coherent avec l'enseignement transversal du projet.

Definition operationnelle du jour "pre-ferie"
-------------------------------------------------------------------------
Un jour de bourse i est marque "pre-ferie" si le jour ouvre (lundi-vendredi)
suivant sa date n'apparait PAS dans le calendrier de bourse reconstruit a
partir des dates de la serie (c'est-a-dire que le marche a ete ferme ce
jour-la pour une raison autre que le week-end). Deliberement derive du
calendrier de bourse REALISE (les dates effectivement presentes dans les
donnees) plutot que du calendrier federal americain officiel : la question
economique posee est "le marche etait-il ferme le jour ouvre suivant",
pas "est-ce un jour ferie federal" (les deux different : Columbus Day et
Veterans Day sont feries au niveau federal mais PAS a la bourse US ; Good
Friday est ferie a la bourse mais pas au niveau federal). Purement calendaire
-- ne depend d'aucune donnee de prix -- verifie par un test dedie.

Auto-critique a surveiller (documentee dans STRATEGIES.md #16->#17)
-------------------------------------------------------------------------
1. Faible nombre de trades pre-ferie (~9-10 jours feries US par an) --
   puissance statistique mecaniquement plus faible qu'aucune strategie
   precedente de ce projet ; rapporte explicitement, seuil de prudence
   renforce avant toute conclusion positive.
2. Risque de chevauchement avec l'effet vendredi/weekend (#16->#17, piste
   jour-de-la-semaine ecartee) : de nombreux jours feries US sont cales sur
   un lundi, creant un pont ; le jour pre-ferie tombe alors un vendredi. La
   grille inclut donc une verification croisee (proportion de jours
   pre-feries qui sont eux-memes des vendredis) rapportee dans le resultat.

Regles d'execution (aucune fuite de futur)
-------------------------------------------------------------------------
1. Entree a l'OUVERTURE du jour i, sortie a la CLOTURE du jour i (meme jour,
   seance ouverte) -- jamais de jambe overnight ici.
2. Le marquage pre-ferie du jour i ne depend que du calendrier de bourse
   (dates presentes dans la serie), jamais du prix.
3. Slippage/commission appliques a chaque entree/sortie reelle.

Usage
-----
    python pre_holiday_backtest.py --instrument SPY
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
    # Sous-groupe rapporte separement par comparabilite avec #10/#14/#15/#16
    # (l'hypothese testee ici n'est PAS a priori restreinte a ce sous-groupe).
    "SPY": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "QQQ": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "IWM": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "DIA": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    # Reste du panier des 20 (memes tickers qu'Ichimoku/momentum/#14/#15/#16).
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
    filter_holiday: str = "unfiltered"  # "unfiltered", "pre_holiday_only", "non_pre_holiday_only"
    slippage_ticks: float = 1.0


# --------------------------------------------------------------------------
# Donnees (memes fichiers que turn_of_month/ichimoku_daily)
# --------------------------------------------------------------------------
def load_daily(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_localize(None).dt.normalize()
    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    return df[["date", "open", "high", "low", "close", "volume"]]


def pre_holiday_membership(df: pd.DataFrame) -> pd.Series:
    """True pour le jour i si le prochain jour ouvre (lundi-vendredi) apres
    sa date n'est PAS un jour de bourse (calendrier reconstruit a partir des
    dates effectivement presentes dans la serie) -- c'est-a-dire que le
    marche a ete ferme pour une raison autre que le week-end. Purement
    calendaire, aucune dependance au prix."""
    dates = df["date"]
    trading_days = pd.DatetimeIndex(dates.unique())
    all_bdays = pd.bdate_range(trading_days.min(), trading_days.max())
    holidays = all_bdays.difference(trading_days)
    next_bday = dates + pd.offsets.BDay(1)
    return pd.Series(next_bday.isin(holidays).to_numpy(), index=df.index)


# --------------------------------------------------------------------------
# Moteur : un jour = un trade intraday au plus (ouverture -> cloture)
# --------------------------------------------------------------------------
TRADE_COLS = ["date", "side", "entry_time", "exit_time", "entry", "exit",
              "pts", "r_mult", "pre_holiday", "pnl", "reason"]


def run_backtest(df: pd.DataFrame, p: Params, inst: Instrument,
                 rng: np.random.Generator | None = None) -> pd.DataFrame:
    """Position intraday LONG (side=+1) prise a l'ouverture du jour i,
    fermee a la cloture du jour i, filtree par le marquage pre-ferie selon
    `p.filter_holiday` ("unfiltered" = tous les jours). Si `rng` est fourni
    (test placebo), le FILTRE (quels jours sont trades) est conserve a
    l'identique -- seul le SENS de la position est tire au hasard, meme
    principe que overnight_backtest.py / turn_of_month_backtest.py."""
    pre_holiday = pre_holiday_membership(df)
    slip = inst.tick * p.slippage_ticks
    open_ = df["open"].to_numpy()
    close = df["close"].to_numpy()
    dates = df["date"].to_numpy()
    n = len(df)

    rows = []
    for i in range(n):
        if p.filter_holiday == "pre_holiday_only" and not pre_holiday.iloc[i]:
            continue
        if p.filter_holiday == "non_pre_holiday_only" and pre_holiday.iloc[i]:
            continue
        side = 1 if rng is None else int(rng.choice([-1, 1]))
        entry_px = open_[i] + side * slip
        exit_px = close[i] - side * slip
        pts = (exit_px - entry_px) * side
        pnl = pts * inst.point_value - 2 * inst.commission_side
        risk_pts = 2 * slip if slip > 0 else 1.0
        rows.append({
            "date": dates[i], "side": side,
            "entry_time": dates[i], "exit_time": dates[i],
            "entry": entry_px, "exit": exit_px, "pts": pts,
            "r_mult": pts / risk_pts, "pre_holiday": bool(pre_holiday.iloc[i]),
            "pnl": pnl, "reason": p.filter_holiday,
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
        log.append((t1.date(), best.filter_holiday))
        t0 = t0 + pd.DateOffset(months=test_months)
    oos = pd.concat(parts) if parts else pd.DataFrame(columns=TRADE_COLS)
    wf_dates = test_all[0].append(test_all[1:]) if test_all else dates[:0]
    return oos, log, wf_dates


def random_direction_test(df, p, inst, dates, n_sims=300, seed=0):
    """Meme filtre pre-ferie (memes jours retenus), direction tiree a pile
    ou face."""
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
    """Execute le protocole complet pour un instrument et renvoie un resume."""
    inst = INSTRUMENTS[symbol]
    df = load_daily(f"data_{symbol.lower()}/{symbol}_daily_all.csv")
    dates = pd.DatetimeIndex(df["date"])
    k = int(len(dates) * (1 - oos_frac))
    is_dates, oos_dates = dates[:k], dates[k:]

    grid = [Params(filter_holiday=f) for f in
            ("unfiltered", "pre_holiday_only", "non_pre_holiday_only")]
    all_trades = {p: run_backtest(df, p, inst) for p in grid}

    rows = []
    for p in grid:
        m_is = metrics(sel(all_trades[p], is_dates), is_dates)
        m_oos = metrics(sel(all_trades[p], oos_dates), oos_dates)
        rows.append({"filter": p.filter_holiday,
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

    pre_holiday = pre_holiday_membership(df)
    n_pre_holiday = int(pre_holiday.sum())
    pct_friday = float(df.loc[pre_holiday, "date"].dt.dayofweek.eq(4).mean()) if n_pre_holiday else np.nan

    return {
        "symbol": symbol, "table": table, "best": best,
        "m_is": m_is, "m_oos": m_oos, "trades_best": tr,
        "placebo": {"actual": actual, "mu": mu, "sd": sd, "pval": pval},
        "dates": dates, "is_dates": is_dates, "oos_dates": oos_dates,
        "df": df, "all_trades": all_trades,
        "n_pre_holiday": n_pre_holiday, "pct_friday": pct_friday,
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
    print(f"Jours pre-feries detectes : {res['n_pre_holiday']} "
          f"({res['n_pre_holiday'] / len(dates) * 100:.1f}% des jours) | "
          f"dont vendredi : {res['pct_friday'] * 100:.1f}%")

    print(f"\n=== 1. Grille ({len(res['table'])} configurations testees) ===")
    print(res["table"].round(2).to_string(index=False))

    best = res["best"]
    print(f"\n=== 2. Meilleure config in-sample : filter={best.filter_holiday} ===")
    print("IS  :", fmt(res["m_is"]))
    print("OOS :", fmt(res["m_oos"]))

    inst = INSTRUMENTS[a.instrument]
    grid = [Params(filter_holiday=f) for f in
            ("unfiltered", "pre_holiday_only", "non_pre_holiday_only")]
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

    print("\n=== 5. Direction au hasard (meme filtre pre-ferie), hors-echantillon ===")
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
        plt.savefig(f"examples/equity_{a.instrument}.png", dpi=120)
        print(f"Courbe ecrite dans examples/equity_{a.instrument}.png")


if __name__ == "__main__":
    main()
