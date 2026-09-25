# Registre des stratégies — évolution récursive

Ce document trace, dans l'ordre chronologique, chaque stratégie testée dans ce
projet : ce qui a été essayé, sur combien d'actifs, le verdict (avec le
critère de décision de `METHODOLOGIE.md`), et **pourquoi** la stratégie
suivante a été choisie. Objectif : que la recherche autonome reste lisible et
traçable dans la durée, sans qu'il soit nécessaire de relire chaque README en
détail pour comprendre où en est le projet.

Règle de fonctionnement (fixée par l'utilisateur) : chaque stratégie est
testée sur 15-20 actifs minimum (une classe d'actifs ou en cross-asset) avant
de passer à la suivante ; le choix de la stratégie et des actifs suivants est
laissé à mon appréciation ; le code est poussé sur GitHub
(`github.com/sachalaborde2-cpu/algorithmic-trading`) à chaque transition.

## Table de suivi

| # | Stratégie | Dossier | Actifs testés | Timeframe | Verdict | p-value placebo (meilleur cas) |
|---|---|---|---|---|---|---|
| 1 | ORB (Opening Range Breakout) | `breakout_opening/` | MES | 5 min intraday | Abandonné (précurseur, voir #3) | — |
| 2 | VWAP reversion | `vwap_reversion/` | MES, SPY, QQQ | 5 min intraday | Rejeté | p=0.003 mais Sharpe OOS négatif |
| 3 | Pullback trend | `pullback_trend/` | MES, SPY, QQQ | 5 min intraday | Rejeté | — |
| 4 | Gap trading | `gap_trading/` | MES, SPY, QQQ | 5 min intraday | Rejeté | — |
| 5 | Vol squeeze (compression Bollinger) | `vol_squeeze/` | MES, SPY, QQQ | 5 min intraday | Rejeté | — |
| 6 | Volume breakout | `volume_breakout/` | MES, SPY, QQQ | 5 min intraday | Rejeté | — |
| 7 | ORB small caps | `orb_small_caps/` | SOFI, PLUG, MARA, RIOT, AFRM, UPST, KRE + indices | 5 min intraday | Rejeté | p=0.844 (pire que le hasard) |
| 8 | Intraday seasonality (13 tranches horaires) | `intraday_seasonality/` | MES, SPY, QQQ | 5 min intraday | Rejeté (Bonferroni) | — |
| 9 | Pairs trading | `pairs_trading/` (+ racine, screening S&P 500) | Paires actions US | Daily | Abandonné | — |
| 10 | **Overnight drift** | `overnight_drift/` | MES, SPY, QQQ, IWM, CSPX | 5 min intraday (fenêtres close/open) | **Seul edge validé du projet** | p=0.040 (SPY), 0.070-0.113 (MES/QQQ/IWM) |
| 11 | Overnight drift sur actions individuelles | `overnight_drift_stocks/` | AAPL, JPM, JNJ, XOM, WMT | 5 min intraday | Rejeté sur les 5 | p=0.096 (JNJ, meilleur cas) |
| 12 | **Ichimoku Kinko Hyo** | `swing_trading/ichimoku_daily/` (à créer) | En cours de conception | Daily (swing) | En cours | — |

## Rationale des transitions

**#10 → #11** : `overnight_drift` a validé un edge structurel sur 4 paniers
larges (indices/ETF), tous fortement corrélés entre eux (ce ne sont pas 4
preuves indépendantes du même phénomène). Avant de considérer ce edge comme
établi, il fallait vérifier s'il se généralise à un niveau plus granulaire —
l'action individuelle — plutôt que de s'arrêter après un seul succès. Bonus
pratique : les actions US ne sont pas bloquées par PRIIPs sur un compte IB
retail européen (contrairement à SPY/QQQ/IWM), donc ce test avait aussi une
utilité de trading réel immédiat.

**#11 → #12** : Le rejet sur les 5 actions confirme que l'edge overnight est
spécifique aux paniers larges, pas à l'action individuelle — piste
raisonnablement épuisée pour l'instant côté "dérive structurelle pure sans
indicateur technique". Sur instruction explicite de l'utilisateur
(2026-09-25) : explorer deux nouveaux axes simultanément - (a) une famille de
stratégie entièrement nouvelle, l'indicateur **Ichimoku Kinko Hyo**, jamais
testée dans ce projet (toutes les stratégies précédentes étaient soit des
patterns de prix intrajournaliers soit un biais structurel sans indicateur),
et (b) élargir le champ au-delà du pur intraday vers du swing/multi-day, champ
non couvert jusqu'ici (à l'exception de `pairs_trading/`, en daily mais
abandonné). Ichimoku est traditionnellement conçu pour des marchés qui
tendent sur des timeframes plus élevés (H4/daily), ce qui motive le choix
d'un backtest en barres journalières plutôt qu'en 5 minutes — cohérent avec
l'indicateur plutôt qu'un choix arbitraire.

## Enseignements transversaux (mis à jour à chaque stratégie)

- Sur ce projet, **11 stratégies testées, 1 seule validée** (overnight drift
  sur indices/ETF) — taux de réussite ~9 %, cohérent avec le principe de
  METHODOLOGIE.md : le protocole est conçu pour rejeter, pas pour confirmer.
- Les tentatives de patterns de prix intrajournaliers purs (ORB, pullback,
  gap, squeeze, volume breakout, VWAP reversion, saisonnalité) ont **toutes**
  échoué, sur indices comme sur small caps — signal que la classe entière
  "pattern technique intraday sur données 5 min" est peu prometteuse dans ce
  cadre de test, par opposition aux biais structurels (overnight) ou,
  potentiellement, aux indicateurs de suivi de tendance sur des timeframes
  plus longs (piste Ichimoku).
- Un edge validé sur un panier large (indice/ETF) ne se transpose pas
  automatiquement à l'action individuelle (#10 vs #11) — chaque niveau de
  granularité doit être retesté indépendamment, pas supposé hérité.
