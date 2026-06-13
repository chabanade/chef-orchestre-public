# -*- coding: utf-8 -*-
"""
Le serveur du Pupitre : une petite appli web locale (FastAPI) qui relie
le coffre chiffre (coffre.py) au Chef d'Orchestre (relais.py), et sert la
page de chat dans le navigateur.

Multi-plateforme : c'est du Python + un navigateur. La meme commande lance
le Pupitre sur Windows, macOS et Linux ; on ouvre ensuite http://localhost:8800.

Modele de securite (v1, mono-utilisateur, poste local) :
  - la PASSPHRASE du coffre est fournie AU LANCEMENT (variable d'environnement
    CHEF_PUPITRE_PASSPHRASE, sinon saisie au terminal). Le navigateur ne la
    voit jamais ; il n'y a pas de cle cote client.
  - le serveur n'ecoute que sur 127.0.0.1 (pas expose au reseau).
  - le coffre, partage entre les threads du serveur, est protege par un verrou.
Combine au chiffrement du DISQUE (socle recommande), l'historique est protege
au repos meme si la machine est volee/eteinte.
"""

import os
import sys
import threading

try:
    from fastapi import FastAPI, File, HTTPException, UploadFile
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
except ImportError:
    sys.stderr.write(
        "[LE PUPITRE] FastAPI n'est pas installe. Lancer d'abord install/install"
        " (cf. README) pour creer l'environnement et installer les dependances.\n"
    )
    raise

import rag
import relais
from coffre import Coffre

# ------------------------------------------------------------------
# Configuration (tout via l'environnement ; aucune valeur en dur)
# ------------------------------------------------------------------
ICI = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("CHEF_PUPITRE_DB", os.path.join(ICI, "pupitre.db"))
BASE_URL = os.environ.get("CHEF_PUPITRE_BASE_URL", "http://localhost:4000")
CLE_ROUTEUR = os.environ.get("CHEF_PUPITRE_CLE", "")
MODELE = os.environ.get("CHEF_PUPITRE_MODELE", "chef-auto")
# Modele d'embedding LOCAL pour le RAG (doit etre une route LOCALE du routeur,
# listee dans CHEF_ROUTES_LOCALES : le texte des documents ne sort jamais).
MODELE_EMBED = os.environ.get("CHEF_PUPITRE_MODELE_EMBED", "local-embeddings")
EXIGER_CHIFFREMENT = os.environ.get("CHEF_PUPITRE_EXIGER_CHIFFREMENT", "1").strip() != "0"


def _obtenir_passphrase():
    """Variable d'environnement, sinon saisie masquee au terminal."""
    p = os.environ.get("CHEF_PUPITRE_PASSPHRASE")
    if p:
        return p
    import getpass
    return getpass.getpass("Passphrase du coffre Pupitre : ")


# Le coffre est ouvert UNE fois au demarrage ; un verrou serialise les acces
# (sqlite n'est pas garanti sur en multi-thread).
_coffre = Coffre(DB, _obtenir_passphrase(), exiger_chiffrement=EXIGER_CHIFFREMENT)
_verrou = threading.Lock()

# La bibliotheque RAG : meme coffre (corpus chiffre), embedder LOCAL via le routeur.
_biblio = rag.Bibliotheque(_coffre, rag.Embedder(BASE_URL, CLE_ROUTEUR, MODELE_EMBED))

app = FastAPI(title="Le Pupitre", docs_url=None, redoc_url=None)


class NouvelleConv(BaseModel):
    titre: str = "Nouvelle conversation"


class Envoi(BaseModel):
    conversation_id: int
    message: str
    rag: bool = False  # True = repondre en s'appuyant sur les documents charges


class RenommerConv(BaseModel):
    titre: str


@app.get("/")
def racine():
    return FileResponse(os.path.join(ICI, "static", "index.html"))


@app.get("/api/conversations")
def lister_conversations():
    with _verrou:
        return _coffre.conversations()


@app.post("/api/conversations")
def creer_conversation(corps: NouvelleConv):
    with _verrou:
        cid = _coffre.nouvelle_conversation(corps.titre)
    return {"id": cid, "titre": corps.titre}


@app.get("/api/conversations/{conversation_id}/messages")
def lire_messages(conversation_id: int):
    with _verrou:
        return _coffre.messages(conversation_id)


