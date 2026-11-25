#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Cœur de l'installateur ERPLibre piloté par le profil machine.

Il ne pose aucune question : tout ce que l'écran demanderait arrive dans
un document de RÉPONSES (JSON), que l'interface Textual remplit ou qu'un
test passe par la ligne de commande du noyau. Déroulé :

  faits (facts.snapshot) → profil machine (machine.json du support, ou
  « generic ») → machine_profile.resolve(profil, faits, réponses) → refus
  sur question restante, mise en garde bloquante, secret manquant ou
  disque non confirmé → étape disque (erplibre_disk) → archinstall
  --silent --config --creds --plugin (erplibre_plugin) → verdict du
  greffon et de l'étape ERPLibre → démontage → code de sortie.

Document de réponses (schéma 1) :

  {"schema": 1,
   "answers": {"<chemin pointé du profil>": valeur, ...},
   "erplibre_profile": "odoo18" | "home" | "dev" | "gnome",
   "root": "lock" | "password",
   "confirm": {"disk": "<nom ou chemin du disque effacé>",
               "disk_size": <octets>, "disk_model": "<modèle>",
               "nvme_format": false},
   "offline": false,
   "secrets": {"user_password", "root_password", "luks_passphrase",
               "secret_lv_passphrase"}}

« answers » répond aux champs « ask » du profil (et à « disk.target »
quand « auto » ne trouve pas de disque) ; « system.console_keymap » prend
« live.keymap » s'il n'est pas donné. « root » vaut « lock » par défaut
quand le compte a sudo.

« confirm.disk_size » et « confirm.disk_model », facultatifs, sont la
taille et le modèle que le récapitulatif a montrés : le cœur relit le
matériel, et un nom de disque qui désigne désormais un autre disque
(débranché puis remplacé, nœuds renumérotés) est refusé (« disk-
changed ») au lieu d'être effacé. L'interface les donne toujours.

Les secrets ne sont acceptés que d'une source qui ne touche aucun disque :
le paramètre noyau « erplibre.answers=b64:<JSON en base64> » (tests
automatiques) ou un fichier sous RUN_DIR (tmpfs, écrit par l'interface).
Ils ne sont jamais journalisés ; ils passent à cryptsetup sur l'entrée
standard et à archinstall par un fichier --creds 0600 sur RUN_DIR, écrasé
puis effacé dès qu'archinstall rend la main.

Codes de sortie : 0 réussi ; 2 usage ; ceux de l'étape ERPLibre (3,
10 à 14, voir erplibre-stage.sh) ; EXIT_* ci-dessous pour le reste. En
mode automatique, la dernière ligne sur la console série est
« __ERPLIBRE_EXIT__ <code> ».

