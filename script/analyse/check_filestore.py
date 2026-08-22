#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Des pièces jointes sans fichier : lesquelles peut-on encore récupérer ?

« 266 fichiers absents du filestore » ne dit pas quoi faire. La question
utile est ailleurs : combien sont PERDUS, et combien dorment quelque part
sur la machine en attendant qu'on les remette ?

Mesuré sur une migration réelle : sur 266 absents, 262 étaient des images
engendrées par des modules — dont 235 drapeaux de pays dont le champ
n'existe même plus en 18 — et QUATRE étaient de vrais documents. Ces
quatre-là sont la réponse. Les 262 autres sont du bruit qu'il ne faut pas
confondre avec eux.

Où l'outil cherche
------------------
1. Les autres filestores de la machine. Une migration laisse une base par
   palier ; un fichier perdu dans la 12 est souvent intact dans la 15,
   régénéré en chemin par une mise à jour de module.
2. Les `filestore/` NICHÉS. `shutil.move(src, dst)` d'Odoo renomme quand
   la destination n'existe pas et IMBRIQUE quand elle existe : une base
   restaurée deux fois sous le même nom se retrouve avec
   `filestore/<base>/filestore/xx/sha`, qu'Odoo ne lira jamais. Mesuré :
   1168 fichiers, 133 Mo, recopiés à l'identique dans les sept bases de
   la chaîne par le clone.
3. Les sauvegardes `.zip`. Leur répertoire central se lit sans tout
   décompresser.

Ce qui n'est PAS récupérable
----------------------------
Un fichier introuvable partout. On le dit alors franchement, avec le
modèle et l'enregistrement auxquels il se rattache, pour qu'on puisse
juger de la perte — et non « 266 fichiers absents », devant quoi il n'y
a rien à décider.

Un cas mérite sa propre catégorie : la pièce jointe dont le CHAMP
n'existe plus. `res.country.image` était un binaire en 12 ; en 18 c'est
`image_url`, calculé. Les 235 lignes survivent en pointant vers un champ
disparu : rien ne les lit, rien ne les régénérera, et il n'y a rien à
récupérer. Les compter comme des pertes serait faux.

Lecture seule de bout en bout.

