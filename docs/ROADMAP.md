# Roadmap Noeon

## Livré : Skill Universe v1

- Catalogue multi-sources audité, licences et commits épinglés, index SQLite FTS5
  exportable de façon déterministe en `catalog/registry.jsonl.gz` (non versionné,
  hash inscrit dans `catalog/sources.lock.json`).
- Validation structurelle, score qualité, scanner de sécurité statique avec
  décisions `allow` / `review` / `block`.
- Découverte par rôle, chargement sous budget de tokens, affectation par agent,
  prêt et emprunt de compétences.
- Exécuteur de scripts confiné et désactivé par défaut, vérification de hash,
  registre d’outils avec sondes réelles, gestion MCP sans connexion automatique.
- Apprentissage : brouillon de skill depuis une mission, quarantaine, test réel
  avant approbation.
- Orchestrateur : plan de skills par mission, contexte injecté, journal
  `.noeon/skills-plan.json`, vérification des changements par Git.

## Prochaine tranche

1. Ajouter un service Agent Server headless avec streaming d’événements.
2. Remplacer l’exécuteur local par un provider Docker avec allowlist de commandes et quotas.
3. Persister sessions, événements et checkpoints dans SQLite puis PostgreSQL.
4. Brancher les vrais sous-agents DeerFlow sur des rôles spécialisés avec permissions par outil.
5. Ajouter des missions fixtures et un protocole de benchmark reproductible.
6. Ajouter des tests d’intégration avec OpenHands et DeerFlow épinglés par commit.
7. Étendre le catalogue : activer des sources `reference` après audit de licence
   et de provenance, et ajouter des sources MCP vérifiées.
8. Exécution Docker par défaut pour les scripts de skills, avec quotas et journaux.
9. Embeddings optionnels fournis par l’opérateur pour la recherche sémantique.

## Critères de sortie de la prochaine tranche

Une mission de fixture devra créer/modifier un fichier dans un dépôt temporaire, exécuter sa suite de tests, corriger une erreur introduite volontairement et produire un journal d’événements complet. Les erreurs d’authentification, de quota, de timeout et de sécurité devront être distinguées des erreurs de code.