prepare() est pure : elle rend le plan complet (réglages, résumé, disque
effacé, commandes) que l'écran de récapitulatif affiche avant toute
écriture. run_install() l'exécute, par un `run` injecté.
"""

import argparse
import base64
import binascii
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time

SHARE_DIR = os.path.dirname(os.path.abspath(__file__))
MACHINE_DIR = os.path.join(SHARE_DIR, "machine")
if MACHINE_DIR not in sys.path:
    sys.path.insert(0, MACHINE_DIR)

import erplibre_archinstall as ai  # noqa: E402
import erplibre_disk as disk_mod  # noqa: E402
import erplibre_plugin as plugin_mod  # noqa: E402
import facts as facts_mod  # noqa: E402
import machine_profile as mp  # noqa: E402

ANSWERS_SCHEMA = 1
INLINE_PREFIX = "b64:"
ANSWERS_PARAM = "erplibre.answers"
UUID_PARAM = "archisosearchuuid"
EXIT_MARKER = "__ERPLIBRE_EXIT__"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_ANSWERS = 21
EXIT_PROFILE = 22
EXIT_DISK_REFUSED = 23
EXIT_DISK_FAILED = 24
EXIT_ARCHINSTALL_VERSION = 25
EXIT_ARCHINSTALL = 26
EXIT_PLUGIN = 27
EXIT_INTERRUPTED = 130
# L'étape ERPLibre attendue n'a laissé aucun fichier d'état.
EXIT_STAGE_MISSING = 1

DEFAULT_PATHS = {
    "share": SHARE_DIR,
    "profiles": os.path.join(MACHINE_DIR, "profiles"),
    "config_tool": os.path.normpath(
        os.path.join(SHARE_DIR, "..", "..", "bin", "erplibre-install-config")
    ),
    "plugin": os.path.join(SHARE_DIR, "erplibre_plugin.py"),
    "run": "/run/erplibre-install",
    "log": "/var/log/erplibre-install",
    "boot_mount": "/run/archiso/bootmnt",
    "target": disk_mod.TARGET,
    "cmdline": "/proc/cmdline",
}
MACHINE_REL = os.path.join("erplibre", "machine.json")
GENERIC_PROFILE = "generic"

TOP_KEYS = frozenset(
    {
        "schema",
        "answers",
        "erplibre_profile",
        "root",
        "confirm",
        "offline",
        "secrets",
    }
)
SECRET_FIELDS = (
    "user_password",
    "root_password",
    "luks_passphrase",
    "secret_lv_passphrase",
)

# Les mises en garde de resolve() qui interdisent d'effacer : le disque
# n'est pas sûr, ou une réponse a été refusée.
BLOCKING_WARNINGS = frozenset(
    {
        "no-disk",
        "disk-not-found",
        "disk-is-boot-medium",
        "disk-is-usb",
        "disk-unknown",
        "loader-needs-uefi",
        "answer-invalid",
    }
)

REASON_EXIT = {
    "answers-invalid": EXIT_ANSWERS,
    "questions": EXIT_ANSWERS,
    "secrets-missing": EXIT_ANSWERS,
    "root-lock-needs-sudo": EXIT_ANSWERS,
    "disk-not-confirmed": EXIT_ANSWERS,
    "profile-invalid": EXIT_PROFILE,
    "erplibre-profile-unknown": EXIT_PROFILE,
    "blocking-warnings": EXIT_PROFILE,
    "no-target": EXIT_DISK_REFUSED,
    "disk-too-small": EXIT_DISK_REFUSED,
    "disk-changed": EXIT_DISK_REFUSED,
}


# Réponses


def decode_answers(value, run_dir=DEFAULT_PATHS["run"]):
    """(document, secrets_permis) depuis la valeur de erplibre.answers :
    « b64:<base64> » est le JSON en ligne, le reste un chemin de fichier.
    Les secrets ne sont permis que d'une source en mémoire : en ligne, ou
    un fichier sous `run_dir`. ValueError si rien ne se lit."""
    if value.startswith(INLINE_PREFIX):
        try:
            brut = base64.b64decode(value[len(INLINE_PREFIX) :], validate=True)
            return json.loads(brut.decode("utf-8")), True
        except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
            raise ValueError(f"inline answers unreadable: {exc}") from exc
    try:
        with open(value, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ValueError(f"answers file unreadable: {exc}") from exc
    reel = os.path.realpath(value)
    racine = os.path.realpath(run_dir) + os.sep
    return doc, reel.startswith(racine)


def encode_answers(doc):
    """La valeur de erplibre.answers qui transporte `doc` en ligne : du
    base64 sans blanc, que le découpage de /proc/cmdline garde entier."""
    texte = json.dumps(doc, separators=(",", ":"), ensure_ascii=False)
    return INLINE_PREFIX + base64.b64encode(texte.encode("utf-8")).decode()


def check_answers(doc, secrets_allowed):
    """Les (code, détails) d'un document de réponses ; vide s'il est bien
    formé. Codes : not-object, schema, unknown-key, type, secrets-not-
    allowed, secret-format, root-policy."""
    if not isinstance(doc, dict):
        return [("not-object", {})]
    erreurs = []
    if doc.get("schema") != ANSWERS_SCHEMA:
        erreurs.append(("schema", {"expected": ANSWERS_SCHEMA}))
    for cle in doc:
        if cle not in TOP_KEYS:
            erreurs.append(("unknown-key", {"key": cle}))
    attendus = {
        "answers": dict,
        "confirm": dict,
        "secrets": dict,
        "offline": bool,
        "erplibre_profile": str,
        "root": str,
    }
    for cle, sorte in attendus.items():
        if cle in doc and not isinstance(doc[cle], sorte):
            erreurs.append(("type", {"key": cle}))
    if "root" in doc and doc["root"] not in ai.ROOT_POLICIES:
        erreurs.append(("root-policy", {"value": doc["root"]}))
    confirm = (
        doc.get("confirm") if isinstance(doc.get("confirm"), dict) else {}
    )
    for cle, sorte in (("disk_size", int), ("disk_model", (str, type(None)))):
        if cle in confirm and (
            not isinstance(confirm[cle], sorte)
            or isinstance(confirm[cle], bool)
        ):
            erreurs.append(("type", {"key": f"confirm.{cle}"}))
    secrets = (
        doc.get("secrets") if isinstance(doc.get("secrets"), dict) else {}
    )
    if secrets and not secrets_allowed:
        erreurs.append(("secrets-not-allowed", {}))
    for cle, valeur in secrets.items():
        if cle not in SECRET_FIELDS:
            erreurs.append(("unknown-key", {"key": f"secrets.{cle}"}))
        elif (
            not isinstance(valeur, str)
            or not valeur
            or any(c in valeur for c in "\r\n\0")
        ):
            # Une fin de ligne ferait partie de la clé LUKS lue par
            # --key-file=-, et ne se tape pas à l'invite du démarrage.
            erreurs.append(("secret-format", {"key": f"secrets.{cle}"}))
    return erreurs


def _answers_for_resolve(doc):
    reponses = dict(doc.get("answers") or {})
    if "system.console_keymap" not in reponses and "live.keymap" in reponses:
        reponses["system.console_keymap"] = reponses["live.keymap"]
    return reponses


def root_policy(doc, settings):
    """La politique root retenue : celle du document, sinon « lock » quand
    le compte a sudo, sinon « password »."""
    if doc.get("root") in ai.ROOT_POLICIES:
        return doc["root"]
    return ai.ROOT_LOCK if mp.get(settings, "user.sudo") else ai.ROOT_PASSWORD


def missing_secrets(settings, lay, policy, secrets):
    """Les noms des secrets que l'installation de `settings` exige et que
    `secrets` ne donne pas."""
    requis = ["user_password"]
    if policy == ai.ROOT_PASSWORD:
        requis.append("root_password")
    if lay and lay.get("luks"):
        requis.append("luks_passphrase")
        if lay.get("secret_gib"):
            requis.append("secret_lv_passphrase")
    return [n for n in requis if not secrets.get(n)]


def disk_confirmed(confirm, disque):
    """Vrai si la confirmation tapée nomme le disque retenu, par son nom
    (« nvme0n1 ») ou son chemin (« /dev/nvme0n1 »)."""
    tape = str((confirm or {}).get("disk") or "").strip()
    if not tape or not disque:
        return False
    return tape in (disque.get("name"), disque.get("path"))


def disk_changes(confirm, disque):
    """Les champs (« size », « model ») où le disque retenu diffère de ce
    que la confirmation a vu ; un champ absent de `confirm` n'est pas
    comparé."""
    confirm = confirm or {}
    disque = disque or {}
    ecarts = []
    for champ in ("size", "model"):
        cle = f"disk_{champ}"
        if cle in confirm and confirm[cle] != disque.get(champ):
            ecarts.append(champ)
    return ecarts


def _result(ok, reason=None, **champs):
    base = {
        "ok": ok,
        "reason": reason,
        "details": {},
        "settings": None,
        "questions": [],
        "warnings": [],
        "blocking": [],
        "summary": [],
        "disk": None,
        "erplibre_profile": None,
        "root_policy": None,
    }
    base.update(champs)
    return base


def prepare(profile, facts, doc, erplibre_keys, secrets_allowed=True):
    """Le plan complet, sans rien exécuter : {"ok", "reason", "details",
    "settings", "questions", "warnings", "blocking", "summary", "disk",
    "erplibre_profile", "root_policy"}.

    `profile` est le profil machine complet (machine_profile.effective),
    `facts` ceux de facts.facts_from, `doc` le document de réponses,
    `erplibre_keys` les clés de profiles.json. Les refus s'enchaînent dans
    l'ordre où l'écran les règle, et « disk-not-confirmed » vient en
    dernier : le récapitulatif a déjà tout (résumé, disque, commandes)
    quand il demande de taper le nom du disque."""
    erreurs = check_answers(doc, secrets_allowed)
    if erreurs:
        return _result(False, "answers-invalid", details={"errors": erreurs})
    invalides = mp.validate(profile)
    if invalides:
        return _result(False, "profile-invalid", details={"errors": invalides})
    if doc.get("erplibre_profile"):
        profile = mp.merge(
            profile, {"erplibre": {"profile": doc["erplibre_profile"]}}
        )
    settings, questions = mp.resolve(profile, facts, _answers_for_resolve(doc))
    alertes = settings.get("warnings") or []
    bloquantes = [a for a in alertes if a.get("code") in BLOCKING_WARNINGS]
    cle = mp.get(settings, "erplibre.profile")
    policy = root_policy(doc, settings)
    commun = {
        "settings": settings,
        "questions": questions,
        "warnings": alertes,
        "blocking": bloquantes,
        "summary": mp.plan_summary(settings),
        "erplibre_profile": cle,
        "root_policy": policy,
    }
    if questions:
        return _result(
            False, "questions", details={"questions": questions}, **commun
        )
    if bloquantes:
        return _result(
            False,
            "blocking-warnings",
            details={"warnings": bloquantes},
            **commun,
        )
    if cle not in erplibre_keys:
        return _result(
            False,
            "erplibre-profile-unknown",
            details={"value": cle, "allowed": list(erplibre_keys)},
            **commun,
        )
    if policy == ai.ROOT_LOCK and not mp.get(settings, "user.sudo"):
        return _result(False, "root-lock-needs-sudo", **commun)
    confirm = doc.get("confirm") or {}
    plan = disk_mod.plan(
        settings, {"nvme_format": confirm.get("nvme_format") is True}
    )
    commun["disk"] = plan
    if not plan["ok"]:
        return _result(
            False, plan["reason"], details=plan["details"], **commun
        )
    # Le formatage NVMe 4 KiB confirmé relève les secteurs LUKS à 4096 :
    # les réglages, donc le récapitulatif et settings.json de la cible,
    # reprennent la taille que le plan emploie.
    secteur = plan["details"].get("sector_size")
    if (
        plan["layout"].get("luks")
        and secteur
        and mp.get(settings, "disk.luks.sector_size") != secteur
    ):
        mp.put(settings, "disk.luks.sector_size", secteur)
        commun["summary"] = mp.plan_summary(settings)
    manquants = missing_secrets(
        settings, plan["layout"], policy, doc.get("secrets") or {}
    )
    if manquants:
        return _result(
            False, "secrets-missing", details={"missing": manquants}, **commun
        )
    disque = (settings.get("derived") or {}).get("disk")
    if not disk_confirmed(confirm, disque):
        return _result(
            False,
            "disk-not-confirmed",
            details={"expected": disque.get("name") if disque else None},
            **commun,
        )
    ecarts = disk_changes(confirm, disque)
    if ecarts:
        return _result(
            False,
            "disk-changed",
            details={"device": disque.get("path"), "fields": ecarts},
            **commun,
        )
    return _result(True, **commun)


# Profil machine et profils ERPLibre


def _run_quiet(run, argv):
    try:
        return (
            run(argv, capture_output=True, text=True, check=False).returncode
            == 0
        )
    except OSError:
        return False


def find_machine_profile(paths, params, run=subprocess.run):
    """(chemin lu, profil brut) de machine.json, ou (None, None).

    Cherché sur le support monté par archiso ; s'il n'y est plus
    (copytoram démonte le support une fois l'image copiée en mémoire), le
    support est remonté en lecture seule par l'UUID de
    « archisosearchuuid », lu, puis démonté."""
    sur_support = os.path.join(paths["boot_mount"], MACHINE_REL)
    if os.path.isfile(sur_support):
        return sur_support, mp.load(sur_support)
    uuid = params.get(UUID_PARAM)
    if not uuid:
        return None, None
    media = os.path.join(paths["run"], "media")
    os.makedirs(media, exist_ok=True)
    source = f"/dev/disk/by-uuid/{uuid}"
    if not _run_quiet(run, ["mount", "-o", "ro", source, media]):
        return None, None
    try:
        chemin = os.path.join(media, MACHINE_REL)
        if os.path.isfile(chemin):
            return f"{source}:/{MACHINE_REL}", mp.load(chemin)
        return None, None
    finally:
        _run_quiet(run, ["umount", media])


def machine_profile(paths, params, override=None, run=subprocess.run):
    """(origine, profil complet). `override` est un chemin imposé ; sans
    machine.json, le profil « generic » de l'ISO. ProfileError si le
    profil ne se lit pas ou si son « extends » ne se résout pas."""
    if override:
        origine, brut = override, mp.load(override)
    else:
        origine, brut = find_machine_profile(paths, params, run)
    if brut is None:
        chemin = mp.find(GENERIC_PROFILE, [paths["profiles"]])
        if chemin is None:
            raise mp.ProfileError("extends-missing", name=GENERIC_PROFILE)
        origine, brut = chemin, mp.load(chemin)
    return origine, mp.effective(brut, [paths["profiles"]])


def load_config_tool(path):
    """erplibre-install-config chargé comme module : sa configuration de
    base (bureau, réseau, étape ERPLibre) est reprise telle quelle. Aucun
    cache Python n'est écrit à côté du script : dans le dépôt, ce dossier
    part dans l'ISO."""
    loader = importlib.machinery.SourceFileLoader(
        "erplibre_install_config", path
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    garde = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = garde
    return module


# Exécution


class Logger:
    """Une ligne horodatée vers le fichier, l'écran et, en mode
    automatique, la console série. Aucun secret ne lui est jamais passé."""

    def __init__(self, path=None, serial=None, echo=True):
        self.path = path
        self.serial = serial
        self.echo = echo
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)

    def __call__(self, message):
        ligne = f"[erplibre] {message}"
        if self.echo:
            print(ligne, flush=True)
        for cible, horodate in ((self.path, True), (self.serial, False)):
            if not cible:
                continue
            try:
                with open(cible, "a", encoding="utf-8") as fh:
                    debut = (
                        time.strftime("%Y-%m-%dT%H:%M:%S ") if horodate else ""
                    )
                    fh.write(debut + ligne + "\n")
            except OSError:
                pass


def plugin_failures(status_path):
    """Les accroches du greffon dont le verdict est un échec, ou
    ["missing"] si le fichier de verdicts n'existe pas."""
    try:
        with open(status_path, encoding="utf-8") as fh:
            statut = json.load(fh)
    except (OSError, ValueError):
        return ["missing"]
    return [
        h
        for h, v in statut.items()
        if not (isinstance(v, dict) and v.get("ok"))
    ]


def stage_rc(target, has_stage):
    """Le code de l'étape ERPLibre lu dans la cible ; sans fichier d'état,
    0 si le profil n'a pas d'étape, EXIT_STAGE_MISSING sinon."""
    chemin = os.path.join(target, "var/lib/erplibre-install/status")
    try:
        with open(chemin, encoding="utf-8") as fh:
            for ligne in fh:
                if ligne.startswith("rc="):
                    valeur = ligne[3:].strip()
                    return int(valeur) if valeur.isdigit() else 1
    except OSError:
        pass
    return EXIT_STAGE_MISSING if has_stage else 0


def archinstall_argv(paths, offline=False):
    argv = [
        "archinstall",
        "--silent",
        "--skip-version-check",
        "--config",
        os.path.join(paths["run"], "config.json"),
        "--creds",
        os.path.join(paths["run"], "creds.json"),
        "--plugin",
        paths["plugin"],
        "--mountpoint",
        paths["target"],
    ]
    if offline:
        argv += ["--skip-ntp", "--skip-wkd"]
    return argv


def _read_text(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def run_install(
    doc,
    secrets_allowed,
    paths=None,
    override=None,
    tty="",
    serial=None,
    dry_run=False,
    run=subprocess.run,
    raw_facts=None,
    version=None,
    echo=True,
):
    """Installe selon `doc` ; rend le code de sortie. `raw_facts`,
    `version` et `run` remplacent la lecture du matériel, de la version
    d'archinstall et le lancement des commandes, `echo` faux garde le
    journal hors de l'écran (tests). `dry_run` s'arrête après prepare() :
    plan affiché, rien d'écrit."""
    paths = dict(DEFAULT_PATHS, **(paths or {}))
    log = Logger(os.path.join(paths["log"], "installer.log"), serial, echo)
    trouvee = (
        version if version is not None else plugin_mod.archinstall_version()
    )
    if not plugin_mod.version_ok(trouvee):
        log(f"archinstall {trouvee} is not the supported version: refused")
        return EXIT_ARCHINSTALL_VERSION
    brut = raw_facts if raw_facts is not None else facts_mod.snapshot()
    fx = facts_mod.facts_from(brut)
    params = facts_mod.cmdline_params(brut.get("cmdline"))
    try:
        origine, profil = machine_profile(paths, params, override, run)
    except mp.ProfileError as exc:
        log(f"machine profile unreadable: {exc.code} {exc.details}")
        return EXIT_PROFILE
    log(f"machine profile: {mp.get(profil, 'name')} ({origine})")

    outil = load_config_tool(paths["config_tool"])
    share = paths["share"]
    erplibre_doc = outil.load_json(os.path.join(share, outil.PROFILES_FILE))
    cles = [p["key"] for p in erplibre_doc.get("profiles", [])]
    prep = prepare(profil, fx, doc, cles, secrets_allowed)
    for libelle, valeur in prep["summary"]:
        log(f"  {libelle}: {valeur}")
    for alerte in prep["warnings"]:
        log(f"warning: {alerte}")
    plan = prep["disk"] or {}
    for step in plan.get("plan") or []:
        log(f"  plan: {disk_mod.describe(step)}")
    if not prep["ok"]:
        log(f"refused: {prep['reason']} {prep['details']}")
        return REASON_EXIT.get(prep["reason"], EXIT_ANSWERS)
    if dry_run:
        log("dry run: nothing executed")
        return EXIT_OK

    settings = prep["settings"]
    lay = plan["layout"]
    secrets = doc.get("secrets") or {}
    lsblk = subprocess_output(run, facts_mod.LSBLK_COMMAND)
    refus = disk_mod.preflight(
        settings["derived"]["disk"],
        lsblk,
        brut.get("cmdline"),
        nvme_format=disk_mod.plan_formats_nvme(plan["plan"]),
    )
    if refus:
        log(f"disk refused: {refus[0]} {refus[1]}")
        return EXIT_DISK_REFUSED

    disk_log = Logger(os.path.join(paths["log"], "disk.log"), serial, echo)
    log(f"erasing {lay['disk']}")
    try:
        ok, _indice, _rc = disk_mod.execute(
            plan["plan"],
            {
                disk_mod.SECRET_LUKS: secrets.get("luks_passphrase"),
                disk_mod.SECRET_LV: secrets.get("secret_lv_passphrase"),
            },
            run=run,
            log=disk_log,
        )
    except BaseException:
        # Ctrl-C ou SIGINT au milieu de luksFormat ou de lvcreate : sans
        # démontage, cryptlvm et le groupe resteraient ouverts, et la
        # relance serait refusée (« target-has-holders ») jusqu'au
        # redémarrage.
        log("disk stage interrupted")
        disk_mod.teardown(lay, run=run, log=disk_log, target=paths["target"])
        raise
    if not ok:
        log("disk stage failed")
        disk_mod.teardown(lay, run=run, log=disk_log, target=paths["target"])
        return EXIT_DISK_FAILED

    try:
        return _archinstall_phase(
            paths,
            doc,
            prep,
            lay,
            erplibre_doc,
            outil,
            fx,
            params,
            tty,
            run,
            log,
        )
    except Exception as exc:
        log(f"archinstall phase failed: {exc!r}")
        return EXIT_ARCHINSTALL
    finally:
        _copy_logs(paths)
        disk_mod.teardown(lay, run=run, log=disk_log, target=paths["target"])


def subprocess_output(run, argv):
    try:
        res = run(argv, capture_output=True, text=True, check=False)
    except OSError:
        return ""
    return res.stdout or ""


def _archinstall_phase(
    paths, doc, prep, lay, erplibre_doc, outil, fx, params, tty, run, log
):
    settings = prep["settings"]
    uuids = disk_mod.read_uuids(lay, run)
    manquants = disk_mod.missing_uuids(lay, uuids)
    if manquants:
        log(f"blkid gave no UUID for: {', '.join(manquants)}: refused")
        return EXIT_DISK_FAILED
    disk_state = dict(
        uuids, disk=lay["disk"], vg=lay["vg"], swap_dev=lay["swap_dev"]
    )
    profil_erplibre = outil.find_profile(
        erplibre_doc, prep["erplibre_profile"]
    )
    lang = outil.pick_lang(params, erplibre_doc)
    base = outil.build_config(
        outil.load_json(os.path.join(paths["share"], outil.TEMPLATE_FILE)),
        erplibre_doc,
        profil_erplibre,
        _read_text(os.path.join(paths["share"], outil.STAGE_FILE)),
        fx["firmware"]["mode"] == "uefi",
        tty,
        lang,
    )
    config = ai.machine_config(base, settings, paths["target"])
    a_etape = bool(config.get("custom_commands"))
    run_dir = paths["run"]
    etat = {
        "version": 1,
        "settings": settings,
        "facts": fx,
        "disk": disk_state,
        "keymap": mp.get(settings, "system.console_keymap"),
        "root_policy": prep["root_policy"],
        "status_path": os.path.join(run_dir, "plugin-status.json"),
        "log_path": os.path.join(paths["log"], "plugin.log"),
    }
    creds = os.path.join(run_dir, "creds.json")
    try:
        ai.write_private_json(os.path.join(run_dir, "config.json"), config)
        ai.write_private_json(os.path.join(run_dir, "plugin-state.json"), etat)
        if os.path.exists(etat["status_path"]):
            os.unlink(etat["status_path"])
        ai.write_private_json(
            creds,
            ai.credentials(
                settings, doc.get("secrets") or {}, prep["root_policy"]
            ),
        )
        env = dict(os.environ)
        env[plugin_mod.STATE_ENV] = os.path.join(run_dir, "plugin-state.json")
        argv = archinstall_argv(paths, doc.get("offline") is True)
        log(f"$ {' '.join(argv)}")
        try:
            rc = run(argv, env=env, check=False).returncode
        except OSError as exc:
            log(f"cannot run archinstall: {exc}")
            rc = 127
    finally:
        ai.shred(creds)
    log(f"archinstall: exit code {rc}")
    echecs = plugin_failures(etat["status_path"])
    if echecs:
        log(f"plugin failed: {', '.join(echecs)}")
        return EXIT_PLUGIN
    if rc != 0:
        return EXIT_ARCHINSTALL
    code = stage_rc(paths["target"], a_etape)
    log(f"ERPLibre stage: exit code {code}")
    return code


def _copy_logs(paths):
    """Les journaux de l'installateur (sans secret) recopiés dans la cible,
    à côté de ceux d'archinstall."""
    cible = os.path.join(paths["target"], "var/log/erplibre-install")
    if not os.path.isdir(os.path.join(paths["target"], "var/log")):
        return
    try:
        shutil.copytree(paths["log"], cible, dirs_exist_ok=True)
    except OSError:
        pass


def _parser():
    parser = argparse.ArgumentParser(
        description="ERPLibre installer core: machine profile + answers."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--answers", help="answers JSON file")
    source.add_argument(
        "--auto",
        action="store_true",
        help=f"answers from the kernel parameter {ANSWERS_PARAM}",
    )
    parser.add_argument("--machine", help="machine profile file (override)")
    parser.add_argument("--serial", help="serial console for the log lines")
    parser.add_argument(
        "--dry-run", action="store_true", help="plan only, nothing executed"
    )
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    paths = dict(DEFAULT_PATHS)
    if args.auto:
        params = facts_mod.cmdline_params(_read_text(paths["cmdline"]))
        valeur = params.get(ANSWERS_PARAM)
        if not valeur:
            _error(
                f"{ANSWERS_PARAM}= missing from the kernel command line", args
            )
            return _finish(EXIT_USAGE, args)
        source = valeur
    else:
        source = args.answers
    try:
        doc, permis = decode_answers(source, paths["run"])
    except ValueError as exc:
        _error(str(exc), args)
        return _finish(EXIT_ANSWERS, args)
    if not args.dry_run and os.geteuid() != 0:
        _error("root is required", args)
        return _finish(EXIT_USAGE, args)
    tty = args.serial or ""
    if not tty and os.isatty(0):
        tty = os.ttyname(0)
    try:
        rc = run_install(
            doc,
            permis,
            override=args.machine,
            tty=tty,
            serial=args.serial if args.auto else None,
            dry_run=args.dry_run,
        )
    except KeyboardInterrupt:
        # Le disque est déjà rendu (voir run_install) ; le code 130 est
        # celui d'un processus interrompu par SIGINT.
        _error("interrupted", args)
        rc = EXIT_INTERRUPTED
    return _finish(rc, args)


def _append_serial(args, ligne):
    if args.auto and args.serial:
        try:
            with open(args.serial, "a", encoding="utf-8") as fh:
                fh.write(ligne + "\n")
        except OSError:
            pass


def _error(message, args):
    """Un refus d'avant le journal : sur stderr et, en mode automatique,
    sur la console série, que lit le test long à côté du code de
    sortie."""
    print(message, file=sys.stderr)
    _append_serial(args, f"[erplibre] {message}")


def _finish(rc, args):
    if args.auto:
        ligne = f"{EXIT_MARKER} {rc}"
        print(ligne, flush=True)
        _append_serial(args, ligne)
    return rc


if __name__ == "__main__":
    sys.exit(main())
