#!/usr/bin/env bash

# --- Configuration ---
# Set variable
# export MASTER_PWD=""
# export DATABASE_NAME=""
# export OUTPUT_FILE_PATH=""
# export ODOO_URL=""

#MASTER_PWD="ADMIN"
#DATABASE_NAME="BD"
BACKUP_FORMAT="zip"
#OUTPUT_FILE_PATH="/tmp/test.zip"
#ODOO_URL="https://mondomain"

QUIET_MODE=false

for arg in "$@"; do
  case "$arg" in
    --quiet)
      QUIET_MODE=true
      ;;
    *)
      echo "Argument non reconnu : $arg"
      exit 1
      ;;
  esac
done

# --- Security Check ---
# Check if the MASTER_PWD environment variable is set
if [[ -z "$MASTER_PWD" ]]; then
  echo "Error: The MASTER_PWD environment variable is not set." >&2
  echo "Please set it before running this script:" >&2
  echo "  export MASTER_PWD='your_master_password'" >&2
  exit 1
fi
# Check if the ODOO_URL environment variable is set
if [[ -z "$ODOO_URL" ]]; then
  #  echo "Error: The ODOO_URL environment variable is not set." >&2
  #  echo "Please set it before running this script:" >&2
  #  echo "  export ODOO_URL='your_master_password'" >&2
  #  exit 1
  read -p "Odoo URL: " ODOO_URL
fi
# Check if the DATABASE_NAME environment variable is set
if [[ -z "$DATABASE_NAME" ]]; then
  #  echo "Error: The DATABASE_NAME environment variable is not set." >&2
  #  echo "Please set it before running this script:" >&2
  #  echo "  export DATABASE_NAME='your_master_password'" >&2
  #  exit 1
  read -p "Database: " DATABASE_NAME
fi
# Check if the OUTPUT_FILE_PATH environment variable is set
if [[ -z "$OUTPUT_FILE_PATH" ]]; then
  #  echo "Error: The OUTPUT_FILE_PATH environment variable is not set." >&2
  #  echo "Please set it before running this script:" >&2
  #  echo "  export OUTPUT_FILE_PATH='your_master_password'" >&2
  #  exit 1
  read -p "Output File Path: " OUTPUT_FILE_PATH
fi

ODOO_BACKUP_URL="${ODOO_URL}/web/database/backup"

# --- Destination ---
# The download goes to a temporary file beside the destination, renamed only
# once it is a zip: a failure never leaves a truncated or empty .zip under
# the final name, and never touches a file already there. Creating it now
# also refuses a missing or read-only directory before the server spends
# minutes preparing the dump.
OUTPUT_DIR="$(dirname -- "$OUTPUT_FILE_PATH")"
if ! PART_FILE="$(mktemp -- "${OUTPUT_FILE_PATH}.part.XXXXXX" 2>/dev/null)"; then
  echo "Backup failed: cannot write to '${OUTPUT_DIR}'." >&2
  exit 1
fi
trap 'rm -f -- "$PART_FILE"' EXIT

# --- Curl Command to Download Database ---
echo "Starting Odoo database backup for '${DATABASE_NAME}' from '${ODOO_BACKUP_URL}' to path '${OUTPUT_FILE_PATH}'..."

# The master password goes through curl's standard input ("<-"), never its
# arguments: any account on the host reads those with ps for the whole
# download. printf is a shell builtin, so it never shows up there either.
CURL_ARGS=(
  -X POST
  --fail
  -F "master_pwd=<-"
  -F "name=$DATABASE_NAME"
  -F "backup_format=$BACKUP_FORMAT"
  -o "$PART_FILE"
)
if [ "$QUIET_MODE" = false ]; then
  CURL_ARGS+=(--progress-bar)
fi

curl "${CURL_ARGS[@]}" "$ODOO_BACKUP_URL" < <(printf '%s' "$MASTER_PWD")
CURL_STATUS=$?

# --- Verification ---
if [[ $CURL_STATUS -ne 0 ]]; then
  echo "Backup failed: curl exited with code ${CURL_STATUS}." >&2
  # 23: curl could not write what it received.
  if [[ $CURL_STATUS -eq 23 ]]; then
    echo "Writing to '${OUTPUT_DIR}' failed: check its free space (df -h)." >&2
  fi
  exit 1
fi

# Odoo answers a refused backup (unknown database, wrong master password)
# with HTTP 200 and an HTML page: only the zip signature tells them apart.
if [[ "$(head -c 2 -- "$PART_FILE")" != "PK" ]]; then
  REASON="$(grep -o -m 1 'Database backup error: [^<]*' -- "$PART_FILE" |
    sed -e "s/&#39;/'/g" -e 's/&quot;/"/g' -e 's/&lt;/</g' -e 's/&gt;/>/g' \
      -e 's/&amp;/\&/g')"
  echo "Backup failed: the server did not send a zip." >&2
  if [[ -n "$REASON" ]]; then
    echo "$REASON" >&2
  fi
  exit 1
fi

# mktemp creates its file 0600: the backup gets the mode the umask gives any
# new file instead, as when curl wrote the destination itself.
chmod -- "$(printf '%o' $((0666 & ~0$(umask))))" "$PART_FILE"
if ! mv -- "$PART_FILE" "$OUTPUT_FILE_PATH"; then
  echo "Backup failed: cannot rename to '${OUTPUT_FILE_PATH}'." >&2
  exit 1
fi
echo "Backup completed successfully!"
echo "File saved to: $OUTPUT_FILE_PATH"
