# Algorithmic trading — règles de travail

## Vocabulaire
Chaque fois que j'utilise un mot de jargon trading ou un acronyme dans une réponse,
je l'ajoute (avec une courte définition) dans `vocabulaire.md` à la racine de ce
dossier, s'il n'y est pas déjà. Ordre alphabétique.

## Nouvelles stratégies intraday
Pour chaque nouvelle stratégie de trading intraday étudiée :
1. Créer un nouveau dossier à la racine de `Intraday_trading/` (un dossier par stratégie).
2. Y mettre tous les fichiers liés : code de backtest, données/scripts de téléchargement,
   tests, résultats (CSV), graphiques.
3. Produire des graphiques illustrant la logique de la stratégie (exemples visuels sur
   des données réelles : range, signal, entrée/sortie, etc.), en plus des résultats de
   performance (équity curve).
4. Toujours backtester avec la même rigueur que la stratégie ORB précédente : pas de
   look-ahead, coûts/slippage inclus, split in-sample/hors-échantillon, walk-forward,
   et un test de robustesse (ex. benchmark aléatoire) avant de conclure à un edge réel.
   Voir `METHODOLOGIE.md` (racine) pour le détail de chaque test (définition, objectif,
   comment interpréter le résultat) et le critère de décision global.

## Auto-amélioration de la méthodologie (règle permanente)
À la fin de chaque stratégie testée, avant de documenter le verdict final, prendre
du recul sur la méthodologie elle-même plutôt que de l'appliquer mécaniquement :
- Se demander si le critère de rejet/validation appliqué correspond vraiment à
  l'objectif réel (trouver un edge rentable), pas seulement à une procédure
  statistique appliquée par réflexe. Ex. : tester 15-20 actifs de classes
  différentes sert à cartographier OÙ un edge se généralise, pas à punir un
  résultat concentré sur une seule classe via une correction multiple-testing
  globale non pertinente (voir l'erreur corrigée sur Ichimoku, révisée avec
  l'utilisateur le 2026-09-25 : Bonferroni doit être appliqué par sous-groupe
  économiquement cohérent défini a priori, pas sur l'ensemble du panier).
- Si la méthodologie s'avère mal calibrée ou trop mécanique sur un point précis,
  corriger `METHODOLOGIE.md` (et refaire le calcul concerné) avant de figer le
  verdict, plutôt que de perpétuer une erreur d'une stratégie à l'autre.
- Documenter dans `STRATEGIES.md` non seulement le verdict, mais aussi toute
  évolution de la méthodologie elle-même décidée à cette occasion.
- **Au-delà des statistiques : respecter les principes fondamentaux d'une bonne
  stratégie de trading** (précisé par l'utilisateur le 2026-09-25) — pas
  d'approximation dans la simulation (coûts, slippage, horaires d'exécution
  réalistes, pas de fuite de futur même subtile) et surtout **pas de biais
  psychologique dans la prise de décision**, y compris de la part de l'agent qui
  choisit le verdict : ne jamais sélectionner après coup la configuration/le
  sous-ensemble de résultats qui "a l'air bien" une fois les résultats connus
  (cherry-picking post-hoc) — c'est la même erreur que le trader qui rationalise
  un trade perdant après coup. Toute sélection de config (grid search) doit être
  décidée sur le critère in-sample AVANT de regarder les résultats
  hors-échantillon/placebo, et le nombre d'essais de cette sélection (ex. une
  grille de N configs sur le même instrument/portefeuille) doit lui-même être
  soumis à une correction multiple-testing standard (globale, car il s'agit bien
  ici d'une seule hypothèse testée N fois) — distinct du cas de la diversité
  cross-asset ci-dessus. Vérifier aussi que les horaires/timing d'exécution
  simulés sont ceux d'un trader réel et discipliné (pas d'exécution à un moment
  irréaliste ou avantageux qu'on ne pourrait pas répliquer en pratique).
