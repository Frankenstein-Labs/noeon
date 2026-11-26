# Roadmap Noeon

## Prochaine tranche

1. Ajouter un service Agent Server headless avec streaming d’événements.
2. Remplacer l’exécuteur local par un provider Docker avec allowlist de commandes et quotas.
3. Persister sessions, événements et checkpoints dans SQLite puis PostgreSQL.
4. Brancher les vrais sous-agents DeerFlow sur des rôles spécialisés avec permissions par outil.
5. Ajouter des missions fixtures et un protocole de benchmark reproductible.
6. Ajouter des tests d’intégration avec OpenHands et DeerFlow épinglés par commit.

## Critères de sortie de la prochaine tranche

Une mission de fixture devra créer/modifier un fichier dans un dépôt temporaire, exécuter sa suite de tests, corriger une erreur introduite volontairement et produire un journal d’événements complet. Les erreurs d’authentification, de quota, de timeout et de sécurité devront être distinguées des erreurs de code.
