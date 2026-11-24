#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La base d'un ERPLibre déployé par SSH, quand elle vit sur un serveur
PostgreSQL dédié plutôt que sur la machine d'Odoo.

L'installation pose toujours son PostgreSQL local, et `config.conf` est
réécrit à chaque installation : une base distante écrite là redeviendrait
locale en silence. Avec une base distante, l'unité lance donc
`script/deployment/erplibre_serve.py`, qui rend sa propre configuration
depuis un fichier d'environnement — celui-ci ne change qu'à la demande.

LE SECRET NE PASSE PAR AUCUNE LIGNE DE COMMANDE. Le fichier d'environnement
voyage sur l'entrée standard de ssh vers un dossier 0700 du compte distant,
puis est posé en 0600 root dans /etc/erplibre ; systemd le lit avant de
lancer le service. La vérification de la base l'emprunte par `systemd-run`,
qui le lit de la même façon.
"""

from __future__ import annotations

import io
import re

from script.lib_valid import HOST_RE, ValidationError

MODES = ("local", "distant")
SSLMODES = (
    "disable",
    "allow",
    "prefer",
    "require",
    "verify-ca",
    "verify-full",
)
SSLMODE_DISTANT = "verify-full"
# Un identifiant PostgreSQL non cité : il finit dans un fichier lu par libpq
# et dans le `dbfilter` d'Odoo, où un caractère spécial changerait le sens.
_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

DEPOT = "~/.erplibre-base"
ENV_HOTE = "/etc/erplibre/erplibre.env"
RACINE_HOTE = "/usr/local/share/ca-certificates/erplibre-site-racine.crt"
ETAT_HOTE = "/var/lib/erplibre"
MAGASIN_SYSTEME = "/etc/ssl/certs/ca-certificates.crt"


def valider_base(fiche: dict) -> dict:
    """Les champs de base de `fiche`, normalisés, ou ValidationError.

    En local, ils sont vidés : une base locale n'a ni hôte ni racine, et des
    restes d'une configuration distante feraient croire qu'ils servent. En
    distant, l'hôte, le compte et la base sont exigés, et un mode qui
    vérifie le certificat exige la racine qui le vérifie.
    """
    mode = str(fiche.get("db_mode") or "local").strip()
    if mode not in MODES:
        raise ValidationError(
            f"Mode de base inconnu : « {mode} ». Connus : {', '.join(MODES)}."
        )
    champs = ("db_host", "db_port", "db_user", "db_name", "db_sslmode")
    rendu = {"db_mode": mode, "ca_root": ""}
    rendu.update({c: "" for c in champs})
    if mode == "local":
        return rendu
    hote = str(fiche.get("db_host") or "").strip()
    if not hote or not HOST_RE.match(hote):
        raise ValidationError("Base distante : hôte absent ou invalide.")
    port = str(fiche.get("db_port") or "").strip()
    if port and (not port.isdigit() or not 0 < int(port) < 65536):
        raise ValidationError(f"Base distante : port invalide « {port} ».")
    for cle, libelle in (("db_user", "compte"), ("db_name", "base")):
        valeur = str(fiche.get(cle) or "").strip()
        if not _IDENT_RE.match(valeur):
            raise ValidationError(
                f"Base distante : {libelle} absent ou invalide « {valeur} »."
            )
        rendu[cle] = valeur
    sslmode = str(fiche.get("db_sslmode") or SSLMODE_DISTANT).strip()
    if sslmode not in SSLMODES:
        raise ValidationError(
            f"Base distante : mode TLS inconnu « {sslmode} »."
        )
    racine = str(fiche.get("ca_root") or "").strip()
    if sslmode.startswith("verify-") and not racine:
        raise ValidationError(
            f"Base distante en {sslmode} : la racine qui vérifie le"
            " certificat du serveur est exigée."
        )
    rendu.update(
        db_host=hote, db_port=port, db_sslmode=sslmode, ca_root=racine
    )
    return rendu


def _valeur(texte: str) -> str:
    """Une valeur d'`EnvironmentFile` : entre guillemets, `\\` et `"`
    échappés."""
    return '"' + str(texte).replace("\\", "\\\\").replace('"', '\\"') + '"'


def texte_env(fiche: dict, mot_de_passe: str, admin: str) -> str:
    """Le fichier d'environnement du service, pour une base distante."""
    base = valider_base(fiche)
    if base["db_mode"] != "distant":
        raise ValidationError(
            "Le fichier d'environnement sert la base distante."
        )
    if not mot_de_passe or not admin:
        raise ValidationError(
            "Mot de passe de la base et mot de passe maître exigés."
        )
    lignes = [
        ("PGHOST", base["db_host"]),
        ("PGPORT", base["db_port"] or "5432"),
        ("PGDATABASE", base["db_name"]),
        ("PGUSER", base["db_user"]),
        ("PGPASSWORD", mot_de_passe),
        ("PGSSLMODE", base["db_sslmode"]),
        ("ODOO_ADMIN_PASSWD", admin),
        # `requests`, qu'Odoo emploie vers le fournisseur d'identité, lit le
        # paquet certifi et non le magasin du système, où la racine du site
        # vient d'entrer.
        ("REQUESTS_CA_BUNDLE", MAGASIN_SYSTEME),
    ]
    if base["ca_root"]:
        lignes.append(("PGSSLROOTCERT", RACINE_HOTE))
    return "".join(f"{nom}={_valeur(v)}\n" for nom, v in lignes)


