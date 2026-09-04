#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Monter, démonter et diagnostiquer un tunnel VPN.

    ./script/vpn/vpn.py list
    ./script/vpn/vpn.py up      --profile client-acme [--dry-run]
    ./script/vpn/vpn.py down    --profile client-acme
    ./script/vpn/vpn.py status  --profile client-acme
    ./script/vpn/vpn.py diagnose --profile client-acme
    ./script/vpn/vpn.py check   [--driver l2tp_ipsec]

Les profils (hôte, utilisateur, routes) viennent de la configuration ; les
secrets (PSK, mot de passe) du coffre KeePassXC. Voir `profiles.py` et
`vault.py`.

À lancer en tant qu'UTILISATEUR, pas sous sudo : le coffre est dans le home
de l'utilisateur et son mot de passe maître est saisi par lui. Chaque étape
privilégiée appelle `sudo` séparément, et `--dry-run` les montre toutes sans
en exécuter aucune.
"""
from __future__ import annotations

import argparse
import os
import sys

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if new_path not in sys.path:
    sys.path.append(new_path)

from script.config import config_file
from script.todo.kdbx_manager import KdbxManager
from script.vpn import profiles
from script.vpn.drivers import DRIVERS, driver_names, get_driver
from script.vpn.drivers.base import INSTALL_SCRIPT
from script.vpn.runner import Runner
from script.vpn.vault import (
    PLACEHOLDER,
    VaultError,
    VpnVault,
    redact,
    secrets_from_env,
)


def _vault():
    cfg = config_file.ConfigFile()
    return VpnVault(cfg, KdbxManager(cfg)), cfg


def _load_secrets(profile, driver_cls, required=True):
    """Secrets du profil, ou {} si on renonce.

    `required=False` sert le mode à blanc : montrer le plan ne justifie pas
    d'exiger le mot de passe maître, et un plan avec des marqueurs à la
    place des secrets reste un plan juste.
    """
    fields = tuple(key for key, _, _ in driver_cls.secret_fields)
    # Déjà fournis par le menu, qui tient le coffre ouvert ? Alors ne pas
    # redemander le mot de passe maître.
    deja = secrets_from_env(fields)
    if deja is not None:
        return deja
    vault, _ = _vault()
    title = profiles.secret_title(profile["name"])
    try:
        values = vault.read(title, fields=fields)
    except VaultError as err:
        if required:
            raise
        print(f"  ! {err}")
        print(f"  ! plan rendu avec « {PLACEHOLDER} » à la place des secrets")
        return {field: PLACEHOLDER for field in fields}
    if vault.master_password_is_stored():
        print(
            "  ! le mot de passe MAÎTRE du coffre est écrit dans la"
            " configuration : le retirer et le saisir à la demande"
        )
    return values


def _build(args, want_secrets=True, secrets_required=True):
    """(profil, pilote, exécuteur) ou (None, None, None) après un message."""
    profile = profiles.load(args.profile)
    if profile is None:
        known = ", ".join(profiles.names()) or "aucun"
        print(f"✗ Profil « {args.profile} » inconnu. Connus : {known}.")
        return None, None, None
    driver_cls = get_driver(profile["driver"])
    if driver_cls is None:
        print(
            f"✗ Le profil « {args.profile} » demande le pilote"
            f" « {profile['driver']} », qui n'existe pas."
            f" Connus : {', '.join(driver_names())}."
        )
        return None, None, None
    secrets = {}
    # Le PROFIL décide, pas seulement la technologie : ouvrir le coffre
    # pour un secret que ce montage n'utilisera pas réclamerait le mot de
    # passe maître pour rien.
    if want_secrets and driver_cls.wants_secrets(profile):
        try:
            secrets = _load_secrets(
                profile, driver_cls, required=secrets_required
            )
        except VaultError as err:
            print(f"✗ {err}")
            return None, None, None
    driver = driver_cls(profile, secrets)
    values = driver.secret_values()
    runner = Runner(
        dry_run=getattr(args, "dry_run", False),
        redactor=lambda text: redact(text, values),
    )
    return profile, driver, runner


def _prime_sudo(runner):
    """Demande le mot de passe sudo UNE fois, au début.

    Sans cela, l'invite surgit au milieu de la séquence — entre le « ipsec
    up » et le « c <lac> » — là où une saisie lente fait expirer le tunnel.
    """
    if runner.dry_run:
        return
    runner.cmd("autoriser sudo", "-v", sudo=True, check=False)


# ----------------------------------------------------------------------
# Commandes
# ----------------------------------------------------------------------
def cmd_list(args):
    all_profiles = profiles.load_all()
    if not all_profiles:
        print(
            "Aucun profil VPN. En créer un depuis TODO › Execute ›"
            " Déploiement › VPN › « Ajouter / modifier un profil »."
        )
        return 0
    for raw in all_profiles:
        profile = profiles.with_defaults(raw)
        mode = (
            "tout le trafic"
            if profile["default_route"]
            else ", ".join(profile["routes"]) or "aucune route"
        )
        print(
            f"  {profile['name']:<20} {profile['driver']:<12}"
            f" {profile['server']:<28} {mode}"
        )
    return 0


def cmd_up(args):
    profile, driver, runner = _build(
        args, secrets_required=not getattr(args, "dry_run", False)
    )
    if driver is None:
        return 1
    title = "Plan de montage (à blanc)" if runner.dry_run else "Montage"
    print(f"\n{title} — {profile['name']} ({driver.label})\n")
    _prime_sudo(runner)
    ok = driver.up(runner)
    print()
    if ok and not runner.failures:
        print(
            "✓ Tunnel monté."
            if not runner.dry_run
            else "✓ Plan complet, rien n'a été exécuté."
        )
        return 0
    print("✗ Montage incomplet :")
    for failure in runner.failures:
        print(f"    · {failure}")
    print(
        "  Démonter proprement avant de réessayer :"
        f" ./script/vpn/vpn.py down --profile {profile['name']}"
    )
    return 1


def cmd_down(args):
    profile, driver, runner = _build(args, want_secrets=False)
    if driver is None:
        return 1
    print(f"\nDémontage — {profile['name']}\n")
    _prime_sudo(runner)
    driver.down(runner)
    return 0


def cmd_status(args):
    if not args.profile:
        return cmd_list(args)
    profile, driver, runner = _build(args, want_secrets=False)
    if driver is None:
        return 1
    runner.quiet = True
    print(f"\nÉtat — {profile['name']} ({driver.label})\n")
    verdicts = driver.status(runner)
    _print_verdicts(verdicts)
    return 0 if all(ok for _, ok, _ in verdicts if ok is not None) else 1


def cmd_diagnose(args):
    profile, driver, runner = _build(args, want_secrets=False)
    if driver is None:
        return 1
    runner.quiet = True
    print(f"\nDiagnostic — {profile['name']} ({driver.label})\n")
    verdicts = driver.status(runner)
    _print_verdicts(verdicts)
    print()
    # Avant les journaux : quand le noyau est la cause, ils sont vides —
    # le démon n'a pas vécu assez longtemps pour écrire — et faire lire
    # soixante lignes de rien avant d'annoncer le remède n'aide personne.
    if driver.needs_reboot():
        runner.quiet = False
        driver.propose_reboot(runner)
        runner.quiet = True
        print()
    for label, command in driver.log_commands():
        print(f"── {label} ──")
        runner.quiet = False
        runner.cmd(label, command, check=False)
        runner.quiet = True
        print()
    failed = [label for label, ok, _ in verdicts if ok is False]
    if failed:
        print(f"✗ En défaut : {', '.join(failed)}")
        return 1
    print("✓ Tous les étages répondent.")
    return 0


def cmd_check(args):
    """Ce que la machine sait faire, avant tout profil."""
    names = [args.driver] if args.driver else driver_names()
    code = 0
    for name in names:
        driver_cls = get_driver(name)
        if driver_cls is None:
            print(f"✗ Pilote inconnu : {name}")
            code = 1
            continue
        driver = driver_cls({"name": "check"})
        missing = driver.missing_binaries()
        broken = [d for _, ok, d in driver.check_kernel() if ok is False]
        if missing:
            code = 1
            _line("✗", driver_cls.label, f"absents : {', '.join(missing)}")
            print(f"      {INSTALL_SCRIPT} {name}")
        elif broken:
            # Les paquets sont là et le noyau ne suit pas : « prêt » serait
            # faux, et l'installateur n'y changerait rien.
            code = 1
            _line("✗", driver_cls.label, "; ".join(broken))
        else:
            _line("✓", driver_cls.label, "prêt")
    vault, _ = _vault()
    path = vault.vault_path()
    if not path:
        _line("!", "coffre KeePassXC", "non configuré")
    else:
        exists = os.path.exists(os.path.expanduser(path))
        _line("✓" if exists else "✗", "coffre KeePassXC", path)
        if not exists:
            code = 1
    if vault.master_password_is_stored():
        _line(
            "!",
            "mot de passe maître",
            "stocké en clair dans la configuration : le retirer",
        )
    return code


def cmd_install(args):
    """Une SEULE invocation, même pour plusieurs pilotes : le script fait
    un `apt-get update` par appel, et cinq appels le referaient cinq
    fois."""
    names = [args.driver] if args.driver else driver_names()
    runner = Runner()
    # `--sso` en QUEUE : le script retire ce drapeau avant de traiter le
    # reste comme une liste de pilotes.
    extra = " --sso" if getattr(args, "with_sso", False) else ""
    code, _ = runner.cmd(
        f"installer les paquets de : {', '.join(names)}",
        f"bash {INSTALL_SCRIPT} {' '.join(names)}{extra}",
        check=True,
    )
    return code


def _line(mark, label, detail):
    """Une ligne de verdict, en colonnes. Un seul endroit décide de la
    largeur : sinon les listes de `check` et de `status` cessent de
    s'aligner entre elles."""
    print(f"  {mark} {label:<34} {detail}")


