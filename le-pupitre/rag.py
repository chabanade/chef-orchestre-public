# -*- coding: utf-8 -*-
"""
La premiere competence du Pupitre : le RAG LOCAL.

RAG = "Retrieval Augmented Generation" : repondre a partir des PROPRES documents
de l'utilisateur (dossiers PDF, notes...). C'est le plus gros saut de puissance
vers l'experience "Claude Code", et le faire SANS fuite est tout l'enjeu.

Comment la confidentialite est tenue :
  1. INGESTION : le document est decoupe en morceaux ; chaque morceau est
     transforme en vecteur (embedding) par un modele d'embedding LOCAL, appele
     via le routeur (Chef d'Orchestre) sur une route locale. Le texte ne part
     JAMAIS au cloud. Morceaux + vecteurs sont ranges dans le coffre CHIFFRE.
  2. QUESTION : la question est vectorisee (toujours en local), comparee aux
     morceaux par similarite cosinus (calcul pur Python, en local), et les
     meilleurs extraits sont injectes dans le prompt envoye au routeur, qui
     decide ensuite local/cloud selon sa regle (un extrait sensible -> local).

Pur stdlib pour la logique (decoupage, cosinus) : testable sans rien installer.
L'embedder fait un appel HTTP au routeur (urllib) ; il est remplacable par un
faux pour les tests.
"""

import json
import math
import os
import urllib.error
import urllib.request


# ------------------------------------------------------------------
# Decoupage en morceaux (fenetres glissantes, coupees sur des espaces)
# ------------------------------------------------------------------
def decouper(texte, taille=1000, chevauchement=150):
    """Coupe `texte` en morceaux d'environ `taille` caracteres qui se
    chevauchent (pour ne pas casser une idee a la frontiere). On essaie de
    couper sur un espace proche pour ne pas trancher un mot en deux."""
    texte = (texte or "").strip()
    if not texte:
        return []
    if len(texte) <= taille:
        return [texte]
    morceaux = []
    debut = 0
    n = len(texte)
    while debut < n:
        fin = min(debut + taille, n)
        if fin < n:
            espace = texte.rfind(" ", debut + taille - chevauchement, fin)
            if espace > debut:
                fin = espace
        morceaux.append(texte[debut:fin].strip())
        if fin >= n:
            break
        debut = max(fin - chevauchement, debut + 1)
    return [m for m in morceaux if m]


