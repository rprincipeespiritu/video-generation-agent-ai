#!/bin/sh
set -eu
# El volumen de Railway se monta con propietario root. Solo estos directorios nuevos
# necesitan cambiar de propietario; el servidor y sus procesos corren como video.
mkdir -p "$VIDEO_DATA_DIR" "$VIDEO_CONFIG_DIR"
if [ "$(id -u)" = 0 ]; then
    chown video:video "$VIDEO_DATA_DIR" "$VIDEO_CONFIG_DIR"
    chmod 700 "$VIDEO_CONFIG_DIR"
    exec gosu video "$@"
fi
exec "$@"
