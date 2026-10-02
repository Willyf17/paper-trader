# Validation de livraison

16 tests automatisés passent : priorité du stop, gap sous stop, trailing différé,
exclusion pré-entrée, trou historique, doublon, agrégation 1h, OHLC invalides et
manquants, drawdown, pause quotidienne, sizing avec coûts, minimum d'ordre,
bougie répétée, corrélation et entrée historique à l'ouverture suivante.
Compilation Python et démo synthétique du runner vérifiées.

L'accès Kraken a échoué dans l'environnement de création (réponse non JSON).
Aucun rendement réel ou historique mesuré, aucun entraînement ni gain démontré.
Workflows non déployés par cette livraison : à lancer sur GitHub pour valider
la connectivité, les métadonnées actuelles et la disponibilité des archives.
Les tests vérifient des propriétés du simulateur, pas un avantage de marché.
