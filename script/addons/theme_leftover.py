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


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=("List what an uninstalled theme left behind (read-only).")
    )
    parser.add_argument("-d", "--database", required=True)
    parser.add_argument("-t", "--theme", required=True)
    config = parser.parse_args(argv)
    try:
        attachments, views = collect(config.database, config.theme)
    except RuntimeError as exc:
        print(f"❌ {exc}")
        return 2
    print(render(config.theme, attachments, views))
    return 1 if (attachments or views) else 0


if __name__ == "__main__":
    sys.exit(main())
