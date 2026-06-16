# -*- coding: utf-8 -*-
"""
Banc d'essai FR du detecteur PII : mesure le RAPPEL par type d'entite, en mode
STRICT (toute la valeur sensible couverte = vraiment masquee) et LARGE (au moins
reperee). Compare trois configurations sur le MEME jeu : regex maison seules,
Anonym-IA seul, et leur UNION (la doctrine du Chef d'Orchestre : aucun detecteur
seul, on unit).

Lancer (regex seules, Python pur, aucune installation) :
    python banc_essai_pii.py
Lancer avec Anonym-IA (dans un venv jetable : pip install transformers torch) :
    python banc_essai_pii.py --anonymia

Toutes les donnees sont FICTIVES. Resultats de reference : voir README.md.
"""
import collections
import os
import sys

# Importer la serrure (detection.py, Python pur) depuis le dossier parent.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import detection  # noqa: E402

MODELE = "Anonym-IA/V2-camembert-ner-pii-french"

# Anonym-IA (entity_group) -> type canonique du Chef d'Orchestre.
MAP_ANONYMIA = {
    "NOM_PERSONNE": "PERSONNE", "PRENOM_PERSONNE": "PERSONNE",
    "NUM_SECURITE_SOCIALE": "NIR", "IBAN": "IBAN", "EMAIL": "EMAIL",
    "TELEPHONE": "TELEPHONE", "CREDITCARD": "CARTE_BANCAIRE",
    "ACCOUNTNUMBER": "COMPTE", "NUM_DOSSIER": "DOSSIER",
    "REF_CADASTRALE": "CADASTRE", "NOM_SOCIETE": "ENTREPRISE",
    "DOB": "DATE_NAISSANCE", "DATE": "DATE_NAISSANCE",
    "NOM_VOIE": "ADRESSE", "NUMERO_VOIE": "ADRESSE",
    "CODE_POSTAL": "ADRESSE", "VILLE": "ADRESSE", "SECONDARYADDRESS": "ADRESSE",
}

# (phrase, [(type_canonique, valeur exacte a masquer), ...]). Donnees FICTIVES.
CAS = [
    ("Le patient Karim Benhassine est convoque le 3 juin.", [("PERSONNE", "Karim Benhassine")]),
    ("NIR du beneficiaire : 1 80 03 75 116 001 42.", [("NIR", "1 80 03 75 116 001 42")]),
    ("Numero de securite sociale 2750375116001 42 a verifier.", [("NIR", "2750375116001 42")]),
    ("Reglez sur l'IBAN FR76 3000 6000 0112 3456 7890 189.", [("IBAN", "FR76 3000 6000 0112 3456 7890 189")]),
    ("IBAN belge : BE68 5390 0754 7034, merci.", [("IBAN", "BE68 5390 0754 7034")]),
    ("Ecrivez a sophie.bernard@cabinet-test.fr rapidement.", [("EMAIL", "sophie.bernard@cabinet-test.fr")]),
    ("Mon mail perso : j_dupont42@gmail.com.", [("EMAIL", "j_dupont42@gmail.com")]),
    ("Appelez le 06 12 34 56 78 ce soir.", [("TELEPHONE", "06 12 34 56 78")]),
    ("Tel : +33 6 98 76 54 32 pour le rendez-vous.", [("TELEPHONE", "+33 6 98 76 54 32")]),
    ("Joignable au 04.93.12.34.56 en journee.", [("TELEPHONE", "04.93.12.34.56")]),
    ("Carte 4539 1488 0343 6467 expiree.", [("CARTE_BANCAIRE", "4539 1488 0343 6467")]),
    ("Compte 00012345678 a la BNP.", [("COMPTE", "00012345678")]),
    ("Voir le dossier 2024/0457-B au greffe.", [("DOSSIER", "2024/0457-B")]),
    ("Parcelle cadastrale AB 0123 a Grasse.", [("CADASTRE", "AB 0123")]),
    ("La societe SOLARIS ENERGIE intervient demain.", [("ENTREPRISE", "SOLARIS ENERGIE")]),
    ("Ne le 12/03/1980 a Marseille.", [("DATE_NAISSANCE", "12/03/1980")]),
    ("Domicile : 12 rue des Lilas, 06000 Nice.",
     [("ADRESSE", "12 rue des Lilas"), ("ADRESSE", "06000"), ("ADRESSE", "Nice")]),
    ("Adresse du temoin : 3 avenue Jean Medecin, 06000 Nice.",
     [("ADRESSE", "3 avenue Jean Medecin"), ("ADRESSE", "06000")]),
    ("M. Wei Zhang a signe le bail.", [("PERSONNE", "Wei Zhang")]),
    ("Madame O'Sullivan conteste la facture.", [("PERSONNE", "O'Sullivan")]),
    ("Le RIB indique FR14 2004 1010 0505 0001 3M02 606.", [("IBAN", "FR14 2004 1010 0505 0001 3M02 606")]),
    ("Contactez Maitre Jean-Pierre de La Tour.", [("PERSONNE", "Jean-Pierre de La Tour")]),
    ("Reference du dossier client : DOS-2025-00891.", [("DOSSIER", "DOS-2025-00891")]),
    ("Virement vers l'IBAN allemand DE89 3704 0044 0532 0130 00.", [("IBAN", "DE89 3704 0044 0532 0130 00")]),
    ("Patiente : Awa Diallo, nee le 5 janvier 1991.",
     [("PERSONNE", "Awa Diallo"), ("DATE_NAISSANCE", "5 janvier 1991")]),
]


