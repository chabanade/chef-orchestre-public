# Le 2e rideau : Presidio en serie derriere la serrure

> **Statut : pret a brancher, pas encore allume.** Ce kit sera teste le
> jour J sur la machine qui fait tourner le routeur. Rien ici ne touche
> la machine tant qu'on ne lance pas `docker compose up`.

## Pourquoi un deuxieme rideau ?

Notre serrure (`detection.py` + la loupe) et le guardrail Presidio natif de
LiteLLM font le meme metier, mais ont ete ecrits par des gens differents :
**ils n'ont pas les memes angles morts**. En les mettant en serie, ce que
l'un rate, l'autre peut l'attraper. C'est le principe de la double
verification deja applique a la loupe (GLiNER + Presidio), etendu a tout
le routeur.

Bonus decouvert pendant l'etude du 12/06/2026 : LiteLLM sait faire
l'aller-retour nativement (`output_parse_pii: true`) : il masque a l'aller
et restaure les vraies valeurs au retour, comme notre greffier. Une
deuxieme armoire, independante de la notre.

## Ce que contient ce dossier

| Fichier | Role |
|---|---|
| `docker-compose.yml` | Les 2 conteneurs Presidio (analyzer + anonymizer), **locaux**, ports fermes sur 127.0.0.1 |
| `analyzer-fr/Dockerfile` | L'analyzer officiel + le modele de langue **francais** (l'image de base ne parle qu'anglais) |
| `analyzer-fr/languages-config.yml` | La configuration bilingue fr/en du moteur NLP (format officiel Presidio) |
| `recognizers-fr.json` | **Nos regles francaises injectees dans Presidio** : NIR (avec mois et Corse valides), TVA FR, SIRET, telephone, CNI et passeport en contextuels |

## Branchement le jour J (3 gestes)

1. **Lancer les conteneurs** (la premiere fois, le build telecharge le
   modele francais) :

   ```bash
   cd rideau-presidio
   docker compose up -d --build
   ```

2. **Declarer les adresses** dans le `.env` du routeur :

   ```
   PRESIDIO_ANALYZER_API_BASE=http://localhost:5002
   PRESIDIO_ANONYMIZER_API_BASE=http://localhost:5001
   ```

3. **Decommenter le bloc `guardrails:`** dans `config.yaml`, puis
   redemarrer le routeur.

## Decision a prendre au branchement (pas avant)

Le perimetre du rideau : actif sur **tout** le trafic (`default_on`), ou
seulement sur les **routes cloud** (attache au modele dans `model_list`).
Sur les routes locales il ne protege rien (la donnee ne sort pas) et
ajoute de la latence ; sur la route `cloud-pseudo` il repasserait derriere
notre greffier (double masquage : inoffensif mais a verifier en vrai).
A trancher avec un test reel le jour J.

## Sources verifiees (12/06/2026)

- Doc LiteLLM du guardrail : <https://docs.litellm.ai/docs/proxy/guardrails/pii_masking_v2>
- Format des recognizers ad hoc : exemple officiel du depot LiteLLM
  (`litellm/proxy/hooks/example_presidio_ad_hoc_recognizer.json`)
- Configuration multilingue Presidio : `docs/analyzer/languages-config.yml`
  du depot microsoft/presidio ; le serveur lit la variable `NLP_CONF_FILE`
  (verifie dans `presidio-analyzer/app.py`)
