<#
  Le Pupitre / Le Chef d'Orchestre - LANCEUR WINDOWS (niveau 1).

  But : sur une machine Windows quasi nue (typiquement le poste d'un avocat),
  un SEUL fichier qui :
    1. verifie/installe les prerequis (Ollama, Python) ;
    2. prepare un environnement isole (venv) + les dependances ;
    3. recupere le modele local adapte au materiel (GPU NVIDIA ou CPU) ;
    4. demarre le routeur (la serrure) + l'interface, et ouvre le navigateur.

  PRINCIPES (cf. maj/POLITIQUE-MISE-A-JOUR.md, charte du produit) :
    - Rien ne sort : aucune donnee client ne quitte la machine. Les seuls acces
      reseau sont les TELECHARGEMENTS d'installation (Ollama, Python, modele,
      paquets pip), affiches et explicites.
    - Idempotent : relancable sans danger ; ce qui est deja la n'est pas refait.
    - Reversible : tout est range dans %LOCALAPPDATA%\LePupitre (effacable).
    - La passphrase du coffre est demandee au lancement, JAMAIS stockee.

  Usage :
    .\lanceur.ps1            # installe si besoin, puis demarre
    .\lanceur.ps1 -Verifier  # AUDIT seulement : n'installe rien, ne lance rien
#>

param(
  [switch]$Verifier
)

$ErrorActionPreference = "Stop"

# Module d'auto-adaptation materielle (exigence #10) : detection GPU/VRAM,
# ESSAI REEL du GPU, et repli CPU propre si quoi que ce soit cloche.
. (Join-Path $PSScriptRoot "materiel.ps1")

# --- Reperage des dossiers ------------------------------------------------
# Le code du produit (routeur + le-pupitre) est a la racine du depot, deux
# niveaux au-dessus de ce script (installeur\windows\lanceur.ps1).
$Racine    = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Pupitre   = Join-Path $Racine "le-pupitre"
$DataDir   = Join-Path $env:LOCALAPPDATA "LePupitre"
$VenvDir   = Join-Path $DataDir ".venv"
$VenvPy    = Join-Path $VenvDir "Scripts\python.exe"
$EnvFile   = Join-Path $DataDir ".env"          # secrets LOCAUX (master key) - jamais en git
$DbFile    = Join-Path $DataDir "pupitre.db"    # le coffre chiffre
# PIEGE #6 (prouve par smoke test le 15/06) : litellm charge le module du
# callback PAR CHEMIN DE FICHIER, a cote du fichier config, SANS ajouter ce
# dossier au sys.path. Donc la config DOIT vivre dans $Racine (a cote de
# chef_orchestre_hook.py), et il faut EN PLUS PYTHONPATH=$Racine pour ses
# imports internes (vigie/detection/greffier). Les deux, pas l'un OU l'autre.
$ConfActive= Join-Path $Racine "config.active.yaml"

# --- Affichage ------------------------------------------------------------
function Titre($t)  { Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function Info($t)   { Write-Host "    $t" }
function OK($t)     { Write-Host "[OK] $t" -ForegroundColor Green }
function Avert($t)  { Write-Host "[!]  $t" -ForegroundColor Yellow }
function Souci($t)  { Write-Host "[X]  $t" -ForegroundColor Red }

# --- Detections (lecture seule) ------------------------------------------
function Trouver-Ollama {
  $c = Get-Command ollama -ErrorAction SilentlyContinue
  if ($c) { return $c.Source }
  $g = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
  if (Test-Path $g) { return $g }
  return $null
}

function Trouver-Python {
  foreach ($n in "python","py") {
    $c = Get-Command $n -ErrorAction SilentlyContinue
    if ($c) {
      try {
        $v = & $c.Source --version 2>&1
        if ($v -match "Python\s+3\.(1[0-9]|[2-9][0-9])") { return $c.Source }
      } catch {}
    }
  }
  return $null
}

function A-GPU-NVIDIA {
  # nvidia-smi present = pilote CUDA exploitable par Ollama.
  if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) { return $true }
  $gpus = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue
  foreach ($g in $gpus) { if ($g.Name -match "NVIDIA") { return $true } }
  return $false
}

function Rafraichir-Path {
  $env:Path = [System.Environment]::GetEnvironmentVariable("Path","User") + ";" +
              [System.Environment]::GetEnvironmentVariable("Path","Machine")
}