def couverture(zone, spans):
    couvert = set()
    for s, e in spans:
        couvert |= set(range(s, e))
    return len(zone & couvert) / len(zone) if zone else 0.0


def spans_regex(phrase):
    """Spans des regex maison (directes + contextuelles si le contexte est la)."""
    spans = []
    for regex in detection.MOTIFS_REGEX.values():
        spans += [(m.start(), m.end()) for m in regex.finditer(phrase)]
    bas = phrase.lower()
    for regex, contextes in detection.MOTIFS_CONTEXTUELS.values():
        if detection.contexte_present(contextes, bas):
            spans += [(m.start(), m.end()) for m in regex.finditer(phrase)]
    return spans


def mesurer(fournisseur):
    strict = collections.Counter(); large = collections.Counter(); total = collections.Counter()
    for phrase, golds in CAS:
        spans = fournisseur(phrase)
        for typ, val in golds:
            idx = phrase.find(val)
            if idx < 0:
                continue
            zone = set(range(idx, idx + len(val)))
            frac = couverture(zone, spans)
            total[typ] += 1
            if frac >= 0.999:
                strict[typ] += 1
            if frac > 0:
                large[typ] += 1
    return strict, large, total


def afficher(titre, strict, large, total):
    print("\n===== %s =====" % titre)
    print("%-16s %8s %8s %8s" % ("TYPE", "STRICT", "LARGE", "N"))
    ts = ds = tl = 0
    for typ in sorted(total):
        n, s, l = total[typ], strict[typ], large[typ]
        ts += n; ds += s; tl += l
        print("%-16s %7d%% %7d%% %8d" % (typ, round(100 * s / n), round(100 * l / n), n))
    if ts:
        print("%-16s %7d%% %7d%% %8d" % ("GLOBAL", round(100 * ds / ts), round(100 * tl / ts), ts))


# Labels PII de GLiNER (memes que detection_fine.py).
LABELS_PII = [
    "person", "organization", "address", "email", "phone number", "iban",
    "credit card number", "social security number", "date of birth",
    "passport number", "driver licence", "medical condition", "bank account number",
]


def main():
    seuil = 0.3
    detecteurs = [("regex", spans_regex)]
    if "--gliner" in sys.argv:
        from gliner import GLiNER
        modele = GLiNER.from_pretrained("urchade/gliner_multi_pii-v1")

        def spans_gliner(phrase):
            return [(e["start"], e["end"])
                    for e in modele.predict_entities(phrase, LABELS_PII, threshold=seuil)]

        detecteurs.append(("GLiNER", spans_gliner))
    if "--anonymia" in sys.argv:
        from transformers import pipeline
        ner = pipeline("token-classification", model=MODELE, aggregation_strategy="simple")

        def spans_anonymia(phrase):
            return [(int(r["start"]), int(r["end"])) for r in ner(phrase)
                    if float(r["score"]) >= seuil]

        detecteurs.append(("Anonym-IA", spans_anonymia))

    # Cumul : regex, puis regex+GLiNER, puis regex+GLiNER+Anonym-IA (l'union
    # qui monte). On voit ainsi le rappel grimper detecteur apres detecteur.
    cumul, noms = [], []
    for nom, fonction in detecteurs:
        cumul.append(fonction)
        noms.append(nom)
        sources = list(cumul)
        afficher(" + ".join(noms),
                 *mesurer(lambda p, s=sources: [sp for f in s for sp in f(p)]))
    if len(detecteurs) == 1:
        print("\n(Ajouter --gliner et/ou --anonymia dans un venv avec "
              "gliner/transformers/torch pour voir l'union monter.)")


if __name__ == "__main__":
    main()
