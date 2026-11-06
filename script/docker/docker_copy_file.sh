#!/usr/bin/env bash

set -euo pipefail

# -----------------------------
# Parameters
# -----------------------------

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <source_file> [destination_directory]"
  exit 1
fi

SRC_FILE="$1"
DEST_DIR="${2:-/home/seluser/Downloads}" # default destination inside container

if [[ ! -f "$SRC_FILE" ]]; then
  echo "Error: Source file '$SRC_FILE' does not exist."
  exit 1
fi

SRC_BASENAME="$(basename "$SRC_FILE")"

# -----------------------------
# Determine container name
# -----------------------------

source "$(dirname "$0")/lib_conteneur.sh"
CONTAINER=$(conteneur_erplibre)

echo "Detected container: ${CONTAINER}"

# -----------------------------
# Copy file into container
# -----------------------------

echo "Ensuring directory exists inside container: ${DEST_DIR}"
docker exec -u root "${CONTAINER}" mkdir -p "${DEST_DIR}"

echo "Copying '${SRC_FILE}' to '${CONTAINER}:${DEST_DIR}/${SRC_BASENAME}'"
docker cp "${SRC_FILE}" "${CONTAINER}:${DEST_DIR}/${SRC_BASENAME}"

echo "File copy complete."
