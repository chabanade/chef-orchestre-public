# Installeurs : Le Pupitre / Le Chef d'Orchestre

> Objectif : un utilisateur **non technique** (un avocat) installe et lance le
> produit **sans rien y connaître**. Trois niveaux d'ambition, du plus rapide au
> plus abouti. **Dépôt privé** : l'installeur est un élément premium.

## Les 3 niveaux

| Niveau | Quoi | État |
|---|---|---|
| **1. Lanceur « double-clic »** | Un fichier qui installe les prérequis, prépare tout et démarre. Suppose le dossier du produit copié sur la machine. | ✅ **fait (Windows)** : `windows/` |
| **2. Vrai installeur natif** | Un `.exe` (Windows) / `.dmg` (Mac) / `.AppImage` (Linux) qui pose tout proprement, crée un raccourci, sans Docker. | ⏳ à venir |
| **3. Application de bureau** | Emballage Tauri/Electron avec **auto-update signé** intégré (cf. `../maj/POLITIQUE-MISE-A-JOUR.md`). Le produit final vendable. | ⏳ à venir |

## Niveau 1 : Windows (aujourd'hui)

Dossier `windows/` :
- `Demarrer-Le-Pupitre.bat` : le fichier à **double-cliquer**.
- `lanceur.ps1` : le script qui fait tout (installe Ollama + Python si besoin,
  prépare un environnement isolé, choisit le moteur **adapté au matériel par un
  ESSAI RÉEL** (cf. `materiel.ps1`), démarre le routeur + l'interface, crée une
  **icône « Le Pupitre »** sur le Bureau et le menu Démarrer, et ouvre le produit
  en **fenêtre application** (pas un onglet de navigateur).
- `materiel.ps1` : l'**auto-adaptation matérielle** (exigence #10). Ne *devine*
  pas le matériel : il l'*essaie*. Détecte la carte/VRAM, choisit un modèle qui
  rentre, le teste pour de vrai sur le GPU (réponse cohérente + calcul bien sur
  le GPU), et **bascule proprement sur le processeur** si quoi que ce soit
  cloche. Marche sur un PC modeste de nomade, **CUDA ou pas**. Utilisable seul :
  `lanceur.ps1 -Verifier` (audit) ou `materiel.ps1 -Probe` (essai réel).

### Utilisation sur une machine de test (ex. portable RTX 3060)
1. Copier le dossier du produit sur la machine (clé USB, zip…).
2. Ouvrir `installeur\windows\`, **double-cliquer `Demarrer-Le-Pupitre.bat`**.
3. Au premier lancement : il télécharge ce qu'il faut (quelques minutes), demande
   **une phrase secrète** (la clé du coffre), puis ouvre `http://localhost:8800`.

### Vérifier sans rien installer (audit)
```powershell
powershell -ExecutionPolicy Bypass -File .\windows\lanceur.ps1 -Verifier
```
N'installe rien, ne lance rien : affiche juste l'état de la machine (Ollama,
Python, GPU, RAM, disque).

### Ce que le lanceur garantit
- **Rien ne sort** : les seuls accès réseau sont les **téléchargements
  d'installation** (Ollama, Python, modèle, paquets), explicites. Aucune donnée
  client ne quitte la machine.
- **Idempotent** : relançable sans danger ; ce qui est déjà là n'est pas refait.
- **Rangé et réversible** : les données vivent dans `%LOCALAPPDATA%\LePupitre`
  (environnement, coffre, clé interne). Effaçable. Seule exception :
  `config.active.yaml` est écrit **dans le dossier du produit** (à côté de
  `chef_orchestre_hook.py`), car litellm charge le callback à côté du config
  (piège #6) ; il est généré, ignoré par git, et adapté à CHAQUE machine.
- **S'adapte au matériel par un essai réel**, jamais en devinant (exigence #10).
- **UX zéro technique** : icône Bureau + menu Démarrer, fenêtre application ;
  on ne tape jamais d'adresse (exigence #9).
- **Passphrase jamais stockée** : demandée à chaque lancement.

### Limites du niveau 1 (franchise)
- Suppose que le **dossier du produit** est présent sur la machine (le niveau 2
  empaquettera tout dans un seul fichier).
- Utilise `winget` pour installer Ollama/Python : sur une machine très ancienne
  sans `winget`, prévoir l'installation manuelle d'Ollama et de Python.
- Pas encore d'auto-update ni de signature (niveaux 2/3).
