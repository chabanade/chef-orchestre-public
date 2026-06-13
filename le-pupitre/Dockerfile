# Image du Pupitre : Python + l'appli. sqlcipher3-wheels fournit des binaires
# Linux prets (manylinux), donc aucune compilation ici.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . ./

# La passphrase du coffre arrive par l'environnement (CHEF_PUPITRE_PASSPHRASE) :
# en conteneur il n'y a pas de terminal pour la saisir. Le coffre (et le corpus
# RAG) sont chiffres ; ranger le volume sur un disque hote chiffre reste le socle.
EXPOSE 8800
CMD ["python", "serveur.py"]
