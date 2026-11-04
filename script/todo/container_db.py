#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les bases de données du conteneur ERPLibre : espace, restauration,
suppression.

Ce module rend des faits et des commandes ; le menu (container_menu.py)
pose les questions. Rien ici n'écrit à l'écran ni ne lance de restauration.

Restaurer par le gestionnaire web d'Odoo écrit dans /tmp du conteneur : deux
copies de l'upload (le tampon de werkzeug, puis le fichier du contrôleur),
puis le zip décompressé. /tmp est la couche inscriptible du conteneur, sur le
disque qui porte le moteur, et le filestore extrait est ensuite COPIÉ vers le
volume de données, un autre point de montage. Une sauvegarde de 2 Go qui se
décompresse en 8 Go demande ainsi plus de 12 Go avant même que PostgreSQL
n'écrive.

La restauration de ce module pousse le zip dans un dossier de travail DANS
le répertoire de données d'Odoo, et y pointe TMPDIR pendant « odoo-bin db
load » : l'extraction se fait sur le système de fichiers du filestore, où le
déplacement final n'est plus qu'un renommage, et aucun upload n'est tamponné.

Les identifiants PostgreSQL atteignent Odoo et psql par les variables PG* de
libpq, jamais par la ligne de commande : un processus du conteneur est un
processus de l'hôte, et « ps » y montre ses arguments à tout compte. Odoo ne
pose host, user et password que si sa configuration les donne, sinon libpq
lit l'environnement.
"""

import os
import re
import zipfile

from script.todo import container_runtime

# Le service du fichier compose, et le nom que Compose donne au conteneur à
# défaut d'étiquette : « <projet>-ERPLibre-1 » (v2) ou « <projet>_ERPLibre_1 »
# (v1).
SERVICE = "ERPLibre"
RE_NOM_ERPLIBRE = re.compile(r"[-_]ERPLibre[-_]\d+$")

# Le compte qui fait tourner Odoo. La composition démarre souvent en root,
# puis entrypoint_pip_extra.sh passe à ERPLIBRE_RUN_AS ; ce root a perdu ses
# capacités (cap_drop) et ne traverse plus le répertoire de données d'odoo.
# La restauration s'exécute donc sous le compte d'Odoo, propriétaire du
# filestore qu'elle écrit.
COMPTE_DEFAUT = "odoo"

# Le nom qu'Odoo accepte pour une base (web/controllers/database.py).
RE_NOM_BASE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]+$")

# Le dossier de travail, sous le répertoire de données. Un nom fixe : un
# reste d'une restauration interrompue est effacé par la suivante au lieu de
# s'accumuler.
TRAVAIL = ".erplibre_restore"
ZIP = "sauvegarde.zip"

# Les fonctions shell communes : la configuration d'Odoo, et la lecture
# d'une clé comme le fait l'entrypoint (la configuration l'emporte sur
# l'environnement).
_CONF = r"""
rc="${ODOO_RC:-/etc/odoo/odoo.conf}"
conf() {
  sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$rc" 2>/dev/null \
    | tail -n 1 | tr -d '"\r'
}
data_dir=$(conf data_dir)
case "$data_dir" in "" | False) data_dir="$HOME/.local/share/Odoo" ;; esac
"""

# Les PG* de libpq, dans l'ordre de l'entrypoint : la clé de la
# configuration, puis la variable de la composition, puis le défaut. Puis le
# python du venv d'Odoo et odoo-bin, sans activer le venv.
_ODOO = (
    _CONF
    + r"""
cd "${ODOO_PREFIX:-/ERPLibre}" || exit 1
pg() {
  v=$(conf "$1")
  case "$v" in "" | False) printf '%s' "$2" ;; *) printf '%s' "$v" ;; esac
}
export PGHOST="$(pg db_host "${HOST:-${DB_PORT_5432_TCP_ADDR:-db}}")"
export PGPORT="$(pg db_port "${PORT:-${DB_PORT_5432_TCP_PORT:-5432}}")"
export PGUSER="$(pg db_user "${USER:-${DB_ENV_POSTGRES_USER:-${POSTGRES_USER:-odoo}}}")"
export PGPASSWORD="$(pg db_password "${PASSWORD:-${DB_ENV_POSTGRES_PASSWORD:-${POSTGRES_PASSWORD:-odoo}}}")"
py="$PWD/.venv.$(tr -d '[:space:]' < .erplibre-version)/bin/python"
bin="${ODOO_EXEC_BIN:-$PWD/odoo$(tr -d '[:space:]' < .odoo-version)/odoo/odoo-bin}"
"""
)

# Le répertoire de données, s'il est inscriptible, et l'espace libre de
# celui-ci et de /tmp. Chaque ligne porte une clé : les avertissements du
# moteur se mêlent à la sortie, et ne doivent pas être lus comme des valeurs.
SONDE = (
    _CONF
    + r"""
