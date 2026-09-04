#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le sous-réseau d'un réseau libvirt, et sa remise en place sous les VM.

Un réseau libvirt sert un /24 : ses VM y prennent une adresse par DHCP et le
quittent par le .1, porté par son pont. Changer ce /24 sous des VM allumées
les laisse avec un bail qui ne mène plus nulle part — leur passerelle n'existe
plus, et leur tap n'est même plus sur un pont si le réseau a été abattu.

D'où l'ordre que ce script tient, et qui est tout ce qu'il fait :

  0. ARRÊTER les VM attachées au réseau — proprement, et en les attendant ;
  1. REDÉFINIR le réseau sur le préfixe voulu, puis le redémarrer ;
  2. REDÉMARRER les VM qu'il a arrêtées, elles seules.

Le préfixe par défaut est celui de libvirt (192.168.122) : c'est celui que la
documentation, les entrées ~/.ssh/config et les notes prises avant supposent.

Les fonctions qui savent lire libvirt vivent dans deploy_qemu.py, chargé ici
comme module ; ce fichier n'apporte que l'ordre des gestes.

    ./script/qemu/network_qemu.py --status
    ./script/qemu/network_qemu.py --recreate
    ./script/qemu/network_qemu.py --recreate --prefix 192.168.140
"""

from __future__ import annotations

import argparse
import importlib.util
import ipaddress
import os
import re
import shutil
import sys
import time
from pathlib import Path

# Le préfixe d'origine du « default » de libvirt. Le remettre est le cas
# courant : c'est de lui que partent les baux, les entrées SSH écrites à la
# main et les README.
PREFIXE_LIBVIRT = "192.168.122"

# Ce qu'on laisse à une VM pour s'éteindre d'elle-même. Un arrêt propre passe
# par l'invité : il démonte ses systèmes de fichiers, là où une coupure les
# laisse à rejouer au démarrage suivant.
DELAI_ARRET = 120


def deploy_qemu():
    """deploy_qemu.py chargé comme module, comme le fait le menu TODO.

    Chargé par CHEMIN et non par « import » : script/qemu n'est pas un paquet,
    et ce script doit rester lançable depuis n'importe quel répertoire.
    """
    path = Path(__file__).resolve().parent / "deploy_qemu.py"
    spec = importlib.util.spec_from_file_location("deploy_qemu", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DQ = deploy_qemu()


def domaines(use_sudo: bool) -> list[str]:
    """Tous les domaines définis sur l'hôte, allumés ou non."""
    return DQ.virsh_out(["list", "--all", "--name"], use_sudo).split()


def domaine_actif(nom: str, use_sudo: bool) -> bool:
    """La VM tourne-t-elle ? Lu en anglais, virsh traduisant « running »."""
    etat = DQ.virsh_out(["domstate", nom], use_sudo).strip()
    return etat.startswith("running") or etat.startswith("paused")


def domaines_du_reseau(reseau: str, use_sudo: bool) -> list[str]:
    """Les VM dont une interface nomme ce réseau.

    Lu dans la définition PERSISTANTE (« --inactive ») : la vue vivante d'une
    VM allumée décore l'interface de ce que libvirt lui a alloué, mais c'est
    la définition qui dit à quel réseau la VM revient en démarrant.
    """
    attaches = []
    motif = re.compile(rf"<source network='{re.escape(reseau)}'")
    for nom in domaines(use_sudo):
        if motif.search(
            DQ.virsh_out(["dumpxml", "--inactive", nom], use_sudo)
        ):
            attaches.append(nom)
    return attaches


def baux(reseau: str, use_sudo: bool) -> list[str]:
    """Les lignes de « net-dhcp-leases », en-tête compris, ou []."""
    out = DQ.virsh_out(["net-dhcp-leases", reseau], use_sudo)
    return [ligne for ligne in out.splitlines() if ligne.strip()]


def prefixe_de(cidr: str) -> str:
    """« 192.168.122.0/24 » -> « 192.168.122 ». '' si rien n'est lisible."""
    if not cidr:
        return ""
    return cidr.split("/")[0].rsplit(".", 1)[0]


