#!/bin/sh
# Starts as root, aligns the mounted Docker socket to the in-image docker
# group, then drops to the unprivileged `vela` user.
set -eu

SOCKET=/var/run/docker.sock
APP_USER=vela

if [ "$(id -u)" -eq 0 ]; then
    if [ -S "$SOCKET" ] && [ "$(stat -c %G "$SOCKET")" = "0" ]; then
        # Docker Desktop (Windows) exposes the host socket as root:root, which
        # the vela user cannot open. Sockets owned by a real `docker` group
        # are left as-is (match its GID via DOCKER_GROUP_ID at build time).
        chown root:"${DOCKER_GROUP_ID:-999}" "$SOCKET"
    fi
    app_home="$(getent passwd "$APP_USER" | cut -d: -f6)"
    exec env HOME="$app_home" USER="$APP_USER" LOGNAME="$APP_USER" \
        setpriv --reuid="$APP_USER" --regid="$APP_USER" --init-groups "$@"
fi

exec "$@"
