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

from script.todo import devstack_report as report
from script.todo import host_os, qemu_privilege
from script.todo.todo_i18n import t


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