Codes de sortie : 0 rien d'irrécupérable, 1 des trouvailles, 2 échec.
"""

import os
import subprocess
import sys
import zipfile

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


SEP = "\x1f"
REPO_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)

# L'ordre EST la gravité : ce qu'on ne peut pas récupérer se lit en premier.
VERDICTS = ("lost", "in_backup", "in_other_filestore", "nested", "dead_field")

ICONE = {
    "lost": "❌",
    "in_backup": "📦",
    "in_other_filestore": "🗂",
    "nested": "↳",
    "dead_field": "🕳",
}

EXPLICATION = {
    "lost": "nowhere to be found — truly lost",
    "in_backup": "still in a backup zip",
    "in_other_filestore": "intact in another database's filestore",
    "nested": "stranded in a nested filestore Odoo never reads",
    "dead_field": "its field no longer exists — nothing reads it",
}


def run_psql(database, sql):
    """Interroger la base en lecture seule, garantie par le SERVEUR."""
    env = os.environ.copy()
    env["PGOPTIONS"] = "-c default_transaction_read_only=on"
    env["PSQLRC"] = ""
    done = subprocess.run(
        ["psql", "-X", "-w", "-d", database, "-tAF", SEP, "-c", sql],
        capture_output=True,
        text=True,
        env=env,
    )
    if done.returncode:
        return None
    return [ligne.split(SEP) for ligne in done.stdout.splitlines() if ligne]


def data_dir(config_path=None):
    """Le `data_dir` d'Odoo, lu dans la configuration.

    Le deviner reviendrait à chercher au mauvais endroit et à déclarer
    tout perdu — le pire diagnostic possible pour cet outil.
    """
    chemin = config_path or os.path.join(REPO_ROOT, "config.conf")
    try:
        with open(chemin, "r", encoding="utf-8") as handle:
            for ligne in handle:
                if ligne.strip().startswith("data_dir"):
                    return ligne.split("=", 1)[1].strip()
    except OSError:
        pass
    return os.path.expanduser("~/.local/share/Odoo")


def filestore_root(config_path=None):
    return os.path.join(data_dir(config_path), "filestore")


def attachments(database):
    """Les pièces jointes stockées sur disque. None si la base se tait."""
    lignes = run_psql(
        database,
        "SELECT a.store_fname, coalesce(a.res_model, ''),"
        " a.id::text,"
        " coalesce(a.res_field, ''), coalesce(a.res_id::text, ''),"
        " coalesce(a.name, ''), coalesce(a.file_size::text, '0'),"
        " coalesce(a.mimetype, ''), coalesce(a.create_date::text, '')"
        " FROM ir_attachment a WHERE a.store_fname IS NOT NULL"
        " ORDER BY a.file_size DESC",
    )
    if lignes is None:
        return None
    return [
        {
            "store_fname": ligne[0],
            "model": ligne[1],
            "id": ligne[2],
            "field": ligne[3],
            "res_id": ligne[4],
            "name": ligne[5],
            "size": int(ligne[6] or 0),
            "mimetype": ligne[7],
            "created": ligne[8][:10],
        }
        for ligne in lignes
        if len(ligne) >= 9
    ]


def live_fields(database):
    """Les champs qui EXISTENT encore, en « modele.champ ».

    Sans eux, une pièce jointe orpheline d'un champ supprimé passerait
    pour une perte alors qu'il n'y a rien à perdre.
    """
    lignes = run_psql(
        database, "SELECT model || '.' || name FROM ir_model_fields"
    )
    return {ligne[0] for ligne in lignes or [] if ligne and ligne[0]}


def scan_filestores(racine, sauf=None):
    """{store_fname: base} pour toutes les bases, la nôtre exclue.

    Les fichiers NICHÉS sont indexés sous leur nom logique — c'est ce
    qu'on cherchera — mais notés à part : les remettre en place est un
    déplacement, pas une copie depuis ailleurs.
    """
    ailleurs, niches = {}, {}
    if not os.path.isdir(racine):
        return ailleurs, niches
    for base in sorted(os.listdir(racine)):
        chemin = os.path.join(racine, base)
        if not os.path.isdir(chemin):
            continue
        for prefixe in sorted(os.listdir(chemin)):
            sous = os.path.join(chemin, prefixe)
            if not os.path.isdir(sous):
                continue
            if prefixe == "filestore":
                cible, marque = niches, base
                for deux in sorted(os.listdir(sous)):
                    profond = os.path.join(sous, deux)
                    if not os.path.isdir(profond):
                        continue
                    for nom in os.listdir(profond):
                        cible.setdefault(f"{deux}/{nom}", marque)
                continue
            if base == sauf:
                continue
            for nom in os.listdir(sous):
                ailleurs.setdefault(f"{prefixe}/{nom}", base)
    return ailleurs, niches


def scan_backups(dossier):
    """{store_fname: zip} en lisant le répertoire central, sans extraire."""
    trouves = {}
    if not os.path.isdir(dossier):
        return trouves
    for nom in sorted(os.listdir(dossier)):
        if not nom.endswith(".zip"):
            continue
        chemin = os.path.join(dossier, nom)
        try:
            with zipfile.ZipFile(chemin) as archive:
                for membre in archive.namelist():
                    if membre.startswith("filestore/") and not membre.endswith(
                        "/"
                    ):
                        trouves.setdefault(membre[len("filestore/") :], nom)
        except (OSError, zipfile.BadZipFile):
            continue
    return trouves


def resources_alive(database, pieces):
    """{(modele, id): True/False} — l'enregistrement visé existe-t-il ?

    Une image perdue dont la tâche a été supprimée n'est pas une perte :
    personne ne la cherchera jamais. Une image perdue sur une tâche
    VIVANTE en est une, et c'est la seule qu'il faille regretter.
    Confondre les deux, c'est pleurer au hasard.

    Une requête par modèle, sur les seules pièces jointes déjà classées
    perdues — jamais sur les milliers d'autres.
    """
    par_modele = {}
    for piece in pieces:
        if not piece.get("model") or not (piece.get("res_id") or "").isdigit():
            continue
        par_modele.setdefault(piece["model"], set()).add(int(piece["res_id"]))
    vivants = {}
    for modele, ids in par_modele.items():
        table = modele.replace(".", "_").replace("'", "")
        # Un modèle abstrait ou transitoire n'a pas de table : interroger
        # une table absente rendrait None, qu'on lirait « n'existe pas ».
        # Ce serait un mensonge, et le pire sens du mensonge ici.
        existe = run_psql(
            database, f"SELECT to_regclass('{table}') IS NOT NULL"
        )
        if not existe or existe[0][0] != "t":
            continue
        liste = ", ".join(str(i) for i in sorted(ids))
        lignes = run_psql(
            database, f"SELECT id FROM {table} WHERE id IN ({liste})"
        )
        if lignes is None:
            continue
        trouves = {int(ligne[0]) for ligne in lignes if ligne and ligne[0]}
        for identifiant in ids:
            vivants[(modele, str(identifiant))] = identifiant in trouves
    return vivants


def files_on_disk(racine, database):
    """(au bon niveau, nichés) pour une base. Deux ensembles de noms."""
    base = os.path.join(racine, database)
    bons, niches = set(), set()
    if not os.path.isdir(base):
        return bons, niches
    for prefixe in os.listdir(base):
        sous = os.path.join(base, prefixe)
        if not os.path.isdir(sous):
            continue
        if prefixe == "filestore":
            for deux in os.listdir(sous):
                profond = os.path.join(sous, deux)
                if not os.path.isdir(profond):
                    continue
                for nom in os.listdir(profond):
                    if os.path.isfile(os.path.join(profond, nom)):
                        niches.add(f"{deux}/{nom}")
            continue
        for nom in os.listdir(sous):
            if os.path.isfile(os.path.join(sous, nom)):
                bons.add(f"{prefixe}/{nom}")
    return bons, niches


def verify_restore(database, zip_path, config_path=None):
    """La sauvegarde a-t-elle bien atterri ? À vérifier UNE fois.

    Après un clone, il n'y a rien à contrôler : `copytree` recopie la
    source telle quelle, défauts compris — le contrôle appartient à la
    restauration d'origine, pas au miroir.

    Ce qu'on cherche est précis. `shutil.move` d'Odoo renomme quand la
    destination n'existe pas et IMBRIQUE quand elle existe. Un dossier
    `filestore/<base>/` laissé par une restauration précédente suffit
    donc à envoyer toute la sauvegarde dans
    `filestore/<base>/filestore/`, où Odoo ne regardera jamais. Mesuré :
    1168 fichiers, 133 Mo, recopiés ensuite dans les six bases de la
    chaîne par le clone, sans que rien ne le signale.
    """
    attendus = set(scan_zip(zip_path))
    racine = filestore_root(config_path)
    bons, niches = files_on_disk(racine, database)
    return {
        "database": database,
        "zip": os.path.basename(zip_path),
        "expected": len(attendus),
        "placed": len(attendus & bons),
        "nested": len(attendus & niches),
        "missing": len(attendus - bons - niches),
        "root": os.path.join(racine, database),
    }


def scan_zip(chemin):
    """Les noms de fichiers du `filestore/` d'une sauvegarde."""
    try:
        with zipfile.ZipFile(chemin) as archive:
            return [
                membre[len("filestore/") :]
                for membre in archive.namelist()
                if membre.startswith("filestore/") and not membre.endswith("/")
            ]
    except (OSError, zipfile.BadZipFile):
        return []


