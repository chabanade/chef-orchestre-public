# -*- coding: utf-8 -*-
"""
Le cerveau de la serrure : detection de sensibilite et de complexite.

Fichier en Python PUR (aucune dependance) : testable sur n'importe quelle
machine avec `python test_detection.py`, sans rien installer.
La plomberie LiteLLM, elle, vit dans chef_orchestre_hook.py.
"""

import json
import os
import re
import time

import vigie


def _env_int(nom, defaut):
    """Lit un entier dans l'environnement ; valeur malformee -> defaut (jamais de crash)."""
    try:
        return int(os.environ.get(nom, defaut))
    except (TypeError, ValueError):
        return defaut


def _env_float(nom, defaut):
    try:
        return float(os.environ.get(nom, defaut))
    except (TypeError, ValueError):
        return defaut


SEUIL_COMPLEXITE_CARACTERES = _env_int("CHEF_SEUIL_LOURD", 4000)
JOURNAL = os.environ.get("CHEF_JOURNAL", os.path.join(os.path.dirname(__file__), "journal-routage.jsonl"))

# Codes "techniques" : ils forcent la prudence (local) sans signifier qu'une
# donnee sensible a ete VUE. Le hook s'en sert pour adapter son message.
CODES_TECHNIQUES = {
    "loupe-en-panne",
    "detection-en-panne",
    "contenu-non-inspectable",
    "langue-non-identifiee",
    "identifiant-inconnu",
}

# Codes "couverture" (la vigie) : le document sort des cases connues du
# routeur -> prudence + ALERTE "demande de mise a jour" (packs-pays/).
PREFIXES_COUVERTURE = ("ecriture-non-couverte:", "pack-en-panne:",
                       "langue-non-identifiee", "identifiant-inconnu")


def est_technique(code):
    """Prudence sans donnee VUE : codes techniques et codes couverture."""
    return code in CODES_TECHNIQUES or code.startswith(("ecriture-non-couverte:", "pack-en-panne:"))


def est_couverture(code):
    """Ce code signifie-t-il "hors des cases connues" (mise a jour a demander) ?"""
    return code.startswith(PREFIXES_COUVERTURE)

