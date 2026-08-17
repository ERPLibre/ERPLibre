#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce qu'un thème laisse derrière lui une fois désinstallé. Lecture seule.

Décharger un thème retire ses copies de vues et rend au site sa configuration
par défaut. Restent des pièces jointes portant son chemin — SCSS compilé,
images téléversées dans ses dossiers — et parfois des vues dont la clé le
nomme encore.

Elles ne cassent rien tant que le module est parti : plus personne ne les
inclut dans un bundle. Mais elles traversent toutes les migrations suivantes,
et l'on finit par tomber sur un `/theme_x/static/...` dont le module n'existe
plus nulle part, sans savoir si c'est grave.

Rien n'est supprimé ici. Le contenu d'une pièce jointe peut être la seule
trace d'une personnalisation, et c'est une décision, pas un ménage.

Codes de sortie : 0 rien à signaler, 1 des restes, 2 l'outil a échoué.
"""

import argparse
import os
import subprocess
import sys

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


def can_ask():
    """Peut-on poser une question ICI ?

    Il faut deux choses, pas une : de quoi LIRE la réponse (stdin sur un
    terminal) et de quoi MONTRER la question (stdout aussi). Ne tester que
    stdin laisse poser une invite qui part dans un tube : elle reste en
    tampon, invisible, pendant que le processus attend — on croit à un
    blocage et l'on tape Entrée à l'aveugle.
    """
    return sys.stdin.isatty() and sys.stdout.isatty()


def run_psql(database, sql):
    """Interroger la base en lecture seule, garantie côté serveur.

    `default_transaction_read_only` est posé par le serveur pour toute la
    session : ce n'est pas une promesse de l'outil, c'est PostgreSQL qui
    refusera l'écriture même si le SQL en contenait une.
    """
    env = os.environ.copy()
    env["PGOPTIONS"] = (
        "-c default_transaction_read_only=on -c statement_timeout=30000"
    )
    env["PSQLRC"] = ""
    done = subprocess.run(
        [
            "psql",
            "-X",
            "-w",
            "-v",
            "ON_ERROR_STOP=1",
            "-d",
            database,
            "-tAF",
            "|",
            "-c",
            sql,
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    if done.returncode:
        raise RuntimeError(done.stderr.strip() or "psql failed")
    return [line for line in done.stdout.splitlines() if line]


def quote_literal(value):
    return "'" + value.replace("'", "''") + "'"


def collect(database, theme):
    """Pièces jointes et vues qui nomment encore ce thème."""
    like = quote_literal(f"%/{theme}/%")
    key_like = quote_literal(f"{theme}.%")
    attachments = run_psql(
        database,
        "SELECT id, COALESCE(url, name), create_date::date FROM ir_attachment"
        f" WHERE url LIKE {like} ORDER BY id;",
    )
    views = run_psql(
        database,
        "SELECT id, key, website_id FROM ir_ui_view"
        f" WHERE key LIKE {key_like} ORDER BY id;",
    )
    return attachments, views


def render(theme, attachments, views):
    if not attachments and not views:
        return f"✅ -> {t('No leftover for theme')} '{theme}'.\n"
    lines = []
    if attachments:
        lines.append(
            f"ℹ {len(attachments)} {t('attachment(s) still under')}"
            f" /{theme}/ :"
        )
        for row in attachments[:20]:
            lines.append(f"   - {row}")
        if len(attachments) > 20:
            lines.append(f"   … {len(attachments) - 20} {t('more')}")
    if views:
        lines.append(
            f"ℹ {len(views)} {t('view(s) whose key still names it')} :"
        )
        for row in views[:20]:
            lines.append(f"   - {row}")
        if len(views) > 20:
            lines.append(f"   … {len(views) - 20} {t('more')}")
    lines.append(
        f"   {t('Nothing was deleted: their content may be the only trace')}"
        f" {t('of a customization. Read before removing.')}"
    )
    return "\n".join(lines) + "\n"


def backup_attachments(database, theme, lst_row, filestore=None):
    """Écrire le contenu des pièces jointes AVANT de les supprimer.

    C'est la condition pour pouvoir répondre « efface ». Sans elle, on
    détruirait ce dont on vient d'écrire qu'il peut être la seule trace
    d'une personnalisation.
    """
    base = filestore or os.path.join(
        os.path.expanduser("~"),
        ".local",
        "share",
        "Odoo",
        "filestore",
        database,
    )
    directory = os.path.join(
        "private", "odoo", "migration", database, "theme_backup", theme
    )
    os.makedirs(directory, exist_ok=True)
    lst_saved = []
    for row in lst_row:
        att_id = row.split("|")[0]
        rows = run_psql(
            database,
            "SELECT COALESCE(store_fname, '') FROM ir_attachment"
            f" WHERE id = {int(att_id)};",
        )
        store_fname = rows[0].strip() if rows else ""
        if not store_fname:
            continue
        source = os.path.join(base, store_fname)
        if not os.path.isfile(source):
            continue
        target = os.path.join(
            directory, f"{att_id}_" + os.path.basename(row.split("|")[1])
        )
        with open(source, "rb") as src, open(target, "wb") as dst:
            dst.write(src.read())
        lst_saved.append(target)
    return lst_saved


def delete_attachments(database, lst_row, config_path="./config.conf"):
    """Supprimer par le shell d'Odoo, pour qu'il gère aussi le filestore.

    Un DELETE en SQL laisserait les fichiers orphelins et les caches
    incohérents ; unlink() fait le ménage complet, dans toutes les versions.
    """
    lst_id = [row.split("|")[0] for row in lst_row]
    script = (
        f"env['ir.attachment'].browse({lst_id!r}).unlink()\n"
        "env.cr.commit()\n"
    )
    done = subprocess.run(
        ["./odoo_bin.sh", "shell", "-c", config_path, "-d", database],
        input=script,
        capture_output=True,
        text=True,
    )
    return done.returncode, done.stdout + done.stderr


def prompt(database, theme, attachments, views, config_path, ask=input):
    """Garder ou effacer. « Garder » par défaut, et la sauvegarde d'abord."""
    if not attachments:
        return False
    answer = (
        ask(
            f"💬 {t('Delete these leftovers, or keep them?')}"
            f" ({t('Enter = keep')}, d = {t('delete, after saving them')}) : "
        )
        .strip()
        .lower()
    )
    if answer != "d":
        print(f"ℹ -> {t('Kept. Nothing was deleted.')}")
        return False
    lst_saved = backup_attachments(database, theme, attachments)
    print(f"📦 {t('Saved before deleting')} : {len(lst_saved)}")
    if lst_saved:
        print(f"   {os.path.dirname(lst_saved[0])}")
    status, output = delete_attachments(database, attachments, config_path)
    print(output.strip()[-1500:])
    if status:
        print(f"❌ {t('Deletion failed, nothing was removed.')}")
        return False
    print(f"✅ -> {len(attachments)} {t('attachment(s) deleted.')}")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=("List what an uninstalled theme left behind (read-only).")
    )
    parser.add_argument("-d", "--database", required=True)
    parser.add_argument("-t", "--theme", required=True)
    parser.add_argument(
        "-c",
        "--config",
        default="./config.conf",
        help="Odoo config used by the shell for --delete",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="delete them (WRITES; saves their content first)",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="never ask anything, even in front of a terminal",
    )
    config = parser.parse_args(argv)
    try:
        attachments, views = collect(config.database, config.theme)
    except RuntimeError as exc:
        print(f"❌ {exc}")
        return 2
    print(render(config.theme, attachments, views))
    if not attachments and not views:
        return 0
    if config.delete:
        lst_saved = backup_attachments(
            config.database, config.theme, attachments
        )
        print(f"📦 {t('Saved before deleting')} : {len(lst_saved)}")
        status, output = delete_attachments(
            config.database, attachments, config.config
        )
        print(output.strip()[-1500:])
        if status:
            print(f"❌ {t('Deletion failed, nothing was removed.')}")
            return 2
        print(f"✅ -> {len(attachments)} {t('attachment(s) deleted.')}")
        return 0
    # Voir ET pouvoir répondre : une invite dont la sortie part dans un
    # tube reste invisible — Python bufferise par blocs — pendant que le
    # processus attend. Mesuré : l'utilisateur tape Entrée à l'aveugle.
    if not config.report_only and can_ask():
        if prompt(
            config.database,
            config.theme,
            attachments,
            views,
            config.config,
        ):
            return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