def render_verify(rapport):
    """Se taire quand tout va bien : un contrôle bavard finit ignoré."""
    if not rapport["expected"]:
        return []
    if not rapport["nested"] and not rapport["missing"]:
        return [
            f"✅ {t('Filestore restored:')} {rapport['placed']}"
            f"/{rapport['expected']} {t('file(s) in place')}"
        ]
    lignes = [
        f"⚠  {t('Filestore restore looks wrong for')} {rapport['database']}"
        f" ({rapport['zip']}) :",
        f"     {rapport['placed']}/{rapport['expected']}"
        f" {t('file(s) in place')}",
    ]
    if rapport["nested"]:
        lignes.append(
            f"     {rapport['nested']}"
            f" {t('landed in a nested filestore Odoo never reads')}"
        )
        lignes.append(
            f"     {t('To fix:')} rsync -a --remove-source-files"
            f" {rapport['root']}/filestore/ {rapport['root']}/"
        )
    if rapport["missing"]:
        lignes.append(f"     {rapport['missing']} {t('never landed at all')}")
    return lignes


def classify(piece, present, ailleurs, niches, sauvegardes, champs_vivants):
    """Le verdict d'une pièce jointe. None si son fichier est là.

    L'ordre des questions est l'ordre de l'action à mener : d'abord
    « y a-t-il seulement quelque chose à récupérer », puis « où ».
    """
    if piece["store_fname"] in present:
        return None
    # Un champ disparu n'a rien à récupérer : la ligne est une scorie.
    # Le tester EN PREMIER évite de proposer une remise en place inutile.
    if piece["field"]:
        cle = f"{piece['model']}.{piece['field']}"
        if cle not in champs_vivants:
            return ("dead_field", cle)
    if piece["store_fname"] in niches:
        return ("nested", niches[piece["store_fname"]])
    if piece["store_fname"] in ailleurs:
        return ("in_other_filestore", ailleurs[piece["store_fname"]])
    if piece["store_fname"] in sauvegardes:
        return ("in_backup", sauvegardes[piece["store_fname"]])
    return ("lost", None)