@app.patch("/api/conversations/{conversation_id}")
def renommer_conversation(conversation_id: int, corps: RenommerConv):
    titre = (corps.titre or "").strip()[:60] or "Sans titre"
    with _verrou:
        _coffre.renommer_conversation(conversation_id, titre)
    return {"id": conversation_id, "titre": titre}


@app.delete("/api/conversations/{conversation_id}")
def supprimer_conversation(conversation_id: int):
    with _verrou:
        _coffre.supprimer_conversation(conversation_id)
    return {"supprime": conversation_id}


@app.post("/api/envoyer")
def envoyer(corps: Envoi):
    """Sauve le message de l'utilisateur, relaie au routeur, sauve la reponse.

    Important : le message utilisateur est ENREGISTRE avant l'appel au routeur.
    Si le routeur refuse (fail-closed) ou est injoignable, on rend la RAISON du
    refus telle quelle (le Pupitre n'invente jamais une reponse) sans casser la
    conversation.
    """
    texte = (corps.message or "").strip()
    if not texte:
        raise HTTPException(status_code=400, detail="Message vide.")

    with _verrou:
        _coffre.ajouter_message(corps.conversation_id, "user", texte)
        historique = _coffre.messages(corps.conversation_id)

    # RAG : si demande, on retrouve les extraits pertinents des documents (en
    # LOCAL) et on les injecte en tete comme contexte. On enregistre le message
    # de l'utilisateur tel quel (sans le contexte) : le contexte est ephemere,
    # il ne pollue pas l'historique.
    if corps.rag:
        try:
            with _verrou:
                extraits = _biblio.interroger(texte, k=4)
            contexte = rag.construire_contexte(extraits)
        except rag.RagErreur as exc:
            return JSONResponse(status_code=200, content={"type": "refus", "message": str(exc)})
        if contexte:
            historique = [{"role": "system", "contenu": contexte}] + historique

    requete = relais.construire_requete(historique, MODELE)
    try:
        reponse = relais.envoyer(requete, BASE_URL, CLE_ROUTEUR)
    except relais.RelaisErreur as exc:
        # On AFFICHE le refus du routeur, on ne le masque pas. Il n'est PAS
        # enregistre comme un message d'assistant (ce n'en est pas un).
        return JSONResponse(
            status_code=200,
            content={"type": "refus", "message": str(exc), "detail": exc.detail},
        )

    if not reponse:
        return JSONResponse(
            status_code=200,
            content={"type": "vide", "message": "Le modele a renvoye une reponse vide."},
        )

    with _verrou:
        _coffre.ajouter_message(corps.conversation_id, "assistant", reponse)
    return {"type": "message", "role": "assistant", "contenu": reponse}


# ------------------------------------------------------------------
# Documents (RAG local) : deposer, lister, retirer. Tout reste chiffre,
# l'embedding se fait en local via le routeur.
# ------------------------------------------------------------------
@app.get("/api/documents")
def lister_documents():
    with _verrou:
        return _coffre.sources()


@app.post("/api/documents")
async def deposer_document(fichier: UploadFile = File(...)):
    donnees = await fichier.read()
    try:
        texte = rag.extraire_texte_fichier(fichier.filename, donnees=donnees)
    except rag.RagErreur as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not (texte or "").strip():
        raise HTTPException(status_code=400, detail="Document vide ou illisible.")
    try:
        with _verrou:
            n = _biblio.ingerer(fichier.filename, texte)
    except rag.RagErreur as exc:
        # Embedder local injoignable : on le DIT, on n'ingere pas a moitie.
        raise HTTPException(status_code=503, detail=str(exc))
    return {"source": fichier.filename, "morceaux": n}


@app.delete("/api/documents/{source}")
def retirer_document(source: str):
    with _verrou:
        _coffre.supprimer_source(source)
    return {"retire": source}


# Fichiers statiques (app.js, style.css) sous /static
app.mount("/static", StaticFiles(directory=os.path.join(ICI, "static")), name="static")


def main():
    import uvicorn
    port = int(os.environ.get("CHEF_PUPITRE_PORT", "8800"))
    etat = "CHIFFRE (SQLCipher)" if _coffre.chiffre else "EN CLAIR (dev !)"
    sys.stderr.write(
        "[LE PUPITRE] Coffre %s | routeur %s | modele %s\n"
        "[LE PUPITRE] Ouvre http://localhost:%d dans ton navigateur.\n"
        % (etat, BASE_URL, MODELE, port)
    )
    # host=127.0.0.1 : jamais expose au reseau.
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
