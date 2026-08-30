#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Réveiller l'instance dès qu'elle écoute, puis disparaître.

Odoo ne charge le registre d'une base qu'à la PREMIÈRE requête qui la
concerne. Sur une base migrée, ce premier chargement prend des dizaines de
secondes — et c'est la personne qui ouvre la page qui les attend. Lancée
en parallèle de `run.sh`, cette sonde prend ce temps à sa place.

Trois règles, et elles tiennent au fait qu'elle tourne À CÔTÉ du serveur
--------------------------------------------------------------------
1. Elle se TAIT. Une seule ligne, au démarrage, pour dire quelle adresse
   elle a choisie — c'est ce qui permet de comprendre après coup un
   réveil qui n'a pas eu lieu. Ensuite plus rien : ni échec, ni trace.
   Un serveur qu'on arrête au bout de dix secondes est un cas ordinaire,
   pas une erreur, et un message d'erreur dans le journal de `run.sh`
   ferait chercher une panne qui n'existe pas.
2. Elle s'arrête à la PREMIÈRE réponse, quelle qu'elle soit. Un 303 vers
   /web/login, un 404, un 500 : tous prouvent que le registre est chargé,
   ce qui est l'objet. Seul le refus de connexion ne compte pas.
3. Elle meurt au bout de deux minutes. Le réveil est un confort ; une
   sonde qui survit à son serveur en est un autre, mauvais.

Où elle trouve le port
----------------------
D'abord la ligne de commande — `-p 8090` l'emporte sur tout le reste,
c'est ce que la personne vient de taper. Puis `config.conf`, que `run.sh`
a déjà résolu et qu'elle reçoit tel quel. Le journal d'exécution ne sert
qu'en dernier recours : Odoo y écrit « HTTP service (werkzeug) running on
127.0.0.1:8069 » une fois qu'il écoute, ce qui arrive parfois APRÈS le
premier essai — mais c'est aussi la seule source exacte quand le port
demandé était déjà pris.
"""

from __future__ import annotations

import os
import re
import sys
import time

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from script.analyse import lib_analyse  # noqa: E402

DELAI_TOTAL = 120.0
DELAI_ENTRE_ESSAIS = 1.0
DELAI_REQUETE = 10.0
PORT_PAR_DEFAUT = 8069
HOTE_PAR_DEFAUT = "127.0.0.1"

# « HTTP service (werkzeug) running on 127.0.0.1:8069 »
MOTIF_JOURNAL = re.compile(
    r"HTTP service \(werkzeug\) running on ([^:\s]+):(\d+)"
)


def port_de_la_ligne(argv):
    """Le port demandé sur la ligne de commande, ou None.

    `-p 8090`, `--http-port 8090` et `--http-port=8090` : les trois
    formes existent, et Odoo les accepte toutes.
    """
    for index, argument in enumerate(argv):
        if argument in ("-p", "--http-port") and index + 1 < len(argv):
            valeur = argv[index + 1]
            if valeur.isdigit():
                return int(valeur)
        if argument.startswith("--http-port="):
            valeur = argument.split("=", 1)[1]
            if valeur.isdigit():
                return int(valeur)
    return None


def adresse_du_journal(chemin, taille=8192):
    """(hôte, port) lus dans la fin du journal, ou (None, None).

    On ne lit que la queue : un journal de migration pèse des mégaoctets,
    et la ligne qu'on cherche est la dernière écrite.
    """
    if not chemin or not os.path.isfile(chemin):
        return None, None
    try:
        with open(chemin, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            debut = max(0, handle.tell() - taille)
            handle.seek(debut)
            queue = handle.read().decode("utf-8", "replace")
    except OSError:
        return None, None
    trouve = MOTIF_JOURNAL.findall(queue)
    if not trouve:
        return None, None
    hote, port = trouve[-1]
    return hote, int(port)


def adresse(argv=(), config_path=None, journal=None):
    """(hôte, port) à réveiller, dans l'ordre de ce qui fait autorité."""
    config = lib_analyse.read_config(config_path)

    port = port_de_la_ligne(argv)
    hote = None
    if port is None:
        hote, port = adresse_du_journal(journal)
    if port is None:
        brut = str(config.get("http_port", "")).strip()
        port = int(brut) if brut.isdigit() else PORT_PAR_DEFAUT

    if not hote:
        interface = str(config.get("http_interface", "")).strip()
        # Une interface vide veut dire « toutes » : on se parle à soi-même.
        # 0.0.0.0 n'est pas une adresse de destination.
        if interface.lower() in ("", "false", "none", "0.0.0.0", "::"):
            hote = HOTE_PAR_DEFAUT
        else:
            hote = interface
    return hote, port


