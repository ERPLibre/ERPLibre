import requests
import sys
import os

# --- Configuration ---
# Replace these values with your own information
ODOO_URL = 'http://localhost:8069'  # Your Odoo server URL
DATABASE_NAME = 'your_database_name'
MASTER_PASSWORD = 'your_master_password'
BACKUP_FORMAT = 'zip'  # 'zip' or 'dump'
# Output file name
OUTPUT_FILE_NAME = f'{DATABASE_NAME}_backup.{BACKUP_FORMAT}'


# --- Function to download the database ---
def download_odoo_db():
    print(f"Attempting to download database '{DATABASE_NAME}' from URL '{ODOO_URL}'...")

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
            print(f"ERROR: Expected one of {expected_types} but got {content_type}.")
            print("This usually indicates a server-side error or an incorrect master password.")
            sys.exit(1)

        # Check if the content is an HTML page (to handle incorrect passwords)
        first_chunk = next(response.iter_content(chunk_size=128), b'')
        if first_chunk.startswith(b'<'):
            print("ERROR: It seems the server returned an HTML page instead of a database file.")
            print("This is often due to an incorrect master password or an invalid request.")
            print("Server Response (First 200 chars):")
            print(response.text[:200])
            sys.exit(1)

        # --- DOWNLOAD ---
        print(f"Download started, saving to '{OUTPUT_FILE_NAME}'...")

        # Write the content from the first chunk to the file
        with open(OUTPUT_FILE_NAME, 'wb') as f:
            f.write(first_chunk)
            # Continue writing the rest of the stream
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        print(f"Download successful! File saved at: {os.path.abspath(OUTPUT_FILE_NAME)}")

    except requests.exceptions.RequestException as e:
        print(f"An error occurred while connecting to the Odoo server: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


# --- Script execution ---
if __name__ == '__main__':
    # Add a simple check to ensure the user has configured the variables
    if ODOO_URL == 'http://localhost:8069' and DATABASE_NAME == 'your_database_name':
        print("Please configure the ODOO_URL, DATABASE_NAME, and MASTER_PASSWORD variables at the start of the script.")
        sys.exit(1)

    download_odoo_db()
