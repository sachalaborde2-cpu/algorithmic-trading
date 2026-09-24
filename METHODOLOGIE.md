# Méthodologie de backtest

Ce document explique **une seule fois, en détail**, le protocole de rigueur
appliqué à chaque stratégie du dossier `Intraday_trading/`. Chaque README de
stratégie a sa propre section "Rigueur du backtest" qui résume les points
spécifiques à cette stratégie (garde-fous de look-ahead particuliers, etc.) ;
ce document-ci explique le "pourquoi" et le "comment lire les résultats" une
bonne fois pour toutes, sans le répéter à chaque dossier.

Référence : la règle est fixée dans `CLAUDE.md` — *"backtester avec la même
rigueur que la stratégie ORB précédente"*.

## Pourquoi ce protocole existe

Un backtest naïf (une seule période, un seul jeu de paramètres, sans se poser
la question du hasard) trouve presque toujours une configuration "gagnante"
sur des données passées — même sur du bruit pur. Le but du protocole n'est
pas de rendre une stratégie profitable, mais de **rendre difficile de se
tromper soi-même** : chaque étape est une occasion de rejeter une stratégie
qui n'a pas de véritable edge, avant de perdre de l'argent réel dessus. La
grande majorité des stratégies testées dans ce projet (`breakout_opening`,
`vwap_reversion`, `orb_small_caps`, `pullback_trend`, `gap_trading`,
`vol_squeeze`, `volume_breakout`, `intraday_seasonality`...) ont d'ailleurs
été **rejetées** après ce protocole — c'est le résultat attendu la plupart du
temps, pas un échec de la méthode.

## 1. Absence de look-ahead (fuite de futur)

**Ce que c'est** : s'assurer qu'aucune décision de trading (signal, entrée,
stop, sortie) n'utilise, même involontairement, une information qui n'était
pas encore connue au moment réel de la décision.

**Pourquoi** : c'est l'erreur la plus courante et la plus dangereuse en
backtest — elle peut faire passer une stratégie sans aucun edge pour
extrêmement profitable, car le "futur" contient justement l'information qui
manque pour trader parfaitement.

**Comment c'est vérifié dans ce projet** :
- Convention systématique : signal détecté à la clôture d'une barre → exécution
  à l'ouverture de la barre suivante (jamais au prix de la barre du signal
  lui-même).
- Tout indicateur "glissant" (β, ATR, moyenne/écart-type d'un z-score, tranche
  horaire sélectionnée) est calculé uniquement sur des données strictement
  antérieures au jour tradé.
- Chaque stratégie a un ou plusieurs tests unitaires dédiés qui modifient à la
  main une barre future et vérifient que le résultat déjà calculé ne change
  pas (voir `test_*.py` de chaque dossier).

## 2. Coûts et slippage

**Ce que c'est** : inclure dans chaque trade simulé une commission
(aller-retour) et un slippage (écart entre le prix théorique et le prix
réellement obtenu), au lieu de simuler des exécutions à un prix "parfait".

**Pourquoi** : une stratégie qui n'est profitable qu'à coût nul n'a aucune
chance de l'être en réel — le slippage et les commissions sont incompressibles
et souvent du même ordre de grandeur que l'edge recherché en intraday.

**Comment c'est fait** : slippage exprimé en ticks par exécution (typiquement
1 tick de référence, avec une analyse de sensibilité de 0 à 3 ticks — voir
section 6), commission fixe par côté et par jambe, mêmes conventions
`INSTRUMENTS` réutilisées d'une stratégie à l'autre pour rester comparables.

## 3. Split in-sample (IS) / hors-échantillon (OOS)

**Ce que c'est** : couper l'historique en deux, généralement 70 % / 30 %
chronologique (jamais un split aléatoire, qui mélangerait le futur et le
passé). La partie **in-sample** sert à choisir les paramètres (grid search) ;
la partie **hors-échantillon**, jamais vue pendant le choix des paramètres,
sert uniquement à vérifier que ce choix généralise.

**Pourquoi** : sur une grille de N configurations, la meilleure d'entre elles
en in-sample est mécaniquement biaisée à la hausse par construction (voir
section 5, data snooping) — le seul moyen de savoir si ce résultat est réel
est de le rejouer sur des données que le choix n'a pas pu "voir".

**Comment lire le résultat** : si le Sharpe s'effondre ou change de signe
entre IS et OOS, c'est le symptôme classique d'un **overfitting** — la
config "gagnante" a capté du bruit spécifique à la période IS, pas un signal
qui persiste.

## 4. Walk-forward

**Ce que c'est** : au lieu d'un split IS/OOS unique et figé, on répète le
schéma sur des fenêtres glissantes — typiquement 12 mois d'entraînement, puis
3 mois de test, avec ré-optimisation des paramètres à chaque fenêtre — et on
concatène tous les segments de test pour obtenir une série de résultats
"hors-échantillon" sur toute la période disponible.

**Pourquoi** : un split IS/OOS unique ne teste qu'une seule coupure
temporelle ; le walk-forward vérifie que la stratégie reste viable même quand
les paramètres optimaux changent au cours du temps (ce qui est fréquent : voir
par exemple `orb_small_caps/backtest_upst.log`, où la config gagnante change
presque à chaque fenêtre de test — signe que le "edge" trouvé en IS est
instable, pas structurel).

**Comment lire le résultat** : un Sharpe walk-forward cohérent (même signe,
même ordre de grandeur) avec le Sharpe OOS renforce la confiance ; un
walk-forward qui n'est positif que grâce à une poignée de fenêtres, avec des
configs très différentes d'une fenêtre à l'autre, est un signal d'alarme
plutôt qu'une validation.

## 5. Data snooping et correction multiple-testing

