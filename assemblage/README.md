# Le kit d'assemblage : tout l'orchestre en une commande

Ce dossier monte les trois pièces ensemble : **Ollama** (le moteur local),
**le Chef d'Orchestre** (la serrure/routeur) et **Le Pupitre** (l'interface
chiffrée). C'est ce qui rend l'ensemble *réellement lançable et démontrable*.

> **Statut : prêt à lancer, PAS encore testé en vrai.** Comme le kit
> `rideau-presidio/`, les recettes Docker sont écrites et validées sur le
> papier ; le premier `docker compose up` se fait sur la machine cible. Rien
> n'est installé sur le PC de développement.

## Ce que ça lance

```
  Navigateur ──► 127.0.0.1:8800 ──► Le Pupitre (coffre chiffré, RAG local)
                                          │
                                          ▼
                                   Chef d'Orchestre (LiteLLM + serrure)
                                     │                    │
                                     ▼ (local)            ▼ (cloud, si anodin)
                                   Ollama               Anthropic
                              (chat + embeddings)
```

**Cloisonnement réseau** : seul Le Pupitre est exposé, et seulement sur
`127.0.0.1`. Ollama et le routeur ne sont joignables qu'entre conteneurs :
aucune porte ouverte vers l'extérieur.

## Lancer (sur la machine cible)

1. **Pré-requis** : Docker + Docker Compose installés.
2. **Configurer** :
   ```bash
   cd assemblage
   cp .env.example .env      # remplir LITELLM_MASTER_KEY et CHEF_PUPITRE_PASSPHRASE
   ```
3. **Démarrer** :
   ```bash
   docker compose up -d --build
   ```
4. **Charger les modèles locaux** (une seule fois, dans Ollama) :
   ```bash
   docker compose exec ollama ollama pull qwen3:4b
   docker compose exec ollama ollama pull nomic-embed-text
   ```
   (`qwen3:4b` = le cerveau local ; `nomic-embed-text` = l'embedding du RAG.)
5. **Ouvrir** : http://localhost:8800

## Le socle, encore et toujours

Le coffre du Pupitre **et** le corpus RAG sont chiffrés. Mais sur un poste de
cabinet, **chiffrer le disque hôte** (BitLocker / LUKS) reste la première
mesure : c'est ce qui protège le fichier `.env` (qui contient la passphrase
dans ce kit Docker), les volumes et tout le reste, en cas de vol.

## Prouver que ça marche (le jour du test réel)

1. **Routage** : poser une question anodine → réponse locale (ou cloud si une
   clé Anthropic est mise et la tâche lourde). Poser une question avec un faux
   IBAN vers le cloud → **refus fail-closed**.
2. **RAG local** : déposer un document (📎), cocher « 📚 Mes documents », poser
   une question dessus → la réponse cite l'extrait, **sans aucun appel externe**
   (vérifiable au pare-feu : l'embedding part vers `ollama`, jamais dehors).
3. **Chiffrement** : arrêter le kit, inspecter le volume `pupitre` → la base
   est illisible sans la passphrase (cf. `le-pupitre/README.md`).

## Points à ajuster au déploiement (franchise)

- Le tag de l'image LiteLLM (`ghcr.io/berriai/litellm:main-stable`) et le
  comportement exact de son entrypoint sont à confirmer sur la machine cible
  (l'API LiteLLM évolue vite). Le `CMD` du `Dockerfile.routeur` part de l'usage
  standard ; à vérifier au premier `up`.
- La passphrase dans `.env` est un compromis du format Docker. Option durcie :
  **docker secrets** (ou lancer Le Pupitre hors Docker pour une saisie au
  terminal). À trancher selon le niveau d'exigence du cabinet.
- La loupe (GLiNER/Presidio) n'est pas incluse dans l'image du routeur pour
  rester légère : la serrure regex + la vigie tournent. Pour l'ajouter, voir le
  README du Chef d'Orchestre (`--fine` / `--fine-double`).
