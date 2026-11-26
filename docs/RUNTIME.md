# Runtime partagé Noeon

## Concurrence

`ConcurrencyManager` maintient une file prioritaire et un nombre fixe de workers asyncio. Soumettre 1 000 ou 100 000 tâches ne crée pas autant de processus ni de threads : les tâches restent des entrées légères en attente, puis sont exécutées par les workers disponibles. `per_agent_limit` empêche un agent de monopoliser le runtime. Chaque tâche peut définir une priorité, un timeout et un nombre de retries.

```python
async with ConcurrencyManager(max_workers=64, per_agent_limit=4) as runtime:
    future = await runtime.submit(AgentTask(
        run=lambda: run_specialist_mission(),
        agent_id="backend-42",
        priority=10,
        max_retries=2,
    ))
    result = await future
```

La capacité à traiter des milliers de sous-agents dépend ensuite du coût de chaque conversation, du fournisseur de modèles et des limites du sandbox. Le scheduler ne promet pas une exécution illimitée : il applique une capacité et une file bornées.

## Mémoire partagée

`SharedMemory` utilise SQLite en mode WAL et stocke des documents JSON. Les écritures concurrentes doivent fournir `expected_version` lorsqu’elles reposent sur une lecture antérieure. Une divergence lève `MemoryConflict`, afin que l’agent puisse relire, fusionner et réessayer au lieu d’écraser silencieusement le travail d’un autre agent.

```python
memory = SharedMemory(".noeon/memory.sqlite3")
entry = await memory.put("mission/123", "architecture", plan)
updated = await memory.put(
    "mission/123", "architecture", revised_plan,
    expected_version=entry.version,
)
```

Les scopes limitent les namespaces accessibles et peuvent être en lecture seule. Les événements `put` et `delete` sont conservés pour l’audit et la reconstruction d’un contexte partagé. Les secrets ne doivent pas être écrits dans cette mémoire ; ils doivent rester dans le gestionnaire de secrets de l’environnement d’exécution.
