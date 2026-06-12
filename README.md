# Le Chef d'Orchestre — routeur local/cloud fail-closed pour l'IA

> 🇬🇧 [English version](README.en.md)

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
| `config.yaml` | La table d'aiguillage LiteLLM : routes `local-sensible`, `cloud-lourd`, `chef-auto`, `cloud-pseudo` |
| `greffier.py` | La methode de l'armoire : pseudonymisation aller-retour, table jamais sortie |
| `detection.py` | Le cerveau de la serrure : extraction du texte, sensibilite, complexite (Python pur, zero dependance) |
| `detection_fine.py` | La loupe optionnelle : detection fine PII (GLiNER ou Presidio), fenetres glissantes |
| `chef_orchestre_hook.py` | La plomberie LiteLLM : fail-closed, default-deny, journal |
| `test_detection.py` | 50 tests unitaires (stdlib uniquement) : `python test_detection.py` |
| `requirements-fine.txt` | Dependances optionnelles de la loupe (versions epinglees) |
| `demo.py` | La demonstration en 4 actes (voir ci-dessous) |
| `install/install.sh` / `install.ps1` | Installation machine cible (Linux GPU ou Windows) |
| `start.sh` / `start.ps1` | Lancement du routeur (Ollama + LiteLLM) |
| `.env.example` | Les variables a remplir (les cles ne passent JAMAIS par git) |

## La demo (`demo.py`)

1. **Question anodine simple** -> part en LOCAL (par economie).
2. **Question avec donnee sensible** (faux IBAN) -> FORCEE en local, motif journalise.
3. **Fail-closed** : on coupe le modele local, on repose la question sensible -> ERREUR
   PROPRE, zero tentative cloud. C'est la preuve qui compte devant un juriste.
4. **Tache lourde anodine** -> aiguillee vers le CLOUD (si cle presente).
5. **Aller-retour de l'armoire** : un IBAN part en `<IBAN_1>`, le cloud repond avec le
   jeton, la vraie valeur est restauree en local.
6. **Refus de l'armoire** : le mot "patient" (contexte, pas une valeur remplacable)
   fait refuser la route pseudonymisee : une anonymisation incomplete ne sort pas.

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

## La loupe : detection fine PII (optionnelle)

