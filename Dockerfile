# syntax=docker/dockerfile:1@sha256:572cebbc2b15e6f84c077742952674889cb63cd5e9b80abdffcbe587b6f19183
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928

ARG VERSION_APP=dev
LABEL org.opencontainers.image.title="Carnet de briques" \
      org.opencontainers.image.description="Choix de sets de briques pour adultes : catalogue, relevé des prix, sélection partagée" \
      org.opencontainers.image.source="https://github.com/actarus314/lego" \
      org.opencontainers.image.licenses="AGPL-3.0-only"

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    VERSION_APP=${VERSION_APP} PORT=8080 CHEMIN_DONNEES=/donnees

WORKDIR /app
COPY app ./app
COPY web ./web
COPY data ./data
COPY LICENSE ./

VOLUME ["/donnees"]
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8080\")}/api/sante',timeout=4)"]
CMD ["python", "-m", "app.serveur"]