**Ce que c'est** : le risque de "trouver" un edge par pur hasard quand on
teste beaucoup de configurations et/ou beaucoup d'instruments/tranches
horaires en parallèle sur le même jeu de données.

**Pourquoi** : avec une grille de 24 configurations, il est statistiquement
attendu qu'au moins une d'entre elles ressorte avec un bon Sharkpe en
in-sample même s'il n'existe aucun edge réel — c'est un pur effet du nombre
d'essais, pas une découverte. Même logique pour tester 8 tickers en parallèle
(`orb_small_caps/`) ou 13 tranches horaires (`intraday_seasonality/`) : plus
on multiplie les essais, plus la probabilité qu'un seul d'entre eux ressorte
positif par hasard augmente.

**Comment c'est géré** : quand plusieurs hypothèses sont testées explicitement
(ex. 13 tranches horaires), une **correction de Bonferroni** est appliquée —
diviser le seuil de p-value voulu par le nombre de tests, ce qui rend le seuil
de t-stat correspondant beaucoup plus strict. Plus généralement, un résultat
isolé qui ressort positif sur un seul ticker/une seule config parmi beaucoup
testés en parallèle est jugé avec la même exigence que les autres (persistance
OOS + walk-forward + placebo), jamais accepté sur son seul mérite in-sample.

## 6. Sensibilité au slippage

**Ce que c'est** : rejouer la meilleure configuration avec un slippage
croissant (typiquement 0, 1, 2, 3 ticks par exécution) pour voir à quelle
vitesse le résultat se dégrade.

**Pourquoi** : le slippage réel dépend de la liquidité de l'instrument et peut
varier dans le temps ; une stratégie dont le Sharpe passe rapidement en
territoire négatif entre 0 et 1 tick de slippage est trop fragile pour être
tradée en réel, même si son résultat "0 slippage" semblait correct.

## 7. Test placebo (random direction test / benchmark aléatoire)

**Ce que c'est** : rejouer exactement le même timing d'entrée/sortie et la
même distance de stop que la stratégie réelle, mais avec une **direction
tirée au hasard** (pile ou face) plutôt que la direction donnée par le signal.
Répété un grand nombre de fois (Monte Carlo) pour obtenir une distribution du
résultat "au hasard", à laquelle on compare le résultat réel — d'où la
**p-value** rapportée.

**Pourquoi c'est le test le plus important** : les tests précédents (IS/OOS,
walk-forward) peuvent tous être satisfaits par un signal qui a simplement la
bonne structure de risque (bon timing, bon stop) sans qu'il y ait la moindre
information dans le **sens** du signal. Le test placebo isole exactement ça :
si la direction donnée par la stratégie n'apporte aucune information par
rapport à une pièce de monnaie, le résultat réel doit se situer dans la
distribution du hasard.

**Comment lire la p-value** :
- **p-value basse (< 0.05)** : le résultat réel serait très improbable sous
  l'hypothèse "direction aléatoire" — signe que la direction contient une
  vraie information (condition nécessaire, mais pas suffisante à elle seule :
  voir `vwap_reversion/README.md`, où p=0.003 sur les trois actifs mais où la
  stratégie est quand même rejetée car le Sharpe OOS/walk-forward reste
  négatif).
- **p-value élevée (proche de 1)** : le résultat réel n'est pas seulement "pas
  meilleur" que le hasard, il est **pire** — la direction estimée par le
  signal est en moyenne moins bonne qu'un tirage aléatoire, sur la période
  testée (ex. `orb_small_caps/backtest_upst.log` : ORB réel -1619$ contre
  pile-ou-face -796$ ± 841$, p=0.844).
- Une p-value "moyenne" (ni très basse ni très haute) signifie que le réel et
  le hasard sont statistiquement indiscernables : la stratégie ne fait ni
  mieux ni pire qu'un pari sans information directionnelle.

## Critère de décision global

Une stratégie n'est considérée comme ayant un edge potentiellement réel que
si **toutes** les conditions suivantes sont réunies :
1. Sharpe positif en in-sample (nécessaire mais très insuffisant).
2. Sharpe positif (ou au moins cohérent en signe/ordre de grandeur) en
   hors-échantillon **et** en walk-forward — pas seulement en IS.
3. p-value du test placebo basse (typiquement < 0.05) sur la période
   hors-échantillon.
4. Résultat qui ne s'effondre pas sous une sensibilité au slippage réaliste
   (0 à 2-3 ticks).
5. Si plusieurs instruments/configurations/tranches sont testés en parallèle,
   le résultat retenu doit persister avec la correction multiple-testing
   appropriée (Bonferroni ou équivalent), pas seulement être "le meilleur du
   lot".

À ce jour, une seule stratégie du projet a rempli ces conditions sur
plusieurs instruments à la fois : la **dérive overnight**
(`Intraday_trading/overnight_drift/`), désormais en paper trading sur IB.
Toutes les autres stratégies testées (ORB sous toutes ses variantes, VWAP
reversion, pullback, gap trading, squeeze de volatilité, breakout de volume,
saisonnalité intraday, pairs trading) ont été rejetées à une ou plusieurs de
ces étapes — voir le README de chaque dossier pour le détail chiffré.

## Où voir le protocole appliqué en pratique

Chaque dossier de `Intraday_trading/<strategie>/` contient :
- Le moteur de backtest (`*_backtest.py`), avec les fonctions de grid search,
  walk-forward et test placebo.
- Les tests unitaires (`test_*.py`) qui vérifient spécifiquement l'absence de
  look-ahead pour cette stratégie.
- Un `README.md` avec une section "Rigueur du backtest" (spécificités de la
  stratégie) et un tableau de résultats (Sharpe IS/OOS/walk-forward, p-value
  placebo) — la lecture de ce document explique comment interpréter ce
  tableau.
