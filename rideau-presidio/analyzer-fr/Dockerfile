# Presidio Analyzer officiel + le francais.
# L'image de base ne parle qu'anglais : on ajoute le modele spaCy francais
# au build, et on pointe le moteur NLP vers notre configuration bilingue
# via NLP_CONF_FILE (variable lue par le serveur, verifie dans app.py).

FROM mcr.microsoft.com/presidio-analyzer:latest

RUN python -m spacy download fr_core_news_md

COPY languages-config.yml /app/languages-config.yml
ENV NLP_CONF_FILE=/app/languages-config.yml
