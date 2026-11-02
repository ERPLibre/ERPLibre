#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Prépare un conteneur Docker d'ERPLibre 1.6.0 (Odoo 18) pour
# erplibre_info_git : l'instantané du code, en lecture seule. Se lance depuis
# l'hôte, à la racine de ce checkout ; agit dans le conteneur par
# « docker exec ». Relancé, il refait ce qui manque et garde ce qui est fait.
#
#   1. Mémorise l'état de la racine ERPLibre (commit, HEAD, branche,
#      version), une seule fois, dans le volume des données d'Odoo
#      (MEMOIRE). Hors de la racine, il ne la rend pas « modifiée », et il
#      survit à la recréation du conteneur.
#   2. Met la racine sur master (origin/master) : l'image n'a ni
#      script/git/repo_state.py ni repo_pull.py. odoo18.0/ ne bouge pas.
#   3. Active l'option extra de la version (.erplibre-state.json) quand un
#      dépôt de manifest/git_manifest_extra_odoo<V>.xml est déjà cloné : ces
#      dépôts sont au manifeste par défaut de la 1.6.0, mais seulement à
#      l'extra de master. Sans l'option, le manifeste local que régénère le
#      pull les laisse « hors manifeste », et plus aucun pull ne les suit.
#   4. Ouvre en lecture au compte odoo les dossiers de /ERPLibre/.repo que
#      l'image laisse à root en mode 700, les « projects/*.git » : sans eux,
#      chaque dépôt de l'instantané est en erreur. Seuls les dossiers
#      changent : sur overlayfs, changer un dossier ne recopie que ses
#      métadonnées, et les fichiers sont déjà lisibles. odoo n'y gagne
#      aucune écriture.
#   5. Installe ou met à jour erplibre_info_git et erplibre_info_developer_menu
#      dans la base, puis redémarre le conteneur.
#   6. Prend un premier instantané et y remet l'état mémorisé à l'étape 1 :
#      il décrit le déploiement d'avant le checkout de master. Une seule
#      fois : l'identifiant de l'instantané rejoint le fichier mémorisé.
#
# Le tirage (erplibre_info_git_fetch) n'est pas préparé : il écrit dans les
# dépôts git, que l'image 1.6.0 laisse à root, et il exige un serveur lancé
# avec --dev. Il vient avec une image récente, dont le code appartient au
# compte odoo (ERPLIBRE_CODE_OWNER) ; --dev=all n'y suffit pas seul. Le
# message de fin lit les deux conditions dans le conteneur et nomme celle qui
# manque.
#
# Ce qui change dans le conteneur survit à un redémarrage, pas à sa
# recréation (« docker compose down », nouvelle image) ; la base, elle, garde
# ses modules et ses instantanés.
#
# Usage : script/update/docker_fix_erplibre_info_docker_erplibre_160.sh
#           [-c CONTENEUR] [-d BASE] [-b BRANCHE]
#   -c  le conteneur ; défaut : le service ERPLibre du docker-compose.yml
#   -d  la base Odoo ; défaut : test
#   -b  la branche d'ERPLibre à extraire ; défaut : master

set -euo pipefail

CONTENEUR=""
BASE="test"
BRANCHE="master"
MODULES="erplibre_info_git,erplibre_info_developer_menu"
MEMOIRE="/home/odoo/.local/share/Odoo/erplibre_pre_update.json"

while getopts "c:d:b:h" opt; do
  case "${opt}" in
  c) CONTENEUR="${OPTARG}" ;;
  d) BASE="${OPTARG}" ;;
  b) BRANCHE="${OPTARG}" ;;
  h)
    sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
  *) exit 2 ;;
  esac
done

etape() { echo -e "\n\033[1;34m==>\033[0m $*"; }
echec() {
  echo -e "\033[0;31mErreur\033[0m $*" >&2
  exit 1
}

if [[ -z "${CONTENEUR}" ]]; then
  CONTENEUR=$(docker compose ps -q ERPLibre 2>/dev/null || true)
  [[ -n "${CONTENEUR}" ]] ||
    echec "aucun service ERPLibre en marche ici ; nommer le conteneur par -c"
fi
[[ "$(docker inspect -f '{{.State.Running}}' "${CONTENEUR}" 2>/dev/null)" == "true" ]] ||
  echec "le conteneur ${CONTENEUR} n'est pas en marche"

# --privileged rend à cette seule commande les capacités que le compose peut
# retirer au conteneur (cap_drop) : sans elles, root ne peut ni chown ni
# écrire dans un dossier du compte odoo. Le conteneur, lui, garde les siennes.
en_root() { docker exec --privileged -i -u root "${CONTENEUR}" bash -s -- "$@"; }
en_odoo() { docker exec -i -u odoo "${CONTENEUR}" bash -s -- "$@"; }