def audit(database, config_path=None, backups=None):
    """Tout ce qu'il faut savoir, en une passe. Lecture seule."""
    pieces = attachments(database)
    if pieces is None:
        return {"unavailable": True, "database": database}
    racine = filestore_root(config_path)
    mien = os.path.join(racine, database)
    present = set()
    if os.path.isdir(mien):
        for prefixe in os.listdir(mien):
            sous = os.path.join(mien, prefixe)
            if prefixe == "filestore" or not os.path.isdir(sous):
                continue
            for nom in os.listdir(sous):
                if os.path.isfile(os.path.join(sous, nom)):
                    present.add(f"{prefixe}/{nom}")
    ailleurs, niches = scan_filestores(racine, sauf=database)
    sauvegardes = scan_backups(backups or os.path.join(REPO_ROOT, "image_db"))
    champs_vivants = live_fields(database)

    groupes = {verdict: [] for verdict in VERDICTS}
    vus = set()
    for piece in pieces:
        verdict = classify(
            piece, present, ailleurs, niches, sauvegardes, champs_vivants
        )
        if not verdict:
            continue
        # Plusieurs pièces jointes partagent un fichier quand leur contenu
        # est identique : le compter une fois par ligne gonflerait le
        # rapport sans ajouter un seul fichier à récupérer.
        if piece["store_fname"] in vus:
            continue
        vus.add(piece["store_fname"])
        groupes[verdict[0]].append(dict(piece, where=verdict[1]))
    vivants = resources_alive(database, groupes["lost"])
    for piece in groupes["lost"]:
        piece["alive"] = vivants.get((piece["model"], piece["res_id"]))
    return {
        "database": database,
        "attachments": len(pieces),
        "files_present": len(present),
        "missing": len(vus),
        "groups": groupes,
        "nested_total": len(niches),
        "root": racine,
    }


def render(rapport, limit=20):
    if rapport.get("unavailable"):
        return [f"❌ {t('Cannot read the database: ')}{rapport['database']}"]
    lignes = [
        f"🗄 {t('Filestore of')} {rapport['database']} :"
        f" {rapport['attachments']} {t('stored attachment(s)')},"
        f" {rapport['files_present']} {t('file(s) on disk')}"
    ]
    if not rapport["missing"]:
        lignes.append(f"   ✅ {t('every attachment file is present')}")
        return lignes + render_nested(rapport)
    lignes.append(f"   {rapport['missing']} {t('file(s) missing')} :")
    for verdict in VERDICTS:
        groupe = rapport["groups"][verdict]
        if not groupe:
            continue
        poids = sum(piece["size"] for piece in groupe)
        lignes.append(
            f"     {ICONE[verdict]} {len(groupe)} {t(EXPLICATION[verdict])}"
            f"  ({poids // 1024} ko)"
        )
        # On ne nomme QUE l'irrécupérable : c'est la seule liste devant
        # laquelle il y a une décision à prendre. Nommer les autres
        # ferait défiler trois cents lignes sans rien apprendre.
        if verdict != "lost":
            apercu = summarise(groupe)
            for texte in apercu[:4]:
                lignes.append(f"         {texte}")
            if len(apercu) > 4:
                lignes.append(f"         … {len(apercu) - 4} {t('more')}")
            continue
        for piece in groupe[:limit]:
            ou = (
                f"{piece['model']} #{piece['res_id']}"
                if piece["model"]
                else "—"
            )
            champ = f" [{piece['field']}]" if piece["field"] else ""
            lignes.append(
                f"         {piece['name'][:44] or '(sans nom)':<46}"
                f" {piece['size'] // 1024:>6} ko  {ou}{champ}"
                f"  {piece['created']}  {alive_mark(piece)}"
            )
        if len(groupe) > limit:
            lignes.append(f"         … {len(groupe) - limit} {t('more')}")
    return lignes + render_nested(rapport)