En plus de la serrure a regles, une loupe detecte ce que les regex ratent : noms de
personnes, adresses, organisations, diagnostics... Moteur par defaut :
[GLiNER](https://github.com/urchade/GLiNER) avec le modele `urchade/gliner_multi_pii-v1`
(Apache 2.0, 6 langues dont le francais, tourne sur CPU). Variante :
[Microsoft Presidio](https://github.com/microsoft/presidio) (MIT) + spaCy francais.

Installation : `bash install/install.sh --fine` (ou `install.ps1 -Fine`). Reglages :
`CHEF_DETECTION_FINE` (gliner / presidio / off) et `CHEF_SEUIL_FIN` dans `.env`.

Securite de la loupe : elle COMPLETE les regles (union), ne les remplace jamais.
Loupe absente -> regles seules (journalise). Loupe en panne -> la demande est traitee
comme sensible et reste en local : une panne degrade la puissance, jamais la
confidentialite. Les longs textes sont decoupes en fenetres qui se chevauchent
(GLiNER ne lit que ~384 jetons d'un coup : sans decoupage, une donnee enfouie dans
un long document serait invisible).

### Double verification (donnees ultra-sensibles : sante, avocat)

La loupe est MULTI-MOTEURS : `CHEF_DETECTION_FINE=gliner,presidio` fait tourner les
deux detecteurs sur chaque demande et fait l'union des trouvailles. Il suffit qu'UN
moteur voie une donnee pour qu'elle reste en local. Trois couches au total : regles
regex (formats : IBAN, secu, email) + GLiNER (sens : noms, adresses, diagnostics) +
Presidio (patterns et NER, angle different). Installation : `install.sh --fine-double`
(ou `install.ps1 -FineDouble`). Et `CHEF_LOUPE_STRICTE=1` pour exiger que la defense
promise soit complete : si un moteur demande manque au demarrage, tout reste en local
tant qu'il n'est pas repare. Honnetete : aucun cumul n'atteint 100 % de rappel ; la
classe vraiment ultra-sensible doit rester en local PAR DEFAUT, la loupe ne sert qu'a
attraper ce qui tenterait d'en sortir.

### Choix des moteurs : etude de marche (12/06/2026)

Une etude comparative des detecteurs PII open source utilisables 100 % en local sur
du francais (panorama, qualite fr, defense en profondeur, outils specialises) confirme
cette pile comme la meilleure base libre a date : `gliner_multi_pii-v1` est, en juin
2026, le seul modele PII zero-shot a la fois sous licence libre ET avec francais
atteste ; Presidio est le framework hybride de reference (son editeur prone lui-meme
le cumul de detecteurs). Enseignement applique : seuil GLiNER par defaut a 0.3, car
son biais documente est precision haute / rappel bas, l'inverse de ce qu'exige le
fail-closed (un faux positif coute un passage en local, un faux negatif une fuite).
Pistes d'extension francaises (a auditer avant usage) : Anonym-IA CamemBERT PII (MIT),
NERmembert (MIT), eds-pseudo de l'AP-HP (BSD-3, clinique). Ecartes : Piiranha (licence
non commerciale, performances contestees par arXiv 2504.12308), eu-pii-safeguard
(licence d'evaluation), detecteurs cloud (demander au cloud si une donnee peut sortir
vers le cloud viole le secret par l'acte meme de verification).

## La methode de l'armoire : route `cloud-pseudo` (pseudonymisation aller-retour)

Inspiree d'une pratique hospitaliere reelle (les CECOS, pour le don de gametes) :
le donneur recoit un numero, tout le monde travaille avec le numero et les donnees
utiles (groupe sanguin, caracteristiques), et l'identite reste dans une armoire
fermee, accessible a peu de personnes, sur demande motivee. C'est exactement la
pseudonymisation au sens du RGPD (art. 4.5) : les informations de re-identification
conservees SEPAREMENT, sous mesures techniques et organisationnelles.

Transposition (route opt-in `cloud-pseudo`, voir `greffier.py`) :
1. ALLER : les valeurs formatees (IBAN, NIR, email, telephone, SIRET, CB) sont
   remplacees par des jetons `<IBAN_1>`, `<EMAIL_1>`... La table jeton -> valeur
   (l'armoire) reste EN MEMOIRE LOCALE, jamais sur disque, jamais au journal.
2. Le cloud travaille sur les numeros, comme le labo travaillait sur les donneurs.
3. RETOUR : la reponse est re-personnalisee en local, puis l'armoire est brulee
   (la table ne vit que le temps de l'aller-retour : mieux que l'armoire papier).

Garde-fous fail-closed : apres pseudonymisation, le texte est RE-VERIFIE ; s'il
reste un motif (mot-cle metier comme "patient", entite vue par la loupe, bloc non
inspectable), la demande est REFUSEE : une pseudonymisation incomplete ne sort pas.
Sans le hook, la route `cloud-pseudo` pointe le local (rien ne sort par accident).
Streaming desactive sur cette route (la re-personnalisation exige la reponse complete).

Limites juridiques assumees (verifiees sur sources primaires) : pour celui qui
detient la table, la donnee pseudonymisee RESTE une donnee personnelle (CJUE,
4 septembre 2025, C-413/23 P) ; et le contexte peut re-identifier sans identifiant
direct (criteres G29 : individualisation, correlation, inference). Cette route
REDUIT fortement le risque pour les taches mixtes ; elle ne remplace pas le local
strict pour l'ultra-sensible, et la minimisation reste due.

### L'armoire de SESSION : iterer sans amnesie

Avec une armoire brulee apres chaque aller-retour, le routeur serait amnesique
entre deux questions d'une meme conversation (le `<IBAN_1>` du tour 1 deviendrait
irrecuperable au tour 3). Chaque CONVERSATION a donc son armoire : la meme valeur
garde le meme jeton d'un tour a l'autre, et un jeton pose au tour 1 reste
restaurable au tour 5. Cle de session : `metadata.session_id` (conseille), sinon
le champ standard `user`, sinon une armoire commune (poste mono-utilisateur).

Compromis assume, et borne : l'armoire vit plus longtemps, MAIS elle reste en
memoire d'un seul processus (jamais disque, jamais journal), elle est BRULEE
apres `CHEF_ARMOIRE_TTL_MINUTES` d'inactivite (30 min par defaut), le nombre de
sessions est plafonne, et un redemarrage la perd : degradation SURE (jetons
orphelins opaques, aucune fuite). `CHEF_ARMOIRE_SESSION=0` restaure le brulage
apres chaque aller-retour (securite maximale, amnesie assumee).

### Comparaison avec l'existant (etude du 12/06/2026)

Le greffier a ete compare aux solutions publiques : LLM Guard (jumeau conceptuel
avec son Vault, mais anglais/chinois seulement et au ralenti), Presidio
encrypt/decrypt (le secret chiffre voyage AVEC le prompt : une fuite de cle
rendrait les archives dechiffrables, la ou une table brulee ne laisse rien),
guardrail Presidio natif de LiteLLM (`output_parse_pii` : un vrai aller-retour
natif, recommande en DEUXIEME rideau de defense, mais sans refus fail-closed),
PII-Shield (recognizers francais MIT interessants, table sur disque 7 jours),
Kong ai-sanitizer (payant, ferme), LangChain PresidioReversibleAnonymizer
(archive, mort). Constat : la combinaison francais natif + table en memoire
brulee + refus fail-closed n'existe dans aucun outil public a date.

Durci suite a l'etude (risque principal : jetons abimes par le modele) :
consigne systeme automatique, matching tolerant au retour (`<iban 1>`,
`< IBAN_1 >`, `<Iban-1>` rattrapes), et controle d'integrite journalise
(jeton irrecuperable = laisse opaque : zero fuite, zero devinette).

## Durcissements issus de la revue adversariale (juin 2026)

Trois relecteurs contradicteurs (securite, concurrence, exactitude des API) ont attaque
le code ; chaque correctif est couvert par un test :

- **Images et fichiers = sensibles par defaut.** Un bloc non textuel (photo de carte
  vitale, PDF...) est invisible aux regex : il leve le drapeau "contenu-non-inspectable"
  et la demande reste en local (ou est refusee si elle visait le cloud).
- **Tous les formats d'appel couverts** : messages, prompt legacy (/completions),
  input (/responses), /v1/messages. Un type d'appel que la serrure ne sait pas
  inspecter et qui vise une route non locale est REFUSE (default-deny).
- **IBAN en minuscules** detecte ; mots-cles "iban", "bic" ajoutes.
- **Panne de detection -> local**, jamais une erreur 500, jamais le cloud.
- **Un seul calcul de loupe a la fois** (verrou d'inference) et chargement du modele
  protege contre les doubles demarrages.
- **Configuration blindee** : seuil malforme -> valeur par defaut ; moteur de loupe
  inconnu (faute de frappe) -> loupe coupee proprement, pas de telechargement surprise.

## Limites assumees (honnetete)

- Le detecteur a regles peut rater une donnee sensible mal ecrite, et la loupe GLiNER
  reduit ce risque sans le supprimer : aucun detecteur n'est parfait. Mesurez le taux
  de faux negatifs sur VOS documents avant un usage reel.
- Le routeur garantit OU va la donnee, pas la qualite de la reponse du modele local.
- Les seuils (longueur, mots-cles) sont des reglages de depart, a calibrer sur vos cas.
- Verifiez chaque affirmation juridique avec un juriste avant un usage professionnel reel :
  ce depot est un outil technique, pas un avis juridique.

## Licence

MIT. Faites-en bon usage, ameliorez-le, partagez vos detecteurs.
