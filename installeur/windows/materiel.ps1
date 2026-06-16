<#
  Le Pupitre - AUTO-ADAPTATION MATERIELLE (exigence #10, 15/06/2026).

  Pourquoi ce fichier existe :
    Le lanceur d'origine faisait un raccourci dangereux : "il y a une carte
    NVIDIA -> GPU + gros modele". Sur le portable de test (RTX 3060 Laptop
    6 Go) c'est EXACTEMENT ce qui a plante : le backend Vulkan d'Ollama a
    crashe (0xc0000005) et le modele a sature la VRAM. Resultat : ecran noir
    pour l'avocat.

  La regle apprise (chaque erreur devient une loi) :
    On ne FAIT JAMAIS CONFIANCE a la presence d'une carte. On ESSAIE pour de
    vrai, et si ca ne marche pas, on retombe proprement sur le processeur.
    Mieux vaut lent mais qui marche, que rapide mais qui plante.

  Ce que fait ce module, dans l'ordre :
    1. Detecte le materiel SANS rien casser (carte, VRAM, RAM, disque).
    2. Choisit un modele CANDIDAT qui RENTRE dans la memoire disponible.
    3. PROBE : lance reellement une mini-generation et verifie 3 choses :
         a) ca ne crashe pas / ne bloque pas (sante du backend) ;
         b) la reponse est COHERENTE ("2+2" doit donner "4") -> garde
            anti-charabia (vieilles cartes qui calculent du n'importe quoi) ;
         c) le calcul a bien eu lieu sur le GPU (lecture de "ollama ps").
    4. Si le GPU echoue a n'importe quelle etape -> fabrique la variante CPU
       (num_gpu 0) et re-probe sur processeur. Le CPU est notre filet : il
       marche partout.

  100% lecture seule tant qu'on ne PROBE pas. Aucune donnee ne sort.

  Usage :
    .\materiel.ps1 -Audit    # detection seule, n'allume rien (pas besoin d'Ollama)
    .\materiel.ps1 -Probe    # detection + essai reel (Ollama doit tourner)
    . .\materiel.ps1         # dot-source : fournit la fonction Resoudre-Profil
#>

param(
  [switch]$Audit,
  [switch]$Probe,
  [switch]$Benchmark,          # essaie des modeles de taille croissante, garde le meilleur
  [switch]$Telecharger,        # autorise le benchmark a telecharger les modeles manquants
  [string]$OllamaPath,
  [string]$OllamaUrl = "http://localhost:11434"
)

# --- Petit affichage (noms uniques pour cohabiter avec le lanceur) --------
function _M-Titre($t) { Write-Host "`n--- $t ---" -ForegroundColor Cyan }
function _M-Info($t)  { Write-Host "    $t" }
function _M-OK($t)    { Write-Host "[OK] $t" -ForegroundColor Green }
function _M-Avert($t) { Write-Host "[!]  $t" -ForegroundColor Yellow }
function _M-Souci($t) { Write-Host "[X]  $t" -ForegroundColor Red }