def _print_verdicts(verdicts):
    for label, ok, detail in verdicts:
        _line("✓" if ok else ("?" if ok is None else "✗"), label, detail)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="vpn.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="Lister les profils")

    for name, help_text, with_dry in (
        ("up", "Monter le tunnel", True),
        ("down", "Démonter le tunnel", True),
        ("status", "État du tunnel", False),
        ("diagnose", "État détaillé + journaux", False),
    ):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument(
            "--profile",
            required=name not in ("status",),
            help="Nom du profil VPN",
        )
        if with_dry:
            sp.add_argument(
                "--dry-run",
                action="store_true",
                help="Montrer le plan, secrets masqués, sans rien exécuter",
            )

    for name, help_text in (
        ("check", "Vérifier ce que la machine sait faire"),
        ("install", "Installer les paquets client"),
    ):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument(
            "--driver",
            choices=sorted(DRIVERS),
            help="Se limiter à ce pilote",
        )
        if name == "install":
            sp.add_argument(
                "--with-sso",
                action="store_true",
                help=(
                    "Installer aussi le greffon d'authentification par"
                    " formulaire web (openconnect-sso)"
                ),
            )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    handlers = {
        "list": cmd_list,
        "up": cmd_up,
        "down": cmd_down,
        "status": cmd_status,
        "diagnose": cmd_diagnose,
        "check": cmd_check,
        "install": cmd_install,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
