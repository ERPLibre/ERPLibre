# Versions supportées

Odoo 10.0 à 19.0, **18.0 par défaut**. Les 10 à 15 sont dépréciées ; 10 et 11,
comme 19, ne portent que les dépôts odoo et OCA. Odoo 10 est le seul en
Python 2.7 : son venv et son Poetry passent par
`script/install/install_venv_python2.sh`, et son image Docker par buster.

La correspondance Odoo ↔ Python ↔ Poetry fait autorité dans
`conf/supported_version_erplibre.json` (ses clés portent déjà le couple, ex.
`odoo18.0_python3.12.10`) — la lire plutôt que de mémoriser un tableau.

Version active du checkout : `.odoo-version`, `.erplibre-version`,
`.poetry-version`, `.python-odoo-version`.