def base_a_reveiller(argv=(), config_path=None):
    """La base dont on veut le registre, ou None.

    `-d` d'abord : c'est celle que `run.sh` vient de choisir. Sinon
    `db_name` de la configuration, qu'Odoo utiliserait de toute façon.
    """
    for index, argument in enumerate(argv):
        if argument in ("-d", "--database") and index + 1 < len(argv):
            return argv[index + 1]
        if argument.startswith("--database="):
            return argument.split("=", 1)[1]
    valeur = str(
        lib_analyse.read_config(config_path).get("db_name", "")
    ).strip()
    return valeur if valeur.lower() not in ("", "false", "none") else None


def url(hote, port, database=None):
    """L'adresse à demander.

    `/web/login` plutôt que `/` : elle ne redirige pas vers un tableau de
    bord, ne crée pas de session, et suffit à faire charger le registre.
    Le paramètre `db` dit LAQUELLE quand plusieurs bases répondent.
    """
    base = f"http://{hote}:{port}/web/login"
    if database:
        from urllib.parse import quote

        return f"{base}?db={quote(database)}"
    return base


def sonder(
    cible,
    delai_total=DELAI_TOTAL,
    entre_essais=DELAI_ENTRE_ESSAIS,
    requete=DELAI_REQUETE,
    horloge=time.monotonic,
    dormir=time.sleep,
):
    """Demander jusqu'à obtenir une réponse. Rendre True si elle est venue.

    N'importe quel code HTTP est une réussite : 303, 404 ou 500 prouvent
    tous que le serveur a répondu, donc que le registre est chargé. Seul
    le refus de connexion fait recommencer.
    """
    import urllib.error
    import urllib.request

    fin = horloge() + delai_total
    while horloge() < fin:
        try:
            with urllib.request.urlopen(cible, timeout=requete):
                return True
        except urllib.error.HTTPError:
            # Le serveur a répondu, et c'est tout ce qu'on demandait.
            return True
        except Exception:  # noqa: BLE001 - un serveur pas encore prêt
            pass
        dormir(entre_essais)
    return False


def main(argv=None):
    """Toujours rendre 0 : personne ne doit lire ce code de retour.

    La sonde tourne en arrière-plan d'un `run.sh` qui, lui, rapporte
    l'état d'Odoo. Un code non nul finirait dans un journal et ferait
    croire à une panne du serveur.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Warm up the HTTP registry.")
    parser.add_argument("-c", "--config")
    parser.add_argument("-d", "--database")
    parser.add_argument("--log")
    parser.add_argument("--timeout", type=float, default=DELAI_TOTAL)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("odoo_args", nargs="*")
    # `parse_known_args` et non `parse_args` : les arguments d'Odoo nous
    # traversent, et l'un d'eux ressemblera un jour à une option qu'on ne
    # connaît pas. `parse_args` sortirait alors par SystemExit — ce qui
    # romprait la seule promesse qui compte ici : ne jamais gêner.
    args, restes = parser.parse_known_args(argv)
    args.odoo_args = list(args.odoo_args) + list(restes)

    try:
        hote, port = adresse(args.odoo_args, args.config, args.log)
        database = args.database or base_a_reveiller(
            args.odoo_args, args.config
        )
        cible = url(hote, port, database)
        if not args.quiet:
            print(f"🔥 warmup: {cible}", flush=True)
        sonder(cible, delai_total=args.timeout)
    except Exception:  # noqa: BLE001 - le réveil est un confort, pas un dû
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