# ------------------------------------------------------------------
# Detection de SENSIBILITE (v1 : regles lisibles et auditables)
# Chaque motif a un code court : c'est le code qui va au journal,
# JAMAIS la valeur detectee.
# ------------------------------------------------------------------
MOTIFS_REGEX = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}"),
    # (?<!\d) : un vrai numero n'est jamais colle derriere un chiffre ; sans
    # ce garde, la regex matchait AU MILIEU d'un numero de TVA (FR40123456824).
    "telephone_fr": re.compile(r"(?<!\d)(?:\+33\s?|0)[1-9](?:[\s.-]?\d{2}){4}\b"),
    # IGNORECASE : un IBAN tape en minuscules reste un IBAN (trou trouve en revue).
    # {2,7} et non {4,7} : les IBAN COURTS (Belgique 16, Pays-Bas 18, Norvege 15)
    # passaient au travers — trou trouve par la question "client etranger" du 12/06.
    "iban": re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,3})?\b", re.IGNORECASE),
    "numero_securite_sociale": re.compile(r"\b[12]\s?\d{2}\s?(?:0[1-9]|1[0-2]|62|63)\s?(?:\d{2}|2A|2B)\s?\d{3}\s?\d{3}(?:\s?\d{2})?\b"),
    "siret": re.compile(r"\b\d{3}[ ]?\d{3}[ ]?\d{3}[ ]?\d{5}\b"),
    # Volontairement large (toute suite 4x4 chiffres) : un faux positif coute
    # quelques secondes de local, un faux negatif coute une fuite.
    # La 2e alternative couvre l'Amex (15 chiffres en 4-6-5, commence par 34/37).
    "carte_bancaire": re.compile(r"\b(?:\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}|3[47]\d{2}[ -]?\d{6}[ -]?\d{5})\b"),
    # TVA intracommunautaire FR (FR + cle 2 caracteres + SIREN 9 chiffres).
    # Identifie l'entreprise, comme le SIRET : meme traitement. Pas de
    # collision avec l'IBAN FR : ici les 11 caracteres apres FR sont colles,
    # et un IBAN compact a un chiffre derriere qui fait echouer le \b final.
    "tva_fr": re.compile(r"\bFR[A-Z0-9]{2}\d{9}\b", re.IGNORECASE),
    # ------------------------------------------------------------------
    # CLIENT ETRANGER (12/06 soir) : un professionnel francais a des
    # clients/patients etrangers. Couverture par STRUCTURE de format
    # (pas pays par pays), formats distinctifs seulement ; le filet pour
    # tout le reste = la loupe (GLiNER, multilingue, par le sens) et le
    # 2e rideau Presidio. Un faux positif = local, jamais grave.
    # ------------------------------------------------------------------
    # TVA des autres pays de l'UE (prefixe pays + 8 a 12 alphanum colles).
    # Un IBAN compact ne matche pas : il a toujours des chiffres derriere
    # qui font echouer le \b (meme logique que tva_fr).
    "tva_ue": re.compile(
        r"\b(?:AT|BE|BG|CY|CZ|DE|DK|EE|EL|ES|FI|HR|HU|IE|IT|LT|LU|LV|MT|NL|PL|PT|RO|SE|SI|SK|XI)"
        r"[A-Z0-9]{8,12}\b", re.IGNORECASE),
    # SSN americain : le format a tirets 3-2-4 est distinctif.
    "ssn_us": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    # AVS/AHV suisse : 13 chiffres commencant par 756 (le code pays ISO).
    "avs_suisse": re.compile(r"\b756[.\s]?\d{4}[.\s]?\d{4}[.\s]?\d{2}\b"),
    # Codice fiscale italien : 16 caracteres tres structures (PACA oblige).
    "codice_fiscale_it": re.compile(r"\b[A-Za-z]{6}\d{2}[A-Za-z]\d{2}[A-Za-z]\d{3}[A-Za-z]\b"),
    # Telephone international : +indicatif (E.164) ou prefixe 00. Le "+"
    # ou le "00" de tete rend le motif sur, quel que soit le pays.
    # (?<!\d) : ne pas matcher dans "2+1234567" (addition) ni mi-numero.
    "telephone_international": re.compile(r"(?<!\d)(?:\+|\b00)[1-9](?:[\s.\-]?\d){6,13}\d\b"),
}

# Motifs CONTEXTUELS (idee reprise de PII-Shield, MIT) : un motif trop
# generique pour decider seul (12 chiffres = peut-etre une CNI, peut-etre un
# numero de commande) ne compte que si un mot de contexte l'accompagne dans
# le meme texte. Les deux signaux ensemble = sensible ; le mot seul est deja
# couvert par MOTS_CLES_SENSIBLES (le routage reste prudent de toute facon).
# Formats VERIFIES (Purview/service-public, 12/06/2026) :
#   - CNI (ancien format) : 12 chiffres ;
#   - passeport francais : 2 chiffres + 2 lettres + 5 chiffres (PII-Shield
#     ne couvre que des formats generiques UE, le notre est le bon) ;
#     les variantes UE de PII-Shield sont gardees en complement.
MOTIFS_CONTEXTUELS = {
    "cni_fr": (
        re.compile(r"\b\d{12}\b"),
        ["carte nationale", "carte d'identite", "carte d'identité",
         "piece d'identite", "pièce d'identité", "cni"],
    ),
    # Passeports : format FR verifie (2 chiffres + 2 lettres + 5 chiffres)
    # + variantes internationales courantes (2 lettres + 7 chiffres ;
    # 1 lettre + 8 chiffres, ex. USA recent ; 9 chiffres, ex. USA ancien).
    "passeport_fr": (
        re.compile(r"\b(?:\d{2}[A-Za-z]{2}\d{5}|[A-Za-z]{2}\d{7}|[A-Za-z]\d{8}|\d{9})\b"),
        ["passeport", "passport"],
    ),
    # NINO britannique (2 lettres + 6 chiffres + 1 lettre, souvent espace
    # par paires) : assez generique pour exiger son mot de contexte.
    "nino_uk": (
        re.compile(r"\b[A-Za-z]{2}\s?(?:\d{2}\s?){3}[A-Da-d]\b"),
        ["national insurance", "nino"],
    ),
}