function Trouver-Edge {
  foreach ($p in "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                 "C:\Program Files\Microsoft\Edge\Application\msedge.exe") {
    if (Test-Path $p) { return $p }
  }
  return $null
}

function Creer-Raccourcis {
  # Icone "Le Pupitre" sur le Bureau ET dans le menu Demarrer (barre des
  # taches : clic droit sur l'icone -> Epingler). Elle relance CE fichier .bat
  # (idempotent) : apres un redemarrage, un seul clic remet tout en route.
  # Exigence #9 : on ne demande JAMAIS a un avocat de taper une adresse.
  $bat = Join-Path $PSScriptRoot "Demarrer-Le-Pupitre.bat"
  if (-not (Test-Path $bat)) { return }
  $edge = Trouver-Edge
  $ws = New-Object -ComObject WScript.Shell
  foreach ($dir in [Environment]::GetFolderPath('Desktop'),
                   (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs')) {
    try {
      $lnk = $ws.CreateShortcut((Join-Path $dir 'Le Pupitre.lnk'))
      $lnk.TargetPath = $bat
      $lnk.WorkingDirectory = $PSScriptRoot
      if ($edge) { $lnk.IconLocation = "$edge,0" }
      $lnk.Description = "Le Pupitre - assistant confidentiel (tout reste sur cet ordinateur)"
      $lnk.Save()
    } catch {}
  }
  OK "Icone 'Le Pupitre' creee (Bureau + menu Demarrer)"
}

function Ouvrir-Pupitre {
  param([string]$Url = "http://localhost:8800/")
  # Mode APPLICATION : une fenetre dediee, sans barre d'adresse, comme un vrai
  # logiciel. Repli sur le navigateur par defaut si Edge est absent.
  $edge = Trouver-Edge
  if ($edge) { Start-Process -FilePath $edge -ArgumentList "--app=$Url" }
  else { Start-Process $Url }
}

# --- Etape AUDIT ----------------------------------------------------------
function Auditer {
  Titre "Audit de la machine"
  $ollama = Trouver-Ollama
  if ($ollama) { OK "Ollama present : $ollama" } else { Avert "Ollama absent (sera installe)" }
  $py = Trouver-Python
  if ($py) { OK "Python 3.10+ present : $py" } else { Avert "Python 3.10+ absent (sera installe)" }
  # Detection materielle riche (carte + VRAM). Le choix DEFINITIF du moteur
  # se fera par un essai reel au demarrage (exigence #10), pas sur ce simple
  # constat : une carte presente n'est pas une carte qui marche.
  $gpu = Detecter-Gpu
  if ($gpu.Vendeur -eq "nvidia") {
    Info ("Carte NVIDIA : {0} ({1} Go VRAM) -> GPU tente, confirme par essai reel" -f $gpu.Nom, $gpu.VramGo)
  } elseif ($gpu.Vendeur -eq "nvidia-sans-pilote") {
    Avert ("Carte NVIDIA {0} mais pilote CUDA absent -> sera sur PROCESSEUR" -f $gpu.Nom)
  } else {
    Avert ("Pas de GPU NVIDIA exploitable ({0}) -> PROCESSEUR (plus lent mais sur)" -f $gpu.Nom)
  }
  $c = Get-PSDrive C -ErrorAction SilentlyContinue
  if ($c) { Info ("Disque C libre : {0:N1} Go" -f ($c.Free/1GB)) }
  $os = Get-CimInstance Win32_OperatingSystem
  Info ("RAM libre : {0:N1} Go / {1:N1} Go" -f ($os.FreePhysicalMemory/1MB), ($os.TotalVisibleMemorySize/1MB))
  Info "Dossier d'installation prevu : $DataDir"
}

# --- Etapes d'installation -----------------------------------------------
function Installer-Ollama {
  if (Trouver-Ollama) { OK "Ollama deja installe"; return }
  Titre "Installation d'Ollama (telechargement)"
  winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
  Rafraichir-Path
  if (-not (Trouver-Ollama)) { throw "Ollama n'a pas pu etre installe automatiquement. Voir https://ollama.com/download" }
  OK "Ollama installe"
}

function Installer-Python {
  if (Trouver-Python) { OK "Python deja installe"; return }
  Titre "Installation de Python (telechargement)"
  winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
  Rafraichir-Path
  if (-not (Trouver-Python)) { throw "Python n'a pas pu etre installe automatiquement. Voir https://www.python.org/downloads/" }
  OK "Python installe"
}

function Preparer-Venv {
  if (-not (Test-Path $DataDir)) { New-Item -ItemType Directory -Path $DataDir -Force | Out-Null }
  if (-not (Test-Path $VenvPy)) {
    Titre "Creation de l'environnement isole"
    $py = Trouver-Python
    & $py -m venv $VenvDir
  } else { OK "Environnement deja present" }
  Titre "Installation des composants (premiere fois : quelques minutes)"
  & $VenvPy -m pip install --quiet --upgrade pip
  & $VenvPy -m pip install --quiet -r (Join-Path $Pupitre "requirements.txt")
  & $VenvPy -m pip install --quiet "litellm[proxy]" pyyaml
  & $VenvPy -c "import sqlcipher3, fastapi, uvicorn, litellm, yaml"
  OK "Composants prets"
}

function Demarrer-Ollama {
  $ollama = Trouver-Ollama
  try { Invoke-WebRequest "http://localhost:11434/api/version" -UseBasicParsing -TimeoutSec 3 | Out-Null; OK "Ollama deja en service"; return } catch {}
  Titre "Demarrage d'Ollama"
  Start-Process -FilePath $ollama -ArgumentList "serve" -WindowStyle Hidden
  for ($i=0; $i -lt 20; $i++) {
    try { Invoke-WebRequest "http://localhost:11434/api/version" -UseBasicParsing -TimeoutSec 2 | Out-Null; OK "Ollama en service"; return } catch { Start-Sleep -Milliseconds 700 }
  }
  throw "Ollama ne repond pas sur le port 11434."
}

function Preparer-Modeles {
  param([string]$ollama, [switch]$SansQuestion)
  # Exigence #10 : on ne DEVINE plus le materiel, on l'ESSAIE.
  #  - Demarrage RAPIDE (defaut) : Resoudre-Profil teste un modele adapte a la
  #    VRAM et bascule au CPU si le GPU plante.
  #  - RECHERCHE DU MEILLEUR (option avancee) : Benchmarker-Machine essaie des
  #    modeles de taille croissante et garde le plus gros qui tient ET reste
  #    rapide (peut telecharger plusieurs Go). L'utilisateur DECIDE.
  Titre "Choix du moteur adapte a cette machine"
  $bench = $false
  if (-not $SansQuestion) {
    Info "Option : chercher le modele le PLUS PERFORMANT que ta machine peut faire tourner."
    Info "Cela essaie plusieurs tailles et peut TELECHARGER plusieurs Go (plus long)."
    $r = Read-Host "Chercher le meilleur modele ? (O = recherche / Entree = demarrage rapide)"
    $bench = ($r -match '^(o|oui|y|yes)$')
  }
  if ($bench) {
    $script:Profil = Benchmarker-Machine -Ollama $ollama -DossierTravail $DataDir -Telecharger
  } else {
    $script:Profil = Resoudre-Profil -Ollama $ollama -DossierTravail $DataDir -AvecProbe
  }
  $script:Backend     = $script:Profil.Backend
  $script:ModeleChat  = $script:Profil.ModeleChat
  $script:ModeleEmbed = $script:Profil.ModeleEmbed
  OK "Moteur retenu : $($script:Profil.Backend) (chat: $script:ModeleChat, embeddings: $script:ModeleEmbed)"
}

function MettreAJour-PiloteGpu {
  # Met a jour le pilote de la carte NVIDIA avec l'outil open-source
  # TinyNvidiaUpdateChecker (il telecharge le pilote OFFICIEL chez NVIDIA),
  # installe a la demande via winget. On LANCE l'outil pour que l'utilisateur
  # confirme et suive l'installation (l'ecran peut clignoter ; quelques minutes).
  # Retourne $true si l'outil a pu etre lance.
  Titre "Mise a jour du pilote de la carte graphique"
  $win = Get-Command winget -ErrorAction SilentlyContinue
  if ($win) {
    Info "Recuperation de l'outil de mise a jour (pilote officiel NVIDIA)..."
    try { & winget install --id Hawaii_Beach.TinyNvidiaUpdateChecker -e --accept-source-agreements --accept-package-agreements --disable-interactivity | Out-Null } catch {}
  }
  $exe = Get-ChildItem (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages") -Recurse -Filter "TinyNvidiaUpdateChecker*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
  if (-not $exe) {
    Avert "Outil de mise a jour indisponible. J'ouvre la page officielle NVIDIA : installe le pilote, puis relance Le Pupitre."
    Start-Process "https://www.nvidia.com/Download/index.aspx"
    return $false
  }
  Info "Une fenetre de mise a jour va s'ouvrir. Lance le telechargement + l'installation du pilote."
  Info "L'ecran peut clignoter pendant l'installation (c'est normal)."
  Start-Process -FilePath $exe -Verb RunAs   # eleve : l'install de pilote exige les droits admin
  Read-Host "Quand l'installation du pilote est TERMINEE, appuie sur Entree pour re-tester le GPU"
  return $true
}

function Proposer-MajGpu {
  # Si une carte NVIDIA est presente mais que l'essai GPU a echoue (souvent un
  # pilote trop ancien), on PROPOSE la mise a jour. L'utilisateur DECIDE :
  # accepte -> on met a jour et on re-teste ; refuse -> on garde le CPU (qui
  # marche). On ne met jamais a jour le pilote sans accord (choix de conception).
  if (-not ($script:Profil -and $script:Profil.MajGpuPossible) ) { return }
  if ($script:Backend -ne "cpu") { return }
  $g = $script:Profil.Gpu
  Titre "Ta carte graphique pourrait accelerer Le Pupitre"
  Info "Carte detectee : $($g.Nom) (pilote $($g.Pilote))."
  Info "Elle n'a pas pu etre utilisee : son pilote est probablement trop ancien."
  Info "Mettre a jour le pilote peut rendre les reponses BEAUCOUP plus rapides."
  Info "Sans mise a jour, Le Pupitre fonctionne quand meme (sur le processeur, plus lent)."
  $rep = Read-Host "Veux-tu mettre a jour le pilote maintenant ? (O/N)"
  if ($rep -notmatch '^(o|oui|y|yes)$') { Info "Tres bien, on reste sur le processeur."; return }
  if (-not (MettreAJour-PiloteGpu)) { return }
  # Re-test apres mise a jour : si le GPU marche maintenant, on l'adopte.
  # -SansQuestion : on ne redemande pas le benchmark ici (essai rapide suffit).
  Titre "Nouveau test du GPU apres mise a jour"
  Preparer-Modeles -ollama (Trouver-Ollama) -SansQuestion
  if ($script:Backend -eq "gpu") { OK "Parfait : le GPU est maintenant utilise (rapide)." }
  else { Avert "Le GPU n'est toujours pas exploitable. On reste sur le processeur (sur)." }
}

function Ecrire-Config {
  # On part de la config canonique (config.yaml, GPU/qwen3:4b) et on l'adapte au
  # materiel detecte. config.yaml n'est jamais modifie.
  $src = Get-Content (Join-Path $Racine "config.yaml") -Raw
  $src = $src.Replace("ollama_chat/qwen3:4b", "ollama_chat/$script:ModeleChat")
  $src = $src.Replace("ollama/nomic-embed-text", "ollama/$script:ModeleEmbed")
  # UTF-8 SANS BOM : Set-Content -Encoding utf8 (PS 5.1) ajoute un BOM qui
  # casse l'analyse YAML de litellm (piege #3, prouve sur le portable).
  [System.IO.File]::WriteAllText($ConfActive, $src, (New-Object System.Text.UTF8Encoding($false)))
  OK "Configuration adaptee a la machine : $ConfActive"
}

function Assurer-MasterKey {
  if (Test-Path $EnvFile) {
    $existant = Get-Content $EnvFile | Where-Object { $_ -match "^LITELLM_MASTER_KEY=" }
    if ($existant) { return ($existant -replace "^LITELLM_MASTER_KEY=","") }
  }
  $alea = -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 44 | ForEach-Object {[char]$_})
  $cle = "sk-local-$alea"
  "LITELLM_MASTER_KEY=$cle" | Set-Content -Path $EnvFile -Encoding ascii
  OK "Cle interne du routeur generee (locale, jamais partagee)"
  return $cle
}

# --- MAIN -----------------------------------------------------------------
Write-Host "Le Pupitre - lanceur Windows" -ForegroundColor White

if ($Verifier) {
  Auditer
  Write-Host "`n(Audit seul : rien n'a ete installe ni lance.)" -ForegroundColor DarkGray
  return
}

Auditer
Installer-Ollama
Installer-Python
Preparer-Venv
$ollama = Trouver-Ollama
Demarrer-Ollama
Preparer-Modeles -ollama $ollama
Proposer-MajGpu          # si carte NVIDIA + pilote trop vieux : propose la MAJ (l'utilisateur decide)
Ecrire-Config
$masterKey = Assurer-MasterKey

# Passphrase du coffre : demandee a CHAQUE lancement, jamais ecrite sur disque.
Titre "Coffre chiffre"
Info "Choisis (ou retape) la phrase secrete qui protege ton historique."
Info "Elle n'est jamais enregistree : sans elle, le coffre est illisible."
$sec = Read-Host "Phrase secrete du coffre" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
$passphrase = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
if (-not $passphrase) { Souci "Phrase secrete vide : abandon."; return }

# Demarrage du routeur (la serrure).
Titre "Demarrage du Chef d'Orchestre (routeur)"
# PIEGE #4 : la config definit une route cloud (Anthropic) ; litellm REFUSE de
# demarrer si ANTHROPIC_API_KEY est absente. En mode local par defaut, le cloud
# n'est jamais appele (le hook route tout en local), mais la cle doit EXISTER
# pour passer le demarrage. On garde une vraie cle si l'utilisateur en a
# configure une (cloud apres anonymisation, plus tard), sinon une factice.
$cleCloud = $env:ANTHROPIC_API_KEY
if (-not $cleCloud) { $cleCloud = "sk-ant-non-configure-local-uniquement" }
$envRouteur = @{
  OLLAMA_API_BASE     = "http://localhost:11434"
  LITELLM_MASTER_KEY  = $masterKey
  ANTHROPIC_API_KEY   = $cleCloud
  CHEF_ROUTES_LOCALES = "local-sensible,chef-auto,local-embeddings"
  CHEF_DETECTION_FINE = "off"
  PYTHONPATH          = $Racine
  # PIEGE #5 : sans UTF-8 force, litellm plante sur sa banniere Unicode dans
  # une console Windows en cp1252.
  PYTHONUTF8          = "1"
  PYTHONIOENCODING    = "utf-8"
}
foreach ($k in $envRouteur.Keys) { Set-Item -Path "Env:$k" -Value $envRouteur[$k] }
$litellm = Join-Path $VenvDir "Scripts\litellm.exe"
Start-Process -FilePath $litellm -ArgumentList "--config `"$ConfActive`" --port 4000 --host 127.0.0.1" -WindowStyle Hidden
for ($i=0; $i -lt 40; $i++) {
  try { Invoke-WebRequest "http://127.0.0.1:4000/health/liveliness" -UseBasicParsing -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep -Milliseconds 1500 }
}
OK "Routeur pret"

# Demarrage de l'interface (Le Pupitre).
Titre "Demarrage de l'interface"
$env:CHEF_PUPITRE_PASSPHRASE = $passphrase
$env:CHEF_PUPITRE_DB         = $DbFile
$env:CHEF_PUPITRE_CLE        = $masterKey
$env:CHEF_PUPITRE_BASE_URL   = "http://localhost:4000"
$env:CHEF_PUPITRE_MODELE     = "chef-auto"
$env:CHEF_PUPITRE_EXIGER_CHIFFREMENT = "1"
Start-Process -FilePath $VenvPy -ArgumentList "`"$(Join-Path $Pupitre "serveur.py")`"" -WindowStyle Hidden
$passphrase = $null  # on lache la phrase secrete de notre cote
for ($i=0; $i -lt 30; $i++) {
  try { Invoke-WebRequest "http://127.0.0.1:8800/" -UseBasicParsing -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep -Milliseconds 800 }
}
OK "Interface prete"

# Icone(s) pour les prochaines fois, puis ouverture en mode application.
Creer-Raccourcis
Ouvrir-Pupitre
Write-Host "`nLe Pupitre est ouvert." -ForegroundColor Green
Write-Host "La prochaine fois : double-clique l'icone 'Le Pupitre' sur ton Bureau." -ForegroundColor Green
Write-Host "Pour tout arreter : ferme la fenetre de l'application et cette fenetre noire." -ForegroundColor DarkGray
