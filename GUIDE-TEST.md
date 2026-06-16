# Guide de test pas a pas

Ce guide est fait pour etre suivi sans etre developpeur. Objectif : installer
Le Chef d'Orchestre, le faire tourner, et surtout voir de vos yeux la preuve
qui compte : une donnee sensible ne part JAMAIS au cloud, meme quand le modele
local tombe en panne.

Comptez 10 a 15 minutes la premiere fois (le telechargement du modele prend le
plus gros du temps).

## Avant de commencer

- Un PC Windows, macOS ou Linux. Pas besoin de carte graphique : ca tourne aussi
  sur le processeur, juste un peu plus lentement.
- Environ 3 Go d'espace disque libre (pour le modele local `qwen3:4b`).
- Une connexion internet pour le premier telechargement seulement. Ensuite, tout
  marche hors-ligne.
- Aucune cle, aucun compte cloud n'est necessaire pour tester la partie locale.

## Etape 1 : installer

### Le plus simple (Windows)

Ouvrez PowerShell et collez :

```powershell
git clone https://github.com/chabanade/chef-orchestre-public
cd chef-orchestre-public\installeur\windows
.\lanceur.ps1
```

Ce que l'installeur fait tout seul, en vous tenant au courant :

1. Il verifie et installe si besoin Ollama (le moteur local) et Python.
2. Il regarde votre materiel. Si vous avez une carte graphique, il l'essaie
   pour de vrai. Si elle est bridee par un pilote trop ancien, il vous PROPOSE
   la mise a jour : vous acceptez ou vous refusez, c'est vous qui decidez.
3. Il lance un court banc d'essai pour garder le modele le plus gros qui reste
   rapide sur votre machine.
4. Il cree une icone "Le Pupitre" sur le Bureau et ouvre l'interface.

### En ligne de commande (Linux, macOS, Windows)

```bash
git clone https://github.com/chabanade/chef-orchestre-public
cd chef-orchestre-public
cp .env.example .env        # rien d'obligatoire a remplir pour un test local
bash install/install.sh     # installe Ollama + le modele + LiteLLM
bash start.sh               # demarre le routeur sur le port 4000
```

Sous Windows en ligne de commande : `install\install.ps1` puis `start.ps1`.

## Etape 2 : la demonstration automatique

C'est le moyen le plus rapide de voir le comportement. Depuis le dossier du
projet :

```bash
python demo.py
```

Vous verrez defiler :

- **Une question anodine simple** part en LOCAL (par economie).
- **Une question avec un faux IBAN** est FORCEE en local, avec le motif ecrit
  dans le journal.
- **Une tache lourde mais anodine** est aiguillee vers le cloud (uniquement si
  vous avez renseigne une cle cloud dans `.env` ; sinon cette route reste
  dormante, c'est normal).

## Etape 3 : LE test qui compte devant un juriste (le fail-closed)

C'est la demonstration la plus parlante. On va couper le modele local, puis
reposer une question sensible. Un produit mal concu basculerait en douce vers
le cloud. Celui-ci doit renvoyer une erreur propre, sans aucune tentative cloud.

```bash
python demo.py fail
```

Ce que vous devez voir : une **erreur claire** qui dit que le modele local est
indisponible et que, la demande etant sensible, **rien n'a ete tente vers le
cloud**. Zero fuite. C'est exactement l'argument a montrer a un avocat ou un
medecin : "quand ca casse, ca casse en position fermee".

## Etape 4 : la trace de conformite (RGPD article 32)

Ouvrez le fichier `journal-routage.jsonl` cree dans le dossier. Chaque ligne est
une decision : la date, la route choisie, le motif. Point essentiel : **le
contenu de la demande n'y est jamais**. Vous avez la preuve de QUI a decide QUOI
et POURQUOI, sans jamais stocker la donnee sensible elle-meme.

## Etape 5 : l'interface (Le Pupitre)

Si vous avez utilise l'installeur Windows, l'icone "Le Pupitre" est sur le
Bureau. Sinon, suivez `le-pupitre/README.md` pour le lancer.

A l'ouverture :

- Une **passphrase** vous est demandee. Elle protege l'historique, qui est
  **chiffre** sur le disque (SQLCipher AES-256). Cette passphrase n'est jamais
  stockee : si vous l'oubliez, l'historique reste illisible. C'est voulu.
- Posez une question : la reponse s'affiche proprement. Un repli **"voir le
  raisonnement"** permet d'afficher, a la demande, le cheminement du modele.
- Deposez un document (bouton trombone) puis posez une question dessus : c'est
  le **RAG local**. Le texte du document ne sort pas de la machine, les calculs
  se font en local.

## Etape 6 : verifier que tout est sain (les tests)

Pour les curieux, lancez la batterie de tests (aucune dependance requise) :

```bash
python test_detection.py
```

Vous devez lire `OK` et 107 tests passes. Le detecteur a regles, les
identifiants etrangers, les motifs contextuels et la loupe sont tous couverts.

## Petits soucis frequents

- **C'est lent.** Vous tournez probablement sur le processeur. C'est normal et
  sans danger. Avec une carte graphique a jour, c'est nettement plus rapide.
- **La carte graphique n'est pas utilisee.** L'installeur Windows le detecte et
  propose la mise a jour du pilote. Acceptez, il re-teste tout seul.
- **La route cloud ne fait rien.** C'est normal sans cle : la route cloud reste
  dormante tant que `ANTHROPIC_API_KEY` n'est pas renseignee dans `.env`. La
  partie locale, elle, fonctionne sans aucune cle.

## Pour aller plus loin

- La liste complete des capacites : section "Ce que le produit sait faire" du
  [README](README.md).
- La detection fine par IA (noms, adresses) et la double verification :
  section "La loupe" du README.
- Etendre la couverture a un nouveau pays : `packs-pays/README.md`.