VERSION_ODOO=$(docker exec "${CONTENEUR}" cat /ERPLibre/.odoo-version 2>/dev/null || true)
[[ "${VERSION_ODOO}" == "18.0" ]] ||
  echec "/ERPLibre/.odoo-version vaut « ${VERSION_ODOO} », ce script vise Odoo 18.0"

# Les points de montage sous /ERPLibre : ni chown, ni git n'y entrent.
MONTAGES=$(docker inspect -f '{{range .Mounts}}{{.Destination}}{{"\n"}}{{end}}' "${CONTENEUR}" |
  grep '^/ERPLibre/' || true)
echo "Conteneur : ${CONTENEUR}  base : ${BASE}  branche : ${BRANCHE}"
echo "Volumes montés sous /ERPLibre : ${MONTAGES:-aucun}" | tr '\n' ' '
echo

# ── 1. mémoire de l'état d'avant ───────────────────────────────────────
etape "1. Mémoire de la racine ERPLibre avant la mise à jour"
en_root "${MEMOIRE}" <<'EOF'
set -euo pipefail
memoire="$1"
cd /ERPLibre
if [[ -f "${memoire}" ]]; then
  echo "Déjà mémorisé, gardé tel quel :"
  cat "${memoire}"
  exit 0
fi
g() { git -c safe.directory='*' "$@"; }
python3 - "${memoire}" \
  "$(g describe --tags --always HEAD)" \
  "$(g rev-parse HEAD)" \
  "$(g symbolic-ref -q --short HEAD || true)" \
  "$(cat .erplibre-version 2>/dev/null || true)" \
  "$(g status --porcelain --untracked-files=no | head -1)" <<'PY'
import datetime, json, sys
chemin, commit, head, branche, version, sale = sys.argv[1:]
etat = {
    "commit": commit,
    "head": head,
    "branch": branche or None,
    "version": version.strip() or None,
    "dirty": bool(sale),
    "saved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds"
    ),
    "snapshot_id": None,
}
with open(chemin, "w") as fh:
    json.dump(etat, fh, indent=1)
print(json.dumps(etat, indent=1))
PY
chown odoo:odoo "${memoire}"
EOF

# ── 2. racine sur la branche ───────────────────────────────────────────
etape "2. Racine ERPLibre sur ${BRANCHE}"
en_root "${BRANCHE}" <<'EOF'
set -euo pipefail
branche="$1"
cd /ERPLibre
g() { git -c safe.directory='*' "$@"; }
if [[ -n "$(g status --porcelain --untracked-files=no)" ]]; then
  echo "Fichiers suivis modifiés dans /ERPLibre : rien n'est extrait." >&2
  g status --short --untracked-files=no | head -20 >&2
  exit 1
fi
g fetch --quiet origin "${branche}"
if [[ "$(g symbolic-ref -q --short HEAD || true)" == "${branche}" ]]; then
  g merge --ff-only --quiet "origin/${branche}"
else
  g checkout --quiet -B "${branche}" --track "origin/${branche}"
fi
g log --oneline -1
for s in repo_state.py repo_pull.py repo_upgrade.py repo_apply.py; do
  [[ -f "script/git/${s}" ]] || { echo "script/git/${s} absent après le checkout" >&2; exit 1; }
done
EOF

# ── 3. option extra ────────────────────────────────────────────────────
etape "3. Option extra, si ses dépôts sont déjà clonés"
en_root <<'EOF'
set -euo pipefail
cd /ERPLibre
".venv.erplibre/bin/python" - <<'PY'
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, ".")
from script.version import erplibre_state

version = open(".odoo-version").read().strip()
extra = f"manifest/git_manifest_extra_odoo{version}.xml"
if not os.path.isfile(extra):
    print(f"Pas de {extra} : rien à activer.")
    sys.exit(0)
chemins = [p.get("path") for p in ET.parse(extra).iter("project")]
clones = [c for c in chemins if os.path.lexists(os.path.join(c, ".git"))]
if not clones:
    print("Aucun dépôt du manifeste extra n'est cloné : l'option reste coupée.")
    sys.exit(0)
print("Dépôts du manifeste extra déjà clonés :", ", ".join(clones))
if erplibre_state.get_version_extra(version):
    print(f"Option extra déjà active pour {version}.")
    sys.exit(0)


def lire(nom):
    try:
        return open(nom).read().strip() or None
    except OSError:
        return None


