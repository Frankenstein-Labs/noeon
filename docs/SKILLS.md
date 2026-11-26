# Noeon Skill Universe

Le catalogue de compétences de Noeon découple quatre choses que les catalogues de
skills confondent souvent : **découvrir**, **importer**, **valider** et **exécuter**.

Un skill `discovered` existe dans une source auditée. Un skill `imported` a son
contenu téléchargé, haché et indexé. Un skill `validated` a passé le validateur et
le scanner de sécurité. Un skill `installed` peut être chargé et, s'il le déclare,
exécuté par le `SkillExecutor`. Aucun skill n'est compté comme exécutable sans
contenu réel et sans contrôle.

## Sources et licences

[`catalog/sources.toml`](../catalog/sources.toml) est la liste blanche auditée.

- `mode = "import"` : MIT, Apache-2.0 ou BSD. Le contenu est téléchargé au commit
  épinglé, haché (SHA-256), scanné, puis indexé.
- `mode = "reference"` : la source est auditée et son nombre de `SKILL.md` est
  enregistré, mais le contenu n'est pas copié. C'est le cas des licences absentes,
  copyleft (AGPL) ou des agrégateurs dont la provenance par skill est incertaine.

[`catalog/sources.lock.json`](../catalog/sources.lock.json) enregistre le commit
réellement utilisé et les compteurs par source.
L'index complet (`catalog/registry.jsonl.gz`, une ligne JSON par skill importé)
est généré localement, compressé de façon déterministe et ignoré par Git : le
dépôt ne redistribue aucune ligne de contenu tiers. Son SHA-256 et sa taille sont
inscrits dans `sources.lock.json`, ce qui rend l'état épinglé vérifiable.

Les fichiers de skills eux-mêmes ne sont pas versionnés : ils sont récupérés à
l'installation, vérifiés par hash et mis en cache dans `.noeon/skills/`. Cela évite
de redistribuer des contenus tiers dans ce dépôt.

## Architecture

| Module | Rôle |
| --- | --- |
| `skills/model.py` | `SkillRecord`, statuts, identifiants dérivés de la provenance |
| `skills/frontmatter.py` | frontmatter YAML strict, avec limites de taille |
| `skills/manifest.py` | construction d'un enregistrement depuis un `SKILL.md` |
| `skills/taxonomy.py` | 16 catégories, tags par mots-clés, profils de rôles |
| `skills/validate.py` | validation structurelle et licence normalisée |
| `skills/security.py` | scanner statique : injection, exfiltration, scripts dangereux |
| `skills/registry.py` | SQLite + FTS5, recherche BM25, historique d'audit, affectations |
| `skills/sources.py` | client GitHub en lecture seule, arbres et contenus épinglés |
| `skills/sync.py` | découverte, import, doublons, installation, vérification |
| `skills/discovery.py` | sélection par rôle, score lexical, embeddings optionnels |
| `skills/loader.py` | chargement sous budget de tokens |
| `skills/agents.py` | affectation par agent, prêt et emprunt de compétences |
| `skills/tools.py` | registre d'outils avec sondes réelles |
| `skills/dependencies.py` | vérification des dépendances, plan d'installation non exécuté |
| `skills/mcp.py` | validation des serveurs MCP, aucune connexion automatique |
| `skills/evaluation.py` | score qualité déterministe, 0-100 |
| `skills/executor.py` | exécution confinée des scripts déclarés |
| `skills/learning.py` | brouillon de skill depuis une mission, quarantaine puis test |
| `skills/runtime.py` | façade `SkillUniverse` et plan de mission multi-rôles |

## Utilisation

```bash
pip install -e '.[dev]'
python -m noeon.skills.cli sync            # importe les sources de catalog/sources.toml
python -m noeon.skills.cli import-local catalog/core --repository noeon/core \
  --license proprietary                   # skills internes, scripts inclus
python -m noeon.skills.cli load catalog/registry.jsonl.gz   # index sans réseau
python -m noeon.skills.cli stats
python -m noeon.skills.cli search "postgres migration" --role database
python -m noeon.skills.cli plan "Créer une API FastAPI avec tests et déploiement"
python -m noeon.skills.cli install <skill-id>
python -m noeon.skills.cli verify <skill-id>
```

Le CLI `noeon-skills` est aussi installé comme point d'entrée.

## État livré

Le catalogue contient 2 064 skills importés depuis 13 sources épinglées :
1 997 valides, 33 bloqués par le scanner, 86 en revue, 54 doublons signalés.
535 déclarent des scripts, 101 des dépendances, et 16 catégories sont couvertes.
Quatre skills internes (`catalog/core`) sont importés localement et deux d'entre
eux, `repo-inventory` et `test-report`, s'installent et s'exécutent réellement.

## Sélection pour une mission

`plan_mission` choisit les rôles à partir de la demande (architecte et QA toujours
présents, puis design, frontend, backend, base de données, DevOps, sécurité,
recherche, IA, mobile, documentation selon les mots-clés réels de la mission).

Chaque rôle reçoit au plus `RoleProfile.max_skills` skills, chargés sous un budget
de tokens. Le contexte n'est jamais la totalité du catalogue : les skills non
chargés apparaissent en index court. Le plan est écrit dans `.noeon/skills-plan.json`
et enregistré dans le registre avec les scores et les raisons de sélection.

## Sécurité

Le scanner combine des règles statiques (pipe vers shell, exfiltration de secrets,
persistance SSH, `sudo`, `eval`, caractères invisibles, consignes d'injection) et
un contrôle des scripts au moment de l'installation et de l'exécution.

- `BLOCK` : installation refusée. Aucun contournement automatique.
- `REVIEW` : installable, mais signalé et pénalisé dans le score de sélection.
- Licence inconnue : installation refusée sauf `--force` explicite de l'opérateur.

L'exécuteur est fermé par défaut : il faut `ExecutionPolicy(allow_execution=True)`,
un skill `installed`, la permission `execute`, un script sous `scripts/`, et un scan
du script sans constat élevé. L'environnement est reconstruit à partir d'une liste
blanche (`NOEON_EXEC_ENV_ALLOWLIST`), `HOME` pointe vers le workspace, le timeout et
la mémoire sont bornés, et aucun secret global n'est hérité. Le mode `docker` existe
(`--network none`) mais n'est pas le mode par défaut.

Les skills générés par Noeon restent en quarantaine (`approval: pending`) jusqu'à
ce qu'une commande de vérification réelle réussisse en subprocess.

## Limites assumées

- La recherche sémantique nécessite un fournisseur d'embeddings fourni par
  l'opérateur. Sans lui, seule la recherche lexicale BM25 est utilisée et le CLI
  l'indique (`semantic_available: false`).
- L'exécution locale n'est pas une frontière de sécurité pour un hôte partagé.
  Le mode Docker est fourni mais n'est pas validé sur toutes les plateformes.
- Un skill `REVIEW` reste utilisable pour un agent, mais son score est réduit.
  Une politique stricte peut filtrer `security_status != "allow"`.
- L'import dépend du réseau et de l'API GitHub ; le cache et les commits épinglés
  rendent les imports reproductibles.