printf 'data_dir=%s\n' "$data_dir"
if [ -d "$data_dir" ] && [ -w "$data_dir" ]; then
  echo ecriture=1
else
  echo ecriture=0
fi
df -Pk "$data_dir" 2>/dev/null | tail -n 1 | sed 's/^/df_data=/'
df -Pk /tmp 2>/dev/null | tail -n 1 | sed 's/^/df_tmp=/'
"""
)

# Les bases, chacune marquée « vide » quand ir_module_module n'y existe pas :
# c'est ce que laisse une restauration interrompue avant psql, Odoo créant la
# base AVANT d'extraire. Même filtre que list_dbs d'Odoo.
LISTE = (
    _ODOO
    + r"""
noms=$(psql -d postgres -At -c "select datname from pg_database
  where not datistemplate and datallowconn and datname <> 'postgres'
  order by datname") || exit 1
for b in $noms; do
  vide=$(psql -d "$b" -At -c \
    "select to_regclass('public.ir_module_module') is null" 2>/dev/null)
  printf 'base=%s|%s\n' "$b" "$vide"
done
"""
)

# Reçoit le zip sur l'entrée standard. Il est écrit par le compte d'Odoo,
# qui le lira : « docker cp » le poserait au nom de root, avec les droits du
# fichier de l'hôte, souvent illisibles pour odoo.
RECEVOIR = (
    _CONF
    + r"""
set -e
travail="$data_dir/__TRAVAIL__"
rm -rf "$travail"
mkdir -p "$travail/tmp"
cat > "$travail/__ZIP__"
""".replace("__TRAVAIL__", TRAVAIL).replace("__ZIP__", ZIP)
)

# $1 : la base ; la suite : les options de « db load ». L'absence de la
# commande « db » (antérieure à Odoo 18) sort en 3 avant de rien toucher.
RESTAURER = (
    _ODOO
    + r"""
travail="$data_dir/__TRAVAIL__"
base=$1
shift
if [ ! -f "$(dirname "$bin")/odoo/cli/db.py" ]; then
  echo "odoo-bin db: absent"
  exit 3
fi
export TMPDIR="$travail/tmp"
"$py" "$bin" db -c "$rc" load "$@" "$base" "$travail/__ZIP__"
""".replace("__TRAVAIL__", TRAVAIL).replace("__ZIP__", ZIP)
)

NETTOYER = (
    _CONF
    + r"""
rm -rf "$data_dir/__TRAVAIL__"
""".replace("__TRAVAIL__", TRAVAIL)
)

# $1 : la base. « db drop » efface aussi son filestore, là où dropdb le
# laisserait sur le volume.
SUPPRIMER = (
    _ODOO
    + r"""
if [ ! -f "$(dirname "$bin")/odoo/cli/db.py" ]; then
  echo "odoo-bin db: absent"
  exit 3
fi
"$py" "$bin" db -c "$rc" drop "$1"
"""
)

# Le répertoire racine du moteur, où vivent images, conteneurs et volumes.
FORMAT_RACINE = {
    "docker": "{{.DockerRootDir}}",
    "podman": "{{.Store.GraphRoot}}",
}


def est_erplibre(conteneur):
    """Le conteneur est-il le service ERPLibre d'une composition ?"""
    if conteneur.get("service"):
        return conteneur["service"] == SERVICE
    return bool(RE_NOM_ERPLIBRE.search(conteneur.get("nom", "")))


def conteneurs_erplibre(fiche, lanceur=container_runtime.lancer):
    """Les conteneurs ERPLibre EN MARCHE : restaurer passe par leur Odoo."""
    return [
        c
        for c in container_runtime._inspecter_conteneurs(fiche, lanceur)
        if c["etat"] == "running" and est_erplibre(c)
    ]


def du_dossier(conteneurs, dossier):
    """Le conteneur dont la composition vit dans `dossier`, ou None.

    Les scripts de script/docker/ retrouvent le leur par le nom du
    répertoire courant ; le dossier de travail que Compose étiquette dit la
    même chose sans deviner la transformation du nom.
    """
    trouves = [c for c in conteneurs if c.get("dossier") == dossier]
    return trouves[0] if len(trouves) == 1 else None


def compte(conteneur):
    """Le compte sous lequel lancer les commandes : celui d'Odoo."""
    utilisateur = conteneur.get("utilisateur") or ""
    if utilisateur and utilisateur.split(":")[0] not in ("root", "0"):
        return utilisateur
    return conteneur.get("env", {}).get("ERPLIBRE_RUN_AS") or COMPTE_DEFAUT


def executer(fiche, conteneur, script, args=(), interactif=False):
    """La commande « exec » qui lance `script` sous bash dans le conteneur.

    Les valeurs voyagent en paramètres positionnels ($1…), jamais collées
    dans le script : un nom de base n'y est jamais interprété.
    """
    options = ["-i"] if interactif else []
    return container_runtime.commande(
        fiche,
        [
            "exec",
            *options,
            "-u",
            compte(conteneur),
            conteneur["nom"],
            "bash",
            "-c",
            script,
            "bash",
            *args,
        ],
    )


def libelle(conteneur, action):
    """La ligne du journal pour une commande lancée dans le conteneur."""
    return f"exec {conteneur['nom']} ({compte(conteneur)}): {action}"


def lire_sonde(sortie):
    """La sortie de SONDE en dictionnaire.

    {"data_dir": str, "ecriture": bool, "libre_data": octets ou None,
    "libre_tmp": octets ou None, "montage_data": str, "montage_tmp": str}.
    """
    sonde = {
        "data_dir": "",
        "ecriture": False,
        "libre_data": None,
        "libre_tmp": None,
        "montage_data": "",
        "montage_tmp": "",
    }
    for ligne in sortie.splitlines():
        cle, egal, valeur = ligne.partition("=")
        if not egal:
            continue
        if cle == "data_dir":
            sonde["data_dir"] = valeur.strip()
        elif cle == "ecriture":
            sonde["ecriture"] = valeur.strip() == "1"
        elif cle in ("df_data", "df_tmp"):
            champs = valeur.split()
            # Système de fichiers, blocs de 1 Kio, utilisés, libres,
            # capacité, point de montage.
            if len(champs) >= 6 and champs[3].isdigit():
                suffixe = cle[3:]
                sonde[f"libre_{suffixe}"] = int(champs[3]) * 1024
                sonde[f"montage_{suffixe}"] = " ".join(champs[5:])
    return sonde


def lire_liste(sortie):
    """La sortie de LISTE : [(base, vide)], dans l'ordre de PostgreSQL."""
    bases = []
    for ligne in sortie.splitlines():
        if not ligne.startswith("base="):
            continue
        nom, _, vide = ligne[5:].partition("|")
        if nom:
            bases.append((nom, vide.strip() == "t"))
    return bases


def tailles_sauvegarde(chemin):
    """Ce que la restauration écrira, lu dans l'index du zip, ou None.

    Seuls comptent les membres qu'Odoo extrait — dump.sql et filestore/ —
    à leur taille DÉCOMPRESSÉE : c'est elle qui occupe le disque.
    {"zip", "dump", "filestore", "fichiers"} en octets, sauf le dernier :
    le nombre de pièces jointes.
    """
    if not zipfile.is_zipfile(chemin):
        return None
    dump = filestore = fichiers = 0
    with zipfile.ZipFile(chemin) as archive:
        noms = set()
        for membre in archive.infolist():
            noms.add(membre.filename)
            if membre.filename == "dump.sql":
                dump = membre.file_size
            elif membre.filename.startswith("filestore/"):
                filestore += membre.file_size
                # Odoo 18 joint, sous filestore/checklist/, un marqueur vide
                # par pièce jointe : ce ne sont pas des fichiers à compter.
                fichiers += not (
                    membre.is_dir()
                    or membre.filename.startswith("filestore/checklist/")
                )
    if "dump.sql" not in noms:
        return None
    return {
        "zip": os.path.getsize(chemin),
        "dump": dump,
        "filestore": filestore,
        "fichiers": fichiers,
    }


def besoin(tailles):
    """L'espace qu'exige la restauration sur le volume de données, en octets.

    Le zip copié, puis son contenu extrait à côté ; le filestore n'est plus
    réécrit, le déplacement final étant un renommage. PostgreSQL écrit en
    plus au moins la taille de dump.sql dans SON volume — sur le même disque
    pour des volumes nommés du même moteur : il est compté.
    """
    return tailles["zip"] + tailles["dump"] * 2 + tailles["filestore"]


def lisible(octets):
    """Une taille en unité binaire, à une décimale : « 8.4 GiB ».

    Les symboles CEI plutôt que « Gio » : ils se lisent dans les deux
    langues du menu.
    """
    if octets is None:
        return "?"
    taille = float(octets)
    for unite in ("B", "KiB", "MiB", "GiB"):
        if taille < 1024:
            break
        taille /= 1024
    else:
        unite = "TiB"
    return f"{taille:.1f} {unite}"


def nom_par_defaut(chemin):
    """Le nom de base que suggère le fichier, s'il est accepté par Odoo."""
    nom = os.path.splitext(os.path.basename(chemin))[0]
    return nom if RE_NOM_BASE.match(nom) else ""