# Vocabulaire du secret professionnel (avocat, sante, comptable).
# En cas de doute, on prefere un faux positif (reste en local, ca coute
# quelques secondes) a un faux negatif (fuite vers le cloud, irreversible).
MOTS_CLES_SENSIBLES = [
    "patient", "diagnostic", "medical", "médical", "ordonnance", "mutuelle",
    "dossier client", "n° de dossier", "numero de dossier", "confidentiel",
    "secret professionnel", "salaire", "fiche de paie", "rib", "iban", "bic",
    "coordonnees bancaires", "coordonnées bancaires", "succession",
    "divorce", "plainte", "garde a vue", "garde à vue", "piece d'identite",
    "pièce d'identité", "passeport", "carte vitale", "adresse personnelle",
    "carte d'identite", "carte d'identité", "carte nationale", "cni",
    # Le mot "securite sociale" seul (sans numero bien forme) doit suffire.
    "securite sociale", "sécurité sociale", "numero de secu", "numéro de sécu",
    # Client/dossier etranger redige en anglais : les mots du secret
    # professionnel anglophone les plus discriminants.
    "social security", "confidential", "medical record", "attorney-client",
    "privileged", "payroll", "passport",
]

MOTS_CLES_LOURDS = [
    "redige un rapport", "rédige un rapport", "analyse approfondie",
    "synthese complete", "synthèse complète", "strategie", "stratégie",
    "business plan", "plan detaille", "plan détaillé", "compare en detail",
    "etude de marche", "étude de marché", "argumentaire complet",
]

# Mots courts ou ambigus : detectes en mot entier pour eviter les faux
# positifs dans un mot plus long (ex. "rib" dans "courrier ou ruban").
_MOTS_ENTIERS = {"rib", "iban", "bic", "patient", "salaire", "passeport", "succession", "divorce", "plainte", "confidentiel", "cni"}


def _present(mot, texte_minuscule):
    if mot in _MOTS_ENTIERS:
        return re.search(r"\b" + re.escape(mot) + r"\b", texte_minuscule) is not None
    return mot in texte_minuscule


def contexte_present(contextes, texte_minuscule):
    """Un des mots de contexte est-il present ? (partage avec le greffier)."""
    return any(_present(mot, texte_minuscule) for mot in contextes)


# ------------------------------------------------------------------
# PACKS PAYS (12/06 soir) : l'amelioration continue, sous GO humain.
# Un pack (packs-pays/<nom>.json) AJOUTE des motifs, des contextuels et
# des mots-cles pour un pays : il ne peut jamais RETIRER une detection
# (surface sure par construction). Activation : CHEF_PACKS_PAYS=bresil,inde
# dans .env — c'est le geste de l'utilisateur, jamais celui de la machine.
# Auto-test au chargement : chaque regex doit compiler ET reconnaitre son
# propre exemple, sinon le pack ENTIER est refuse et signale ; un pack
# demande mais en panne = promesse de couverture non tenue = TOUT reste
# en local tant que ce n'est pas repare (fail-closed).
# ------------------------------------------------------------------
PACKS_DEMANDES = [p.strip() for p in os.environ.get("CHEF_PACKS_PAYS", "").split(",") if p.strip()]
CLASSES_PACKS = []   # codes directs des packs, jetonnables par le greffier
PACKS_STATUT = []    # ["pack-en-panne:<nom>"] si un pack demande a echoue
PACKS_CHARGES = []   # noms des packs actifs (pour le journal)


