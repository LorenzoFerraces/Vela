FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY . .
RUN pip install --no-cache-dir .

# Runs as an unprivileged user. The user joins the host docker group that owns
# /var/run/docker.sock (GID 999 on Debian/Ubuntu/WSL2 defaults) so the API can
# still drive the host daemon; pass --build-arg DOCKER_GROUP_ID=<gid> if yours
# differs. /data (folder uploads) and /etc/traefik/dynamic (Traefik file router)
# are the container-writable dirs; chowning them seeds the compose named
# volumes with matching ownership on first use.
ARG DOCKER_GROUP_ID=999
RUN set -e; \
    useradd --create-home --uid 1000 --shell /usr/sbin/nologin vela; \
    if getent group docker; then \
        groupmod -g ${DOCKER_GROUP_ID} docker; \
    else \
        groupadd -g ${DOCKER_GROUP_ID} docker; \
    fi; \
    usermod -aG docker vela; \
    mkdir -p /data/volume-uploads /etc/traefik/dynamic; \
    chown -R vela:vela /app /data /etc/traefik/dynamic

USER vela

# Migrations are a one-shot deployment step (the compose `migrate` service),
# not part of API startup, so restarts and replicas do not race alembic.
# Alembic uses the sync psycopg driver (URL rewritten in app/db/engine.py).
CMD ["uvicorn", "app.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
