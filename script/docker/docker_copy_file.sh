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

CURRENT=$(pwd)
BASENAME=$(basename "${CURRENT}")

# Remove dots and convert to lowercase (same logic as original)
BASENAME="${BASENAME//./}"
BASENAME="${BASENAME,,}"

CANDIDATE1="${BASENAME}-ERPLibre-1"
CANDIDATE2="${BASENAME}_ERPLibre_1"

CONTAINER=""

# Find which container exists
if docker ps --format '{{.Names}}' | grep -qx "${CANDIDATE1}"; then
  CONTAINER="${CANDIDATE1}"
elif docker ps --format '{{.Names}}' | grep -qx "${CANDIDATE2}"; then
  CONTAINER="${CANDIDATE2}"
else
  echo "Error: No matching container found:"
  echo "  - ${CANDIDATE1}"
  echo "  - ${CANDIDATE2}"
  exit 1
fi

echo "Detected container: ${CONTAINER}"

# -----------------------------
# Copy file into container
# -----------------------------

echo "Ensuring directory exists inside container: ${DEST_DIR}"
docker exec -u root "${CONTAINER}" mkdir -p "${DEST_DIR}"

echo "Copying '${SRC_FILE}' to '${CONTAINER}:${DEST_DIR}/${SRC_BASENAME}'"
docker cp "${SRC_FILE}" "${CONTAINER}:${DEST_DIR}/${SRC_BASENAME}"

echo "File copy complete."
