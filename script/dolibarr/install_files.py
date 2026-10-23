#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le texte des fichiers que l'installateur pose dans un arbre Dolibarr.

Rendu pur : ce module rend des chaînes, l'appelant les écrit (en 0600).

install.forced.php est lu par les étapes step1, step2 et step5 de
htdocs/install, relativement au répertoire courant : avec noedit=2, ses
valeurs l'emportent sur argv et sur les formulaires, et il porte ainsi
tous les secrets de l'installation sans qu'aucun ne passe par argv. Il doit
disparaître dès l'installation finie.

conf.php, lui, est écrit par step1 ; set_conf_values n'en change que les
lignes nommées, par exemple prod que l'installeur écrit toujours à 0.
"""

import re

# L'installeur de Dolibarr passe le mot de passe de base par
# dol_escape_php(…, 1) en écrivant conf.php : il retire les « \\ » et change
# les « " » en « ' ». Un tel mot de passe différerait donc entre la base et
# conf.php ; il est refusé ici plutôt que découvert à la connexion.
_ALTERED_BY_DOLIBARR = ('"', "\\")


def php_single_quoted(value):
    """`value` en littéral PHP entre apostrophes : « \\ » et « ' » échappés."""
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def render_install_forced(v):
    """Texte de install.forced.php pour les valeurs `v`.

    Clés : db_type (mysqli|pgsql), db_host, db_port, db_name, db_user,
    db_pass, data_root, admin_login, admin_pass. La base et son compte
    existent déjà : l'installeur n'en crée pas et ne reçoit aucun
    identifiant root. Le verrou install.lock est posé en 0444.
    """
    try:
        port = int(v["db_port"])
    except (TypeError, ValueError):
        raise ValueError(f"db_port {v['db_port']!r} is not an integer")
    if any(c in v["db_pass"] for c in _ALTERED_BY_DOLIBARR):
        raise ValueError("db_pass holds a character Dolibarr rewrites")
    q = php_single_quoted
    lines = [
        "<?php",
        "// Écrit par ERPLibre pour une installation sans navigateur ;",
        "// supprimé à la fin de l'installation.",
        "$force_install_distrib = 'erplibre';",
        "$force_install_nophpinfo = true;",
        "$force_install_noedit = 2;",
        "$force_install_mainforcehttps = false;",
        f"$force_install_main_data_root = {q(v['data_root'])};",
        f"$force_install_type = {q(v['db_type'])};",
        f"$force_install_dbserver = {q(v['db_host'])};",
        f"$force_install_port = {port};",
        f"$force_install_database = {q(v['db_name'])};",
        "$force_install_prefix = 'llx_';",
        "$force_install_createdatabase = false;",
        "$force_install_createuser = false;",
        f"$force_install_databaselogin = {q(v['db_user'])};",
        f"$force_install_databasepass = {q(v['db_pass'])};",
        "$force_install_databaserootlogin = '';",
        "$force_install_databaserootpass = '';",
        f"$force_install_dolibarrlogin = {q(v['admin_login'])};",
        f"$force_install_dolibarrpassword = {q(v['admin_pass'])};",
        "$force_install_lockinstall = '444';",
        "$force_install_module = '';",
    ]
    return "\n".join(lines) + "\n"


def set_conf_values(text, values):
    """`text` de conf.php où chaque réglage de `values` prend sa valeur.

    `values` : {nom sans le préfixe « dolibarr_main_ » : valeur}. La ligne
    active du réglage est remplacée sur place, entre apostrophes ; une ligne
    commentée n'en est pas une. Un réglage absent est ajouté à la fin.
    """
    for name, value in values.items():
        line = f"$dolibarr_main_{name}={php_single_quoted(value)};"
        pattern = re.compile(
            rf"^\$dolibarr_main_{re.escape(name)}\s*=.*;[ \t]*$", re.M
        )
        text, count = pattern.subn(lambda _m, line=line: line, text)
        if not count:
            if text and not text.endswith("\n"):
                text += "\n"
            text += line + "\n"
    return text