etat = erplibre_state.read_state()
entree = etat["odoo_versions"].get(version) or {
    "installed": True,
    "python": lire(".python-odoo-version"),
    "poetry": lire(".poetry-version"),
    "installed_at": None,
    "switched_at": None,
}
entree["extra"] = True
etat["odoo_versions"][version] = entree
etat["current_odoo_version"] = etat.get("current_odoo_version") or version
erplibre_state.write_state(etat)
print(f"Option extra activée pour {version} dans {erplibre_state.STATE_FILE}.")
PY
EOF

# ── 4. lecture des dépôts git ──────────────────────────────────────────
etape "4. Dossiers de /ERPLibre/.repo lisibles par le compte odoo"
en_root <<'EOF'
set -euo pipefail
fermes=$(find /ERPLibre/.repo -type d ! -perm -o=rx -print | wc -l)
find /ERPLibre/.repo -type d ! -perm -o=rx -print0 | xargs -0 -r chmod go+rx
echo "Dossiers ouverts en lecture : ${fermes}"
EOF

# ── 5. modules, puis redémarrage ───────────────────────────────────────
etape "5. ${MODULES} dans la base ${BASE}, puis redémarrage"
en_odoo "${BASE}" "${MODULES}" <<'EOF'
set -euo pipefail
base="$1"
modules="$2"
cd /ERPLibre
# Le venv d'Odoo, que l'entrypoint active et que « docker exec » n'a pas.
py=".venv.$(cat .erplibre-version)/bin/python"
# Odoo ignore un nom de -i qu'il ne trouve pas, sur un simple avertissement
# que --log-level error tait : chaque module doit d'abord exister dans
# l'addons_path, et être installé après coup.
addons_path=$(sed -n 's/^[[:space:]]*addons_path[[:space:]]*=[[:space:]]*//p' /etc/odoo/odoo.conf)
IFS=',' read -ra chemins <<<"${addons_path// /}"
IFS=',' read -ra liste <<<"${modules}"
manquants=()
for m in "${liste[@]}"; do
  trouve=""
  for c in "${chemins[@]}"; do
    [[ -f "${c}/${m}/__manifest__.py" ]] && { trouve=1; break; }
  done
  [[ -n "${trouve}" ]] || manquants+=("${m}")
