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
| 12 | Ichimoku Kinko Hyo | `Swing_trading/ichimoku_daily/` | 20 tickers cross-asset (indices, secteurs, matières premières, obligataire, international, méga-caps) | Daily (swing) | Rejeté (Bonferroni hiérarchique, sous-groupe des 4 indices) | p=0.030 (SPY, meilleur cas, seuil corrigé du sous-groupe = 0.0125) |
| 13 | Momentum cross-sectionnel | `Swing_trading/momentum_cross_sectional/` | Mêmes 20 tickers cross-asset | Daily (swing, rebalancement mensuel) | Rejeté | p=0.286 (config sélectionnée en IS), p=0.035 (config non retenue, échoue quand même à 0.0125) |
| 14 | Overnight drift filtré par régime de tendance (Kumo Ichimoku) | `Swing_trading/overnight_drift_regime_filtered/` | Indices/ETF larges (SPY, QQQ, IWM, DIA) — hypothèse principale ; 16 tickers cross-asset en cartographie exploratoire secondaire | Daily (swing, entrée overnight conditionnée) | Rejeté (le filtre n'apporte rien face à l'edge non filtré) | p=0.003 (SPY/QQQ, mais leur meilleure config est "sans filtre" — n'appuie pas l'hypothèse testée) |
| 15 | Overnight drift sur ETF-paniers hors indices actions larges | `Swing_trading/overnight_drift_baskets/` (à créer) | Secteurs SPDR (XLE, XLF, XLK, XLV, XLY, XLP), matières premières (GLD, SLV, USO), obligataire (TLT, IEF), international (EFA, EEM) — 13 ETF-paniers | Daily (swing, entrée overnight non filtrée) | En cours de conception | — |

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

**#12 → #13** : Sur les 20 instruments cross-asset testés (indices, secteurs,
matières premières, obligataire, international, méga-caps), un seul —
SPY — passe le test placebo au seuil naïf de 0.05 (p=0.030), avec un Sharpe
IS/OOS/walk-forward cohérent et une robustesse au slippage inédite dans ce
projet. **Correction méthodologique du 2026-09-25** (voir événement dédié
ci-dessous) : le rejet ne repose plus sur une correction Bonferroni globale à
20 tests (seuil 0.05/20=0.0025), qui traitait à tort 20 classes d'actifs
volontairement diverses comme une seule famille d'hypothèses interchangeables,
mais sur la correction Bonferroni appliquée au seul sous-groupe pertinent a
priori — les 4 indices larges (SPY/QQQ/IWM/DIA), seule classe où Ichimoku a
une légitimité traditionnelle documentée. Seuil de ce sous-groupe : 0.05/4 =
0.0125, encore 2,4× trop strict pour les 0.030 de SPY — donc le verdict final
(rejeté) ne change pas, mais la marge d'échec est nettement plus fine
(2,4× au lieu de 12×) et la raison invoquée est désormais correcte. Ce rejet
reste cohérent avec le reste du projet — un signal directionnel testé sur un
sous-groupe pertinent d'actifs comparables n'a, à ce jour, jamais survécu à la
correction multiple-testing intra-groupe (seul le biais structurel
`overnight_drift`, testé sur 4 instruments fortement corrélés et analysé sans
prétention de généralisation cross-asset, y est parvenu).
Piste suivante choisie de façon autonome : le **momentum cross-sectionnel**
(classement relatif des mêmes 20 instruments par performance passée,
rebalancement périodique), un facteur académique établi (Jegadeesh-Titman)
et le style CTA — déjà identifié dans `vocabulaire.md` comme "le style où un
edge réplicable en gestion retail a historiquement le mieux persisté, car il
repose sur la diversification plutôt que sur la vitesse d'exécution" — jamais
testé dans ce projet, où toutes les stratégies précédentes comparaient un
instrument à son propre passé plutôt qu'à ses pairs au même instant. Réutilise
directement les données déjà téléchargées pour Ichimoku (mêmes 20 tickers, 10
ans de barres journalières), donc pas de nouveau téléchargement nécessaire.