def etat(reseau: str, use_sudo: bool) -> None:
    """Ce que sert le réseau, qui y vit, et ce que l'hôte route par ailleurs.

    Écrit AVANT toute modification, et lisible seul : c'est le rapport qu'on
    relit pour décider s'il y a quelque chose à recréer.
    """
    actif, autostart = DQ.network_state(reseau, use_sudo)
    cidr = DQ.network_cidr(reseau, use_sudo)
    pont = DQ.network_bridge(reseau, use_sudo)
    print(f"\n== Réseau libvirt « {reseau} » ==")
    print(f"  état      : {'actif' if actif else 'INACTIF'}")
    print(f"  autostart : {'oui' if autostart else 'non'}")
    print(f"  sous-réseau : {cidr or 'illisible'}")
    print(f"  pont      : {pont or 'inconnu'}")

    collision = DQ.network_collision(
        cidr, DQ.host_networks(exclure_ponts=[pont])
    )
    if collision:
        print(
            f"  ⚠ collision : l'hôte route déjà {collision} par une AUTRE"
            " interface. Le pont y prendrait l'adresse de la passerelle."
        )
    else:
        print("  collision : aucune")

    print("\n  Ce que l'hôte route (hors ce pont) :")
    for reseau_hote in sorted(
        {str(r) for r in DQ.host_networks(exclure_ponts=[pont])}
    ):
        print(f"    {reseau_hote}")

    attaches = domaines_du_reseau(reseau, use_sudo)
    print(f"\n  VM attachées à « {reseau} » : {len(attaches)}")
    for nom in attaches:
        vivante = "allumée" if domaine_actif(nom, use_sudo) else "éteinte"
        print(f"    {nom} ({vivante})")

    lignes = baux(reseau, use_sudo)
    if lignes:
        print("\n  Baux DHCP :")
        for ligne in lignes:
            print(f"    {ligne}")


def attendre_extinction(noms: list[str], delai: int, use_sudo: bool) -> list:
    """Attend que ces VM s'éteignent. Rend celles qui tournent encore.

    Une seule attente pour tout le monde, et non un délai par VM : elles
    s'éteignent en parallèle, les compter l'une après l'autre multiplierait
    l'attente par leur nombre.
    """
    fin = time.monotonic() + delai
    restantes = list(noms)
    while restantes and time.monotonic() < fin:
        restantes = [n for n in restantes if domaine_actif(n, use_sudo)]
        if not restantes:
            break
        time.sleep(2)
    return restantes


def arreter(noms: list[str], runner, delai: int, forcer: bool) -> list[str]:
    """Étape 0 : éteint les VM attachées. Rend celles qui n'ont pas obéi.

    L'arrêt est demandé à l'invité (« shutdown ») ; « destroy » coupe le
    courant, et ne part qu'à la demande explicite de l'appelant.
    """
    if not noms:
        print("  Aucune VM attachée à arrêter.")
        return []
    for nom in noms:
        runner.run(
            ["virsh", "-c", DQ.LIBVIRT_URI, "shutdown", nom],
            privileged=True,
            check=False,
        )
    if runner.dry_run:
        return []
    print(f"  Attente de l'extinction ({delai} s au plus)…")
    restantes = attendre_extinction(noms, delai, runner.use_sudo)
    if restantes and forcer:
        print(f"  Arrêt forcé : {', '.join(restantes)}")
        for nom in restantes:
            runner.run(
                ["virsh", "-c", DQ.LIBVIRT_URI, "destroy", nom],
                privileged=True,
                check=False,
            )
        restantes = attendre_extinction(restantes, 30, runner.use_sudo)
    return restantes


