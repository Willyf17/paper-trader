# Paper Lab — expérience multi-actifs à 50 € virtuels

**Performance non établie. Aucun ordre réel ni levier.** Stratégie à règles
fixes, pas un modèle ML entraîné ni un agent OpenAI. Gratuit, sans clé API.
La sophistication ne prouve pas un avantage sur le marché.

## Fonctionnement

- Cinq paires Kraken EUR : BTC, ETH, SOL, XRP, ADA.
- Bougies 15m et 1h clôturées : EMA20/50, pente, RSI, ATR, volume relatif,
  momentum et cassure des 20 bougies précédentes.
- Deux déclencheurs : cassure avec volume, ou reprise après repli dans une
  tendance haussière. Sortie de régime baissier. Aucune entrée forcée.
- Stratégie de retour à la moyenne disponible mais **désactivée** sans validation.
- Classement des opportunités : les scores ne sont pas des probabilités de succès.
- Stops ATR entre 2,5 et 8 %, objectifs ≥9 % et ≥3,5 fois la distance au stop,
  rendement/risque net ≥2. Stops suiveurs activés seulement après clôture.
- Deux positions maximum, 80 % du capital engagé, 50 % par position, risque
  théorique net 2 % par position et 3,5 % au total. Frais et slippage inclus
  dans le budget au stop ; un gap peut néanmoins dépasser ce budget.
- Seconde position refusée si corrélation des rendements 15m >0,85.
- Vérification des minimums/arrondis Kraken, du spread et du volume 24h.
- Pause 6h après trois pertes consécutives ; pause jusqu'au jour UTC suivant
  après perte quotidienne observée ≥8 % ; suspension permanente à drawdown ≥20 %.
- Sortie temporelle après 48h. Portefeuille sauvegardé entre les passages.

## Installer dans un dépôt séparé

1. Créer sur https://github.com/new un dépôt PUBLIC `paper-trader-lab` avec README.
   Conserver le premier bot pour comparer les résultats en direct.
2. Cloner le nouveau dépôt sur le Mac :

```bash
git clone https://github.com/TON_PSEUDO/paper-trader-lab.git
```

3. Décompresser ce ZIP. Copier son contenu dans le dépôt local, y compris
   `.github` et `.gitignore` (Finder : Cmd+Maj+. pour afficher ces fichiers).
4. Dans le Terminal du nouveau dépôt :

```bash
git add engine.py market.py run.py history.py backtest.py test_engine.py config.json README.md VALIDATION.md .github .gitignore
git commit -m "Install multi-asset paper research bot"
git push
```

5. Settings → Actions → General → Workflow permissions → Read and write → Save.
6. Actions → Paper Lab → Run workflow. Vérifier un lancement vert.
7. Rapport : `state/REPORT.md`. Capital après sortie estimée, positions,
   scores, refus, frais, rendement, drawdown et benchmark BTC.
8. Planning : :09, :24, :39, :54 UTC. Mac éteint possible. GitHub peut retarder
   ou omettre une exécution : aucune garantie d'un passage toutes les 15 minutes.
9. Arrêt : Actions → Paper Lab → … → Disable workflow.

Pas d'identifiant d'exchange ni de clé OpenAI. Code et portefeuille virtuel
publics. Runners standards publics gratuits selon l'offre GitHub ; artefacts
soumis aux quotas de stockage, avec rétention de 7 jours pour la recherche.

## Évaluer la stratégie

Actions → Historical evaluation → Run workflow. Par défaut : juin à août 2026,
BTC/EUR, ETH/EUR, SOL/EUR. Le sous-univers est explicite (live : cinq paires).
Télécharger l'artefact `historical-evaluation`, lire `evaluation.json` et
`stress.json`. Une archive manquante déclenche une erreur, pas une substitution.

Archives Binance officielles 15m en EUR avec SHA256 vérifiés, timestamps
millisecondes/microsecondes normalisés et trous temporels rejetés. Trois
partitions chronologiques, mêmes règles figées, chacune à 50 € initiaux.
Ce n'est pas un apprentissage ni une sélection optimisée walk-forward.
Les signaux utilisent uniquement le passé ; entrée à l'ouverture suivante.
Une liquidation forcée termine chaque partition. Stress : frais +50 %,
slippage doublé. Minimum sept jours par partition, plus 300 bougies de warmup.

Comparer rendement net, drawdown, nombre de trades, profit factor, stabilité
entre partitions, achat-conservation BTC et 50 € gardés en réserve. Tester
ensuite d'autres périodes sans ajuster les paramètres au résultat. Un taux de
réussite élevé ne suffit pas : quelques pertes peuvent annuler les gains.
Une soirée ou un backtest favorable ne prouve pas la rentabilité future.

## Coûts et limites de mesure

Live : données publiques Kraken, dernière bougie non clôturée exclue.
Frais supposés 0,40 % par côté, slippage supposé 0,10 % par côté en plus du
spread observé. Ce sont des hypothèses, pas la lecture des frais de ton compte.
Les objectifs sont des hypothèses de sortie, pas des prédictions de cours.

Stops : bougies 1m en live, 15m en historique. Si stop et cible touchent,
stop prioritaire. Gap sous stop : ouverture puis slippage. Trailing recalculé
après clôture, jamais appliqué rétroactivement au plus bas de la même bougie.
OHLC = prix échangés, pas historique bid/ask. Aucun carnet, remplissage partiel
ou latence réelle reconstitué. Minute d'entrée live exclue car elle contient
des prix antérieurs ; une sortie dans cette minute peut être manquée.

Kraken limite l'historique à 720 bougies. Trou dans le suivi ⇒ suspension
permanente et DATA_GAP, sorties toujours suivies sur données disponibles,
mais rendement incomplet. Les données invalides/manquantes interrompent le run.
Les gardes d'équité et le drawdown utilisent les observations aux passages,
pas tous les ticks : un creux entre passages peut ne pas être mesuré.
Corrélation historique ≠ protection garantie. Les positions restent au comptant.

Historique : Binance n'est pas Kraken. Spread supposé ~0,15 % total, frais
Kraken simulés, volume 24h approximé par somme prix×volume. Minimums historiques
inconnus : seuil 5 € et 8 décimales. Actifs sélectionnés aujourd'hui : biais de
sélection/survie. Changement de place, granularité 15m et absence de délais
réels empêchent de traiter le test comme une preuve d'exécutabilité sur Kraken.

`state/portfolio.json` est la source de vérité, remplacée atomiquement localement
puis committée. Push échoué : prochain run depuis le dernier état distant.
Surveiller les erreurs, droits/protections de branche ; ne pas modifier la
branche pendant un run. Une exécution live à la fois. Historique Git croissant :
archiver l'expérience périodiquement. Configuration figée par hash : utiliser
un nouveau dépôt pour changer les paramètres et éviter de mélanger les tests.

## Sources primaires

- https://docs.kraken.com/api-reference/market-data/get-ohlc-data
- https://docs.kraken.com/api-reference/market-data/get-tradable-asset-pairs
- https://docs.kraken.com/api-reference/market-data/get-ticker-information
- https://github.com/binance/binance-public-data
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

## Commandes locales facultatives

```bash
python3 -m unittest discover -v
python3 run.py --demo
python3 history.py --months 2026-06 2026-07 2026-08
python3 backtest.py --folds 3
python3 backtest.py --folds 3 --stress-costs
```

La démo est synthétique : aucun réseau ni état persisté. Voir VALIDATION.md.
