# Le Chef d'Orchestre — routeur local/cloud fail-closed pour l'IA

Aiguilleur de demandes IA : les donnees sensibles restent sur la machine (modele local),
les taches lourdes et anodines peuvent partir vers le cloud. Construit pendant le workshop
LE LABO IA (juin 2026) autour d'une idee simple : la frontiere local/cloud est d'abord une
question de confidentialite, pas de performance.

Stack 100 % open source : [LiteLLM](https://github.com/BerriAI/litellm) (passerelle) +
[Ollama](https://ollama.com) (moteur local) + un modele a licence permissive (Qwen, Apache 2.0).

## L'idee en une image

Le standardiste (LiteLLM) decroche chaque appel. Une serrure (le hook `chef_orchestre_hook.py`)
verifie d'abord : la demande contient-elle une donnee sensible (email, IBAN, numero de
securite sociale, vocabulaire du secret professionnel) ?

- **OUI -> LOCAL obligatoire.** Et si le local est en panne : erreur propre. JAMAIS de
  bascule vers le cloud. C'est le **fail-closed** : la porte casse en position fermee.
- **NON -> arbitrage de cout.** Tache lourde : cloud. Tache simple : local (quasi gratuit).

Chaque decision est ecrite dans un journal (`journal-routage.jsonl`) SANS le contenu de la
demande : qui a decide quoi, quand, pourquoi. C'est la trace de conformite (RGPD article 32,
accountability).

## La regle d'or

Le classifieur de SENSIBILITE passe TOUJOURS avant le classifieur de cout. En cas de doute :
local. Deux raisons juridiques, verifiees sur sources primaires :

1. La pseudonymisation ne sort pas du regime des donnees personnelles pour celui qui garde
   la table de correspondance (CJUE, 4 septembre 2025, affaire C-413/23 P, EDPS c. SRB ;
   rendu sous le reglement UE 2018/1725, raisonnement transposable au RGPD).
2. Certains modeles cloud recents conservent les requetes au moins 30 jours sans option
   "zero retention" (exemple : modeles de classe Mythos d'Anthropic, documentation
   officielle support.claude.com, juin 2026). Pour une donnee couverte par le secret
   professionnel, la reponse imbattable reste : "ca ne sort pas".

## Contenu

| Fichier | Role |
|---|---|
| `config.yaml` | La table d'aiguillage LiteLLM : routes `local-sensible`, `cloud-lourd`, `chef-auto` |
| `detection.py` | Le cerveau de la serrure : detection sensibilite + complexite (Python pur, zero dependance) |
| `chef_orchestre_hook.py` | La plomberie LiteLLM : fail-closed, journal |
| `test_detection.py` | 12 tests unitaires (stdlib uniquement) : `python test_detection.py` |
| `demo.py` | La demonstration en 4 actes (voir ci-dessous) |
| `install/install.sh` / `install.ps1` | Installation machine cible (Linux GPU ou Windows) |
| `start.sh` / `start.ps1` | Lancement du routeur (Ollama + LiteLLM) |
| `.env.example` | Les variables a remplir (les cles ne passent JAMAIS par git) |

## La demo en 4 actes (`demo.py`)

1. **Question anodine simple** -> part en LOCAL (par economie).
2. **Question avec donnee sensible** (faux IBAN) -> FORCEE en local, motif journalise.
3. **Fail-closed** : on coupe le modele local, on repose la question sensible -> ERREUR
   PROPRE, zero tentative cloud. C'est la preuve qui compte devant un juriste.
4. **Tache lourde anodine** -> aiguillee vers le CLOUD (si cle presente).

## Installation

```bash
git clone https://github.com/chabanade/chef-orchestre-public && cd chef-orchestre-public
cp .env.example .env        # remplir les valeurs (jamais dans git, jamais dans un chat)
bash install/install.sh     # installe Ollama + modele + LiteLLM
bash start.sh               # demarre le routeur sur le port 4000
python demo.py              # joue les actes 1, 2 et 4
python demo.py fail         # acte 3, apres avoir coupe Ollama
```

Sous Windows : `install\install.ps1` puis `start.ps1`.

Modele local par defaut : `qwen3:4b` (Apache 2.0, ~2,6 Go, tourne meme sur CPU).
Sur une machine GPU, passer a `qwen3:14b` ou plus : variable `OLLAMA_MODEL` dans `.env`.

## Limites assumees (honnetete)

- Le detecteur v1 est a REGLES (regex + mots-cles francais) : simple, lisible, auditable,
  mais il peut rater une donnee sensible mal ecrite (faux negatif = fuite). Etape 2 prevue :
  brancher [Microsoft Presidio](https://github.com/microsoft/presidio) (MIT) ou
  [GLiNER](https://github.com/urchade/GLiNER) (Apache 2.0) pour la detection fine.
- Le routeur garantit OU va la donnee, pas la qualite de la reponse du modele local.
- Les seuils (longueur, mots-cles) sont des reglages de depart, a calibrer sur vos cas.
- Verifiez chaque affirmation juridique avec un juriste avant un usage professionnel reel :
  ce depot est un outil technique, pas un avis juridique.

## Licence

MIT. Faites-en bon usage, ameliorez-le, partagez vos detecteurs.