# --- Localiser Ollama -----------------------------------------------------
function Trouver-OllamaExe {
  param([string]$Indice)
  if ($Indice -and (Test-Path $Indice)) { return $Indice }
  $c = Get-Command ollama -ErrorAction SilentlyContinue
  if ($c) { return $c.Source }
  foreach ($p in (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
                 "C:\Program Files\Ollama\ollama.exe") {
    if (Test-Path $p) { return $p }
  }
  return $null
}

# --- ETAPE 1 : detection materielle (lecture seule) -----------------------
function Detecter-Gpu {
  # Retourne @{ Vendeur; Nom; VramGo; Pilote }. VramGo = 0 si inconnu.
  # On privilegie nvidia-smi (chiffre VRAM fiable) ; sinon on lit la carte
  # via Windows (CIM) pour au moins connaitre le vendeur.
  $res = @{ Vendeur = "aucun"; Nom = "(aucune carte dediee)"; VramGo = 0; Pilote = "" }

  $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
  if ($smi) {
    try {
      $ligne = (& $smi.Source --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits 2>$null | Select-Object -First 1)
      if ($ligne) {
        $parts = $ligne -split ","
        $res.Vendeur = "nvidia"
        $res.Nom = $parts[0].Trim()
        $mib = 0
        if ([int]::TryParse(($parts[1].Trim()), [ref]$mib)) { $res.VramGo = [math]::Round($mib / 1024, 1) }
        if ($parts.Count -ge 3) { $res.Pilote = $parts[2].Trim() }
        return $res
      }
    } catch {}
  }

  # Pas de nvidia-smi exploitable : on regarde quand meme les cartes.
  $cartes = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue
  foreach ($g in $cartes) {
    if ($g.Name -match "NVIDIA") {
      # Carte NVIDIA presente mais pilote CUDA absent (nvidia-smi manquant).
      # On la signale, mais sans pilote on ne pourra pas l'exploiter -> CPU.
      $res.Vendeur = "nvidia-sans-pilote"; $res.Nom = $g.Name
      # AdapterRAM est souvent faux/plafonne a 4 Go en 32 bits : on ne s'y fie pas.
      return $res
    }
  }
  foreach ($g in $cartes) {
    if ($g.Name -match "AMD|Radeon")  { $res.Vendeur = "amd";   $res.Nom = $g.Name; return $res }
    if ($g.Name -match "Intel")       { $res.Vendeur = "intel"; $res.Nom = $g.Name; return $res }
  }
  if ($cartes) { $res.Nom = ($cartes | Select-Object -First 1).Name }
  return $res
}

function Detecter-RamLibreGo {
  $os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
  if ($os) { return [math]::Round($os.FreePhysicalMemory / 1MB, 1) }
  return 0
}

function Detecter-DisqueLibreGo {
  $d = Get-PSDrive C -ErrorAction SilentlyContinue
  if ($d) { return [math]::Round($d.Free / 1GB, 1) }
  return 0
}

# --- ETAPE 2 : choisir un modele candidat qui RENTRE ----------------------
# Tailles approximatives en VRAM/RAM (quantification Q4, marge de securite
# incluse pour le contexte). On reste volontairement CONSERVATEUR : un modele
# qui rentre tout juste finit par planter des qu'on lui parle longtemps.
function Choisir-Candidat {
  param([hashtable]$Gpu, [double]$RamGo)

  $embed = "nomic-embed-text"   # ~0.3 Go, tient partout si le GPU marche

  # GPU NVIDIA avec pilote CUDA : on dimensionne sur la VRAM.
  if ($Gpu.Vendeur -eq "nvidia" -and $Gpu.VramGo -ge 3.5) {
    if     ($Gpu.VramGo -ge 15) { $chat = "qwen3:14b" }
    elseif ($Gpu.VramGo -ge 7)  { $chat = "qwen3:8b"  }
    else                        { $chat = "qwen3:4b"  }   # 4 a 7 Go (ex. 3060 6 Go)
    return @{
      Backend = "gpu"; ModeleChat = $chat; ModeleEmbed = $embed; ModeleCpuBase = "qwen3:1.7b"
      Raison = "Carte NVIDIA $($Gpu.Nom) avec $($Gpu.VramGo) Go de VRAM -> essai GPU avec $chat."
    }
  }

  # Tout le reste (pas de NVIDIA, pilote absent, VRAM trop faible, AMD, Intel,
  # rien) -> processeur. Le modele depend de la RAM libre.
  if ($RamGo -ge 6) { $base = "qwen3:4b" } else { $base = "qwen3:1.7b" }
  return @{
    Backend = "cpu"; ModeleChat = "$base-cpu"; ModeleEmbed = "nomic-embed-cpu"; ModeleCpuBase = $base
    Raison = "Pas de GPU NVIDIA exploitable ($($Gpu.Nom)) -> processeur, modele $base (force CPU)."
  }
}

# --- Fabriquer une variante "100% CPU" d'un modele (num_gpu 0) -------------
# C'est ce qui sauve les vieilles cartes et les backends qui plantent :
# on dit explicitement a Ollama "ne touche pas au GPU".
function Assurer-VarianteCpu {
  param([string]$Ollama, [string]$Base, [string]$Cible, [string]$DossierTravail)
  $present = (& $Ollama list 2>$null) -join "`n"
  if ($present -match [regex]::Escape($Cible)) { return }
  if ($present -notmatch [regex]::Escape($Base)) {
    _M-Info "Telechargement du modele de base $Base ..."
    & $Ollama pull $Base | Out-Host
  }
  if (-not (Test-Path $DossierTravail)) { New-Item -ItemType Directory -Path $DossierTravail -Force | Out-Null }
  $mf = Join-Path $DossierTravail ("Modelfile." + ($Cible -replace "[^A-Za-z0-9]","_"))
  # ASCII sans BOM : un Modelfile avec BOM fait echouer "ollama create".
  [System.IO.File]::WriteAllText($mf, "FROM $Base`nPARAMETER num_gpu 0`n", [System.Text.Encoding]::ASCII)
  _M-Info "Creation de la variante CPU $Cible ..."
  & $Ollama create $Cible -f $mf | Out-Host
}

# --- ETAPE 3 : la PROBE (essai reel) --------------------------------------
# Retourne @{ OK; Coherent; Processeur; Secondes; Vitesse; Detail }.
# Vitesse = jetons/seconde (eval_count / eval_duration d'Ollama) : la vraie
# mesure de rapidite, independante du nombre de jetons produits. Sert au
# benchmark (garder le plus gros modele qui reste assez rapide).
function Tester-Modele {
  param([string]$Ollama, [string]$Modele, [int]$TimeoutSec = 120, [string]$Url = "http://localhost:11434")

  $res = @{ OK = $false; Coherent = $false; Processeur = "?"; Secondes = 0; Vitesse = 0; Detail = "" }

  # S'assurer que le modele est present (sinon le pull pourrait masquer un
  # vrai echec GPU derriere un long telechargement).
  $present = (& $Ollama list 2>$null) -join "`n"
  $nomCourt = $Modele -replace ":latest$",""
  if (($present -notmatch [regex]::Escape($Modele)) -and ($present -notmatch [regex]::Escape($nomCourt))) {
    _M-Info "Telechargement de $Modele pour l'essai ..."
    try { & $Ollama pull $Modele | Out-Host } catch { $res.Detail = "pull impossible : $($_.Exception.Message)"; return $res }
  }

  # Question piege : un GPU sain repond "4" ; un GPU qui delire (charabia)
  # ne le fera pas. think=$false coupe la reflexion de qwen3 quand le modele
  # l'honore. Mais certains modeles (ex. qwen3:4b) restent bavards et mettent
  # du preambule : il faut donc assez de jetons pour ATTEINDRE la reponse,
  # sinon on coupe avant le "4" et on croit a tort a du charabia (faux negatif
  # observe sur la RTX 3060 le 15/06, GPU pourtant sain). 200 jetons : rapide
  # sur GPU, acceptable sur CPU, et large pour laisser sortir "4".
  $corps = @{
    model   = $Modele
    prompt  = "Combien font 2 plus 2 ? Reponds uniquement par le chiffre, rien d'autre."
    think   = $false
    stream  = $false
    options = @{ num_predict = 200; temperature = 0 }
  } | ConvertTo-Json

  $t0 = Get-Date
  try {
    $r = Invoke-RestMethod -Uri "$Url/api/generate" -Method Post -Body $corps -ContentType "application/json" -TimeoutSec $TimeoutSec
  } catch {
    $res.Secondes = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
    $res.Detail = "echec/timeout du backend : $($_.Exception.Message)"
    return $res
  }
  $res.Secondes = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
  $res.OK = $true
  $reponse = "$($r.response)"
  $res.Coherent = ($reponse -match "4")
  # Vitesse reelle en jetons/seconde (Ollama donne eval_count + eval_duration ns).
  if ($r.eval_count -and $r.eval_duration -and $r.eval_duration -gt 0) {
    $res.Vitesse = [math]::Round($r.eval_count / ($r.eval_duration / 1e9), 1)
  }
  $res.Detail = "reponse=[" + ($reponse.Trim() -replace "\s+"," ") + "] vitesse=" + $res.Vitesse + " j/s"

  # Sur quel processeur Ollama a-t-il REELLEMENT charge le modele ?
  try {
    $ps = (& $Ollama ps 2>$null) -join "`n"
    $ligne = ($ps -split "`n" | Where-Object { $_ -match [regex]::Escape($nomCourt) } | Select-Object -First 1)
    if ($ligne -match "GPU" -and $ligne -notmatch "CPU") { $res.Processeur = "GPU" }
    elseif ($ligne -match "CPU" -and $ligne -match "GPU") { $res.Processeur = "MIXTE" }
    elseif ($ligne -match "CPU") { $res.Processeur = "CPU" }
  } catch {}

  return $res
}

# --- ETAPE 4 : resolution complete (detection -> candidat -> probe -> repli)
function Resoudre-Profil {
  param([string]$Ollama, [string]$DossierTravail = $env:TEMP, [switch]$AvecProbe, [string]$Url = "http://localhost:11434")

  $gpu = Detecter-Gpu
  $ram = Detecter-RamLibreGo
  $candidat = Choisir-Candidat -Gpu $gpu -RamGo $ram

  _M-Info "Materiel : carte=$($gpu.Nom) | VRAM=$($gpu.VramGo) Go | RAM libre=$ram Go"
  _M-Info "Candidat : $($candidat.Raison)"

  $profil = @{
    Backend = $candidat.Backend; ModeleChat = $candidat.ModeleChat; ModeleEmbed = $candidat.ModeleEmbed
    Raison = $candidat.Raison; Gpu = $gpu; RamGo = $ram; Probe = $null
    # Leve a $true si une carte NVIDIA est presente mais que l'essai GPU
    # echoue : mettre a jour le pilote pourrait la rendre utilisable. Le
    # lanceur s'en sert pour PROPOSER la mise a jour (l'utilisateur decide).
    MajGpuPossible = $false
  }

  if (-not $AvecProbe) { return $profil }
  if (-not $Ollama) { $profil.Raison += " (probe sautee : Ollama introuvable)"; return $profil }

  # Cas GPU : on ESSAIE pour de vrai, et on bascule au CPU si quoi que ce soit cloche.
  if ($candidat.Backend -eq "gpu") {
    _M-Titre "Essai reel sur GPU ($($candidat.ModeleChat))"
    $essai = Tester-Modele -Ollama $Ollama -Modele $candidat.ModeleChat -TimeoutSec 150 -Url $Url
    $profil.Probe = $essai
    $gpuBon = $essai.OK -and $essai.Coherent -and ($essai.Processeur -eq "GPU" -or $essai.Processeur -eq "MIXTE")
    if ($gpuBon) {
      _M-OK "GPU valide en $($essai.Secondes)s sur $($essai.Processeur). $($essai.Detail)"
      return $profil
    }
    # Diagnostic precis du pourquoi on retombe au CPU.
    if (-not $essai.OK)            { _M-Avert "GPU : le backend a echoue ($($essai.Detail)). Repli CPU." }
    elseif (-not $essai.Coherent) { _M-Avert "GPU : reponse incoherente / charabia ($($essai.Detail)). Repli CPU." }
    else                          { _M-Avert "GPU : Ollama a calcule sur $($essai.Processeur), pas sur le GPU. Repli CPU assume." }

    # Une carte NVIDIA est la mais l'essai a echoue : tres souvent un pilote
    # trop ancien pour le CUDA d'Ollama (cas vu sur RTX 3060 Laptop, pilote
    # 461.79). On le SIGNALE pour que le lanceur PROPOSE une mise a jour ;
    # on ne met jamais a jour sans l'accord de l'utilisateur.
    if ($gpu.Vendeur -eq "nvidia") { $profil.MajGpuPossible = $true }

    # Bascule : on fabrique la variante CPU et on la prend.
    $base = $candidat.ModeleCpuBase
    $cibleCpu = "$base-cpu"
    Assurer-VarianteCpu -Ollama $Ollama -Base $base -Cible $cibleCpu -DossierTravail $DossierTravail
    $profil.Backend = "cpu"; $profil.ModeleChat = $cibleCpu; $profil.ModeleEmbed = "nomic-embed-cpu"
    $profil.Raison = "GPU teste mais inutilisable -> bascule CPU sur $cibleCpu (filet de securite)."
  }

  # Cas CPU (d'origine ou apres bascule) : on prepare et on verifie le filet.
  if ($profil.Backend -eq "cpu") {
    Assurer-VarianteCpu -Ollama $Ollama -Base $candidat.ModeleCpuBase -Cible $profil.ModeleChat -DossierTravail $DossierTravail
    Assurer-VarianteCpu -Ollama $Ollama -Base "nomic-embed-text" -Cible "nomic-embed-cpu" -DossierTravail $DossierTravail
    _M-Titre "Verification du filet CPU ($($profil.ModeleChat))"
    $essaiCpu = Tester-Modele -Ollama $Ollama -Modele $profil.ModeleChat -TimeoutSec 180 -Url $Url
    $profil.Probe = $essaiCpu
    if ($essaiCpu.OK -and $essaiCpu.Coherent) {
      _M-OK "CPU valide en $($essaiCpu.Secondes)s. $($essaiCpu.Detail)"
    } elseif ($essaiCpu.OK) {
      _M-Avert "CPU repond mais incoherent ($($essaiCpu.Detail)). A surveiller."
    } else {
      _M-Souci "CPU ne repond pas ($($essaiCpu.Detail)). Probleme Ollama a regler."
    }
  }

  return $profil
}

# --- ETAPE 5 : BENCHMARK (option avancee) -------------------------------------
# Au lieu de DEVINER une taille, on MONTE progressivement : on part du plus
# petit modele et on garde le PLUS GROS qui (a) tient sur le bon moteur ET
# (b) reste assez rapide. Des qu'un etage deborde (OOM/erreur), tombe sur le
# mauvais processeur, ou passe sous le seuil de vitesse, on s'arrete et on
# garde le precedent. C'est ainsi qu'on trouve la limite REELLE de la machine.
$script:ECHELLE_MODELES = @(
  @{ nom = "qwen3:1.7b"; vramMin = 2;  ramMin = 4  },
  @{ nom = "qwen3:4b";   vramMin = 4;  ramMin = 6  },
  @{ nom = "qwen3:8b";   vramMin = 7;  ramMin = 11 },
  @{ nom = "qwen3:14b";  vramMin = 11; ramMin = 18 }
)

function Benchmarker-Machine {
  param([string]$Ollama, [string]$DossierTravail = $env:TEMP, [string]$Url = "http://localhost:11434", [switch]$Telecharger)

  $gpu = Detecter-Gpu
  $ram = Detecter-RamLibreGo
  # Seuil de vitesse confortable (jetons/seconde). En dessous, on arrete de
  # monter : trop lent pour un usage agreable. Reglable via CHEF_BENCH_MIN_JPS.
  $seuil = 12.0
  if ($env:CHEF_BENCH_MIN_JPS) { [double]::TryParse($env:CHEF_BENCH_MIN_JPS, [ref]$seuil) | Out-Null }

  $profil = @{
    Backend = "cpu"; ModeleChat = $null; ModeleEmbed = "nomic-embed-cpu"; Raison = "";
    Gpu = $gpu; RamGo = $ram; Probe = $null; MajGpuPossible = $false; Banc = @()
  }
  _M-Info "Benchmark : carte=$($gpu.Nom) | VRAM=$($gpu.VramGo) Go | RAM libre=$ram Go | seuil=$seuil j/s"

  # 1) Le GPU est-il utilisable du tout ? (essai du plus petit modele)
  $gpuUtilisable = $false
  if ($gpu.Vendeur -eq "nvidia" -and $gpu.VramGo -ge 2) {
    _M-Titre "Le GPU est-il utilisable ? (essai qwen3:1.7b)"
    $t0 = Tester-Modele -Ollama $Ollama -Modele "qwen3:1.7b" -TimeoutSec 150 -Url $Url
    if ($t0.OK -and $t0.Coherent -and ($t0.Processeur -eq "GPU" -or $t0.Processeur -eq "MIXTE")) {
      $gpuUtilisable = $true; _M-OK "GPU utilisable ($($t0.Vitesse) j/s sur $($t0.Processeur))."
    } else {
      _M-Avert "GPU inutilisable (souvent pilote trop vieux). Benchmark sur processeur."
      $profil.MajGpuPossible = $true
    }
  }

  # 2) Montee en taille sur le bon moteur.
  $meilleur = $null
  if ($gpuUtilisable) {
    $profil.Backend = "gpu"; $profil.ModeleEmbed = "nomic-embed-text"
    foreach ($etage in $script:ECHELLE_MODELES) {
      if ($etage.vramMin -gt $gpu.VramGo) { _M-Info "$($etage.nom) : ignore (besoin ~$($etage.vramMin) Go VRAM > $($gpu.VramGo) Go). Limite atteinte."; break }
      $present = (& $Ollama list 2>$null) -join "`n"
      if (($present -notmatch [regex]::Escape($etage.nom)) -and (-not $Telecharger)) { _M-Info "$($etage.nom) : absent et telechargement off -> stop."; break }
      _M-Titre "Essai $($etage.nom) sur GPU"
      $t = Tester-Modele -Ollama $Ollama -Modele $etage.nom -TimeoutSec 300 -Url $Url
      $profil.Banc += @{ modele = $etage.nom; ok = $t.OK; coherent = $t.Coherent; proc = $t.Processeur; vitesse = $t.Vitesse }
      if (-not ($t.OK -and $t.Coherent -and ($t.Processeur -eq "GPU" -or $t.Processeur -eq "MIXTE"))) { _M-Avert "$($etage.nom) : ne tient pas sur GPU. On garde le precedent."; break }
      if ($t.Vitesse -lt $seuil) { _M-Avert "$($etage.nom) : trop lent ($($t.Vitesse) < $seuil j/s). On garde le precedent."; break }
      _M-OK "$($etage.nom) : OK sur GPU a $($t.Vitesse) j/s -> retenu, on tente plus gros."
      $meilleur = $etage.nom; $profil.Probe = $t
    }
    if ($meilleur) { $profil.ModeleChat = $meilleur; $profil.Raison = "Benchmark GPU : plus gros modele rapide qui tient = $meilleur (seuil $seuil j/s)."; return $profil }
    _M-Avert "Aucun etage GPU retenu, repli CPU."
    $profil.Backend = "cpu"; $profil.ModeleEmbed = "nomic-embed-cpu"
  }

  # 3) Benchmark CPU : variantes -cpu (num_gpu 0). Monter en taille rend plus
  # lent, donc on garde naturellement le plus petit rapide.
  Assurer-VarianteCpu -Ollama $Ollama -Base "nomic-embed-text" -Cible "nomic-embed-cpu" -DossierTravail $DossierTravail
  foreach ($etage in $script:ECHELLE_MODELES) {
    if ($etage.ramMin -gt $ram) { _M-Info "$($etage.nom) : ignore (besoin ~$($etage.ramMin) Go RAM > $ram Go). Limite atteinte."; break }
    $present = (& $Ollama list 2>$null) -join "`n"
    if (($present -notmatch [regex]::Escape($etage.nom)) -and (-not $Telecharger)) { _M-Info "$($etage.nom) : base absente, telechargement off -> stop."; break }
    $cible = "$($etage.nom)-cpu"
    Assurer-VarianteCpu -Ollama $Ollama -Base $etage.nom -Cible $cible -DossierTravail $DossierTravail
    _M-Titre "Essai $cible (processeur)"
    $t = Tester-Modele -Ollama $Ollama -Modele $cible -TimeoutSec 360 -Url $Url
    $profil.Banc += @{ modele = $cible; ok = $t.OK; coherent = $t.Coherent; proc = $t.Processeur; vitesse = $t.Vitesse }
    if (-not ($t.OK -and $t.Coherent)) { _M-Avert "$cible : echec ($($t.Detail)). On garde le precedent."; break }
    if ($t.Vitesse -lt $seuil) { _M-Avert "$cible : trop lent ($($t.Vitesse) < $seuil j/s). On garde le precedent."; break }
    _M-OK "$cible : OK a $($t.Vitesse) j/s -> retenu, on tente plus gros."
    $meilleur = $cible; $profil.Probe = $t
  }
  if (-not $meilleur) {
    # Filet ultime : le plus petit en CPU, sans condition de vitesse (mieux
    # vaut lent que rien). C'est la garantie "ca marche toujours".
    $meilleur = "qwen3:1.7b-cpu"
    Assurer-VarianteCpu -Ollama $Ollama -Base "qwen3:1.7b" -Cible $meilleur -DossierTravail $DossierTravail
    $profil.Raison = "Benchmark : aucun modele au-dessus du seuil -> filet $meilleur (ca marche toujours)."
  } else {
    $profil.Raison = "Benchmark CPU : plus gros modele rapide = $meilleur (seuil $seuil j/s)."
  }
  $profil.ModeleChat = $meilleur
  return $profil
}

# --- Execution directe (audit / probe / benchmark) ------------------------
if ($Audit -or $Probe -or $Benchmark) {
  Write-Host "Le Pupitre - auto-adaptation materielle" -ForegroundColor White
  $ollamaExe = Trouver-OllamaExe -Indice $OllamaPath
  if ($ollamaExe) { _M-Info "Ollama : $ollamaExe" } else { _M-Avert "Ollama introuvable (l'audit reste possible)" }

  if ($Benchmark) {
    $profil = Benchmarker-Machine -Ollama $ollamaExe -DossierTravail $env:TEMP -Url $OllamaUrl -Telecharger:$Telecharger
  } else {
    $profil = Resoudre-Profil -Ollama $ollamaExe -DossierTravail $env:TEMP -AvecProbe:$Probe -Url $OllamaUrl
  }

  if ($profil.Banc -and $profil.Banc.Count -gt 0) {
    _M-Titre "BANC D'ESSAI (du plus petit au plus gros)"
    foreach ($e in $profil.Banc) {
      $etat = if ($e.ok -and $e.coherent) { "OK " } else { "KO " }
      _M-Info ("{0} {1,-16} {2,-5} {3,6} j/s" -f $etat, $e.modele, $e.proc, $e.vitesse)
    }
  }

  _M-Titre "PROFIL RETENU"
  _M-Info ("Backend     : " + $profil.Backend)
  _M-Info ("Modele chat : " + $profil.ModeleChat)
  _M-Info ("Embeddings  : " + $profil.ModeleEmbed)
  _M-Info ("Raison      : " + $profil.Raison)
  # Sortie machine (pour le lanceur) : une ligne JSON facile a relire.
  $json = @{ backend = $profil.Backend; chat = $profil.ModeleChat; embed = $profil.ModeleEmbed } | ConvertTo-Json -Compress
  Write-Host "PROFIL_JSON=$json" -ForegroundColor DarkGray
}
