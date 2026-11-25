# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Moteur d'étapes d'un installateur : exécution, secrets, registre.

Un installateur est une suite d'étapes (libellé, fonction(ctx, runner)).
run_steps les joue dans l'ordre et s'arrête à la première qui lève
StepError ; rien n'est défait, et chaque étape constate avant d'agir, si
bien qu'une relance reprend là où la précédente s'est arrêtée.

Runner est le seul point qui exécute. En essai à blanc, il affiche ce qu'il
aurait lancé et rend (0, "") ; les sondes en lecture tournent quand même,
sauf celles qui demandent sudo. Un contenu à écrire sous sudo passe par
stdin, jamais par argv : /proc/<pid>/cmdline est lisible par tout compte.
"""

import json
import os
import secrets
import shlex
import string
import subprocess

# Alphabet des secrets générés : lettres et chiffres seulement. Ni « \\ » ni
# « " », qu'un fichier de configuration PHP ou un installateur réécrit, ni
# rien qu'un shell ou du SQL interprète.
_SECRET_ALPHABET = string.ascii_letters + string.digits


def t(key):
    """Traduction si l'outillage TODO est là ; la clé sinon."""
    try:
        from script.todo.todo_i18n import t as _t
    except Exception:
        return key
    return _t(key)


class StepError(Exception):
    """Une étape a échoué ; `detail` porte la sortie utile, déjà filtrée.

    `resumable` faux : un refus avant toute écriture, que relancer ne
    reprendrait pas (instance existante, système non pris en charge).
    """

    def __init__(self, message, detail="", resumable=True):
        super().__init__(message)
        self.detail = detail
        self.resumable = resumable


class Runner:
    """Seul point qui exécute. En essai à blanc, il affiche et rend (0, "").

    Les sondes en lecture (probe) tournent aussi à blanc tant qu'elles ne
    demandent pas sudo : elles rendent le plan fidèle sans rien changer.
    """

    def __init__(self, dry_run=False, out=print):
        self.dry_run = dry_run
        self.out = out

    def run(self, argv, input=None, cwd=None, env=None):
        shown = shlex.join(argv)
        if input is not None:
            shown += "  < stdin"
        if self.dry_run:
            self.out(f"      [dry-run] $ {shown}")
            return 0, ""
        return self._exec(argv, input, cwd, env)

    def probe(self, argv, cwd=None):
        """Commande en lecture seule. None si à blanc et qu'elle veut sudo."""
        if self.dry_run and argv and argv[0] == "sudo":
            return None
        return self._exec(argv, None, cwd, None)

    def write(
        self, path, text, mode=0o600, sudo=False, owner=None, group=None
    ):
        """Écrit `text` dans `path` ; le contenu passe par stdin sous sudo.

        Sous sudo, `owner` et `group` fixent le propriétaire du fichier.
        """
        if self.dry_run:
            self.out(f"      [dry-run] write {path} ({oct(mode)})")
            return
        if sudo:
            argv = ["sudo", "install", "-m", f"{mode:o}"]
            if owner:
                argv += ["-o", owner]
            if group:
                argv += ["-g", group]
            code, out = self._exec(
                argv + ["/dev/stdin", path],
                text,
                None,
                None,
            )
            if code:
                raise StepError(t("Cannot write %s") % path, out)
            return
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(path, mode)

    def _exec(self, argv, input, cwd, env):
        full_env = None
        if env:
            full_env = dict(os.environ, **env)
        try:
            r = subprocess.run(
                argv,
                input=input,
                cwd=cwd,
                env=full_env,
                capture_output=True,
                text=True,
            )
        except OSError as e:
            return 127, str(e)
        return r.returncode, (r.stdout or "") + (r.stderr or "")


def tail(text, lines=20):
    """Les `lines` dernières lignes de `text`, blancs de bord retirés."""
    return "\n".join((text or "").strip().splitlines()[-lines:])


def run_or_fail(runner, argv, message, **kw):
    """Lance `argv` par `runner` ; rend sa sortie, ou lève StepError.

    `message` est l'erreur levée sur un code non nul, avec la fin de la
    sortie pour détail. `kw` passe tel quel à runner.run (input, cwd, env).
    """
    code, out = runner.run(argv, **kw)
    if code:
        raise StepError(message, tail(out))
    return out


def sudo_read(runner, path):
    """Le contenu de `path` lu sous sudo, ou None s'il ne se lit pas.

    None aussi en essai à blanc : la sonde demande sudo et ne tourne pas.
    """
    res = runner.probe(["sudo", "cat", path])
    return res[1] if res and res[0] == 0 else None


def sudo_exists(runner, path):
    """Vrai si `path` existe, vu sous sudo ; faux en essai à blanc."""
    res = runner.probe(["sudo", "test", "-e", path])
    return bool(res) and res[0] == 0


def generate_secret(length=32):
    """Secret aléatoire de `length` caractères pris dans _SECRET_ALPHABET."""
    return "".join(secrets.choice(_SECRET_ALPHABET) for _ in range(length))


def state_dir(erp, instance):
    """~/.local/share/ERPLibre/<erp>/<instance>, XDG_DATA_HOME respecté."""
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share"
    )
    return os.path.join(base, "ERPLibre", erp, instance)


def parse_secrets(text):
    """{NOM: valeur} du texte d'un fichier secrets.env."""
    out = {}
    for line in (text or "").splitlines():
        if "=" in line and not line.startswith("#"):
            name, value = line.split("=", 1)
            out[name.strip()] = value
    return out


def read_secrets(path):
    """{NOM: valeur} d'un fichier secrets.env, {} s'il n'existe pas."""
    try:
        with open(path, encoding="utf-8") as f:
            return parse_secrets(f.read())
    except FileNotFoundError:
        return {}


def record_entry(runner, registry, load, instance, entry):
    """Inscrit `entry` sous `instance` dans le registre json `registry`.

    `load()` rend les instances déjà inscrites, {nom: fiche} ; ce qu'il
    lève remonte tel quel, à l'appelant de le dire dans les termes de son
    ERP. Le dossier du registre est créé en 0700 et le fichier écrit en
    0600 par runner.write. En essai à blanc, rien n'est lu ni écrit.
    """
    if runner.dry_run:
        runner.out(f"      [dry-run] record {instance} in {registry}")
        return t("ok")
    data = {"instances": load()}
    data["instances"][instance] = entry
    os.makedirs(os.path.dirname(registry), mode=0o700, exist_ok=True)
    runner.write(registry, json.dumps(data, indent=4, sort_keys=True) + "\n")
    return t("ok")


def run_steps(ctx, runner, steps):
    """Joue les étapes ; rend 0, ou 1 à la première qui échoue.

    `steps` est une suite de (libellé, fonction(ctx, runner)) ; chaque
    fonction rend le texte affiché après son libellé, ou lève StepError.
    """
    total = len(steps)
    for i, (label, step) in enumerate(steps, start=1):
        try:
            result = step(ctx, runner)
        except StepError as e:
            runner.out(f"[{i}/{total}] {t(label)}: {t('FAILED')} — {e}")
            if e.detail:
                runner.out(e.detail)
            runner.out(t("Step failed, stopping here."))
            if e.resumable:
                runner.out(
                    t(
                        "Nothing was undone: running again resumes at this step."
                    )
                )
            return 1
        runner.out(f"[{i}/{total}] {t(label)}: {result}")
    return 0