def redefinir(reseau: str, prefixe: str, runner) -> bool:
    """Étape 1 : pose le réseau sur `prefixe`, puis le démarre. Vrai si fait.

    La redéfinition garde le XML tel quel, son seul sous-réseau réécrit :
    l'UUID, le nom du pont et son adresse MAC restent, si bien que les
    domaines qui nomment ce réseau le retrouvent sans être redéfinis eux aussi.
    """
    xml = DQ.virsh_out(["net-dumpxml", reseau], runner.use_sudo)
    if not xml:
        print(f"  ⚠ réseau « {reseau} » illisible : rien n'est changé.")
        return False
    cidr = DQ.cidr_from_network_xml(xml)
    ancien = prefixe_de(cidr)
    if not ancien:
        print(
            f"  ⚠ sous-réseau de « {reseau} » illisible : rien n'est changé."
        )
        return False

    pont = DQ.bridge_from_network_xml(xml)
    vise = f"{prefixe}.0/24"
    # Le pont du réseau examiné est écarté : il porte le sous-réseau ACTUEL, et
    # le compter ferait passer un réseau démarré pour sa propre collision.
    collision = DQ.network_collision(
        vise, DQ.host_networks(exclure_ponts=[pont])
    )
    if collision:
        print(
            f"  ⚠ {vise} recouvre {collision}, que cette machine route déjà."
            "\n    Le pont y prendrait l'adresse de la passerelle de l'hôte,"
            " qui perdrait son accès au réseau. Rien n'est changé."
        )
        return False
    for autre in DQ.libvirt_networks_cidrs(reseau, runner.use_sudo):
        if autre.overlaps(ipaddress.ip_network(vise)):
            print(
                f"  ⚠ {vise} est déjà servi par un autre réseau libvirt"
                f" ({autre}). Rien n'est changé."
            )
            return False

    actif, _autostart = DQ.network_state(reseau, runner.use_sudo)
    if ancien == prefixe:
        print(f"  Le réseau sert déjà {vise} : aucune redéfinition.")
    else:
        print(f"  {cidr} → {vise}")
        if actif:
            runner.run(
                ["virsh", "-c", DQ.LIBVIRT_URI, "net-destroy", reseau],
                privileged=True,
                check=False,
            )
            actif = False
        DQ.define_network_xml(
            DQ.moved_network_xml(xml, ancien, prefixe), runner
        )
    if not actif:
        runner.run(
            ["virsh", "-c", DQ.LIBVIRT_URI, "net-start", reseau],
            privileged=True,
            check=False,
        )
    runner.run(
        ["virsh", "-c", DQ.LIBVIRT_URI, "net-autostart", reseau],
        privileged=True,
        check=False,
    )
    return True


def redemarrer(noms: list[str], runner) -> None:
    """Étape 2 : rallume les VM que l'étape 0 a éteintes, elles seules.

    Une VM déjà éteinte AVANT l'opération le reste : ce script recrée un
    sous-réseau, il ne décide pas de ce qui doit tourner sur l'hôte.
    """
    for nom in noms:
        runner.run(
            ["virsh", "-c", DQ.LIBVIRT_URI, "start", nom],
            privileged=True,
            check=False,
        )


def recreer(args, runner) -> int:
    """Les trois étapes, dans l'ordre. Rend le code de sortie du programme."""
    reseau, prefixe = args.network, args.prefix
    cidr = DQ.network_cidr(reseau, runner.use_sudo)
    attaches = domaines_du_reseau(reseau, runner.use_sudo)
    allumees = [n for n in attaches if domaine_actif(n, runner.use_sudo)]

    print(f"\n== Recréer le sous-réseau de « {reseau} » ==")
    print(f"  {cidr or 'sous-réseau illisible'} → {prefixe}.0/24")
    print(f"  VM attachées : {len(attaches)}, dont allumées : {len(allumees)}")
    for nom in allumees:
        print(f"    {nom}")
    print(
        "\n  Les VM allumées seront ARRÊTÉES, le réseau redéfini, puis"
        "\n  ces mêmes VM redémarrées. Une VM à adresse fixe dans l'ancien"
        "\n  sous-réseau devra être corrigée dans l'invité."
    )
    if not args.assume_yes and not args.dry_run:
        if not demander("\n  Continuer ? (o/N) : "):
            print("  Annulé.")
            return 1

    print("\n-- 0/2 Arrêt des VM attachées --")
    restantes = arreter(allumees, runner, args.timeout, args.force_off)
    if restantes:
        print(
            f"  ⚠ encore allumées : {', '.join(restantes)}."
            "\n    Le réseau n'est PAS redéfini : le faire sous une VM vivante"
            "\n    la laisserait sans passerelle et sans pont."
            "\n    Éteignez-les, ou relancez avec --force-off."
        )
        return 1

    print("\n-- 1/2 Redéfinition du réseau --")
    if not redefinir(reseau, prefixe, runner):
        print(
            "\n  Le réseau n'a pas été redéfini. Les VM arrêtées sont"
            " redémarrées telles quelles."
        )
        redemarrer(allumees, runner)
        return 1

    print("\n-- 2/2 Redémarrage des VM --")
    redemarrer(allumees, runner)

    if not runner.dry_run:
        print("\nTerminé. Le nouvel état :")
        etat(reseau, runner.use_sudo)
        print(
            "\n  Une VM absente des baux n'a pas encore renouvelé le sien :"
            "\n  laissez-lui le temps de démarrer, puis relancez --status."
        )
    return 0