**#13 → #14** : Le momentum cross-sectionnel est rejeté sans ambiguïté : la
config retenue par la procédure de sélection décidée a priori (Sharpe
in-sample, lookback=6/long_only) échoue le test placebo par une large marge
(p=0.286), et le seul résultat isolé qui aurait pu sembler prometteur
(lookback=12/long_only, p=0.035, découvert seulement après coup lors d'un
balayage complet de la grille) n'était pas la config retenue par la
procédure et échoue de toute façon la correction multiple-testing propre à
un grid search de 4 configurations sur le même portefeuille (seuil
0.05/4=0.0125) — l'accepter aurait exigé de revenir sur la sélection après
avoir vu les résultats, exactement le biais psychologique de rationalisation
post-hoc que la règle d'auto-amélioration de la méthodologie interdit
explicitement (voir `CLAUDE.md`, révisé le 2026-09-25).
Deux signaux directionnels/relatifs de suite (Ichimoku #12, momentum #13)
échouent sur ce même panier cross-asset de 20 instruments, alors que le seul
edge validé du projet (`overnight_drift`, #10) est un **biais structurel
calendaire/horaire**, pas un signal basé sur le niveau ou le classement des
prix.

Sur instruction explicite de l'utilisateur (2026-09-25) : apprendre
réellement de cette série d'échecs plutôt que de la documenter puis répéter
le même type d'erreur de conception, ET viser l'**innovation par
combinaison** de ce qui a déjà été étudié dans ce projet plutôt que
d'importer un énième facteur académique isolé testé tel quel (ce qu'étaient,
chacun à sa façon, Ichimoku #12 et le momentum #13). Piste retenue :
**l'edge overnight structurel (`overnight_drift`, seul edge validé du
projet) filtré par le régime de tendance Ichimoku (Kumo)** — n'entrer en
position overnight long que lorsque l'instrument est déjà en régime
haussier au sens du nuage Ichimoku (clôture au-dessus du Kumo), et rester à
plat sinon. C'est une combinaison inédite de deux éléments déjà présents
dans ce projet mais jamais associés : le seul biais structurel validé
(#10) et l'indicateur de régime de tendance déjà backtesté et compris (#12,
dont le signal KBO/Kumo a été rejeté comme signal directionnel autonome,
mais dont la légitimité comme **filtre de régime** — cf. `vocabulaire.md`,
"Filtre de régime" — n'a jamais été testée séparément). Hypothèse
testable et non triviale : l'edge overnight pourrait être plus fort (ou
plus stable) en régime haussier établi qu'en régime baissier/neutre — mais
rien ne garantit a priori ce sens (l'effet pourrait tout aussi bien être
plus fort en régime baissier, type "fuite vers la sécurité" overnight) : le
test doit rester symétrique (au-dessus du Kumo vs en-dessous, testés tous
les deux) et laisser les données trancher, pas cadrer le protocole autour du
résultat anticipé.

**#14 → #15** : Le filtre de régime Kumo est rejeté proprement : sur 3 des 4
indices primaires (SPY, QQQ, DIA), il n'est même pas préféré à l'absence de
filtre en in-sample, et le seul cas où il l'est (IWM) échoue le seuil
Bonferroni de son sous-groupe (p=0.013 contre 0.0125 requis). L'edge overnight
non filtré reste, lui, pleinement confirmé (p=0.003 sur SPY/QQQ) — c'est le
filtre qui échoue, pas la stratégie `overnight_drift` sous-jacente.
Application de Rule #4 (être critique, y compris envers mes propres choix
précédents) : `overnight_drift` (#10) n'a été validé que sur 4 paniers larges
d'indices actions US, très corrélés entre eux, et `overnight_drift_stocks`
(#11) l'a rejeté sur 5 actions individuelles — mais la frontière testée par
#11 (indice vs action individuelle) confond deux dimensions : "large panier
diversifié" et "classe d'actifs actions". Une question restée sans réponse
dans ce projet : l'edge overnight est-il spécifique aux **indices actions**,
ou plus généralement à **tout ETF/panier liquide avec flux institutionnels
lourds à la clôture** (secteurs, matières premières, obligataire,
international) ? Les 16 tickers cross-asset déjà téléchargés pour Ichimoku
incluent justement 13 ETF-paniers (hors les 3 méga-caps déjà couvertes par
#11 : AAPL, JPM, XOM) jamais testés pour ce biais structurel précis avec le
protocole complet. Piste retenue pour #15 : **généralisation de l'overnight
drift aux ETF-paniers hors indices actions larges** — XLE/XLF/XLK/XLV/XLY/XLP
(secteurs SPDR), GLD/SLV/USO (matières premières), TLT/IEF (obligataire),
EFA/EEM (international) — dossier `Swing_trading/overnight_drift_baskets/`,
réutilisant les données déjà en place, sans filtre ni indicateur (retour
volontaire à la version la plus simple de la stratégie validée, pas une
nouvelle combinaison) pour isoler la question à sa forme la plus pure : ce
biais est-il un phénomène par classe d'actif ou par structure de produit
(panier vs titre unique) ? Sous-groupe Bonferroni a priori : ces 13 ETF,
seuil 0.05/13 ≈ 0.00385 — auto-critique assumée : ce sous-groupe mélange déjà
4 classes économiques différentes (secteurs, matières premières, obligataire,
international), ce qui est justifiable ici uniquement parce que l'hypothèse
testée porte sur une propriété de *structure de produit* commune aux 13
(panier liquide, flux de clôture institutionnels), pas sur une propriété
économique sectorielle — mais si l'edge ne se concentre finalement que sur
une seule de ces 4 classes, un second test hiérarchique plus étroit sur cette
classe sera nécessaire avant toute conclusion, exactement comme pour Ichimoku
(#12) où seuls les indices se sont distingués du reste du panier de 20.

**Auto-critique avant de coder (exigée explicitement par l'utilisateur,
2026-09-25 : "sois critique même sur ce que je dis moi [...] ne prend pas
tout au pied de la lettre")** — relecture à froid de cette conception,
deux défauts corrigés avant implémentation :
1. **Mauvais panier pour l'hypothèse principale.** `overnight_drift` (#10)
   n'a été validé que sur des paniers larges indices/ETF fortement corrélés
   (SPY/QQQ/IWM/MES/CSPX) et a été explicitement rejeté sur les actions
   individuelles (#11). Réutiliser mécaniquement les mêmes 20 tickers
   cross-asset qu'Ichimoku/momentum (qui incluent méga-caps individuelles,
   matières premières, obligataire, international — classes où #11 indique
   déjà que l'edge overnight a peu de chances de tenir) aurait dilué un
   résultat potentiellement réel dans un panier majoritairement hors
   périmètre. **Correction, cohérente avec le principe de Bonferroni
   hiérarchique déjà acté** : l'**hypothèse principale** est testée sur le
   sous-groupe où l'edge a une légitimité établie a priori — les indices/ETF
   larges (SPY, QQQ, IWM, DIA — les 4 indices déjà présents dans le panier
   des 20 d'Ichimoku/momentum, cohérent avec le sous-groupe Bonferroni déjà
   défini pour #12) — avec
   sa propre correction multiple-testing restreinte à ce sous-groupe. Le
   reste du panier des 20 (méga-caps, secteurs, matières premières,
   obligataire, international) est conservé en **cartographie exploratoire
   secondaire**, reportée séparément, jamais mélangée au verdict principal.
2. **Risque de perte de puissance statistique.** Le filtre de régime réduit
   mécaniquement le nombre d'entrées overnight, sur un edge déjà marginal
   (p=0.040 à 0.113 selon l'instrument sans filtre). Le nombre de trades
   post-filtre doit être vérifié et rapporté explicitement ; si trop faible,
   la conclusion doit être "échantillon insuffisant pour statuer", jamais une
   extrapolation sur un sous-échantillon appauvri.

**Note technique (vérifiée avant codage)** : contrairement à l'estimation
initiale, aucune nouvelle donnée n'est nécessaire. La fenêtre overnight
(clôture J-1 → ouverture J) se calcule directement à partir des colonnes
open/close des barres **journalières** déjà téléchargées pour Ichimoku
(mêmes conventions de séance `useRTH=True`, 09:30-16:00 ET, que les barres
5 min utilisées dans `overnight_drift/` original — la clôture d'une barre
journalière IB *est* la clôture 16:00, l'ouverture *est* l'ouverture 9:30,
donc rigoureusement équivalent, sans le bruit de devoir ré-identifier les
bornes de séance). Réutilise donc telles quelles les données de
`Swing_trading/ichimoku_daily/data_*/` pour les 20 instruments (hypothèse
principale sur SPY/QQQ/IWM/DIA, cartographie secondaire sur le reste).

## Évolutions de la méthodologie elle-même

**2026-09-25 — correction de la portée de la correction multiple-testing**
(sur remarque explicite de l'utilisateur, voir aussi `CLAUDE.md` section
"Auto-amélioration de la méthodologie") : le verdict initial d'Ichimoku (#12)
appliquait une correction Bonferroni globale sur les 20 instruments
cross-asset testés, comme si tester 20 classes d'actifs différentes revenait
à poser 20 fois la même question. Erreur de raisonnement identifiée : le but
explicite de tester un large panier cross-asset est de **cartographier** où
un edge se généralise, pas de le soumettre à une seule hypothèse pooled — un
edge concentré sur une seule classe d'actifs peut être un vrai edge
économiquement cohérent plutôt qu'un faux positif à corriger contre des
essais non liés (précédent déjà présent dans le projet sans avoir été nommé
comme principe général : `overnight_drift`, seul edge validé, ne fonctionne
que sur des paniers larges et a été rejeté sur les actions individuelles,
sans que cela remette en cause sa validité sur les paniers).
**Correction adoptée** : appliquer Bonferroni (ou une correction plus fine
type effective-N ajusté de la corrélation) à l'intérieur de **sous-groupes
économiquement cohérents définis a priori**, jamais sur l'ensemble hétérogène
du panier. Recalcul pour Ichimoku : sous-groupe des 4 indices larges
(seule classe avec une légitimité a priori pour ce signal), seuil 0.05/4 =
0.0125 — SPY (p=0.030) échoue toujours, donc le verdict rejeté est confirmé,
mais pour la bonne raison. `METHODOLOGIE.md` section 5 et
`Swing_trading/ichimoku_daily/README.md` (Rigueur/Constats/Verdict) ont été
corrigés en conséquence. Cette distinction (sous-groupe a priori vs pool
global) s'applique désormais à toute stratégie testée sur des actifs
hétérogènes, y compris #13 en cours.

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
- Tester un signal directionnel sur un large panier cross-asset (20
  instruments) rend la correction multiple-testing décisive, mais celle-ci
  doit être bornée au bon périmètre : un résultat isolé à p=0.03-0.05 (#12,
  SPY) reste jugé contre les essais *comparables* (les 4 indices larges,
  seuil 0.0125), pas contre 16 autres classes d'actifs sans rapport dont
  l'échec ou le succès ne dit rien sur la validité du résultat testé. La
  rigueur du protocole ne se relâche jamais face à un résultat qui "a l'air
  bon", mais elle ne se durcit pas non plus artificiellement en élargissant
  le pool de comparaison au-delà de ce qui est économiquement pertinent (voir
  "Évolutions de la méthodologie elle-même" ci-dessus).
- **Ne jamais choisir la config d'une grille après avoir vu les résultats
  OOS/placebo** (#13, momentum cross-sectionnel) : la procédure de sélection
  (Sharpe in-sample) doit être fixée avant de regarder le reste, sinon un
  résultat isolé qui "a l'air bon" dans un balayage complet (ex : p=0.035
  sur une config non retenue) devient une tentation de rationalisation
  post-hoc — la même erreur qu'un trader qui change sa règle après avoir vu
  le trade gagnant. Un grid search de plusieurs configs sur le **même**
  portefeuille/instrument (contrairement à un panier cross-asset diversifié)
  reste soumis à une correction multiple-testing globale classique, car
  toutes les configs répondent à la même question.
- **Deux signaux directionnels/relatifs de suite ont échoué sur le même
  panier cross-asset** (Ichimoku #12, momentum #13), alors que le seul edge
  validé du projet (`overnight_drift`, #10) est un biais structurel
  calendaire/horaire — signal (encore provisoire à ce stade) que les biais
  structurels sans indicateur ni classement de prix pourraient être une
  piste plus prometteuse que les signaux basés sur le niveau ou le rang des
  prix, sur ce type de panier large.
- **Toujours inclure une config "non traitée" (baseline) dans la grille d'un
  filtre, pas seulement ses variantes filtrées** (#14, filtre de régime Kumo) :
  un filtre peut échouer de deux façons bien distinctes — soit il est
  sélectionné en in-sample mais ne survit pas à l'OOS/placebo (cas classique
  d'overfitting, ex. Ichimoku #12, momentum #13), soit il n'est **même pas
  sélectionné** comme meilleur que l'absence de filtre dès l'étape in-sample
  (cas #14 sur 3 des 4 indices primaires) — un rejet plus net et moins cher
  à détecter, mais invisible si la grille ne teste que des variantes filtrées
  entre elles. Cette pratique (déjà appliquée par construction dans #14) doit
  rester systématique pour toute stratégie de filtrage future.
