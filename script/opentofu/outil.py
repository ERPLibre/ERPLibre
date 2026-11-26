# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Trouver, vérifier et installer le binaire `tofu`.

`trouver_tofu` cherche dans le PATH puis dans `~/.local/bin`. Là où la
distribution fournit un paquet, `commande_paquet` rend la commande à lancer
(elle n'est jamais exécutée ici). Sinon `installer_zip` pose l'archive
publiée par l'éditeur dans un dossier utilisateur, sans sudo : la signature
GPG du fichier de sommes est vérifiée contre l'empreinte épinglée AVANT que
l'archive soit téléchargée, puis le sha256 de l'archive est comparé à la
somme signée. Aucun script d'installation distant n'est exécuté.
"""

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from script.opentofu import resolution
from script.opentofu.moteur import Resultat
from script.todo.qemu_privilege import install_cmd_for
from script.todo.todo_i18n import t

_BASE = "https://github.com/opentofu/opentofu/releases/download/v{version}/"
_ARCHS = {"x86_64": "amd64", "aarch64": "arm64"}
_RE_PLANCHER = re.compile(r"^\s*>=\s*(\d+(?:\.\d+){0,2})\s*$")
_RE_VERSION = re.compile(r"^(\d+(?:\.\d+){0,2})(-.+)?$")
_RE_FPR = re.compile(r"^fpr:(?:[^:]*:){8}([0-9A-Fa-f]+):", re.MULTILINE)


def trouver_tofu():
    """Chemin de `tofu` : celui du PATH, puis `~/.local/bin`, sinon None."""
    trouve = shutil.which("tofu")
    if trouve:
        return trouve
    local = Path.home() / ".local" / "bin" / "tofu"
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    return None


def version_tofu(binaire):
    """`terraform_version` de `<binaire> version -json`, "" au moindre échec."""
    try:
        res = subprocess.run(
            [binaire, "version", "-json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        version = json.loads(res.stdout)["terraform_version"]
    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
        KeyError,
        TypeError,
    ):
        return ""
    return version if isinstance(version, str) else ""


def _tuple(numeros):
    """Tuple d'entiers de `1.10[.2]`, complété à trois champs."""
    champs = [int(x) for x in numeros.split(".")]
    return tuple(champs + [0] * (3 - len(champs)))


def version_suffisante(version, plancher):
    """Vrai si `version` satisfait `plancher` de forme `">= X.Y[.Z]"`.

    La comparaison est numérique. Une préversion (`1.14.0-beta1`) précède sa
    version de base : elle ne satisfait donc pas un plancher égal à cette
    base. Une version ou un plancher illisible rend faux.
    """
    pl = _RE_PLANCHER.match(plancher or "")
    ve = _RE_VERSION.match((version or "").strip())
    if not pl or not ve:
        return False
    base, prerelease = _tuple(ve.group(1)), ve.group(2)
    voulu = _tuple(pl.group(1))
    if base == voulu:
        return not prerelease
    return base > voulu


def arch_tofu():
    """Architecture des assets amont pour cette machine, "" si inconnue."""
    return _ARCHS.get(platform.machine(), "")


def commande_paquet():
    """`(commande, paquet)` du gestionnaire de l'hôte, ou `(None, None)`.

    Seul pacman fournit un paquet ; les autres gestionnaires passent par
    `installer_zip`. La commande est à afficher ou à lancer par l'appelant.
    """
    return install_cmd_for({"pacman": "opentofu"})


def noms_assets(version, arch):
    """Noms des fichiers publiés pour `version` : zip, sommes, signature."""
    return {
        "zip": f"tofu_{version}_linux_{arch}.zip",
        "sommes": f"tofu_{version}_SHA256SUMS",
        "signature": f"tofu_{version}_SHA256SUMS.gpgsig",
    }


def _normaliser(empreinte):
    return "".join(str(empreinte).split()).upper()


def verifier_signature(sommes, signature, cle, empreinte, gpg="gpg"):
    """Vrai si `signature` (binaire, détachée) valide `sommes` par `empreinte`.

    La clé est importée dans un `GNUPGHOME` neuf (0700), jamais dans le
    trousseau de l'utilisateur. Elle doit porter l'empreinte attendue, et gpg
    doit rapporter `VALIDSIG <empreinte>` : une signature valide d'une autre
    clé ne passe pas.
    """
    voulue = _normaliser(empreinte)
    dossier = tempfile.mkdtemp(prefix="tofu_gpg_")
    try:
        os.chmod(dossier, 0o700)
        d = Path(dossier)
        (d / "cle.asc").write_bytes(cle)
        (d / "sommes").write_bytes(sommes)
        (d / "sommes.sig").write_bytes(signature)
        env = {**os.environ, "GNUPGHOME": dossier}

        def lancer(*args):
            return subprocess.run(
                [gpg, "--batch", *args],
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
            )

        if lancer("--import", str(d / "cle.asc")).returncode != 0:
            return False
        listing = lancer("--list-keys", "--with-colons")
        if listing.returncode != 0:
            return False
        if voulue not in {
            _normaliser(f) for f in _RE_FPR.findall(listing.stdout)
        }:
            return False
        verif = lancer(
            "--status-fd",
            "1",
            "--verify",
            str(d / "sommes.sig"),
            str(d / "sommes"),
        )
        if verif.returncode != 0:
            return False
        for ligne in verif.stdout.splitlines():
            champs = ligne.split()
            if (
                champs[:2] == ["[GNUPG:]", "VALIDSIG"]
                and len(champs) > 2
                and _normaliser(champs[2]) == voulue
            ):
                return True
        return False
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        shutil.rmtree(dossier, ignore_errors=True)


def _telecharger_http(url):
    with urllib.request.urlopen(url, timeout=60) as rep:
        return rep.read()


def installer_zip(conf, dest=None, telecharger=None, gpg="gpg"):
    """Installe `tofu` `conf["version"]` dans `dest` (`~/.local/bin`).

    Ordre : sommes, signature et clé téléchargées, signature vérifiée, PUIS
    l'archive téléchargée et son sha256 comparé à la somme signée ; seul le
    membre `tofu` est extrait. Le binaire posé doit annoncer la version
    épinglée. Au moindre écart le résultat est un refus, le dossier
    temporaire est retiré et `dest` ne reçoit rien.
    """
    dest = Path(dest) if dest else Path.home() / ".local" / "bin"
    telecharger = telecharger or _telecharger_http
    arch = arch_tofu()
    if not arch:
        return Resultat(
            False,
            t("Unsupported architecture for tofu: {arch}").format(
                arch=platform.machine()
            ),
            1,
        )
    version = conf["version"]
    noms = noms_assets(version, arch)
    base = _BASE.format(version=version)
    temp = tempfile.mkdtemp(prefix="tofu_install_")
    try:
        try:
            sommes = telecharger(base + noms["sommes"])
            signature = telecharger(base + noms["signature"])
            cle = telecharger(conf["cle_gpg_url"])
        except (OSError, ValueError) as exc:
            return Resultat(
                False, t("tofu download failed: {err}").format(err=exc), 1
            )
        if not verifier_signature(
            sommes, signature, cle, conf["gpg_fingerprint"], gpg
        ):
            return Resultat(
                False,
                t(
                    "GPG signature of {nom} is not valid for the pinned key."
                ).format(nom=noms["sommes"]),
                1,
            )
        try:
            contenu = telecharger(base + noms["zip"])
        except (OSError, ValueError) as exc:
            return Resultat(
                False, t("tofu download failed: {err}").format(err=exc), 1
            )
        attendue = resolution.charger_deploy_qemu().expected_sum(
            sommes.decode("utf-8", "replace"), noms["zip"]
        )
        if (
            not attendue
            or hashlib.sha256(contenu).hexdigest() != attendue.lower()
        ):
            return Resultat(
                False,
                t("Checksum of {nom} is missing or does not match.").format(
                    nom=noms["zip"]
                ),
                1,
            )
        archive = Path(temp) / noms["zip"]
        archive.write_bytes(contenu)
        try:
            with zipfile.ZipFile(archive) as z:
                z.extract("tofu", temp)
        except (OSError, KeyError, zipfile.BadZipFile) as exc:
            return Resultat(
                False,
                t("Archive does not hold a usable tofu: {err}").format(err=exc),
                1,
            )
        extrait = Path(temp) / "tofu"
        os.chmod(extrait, 0o755)
        dest.mkdir(parents=True, exist_ok=True)
        cible = dest / "tofu"
        shutil.move(str(extrait), str(cible))
        trouvee = version_tofu(str(cible))
        if trouvee != version:
            cible.unlink(missing_ok=True)
            return Resultat(
                False,
                t(
                    "Installed tofu reports {trouvee}, expected {attendue}."
                ).format(trouvee=trouvee or "?", attendue=version),
                1,
            )
        return Resultat(
            True,
            t("tofu {version} installed in {dest}.").format(
                version=version, dest=dest
            ),
        )
    except OSError as exc:
        return Resultat(
            False, t("Cannot install tofu: {err}").format(err=exc), 1
        )
    finally:
        shutil.rmtree(temp, ignore_errors=True)