def demander(question: str) -> bool:
    """Question fermée posée sur le terminal. Vaut NON par défaut.

    Lue sur /dev/tty quand il existe : le menu TODO branche l'entrée standard
    du script sur autre chose que le clavier, et une question sans réponse
    possible vaudrait acceptation silencieuse.
    """
    try:
        with open("/dev/tty", "r+") as tty:
            tty.write(question)
            tty.flush()
            reponse = tty.readline()
    except OSError:
        try:
            reponse = input(question)
        except EOFError:
            return False
    return reponse.strip().lower() in ("o", "oui", "y", "yes")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "État et remise en place du sous-réseau d'un réseau libvirt."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemples :\n"
            "  %(prog)s --status\n"
            "  %(prog)s --recreate\n"
            "  %(prog)s --recreate --prefix 192.168.140 --assume-yes\n"
        ),
    )
    p.add_argument(
        "--network",
        default="default",
        help="Réseau libvirt visé (défaut : default).",
    )
    p.add_argument(
        "--status",
        action="store_true",
        help="Affiche l'état du réseau, ses VM et ses baux, puis quitte.",
    )
    p.add_argument(
        "--recreate",
        action="store_true",
        help="Arrête les VM attachées, redéfinit le réseau sur --prefix, "
        "puis redémarre ces VM.",
    )
    p.add_argument(
        "--prefix",
        default=PREFIXE_LIBVIRT,
        help=f"Préfixe /24 visé (défaut : {PREFIXE_LIBVIRT}, celui de "
        "libvirt).",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=DELAI_ARRET,
        help=f"Secondes laissées aux VM pour s'éteindre (défaut : "
        f"{DELAI_ARRET}).",
    )
    p.add_argument(
        "--force-off",
        action="store_true",
        help="Coupe le courant des VM qui n'obéissent pas au shutdown.",
    )
    p.add_argument(
        "-y",
        "--assume-yes",
        action="store_true",
        help="Ne pose pas la question de confirmation.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche les commandes sans rien exécuter.",
    )
    p.add_argument(
        "--no-sudo",
        action="store_true",
        help="N'ajoute jamais sudo (utile dans le groupe libvirt).",
    )
    return p


def valider_prefixe(prefixe: str) -> str:
    """Refuse un préfixe qui n'est pas trois octets. Rend le préfixe."""
    if not re.fullmatch(r"\d{1,3}\.\d{1,3}\.\d{1,3}", prefixe):
        sys.exit(
            f"Préfixe {prefixe!r} invalide : il en faut trois octets, "
            "ex. 192.168.122."
        )
    try:
        ipaddress.ip_network(f"{prefixe}.0/24")
    except ValueError as err:
        sys.exit(f"Préfixe {prefixe!r} invalide : {err}")
    return prefixe


def main() -> None:
    # Sortie ligne par ligne même dans un tube (menu TODO) : sinon les étapes
    # restent bufferisées et l'opération paraît figée.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass

    args = build_parser().parse_args()
    if not shutil.which("virsh"):
        sys.exit(
            "virsh est absent : préparez l'hôte par\n"
            "  ./script/qemu/deploy_qemu.py --setup-host"
        )
    runner = DQ.Runner(
        use_sudo=not args.no_sudo and os.geteuid() != 0,
        dry_run=args.dry_run,
    )
    if runner.use_sudo:
        # Dit avant que sudo ne réclame le mot de passe : la première lecture
        # de l'état passe par lui, et un mot de passe tapé sans savoir ce
        # qu'il autorise est donné à l'aveugle.
        print(
            "🔑 sudo va demander votre mot de passe : cet hôte n'ouvre"
            " qemu:///system\n   qu'à root (appartenir au groupe libvirt"
            " l'éviterait)."
        )
    if args.recreate:
        valider_prefixe(args.prefix)
        sys.exit(recreer(args, runner))
    etat(args.network, runner.use_sudo)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # Un Ctrl-C au milieu d'une attente d'extinction n'est pas une panne :
        # la trace Python noierait l'état où l'opération s'est arrêtée.
        print("\nInterrompu.")
        sys.exit(130)