def deposer(
    hote: dict,
    fiche: dict,
    mot_de_passe: str,
    admin: str,
    lire_racine=None,
    run=None,
) -> tuple:
    """Dépose le fichier d'environnement, et la racine s'il y en a une, dans
    le dossier de dépôt du compte distant. Rend (code, sortie).

    Par l'entrée standard de ssh, dans un dossier 0700 et sous umask 077 :
    le secret n'apparaît ni dans une ligne de commande, ni lisible d'un autre
    compte pendant le trajet.
    """
    if run is None:
        from script.remote import appliance_ssh

        run = appliance_ssh.run
    texte = texte_env(fiche, mot_de_passe, admin)
    depots = [("erplibre.env", texte.encode("utf-8"))]
    racine = valider_base(fiche)["ca_root"]
    if racine:
        lire = lire_racine or (lambda c: open(c, "rb").read())
        depots.append(("racine.crt", lire(racine)))
    for nom, octets in depots:
        code, sortie = run(
            hote,
            f"umask 077; mkdir -p {DEPOT} && cat > {DEPOT}/{nom}",
            entree=io.BytesIO(octets),
        )
        if code != 0:
            return code, sortie
    return 0, ""


def cmd_service(svc_dir: str, delai: int = 600) -> str:
    """Le bloc joué SUR la VM, après l'installation, pour une base distante.

    Il pose la racine du site et le fichier d'environnement, remplace l'unité
    par celle du lanceur, sans `Requires=postgresql.service` (la base n'est
    pas ici), prouve la base distante par `SELECT 1` avant de lancer Odoo,
    puis attend que `/web/health` réponde 200.
    """
    return (
        f'SVC_DIR="{svc_dir}"; B={DEPOT}; '
        'test -s "$B/erplibre.env" || { echo "❌ fichier d\'environnement'
        ' de la base absent : $B/erplibre.env"; exit 1; }; '
        "sudo install -d -m 755 /etc/erplibre; "
        f'sudo install -m 600 -o root -g root "$B/erplibre.env" {ENV_HOTE}; '
        'rm -f "$B/erplibre.env"; '
        'if [ -s "$B/racine.crt" ]; then '
        f'sudo install -m 644 "$B/racine.crt" {RACINE_HOTE}; '
        "if command -v update-ca-certificates >/dev/null 2>&1; then "
        "sudo update-ca-certificates >/dev/null; "
        "elif command -v trust >/dev/null 2>&1; then "
        f"sudo trust anchor {RACINE_HOTE}; fi; fi; "
        "SVC_USER=$(whoami); "
        f'sudo install -d -o "$SVC_USER" -m 700 {ETAT_HOTE}; '
        "sudo tee /etc/systemd/system/erplibre.service >/dev/null <<UNIT\n"
        "[Unit]\n"
        "Description=ERPLibre\n"
        "Wants=network-online.target\n"
        "After=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        "User=$SVC_USER\n"
        f"EnvironmentFile={ENV_HOTE}\n"
        "ExecStart=/usr/bin/python3 $SVC_DIR/script/deployment/"
        f"erplibre_serve.py --port 8069 --etat {ETAT_HOTE} --racine $SVC_DIR\n"
        "Restart=always\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
        "UNIT\n"
        "sudo systemctl daemon-reload; "
        'echo "== Base distante =="; '
        "if ! EL_PG=$(sudo systemd-run --quiet --pipe --wait"
        f" -p EnvironmentFile={ENV_HOTE} psql -XAt -c 'SELECT 1' 2>&1); then "
        'echo "❌ la base distante ne répond pas : $EL_PG"; exit 1; fi; '
        'echo "   base distante : SELECT 1 → $EL_PG"; '
        "sudo systemctl enable --now erplibre.service; "
        f"EL_FIN=$(( $(date +%s) + {delai} )); "
        "while :; do "
        "EL_CODE=$(curl -s -o /dev/null -m 10 -w '%{http_code}'"
        " http://127.0.0.1:8069/web/health 2>/dev/null || true); "
        '[ "$EL_CODE" = 200 ] && break; '
        '[ "$(date +%s)" -ge "$EL_FIN" ] && { echo "❌ Odoo ne répond pas'
        ' sur /web/health ($EL_CODE)"; sudo journalctl -u erplibre -n 30'
        " --no-pager -o cat 2>/dev/null; exit 1; }; "
        "sleep 5; done; "
        'echo "   HTTP : /web/health répond 200."; '
    )