def render_nested(rapport):
    if not rapport.get("nested_total"):
        return []
    return [
        "",
        f"   ↳ {rapport['nested_total']}"
        f" {t('file(s) sit in nested filestores Odoo never reads.')}",
    ]


def alive_mark(piece):
    """Dire si l'enregistrement visé vit encore, ou qu'on ne sait pas.

    Trois états, pas deux : « on n'a pas pu vérifier » ne doit pas se
    lire comme « il a disparu », sans quoi une vraie perte serait classée
    en fausse alerte.
    """
    etat = piece.get("alive")
    if etat is True:
        return f"✓ {t('record still exists')}"
    if etat is False:
        return f"✗ {t('record is gone — nothing will miss it')}"
    return ""


def summarise(groupe):
    """« modele / champ × N », pour dire beaucoup en peu de lignes."""
    compte = {}
    for piece in groupe:
        cle = f"{piece['model'] or '—'} / {piece['field'] or '—'}"
        compte[cle] = compte.get(cle, 0) + 1
    return [
        f"{cle} × {combien}" if combien > 1 else cle
        for cle, combien in sorted(compte.items(), key=lambda x: -x[1])
    ]


def purge_dead_sql(rapport):
    """Le SQL qui efface les lignes dont le champ n'existe plus, ou "".

    On efface par IDENTIFIANT, pas par un domaine reconstruit : la liste
    a été établie en confrontant `ir_model_fields` à ce que la base
    porte, et rejouer ce raisonnement en SQL laisserait la porte ouverte
    à effacer autre chose que ce qui a été montré.
    """
    ids = sorted(
        int(piece["id"])
        for piece in rapport["groups"]["dead_field"]
        if str(piece.get("id", "")).isdigit()
    )
    if not ids:
        return ""
    liste = ", ".join(str(i) for i in ids)
    return f"DELETE FROM ir_attachment WHERE id IN ({liste})"


def nested_dir(rapport):
    """Le dossier imbriqué de cette base, s'il en existe un."""
    chemin = os.path.join(rapport["root"], "filestore")
    return chemin if os.path.isdir(chemin) else ""


def tidy_nested_plan(rapport):
    """(à remonter, doublons) parmi les fichiers imbriqués.

    Deux tas très différents : ce qui MANQUE au bon niveau doit y
    remonter, ce qui y est déjà est un doublon pur. Les traiter d'un
    bloc écraserait des fichiers présents par des copies — inutile, et
    inquiétant sur une base de production.
    """
    dossier = nested_dir(rapport)
    if not dossier:
        return [], []
    bons, _n = files_on_disk(
        os.path.dirname(rapport["root"]), os.path.basename(rapport["root"])
    )
    remonter, doublons = [], []
    for deux in sorted(os.listdir(dossier)):
        profond = os.path.join(dossier, deux)
        if not os.path.isdir(profond):
            continue
        for nom in sorted(os.listdir(profond)):
            complet = os.path.join(profond, nom)
            if not os.path.isfile(complet):
                continue
            (doublons if f"{deux}/{nom}" in bons else remonter).append(
                (complet, os.path.join(rapport["root"], deux, nom))
            )
    return remonter, doublons


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "List attachments whose file is gone, and say which ones can"
            " still be recovered and from where."
        )
    )
    parser.add_argument("-d", "--database", required=True)
    parser.add_argument("-c", "--config", help="odoo config file")
    parser.add_argument("--backups", help="directory of backup .zip files")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    config = parser.parse_args(argv)

    rapport = audit(config.database, config.config, config.backups)
    if rapport.get("unavailable"):
        print(f"❌ {t('Cannot read the database: ')}{config.database}")
        return 2
    if config.json:
        import json

        print(
            json.dumps(rapport, indent=2, sort_keys=True, ensure_ascii=False)
        )
    else:
        print("\n".join(render(rapport, config.limit)))
    return 1 if rapport["groups"]["lost"] else 0


if __name__ == "__main__":
    sys.exit(main())
