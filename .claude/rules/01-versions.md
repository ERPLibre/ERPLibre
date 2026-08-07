# Versions supportées

Odoo 12.0 à 18.0, **18.0 par défaut**. Les 12 à 15 sont dépréciées.

La correspondance Odoo ↔ Python ↔ Poetry fait autorité dans
`conf/supported_version_erplibre.json` (ses clés portent déjà le couple, ex.
`odoo18.0_python3.12.10`) — la lire plutôt que de mémoriser un tableau.

Version active du checkout : `.odoo-version`, `.erplibre-version`,
`.poetry-version`, `.python-odoo-version`.
