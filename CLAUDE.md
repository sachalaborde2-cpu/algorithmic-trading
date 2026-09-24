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
