# Simulation BTC/EUR — 50 € virtuels

Exécution GitHub Actions toutes les 15 minutes environ, sans Mac allumé.
Par défaut : stratégie technique gratuite (EMA20/50 1h, EMA20 15m), une position
au comptant, 20 € maximum par achat, stop 3 %, cible 10 %. Frais simulés 0,4 %
par côté, slippage 0,05 % par côté. Pas de promesse de rendement.

## Installation sur Mac

1. Créer un dépôt PUBLIC `paper-trader` sur GitHub avec README.
2. Décompresser ce ZIP. Dans Terminal, se placer dans le dossier extrait.
3. Remplacer TON_PSEUDO puis exécuter :

```bash
git clone https://github.com/TON_PSEUDO/paper-trader.git destination
cp paper_trader.py scheduled.py README.md .gitignore destination/
mkdir -p destination/.github/workflows
cp .github/workflows/paper.yml destination/.github/workflows/
cd destination
git add .
git commit -m 'Install paper simulation'
git push
```

Si Git demande un mot de passe, le mot de passe du compte GitHub ne fonctionne
pas pour Git HTTPS. Utiliser GitHub CLI (`gh auth login`) ou un jeton personnel
avec accès Contents et Workflows au dépôt ; ne jamais placer le jeton dans le code.
Sur Mac, `.github` est caché : Cmd+Maj+. l'affiche dans Finder.

4. Dépôt → Settings → Actions → General → Workflow permissions :
   Read and write permissions → Save.
5. Actions → Paper trader → Run workflow → Run workflow.
6. Après un lancement réussi, ouvrir `state/REPORT.md`, puis les rapports des
   exécutions dans Actions. Le planning ne fonctionne que sur la branche par défaut.
7. Arrêter : Actions → Paper trader → menu … → Disable workflow.

## Mode OpenAI optionnel (API payante)

Settings → Secrets and variables → Actions → Secrets → New repository secret :
`OPENAI_API_KEY`. Ne jamais partager la clé ou la committer.
Dans Variables : `AGENT_MODE=openai`, `OPENAI_MODEL` = modèle disponible sur ton
compte et compatible Responses + JSON Schema. Le modèle par défaut doit être
vérifié avec ton compte. Pour changer de stratégie après un premier lancement,
créer un dépôt séparé, afin de garder des résultats comparables sans mélange.
Aucun compte de plateforme de trading ou identifiant d'exchange n'est nécessaire.
Les frais OpenAI ne sont pas déduits du portefeuille virtuel ; les jetons utilisés
sont comptabilisés. ChatGPT Plus ne couvre pas ces appels.

## Limites de la mesure

GitHub peut retarder ou omettre un passage. Le programme traite les bougies 1m
clôturées depuis son dernier contrôle. Les décisions nouvelles sont prises au
prix observé au passage, jamais rétroactivement sur une bougie manquée.
Pour les sorties, le prix OHLC est un proxy du prix échangé, pas un historique du
bid/ask. Si cible et stop touchent dans la même minute, le stop est retenu.
Un gap d'ouverture sous le stop utilise l'ouverture puis le slippage.
La minute d'entrée n'est pas reconstruite car elle contient des prix antérieurs
à l'entrée ; un mouvement à l'intérieur de cette minute peut être manqué.
Kraken retourne au plus 720 bougies : absence de couverture historique ⇒
suspension des nouvelles entrées et événement DATA_GAP ; la position reste
suivie aux prix disponibles, mais le rendement n'est plus une reconstruction complète.
Le programme ne mesure pas la profondeur, les remplissages partiels, les latences
réelles ni tous les effets du spread. Drawdown : valeurs observées aux passages.
Seuil de suspension : capital marqué ≤40 € ou perte ≥3 € depuis le premier
passage UTC du jour. Suspension persistante, sorties toujours possibles.

Le code, le portefeuille virtuel et les rapports sont publics. Le fichier SQLite
est committé à chaque passage (historique Git croissant). Une transaction est
préparée sur copie puis publiée seulement si l'exécution Python réussit. Si le
push Git échoue, la prochaine exécution repart du dernier état sauvegardé :
vérifier les erreurs Actions, particulièrement les permissions de branche.
Pas d'ordre réel. Ce projet n'est pas un service de trading en production.

## Vérification locale hors réseau

```bash
python3 -m unittest test_scheduled.py
```