done
if ((${#manquants[@]})); then
  depot=odoo18.0/addons/ERPLibre_erplibre_addons
  # Un .git illisible pour ce compte fait remonter git jusqu'à la racine
  # ERPLibre : sa révision ne se lit que si git s'arrête bien sur le dépôt.
  g=(git -c safe.directory='*' -C "${depot}")
  if [[ "$("${g[@]}" rev-parse --show-toplevel 2>/dev/null)" == "${PWD}/${depot}" ]]; then
    revision=$("${g[@]}" log -1 --format='%h %s')
  else
    revision="illisible pour le compte $(id -un)"
  fi
  echo "Absents de l'addons_path du conteneur : ${manquants[*]}." >&2
  echo "${depot} doit être sur une révision qui les porte ; il est sur : ${revision}." >&2
  exit 1
fi
# -i installe ce qui ne l'est pas, -u met à jour ce qui l'est déjà.
"${py}" odoo18.0/odoo/odoo-bin -c /etc/odoo/odoo.conf \
  --db_host "${HOST:-db}" --db_port 5432 --db_user "${USER:-odoo}" \
  --db_password "${PASSWORD:-odoo}" -d "${base}" -i "${modules}" -u "${modules}" \
  --stop-after-init --no-http --workers 0 --max-cron-threads 0 \
  --log-level error >/tmp/erplibre_fix_install.log 2>&1 || {
  tail -40 /tmp/erplibre_fix_install.log >&2
  exit 1
}
"${py}" - "${base}" "${modules}" <<'PY' || exit 1
import os
import sys

import psycopg2

base, modules = sys.argv[1], sys.argv[2].split(",")
with psycopg2.connect(
    host=os.environ.get("HOST", "db"),
    port=5432,
    user=os.environ.get("USER", "odoo"),
    password=os.environ.get("PASSWORD", "odoo"),
    dbname=base,
) as cnx, cnx.cursor() as cur:
    cur.execute(
        "SELECT name, state FROM ir_module_module WHERE name = ANY(%s)",
        (modules,),
    )
    etats = dict(cur.fetchall())
pas_installes = [m for m in modules if etats.get(m) != "installed"]
if pas_installes:
    print(
        "Pas installés après -i : "
        + ", ".join(f"{m} ({etats.get(m, 'inconnu')})" for m in pas_installes)
        + " ; voir /tmp/erplibre_fix_install.log dans le conteneur.",
        file=sys.stderr,
    )
    sys.exit(1)
PY
echo "Modules installés (journal : /tmp/erplibre_fix_install.log dans le conteneur)."
EOF
docker restart "${CONTENEUR}" >/dev/null
echo "Attente d'Odoo sur le port 8069…"
for _ in $(seq 90); do
  if docker exec "${CONTENEUR}" python3 -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8069/web/login', timeout=3)" \
    2>/dev/null; then
    echo "Odoo répond."
    break
  fi
  sleep 2
done

# ── 6. premier instantané, à l'état d'avant ────────────────────────────
etape "6. Premier instantané, à l'état de la racine d'avant la mise à jour"
if en_odoo "${BASE}" "${MEMOIRE}" <<'EOF'
set -euo pipefail
base="$1"
memoire="$2"
cd /ERPLibre
py=".venv.$(cat .erplibre-version)/bin/python"
"${py}" odoo18.0/odoo/odoo-bin shell -c /etc/odoo/odoo.conf \
  --db_host "${HOST:-db}" --db_port 5432 --db_user "${USER:-odoo}" \
  --db_password "${PASSWORD:-odoo}" -d "${base}" --no-http \
  --log-level error 2>/tmp/erplibre_fix_snapshot.log <<PY
import base64, json
with open("${memoire}") as fh:
    avant = json.load(fh)
Snapshot = env["erplibre.code.snapshot"]
if avant.get("snapshot_id") and Snapshot.browse(avant["snapshot_id"]).exists():
    print("Instantané déjà ramené à l'état d'avant :", avant["snapshot_id"])
else:
    snap = Snapshot._capture("manual", force=True)
    data = json.loads(base64.b64decode(snap.raw_json))
    data["erplibre_after_update"] = dict(data.get("erplibre") or {})
    data["erplibre"] = {
        "version": avant["version"],
        "commit": avant["commit"],
        "head": avant["head"],
        "branch": avant["branch"],
        "dirty": avant["dirty"],
    }
    snap.write(
        {
            "erplibre_version": avant["version"],
            "erplibre_commit": avant["commit"],
            "erplibre_head": avant["head"],
            "erplibre_branch": avant["branch"] or False,
            "erplibre_dirty": avant["dirty"],
            "raw_json": base64.b64encode(
                json.dumps(data, ensure_ascii=False, indent=1).encode()
            ),
        }
    )
    env.cr.commit()
    avant["snapshot_id"] = snap.id
    with open("${memoire}", "w") as fh:
        json.dump(avant, fh, indent=1)
    print("Instantané", snap.id, ":", avant["commit"], "—", snap.state_summary)
    if snap.permission_warning:
        print("Avertissement :", snap.permission_warning)
PY
EOF
then
  :
else
  docker exec "${CONTENEUR}" tail -40 /tmp/erplibre_fix_snapshot.log >&2
  echec "l'instantané n'a pas abouti"
fi

etape "Terminé"
echo "Les instantanés sont dans le menu d'erplibre_info_git."
# Le tirage demande deux conditions que ce script ne pose pas : des dépôts git
# que le compte odoo peut écrire, et un serveur lancé avec une valeur de --dev.
# Chacune se lit dans le conteneur, et seule celle qui manque est nommée.
manques=$(en_odoo <<'EOF'
for d in /ERPLibre/.git /ERPLibre/.repo/projects; do
  if [[ ! -w "${d}" ]]; then
    echo "proprietaire ${d} $(stat -c %U "${d}")"
    break
  fi
done
pgrep -a -f odoo-bin | grep -qE -- '--dev(=|[[:space:]]+)[^-[:space:]]' ||
  echo "dev"
EOF
)
if [[ -z "${manques}" ]]; then
  echo "Le tirage est possible : installer erplibre_info_git_fetch depuis Applications."
fi
while read -r genre chemin compte; do
  case "${genre}" in
    proprietaire)
      echo "Pas de tirage depuis Odoo : ${chemin} appartient à ${compte}, que le compte odoo ne peut pas écrire."
      echo "  Il faut une image construite avec ERPLIBRE_CODE_OWNER=odoo, valeur par défaut des images récentes."
      ;;
    dev)
      echo "Pas de tirage depuis Odoo : le serveur tourne sans --dev."
      echo "  Le lancer par « command: odoo --dev=all » dans le compose, avec le « = »."
      ;;
  esac
done <<<"${manques}"
echo "La racine extraite ne survit pas à la recréation du conteneur ; la base garde ses instantanés."
