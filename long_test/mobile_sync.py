#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La synchronisation de l'application mobile contre de vrais Odoo.

Le code de synchronisation de l'application (mobile/erplibre_home_mobile,
par son kit de test src/testing/syncTestKit.ts) tourne sous Vitest contre
Odoo 16, 17 et 18, démarrés pour l'occasion sur des bases jetables : les
scénarios de long_test/mobile_sync/*.test.ts créent, modifient, tirent et
fusionnent des tâches, opportunités, factures, activités et messages, et
vérifient le résultat dans Odoo.

Il vit dans long_test/ et non dans test/ : il installe des bases Odoo et
démarre des serveurs. Le premier passage construit un gabarit par version
(quelques minutes) ; les suivants le copient, en quelques secondes.

  ./long_test/mobile_sync.py                     # 16, 17 et 18
  ./long_test/mobile_sync.py --versions 18       # une seule version
  ./long_test/mobile_sync.py --filtre conflit    # les tests dont le nom correspond
  ./long_test/mobile_sync.py --dry-run           # le plan, rien de créé
  ./long_test/mobile_sync.py --garder            # garder bases et serveurs
  ./long_test/mobile_sync.py --rebuild           # reconstruire les gabarits
  ./long_test/mobile_sync.py --detruire          # supprimer gabarits et cache
  ./long_test/mobile_sync.py --appareil          # aussi sur le téléphone branché

Codes de sortie : 0 tout passe, 1 des tests échouent, 2 un prérequis
manque (le message dit lequel et quoi faire), 3 l'infrastructure (base,
serveur) a échoué.
"""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mobile_sync_device as appareil  # noqa: E402
import mobile_sync_odoo as odoo  # noqa: E402

SCENARIOS = Path(__file__).resolve().parent / "mobile_sync"

SORTIE_OK = 0
SORTIE_TESTS = 1
SORTIE_PREREQUIS = 2
SORTIE_INFRA = 3


def parser():
    parseur = argparse.ArgumentParser(
        description="La synchronisation mobile contre de vrais Odoo."
    )
    parseur.add_argument(
        "--versions", default=",".join(map(str, odoo.VERSIONS))
    )
    parseur.add_argument(
        "--filtre", default="", help="motif des noms de tests (vitest -t)"
    )
    parseur.add_argument("--dry-run", action="store_true")
    parseur.add_argument(
        "--garder", action="store_true", help="garder bases et serveurs"
    )
    parseur.add_argument("--garder-si-echec", action="store_true")
    parseur.add_argument(
        "--rebuild", action="store_true", help="reconstruire les gabarits"
    )
    parseur.add_argument(
        "--detruire", action="store_true", help="supprimer gabarits et cache"
    )
    parseur.add_argument(
        "--appareil",
        action="store_true",
        help="jouer aussi les scénarios de bout en bout sur le téléphone",
    )
    return parseur


def lire_rapport(chemin, versions):
    """Le bilan du rapport JSON de Vitest : (total, échecs, par version).
    Un test se range sous sa version par le nom de son bloc (« Odoo 17 »)."""
    rapport = json.loads(Path(chemin).read_text())
    par_version = {version: 0 for version in versions}
    for fichier in rapport.get("testResults", []):
        for test in fichier.get("assertionResults", []):
            for version in versions:
                if f"Odoo {version}" in (test.get("fullName") or ""):
                    par_version[version] += 1
    return (
        rapport.get("numTotalTests", 0),
        rapport.get("numFailedTests", 0)
        + rapport.get("numFailedTestSuites", 0),
        par_version,
    )


def verdict(total, echecs, par_version):
    """Le code de sortie d'un rapport, et pourquoi : un rapport sans test,
    ou une version sans test, est un échec, pas une réussite silencieuse."""
    if total == 0:
        return SORTIE_TESTS, "aucun test n'a tourné"
    vides = [str(v) for v, n in par_version.items() if n == 0]
    if vides:
        return SORTIE_TESTS, f"aucun test pour Odoo {', '.join(vides)}"
    if echecs:
        return SORTIE_TESTS, f"{echecs} échec(s) sur {total} tests"
    return SORTIE_OK, f"{total} tests, tous passés"


def plan(versions, args):
    lignes = [
        "Plan :",
        f"  dépôt mobile : {odoo.MOBILE}",
        f"  gabarits : {', '.join(f'{odoo.PREFIXE_GABARIT}{v}' for v in versions)}"
        + (
            " (reconstruits)"
            if args.rebuild
            else " (construits s'ils manquent ou changent)"
        ),
        f"  bases de course : {odoo.PREFIXE_COURSE}<pid>_<horodatage>_<version>",
        "  un serveur par version, ports libres, sans worker ni cron",
        f"  vitest run --dir {SCENARIOS}"
        + (f" -t {args.filtre}" if args.filtre else ""),
        "  bases et serveurs "
        + ("gardés" if args.garder else "supprimés à la fin"),
    ]
    if args.appareil:
        lignes.append(
            f"  téléphone : {appareil.PAQUET}, "
            f"{len(appareil.SCENARIOS)} scénarios par version"
        )
    return "\n".join(lignes)


def detruire(a_blanc=False):
    """Supprime les bases mobile_sync_* et le cache ; a_blanc : les liste
    seulement, ce que le menu montre avant de demander."""
    bases = sorted(odoo.bases_existantes())
    if a_blanc:
        for nom in bases:
            print(f"  à supprimer : {nom}")
        print(f"  à supprimer : {odoo.CACHE}")
        return
    for pid in odoo.arreter_gardes(set(bases)):
        print(f"  serveur gardé arrêté : {pid}")
    for nom in bases:
        odoo.supprimer_base(nom)
        print(f"  supprimée : {nom}")
    shutil.rmtree(odoo.CACHE, ignore_errors=True)
    print(f"  supprimé : {odoo.CACHE}")


def main(argv=None):
    # Ligne à ligne : la sortie de Vitest s'intercale avec celle-ci
    sys.stdout.reconfigure(line_buffering=True)
    args = parser().parse_args(argv)
    if args.detruire:
        detruire(a_blanc=args.dry_run)
        return SORTIE_OK
    try:
        versions = odoo.lire_versions(args.versions)
    except ValueError as erreur:
        print(f"--versions : {erreur}")
        return SORTIE_PREREQUIS

    problemes = odoo.verifier_mobile()
    if args.appareil:
        problemes += appareil.verifier_appareil()
    try:
        installees = odoo.versions_installees(demandees=versions)
    except odoo.PrerequisManquant as erreur:
        problemes.append(str(erreur))
    try:
        odoo.psql("SELECT 1")
    except (RuntimeError, OSError) as erreur:
        problemes.append(f"PostgreSQL injoignable : {erreur}")
    if problemes:
        print("Prérequis manquants :")
        for probleme in problemes:
            print(f"  - {probleme}")
        return SORTIE_PREREQUIS

    print(plan(versions, args))
    if args.dry_run:
        return SORTIE_OK

    balayees = odoo.a_balayer(odoo.bases_existantes())
    for pid in odoo.arreter_gardes(set(balayees)):
        print(f"Serveur gardé arrêté : {pid}")
    for nom in balayees:
        odoo.supprimer_base(nom)
        print(f"Balayé : {nom}")

    horodatage = time.strftime("%Y%m%d%H%M%S")
    repertoire = odoo.CACHE / "runs" / f"{os.getpid()}_{horodatage}"
    repertoire.mkdir(parents=True, exist_ok=True)
    serveurs = []
    bases = []
    code = SORTIE_INFRA

    def arreter(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, arreter)
    try:
        if args.rebuild:
            for version in versions:
                odoo.supprimer_base(installees[version].gabarit)
        with ThreadPoolExecutor(len(versions)) as groupe:
            list(
                groupe.map(
                    lambda v: odoo.construire_gabarit(installees[v]), versions
                )
            )
        for version in versions:
            base = odoo.nom_course(os.getpid(), horodatage, version)
            odoo.copier_gabarit(installees[version], base)
            bases.append(base)
        with ThreadPoolExecutor(len(versions)) as groupe:
            serveurs = list(
                groupe.map(
                    lambda paire: odoo.demarrer_serveur(
                        installees[paire[0]], paire[1], repertoire
                    ),
                    zip(versions, bases),
                )
            )
        liste = [
            {
                "version": s.version,
                "url": s.url,
                "database": s.base,
                "admin": {"login": "admin", "password": "admin"},
                "multi": {"login": "mc_user", "password": "mc_user"},
            }
            for s in serveurs
        ]
        cibles = repertoire / "targets.json"
        cibles.write_text(json.dumps(liste, indent=2))
        for s in serveurs:
            print(f"Odoo {s.version} : {s.url} ({s.base})")

        rapport = repertoire / "vitest.json"
        commande = [
            "npx",
            "vitest",
            "run",
            "--dir",
            str(SCENARIOS),
            "--testTimeout=60000",
            "--hookTimeout=180000",
            "--reporter=default",
            "--reporter=json",
            f"--outputFile.json={rapport}",
            # Les journaux de l'application, seulement pour un test en échec
            "--silent=passed-only",
        ]
        if args.filtre:
            commande += ["-t", args.filtre]
        environnement = dict(
            os.environ, TZ=odoo.FUSEAU, MOBILE_SYNC_TARGETS=str(cibles)
        )
        subprocess.run(
            commande, cwd=odoo.MOBILE, env=environnement, check=False
        )
        if not rapport.exists():
            print("Vitest n'a écrit aucun rapport.")
            code = SORTIE_TESTS
        else:
            code, raison = verdict(*lire_rapport(rapport, versions))
            print(f"Bilan : {raison}. Traces : {repertoire}")
        if args.appareil:
            print("Sur le téléphone :")
            total, echecs = appareil.lancer(liste, repertoire)
            print(f"Appareil : {total - echecs}/{total} scénarios passés")
            if echecs or total == 0:
                code = SORTIE_TESTS
        return code
    except KeyboardInterrupt:
        print("Interrompu.")
        code = SORTIE_INFRA
        return code
    except RuntimeError as erreur:
        print(f"Infrastructure : {erreur}")
        return SORTIE_INFRA
    finally:
        garder = args.garder or (args.garder_si_echec and code != SORTIE_OK)
        if garder:
            odoo.noter_gardes(repertoire, serveurs)
            print("Bases et serveurs gardés :")
            for s in serveurs:
                print(
                    f"  Odoo {s.version} : {s.url}  base {s.base}  admin/admin, mc_user/mc_user"
                )
            print(
                "  arrêtés et balayés par la prochaine course, ou par --detruire"
            )
        else:
            for s in serveurs:
                odoo.arreter_serveur(s)
            for base in bases:
                odoo.supprimer_base(base)


if __name__ == "__main__":
    sys.exit(main())