def charger_pack(donnees, nom):
    """Valide PUIS enrichit (atomique : un pack invalide n'ajoute rien).
    Leve ValueError si le pack est invalide."""
    valides_directs, valides_contextuels = {}, {}
    for code, motif in (donnees.get("motifs") or {}).items():
        regex = re.compile(motif["regex"], re.IGNORECASE if motif.get("ignorecase") else 0)
        if not regex.search(motif["exemple"]):
            raise ValueError("motif %s : l'exemple ne matche pas sa propre regex" % code)
        valides_directs[code] = regex
    for code, motif in (donnees.get("motifs_contextuels") or {}).items():
        regex = re.compile(motif["regex"], re.IGNORECASE if motif.get("ignorecase") else 0)
        if not regex.search(motif["exemple"]):
            raise ValueError("motif contextuel %s : l'exemple ne matche pas" % code)
        if not motif.get("contextes"):
            raise ValueError("motif contextuel %s : aucun mot de contexte" % code)
        valides_contextuels[code] = (regex, list(motif["contextes"]))
    # Tout est valide : on enrichit (ajout seulement, jamais de retrait).
    MOTIFS_REGEX.update(valides_directs)
    CLASSES_PACKS.extend(valides_directs)
    MOTIFS_CONTEXTUELS.update(valides_contextuels)
    for mot in donnees.get("mots_cles") or []:
        MOTS_CLES_SENSIBLES.append(mot)
        if len(mot) <= 4:  # mots courts : detection en mot entier
            _MOTS_ENTIERS.add(mot)
    PACKS_CHARGES.append(nom)


def _charger_packs_demandes():
    dossier = os.path.join(os.path.dirname(__file__), "packs-pays")
    for nom in PACKS_DEMANDES:
        try:
            chemin = os.path.join(dossier, nom + ".json")
            with open(chemin, "r", encoding="utf-8") as fichier:
                charger_pack(json.load(fichier), nom)
        except Exception:  # introuvable, JSON casse, regex invalide, exemple rate
            PACKS_STATUT.append("pack-en-panne:" + nom)


_charger_packs_demandes()


# ------------------------------------------------------------------
# Extraction du texte d'une demande (tous formats connus de LiteLLM)
# Pur Python : testable sans LiteLLM.
# ------------------------------------------------------------------
def extraire_texte(data):
    """Concatene TOUT le texte d'une demande : messages, prompt (legacy), input.

    Retourne (texte, contenu_non_inspectable) : le second vaut True si la
    demande contient au moins un bloc que l'on ne sait pas lire (image,
    audio, fichier...). Ce qu'on ne peut pas inspecter, on ne le laisse
    pas sortir : le hook traite ce drapeau comme un motif sensible.
    """
    morceaux = []
    non_inspectable = False

    def _bloc(bloc):
        nonlocal non_inspectable
        if isinstance(bloc, str):
            morceaux.append(bloc)
        elif isinstance(bloc, dict):
            type_bloc = bloc.get("type", "")
            if type_bloc == "text" and isinstance(bloc.get("text"), str):
                morceaux.append(bloc["text"])
            else:  # image_url, image, input_audio, file, document...
                non_inspectable = True
        else:
            non_inspectable = True

    for message in data.get("messages") or []:
        if not isinstance(message, dict):
            non_inspectable = True
            continue
        contenu = message.get("content")
        if contenu is None:
            continue
        if isinstance(contenu, str):
            morceaux.append(contenu)
        elif isinstance(contenu, list):
            for bloc in contenu:
                _bloc(bloc)
        else:
            non_inspectable = True

    prompt = data.get("prompt")  # endpoint legacy /completions
    if isinstance(prompt, str):
        morceaux.append(prompt)
    elif isinstance(prompt, list):
        for element in prompt:
            _bloc(element)

    entree = data.get("input")  # endpoint /responses
    if isinstance(entree, str):
        morceaux.append(entree)
    elif isinstance(entree, list):
        for element in entree:
            if isinstance(element, dict) and isinstance(element.get("content"), list):
                for bloc in element["content"]:
                    _bloc(bloc)
            else:
                _bloc(element)

    return "\n".join(morceaux), non_inspectable


