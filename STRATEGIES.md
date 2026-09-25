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
| 15 | Overnight drift sur ETF-paniers hors indices actions larges | `Swing_trading/overnight_drift_baskets/` | Secteurs SPDR (XLE, XLF, XLK, XLV, XLY, XLP), matières premières (GLD, SLV, USO), obligataire (TLT, IEF), international (EFA, EEM) — 13 ETF-paniers | Daily (swing, entrée overnight non filtrée) | Rejeté (12/13 Sharpe IS négatif ; seul GLD positif échoue le seuil Bonferroni) | p=0.013 (GLD, meilleur cas, seuil corrigé du sous-groupe = 0.00385) |
| 16 | Overnight drift filtré par effet turn-of-month | `Swing_trading/turn_of_month/` | Indices/ETF larges (SPY, QQQ, IWM, DIA) — hypothèse principale ; 16 tickers cross-asset en cartographie exploratoire secondaire | Daily (swing, entrée overnight conditionnée au calendrier) | Rejeté (config IS `tom_only` s'effondre en OOS sur les 4 indices, placebo p=0.90-0.97) | p=0.904-0.967 (4 indices primaires, tous pires que le hasard) |
| 17 | Effet pré-jour-férié (jambe intraday, pas filtre overnight) | `Swing_trading/pre_holiday_effect/` | 20 tickers cross-asset (4 indices primaires + 16 cartographie secondaire) | Daily (swing, edge intraday open→close) | Rejeté (Sharpe IS/WF trop faibles sur le groupe primaire ; seul XLP < 0.05 mais Sharpe IS négatif et échoue Bonferroni du grid search) | p=0.020 (XLP, Sharpe IS négatif — rejeté malgré la p-value) |

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

**#15 → #16** : Rejeté sans ambiguïté — sur les 13 ETF-paniers hors indices
actions larges, 12 ont un Sharpe in-sample négatif sur leur meilleure
direction (échec du critère 1 avant même l'OOS), et le seul cas positif
(GLD, Sharpe IS=0.04) échoue le seuil Bonferroni pré-enregistré du
sous-groupe (p=0.013 contre 0.00385 requis). Aucune des 4 sous-classes
(secteurs, matières premières, obligataire, international) ne montre un edge
concentré et cohérent — le caveat pré-enregistré (second test hiérarchique
plus étroit si concentration) ne se déclenche donc pas. Conclusion consolidée
sur #10/#11/#15 : l'edge overnight n'est pas une propriété de *structure de
produit* (panier vs titre unique, hypothèse de #15) ni généralisable à
d'autres *classes d'actifs* en panier — y compris des indices larges
non-US/EM (EFA/EEM, structurellement proches de SPY/QQQ en tant qu'indices
pondérés par capitalisation, mais rejetés ici) — il semble spécifique aux
indices actions **US** larges et très liquides (SPY/QQQ/IWM/DIA). Cette
question de généralisation est donc close pour ce projet, sans qu'il soit
utile de la retester sous une variante supplémentaire (Rule #3 : privilégier
l'innovation par combinaison plutôt que confirmer/infirmer indéfiniment la
même piste).
Application de Rule #3 pour #16 : les deux stratégies validées ou
prometteuses de ce projet sont toutes deux des **biais structurels/calendaires
sans indicateur ni classement de prix** (overnight drift, #10), alors que
tous les signaux basés sur le niveau ou le rang des prix ont échoué (Ichimoku
#12, momentum #13) — enseignement transversal déjà noté. Aucune autre piste
de biais calendaire (indépendante de la fenêtre overnight elle-même) n'a
encore été testée dans ce projet : effet de fin de mois / début de mois
("turn-of-month"), documenté dans la littérature académique comme
concentrant une large part du rendement actions sur quelques jours du
calendrier boursier (flux de rebalancement institutionnels, cotisations
mensuelles). Piste retenue pour #16 : **effet turn-of-month sur indices/ETF
actions larges**, testé avec le même degré de rigueur (IS/OOS/walk-forward/
placebo/Bonferroni), sur le même sous-groupe a priori légitime (SPY, QQQ,
IWM, DIA) en hypothèse principale, et sur un panier cross-asset plus large en
cartographie exploratoire secondaire (cohérent avec le principe de
sous-groupe hiérarchique acté pour #12/#14). Auto-critique à surveiller dès
la conception : le turn-of-month et l'overnight drift ne sont pas
nécessairement indépendants (les jours de fin de mois pourraient simplement
hériter du biais overnight déjà connu) — le protocole devra isoler la
composante turn-of-month spécifique (ex. comparer le rendement overnight des
jours de fin de mois à celui des autres jours) plutôt que mesurer un
rendement brut qui remélangerait les deux effets.

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

**#16 → #17** : Rejeté sans ambiguïté — sur les 4 indices primaires
(SPY/QQQ/IWM/DIA), la config `tom_only` est retenue en in-sample avec un
Sharpe positif mais s'effondre en OOS (Sharpe -0.81 à -1.19, signe opposé) et
échoue le test placebo de façon extrême (p=0.90-0.97, pire que le hasard) —
signature de sur-ajustement la plus nette observée dans ce projet. Aucun des
16 instruments de la cartographie exploratoire secondaire ne passe même le
seuil non corrigé de 0.05. Sur SPY, les configs `unfiltered`/`non_tom_only`
gardent un Sharpe OOS fortement positif (1.24/1.88) pendant que `tom_only`
s'effondre : l'edge overnight (#10) est confirmé toujours présent, mais
explicitement pas concentré dans la fenêtre turn-of-month.

**Bilan des 4 tentatives d'extension de l'edge overnight (#11, #14, #15,
#16)** : actions individuelles, filtre de tendance, autres classes d'actifs
en panier, filtre calendaire turn-of-month — **toutes rejetées**. Chacune
réduit soit le périmètre d'actifs, soit le nombre de trades in-sample
(#14 : ~régime restreint : #16 : ~254 trades contre ~1750 pour la version non
filtrée), et à chaque fois la config retenue en IS ne survit pas à l'OOS/
placebo. Enseignement consolidé (Rule #3/#4) : l'edge overnight sur
SPY/QQQ/IWM/DIA semble être une propriété **globale et inconditionnelle** de
ces 4 instruments sur la période testée — tenter de le sous-diviser plus
finement (par régime, par calendrier, par classe d'actif) détruit la
puissance statistique sans jamais isoler un sous-ensemble qui le surpasse.
Continuer à chercher un filtre qui améliore #10 reviendrait à retester la
même piste une 5e fois (contraire à Rule #3) — cette question est donc close
pour ce projet : `overnight_drift` original (#10), sans filtre, reste
la seule forme validée de cet edge.

Application de Rule #3 pour #17 (première proposition, corrigée ci-dessous
par Rule #4) : plutôt qu'un nouveau filtre du même edge, tester un mécanisme
structurel différent. Première piste envisagée : retournement à très court
terme (short-term reversal) après un mouvement journalier extrême.

**Auto-critique avant de coder (Rule #4) — piste rejetée avant implémentation** :
cette première piste utilise un signal basé sur la **magnitude du mouvement
de prix** de la veille (un mouvement "extrême" doit être mesuré et classé),
ce qui contredit directement l'enseignement transversal consolidé sur ce
projet — les signaux basés sur le niveau/rang/amplitude des prix (Ichimoku
#12, momentum #13) ont systématiquement échoué, alors que seuls les biais
structurels/calendaires **sans aucun indicateur de prix** (overnight drift
#10) ont montré un edge réel. Proposer un retournement-sur-choc aurait
reproduit la même classe d'erreur que #12/#13 sous une autre forme, en
particulier en resssemblant de près au mean-reversion déjà rejeté en bloc
avec les patterns intraday purs (#2 VWAP reversion) — un risque de
rationalisation post-hoc ("cette fois c'est différent") plutôt qu'une
innovation réelle.

**Deuxième proposition, elle aussi rejetée avant implémentation (Rule #4)** :
l'effet jour-de-la-semaine (day-of-week / "weekend effect", French 1980)
appliqué en FILTRE de l'entrée overnight sur SPY/QQQ/IWM/DIA a été envisagé,
mais relecture à froid : c'est structurellement un **5e filtre calendaire du
même edge overnight**, sur le même sous-groupe, avec le même risque déjà
matérialisé trois fois (#14, #15 pour la composante panier, #16) —
exactement la piste que le paragraphe "Bilan" ci-dessus vient de conclure
comme close. La proposer reviendrait à contredire ma propre conclusion
écrite quelques lignes plus haut dans ce même document.

**Piste retenue pour #17 (deuxième correction)** : tester l'effet
pré-jour-férié ("pre-holiday effect", Ariel 1990 : le rendement moyen le
dernier jour de bourse avant un jour férié est significativement supérieur
aux autres jours) comme **edge autonome sur le rendement intraday (ouverture
→ clôture, RTH)**, PAS comme filtre de l'entrée overnight. C'est une
différence structurelle, pas seulement cosmétique, avec #14/#15/#16 : ces
trois stratégies conditionnaient toutes la même jambe overnight
(clôture→ouverture) déjà validée par #10 — un rendement pré-férié, lui, se
loge dans la jambe opposée (ouverture→clôture, séance ouverte), jamais testée
comme source d'edge dans ce projet. Purement calendaire (calendrier des jours
fériés US connu à l'avance, zéro fuite de futur), sans indicateur ni
classement de prix — cohérent avec l'enseignement transversal. Testé sur le
panier complet des 20 instruments (pas de restriction a priori au sous-groupe
indices, puisque l'hypothèse ne porte pas sur l'edge overnight déjà borné à
ce sous-groupe, mais sur un mécanisme intraday distinct — SPY/QQQ/IWM/DIA
restent néanmoins rapportés séparément par souci de comparabilité avec les
stratégies précédentes), avec le même protocole complet (grille
pré-férié/non-pré-férié/sans-filtre, IS/OOS/walk-forward/placebo).

Auto-critique à surveiller dès la conception : (1) le nombre de jours fériés
US par an (~9-10) rend le nombre de trades pré-férié mécaniquement faible
(~9-10 par an, potentiellement 130-150 sur l'historique complet) — le risque
de perte de puissance statistique déjà rencontré sur #16 est encore plus
sévère ici et devra être rapporté explicitement, avec un seuil de prudence
plus strict encore avant toute conclusion positive ; (2) un jour pré-férié
tombe souvent en fin de semaine (nombreux jours fériés US calés sur un lundi,
créant un pont) — vérifier que l'effet mesuré n'est pas simplement une
redite de l'effet vendredi/weekend déjà écarté ci-dessus.

**#17 → #18** : Rejeté sans ambiguïté — sur les 4 indices primaires, la
config `pre_holiday_only` est certes retenue en in-sample, mais avec un
Sharpe à peine positif (t-stat ≤ 0.63) et un walk-forward négatif pour les 4
(-0.05 à -0.61) ; le test placebo ne descend jamais sous 0.05. Sur la
cartographie secondaire, XLP est le seul résultat sous le seuil naïf
(p=0.020), mais son Sharpe in-sample est négatif — il n'est retenu que
comme la moins mauvaise des 3 configs, pas comme un signal positif — et il
échoue en outre la correction Bonferroni propre au grid search de 3
configs (seuil 0.05/3≈0.0167). Confirmation empirique du confound
pré-enregistré (54.2 % des jours pré-fériés sont des vendredis), mais sans
conséquence puisqu'aucun résultat ne survit au protocole de toute façon.
Cinquième tentative consécutive de biais calendaire (#11, #14, #15, #16,
#17) rejetée — la question "existe-t-il un filtre ou un second biais
calendaire qui améliore ou complète l'edge overnight validé" est
définitivement close pour ce projet (Rule #3) : la piste calendaire pure,
sans indicateur ni classement de prix, est désormais épuisée après 5 essais
indépendants, pas seulement les 4 précédents ciblant la jambe overnight.

Application de Rule #3/#4 pour #18 : au lieu de proposer un 6ᵉ biais
calendaire (piste désormais explicitement épuisée, voir ci-dessus) ou un
signal directionnel isolé sur le panier cross-asset (piste également
épuisée : Ichimoku #12, momentum #13 ont tous deux échoué), **combiner deux
éléments déjà validés/étudiés séparément dans ce projet plutôt que
d'importer un signal académique de plus** : le moteur de sélection
cross-sectionnelle construit pour le momentum (#13 — comparer plusieurs
instruments entre eux au même instant, jamais un instrument à son propre
passé) appliqué non pas à un facteur de prix (déjà rejeté), mais pour
**arbitrer, chaque soir, LEQUEL des paniers larges déjà validés pour l'edge
overnight (SPY/QQQ/IWM/DIA) reçoit le trade**, sur la base d'un ensemble de
confirmations pré-enregistrées (ex. régime de tendance Kumo déjà backtesté
en #14, volume, ou tout autre filtre déjà étudié) — au lieu de trader les 4
instruments chaque soir en parallèle (ce qui revient à l'edge #10 déjà
validé), ne trader que l'instrument (ou sous-ensemble) où les confirmations
sont réunies ce jour-là. Idée suggérée par l'utilisateur le 2026-09-25 en
ces termes : passer le trade seulement quand plusieurs confirmations sont
"au vert" simultanément sur un actif donné parmi plusieurs suivis, l'actif
qui déclenche pouvant changer d'un jour à l'autre.

**Passage au filtre des enseignements du projet avant de coder (Rule #4,
appliqué à cette proposition elle-même, y compris venant de l'utilisateur)**
: cette idée est structurellement différente des 4 filtres déjà rejetés
(#14/#15/#16 + une variante de #17), car ceux-ci filtraient le *temps*
(quels jours trader un instrument fixe), alors que celle-ci filtre
*l'instrument* (quel instrument trader un jour fixe) — une dimension jamais
testée dans ce projet pour l'edge overnight. Point de vigilance
obligatoire avant codage, pour ne pas répéter l'erreur de #14/#16 : (1) les
confirmations utilisées comme critère de sélection doivent être
**pré-enregistrées avant de voir les résultats OOS/placebo**, jamais
choisies après coup parmi plusieurs combinaisons testées (sinon c'est un
grid search parmi N combinaisons de confirmations, sur le même
portefeuille de 4 instruments — soumis à la correction multiple-testing
globale standard, comme pour #13, et non à la correction hiérarchique
cross-asset qui ne s'applique qu'à la diversité de classes d'actifs) ; (2)
puisqu'un seul instrument (ou un sous-ensemble restreint) est tradé par
soir au lieu de 4, le nombre de trades effectif chute mécaniquement — le
même risque de perte de puissance statistique que #16/#17 s'applique ici et
devra être mesuré et rapporté avant toute conclusion ; (3) vérifier que le
mécanisme de sélection ne recrée pas simplement le filtre de régime Kumo
déjà rejeté en #14 sous une autre forme (si la seule confirmation retenue
est le régime de tendance) — la valeur ajoutée attendue de cette approche
est la **sélection relative entre instruments**, pas un nouveau filtre
temporel déguisé ; si le protocole ne teste in fine qu'un filtre par
instrument indépendamment (comme #14), ce ne serait pas une innovation
réelle par rapport à la piste déjà close.

## Évolutions de la méthodologie elle-même

**2026-09-25 — clarification de la correction multiple-testing d'un grid
search sur le même instrument** (précisée dans `CLAUDE.md`, section
"Auto-amélioration de la méthodologie") : distincte de la correction
hiérarchique par sous-groupe cross-asset (voir entrée du 2026-09-25
ci-dessous, qui concerne la diversité de *classes d'actifs*), toute grille
de N configurations testées sur le **même** instrument/portefeuille (ex. les
3 configs unfiltered/filtré/anti-filtré de #14 à #17) répond à une seule
question posée N fois, et doit recevoir une correction Bonferroni globale
standard (seuil 0.05/N) — appliquée en plus, jamais à la place, de la
correction hiérarchique quand l'instrument appartient également à un
sous-groupe cross-asset. Appliqué rétroactivement à #17 (XLP, seuil
0.05/3≈0.0167, p=0.020 échoue) ; les stratégies #12 à #16 n'ont pas nécessité
cette distinction dans leur verdict final (les grid search y échouaient déjà
au critère 1 ou à l'OOS avant même d'atteindre ce seuil), donc pas de
révision de leur verdict, seulement de la justification à appliquer
systématiquement à partir de #17.

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
- **Un edge structurel validé sur un panier ne se généralise pas
  automatiquement à d'autres classes d'actifs en panier** (#15, ETF-paniers
  hors indices actions larges) : l'auto-critique de #14→#15 supposait que la
  frontière tracée par #11 (indice vs action individuelle) confondait classe
  d'actif et structure de produit — mais testée directement, l'hypothèse
  "structure de panier" ne tient pas (12/13 ETF en Sharpe IS négatif, y
  compris EFA/EEM qui sont pourtant des indices pondérés par capitalisation
  comme SPY/QQQ). L'edge overnight semble donc bien spécifique aux indices
  actions **US** larges et très liquides, pas à la notion générale de panier
  diversifié. Enseignement méthodologique : une auto-critique (Rule #4) doit
  être testée empiriquement avant d'être actée comme correction — elle peut
  elle-même se révéler fausse, et c'est un résultat valide en soi, pas un
  échec du processus.
- **Un deuxième biais calendaire indépendant (turn-of-month) ne se superpose
  pas à l'edge overnight déjà validé** (#16) : sur les 4 indices primaires
  (SPY/QQQ/IWM/DIA), la config `tom_only` est sélectionnée en in-sample avec
  un Sharpe positif (jusqu'à t=2.47 pour IWM) mais s'effondre en OOS (signe
  opposé) avec un test placebo qui échoue de façon extrême (p=0.90-0.97, la
  direction réelle faisant moins bien que le hasard sur ~108 trades OOS) — la
  signature la plus nette de sur-ajustement observée dans ce projet à ce
  jour, sur un sous-échantillon in-sample de seulement ~254 trades (contre
  ~1750 pour la config non filtrée). Point méthodologique à retenir : plus un
  filtre réduit le nombre de trades in-sample, plus le risque de capter du
  bruit dans la sélection de grille augmente mécaniquement — un Sharpe IS
  positif avec un t-stat modeste (< 2.5) sur quelques centaines
  d'observations doit être traité avec une suspicion renforcée, pas comme un
  signal fort. Par ailleurs, sur SPY, les configs non filtrées par TOM
  (`unfiltered` et `non_tom_only`) affichent un Sharpe OOS nettement positif
  (1.24 et 1.88) pendant que la config TOM s'effondre (-0.93) : l'edge
  overnight (#10) est donc confirmé toujours présent dans cette fenêtre de
  données, mais explicitement pas concentré dans la fenêtre turn-of-month —
  preuve directe contre l'hypothèse testée, pas une simple absence de preuve.
- **Cinq tentatives consécutives de biais calendaire pur ont maintenant
  échoué à filtrer ou compléter l'edge overnight** (#11 actions
  individuelles, #14 régime Kumo, #15 ETF-paniers, #16 turn-of-month, #17
  pré-jour-férié sur la jambe intraday) : la piste "biais calendaire sans
  indicateur ni classement de prix" est riche en théorie académique
  (Ariel, French, Lakonishok-Smidt) mais aucune variante testée ici n'a
  isolé un edge qui survive à l'OOS/walk-forward/placebo sur ce panier de
  20 instruments, en dehors de l'edge overnight structurel original (#10)
  lui-même. Un Sharpe IS positif avec un t-stat faible (<1) sur un
  échantillon réduit par le filtrage (65 à 254 trades selon la stratégie)
  est un schéma désormais récurrent qui ne survit jamais à l'OOS — signal
  qu'un filtre calendaire supplémentaire, quel qu'il soit, n'a plus de
  raison a priori de mieux se comporter qu'un des 5 déjà testés.
- **Une p-value basse ne suffit jamais si le Sharpe in-sample de la config
  retenue est négatif** (#17, XLP) : quand une config n'est sélectionnée que
  parce qu'elle est la moins mauvaise des options de la grille (pas parce
  qu'elle est positive), un résultat OOS/placebo qui a l'air bon est un
  artefact de sélection sur un petit échantillon, pas une confirmation —
  même logique déjà rencontrée sur `vwap_reversion` (#2, p=0.003 mais rejeté
  sur Sharpe OOS négatif). Ce schéma justifie désormais explicitement de
  vérifier le signe du Sharpe IS de la config retenue avant même de lire la
  p-value du placebo, pas seulement après.
- **La correction multiple-testing d'un grid search sur le même instrument
  (Bonferroni global, seuil 0.05/N) est distincte de la correction
  hiérarchique par sous-groupe cross-asset** (seuil 0.05/taille du
  sous-groupe) et les deux s'appliquent en même temps, jamais l'une à la
  place de l'autre, quand un instrument appartient à un sous-groupe testé
  avec une grille de plusieurs configs (voir "Évolutions de la méthodologie"
  ci-dessus, clarifié à l'occasion de #17).
- **Toute proposition de stratégie suivante — y compris venant de
  l'utilisateur ou de l'agent lui-même — doit être passée au filtre des
  enseignements déjà tirés ci-dessus avant d'être codée** (Rule #4) : deux
  propositions de piste calendaire supplémentaire ont déjà été écartées
  avant codage lors du choix de #17 (retournement court terme, effet
  jour-de-la-semaine) précisément parce qu'elles prolongeaient une classe
  déjà rejetée ou contredisaient l'enseignement sur les signaux de prix —
  cette discipline doit rester systématique, pas ponctuelle.
