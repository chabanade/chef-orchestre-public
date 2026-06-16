# -*- coding: utf-8 -*-
"""
Version du produit + politique de mise a jour (OSSATURE).

Pose les fondations pour que le produit soit EVOLUTIF des le premier jour : on
developpe ici, on diffuse les ameliorations a toutes les installations sans tout
reinstaller. A ce stade (v0.1.0) on pose la STRUCTURE (numero de version, mode,
emplacement du canal) ; le serveur de diffusion et la signature seront branches
avec l'installeur de bureau. Voir maj/POLITIQUE-MISE-A-JOUR.md.

IMPORTANT : ce module ne fait AUCUN appel reseau. La verification reelle des
mises a jour (quand elle existera) ne transmettra qu'un numero de version,
jamais une donnee client (cf. politique, regle "aucune donnee ne sort").
"""

import os


def _lire_version():
    """Numero de version = fichier VERSION (racine du produit), source unique."""
    ici = os.path.dirname(os.path.abspath(__file__))
    for chemin in (os.path.join(ici, "VERSION"), os.path.join(ici, "..", "VERSION")):
        try:
            with open(chemin, "r", encoding="utf-8") as f:
                v = f.read().strip()
            if v:
                return v
        except OSError:
            continue
    return "0.0.0"


VERSION = _lire_version()

# Modes de mise a jour, AU CHOIX de l'utilisateur :
#   auto   : applique les MAJ signees automatiquement
#   manuel : signale "MAJ dispo", installe apres confirmation (defaut prudent)
#   jamais : fige la version (poste hors-ligne / cabinet qui veut maitriser)
MODES_MAJ = ("auto", "manuel", "jamais")


def mode_maj():
    m = (os.environ.get("CHEF_MAJ_MODE", "manuel") or "manuel").strip().lower()
    return m if m in MODES_MAJ else "manuel"


def canal_maj():
    """URL du MANIFESTE de releases signe (vide = aucun canal configure).

    La forme attendue du manifeste est decrite dans maj/manifest.exemple.json.
    """
    return (os.environ.get("CHEF_MAJ_CANAL", "") or "").strip()


def infos_version():
    """Resume affichable (interface, /api/version). Aucune donnee sensible.

    On RELIT le fichier VERSION a chaque appel (et non le cache du demarrage) :
    apres une mise a jour, le numero affiche doit refleter le fichier sans
    dependre d'un redemarrage parfaitement synchronise (produit evolutif)."""
    return {
        "version": _lire_version(),
        "mode_maj": mode_maj(),
        "canal_configure": bool(canal_maj()),
    }