# ------------------------------------------------------------------
# Similarite cosinus (pur Python : suffisant a l'echelle d'un cabinet)
# ------------------------------------------------------------------
def cosinus(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    produit = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return produit / (na * nb)


# ------------------------------------------------------------------
# L'embedder : vectorise un texte via un modele LOCAL, par le routeur
# ------------------------------------------------------------------
class Embedder:
    """Appelle l'endpoint /v1/embeddings du routeur, sur une route LOCALE.

    Le modele d'embedding (ex. nomic-embed-text servi par Ollama) doit etre
    declare comme route locale dans config.yaml et liste dans
    CHEF_ROUTES_LOCALES : ainsi le Chef d'Orchestre laisse passer (local) et
    REFUSERAIT un embedding vers le cloud. Le texte des documents reste donc
    sur la machine par construction.
    """

    def __init__(self, base_url, cle, modele, timeout=120):
        self.base_url = base_url
        self.cle = cle
        self.modele = modele
        self.timeout = timeout

    def vecteur(self, texte):
        return self.vecteurs([texte])[0]

    def vecteurs(self, textes):
        url = self.base_url.rstrip("/") + "/v1/embeddings"
        corps = json.dumps({"model": self.modele, "input": list(textes)}).encode("utf-8")
        demande = urllib.request.Request(url, data=corps, method="POST")
        demande.add_header("Content-Type", "application/json")
        if self.cle:
            demande.add_header("Authorization", "Bearer " + self.cle)
        try:
            with urllib.request.urlopen(demande, timeout=self.timeout) as rep:
                charge = json.loads(rep.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RagErreur(
                "Embedder local injoignable a %s. Modele d'embedding installe "
                "(ex. ollama pull nomic-embed-text) et route locale declaree ?" % self.base_url
            ) from exc
        # Format OpenAI : {"data": [{"embedding": [...]}, ...]} dans l'ordre
        try:
            return [d["embedding"] for d in charge["data"]]
        except (KeyError, TypeError) as exc:
            raise RagErreur("Reponse d'embedding au format inattendu.") from exc


class RagErreur(RuntimeError):
    pass


# ------------------------------------------------------------------
# La bibliotheque : ingerer des documents, retrouver les bons extraits
# ------------------------------------------------------------------
class Bibliotheque:
    """Relie le coffre chiffre (stockage) et l'embedder (vecteurs)."""

    def __init__(self, coffre, embedder):
        self.coffre = coffre
        self.embedder = embedder

    def ingerer(self, source, texte):
        """Decoupe, vectorise (local) et range un document. Renvoie le nb de morceaux."""
        morceaux = decouper(texte)
        if not morceaux:
            return 0
        vecteurs = self.embedder.vecteurs(morceaux)
        for i, (m, v) in enumerate(zip(morceaux, vecteurs)):
            self.coffre.ajouter_chunk(source, i, m, json.dumps(v))
        return len(morceaux)

    def interroger(self, question, k=4):
        """Retourne les k morceaux les plus proches de la question :
        liste de dicts {source, contenu, score}. Vectorisation en LOCAL."""
        corpus = self.coffre.chunks()
        if not corpus:
            return []
        qv = self.embedder.vecteur(question)
        notes = []
        for c in corpus:
            try:
                vec = json.loads(c["vecteur"])
            except (ValueError, TypeError):
                continue
            notes.append((cosinus(qv, vec), c))
        notes.sort(key=lambda t: t[0], reverse=True)
        return [
            {"source": c["source"], "contenu": c["contenu"], "score": round(s, 4)}
            for (s, c) in notes[:k]
        ]


# ------------------------------------------------------------------
# Le contexte injecte dans le prompt (transparent et borne)
# ------------------------------------------------------------------
def construire_contexte(extraits):
    """Fabrique le message systeme qui porte les extraits retrouves.

    On dit explicitement au modele de ne repondre QUE sur la base des extraits
    et d'avouer s'ils ne suffisent pas : c'est la regle anti-invention,
    transposee au RAG (mieux vaut "le dossier ne le dit pas" qu'une reponse
    plausible mais fausse)."""
    if not extraits:
        return None
    blocs = []
    for i, e in enumerate(extraits, 1):
        blocs.append("[Extrait %d - %s]\n%s" % (i, e["source"], e["contenu"]))
    return (
        "Voici des extraits des documents de l'utilisateur. Reponds a la question "
        "UNIQUEMENT a partir de ces extraits. Si les extraits ne suffisent pas, "
        "dis-le clairement plutot que d'inventer. Cite la source utilisee.\n\n"
        + "\n\n".join(blocs)
    )


# ------------------------------------------------------------------
# Extraction du texte d'un fichier (.txt/.md en stdlib, .pdf en option)
# ------------------------------------------------------------------
def extraire_texte_fichier(chemin, donnees=None):
    """Texte d'un fichier. `donnees` = octets deja lus (upload) ; sinon on lit
    `chemin`. .txt/.md en pur stdlib ; .pdf via pypdf (import paresseux)."""
    ext = os.path.splitext(chemin)[1].lower()
    if ext == ".pdf":
        return _texte_pdf(chemin, donnees)
    if donnees is not None:
        return donnees.decode("utf-8", errors="replace")
    with open(chemin, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _texte_pdf(chemin, donnees):
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RagErreur(
            "Lecture PDF : le paquet 'pypdf' n'est pas installe (cf requirements)."
        ) from exc
    import io
    source = io.BytesIO(donnees) if donnees is not None else chemin
    lecteur = PdfReader(source)
    return "\n".join((page.extract_text() or "") for page in lecteur.pages)
