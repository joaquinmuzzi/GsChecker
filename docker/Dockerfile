# syntax=docker/dockerfile:1
#
# Imagen del bot para correrlo fuera de Railway (en local o en otro host).
# Railway NO la usa: sus servicios se construyen con Nixpacks
# (builder NIXPACKS en .railway/railway.py). Por eso vive en docker/ y no en
# la raíz del repo, donde Railway podría detectarla sola.
#
#   docker build -f docker/Dockerfile -t gschecker .
#   docker run --rm --env-file .env gschecker
#   docker run --rm --env-file .env gschecker python -m tools.run_scheduled_preload

# La misma versión que Railway (.tool-versions).
ARG PYTHON_VERSION=3.11.11

# --- build: dependencias en un venv, sin el código ---------------------------
FROM python:${PYTHON_VERSION}-slim AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install -r requirements.txt

# --- runtime: solo el venv y el código, con un usuario sin privilegios -------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# El bot crea logs/ al arrancar y reescribe los cachés de static/
# (item_slot_cache.json, etc.): /app tiene que ser del usuario que lo corre.
RUN useradd --create-home --uid 10001 bot \
    && install -d -o bot -g bot /app

WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY --chown=bot:bot . .

USER bot

CMD ["python", "main.py"]
