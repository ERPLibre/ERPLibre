#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce qu'un déploiement peut affirmer, COUCHE PAR COUCHE.

Un code unique perd ce qui sert le plus. « le pare-feu de l'invité a tenu,
c'est le réseau qui a cédé » ne se déduit pas d'un entier, et les deux se
corrigent de deux côtés opposés.

Ce module COMPOSE, il ne sonde pas. Chaque fait vient d'un producteur qui
existe déjà et qui a sa propre épreuve ; ici on les traduit dans le
vocabulaire du rapport. Écrire une deuxième mesure à côté de la première
est exactement ce qui les fait diverger — et c'est le chemin recopié qui
dérive en silence.

Rien ici ne lance de sous-processus et rien ne s'affiche : les verdicts se
rendent, l'écran les écrit. C'est ce qui permet de les éprouver depuis une
station, sans hyperviseur et sans privilège.
"""

from __future__ import annotations

from script.posture import plan
from script.remote import host_probe
from script.todo import devstack_report as report
from script.todo import host_os, qemu_privilege
from script.todo.todo_i18n import t


def probe_layers(verdict) -> tuple:
    """Le verdict d'une sonde d'appliance, réparti sur ses couches.

    Un code unique perdrait ce qui sert le plus. « ssh passe, c'est le
    produit qui manque » et « rien ne répond » se corrigent de deux côtés
    opposés, et l'un des deux n'a rien à voir avec le réseau.

    Le privilège absent est une ABSENCE et non une panne : deux verbes sur
    onze en ont besoin, et refuser la machine pour eux fermerait les neuf
    autres, qui marchent.

    Ici et non dans un écran : la traduction ne dépend d'aucune conversation,
    et deux écrans qui la recopieraient divergeraient au premier verdict
    ajouté.
    """
    if verdict.kind == host_probe.HOSTKEY:
        return (
            report.layer_verdict(
                "transport",
                report.DS_REFUSED,
                t("Host key not known yet."),
                t("Record it, then check again."),
            ),
        )
    if verdict.kind == host_probe.UNREACHABLE:
        return (
            report.layer_verdict(
                "transport",
                report.DS_ERR,
                verdict.detail or t("No answer."),
                t("Check the address and the SSH access."),
            ),
        )
    passe = report.layer_verdict(
        "transport", report.DS_OK, t("SSH gets through.")
    )
    if verdict.kind == host_probe.PRODUCT_ABSENT:
        return (
            passe,
            report.layer_verdict(
                "service",
                report.DS_ERR,
                verdict.detail or t("ERPLibre is not at that path."),
                t("Push the files, then install."),
            ),
        )
    if verdict.kind not in (
        host_probe.OK,
        host_probe.NO_PRIVILEGE,
        host_probe.NEEDS_ROOT,
    ):
        # Le vocabulaire est clos : un septième verdict se dirait ici plutôt
        # que de tomber en silence dans la branche du succès.
        return (
            report.layer_verdict(
                "transport", report.DS_ERR, t("Unexpected verdict.")
            ),
        )
    service = report.layer_verdict(
        "service", report.DS_OK, f"ERPLibre {verdict.version}"
    )
    if verdict.kind == host_probe.OK:
        dit = t("Elevation available.") if verdict.sudo else t("Root account.")
        return (
            passe,
            service,
            report.layer_verdict("host", report.DS_OK, dit),
        )
    return (
        passe,
        service,
        report.layer_verdict(
            "host",
            report.DS_SKIP,
            t("No passwordless sudo."),
            t("Two verbs need it; the nine others do not."),
        ),
    )


def egress_layers(verdict) -> tuple:
    """Le verdict de la relecture des règles, réparti sur ses couches.

    Chacun se corrige d'un côté différent : une table absente se
    recharge, un analyseur absent se choisit avec l'image, un droit
    manquant s'accorde, et un silence est un problème de transport où
    le pare-feu n'a jamais été mesuré.

    UN DROIT MANQUANT COMPTE POUR UNE PANNE, et non pour un retrait
    propre : la machine a reçu une posture qui promet un confinement, et
    une vérification qui n'aboutit pas ne doit pas se lire comme un
    succès. Le retrait propre est réservé au silence, où rien n'a été
    sondé du tout.
    """
    if verdict == plan.LOADED:
        return (
            report.layer_verdict(
                "firewall", report.DS_OK, t("Egress rules loaded.")
            ),
        )
    if verdict == plan.TABLE_ABSENT:
        return (
            report.layer_verdict(
                "firewall",
                report.DS_ERR,
                t("Egress rules did not load."),
                t("Read cloud-init output in the guest."),
            ),
        )
    if verdict == plan.TOOL_ABSENT:
        return (
            report.layer_verdict(
                "guest",
                report.DS_ERR,
                t("The guest image has no nftables."),
                t("Pick an image that ships it: none is installed here."),
            ),
        )
    if verdict == plan.NO_PRIVILEGE:
        return (
            report.layer_verdict(
                "firewall",
                report.DS_ERR,
                t("Egress rules could not be read."),
                t("Reading the table needs root on the guest."),
            ),
        )
    return (
        report.layer_verdict(
            "transport",
            report.DS_SKIP,
            t("The guest answered nothing."),
            t("Check the guest is up, then check again."),
        ),
    )


def network_layers(active, autostart, cidr="", collision="") -> tuple:
    """Le réseau libvirt : joignable maintenant, et au prochain démarrage ?

    UNE COLLISION DOMINE TOUT LE RESTE. Un réseau qui recouvre ce que l'hôte
    route déjà prend l'adresse de la passerelle sur son pont, et la machine
    perd son réseau. Dans ce cas l'autostart ÉTEINT est le bon état, pas un
    second défaut : le signaler ferait corriger ce qui protège.

    L'AUTOSTART COMPTE MÊME QUAND TOUT MARCHE. Sans lui le réseau ne remonte
    pas au démarrage suivant, et les machines deviennent injoignables sans
    que rien n'ait changé entre-temps — la panne arrive détachée de sa
    cause, ce qui est le plus cher à diagnostiquer.

    Les faits arrivent en paramètres : les lire demande virsh et l'URI
    système, que ce module ne sonde pas.
    """
    if collision:
        return (
            report.layer_verdict(
                "network",
                report.DS_ERR,
                t("The libvirt network overlaps a route of this host:")
                + f" {collision}",
                t("Move its subnet, or stop the network."),
            ),
        )
    if not active:
        return (
            report.layer_verdict(
                "network",
                report.DS_ERR,
                t("The libvirt network is defined but not started."),
                t("Start it: nothing reaches the VMs without it."),
            ),
        )
    if not autostart:
        return (
            report.layer_verdict(
                "network",
                report.DS_ERR,
                t("It works, and it will not come back after a reboot."),
                t("Arm autostart, the subnet being free of collision."),
            ),
        )
    detail = t("Network up and armed for the next boot.")
    return (
        report.layer_verdict(
            "network", report.DS_OK, f"{detail} {cidr}".strip()
        ),
    )


def host_layers(groupe=None, kvm=None) -> tuple:
    """La station qui déploie : peut-elle piloter, et accélérer ?

    DEUX FAITS, DEUX GRAVITÉS. Sans le groupe, rien ne se déploie : le suivi
    d'installation tourne DÉTACHÉ, sans terminal, et ne peut répondre à
    aucune demande de mot de passe. Sans accélération, tout se déploie
    encore — simplement émulé, et sept fois plus lentement.

    D'où une PANNE pour le premier et un retrait PROPRE pour le second : le
    pire code d'une suite domine, et rendre une panne pour une lenteur
    ferait refuser un hôte qui marche.

    `groupe` et `kvm` se passent pour éprouver les cas qu'une station ne
    présente pas — être hors du groupe ne se simule pas en y étant.
    """
    declare, actif = (
        groupe if groupe is not None else qemu_privilege.group_state()
    )
    accelere = host_os.kvm_available() if kvm is None else kvm
    verdicts = []
    if actif:
        verdicts.append(
            report.layer_verdict(
                "host", report.DS_OK, t("libvirt group is active.")
            )
        )
    elif declare:
        # Les groupes d'un processus sont figés à l'ouverture de session :
        # être dans la base système ne suffit pas, et proposer un usermod
        # déjà fait envoie corriger ce qui l'est.
        verdicts.append(
            report.layer_verdict(
                "host",
                report.DS_ERR,
                t(
                    "You are in the libvirt group, but this session predates"
                    " it."
                ),
                t("Log out and back in, or run: newgrp libvirt"),
            )
        )
    else:
        verdicts.append(
            report.layer_verdict(
                "host",
                report.DS_ERR,
                t("virsh cannot reach qemu:///system without sudo."),
                t("Join the libvirt group, then open a new session."),
            )
        )
    if accelere:
        verdicts.append(
            report.layer_verdict(
                "host", report.DS_OK, t("Hardware acceleration is available.")
            )
        )
    else:
        verdicts.append(
            report.layer_verdict(
                "host",
                report.DS_SKIP,
                t("No hardware acceleration: VMs will be EMULATED."),
                t("Load the kvm module, or join the kvm group"),
            )
        )
    return tuple(verdicts)
