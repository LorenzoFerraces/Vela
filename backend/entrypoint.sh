#!/bin/sh
# Starts as root, aligns the mounted Docker socket with the in-image docker
# group, then drops to the unprivileged `vela` user.
set -eu

SOCKET=/var/run/docker.sock
APP_USER=vela

if [ "$(id -u)" -eq 0 ]; then
    if [ -S "$SOCKET" ]; then
        sock_gid="$(stat -c %g "$SOCKET")"
        if [ "$sock_gid" = "0" ]; then
            # Docker Desktop (Windows) exposes the host socket as root:root,
            # which the vela user cannot open. Re-group it to the in-image
            # docker group (vela is a member) so it can connect.
            chown root:"${DOCKER_GROUP_ID:-999}" "$SOCKET"
            echo "vela-entrypoint: socket owned by root; chowned $SOCKET to group ${DOCKER_GROUP_ID:-999}"
        else
            in_gid="$(getent group docker | cut -d: -f3)"
            if [ "$sock_gid" = "$in_gid" ]; then
                echo "vela-entrypoint: socket group already matches docker GID $sock_gid"
            elif groupmod -g "$sock_gid" docker; then
                # Socket owned by a real host docker group with a different GID
                # (e.g. non-999 on RHEL/Amazon Linux). Align the in-image group
                # instead of chowning the socket, so the host's own docker
                # group keeps working.
                echo "vela-entrypoint: aligned in-image docker group from GID $in_gid to host GID $sock_gid"
            else
                echo "vela-entrypoint: WARNING: could not align docker group to host GID $sock_gid; Docker access may fail. Set DOCKER_GROUP_ID=$sock_gid in .env and rebuild the api image."
            fi
        fi
    else
        echo "vela-entrypoint: WARNING: $SOCKET not present in container; Docker access will fail until the socket is mounted."
    fi
    app_home="$(getent passwd "$APP_USER" | cut -d: -f6)"
    exec env HOME="$app_home" USER="$APP_USER" LOGNAME="$APP_USER" \
        setpriv --reuid="$APP_USER" --regid="$APP_USER" --init-groups "$@"
fi

exec "$@"
