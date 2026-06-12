# Packs pays — l'amelioration continue, sous GO humain

Le routeur sait dire quand un document **sort de ses cases connues** (la
vigie : ecriture etrangere, langue inconnue, identifiant d'un format jamais
vu). Ce dossier contient la reponse : des **packs de detection par pays**,
actives par l'utilisateur, jamais par la machine.

## Le flux complet (du blocage a la reprise du dossier)

1. **L'alerte.** Un dossier etranger arrive ; la vigie detecte un manque de
   couverture. La demande reste en LOCAL (rien ne fuit), et si elle visait
   le cloud, le refus 403 explique : « couverture inconnue, renseignez
   l'origine du document ». Le manque est trace dans
   `alertes-couverture.jsonl` (metadonnees seulement, jamais le contenu).
2. **L'origine.** L'utilisateur identifie le pays du document
   (ex. : « c'est un dossier bresilien »).
3. **Le GO.** Il active le pack correspondant dans son `.env` :
   `CHEF_PACKS_PAYS=bresil` (plusieurs : `bresil,inde`), puis redemarre le
   routeur. C'est SON geste : le systeme ne s'auto-modifie jamais.
4. **L'auto-test.** Au chargement, chaque motif du pack est verifie :
   la regex doit compiler ET reconnaitre son propre exemple. Un pack
   casse est REFUSE EN ENTIER et signale (`pack-en-panne:<nom>`) — et
   tant qu'un pack demande est en panne, TOUT reste en local (on a promis
   une couverture qu'on ne peut pas tenir : prudence maximale).
5. **La reprise.** Le dossier repart : les identifiants du pays sont
   maintenant detectes par la serrure et mis sous jeton par le greffier.

## Pourquoi pas une auto-amelioration totale (facon agent autonome) ?

Parce que c'est un outil de SECURITE. Un systeme qui reecrit ses propres
regles de detection sans validation humaine peut s'ouvrir une fuite tout
seul (une « amelioration » mal ecrite = un trou silencieux). Le compromis
retenu :

- la machine DIAGNOSTIQUE et DEMANDE (la vigie, le carnet d'alertes) ;
- l'humain DECIDE et ACTIVE (le pack, sous GO) ;
- le pack ne peut qu'AJOUTER des detections, jamais en retirer : meme un
  pack mal ecrit ne peut pas affaiblir la serrure, au pire il n'ajoute rien.

## Packs disponibles

| Pack | Contenu | Source du format |
|---|---|---|
| `bresil` | CPF (formate, direct ; brut 11 chiffres en contextuel), CNPJ | Microsoft Purview (12/06/2026) |
| `inde` | PAN (contextuel), Aadhaar (contextuel) | Microsoft Purview (12/06/2026) |
| `chine` | Carte d'identite de resident (18 caracteres, date integree : tres distinctif, direct) | Microsoft Purview (12/06/2026) |

## Demander ou creer un pack manquant

Un pack est un simple fichier JSON :

```json
{
    "pays": "Exemple",
    "source": "d'ou viennent les formats, avec la date de consultation",
    "motifs": {
        "mon_code": {"regex": "\\b...\\b", "exemple": "valeur fictive qui doit matcher"}
    },
    "motifs_contextuels": {
        "mon_code_2": {"regex": "...", "contextes": ["mot declencheur"], "exemple": "..."}
    },
    "mots_cles": ["vocabulaire sensible du pays"]
}
```

Regles de fabrication (non negociables) :

- **Chaque format est verifie a la source** (registre officiel, Microsoft
  Purview, documentation d'Etat) avec la date de consultation dans `source`.
  Jamais un format « de memoire ».
- **Chaque motif porte son exemple** (FICTIF) : c'est lui qui sert
  d'auto-test au chargement.
- Un motif trop generique pour decider seul (une simple suite de chiffres)
  va dans `motifs_contextuels` avec ses mots declencheurs, pas dans
  `motifs`.
- Une IA peut PREPARER un pack (brouillon + sources) ; un humain le RELIT
  et l'ACTIVE. Jamais l'inverse.
