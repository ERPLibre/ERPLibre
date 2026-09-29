# Versions supportées

Odoo 8.0 à 20.0, **18.0 par défaut**. Les 8 à 15 sont dépréciées ; 8 à 11,
19 et 20 ne portent que les dépôts odoo et OCA, plus les modules de
neutralisation du dépôt development. Odoo 8 à 10 tournent en Python 2.7 : leur
venv et leur Poetry passent par `script/install/install_venv_python2.sh`, et
leur image Docker par buster. Odoo 20 tourne en Python 3.14.

Ces versions pointent sur l'Odoo amont, sans la commande « db » du fork
ERPLibre : `odoo_bin.sh` redirige alors « db » vers l'addon
`script/odoo/cli_addons/erplibre_db`, qui prend les mêmes options, et
« --uninstall » vers `erplibre_uninstall`.

Odoo 8 et 9 nomment encore leur paquet `openerp` : lanceur `openerp-server`,
cœur d'addons sous `openerp/addons`, manifestes `__openerp__.py`, fichier de
configuration lu par `OPENERP_SERVER`. Odoo 8 n'a ni commande `shell` —
`odoo_bin.sh` la redirige vers `erplibre_shell` — ni option `--dev`, dont le
mode passe par `ERPLIBRE_DEV_MODE`. Il ne crée pas non plus la base nommée par
`-d` : la créer par `./odoo_bin.sh db --create`.

La correspondance Odoo ↔ Python ↔ Poetry fait autorité dans
`conf/supported_version_erplibre.json` (ses clés portent déjà le couple, ex.
`odoo18.0_python3.12.10`) — la lire plutôt que de mémoriser un tableau.

Version active du checkout : `.odoo-version`, `.erplibre-version`,
`.poetry-version`, `.python-odoo-version`.
