# Le Pupitre — l'interface du Chef d'Orchestre, chiffrée par conception

> Le chef d'orchestre le plus génial ne sauvera pas une partition nulle.
> Le Pupitre est notre partition : une petite fenêtre de chat **à nous**,
> **multi-plateforme** (Windows / macOS / Linux), où le chiffrement de
> l'historique n'est pas une option rajoutée mais **la première note**.

## Pourquoi une interface maison plutôt qu'un fork

Une étude vérifiée (12 interfaces auditées à la source, 12-13/06/2026) a montré
deux choses :

1. **Aucune** interface de chat mature pour poste de travail ne chiffre
   l'historique des conversations au repos par défaut (les grandes ne chiffrent,
   au mieux, que les clés d'API).
2. **Forker un géant pour ajouter ce chiffrement est un piège** : des
   développeurs confirmés ont essayé sur LibreChat et abandonné (le
   rafraîchissement de l'écran cassait le chiffrement du flux ; PR #5906
   fermée). Maintenir un fork de 22 Mo qui bouge tous les jours, à deux, c'est
   descendre un escalator qui monte.

La bonne échelle n'est donc pas de réécrire un orchestre, mais d'écrire une
**petite** partition que l'on maîtrise entièrement : quelques centaines de
lignes, relues en entier, chiffrées par conception. En contexte réglementé,
pouvoir **prouver** ce que fait son appli vaut plus que mille fonctions.

## Architecture (simple par sécurité)

```
  Navigateur (page web locale)
        │  http://localhost:8800   (jamais exposé au réseau)
        ▼
  serveur.py  ──►  coffre.py   (historique CHIFFRÉ, SQLCipher / AES-256)
        │
        └────────►  relais.py  ──►  Chef d'Orchestre (LiteLLM, localhost:4000)
                                         puis local / cloud / armoire
```

- **`coffre.py`** : le stockage chiffré. La base (conversations + messages) est
  chiffrée au repos par **SQLCipher** (le moteur de Signal). La passphrase est
  donnée **au lancement**, jamais stockée. Sans elle, le fichier `.db` est
  illisible. *Fail-closed* : en production, si SQLCipher est absent, le coffre
  **refuse de s'ouvrir** plutôt que de stocker en clair.
- **`relais.py`** : le Pupitre ne connaît qu'**une** adresse, celle du routeur
  local. Il ne parle jamais directement à un cloud. C'est le Chef d'Orchestre
  qui décide (local / cloud / méthode de l'armoire) et caviarde. Le Pupitre
  reste « bête » par conception — c'est ce qui le rend sûr.
- **`serveur.py`** : la petite appli web (FastAPI) qui relie le tout et sert la
  page. N'écoute que sur `127.0.0.1`.
- **`static/`** : la page (HTML/CSS/JS pur, **aucune étape de build**,
  auditable en entier).

## Multi-plateforme

C'est du **Python + un navigateur** : la même commande lance le Pupitre sur les
trois systèmes. Le chiffrement est multi-plateforme grâce à `sqlcipher3-wheels`,
qui fournit des binaires prêts (pip, sans compilation) pour Windows, macOS et
Linux.

## Installation et lancement (sur la machine cible)

```bash
# macOS / Linux
./install/install.sh
./start.sh

# Windows (PowerShell)
.\install\install.ps1
.\start.ps1
```

Au lancement, la **passphrase** du coffre est demandée au terminal (ou lue dans
`CHEF_PUPITRE_PASSPHRASE`). Puis on ouvre **http://localhost:8800**.

### Réglages (variables d'environnement)

| Variable | Rôle | Défaut |
|---|---|---|
| `CHEF_PUPITRE_PASSPHRASE` | passphrase du coffre (sinon saisie au terminal) | — |
| `CHEF_PUPITRE_BASE_URL` | adresse du Chef d'Orchestre | `http://localhost:4000` |
| `CHEF_PUPITRE_CLE` | master key du routeur | vide |
| `CHEF_PUPITRE_MODELE` | route demandée au routeur | `chef-auto` |
| `CHEF_PUPITRE_DB` | chemin du coffre | `pupitre.db` |
| `CHEF_PUPITRE_PORT` | port du serveur | `8800` |
| `CHEF_PUPITRE_EXIGER_CHIFFREMENT` | `0` = autorise le mode clair (dev) | `1` |

## Le socle indispensable : chiffrer le disque

Le Pupitre chiffre **son** historique. Mais un poste professionnel doit de toute
façon **chiffrer le disque entier** (BitLocker / FileVault / LUKS) : ça couvre
aussi le swap, les sauvegardes, les fichiers temporaires. C'est l'exigence RGPD
centrale (art. 32, chiffrement au repos) et c'est gratuit. Honnêteté : le
chiffrement (Pupitre ou disque) protège contre le **vol/la perte** du matériel,
pas contre un administrateur sur une machine **allumée** (données déchiffrées en
mémoire).

## Prouver le chiffrement au déploiement (à faire le jour J)

Le code est testé en pur Python ici (`python test_pupitre.py`, **12 tests**),
mais cela prouve la *logique* de stockage en mode développement. La preuve du
chiffrement **réel** se fait sur la machine cible, une fois SQLCipher installé,
en 3 gestes :

1. lancer le Pupitre avec une passphrase, écrire un message, fermer ;
2. tenter d'ouvrir `pupitre.db` avec un lecteur SQLite ordinaire **ou** avec une
   **mauvaise** passphrase → ce doit être illisible (« file is not a
   database ») ;
3. ré-ouvrir avec la **bonne** passphrase → l'historique revient.

Tant que ce test n'est pas passé sur la machine cible, on ne dit pas « c'est
chiffré » — on dit « c'est prêt à l'être ».

## Ce que la v1 ne fait PAS (franchise)

Pas de RAG/upload de documents, pas de multi-utilisateurs, pas de streaming mot
à mot (la route « méthode de l'armoire » exige de toute façon la réponse
complète), pas de génération d'images. C'est un **chat confidentiel** simple et
solide. Le reste viendra si le besoin est réel — sans jamais sacrifier la
première note : le chiffrement.
