# Noeon Engine

Noeon est un moteur headless d’ingénierie logicielle autonome. Il expose des contrats Python, une orchestration de missions et une couche d’exécution, sans frontend, site web ni tableau de bord.

## Positionnement

Noeon compose deux briques externes sans modifier leurs dépôts : DeerFlow fournit le rôle d’orchestrateur/harness (planification, sous-agents, mémoire, skills et sandbox) et OpenHands Software Agent SDK fournit l’exécution orientée code (conversation, outils fichiers/terminal, workspace et Agent Server). La couche Noeon conserve une frontière explicite entre ces responsabilités et échoue clairement lorsqu’une intégration n’est pas installée.

## Installation

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev,openhands]'
pytest
```

Pour charger DeerFlow depuis un checkout local :

```bash
export NOEON_DEERFLOW_BACKEND=/path/to/deer-flow/backend/packages/harness
export NOEON_OPENHANDS_SDK=/path/to/software-agent-sdk/openhands-sdk
export NOEON_MODEL=openai/gpt-4o-mini
noeon 'Inspect the repository, implement the requested change, and run its tests.' --workspace /path/to/repo
```

Les clés et endpoints des fournisseurs sont volontairement gérés par l’environnement de l’opérateur. Noeon ne les écrit pas dans les fichiers de mission.

## Architecture

- `src/noeon/contracts.py` : missions, événements et résultats versionnables.
- `src/noeon/orchestrator.py` : cycle analyser → planifier → exécuter → tester → vérifier.
- `src/noeon/integrations.py` : chargement contrôlé des points d’entrée DeerFlow/OpenHands et routage de modèle.
- `src/noeon/execution.py` : exécution bornée en workspace ; la production doit utiliser un conteneur ou un runtime isolé.
- `tests/` : tests locaux reproductibles, indépendants d’un LLM.

La première version ne prétend pas fournir une isolation Docker complète, une mémoire distribuée, un Agent Server Noeon ou des benchmarks comparatifs. Ces éléments sont des étapes suivantes et sont suivis dans `docs/ROADMAP.md`.

## Exécution sans interface

```bash
python -m noeon.cli 'Run the repository test suite and explain failures' --workspace .
```

Une mission réussie doit produire un résultat vérifié. Une dépendance manquante ou une erreur d’exécution produit un statut `failed`; aucune réussite n’est simulée.

## Sources auditées

Voir [`docs/AUDIT.md`](docs/AUDIT.md) pour les commits audités, les limites d’intégration et les références officielles.
