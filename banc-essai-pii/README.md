# Banc d'essai PII (FR) : mesure cumulative (15-16/06/2026)

Premiere brique du « banc d'essai FR maison » : mesurer le **rappel par type
d'entite** (ce qui FUIT protege le secret, pas la precision). 25 phrases
fictives, 29 entites.

- **STRICT** = toute la valeur sensible est couverte (donc vraiment masquee).
- **LARGE** = au moins reperee (l'ecart = un probleme de frontiere).

## Resultats (seuil 0.3, detecteurs cumules)

| Configuration | Rappel STRICT |
|---|---|
| Regex maison seules | 52 % |
| Regex + GLiNER | 93 % |
| Regex + GLiNER + Anonym-IA | 97 % |

## Lecture

- **GLiNER est le levier** (+41 points) : il debloque ce que les regex ne savent
  pas voir (personnes, adresses 0 -> 100 %, entreprise, cadastre). C'est le
  detecteur a installer en prod, pas une option.
- **Anonym-IA n'ajoute que +4 points** une fois GLiNER present : bon renfort FR
  (il rattrape un dossier), pas un pilier.
- **Date de naissance et numero de compte : 0 -> 100 %** apres l'ajout de regex
  CONTEXTUELLES (15/06). Sur ce petit banc les modeles les couvraient deja,
  donc le global n'a pas bouge ; la valeur est la **defense en profondeur** :
  un backstop deterministe si un modele rate une date.
- **Le seul trou restant** : une reference de dossier (ex. `DOS-2025-00891`,
  1 cas sur 29 = les 3 % manquants). Format trop variable d'un metier a l'autre
  pour une regex fiable : c'est exactement le cas-type d'**escalade** (l'arbitre
  de desaccord reveille un modele local plus puissant sur ces doutes).

## Ce que ce banc prouve

1. **Aucun detecteur seul ne suffit** ; l'union est la bonne reponse, et
   **GLiNER est indispensable** (52 -> 93 %).
2. **97 % n'est pas 100 %.** Honnetete : meme la meilleure union laisse passer
   des cas (ici un dossier). Le 95-99 % est un plancher de travail, pas une
   garantie ; la preuve definitive reste le red-teaming (test de l'intrus).
3. Le banc est l'outil qui dira, **metier par metier**, quand on a le droit de
   retirer le filet humain. Etendre `CAS` vers 100-200 phrases / metier est
   l'etape suivante (cf. section 41 du dossier de recherche : ~200 entites /
   categorie pour un intervalle de confiance de +/-3 %).

## Rejouer

```
# Regex seules (Python pur, aucune installation) :
python banc_essai_pii.py

# Avec les modeles (venv jetable : pip install gliner transformers torch) :
python banc_essai_pii.py --gliner --anonymia
```

Les modeles se telechargent (~0,5-2 Go) dans le cache Hugging Face au premier
appel. Le rappel grimpe detecteur apres detecteur (cumul affiche).
