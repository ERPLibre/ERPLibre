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
ODOO_BACKUP_URL="${ODOO_URL}/web/database/backup"

# --- Security Check ---
# Check if the MASTER_PWD environment variable is set
if [[ -z "$MASTER_PWD" ]]; then
  echo "Error: The MASTER_PWD environment variable is not set." >&2
  echo "Please set it before running this script:" >&2
  echo "  export MASTER_PWD='your_master_password'" >&2
  exit 1
fi

# --- Curl Command to Download Database ---
echo "Starting Odoo database backup for '${DATABASE_NAME}' from '${ODOO_BACKUP_URL}' to path '${OUTPUT_FILE_PATH}'..."
curl -X POST \
     -F "master_pwd=$MASTER_PWD" \
     -F "name=$DATABASE_NAME" \
     -F "backup_format=$BACKUP_FORMAT" \
     -o "$OUTPUT_FILE_PATH" \
     --progress-bar \
     "$ODOO_BACKUP_URL"

# --- Verification ---
if [[ $? -eq 0 ]]; then
  echo "Backup completed successfully!"
  echo "File saved to: $OUTPUT_FILE_PATH"
else
  echo "Backup failed. Please check the logs." >&2
  exit 1
fi