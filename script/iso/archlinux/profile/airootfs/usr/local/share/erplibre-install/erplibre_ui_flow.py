#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le déroulé de l'interface de l'installateur, commun à l'écran Textual
et au mode texte : quels champs demander, comment lire et vérifier une
réponse, le document de réponses qui en sort, le récapitulatif, puis le
lancement du cœur (erplibre-installer).

Les deux interfaces ne font qu'afficher et saisir : chaque décision vit
ici, pour qu'elles posent les mêmes questions et refusent les mêmes
réponses.

Un champ est un dict {"key", "kind", "label", "choices", "default",
"help"} :

- kind « keymap », « text », « choice », « bool », « secret » ou
  « confirm » (la confirmation d'un secret, « of » nomme ce secret) ;
- key est un chemin pointé du profil machine pour un champ « ask »
  (« system.timezone »), ou un nom propre à l'interface : « keymap »,
  « disk », « erplibre_profile », « root » et les secrets de
  erplibre_installer.SECRET_FIELDS ;
- les valeurs saisies forment un dict clé → texte (ou booléen pour
  « bool »), que collect() traduit en document de réponses.

Pures, sauf ce qui touche le live et le dit : load_context (matériel et
support), apply_keymap, live_status, wait_ready, run_core,
archinstall_commands. Chacune prend son `run` ou son `popen`.
"""

import os
import re
import subprocess
import time

import erplibre_archinstall as ai
import erplibre_disk as disk_mod
import erplibre_installer as core
import facts as facts_mod
import machine_profile as mp
import profile_messages as pm
from erplibre_ui_i18n import N_

MIB = 1024**2
GIB = 1024**3

KEYMAP_DIR = "/usr/share/kbd/keymaps"
ZONEINFO_DIR = "/usr/share/zoneinfo"
KEYMAP_SUFFIXES = (".map.gz", ".map")
DEFAULT_KEYMAP = "us"
DEFAULT_TIMEZONE = "UTC"
# Une phrase LUKS plus courte se devine trop vite hors ligne : l'en-tête
# se copie avec le disque.
MIN_LUKS_CHARS = 8
# Les caractères qu'aucune saisie ne doit porter : une fin de ligne ferait
# partie de la clé lue par cryptsetup, et ne se tape pas à l'invite.
FORBIDDEN_SECRET_CHARS = "\r\n\0"

CORE_BIN = "/usr/local/bin/erplibre-installer"
CONFIG_BIN = "/usr/local/bin/erplibre-install-config"
TODO_BIN = "/usr/local/bin/erplibre-todo"
GUIDED_CONFIG = "/root/erplibre/user_configuration.json"
ANSWERS_FILE = "answers.json"
# Le journal de l'étape ERPLibre, écrit DANS la cible par erplibre-stage.sh
# (EL_LOG) : la cible est montée sous TARGET pendant toute l'installation.
STAGE_LOG_REL = "var/log/erplibre-install.log"
# Nom que wait_ready doit pouvoir résoudre : le réseau sert les miroirs
# Arch au pacstrap d'archinstall.
NETWORK_PROBE_HOST = "archlinux.org"
NETWORK_EXIT = 20

ANSI_RE = re.compile(r"\x1b(\[[0-9;?]*[ -/]*[@-~]|\][^\x07]*\x07|[@-Z\\-_])")

# Les champs « ask » qu'un widget propre remplace : le clavier (premier
# champ, il sert aussi à la console de la cible), le disque, le compte et
# le profil ERPLibre.
OWN_WIDGET_PATHS = frozenset(
    {
        "live.keymap",
        "system.console_keymap",
        "disk.target",
        "user.name",
        "erplibre.profile",
    }
)

FIELD_LABELS = {
    "disk.layout": N_("Disk layout"),
    "system.hostname": N_("Host name"),
    "system.timezone": N_("Time zone (Area/City)"),
    "system.locales": N_("Locales (comma separated)"),
    "system.lang": N_("System language (one of the locales)"),
    "security.header_backup": N_("Back up the LUKS header"),
}
FIELD_DEFAULTS = {
    "system.hostname": "erplibre",
    "system.timezone": DEFAULT_TIMEZONE,
    "system.locales": "en_US.UTF-8",
    "system.lang": "en_US.UTF-8",
    "security.header_backup": False,
}
LAYOUT_CHOICES = (
    ("lvm_on_luks", N_("LVM on LUKS (encrypted)")),
    ("plain", N_("plain (not encrypted)")),
)
ROOT_CHOICES = (
    (ai.ROOT_LOCK, N_("locked: administration through sudo")),
    (ai.ROOT_PASSWORD, N_("its own password")),
)

# Les refus de erplibre_installer.prepare() et de erplibre_disk.plan(),
# et les codes de sortie du cœur.
PREPARE_REASONS = {
    "answers-invalid": N_("The answers are malformed: {errors}"),
    "profile-invalid": N_("The machine profile is invalid."),
    "questions": N_("Some questions are still unanswered: {questions}"),
    "blocking-warnings": N_("The installation cannot go on:"),
    "erplibre-profile-unknown": N_(
        "The ERPLibre profile « {value} » does not exist on this key."
    ),
    "root-lock-needs-sudo": N_(
        "Root can only be locked when the user has sudo."
    ),
    "no-target": N_("No disk is chosen."),
    "disk-too-small": N_(
        "The disk is too small: the system would get {root_mib} MiB, "
        "{minimum_mib} MiB at least."
    ),
    "secrets-missing": N_("Missing: {missing}"),
    "disk-not-confirmed": N_("Type the disk name to confirm."),
    "disk-changed": N_(
        "{device} is no longer the disk shown on the summary ({fields}): "
        "nothing was erased."
    ),
}
EXIT_MESSAGES = {
    0: N_("The installation succeeded."),
    1: N_("The ERPLibre stage did not run."),
    2: N_("The installer was started wrongly."),
    3: N_("The ERPLibre stage found no user account."),
    10: N_("The ERPLibre stage could not set up sudo."),
    11: N_("The ERPLibre stage could not clone ERPLibre."),
    12: N_("The ERPLibre stage could not start PostgreSQL."),
    13: N_("The ERPLibre profile command failed."),
    14: N_("The erplibre service could not be installed."),
    NETWORK_EXIT: N_("No network: connect a cable, or Wi-Fi with iwctl."),
    core.EXIT_ANSWERS: N_("The answers were refused."),
    core.EXIT_PROFILE: N_("The machine profile was refused."),
    core.EXIT_DISK_REFUSED: N_(
        "The disk changed or is in use: nothing was erased."
    ),
    core.EXIT_DISK_FAILED: N_("Preparing the disk failed."),
    core.EXIT_ARCHINSTALL_VERSION: N_(
        "This archinstall version is not the supported one."
    ),
    core.EXIT_ARCHINSTALL: N_("archinstall failed."),
    core.EXIT_PLUGIN: N_("The ERPLibre archinstall plugin failed."),
    core.EXIT_INTERRUPTED: N_(
        "The installation was interrupted; the disk was released."
    ),
}
SECRET_LABELS = {
    "user_password": N_("User password"),
    "root_password": N_("Root password"),
    "luks_passphrase": N_("Disk encryption passphrase (LUKS)"),
    "secret_lv_passphrase": N_("Secret volume passphrase"),
}
CONFIRM_LABEL = N_("Confirm: {label}")


# Contexte : le live, le matériel, les profils


def load_context(
    paths=None, run=subprocess.run, raw_facts=None, lang=None, override=None
):
    """Ce que l'interface affiche et dont collect() a besoin :

    {"paths", "facts", "params", "profile", "origin", "machine_found",
    "profile_error", "erplibre", "erplibre_doc", "lang", "keymaps",
    "timezones"}.

    Le profil machine vient de machine.json sur le support (relu par
    erplibre_installer.machine_profile, copytoram compris), du profil
    « generic » sinon ; un profil illisible laisse profile à None et son
    code dans profile_error."""
    paths = dict(core.DEFAULT_PATHS, **(paths or {}))
    brut = raw_facts if raw_facts is not None else facts_mod.snapshot()
    fx = facts_mod.facts_from(brut)
    params = facts_mod.cmdline_params(brut.get("cmdline"))
    profil, origine, erreur = None, None, None
    try:
        origine, profil = core.machine_profile(paths, params, override, run)
    except mp.ProfileError as exc:
        erreur = (exc.code, exc.details)
    racine_profils = os.path.realpath(paths["profiles"]) + os.sep
    trouve = bool(origine) and not os.path.realpath(
        str(origine).split(":")[0]
    ).startswith(racine_profils)
    outil = core.load_config_tool(paths["config_tool"])
    try:
        doc = outil.load_json(
            os.path.join(paths["share"], outil.PROFILES_FILE)
        )
    except (OSError, ValueError):
        doc = {}
    langue = lang or outil.pick_lang(params, doc)
    return {
        "paths": paths,
        "facts": fx,
        "params": params,
        "profile": profil,
        "origin": origine,
        "machine_found": trouve,
        "profile_error": erreur,
        "erplibre": [
            {"key": p["key"], "label": outil.profile_label(p, langue)}
            for p in doc.get("profiles", [])
        ],
        "erplibre_doc": doc,
        "lang": langue,
        "keymaps": list_keymaps(paths.get("keymaps", KEYMAP_DIR)),
        "timezones": list_timezones(paths.get("zoneinfo", ZONEINFO_DIR)),
    }


def list_keymaps(root=KEYMAP_DIR):
    """Les noms de disposition que loadkeys accepte : les fichiers
    *.map(.gz) sous `root`, sans leur suffixe, triés ; vide si `root`
    manque (le dépôt, un test)."""
    noms = set()
    for dossier, _sous, fichiers in os.walk(root):
        for fichier in fichiers:
            for suffixe in KEYMAP_SUFFIXES:
                if fichier.endswith(suffixe):
                    noms.add(fichier[: -len(suffixe)])
                    break
    return sorted(noms)


def list_timezones(root=ZONEINFO_DIR):
    """Les fuseaux « Zone/Ville » de `root` qui passent le motif du profil
    machine, triés ; vide si `root` manque. Les arbres « posix » et
    « right » doublent les autres et sont écartés."""
    zones = []
    if not os.path.isdir(root):
        return zones
    for dossier, sous, fichiers in os.walk(root):
        sous[:] = [s for s in sous if s not in ("posix", "right", "Etc")]
        for fichier in fichiers:
            rel = os.path.relpath(os.path.join(dossier, fichier), root)
            if rel == DEFAULT_TIMEZONE or (
                "/" in rel and mp.TIMEZONE_RE.match(rel)
            ):
                zones.append(rel)
    return sorted(zones)


def profile_name(ctx):
    """Le nom du profil machine, ou None sans profil lisible."""
    if not ctx.get("profile"):
        return None
    return mp.get(ctx["profile"], "name")


# Champs


def _field(key, kind, label, choices=None, default=None, **extra):
    champ = {
        "key": key,
        "kind": kind,
        "label": label,
        "choices": list(choices or []),
        "default": default,
    }
    champ.update(extra)
    return champ


def ask_paths(profile):
    """Les chemins « ask » du profil, dans l'ordre de FIELDS."""
    return [p for p in mp.FIELDS if mp.get(profile, p) == mp.ASK]


def default_keymap(ctx):
    """Le clavier proposé : celui que le profil impose au live, sinon
    celui de la console cible, sinon DEFAULT_KEYMAP."""
    p = ctx.get("profile") or {}
    for chemin in ("live.keymap", "system.console_keymap"):
        valeur = mp.get(p, chemin)
        if isinstance(valeur, str) and valeur not in (mp.ASK, mp.AUTO):
            return valeur
    return DEFAULT_KEYMAP


def disk_candidates(ctx):
    """Les disques que l'installation peut effacer, ceux que « auto »
    considère : fixes, internes, ni support de démarrage ni trop petits."""
    return mp._candidats(ctx.get("facts") or {})


def disk_label(disque):
    """« /dev/nvme0n1  500 GiB  Modèle  nvme » : la ligne d'un disque."""
    morceaux = [
        disque.get("path") or "?",
        f"{(disque.get('size') or 0) // GIB} GiB",
        disque.get("model") or "",
        disque.get("tran") or "",
    ]
    return "  ".join(m for m in morceaux if m)


def disk_field_needed(ctx):
    """Vrai si l'écran doit faire choisir le disque : le profil demande
    « ask », ou « auto » ne tranche pas (aucun candidat, plusieurs, ou un
    support de démarrage non reconnu, qui interdit le choix
    automatique)."""
    cible = mp.get(ctx["profile"], "disk.target")
    if cible == mp.ASK:
        return True
    if cible == mp.AUTO and (ctx.get("facts") or {}).get(
        "boot_medium_unknown"
    ):
        return True
    return cible == mp.AUTO and len(disk_candidates(ctx)) != 1


def _secret_lv(ctx):
    secret = mp.get(ctx["profile"], "disk.lvm.secret_lv")
    return secret if isinstance(secret, dict) else None


def form_fields(ctx, tr):
    """Tous les champs que le formulaire peut montrer, dans l'ordre de
    l'écran : le clavier d'abord, puis chaque « ask » du profil, le
    compte, ses mots de passe, root, les phrases LUKS, le disque et le
    profil ERPLibre. visible() dit lesquels s'affichent selon les
    valeurs déjà saisies. Libellés traduits par `tr`."""
    p = ctx["profile"]
    champs = [
        _field(
            "keymap",
            "keymap",
            tr("Keyboard layout (applied now)"),
            choices=ctx.get("keymaps") or [],
            default=default_keymap(ctx),
        )
    ]
    for chemin in ask_paths(p):
        if chemin in OWN_WIDGET_PATHS:
            continue
        libelle = tr(FIELD_LABELS.get(chemin, chemin))
        sorte = mp.FIELDS[chemin][2]
        if chemin == "disk.layout":
            champs.append(
                _field(
                    chemin,
                    "choice",
                    libelle,
                    [(v, tr(lib)) for v, lib in LAYOUT_CHOICES],
                )
            )
        elif sorte == "bool":
            champs.append(
                _field(
                    chemin,
                    "bool",
                    libelle,
                    default=FIELD_DEFAULTS.get(chemin, False),
                )
            )
        else:
            choix = ctx.get("timezones") if chemin == "system.timezone" else []
            champs.append(
                _field(
                    chemin,
                    "text",
                    libelle,
                    choices=choix,
                    default=FIELD_DEFAULTS.get(chemin, ""),
                )
            )
    secret = _secret_lv(ctx)
    if secret and secret.get("optional"):
        champs.append(
            _field(
                "disk.lvm.secret_lv",
                "bool",
                tr(
                    "Create the secret volume ({size} GiB)",
                    size=secret.get("size_gib"),
                ),
                default=False,
            )
        )
    if mp.get(p, "user.name") == mp.ASK:
        champs.append(_field("user.name", "text", tr("User name")))
    champs += _secret_pair("user_password", tr)
    if mp.get(p, "user.sudo"):
        champs.append(
            _field(
                "root",
                "choice",
                tr("Root account"),
                [(v, tr(lib)) for v, lib in ROOT_CHOICES],
                default=ai.ROOT_LOCK,
            )
        )
    champs += _secret_pair("root_password", tr)
    champs += _secret_pair("luks_passphrase", tr)
    champs += _secret_pair("secret_lv_passphrase", tr)
    if disk_field_needed(ctx):
        candidats = disk_candidates(ctx)
        auto = (
            max(candidats, key=lambda d: d.get("size") or 0)
            if candidats
            else None
        )
        champs.append(
            _field(
                "disk",
                "choice",
                tr("Disk to ERASE"),
                [(d["path"], disk_label(d)) for d in candidats],
                default=auto["path"] if auto else None,
            )
        )
    champs.append(
        _field(
            "erplibre_profile",
            "choice",
            tr("ERPLibre profile"),
            [(e["key"], e["label"]) for e in ctx.get("erplibre") or []],
            default=_default_erplibre(ctx),
        )
    )
    return champs


def _secret_pair(nom, tr):
    libelle = tr(SECRET_LABELS[nom])
    return [
        _field(nom, "secret", libelle),
        _field(
            f"{nom}_confirm",
            "confirm",
            tr(CONFIRM_LABEL, label=libelle),
            of=nom,
        ),
    ]


def _default_erplibre(ctx):
    cles = [e["key"] for e in ctx.get("erplibre") or []]
    voulu = mp.get(ctx["profile"], "erplibre.profile")
    if voulu in cles:
        return voulu
    defaut = (ctx.get("erplibre_doc") or {}).get("default_profile")
    if defaut in cles:
        return defaut
    return cles[0] if cles else None


def layout_of(ctx, values):
    """La disposition retenue : celle du profil, ou la réponse saisie."""
    disposition = mp.get(ctx["profile"], "disk.layout")
    if disposition == mp.ASK:
        return values.get("disk.layout")
    return disposition


def has_secret_lv(ctx, values):
    """Vrai si l'installation crée le volume secret : disposition
    chiffrée, volume au profil, et accepté s'il est facultatif."""
    secret = _secret_lv(ctx)
    if not secret or layout_of(ctx, values) != "lvm_on_luks":
        return False
    if secret.get("optional"):
        return values.get("disk.lvm.secret_lv") is True
    return True


def root_choice(ctx, values):
    """La politique root saisie, « password » d'office sans sudo."""
    if not mp.get(ctx["profile"], "user.sudo"):
        return ai.ROOT_PASSWORD
    return values.get("root") or ai.ROOT_LOCK


def visible(ctx, values):
    """Les clés des champs à montrer pour les valeurs `values`."""
    luks = layout_of(ctx, values) == "lvm_on_luks"
    cles = set()
    for champ in form_fields(ctx, lambda texte, **_c: texte):
        cle = champ["key"]
        base = champ.get("of", cle)
        if base == "root_password" and (
            root_choice(ctx, values) != ai.ROOT_PASSWORD
        ):
            continue
        if base == "luks_passphrase" and not luks:
            continue
        if base == "secret_lv_passphrase" and not has_secret_lv(ctx, values):
            continue
        if cle == "disk.lvm.secret_lv" and not luks:
            continue
        cles.add(cle)
    return cles


# Lecture et vérification des réponses


def reason_message(tr, code, details):
    """La phrase d'un code de validation du profil machine."""
    phrase = pm.REASONS.get(code, code)
    return tr(phrase, **dict({"path": "?"}, **(details or {})))


def warning_message(tr, alerte):
    """La phrase d'une mise en garde de machine_profile.resolve() ou de
    erplibre_disk.plan()."""
    code = alerte.get("code")
    phrase = pm.WARNINGS.get(code) or DISK_WARNINGS.get(code) or code
    return tr(phrase, **{k: v for k, v in alerte.items() if k != "code"})


DISK_WARNINGS = {
    "nvme-format-skipped": N_(
        "The disk can be reformatted to 4 KiB sectors (format {lbaf}); "
        "it is not, unless you tick the box."
    ),
}


def check_profile_answer(path, text, tr):
    """(valeur, None) si `text` est une réponse acceptée pour le champ
    « ask » `path`, (None, phrase) sinon. « auto » et « ask » ne sont
    jamais des réponses."""
    try:
        valeur = mp.parse_value(path, str(text))
    except ValueError:
        return None, reason_message(
            tr,
            "type",
            {"path": path, "value": text, "expected": mp.FIELDS[path][2]},
        )
    if valeur in (mp.AUTO, mp.ASK):
        return None, reason_message(
            tr, "special", {"path": path, "value": valeur}
        )
    verificateur = mp.FIELDS[path][0]
    erreurs = verificateur(valeur) if verificateur else []
    if erreurs:
        code, details = erreurs[0]
        return None, reason_message(
            tr,
            code,
            dict(details, path=path, value=mp.display_value(valeur)),
        )
    return valeur, None


def check_keymap(name, keymaps, tr):
    """La phrase qui refuse le clavier `name`, ou None. Sans liste (le
    dépôt, un test), le motif seul décide."""
    if not name or not mp.KEYMAP_RE.match(name):
        return tr("« {value} » is not a keyboard layout name.", value=name)
    if keymaps and name not in keymaps:
        return tr(
            "The keyboard layout « {value} » does not exist.", value=name
        )
    return None


def check_secret(nom, valeur, tr):
    """La phrase qui refuse le secret `valeur`, ou None."""
    if not valeur:
        return tr("This field is required.")
    if any(c in valeur for c in FORBIDDEN_SECRET_CHARS):
        return tr("Line breaks are not accepted.")
    if nom in ("luks_passphrase", "secret_lv_passphrase") and (
        len(valeur) < MIN_LUKS_CHARS
    ):
        return tr(
            "At least {count} characters are required.", count=MIN_LUKS_CHARS
        )
    return None


def collect(ctx, values, tr):
    """(document, erreurs) : le document de réponses (schéma 1, voir
    erplibre_installer) tiré des valeurs saisies, et les erreurs
    [(clé du champ, phrase)] des champs visibles. Le document n'est
    utilisable que si `erreurs` est vide ; confirm reste vide, le
    récapitulatif le remplit."""
    montres = visible(ctx, values)
    erreurs = []
    reponses = {}
    secrets = {}
    doc = {
        "schema": core.ANSWERS_SCHEMA,
        "answers": reponses,
        "confirm": {},
        "offline": False,
        "secrets": secrets,
    }
    for champ in form_fields(ctx, tr):
        cle = champ["key"]
        if cle not in montres:
            continue
        valeur = values.get(cle)
        sorte = champ["kind"]
        if sorte == "keymap":
            refus = check_keymap(valeur, ctx.get("keymaps"), tr)
            if refus:
                erreurs.append((cle, refus))
            else:
                reponses["live.keymap"] = valeur
        elif sorte == "secret":
            refus = check_secret(cle, valeur or "", tr)
            if refus:
                erreurs.append((cle, refus))
            else:
                secrets[cle] = valeur
        elif sorte == "confirm":
            if cle_ok(erreurs, champ["of"]) and values.get(champ["of"]) != (
                valeur or ""
            ):
                erreurs.append((cle, tr("The two entries differ.")))
        elif cle == "disk":
            if not champ["choices"]:
                erreurs.append(
                    (cle, tr("No disk of this computer can be erased."))
                )
            elif valeur not in [c[0] for c in champ["choices"]]:
                erreurs.append((cle, tr("Choose a disk.")))
            else:
                reponses["disk.target"] = valeur
        elif cle == "erplibre_profile":
            if valeur not in [c[0] for c in champ["choices"]]:
                erreurs.append((cle, tr("Choose a profile.")))
            else:
                doc["erplibre_profile"] = valeur
        elif cle == "root":
            doc["root"] = root_choice(ctx, values)
        elif cle == "disk.lvm.secret_lv":
            reponses[cle] = valeur is True
        elif sorte == "choice":
            if valeur not in [c[0] for c in champ["choices"]]:
                erreurs.append((cle, tr("Choose a value.")))
            else:
                reponses[cle] = valeur
        elif sorte == "bool":
            reponses[cle] = valeur is True
        else:
            if not str(valeur or "").strip():
                erreurs.append((cle, tr("This field is required.")))
                continue
            lue, refus = check_profile_answer(cle, valeur, tr)
            if refus:
                erreurs.append((cle, refus))
            else:
                reponses[cle] = lue
    if "root" not in doc:
        doc["root"] = root_choice(ctx, values)
    return doc, erreurs


def cle_ok(erreurs, cle):
    """Vrai si le champ `cle` n'a pas d'erreur : une confirmation ne se
    compare qu'à un secret accepté."""
    return all(c != cle for c, _m in erreurs)


# Récapitulatif


def review(ctx, doc, tr):
    """{"ok", "prep", "messages"} : prepare() du cœur sur `doc`, sans
    confirmation du disque. ok est vrai quand seul le nom du disque à
    retaper manque : le récapitulatif peut s'afficher. messages porte
    sinon les phrases qui disent pourquoi."""
    cles = [e["key"] for e in ctx.get("erplibre") or []]
    prep = core.prepare(ctx["profile"], ctx["facts"], doc, cles, True)
    if prep["reason"] == "disk-not-confirmed":
        return {"ok": True, "prep": prep, "messages": []}
    if prep["ok"]:
        return {"ok": True, "prep": prep, "messages": []}
    return {"ok": False, "prep": prep, "messages": refusal_messages(tr, prep)}


def refusal_messages(tr, prep):
    """Les phrases d'un prepare() refusé."""
    raison = prep.get("reason")
    details = dict(prep.get("details") or {})
    for cle in ("questions", "missing", "fields"):
        if isinstance(details.get(cle), list):
            details[cle] = ", ".join(details[cle])
    if isinstance(details.get("errors"), list):
        details["errors"] = ", ".join(str(e[0]) for e in details["errors"])
    lignes = [tr(PREPARE_REASONS.get(raison, raison or "?"), **details)]
    if raison == "blocking-warnings":
        lignes += [
            "  " + warning_message(tr, a) for a in prep.get("blocking") or []
        ]
    if raison == "profile-invalid":
        lignes += [
            "  " + reason_message(tr, code, det)
            for code, det in (prep.get("details") or {}).get("errors", [])
        ]
    return lignes


def summary_lines(tr, settings):
    """[(libellé, valeur)] de plan_summary, libellés et jetons
    traduits."""
    lignes = []
    for libelle, valeur in mp.plan_summary(settings):
        valeur = ", ".join(
            tr(pm.TOKENS[m]) if m in pm.TOKENS else m
            for m in str(valeur).split(", ")
        )
        lignes.append((tr(libelle), valeur))
    return lignes


def hardware_lines(tr, facts):
    """[(libellé, valeur)] des faits du matériel qui orientent le plan."""
    fw = facts.get("firmware") or {}
    micrologiciel = (fw.get("mode") or "?").upper()
    if fw.get("bits"):
        micrologiciel += f" {fw['bits']} bits"
    cpu = facts.get("cpu") or {}
    cartes = ", ".join(
        sorted({g.get("vendor") or "?" for g in facts.get("gpus") or []})
    )
    oui, non = tr("yes"), tr("no")
    return [
        (tr("Firmware"), micrologiciel),
        (tr("Processor"), cpu.get("vendor") or "?"),
        (tr("Virtual machine"), oui if facts.get("virtual") else non),
        (tr("Memory"), f"{(facts.get('ram_mib') or 0) // 1024} GiB"),
        (tr("Graphics"), cartes or tr("none")),
        (tr("Laptop"), oui if facts.get("laptop") else non),
        (tr("Wi-Fi"), oui if facts.get("wifi") else non),
    ]


def recap(ctx, doc, prep, tr):
    """Ce que l'écran de récapitulatif montre avant d'effacer :

    {"profile", "summary", "hardware", "warnings", "disk", "partitions",
    "commands", "expected", "nvme_lbaf"}.

    disk est la ligne du disque EFFACÉ, expected le nom à retaper,
    nvme_lbaf l'indice du format NVMe 4 KiB proposé (None sinon : la case
    ne s'affiche pas). warnings comprend les mises en garde du profil, du
    plan disque, et celles du clavier et des phrases LUKS."""
    settings = prep["settings"]
    disque = (settings.get("derived") or {}).get("disk") or {}
    plan = prep.get("disk") or {}
    lay = plan.get("layout") or {}
    alertes = [warning_message(tr, a) for a in prep.get("warnings") or []]
    alertes += [warning_message(tr, a) for a in plan.get("warnings") or []]
    alertes += secret_warnings(ctx, doc, settings, tr)
    lbaf = mp.get(settings, "disk.nvme_lba_4k")
    return {
        "profile": profile_title(ctx, tr),
        "summary": summary_lines(tr, settings),
        "hardware": hardware_lines(tr, ctx["facts"]),
        "warnings": alertes,
        "disk": disk_label(disque) if disque else "?",
        "partitions": [
            f"{p['number']}  {p['name']}  {p['mib']} MiB"
            for p in lay.get("partitions") or []
        ],
        "commands": [disk_mod.describe(s) for s in plan.get("plan") or []],
        "expected": disque.get("name"),
        "nvme_lbaf": lbaf
        if isinstance(lbaf, int) and not isinstance(lbaf, bool)
        else None,
    }


def secret_warnings(ctx, doc, settings, tr):
    """Les mises en garde sur les phrases LUKS : la console de la cible
    n'a pas le clavier où elles ont été tapées, ou elles portent des
    caractères hors ASCII, qu'une disposition différente ou l'invite du
    démarrage peuvent ne pas produire."""
    if mp.get(settings, "disk.layout") != "lvm_on_luks":
        return []
    alertes = []
    live = (doc.get("answers") or {}).get("live.keymap")
    cible = mp.get(settings, "system.console_keymap")
    if live and cible and live != cible:
        alertes.append(
            tr(
                "The passphrase is typed with « {live} » but the installed "
                "system asks for it with « {target} »: check that it types "
                "the same.",
                live=live,
                target=cible,
            )
        )
    secrets = doc.get("secrets") or {}
    if any(
        not v.isascii()
        for k, v in secrets.items()
        if k in ("luks_passphrase", "secret_lv_passphrase")
    ):
        alertes.append(
            tr(
                "The passphrase has non-ASCII characters: make sure the "
                "boot prompt can type them."
            )
        )
    return alertes


def profile_title(ctx, tr):
    """Le profil machine en une ligne : son nom et d'où il vient, ou
    « guidé » sans machine.json."""
    nom = profile_name(ctx) or "?"
    if ctx.get("machine_found"):
        return tr("{name} (from the key)", name=nom)
    return tr("guided (profile « {name} »)", name=nom)


def with_nvme_format(doc, nvme_format):
    """Une copie de `doc` dont la confirmation porte seulement le choix du
    formatage NVMe : review() sur elle rend le plan, les commandes et la
    taille de secteur LUKS que le récapitulatif doit montrer quand la case
    est cochée."""
    copie = dict(doc)
    copie["confirm"] = {"nvme_format": nvme_format is True}
    return copie


def confirm_document(doc, typed, nvme_format=False, prep=None):
    """Une copie de `doc` portant la confirmation tapée. Avec `prep` (le
    plan que le récapitulatif a montré), la taille et le modèle du disque
    affiché l'accompagnent : le cœur, qui relit le matériel, refuse
    d'effacer si le même nom désigne alors un autre disque."""
    copie = dict(doc)
    copie["confirm"] = {
        "disk": str(typed or "").strip(),
        "nvme_format": nvme_format is True,
    }
    disque = (((prep or {}).get("settings") or {}).get("derived") or {}).get(
        "disk"
    )
    if disque:
        copie["confirm"]["disk_size"] = disque.get("size")
        copie["confirm"]["disk_model"] = disque.get("model")
    return copie


def disk_confirmed(prep, typed):
    """Vrai si `typed` nomme le disque que le plan efface."""
    disque = ((prep.get("settings") or {}).get("derived") or {}).get("disk")
    return core.disk_confirmed({"disk": typed}, disque)


def exit_message(tr, rc, dry_run=False):
    """La phrase d'un code de sortie du cœur ; un essai à blanc réussi
    ne se dit pas « installé »."""
    if dry_run and rc == 0:
        return tr("Dry run: the plan is complete, nothing was written.")
    phrase = EXIT_MESSAGES.get(rc)
    if phrase is None:
        return tr("The installer ended with code {rc}.", rc=rc)
    return tr(phrase)


# Le live (impur)


def apply_keymap(name, run=subprocess.run):
    """loadkeys `name` : la console prend la disposition tout de suite,
    et toute saisie qui suit (phrases LUKS comprises) se tape avec elle.
    Rend (ok, sortie d'erreur)."""
    try:
        res = run(
            ["loadkeys", name],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    return res.returncode == 0, (res.stderr or "").strip()


def _quiet(run, argv, timeout=10):
    try:
        return (
            run(
                argv,
                capture_output=True,
                check=False,
                timeout=timeout,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


def live_status(run=subprocess.run, host=NETWORK_PROBE_HOST):
    """{"pacman_init": bool, "network": bool} : le trousseau pacman est
    prêt, et `host` se résout (le réseau sert les miroirs)."""
    return {
        "pacman_init": _quiet(
            run, ["systemctl", "is-active", "--quiet", "pacman-init.service"]
        ),
        "network": _quiet(run, ["getent", "hosts", host]),
    }


def wait_ready(
    log,
    tr,
    run=subprocess.run,
    sleep=time.sleep,
    boot_s=300,
    network_s=60,
    host=NETWORK_PROBE_HOST,
):
    """Attend pacman-init (au plus `boot_s` secondes) puis le réseau (au
    plus `network_s`). Rend vrai si le réseau répond ; pacman-init absent
    n'est qu'un avertissement, pacman le dira s'il échoue."""
    for i in range(boot_s):
        if live_status(run, host)["pacman_init"]:
            break
        if i == 0:
            log(tr("Waiting for the pacman keyring…"))
        sleep(1)
    else:
        log(tr("pacman-init is not active: pacman may fail."))
    for i in range(network_s):
        if live_status(run, host)["network"]:
            return True
        if i == 0:
            log(tr("Waiting for the network…"))
        sleep(1)
    return False


def strip_ansi(line):
    """`line` sans séquences d'échappement du terminal ni retour
    chariot : archinstall colore et réécrit ses lignes."""
    return ANSI_RE.sub("", line).replace("\r", "")


def core_argv(paths, answers_path, dry_run=False):
    argv = [paths.get("core", CORE_BIN), "--answers", answers_path]
    if dry_run:
        argv.append("--dry-run")
    return argv


def run_core(
    ctx,
    doc,
    on_line,
    popen=subprocess.Popen,
    dry_run=False,
    stdin=subprocess.DEVNULL,
):
    """Lance le cœur sur `doc` et rend son code de sortie ; chaque ligne
    de sa sortie passe à `on_line`, sans couleur.

    Le document, secrets compris, ne touche que le tmpfs de RUN_DIR : un
    fichier 0600, écrasé puis effacé dès que le cœur rend la main, quoi
    qu'il arrive.

    `stdin` décide du terminal que voit le cœur. /dev/null (défaut,
    l'écran Textual) : aucun, et l'étape ERPLibre n'écrit pas sur la
    console que l'écran occupe ; sa sortie reste dans STAGE_LOG_REL, que
    StageLogTail relit. None (mode texte) : la console héritée, où
    l'étape recopie sa sortie comme en 1b."""
    paths = ctx["paths"]
    os.makedirs(paths["run"], mode=0o700, exist_ok=True)
    chemin = os.path.join(paths["run"], ANSWERS_FILE)
    try:
        ai.write_private_json(chemin, doc)
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        try:
            proc = popen(
                core_argv(paths, chemin, dry_run),
                stdin=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                bufsize=1,
                env=env,
            )
        except OSError as exc:
            on_line(str(exc))
            return 127
        for ligne in proc.stdout:
            on_line(strip_ansi(ligne.rstrip("\n")))
        return proc.wait()
    finally:
        ai.shred(chemin)


class StageLogTail:
    """Les lignes ajoutées au journal de l'étape ERPLibre depuis le
    dernier appel. Le fichier n'existe qu'une fois la cible montée et
    l'étape lancée ; s'il rétrécit (nouvelle installation), la lecture
    reprend au début."""

    def __init__(self, path):
        self.path = path
        self.offset = 0
        self.rest = ""

    def poll(self):
        try:
            taille = os.path.getsize(self.path)
        except OSError:
            return []
        if taille < self.offset:
            self.offset, self.rest = 0, ""
        if taille == self.offset:
            return []
        with open(self.path, encoding="utf-8", errors="replace") as fh:
            fh.seek(self.offset)
            texte = self.rest + fh.read()
            self.offset = fh.tell()
        morceaux = texte.split("\n")
        self.rest = morceaux.pop()
        return [strip_ansi(m) for m in morceaux]


def stage_log_path(ctx):
    return os.path.join(ctx["paths"]["target"], STAGE_LOG_REL)


def archinstall_commands(ctx, key, tty=""):
    """Les deux commandes de l'archinstall guidé pré-rempli (la voie
    de l'étape 1b) : la configuration du profil ERPLibre `key`, puis
    archinstall qui demande disque, compte, langue et fuseau."""
    paths = ctx["paths"]
    config = paths.get("guided_config", GUIDED_CONFIG)
    return [
        [
            paths.get("config_bin", CONFIG_BIN),
            "--profile",
            key,
            "--output",
            config,
            "--tty",
            tty or "",
            "--lang",
            ctx.get("lang") or "fr",
        ],
        ["archinstall", "--config", config],
    ]