def detecter_sensibilite(texte):
    """Retourne la liste des CODES de motifs sensibles trouves (jamais les valeurs)."""
    codes = [code for code, regex in MOTIFS_REGEX.items() if regex.search(texte)]
    texte_minuscule = texte.lower()
    codes += ["mot-cle:" + mot for mot in MOTS_CLES_SENSIBLES if _present(mot, texte_minuscule)]
    # Motifs contextuels : la valeur generique ET son mot de contexte.
    codes += [
        code for code, (regex, contextes) in MOTIFS_CONTEXTUELS.items()
        if regex.search(texte) and contexte_present(contextes, texte_minuscule)
    ]
    return codes


_statut_loupe_journalise = False
_statut_packs_journalise = False


def detecter_sensibilite_complete(texte):
    """Serrure v1 (regles) + loupe (detection fine PII) si elle est disponible
    + la VIGIE (hors cases connues) + le statut des packs pays.

    La loupe COMPLETE les regles, elle ne les remplace pas (union des codes).
    Doctrine des pannes, sans ambiguite :
      - loupe ABSENTE (pas installee, ou CHEF_DETECTION_FINE=off) : choix
        d'exploitation assume -> regles seules, statut journalise une fois ;
      - loupe EN PANNE (chargee mais qui crashe, ou module casse) : anomalie
        -> code technique "loupe-en-panne" -> la demande reste en local ;
      - VIGIE : ecriture/langue hors couverture -> prudence + carnet
        d'alertes (demande de mise a jour, voir packs-pays/) ;
      - pack demande mais en panne -> promesse de couverture non tenue ->
        code permanent, tout reste en local tant que ce n'est pas repare.
    """
    global _statut_loupe_journalise, _statut_packs_journalise
    codes = detecter_sensibilite(texte)
    try:
        from detection_fine import detecter_sensibilite_fine, statut
        if not _statut_loupe_journalise:
            _statut_loupe_journalise = True
            journaliser("loupe-statut", None, None, [statut()], 0)
        codes += detecter_sensibilite_fine(texte)
    except ImportError:
        pass  # module fin absent du dossier : la serrure v1 suffit
    except Exception:  # module present mais casse : anomalie -> prudence
        codes += ["loupe-en-panne"]
    if PACKS_DEMANDES and not _statut_packs_journalise:
        _statut_packs_journalise = True
        journaliser("packs-statut", None, None,
                    ["actifs:" + ",".join(PACKS_CHARGES or ["aucun"])] + PACKS_STATUT, 0)
    codes_vigie = vigie.detecter_couverture(texte)
    if codes_vigie:
        vigie.signaler(codes_vigie, len(texte))
        codes += codes_vigie
    codes += PACKS_STATUT
    return codes


def detecter_complexite(texte):
    """Tache lourde ? (longueur ou vocabulaire de mission)."""
    if len(texte) > SEUIL_COMPLEXITE_CARACTERES:
        return ["longueur:" + str(len(texte))]
    texte_minuscule = texte.lower()
    return ["mot-cle:" + mot for mot in MOTS_CLES_LOURDS if _present(mot, texte_minuscule)]


def journaliser(decision, modele_demande, modele_final, motifs, taille):
    """Trace la decision SANS le contenu. Echec de journalisation = non bloquant."""
    try:
        ligne = {
            "horodatage": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "decision": decision,
            "modele_demande": modele_demande,
            "modele_final": modele_final,
            "motifs": motifs,
            "taille_caracteres": taille,
        }
        with open(JOURNAL, "a", encoding="utf-8") as fichier:
            fichier.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    except OSError:
        pass
