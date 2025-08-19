#!/usr/bin/env python3
# © 2021-2024 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

print("This script only work with localhost:8069, not working with remote instance.")

import requests
import sys
import logging
from pathlib import Path

ODOO_URL = ''  # Your Odoo server URL
DATABASE_NAME = ''
MASTER_PASSWORD = ''
# BACKUP_FORMAT = env('BACKUP_FORMAT', default='zip')  # 'zip' or 'dump'
BACKUP_FORMAT = 'zip'  # 'zip' or 'dump'
OUTPUT_FILE_NAME = f'{DATABASE_NAME}_backup.{BACKUP_FORMAT}'

# --- Logger Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Function to download the database ---
def download_odoo_db():
    logger.info(f"Attempting to download database '{DATABASE_NAME}' from URL '{ODOO_URL}'...")

    # URL for the backup endpoint
    backup_url = f'{ODOO_URL}/web/database/backup'

    # Form data for the POST request
    payload = {
        'master_pwd': MASTER_PASSWORD,
        'name': DATABASE_NAME,
        'backup_format': BACKUP_FORMAT,
    }

    try:
        # Execute the POST request to start the backup
        response = requests.post(backup_url, data=payload, stream=True)
        response.raise_for_status()  # Raise an exception for bad status codes

        # --- VALIDATION ---
        content_type = response.headers.get('Content-Type', '').split(';')[0]

        # Check if the content type is valid
        expected_types = ['application/zip', 'application/octet-stream']
        if content_type not in expected_types:
            logger.error(f"ERROR: Expected one of {expected_types} but got {content_type}.")
            logger.error("This usually indicates a server-side error or an incorrect master password.")
            sys.exit(1)

        # Check if the content is an HTML page (to handle incorrect passwords)
        first_chunk = next(response.iter_content(chunk_size=128), b'')
        if first_chunk.startswith(b'<'):
            logger.error("ERROR: It seems the server returned an HTML page instead of a database file.")
            logger.error("This is often due to an incorrect master password or an invalid request.")
            logger.error("Server Response (First 200 chars):")
            logger.error(response.text[:200])
            sys.exit(1)

        # --- DOWNLOAD ---
        logger.info(f"Download started, saving to '{OUTPUT_FILE_NAME}'...")

        output_path = Path(OUTPUT_FILE_NAME)
        with open(output_path, 'wb') as f:
            # Write the content from the first chunk to the file
            f.write(first_chunk)
            # Continue writing the rest of the stream in chunks
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        logger.info(f"Download successful! File saved at: {output_path.resolve()}")

    except requests.exceptions.RequestException as e:
        logger.error(f"An error occurred while connecting to the Odoo server: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")


# --- Script execution ---
if __name__ == '__main__':
    # Add a simple check to ensure the user has configured the variables
    if ODOO_URL == 'http://localhost:8069' and DATABASE_NAME == 'your_database_name':
        logger.error("Please configure the ODOO_URL, DATABASE_NAME, and MASTER_PASSWORD variables at the start of the script.")
        sys.exit(1)

    download_odoo_db()
