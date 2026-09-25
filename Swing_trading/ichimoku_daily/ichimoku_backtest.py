"""
Backtest de l'indicateur Ichimoku Kinko Hyo en barres journalieres (swing), sur
un panier cross-asset de 20 ETF/actions US (indices, secteurs, matieres
premieres, obligataire, international, megacaps).

Pourquoi une architecture differente des strategies intraday precedentes
--------------------------------------------------------------------------
Toutes les strategies precedentes du projet (ORB, pullback, VWAP, overnight
drift...) ferment leur position au plus tard a la cloture du jour meme :
un jour = un P&L independant du suivant. Ichimoku est concu pour suivre une
tendance qui dure plusieurs jours voire plusieurs semaines (cf. WH SelfInvest :
"les strategies Ichimoku fonctionnent mieux en daily/weekly qu'en intraday").
Le moteur doit donc gerer une position CONTINUE (long/flat/short), tenue sur
plusieurs jours, avec un P&L marque au marche chaque jour plutot que des
trades isoles.

Indicateur (parametres standards 9/26/52, deplacement 26)
-----------------------------------------------------------
- Tenkan-sen  = (plus haut + plus bas) / 2 sur les 9 dernieres barres.
- Kijun-sen   = (plus haut + plus bas) / 2 sur les 26 dernieres barres.
- Senkou A    = (Tenkan + Kijun) / 2, decale de 26 barres en avant.
- Senkou B    = (plus haut + plus bas) / 2 sur les 52 dernieres barres, decale
                de 26 barres en avant.
- Kumo (nuage) = zone entre Senkou A et Senkou B.
Le decalage de 26 barres est applique via un `shift(26)` : la valeur du nuage
"visible" au jour t n'utilise que des donnees jusqu'a t-26 -> aucune fuite de
futur par construction, exactement comme le veut la definition de l'indicateur
(le nuage affiche aujourd'hui a ete calcule il y a 26 jours).

Signaux testes (grille 2x2, comme les grilles a 4 configs des strategies
precedentes -- peu de parametres, peu de risque de data-snooping)
--------------------------------------------------------------------
- **TKC** (Tenkan-Kijun Cross) : croisement du Tenkan au-dessus/en-dessous du
  Kijun (signal WH SelfInvest le plus simple).
- **KBO** (Kumo Breakout) : cassure de la cloture au-dessus/en-dessous du nuage
  (signal WH SelfInvest le plus suivi de tendance).
- **long_short** vs **long_only** : teste si la vente a decouvert ajoute de la
  valeur ou si un biais long-only (coherent avec la derive structurelle
  haussiere des actions US, cf. overnight_drift) suffit/est superieur.

Regles d'execution (aucune fuite de futur)
-------------------------------------------
1. Le signal du jour J est calcule a la CLOTURE de J (Tenkan/Kijun/Kumo ne
   dependent que des barres 0..J, le Kumo affiche a J ne depend que de
   0..J-26).
2. La position cible ainsi determinee est appliquee a partir de l'OUVERTURE de
   J+1 (jamais avant).
3. Position "reversal" : toujours investi (long ou short) des le premier
   signal, jamais de sortie anticipee autre qu'un signal oppose (long_only :
   un signal court ramene juste a plat).
4. P&L marque au marche chaque jour, decompose en segment "overnight"
   (cloture J-1 -> ouverture J, position de la veille) et "intraday"
   (ouverture J -> cloture J, position du jour) : cela permet d'appliquer le
   slippage/commission uniquement au moment reel de l'execution (l'ouverture
   du jour ou la position change), jamais sur un segment ou aucun ordre n'est
   passe.

Usage
-----
    python ichimoku_backtest.py data_spy/SPY_daily_all.csv --instrument SPY

CSV attendu : datetime (UTC), open, high, low, close, volume
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


# point_value=100.0, tick=0.01, commission=1.00$/cote : memes conventions que
# les autres strategies sur actions/ETF US (100 actions de reference).
INSTRUMENTS = {
    # Indices larges
    "SPY": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "QQQ": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "IWM": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "DIA": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    # Secteurs (SPDR)
    "XLE": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "XLF": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "XLK": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "XLV": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "XLY": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "XLP": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    # Matieres premieres
    "GLD": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "SLV": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "USO": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    # Obligataire
    "TLT": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "IEF": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    # International
    "EFA": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "EEM": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    # Megacaps (deja utilisees dans overnight_drift_stocks, secteurs varies)
    "AAPL": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "JPM": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
    "XOM": Instrument(tick=0.01, point_value=100.0, commission_side=1.00),
}


@dataclass(frozen=True)
class Params:
    signal: str = "tkc"        # "tkc" (Tenkan-Kijun cross) ou "kbo" (Kumo breakout)
    mode: str = "long_short"   # "long_short" ou "long_only"
    tenkan_period: int = 9
    kijun_period: int = 26
    senkou_b_period: int = 52
    displacement: int = 26
    atr_period: int = 14
    slippage_ticks: float = 1.0


# --------------------------------------------------------------------------
# Donnees : barres journalieres, une ligne par jour (pas de regroupement
# intraday necessaire contrairement aux strategies 5 min).
# --------------------------------------------------------------------------
def load_daily(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_localize(None).dt.normalize()
    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    return df[["date", "open", "high", "low", "close", "volume"]]


# --------------------------------------------------------------------------
# Indicateur Ichimoku (vectorise, causal par construction)
# --------------------------------------------------------------------------
def ichimoku_lines(df: pd.DataFrame, p: Params) -> dict[str, pd.Series]:
    high, low, close = df["high"], df["low"], df["close"]
    tenkan = (high.rolling(p.tenkan_period).max() + low.rolling(p.tenkan_period).min()) / 2
    kijun = (high.rolling(p.kijun_period).max() + low.rolling(p.kijun_period).min()) / 2
    senkou_a_raw = (tenkan + kijun) / 2
    senkou_b_raw = (high.rolling(p.senkou_b_period).max() + low.rolling(p.senkou_b_period).min()) / 2
    # decalage en avant : le nuage "visible" au jour t ne depend que de t - displacement
    senkou_a = senkou_a_raw.shift(p.displacement)
    senkou_b = senkou_b_raw.shift(p.displacement)
    return {"tenkan": tenkan, "kijun": kijun, "senkou_a": senkou_a, "senkou_b": senkou_b}


def atr_series(df: pd.DataFrame, period: int) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def compute_target_position(df: pd.DataFrame, p: Params) -> pd.Series:
    """Position cible decidee a la CLOTURE du jour t (a appliquer a partir de
    l'ouverture de t+1). +1 = long, -1 = short, 0 = plat. Reversal : la
    position est maintenue jusqu'au signal oppose (ffill), jamais de sortie
    anticipee autre qu'un nouveau signal."""
    lines = ichimoku_lines(df, p)
    close = df["close"]

    if p.signal == "tkc":
        diff = lines["tenkan"] - lines["kijun"]
        cross_up = (diff > 0) & (diff.shift(1) <= 0)
        cross_down = (diff < 0) & (diff.shift(1) >= 0)
    elif p.signal == "kbo":
        cloud_top = pd.concat([lines["senkou_a"], lines["senkou_b"]], axis=1).max(axis=1)
        cloud_bottom = pd.concat([lines["senkou_a"], lines["senkou_b"]], axis=1).min(axis=1)
        cross_up = (close > cloud_top) & (close.shift(1) <= cloud_top.shift(1))
        cross_down = (close < cloud_bottom) & (close.shift(1) >= cloud_bottom.shift(1))
    else:
        raise ValueError(f"signal inconnu : {p.signal}")

    raw = pd.Series(np.nan, index=df.index)
    raw[cross_up] = 1.0
    raw[cross_down] = -1.0
    target = raw.ffill().fillna(0.0)

    # warmup : pas de position tant que les 3 lignes ne sont pas toutes
    # disponibles (senkou_b + displacement = la plus longue fenetre requise)
    warmup = p.senkou_b_period + p.displacement
    target.iloc[:warmup] = 0.0

    if p.mode == "long_only":
        target = target.clip(lower=0.0)
    return target


# --------------------------------------------------------------------------
# Moteur : P&L marque au marche chaque jour (segments overnight/intraday),
# slippage/commission appliques uniquement au moment reel de l'execution.
# --------------------------------------------------------------------------
def simulate(df: pd.DataFrame, p: Params, inst: Instrument,
            rng: np.random.Generator | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Renvoie (daily, trades) :
      - daily : une ligne par jour (date, pos_day, pnl) -- P&L marque au marche,
        utilise pour Sharpe/drawdown/walk-forward/placebo (les seules metriques
        qui comptent pour le critere de decision).
      - trades : un round-trip par run de position non nulle -- metriques
        secondaires (n_trades/win_rate/profit_factor) uniquement.

    Attention comptable : la nuit et la commission de CLOTURE d'un trade sont
    executees a l'OUVERTURE du jour ou la position change (donc rangees, au
    niveau quotidien, dans le P&L du jour suivant le dernier jour de detention).
    Pour que `trades` reflete le P&L reel de chaque position (et pas un
    decoupage ou l'avant-dernier jour semble plus rentable qu'il ne l'est), ces
    deux montants sont ici reattribues explicitement au trade qui se termine,
    jour par jour via des tableaux numpy plutot que via un groupby naif sur
    `pnl` quotidien -- la somme totale reste identique, seule la repartition
    par trade change.

    Si `rng` est fourni (test placebo), les DATES de changement de position
    (le "timing" du signal) sont conservees a l'identique, seul le SIGNE de
    chaque segment est tire au hasard -- exactement le principe deja utilise
    dans overnight_backtest.py (direction aleatoire, timing reel)."""
    target = compute_target_position(df, p)
    slip = inst.tick * p.slippage_ticks

    if rng is not None:
        # meme decoupage temporel (memes dates de changement de segment),
        # signe aleatoire par segment ; en mode long_only les segments plats
        # (0) restent plats, seuls les segments non nuls sont retires.
        change = target.ne(target.shift(1).fillna(0.0))
        seg_id = change.cumsum()
        nonzero_segments = sorted(seg_id[target != 0].unique())
        rand_sign = {seg: rng.choice([-1.0, 1.0]) for seg in nonzero_segments}
        target = pd.Series(
            [rand_sign.get(seg, 0.0) if target.iloc[i] != 0 else 0.0
             for i, seg in enumerate(seg_id)],
            index=df.index,
        )
        if p.mode == "long_only":
            target = target.clip(lower=0.0)

    n = len(df)
    pos_day = target.shift(1).fillna(0.0).to_numpy()   # position tenue PENDANT le jour D (decidee a la cloture D-1)
    pos_prev = np.concatenate([[0.0], pos_day[:-1]])    # position tenue la nuit precedente (= pendant D-1)

    open_ = df["open"].to_numpy()
    close_ = df["close"].to_numpy()
    prev_close = np.concatenate([[np.nan], close_[:-1]])
    changed = pos_day != pos_prev

    exit_slip = np.where(changed & (pos_prev != 0), pos_prev * slip, 0.0)
    entry_slip = np.where(changed & (pos_day != 0), pos_day * slip, 0.0)
    exit_px = open_ - exit_slip
    entry_px = open_ + entry_slip

    overnight_pnl = pos_prev * (exit_px - prev_close) * inst.point_value
    overnight_pnl[0] = 0.0  # pas de cloture veille disponible pour le tout premier jour
    intraday_pnl = pos_day * (close_ - entry_px) * inst.point_value
    entry_comm = np.where(changed & (pos_day != 0), inst.commission_side, 0.0)
    exit_comm = np.where(changed & (pos_prev != 0), inst.commission_side, 0.0)
    pnl = overnight_pnl + intraday_pnl - entry_comm - exit_comm

    daily = pd.DataFrame({"date": df["date"], "pos_day": pos_day, "pnl": pnl})

    # trades : reconstruits directement a partir des indices entiers (voir
    # note de comptabilite ci-dessus). Pour un run tenu sur les jours i..j :
    # P&L = intraday des jours i..j + overnight "internes" (i+1..j, detention
    # pure, sans slippage) + overnight ET commission de sortie du jour i1+1
    # (nuit de cloture, executee a l'ouverture du jour suivant) - commission
    # d'entree du jour i.
    dates_arr = df["date"].to_numpy()
    atr = atr_series(df, p.atr_period).to_numpy()
    trades_rows = []
    i = 0
    while i < n:
        if pos_day[i] == 0:
            i += 1
            continue
        side = pos_day[i]
        j = i
        while j + 1 < n and pos_day[j + 1] == side:
            j += 1
        trade_pnl = intraday_pnl[i:j + 1].sum() + overnight_pnl[i + 1:j + 1].sum() - entry_comm[i]
        exit_idx = j + 1
        exit_date = dates_arr[j]
        if exit_idx < n:
            trade_pnl += overnight_pnl[exit_idx] - exit_comm[exit_idx]
            exit_date = dates_arr[exit_idx]
        risk = atr[i] if not np.isnan(atr[i]) and atr[i] > 0 else inst.tick
        pts = trade_pnl / inst.point_value
        trades_rows.append({
            "date": dates_arr[i], "side": int(side),
            "entry_time": dates_arr[i], "exit_time": exit_date,
            "entry": np.nan, "exit": np.nan, "pts": pts, "r_mult": pts / risk,
            "pnl": trade_pnl, "reason": p.signal,
        })
        i = j + 1
    trades = pd.DataFrame(trades_rows, columns=["date", "side", "entry_time", "exit_time",
                                                "entry", "exit", "pts", "r_mult", "pnl", "reason"])
    return daily, trades


# --------------------------------------------------------------------------
# Metriques et tests de robustesse (meme forme que les strategies precedentes,
# adaptees a une serie de P&L quotidien marque au marche plutot qu'a des
# trades isoles)
# --------------------------------------------------------------------------
def sel_daily(daily: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.Series:
    return daily[daily["date"].isin(dates)].set_index("date")["pnl"].reindex(dates, fill_value=0.0)


def sel_trades(trades: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    return trades[trades["exit_time"].isin(dates)]


def metrics(daily_pnl: pd.Series, trades: pd.DataFrame) -> dict:
    if len(daily_pnl) == 0:
        return {"n_trades": len(trades)}
    eq = np.concatenate([[0.0], daily_pnl.cumsum().to_numpy()])
    gains = trades.loc[trades["pnl"] > 0, "pnl"].sum() if len(trades) else 0.0
    losses = -trades.loc[trades["pnl"] < 0, "pnl"].sum() if len(trades) else 0.0
    sd = daily_pnl.std()
    return {
        "n_trades": len(trades),
        "win_rate": (trades["pnl"] > 0).mean() if len(trades) else np.nan,
        "exp_$": trades["pnl"].mean() if len(trades) else np.nan,
        "exp_R": trades["r_mult"].mean() if len(trades) else np.nan,
        "profit_factor": gains / losses if losses > 0 else np.inf,
        "total_$": daily_pnl.sum(),
        "sharpe": daily_pnl.mean() / sd * np.sqrt(252) if sd > 0 else np.nan,
        "t_stat": daily_pnl.mean() / sd * np.sqrt(len(daily_pnl)) if sd > 0 else np.nan,
        "max_dd_$": (eq - np.maximum.accumulate(eq)).min(),
    }


def walk_forward(all_sims: dict, dates: pd.DatetimeIndex, train_months: int = 12,
                 test_months: int = 3) -> tuple[pd.Series, pd.DataFrame, list, pd.DatetimeIndex]:
    parts, trade_parts, log, test_all = [], [], [], []
    t0 = dates.min()
    while True:
        t1 = t0 + pd.DateOffset(months=train_months)
        t2 = t1 + pd.DateOffset(months=test_months)
        train = dates[(dates >= t0) & (dates < t1)]
        test = dates[(dates >= t1) & (dates < t2)]
        if len(test) == 0:
            break

        def score(p):
            daily, _ = all_sims[p]
            s = metrics(sel_daily(daily, train), pd.DataFrame()).get("sharpe", np.nan)
            return -1e9 if pd.isna(s) else s

        best = max(all_sims, key=score)
        best_daily, best_trades = all_sims[best]
        parts.append(sel_daily(best_daily, test))
        trade_parts.append(sel_trades(best_trades, test))
        test_all.append(test)
        log.append((t1.date(), best))
        t0 = t0 + pd.DateOffset(months=test_months)
    oos_daily = pd.concat(parts) if parts else pd.Series(dtype=float)
    oos_trades = pd.concat(trade_parts) if trade_parts else pd.DataFrame()
    wf_dates = test_all[0].append(test_all[1:]) if test_all else dates[:0]
    return oos_daily, oos_trades, log, wf_dates


def random_direction_test(df, p, inst, dates, n_sims=300, seed=0):
    """Meme dates de changement de position (meme timing de signal), direction
    de chaque segment tiree a pile ou face. Si le signe reel choisi par
    Ichimoku ne bat pas ca, la direction du signal n'apporte pas d'information
    (seul le fait de detecter un moment de retournement en apporterait, ce qui
    n'est pas ce qu'on cherche a valider ici)."""
    real_daily, _ = simulate(df, p, inst)
    actual = sel_daily(real_daily, dates).sum()
    rng = np.random.default_rng(seed)
    sims = []
    for _ in range(n_sims):
        d, _ = simulate(df, p, inst, rng)
        sims.append(sel_daily(d, dates).sum())
    sims = np.array(sims)
    pval = (np.sum(sims >= actual) + 1) / (n_sims + 1)
    return actual, sims.mean(), sims.std(), pval


def fmt(d: dict) -> str:
    keys = ["n_trades", "win_rate", "exp_$", "exp_R", "profit_factor",
            "total_$", "sharpe", "t_stat", "max_dd_$"]
    return "  ".join(f"{k}={d[k]:.2f}" if k in d and k != "n_trades" else f"{k}={d.get(k)}"
                     for k in keys)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--instrument", default="SPY", choices=INSTRUMENTS)
    ap.add_argument("--oos-frac", type=float, default=0.3)
    ap.add_argument("--plot", action="store_true")
    a = ap.parse_args()

    inst = INSTRUMENTS[a.instrument]
    df = load_daily(a.csv)
    print(f"\nDonnees : {len(df)} jours ({df['date'].iloc[0].date()} -> {df['date'].iloc[-1].date()})")
    if len(df) < 500:
        print("ATTENTION : moins de 2 ans de donnees, les resultats seront peu fiables "
              "(warmup Ichimoku = 78 jours, walk-forward demande 12+3 mois par fenetre).")

    dates = pd.DatetimeIndex(df["date"])
    k = int(len(dates) * (1 - a.oos_frac))
    is_dates, oos_dates = dates[:k], dates[k:]
    print(f"In-sample : {is_dates[0].date()} -> {is_dates[-1].date()} | "
          f"Hors-echantillon : {oos_dates[0].date()} -> {oos_dates[-1].date()}")

    grid = [Params(signal=s, mode=m) for s in ("tkc", "kbo") for m in ("long_short", "long_only")]
    all_sims = {p: simulate(df, p, inst) for p in grid}

    rows = []
    for p in grid:
        daily, trades = all_sims[p]
        m_is = metrics(sel_daily(daily, is_dates), sel_trades(trades, is_dates))
        m_oos = metrics(sel_daily(daily, oos_dates), sel_trades(trades, oos_dates))
        rows.append({"signal": p.signal, "mode": p.mode,
                     "n_IS": m_is.get("n_trades"), "sharpe_IS": m_is.get("sharpe"),
                     "t_IS": m_is.get("t_stat"), "sharpe_OOS": m_oos.get("sharpe"),
                     "exp$_OOS": m_oos.get("exp_$")})
    table = pd.DataFrame(rows).sort_values("sharpe_IS", ascending=False)
    print(f"\n=== 1. Grille ({len(grid)} configurations testees) ===")
    print(table.round(2).to_string(index=False))

    best = max(grid, key=lambda p: (lambda s: -1e9 if pd.isna(s) else s)(
        metrics(sel_daily(all_sims[p][0], is_dates), pd.DataFrame()).get("sharpe", np.nan)))
    best_daily, best_trades = all_sims[best]
    print(f"\n=== 2. Meilleure config in-sample : {best} ===")
    print("IS  :", fmt(metrics(sel_daily(best_daily, is_dates), sel_trades(best_trades, is_dates))))
    print("OOS :", fmt(metrics(sel_daily(best_daily, oos_dates), sel_trades(best_trades, oos_dates))))

    wf_daily, wf_trades, log, wf_dates = walk_forward(all_sims, dates)
    print("\n=== 3. Walk-forward (train 12 mois, test 3 mois) ===")
    if len(wf_dates):
        print("Concatenation des periodes de test :", fmt(metrics(wf_daily, wf_trades)))
        for t1, p in log:
            print(f"  test a partir de {t1} : signal={p.signal}, mode={p.mode}")
    else:
        print("Pas assez d'historique pour un walk-forward 12+3 mois.")

    print("\n=== 4. Sensibilite au slippage (meilleure config, toute la periode) ===")
    for s in (0.0, 1.0, 2.0, 3.0):
        p = Params(**{**asdict(best), "slippage_ticks": s})
        d, t = simulate(df, p, inst)
        print(f"  slippage {s:.0f} tick(s)/execution :", fmt(metrics(sel_daily(d, dates), t)))

    print("\n=== 5. Direction au hasard (meme timing de signal), hors-echantillon ===")
    actual, mu, sd, pval = random_direction_test(df, best, inst, oos_dates)
    print(f"  reel : {actual:.0f}$ | pile ou face : {mu:.0f}$ +/- {sd:.0f}$ | p-value = {pval:.3f}")

    out = f"trades_{a.instrument}_best.csv"
    best_trades.to_csv(out, index=False)
    print(f"\nTrades ecrits dans {out}")

    if a.plot:
        import matplotlib.pyplot as plt
        eq = sel_daily(best_daily, dates).cumsum()
        ax = eq.plot(figsize=(10, 4), title="P&L cumule (100 actions, apres couts)")
        ax.axvline(oos_dates[0], color="red", ls="--", label="debut hors-echantillon")
        ax.legend()
        plt.tight_layout()
        plt.savefig("equity_best.png", dpi=120)
        print("Courbe ecrite dans equity_best.png")


if __name__ == "__main__":
    main()
