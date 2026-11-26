# Noeon Engine

Noeon est un moteur headless d’ingénierie logicielle autonome. Il expose des contrats Python, une orchestration de missions et une couche d’exécution, sans frontend, site web ni tableau de bord.

Le dépôt contient maintenant les sources réelles auditées de DeerFlow et de l’OpenHands Software Agent SDK dans `vendor/`. DeerFlow est conservé sans son frontend upstream afin que Noeon reste headless ; son backend, son harness, ses skills et ses tests sont présents. Les sources exactes et leurs commits sont décrits dans [`vendor/UPSTREAM_SOURCES.md`](vendor/UPSTREAM_SOURCES.md).

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

## Skill Universe

Noeon dispose d'un catalogue de compétences importées de sources open source
auditées, avec provenance, licence, hash et statut de sécurité. Le catalogue ne
charge jamais tout le corpus dans le contexte : il sélectionne les compétences
utiles à une mission, par rôle, sous budget de tokens.

```bash
python -m noeon.skills.cli sync
python -m noeon.skills.cli stats
python -m noeon.skills.cli plan "Créer une API FastAPI avec tests"
python -m noeon.skills.cli search "design system" --role designer
```

Voir [`docs/SKILLS.md`](docs/SKILLS.md) pour l'architecture, les règles de licence,
le scanner de sécurité et les limites. Les sources auditées sont dans
[`catalog/sources.toml`](catalog/sources.toml), le commit et les compteurs réels
dans [`catalog/sources.lock.json`](catalog/sources.lock.json).

## Architecture

- `src/noeon/contracts.py` : missions, événements et résultats versionnables.
- `src/noeon/orchestrator.py` : cycle analyser → planifier → exécuter → tester → vérifier.
- `src/noeon/integrations.py` : chargement contrôlé des points d’entrée DeerFlow/OpenHands et routage de modèle.
- `src/noeon/execution.py` : exécution bornée en workspace ; la production doit utiliser un conteneur ou un runtime isolé.
- `tests/` : tests locaux reproductibles, indépendants d’un LLM.
- `src/noeon/agents.py` : registre de rôles et skills avec capacité configurable jusqu’à 1 000 agents dans cette tranche.
- `src/noeon/concurrency.py` et `src/noeon/memory.py` : runtime borné et mémoire partagée persistante, décrits dans [`docs/RUNTIME.md`](docs/RUNTIME.md).
- `src/noeon/skills/` : catalogue, découverte, validation, sécurité, exécution et apprentissage, décrits dans [`docs/SKILLS.md`](docs/SKILLS.md).

La première version ne prétend pas encore fournir une isolation Docker complète, une mémoire distribuée, un Agent Server Noeon ou une exécution réellement validée de milliers d’agents concurrents. Ces éléments sont des étapes suivantes et sont suivis dans `docs/ROADMAP.md`.

## Exécution sans interface

```bash
python -m noeon.cli 'Run the repository test suite and explain failures' --workspace .
```

Une mission réussie doit produire un résultat vérifié. Une dépendance manquante ou une erreur d’exécution produit un statut `failed`; aucune réussite n’est simulée.

## Sources auditées

Voir [`docs/AUDIT.md`](docs/AUDIT.md) pour les commits audités, les limites d’intégration et les références officielles.
