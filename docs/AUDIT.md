# Audit technique initial — Noeon

## Constat

L’audit a été réalisé sur les checkouts officiels suivants :

- DeerFlow : commit `f8cde989d9b2cf57eb782c49354e295bedd0d77e`, version backend `2.3.0-dev`.
- OpenHands Software Agent SDK : commit `e0ed3c00121e813c5cf98c792ed764d16d8af3e9`, version SDK `1.64.1`.

Les deux dépôts déclarent la licence MIT. Noeon ne copie pas leur code et conserve les liens, noms et attributions dans ce document.

## Découpage retenu

DeerFlow 2.0 est un harness LangGraph/LangChain. Son architecture publiée sépare le harness de l’application et expose notamment `make_lead_agent`, les sous-agents, la mémoire, les skills et les providers de sandbox. La frontière Noeon se branche sur ce factory au moyen de `NOEON_DEERFLOW_BACKEND`.

OpenHands SDK est une bibliothèque Python et un Agent Server orientés ingénierie logicielle. Il expose notamment `Agent`, `Conversation`, `LLM`, des outils de fichiers/terminal et des workspaces. Noeon le charge au moyen de `NOEON_OPENHANDS_SDK` ou du paquet optionnel `openhands-sdk`.

Cette approche évite de dupliquer les moteurs et permet de faire évoluer les versions indépendamment. Elle signifie aussi qu’une installation minimale Noeon ne peut pas exécuter une mission LLM : elle peut uniquement valider les contrats, le plan et la sandbox locale.

## Risques identifiés

La sandbox locale est réservée au développement et n’est pas une frontière de sécurité suffisante pour un hôte partagé. Le déploiement de production devra fournir un runtime isolé, des limites CPU/mémoire/processus, une politique de secrets et un arrêt d’urgence. Les modèles n’ont pas tous les mêmes capacités : le routeur reste donc abstrait et la configuration du fournisseur appartient à l’opérateur.

L’intégration actuelle vérifie l’espace de travail via `git status --short`. Elle ne déclare pas encore une mission complète réussie sans OpenHands réellement installé et configuré. Les benchmarks comparatifs sont volontairement absents tant qu’un protocole reproductible n’est pas défini.

## Références

[1]: https://github.com/bytedance/deer-flow "Dépôt officiel DeerFlow"
[2]: https://github.com/OpenHands/software-agent-sdk "Dépôt officiel OpenHands Software Agent SDK"
[3]: https://docs.openhands.dev/sdk "Documentation officielle OpenHands Software Agent SDK"
[4]: https://github.com/bytedance/deer-flow/blob/main/docs/ARCHITECTURE.md "Architecture DeerFlow"
