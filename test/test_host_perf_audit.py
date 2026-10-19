#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""L'audit de performance d'un hôte : lecteurs de /proc et /sys, taux,
verdicts, réponse « SSD ? », disques des pools ZFS, invités, durée, boucle,
sorties texte, JSON et CSV, et les gardes du fichier unique Python 3.7.

Rien n'est mesuré sur la machine de test, hormis un essai de fumée d'une
seconde dans un processus enfant : chaque arborescence /proc, /sys,
/etc/pve et /dev est inventée sous un dossier temporaire passé en racine,
et les commandes (zpool, zfs, pveversion, smartctl) passent par un faux
système qui compte ses appels. La priorité du lanceur de tests n'est
jamais touchée.
"""

import ast
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize
import unittest
from unittest import mock

RACINE_DEPOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE_DEPOT)

from script.proxmox import host_perf_audit as hpa  # noqa: E402

FICHIER = os.path.join(RACINE_DEPOT, "script", "proxmox", "host_perf_audit.py")
GIB = 2**30


# ----------------------------------------------------------------------- #
# Arborescences inventées
# ----------------------------------------------------------------------- #
class Arbre:
    """Un faux système de fichiers sous un dossier temporaire."""

    def __init__(self, test):
        self.racine = tempfile.mkdtemp(prefix="test-hpa-")
        test.addCleanup(shutil.rmtree, self.racine, True)

    def chemin(self, rel):
        return os.path.join(self.racine, rel.lstrip("/"))

    def ecrire(self, rel, texte):
        p = self.chemin(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(texte)

    def dossier(self, rel):
        os.makedirs(self.chemin(rel), exist_ok=True)

    def lien(self, rel, cible):
        p = self.chemin(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        os.symlink(cible, p)

    def disque(self, nom, rotatif=None, modele="", physique=True):
        self.dossier("/sys/block/%s/queue" % nom)
        if physique:
            self.dossier("/sys/block/%s/device" % nom)
        if rotatif is not None:
            self.ecrire(
                "/sys/block/%s/queue/rotational" % nom,
                "1\n" if rotatif else "0\n",
            )
        if modele:
            self.ecrire("/sys/block/%s/device/model" % nom, modele + "\n")
        self.ecrire("/sys/block/%s/size" % nom, "7814037168\n")
        self.ecrire(
            "/sys/block/%s/queue/scheduler" % nom, "[mq-deadline] none\n"
        )

    def partition(self, disque, nom):
        self.ecrire("/sys/block/%s/%s/partition" % (disque, nom), "1\n")


def ligne_disque(nom, v, champs=14):
    """Une ligne de /proc/diskstats : `v` = 11 compteurs (champs 3 à 13),
    complétés à `champs` champs."""
    valeurs = list(v) + [0] * (champs - 3 - len(v))
    return "   8       0 %s %s\n" % (nom, " ".join(map(str, valeurs)))


def ecrire_compteurs(arbre, k):
    """Compteurs d'un hôte au k-ième instantané, croissant linéairement :
    entre deux instantanés espacés de 10 s, CPU 50 % occupé dont 10 %
    iowait, sda 80 % utilisé (20 ms en lecture, 40 ms en écriture),
    PSI io 20 %, invités à 50 % d'un cœur."""
    ticks = [1000 + 400 * k, 0, 500 + 100 * k, 8000 + 400 * k, 100 + 100 * k]
    arbre.ecrire(
        "/proc/stat",
        "cpu  %s 0 0 0\ncpu0 1 1 1 1 1 0 0 0\ncpu1 1 1 1 1 1 0 0 0\n"
        % " ".join(map(str, ticks)),
    )
    for genre in ("cpu", "memory"):
        arbre.ecrire(
            "/proc/pressure/%s" % genre,
            "some avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
            "full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n",
        )
    io_total = 2000000 * k
    arbre.ecrire(
        "/proc/pressure/io",
        "some avg10=1.00 avg60=1.00 avg300=1.00 total=%d\n"
        "full avg10=0.00 avg60=0.00 avg300=0.00 total=%d\n"
        % (io_total, io_total // 4),
    )
    sda = [
        100 + 100 * k,
        0,
        800 + 800 * k,
        2000 * k,
        100 * k,
        0,
        400 + 400 * k,
        4000 * k,
        0,
        8000 * k,
        9000 * k,
    ]
    nvme = [
        10 * k,
        0,
        80 * k,
        5 * k,
        10 * k,
        0,
        80 * k,
        5 * k,
        0,
        50 * k,
        60 * k,
    ]
    arbre.ecrire(
        "/proc/diskstats",
        ligne_disque("sda", sda)
        + "   8       1 sda1 1 0 1 1 1 0 1 1 0 1 1\n"
        + ligne_disque("nvme0n1", nvme, 20)
        + "   7       0 loop0 1 0 1 1 1 0 1 1 0 1 1 0 0 0\n",
    )
    arbre.ecrire(
        "/proc/meminfo",
        "MemTotal:       32768000 kB\nMemAvailable:   16000000 kB\n"
        "SwapTotal:      8000000 kB\nSwapFree:       7000000 kB\n",
    )
    arbre.ecrire("/proc/vmstat", "pswpin %d\npswpout %d\n" % (10 * k, 20 * k))
    arbre.ecrire(
        "/proc/net/dev",
        "Inter-|   Receive\n face |bytes packets errs drop fifo frame"
        " compressed multicast|bytes packets errs drop\n"
        "    lo: 10 1 0 0 0 0 0 0 10 1 0 0 0 0 0 0\n"
        "  eno1: %d 10 0 0 0 0 0 0 %d 20 0 0 0 0 0 0\n"
        "vmbr0: %d 10 0 0 0 0 0 0 %d 20 0 0 0 0 0 0\n"
        "tap120i0: %d 1 0 0 0 0 0 0 %d 1 0 0 0 0 0 0\n"
        % (
            10485760 * k,
            1048576 * k,
            10485760 * k,
            1048576 * k,
            102400 * k,
            102400 * k,
        ),
    )
    arbre.ecrire("/proc/loadavg", "0.50 0.40 0.30 1/200 12345\n")
    arbre.ecrire(
        "/proc/spl/kstat/zfs/arcstats",
        "13 1 0x01 1 2 3 4\nname type data\nhits 4 %d\nmisses 4 %d\n"
        "size 4 %d\nc_max 4 %d\nc_min 4 %d\n"
        % (9000 + 900 * k, 1000 + 100 * k, 8 * GIB, 16 * GIB, GIB),
    )
    for chemin_cg in ("lxc/101", "qemu.slice/120.scope"):
        base = "/sys/fs/cgroup/" + chemin_cg
        arbre.ecrire(base + "/cpu.stat", "usage_usec %d\n" % (5000000 * k))
        arbre.ecrire(base + "/memory.current", "%d\n" % (2 * GIB))
        arbre.ecrire(base + "/memory.max", "max\n")
        arbre.ecrire(
            base + "/io.stat",
            "8:0 rbytes=%d wbytes=%d rios=1 wios=1\n"
            "259:0 rbytes=%d wbytes=0\n"
            % (1048576 * k, 1048576 * k, 1048576 * k),
        )
        arbre.ecrire(
            base + "/io.pressure",
            "some avg10=0.00 avg60=0.00 avg300=0.00 total=%d\n"
            "full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n" % (1000000 * k),
        )


def hote_complet(test, cgroup_v2=True, pve=True):
    """Un hôte Proxmox inventé : un HDD (sda) et un NVMe, deux invités."""
    a = Arbre(test)
    a.disque("sda", rotatif=True, modele="EXAMPLE-HDD-4T")
    a.partition("sda", "sda1")
    a.disque("nvme0n1", rotatif=False, modele="EXAMPLE-SSD-1T")
    a.dossier("/sys/block/loop0")
    a.ecrire("/proc/cpuinfo", "model name\t: Example CPU 8-Core\n")
    a.ecrire("/proc/sys/vm/swappiness", "60\n")
    a.dossier("/sys/class/net/eno1/device")
    a.ecrire("/sys/class/net/eno1/speed", "1000\n")
    a.dossier("/sys/class/net/vmbr0/bridge")
    if cgroup_v2:
        a.ecrire("/sys/fs/cgroup/cgroup.controllers", "cpu io memory\n")
    if pve:
        a.ecrire(
            "/etc/pve/lxc/101.conf",
            "hostname: ct-web\nmemory: 2048\n\n[snap1]\nhostname: old-name\n",
        )
        a.ecrire(
            "/etc/pve/qemu-server/120.conf",
            "name: vm-demo\nscsi0: local-zfs:vm-120-disk-0,size=32G\n",
        )
    ecrire_compteurs(a, 0)
    return a


class FauxSysteme:
    """Commandes simulées (comptées), horloge et sommeil sans attente."""

    def __init__(
        self,
        sorties=None,
        binaires=(),
        uid=1000,
        temps=(1.0, 1.12),
        interrompre_dormir=None,
        interrompre_lancer=False,
        apres_dormir=None,
        muettes=(),
    ):
        self.sorties = sorties or {}
        self.muettes = set(muettes)
        self.sans_reponse = []
        self.binaires = set(binaires)
        self.uid = uid
        self.temps = list(temps)
        self.interrompre_dormir = interrompre_dormir
        self.interrompre_lancer = interrompre_lancer
        self.apres_dormir = apres_dormir
        self.t = 1000.0
        self.mur = 1790000000.0
        self.appels = []
        self.dormis = []
        self.priorite = 0

    def which(self, nom):
        return "/usr/bin/" + nom if nom in self.binaires else None

    def lancer(self, argv, delai=20):
        self.appels.append(list(argv))
        if self.interrompre_lancer:
            raise KeyboardInterrupt
        if argv[0] not in self.binaires:
            return None, ""
        if tuple(argv) in self.muettes:
            self.sans_reponse.append((list(argv), delai))
            return None, ""
        return self.sorties.get(tuple(argv), (0, ""))

    def euid(self):
        return self.uid

    def horloge(self):
        return self.t

    def maintenant(self):
        return self.mur

    def dormir(self, secondes):
        self.dormis.append(secondes)
        if self.interrompre_dormir == len(self.dormis):
            raise KeyboardInterrupt
        self.t += secondes
        self.mur += secondes
        if self.apres_dormir:
            self.apres_dormir(len(self.dormis))

    def temps_cpu(self):
        return self.temps.pop(0) if self.temps else 0.0

    def nom_hote(self):
        return "pve-example"

    def noyau(self):
        return "6.8.0-example"

    def page_kib(self):
        return 4.0

    def baisser_priorite(self):
        self.priorite += 1


def lancer_main(test, arbre, args, systeme=None, compteurs=True):
    """main() sur l'arborescence ; rend (code, sortie, erreur, systeme)."""
    systeme = systeme or FauxSysteme()
    if compteurs and systeme.apres_dormir is None:
        systeme.apres_dormir = lambda k: ecrire_compteurs(arbre, k)
    sortie, erreur = io.StringIO(), io.StringIO()
    with mock.patch.object(hpa.os, "nice") as nice:
        code = hpa.main(
            ["--root", arbre.racine] + args,
            systeme=systeme,
            sortie=sortie,
            erreur=erreur,
        )
    test.assertFalse(nice.called)
    return code, sortie.getvalue(), erreur.getvalue(), systeme


def ech(
    cpu=None,
    psi=None,
    disks=None,
    mem=None,
    load=None,
    arc=None,
    net=None,
    swap_in=None,
    swap_out=None,
    guests=None,
):
    """Un échantillon de taux synthétique."""
    return {
        "dt": 10.0,
        "wall": 0.0,
        "cpu": cpu,
        "psi": psi or {},
        "disks": disks or {},
        "net": net or {},
        "arc": arc,
        "mem": mem or {},
        "load": load,
        "swap_in": swap_in,
        "swap_out": swap_out,
        "guests": guests or {},
    }


def cpu(busy=10.0, steal=0.0, iowait=0.0):
    return {
        "busy": busy,
        "user": busy,
        "system": 0.0,
        "iowait": iowait,
        "steal": steal,
    }


def dsk(util, attente=1.0, ops=10.0, kib=100.0):
    return {
        "util": util,
        "r_s": ops,
        "w_s": ops,
        "rkb_s": kib,
        "wkb_s": kib,
        "r_await": attente,
        "w_await": attente,
        "queue": 0.0,
    }


def faits(**kw):
    base = {
        "kernel": "6.8.0-example",
        "pve": "",
        "cpu_model": "Example CPU 8-Core",
        "cores": 8,
        "mem_total_kib": 32 * 1048576,
        "swappiness": "60",
        "governor": "",
        "thp": "",
        "ksm": {"run": None, "shared_mib": None},
        "arc_max_param": None,
        "in_container": False,
        "cgroup_v2": True,
        "root": False,
        "disks": {},
    }
    base.update(kw)
    return base


def info_disque(genre, physique=True):
    return {
        "kind": genre,
        "rotational": genre == "HDD",
        "model": "",
        "scheduler": "mq-deadline",
        "size_bytes": None,
        "smart": "",
        "physical": physique,
    }


class FauxBlocs:
    def __init__(self, types):
        self.types = types

    def info(self, nom):
        genre = self.types.get(nom)
        if genre is None:
            return None
        physique = not nom.startswith(("dm-", "md", "zd"))
        return {"kind": genre, "physical": physique, "rotational": None}


def niveau_cpu(echantillons, **kw):
    conseils = hpa.Conseils()
    _res, verdict = hpa.analyser_cpu(echantillons, faits(**kw), conseils)
    return verdict, conseils


# ----------------------------------------------------------------------- #
# 1-6. Lecteurs
# ----------------------------------------------------------------------- #
class TestLecteurs(unittest.TestCase):
    def test_stat_8_et_10_champs_donnent_les_memes_valeurs(self):
        huit = "cpu  1 2 3 4 5 6 7 8\ncpu0 1\ncpu1 1\ncpu2 1\n"
        dix = "cpu  1 2 3 4 5 6 7 8 9 10\ncpu0 1\ncpu1 1\ncpu2 1\n"
        a, b = hpa.analyser_stat(huit), hpa.analyser_stat(dix)
        self.assertEqual(a, b)
        self.assertEqual(a["n"], 3)
        self.assertEqual(a["steal"], 8)

    def test_stat_courte_completee_de_zeros(self):
        r = hpa.analyser_stat("cpu  1 2 3 4 5 6 7\ncpu0 1\n")
        self.assertEqual(r["steal"], 0)
        self.assertEqual(r["softirq"], 7)

    def test_stat_qui_n_est_pas_linux(self):
        self.assertIsNone(hpa.analyser_stat(""))
        self.assertIsNone(hpa.analyser_stat(None))
        self.assertIsNone(hpa.analyser_stat("intr 1 2 3\ncpu 1 2\n"))

    def test_main_sort_en_2_sans_proc_linux(self):
        a = Arbre(self)
        a.ecrire("/proc/stat", "not a stat file\n")
        code, sortie, erreur, systeme = lancer_main(
            self, a, ["--duration", "5"], compteurs=False
        )
        self.assertEqual(code, 2)
        self.assertIn("not Linux /proc", erreur)
        self.assertEqual(sortie, "")
        self.assertEqual(systeme.appels, [])

    def test_pression_some_et_full(self):
        r = hpa.analyser_pression(
            "some avg10=1.50 avg60=2.00 avg300=3.00 total=1234\n"
            "full avg10=0.10 avg60=0.20 avg300=0.30 total=99\n"
        )
        self.assertEqual(r["some"]["total"], 1234)
        self.assertEqual(r["full"]["avg60"], 0.20)

    def test_pression_some_seul(self):
        r = hpa.analyser_pression(
            "some avg10=0.00 avg60=0.00 avg300=0.00 total=5\n"
        )
        self.assertEqual(list(r), ["some"])

    def test_pression_absente_ou_illisible(self):
        self.assertIsNone(hpa.analyser_pression(None))
        a = Arbre(self)
        self.assertIsNone(hpa.lire(a.racine, "/proc/pressure/io"))
        with mock.patch("builtins.open", side_effect=OSError(95, "nope")):
            self.assertIsNone(hpa.lire("", "/proc/pressure/io"))

    def test_main_note_psi_indisponible(self):
        a = hote_complet(self)
        shutil.rmtree(a.chemin("/proc/pressure"))
        code, sortie, _err, _s = lancer_main(
            self, a, ["--duration", "10", "--interval", "10", "--json"]
        )
        self.assertEqual(code, 0)
        donnees = json.loads(sortie)
        self.assertTrue(any("PSI unavailable" in n for n in donnees["notes"]))
        self.assertIsNone(donnees["cpu"]["psi_some_avg"])

    def test_diskstats_14_18_20_champs_et_classement(self):
        a = Arbre(self)
        a.disque("sda", rotatif=True)
        a.partition("sda", "sda1")
        a.disque("nvme0n1", rotatif=False)
        a.partition("nvme0n1", "nvme0n1p3")
        a.disque("nvme0c0n1", rotatif=False)
        a.dossier("/sys/block/loop0")
        a.disque("dm-0", physique=False)
        a.disque("md0", physique=False)
        a.disque("zd0", physique=False)
        a.disque("vda", rotatif=True)
        v = list(range(1, 12))
        texte = "".join(
            ligne_disque(nom, v, champs)
            for nom, champs in (
                ("sda", 14),
                ("sda1", 14),
                ("nvme0n1", 18),
                ("nvme0n1p3", 20),
                ("nvme0c0n1", 20),
                ("loop0", 14),
                ("dm-0", 14),
                ("md0", 14),
                ("zd0", 14),
                ("vda", 20),
            )
        )
        lus = hpa.analyser_diskstats(texte)
        self.assertEqual(lus["sda"]["reads"], 1)
        self.assertEqual(lus["sda"]["weighted_ms"], 11)
        self.assertEqual(lus["nvme0n1p3"]["io_ms"], 10)
        blocs = hpa.Blocs(a.racine)
        gardes = sorted(n for n in lus if blocs.info(n) is not None)
        self.assertEqual(
            gardes, ["dm-0", "md0", "nvme0n1", "sda", "vda", "zd0"]
        )
        physiques = sorted(n for n in gardes if blocs.info(n)["physical"])
        self.assertEqual(physiques, ["nvme0n1", "sda", "vda"])
        self.assertEqual(blocs.info("vda")["kind"], "virtual")
        for nom in ("dm-0", "md0", "zd0"):
            self.assertEqual(blocs.info(nom)["kind"], "virtual")
            self.assertFalse(blocs.info(nom)["physical"])

    def test_diskstats_ligne_trop_courte_ignoree(self):
        self.assertEqual(hpa.analyser_diskstats("8 0 sda 1 2 3\n"), {})

    def test_rotational_donne_le_type(self):
        a = Arbre(self)
        a.disque("sda", rotatif=True)
        a.disque("sdb", rotatif=False)
        a.disque("sdc", rotatif=None)
        a.disque("nvme0n1", rotatif=False)
        blocs = hpa.Blocs(a.racine)
        self.assertEqual(blocs.info("sda")["kind"], "HDD")
        self.assertEqual(blocs.info("sdb")["kind"], "SSD")
        self.assertEqual(blocs.info("sdc")["kind"], "?")
        self.assertEqual(blocs.info("nvme0n1")["kind"], "NVMe")

    def test_meminfo_vmstat_net_loadavg_arcstats(self):
        mem = hpa.analyser_meminfo(
            "MemTotal:  100 kB\nbizarre\nHugePages_Total:   0\nX: abc kB\n"
        )
        self.assertEqual(mem, {"MemTotal": 100, "HugePages_Total": 0})
        self.assertEqual(
            hpa.analyser_vmstat("pgfault 1\npswpin 7\npswpout 9\n"),
            {"pswpin": 7, "pswpout": 9},
        )
        net = hpa.analyser_net_dev(
            "Inter-|\n face |\n    lo: 1 1 0 0 0 0 0 0 1 1 0 0 0 0 0 0\n"
            "  eno1: 100 1 2 3 0 0 0 0 200 1 4 5 0 0 0 0\n"
        )
        self.assertEqual(net, {"eno1": (100, 200, 6, 8)})
        self.assertEqual(hpa.analyser_loadavg("1.25 1 1 1/2 3\n"), 1.25)
        self.assertIsNone(hpa.analyser_loadavg(""))
        arc = hpa.analyser_arcstats(
            "13 1 0x01 1 2 3 4\nname type data\nhits 4 10\nmisses 4 2\n"
        )
        self.assertEqual(arc, {"hits": 10, "misses": 2})
        self.assertIsNone(hpa.analyser_arcstats(None))

    def test_interfaces_vitesse_et_genre(self):
        a = Arbre(self)
        a.dossier("/sys/class/net/eno1/device")
        a.ecrire("/sys/class/net/eno1/speed", "1000\n")
        a.dossier("/sys/class/net/eno2/device")
        a.ecrire("/sys/class/net/eno2/speed", "-1\n")
        a.dossier("/sys/class/net/vmbr0/bridge")
        self.assertEqual(hpa.vitesse_lien(a.racine, "eno1"), 1000)
        self.assertIsNone(hpa.vitesse_lien(a.racine, "eno2"))
        self.assertIsNone(hpa.vitesse_lien(a.racine, "eno3"))
        self.assertEqual(hpa.genre_interface(a.racine, "eno1"), "physical")
        self.assertEqual(hpa.genre_interface(a.racine, "vmbr0"), "bridge")
        for nom in ("tap120i0", "veth101i0", "fwbr120i0", "fwpr1", "fwln1"):
            self.assertEqual(hpa.genre_interface(a.racine, nom), "guest")


# ----------------------------------------------------------------------- #
# 7-12. Taux
# ----------------------------------------------------------------------- #
def instant(t, **kw):
    base = {
        "t": t,
        "wall": t,
        "cpu": None,
        "psi": {},
        "disks": {},
        "mem": {},
        "swap": {},
        "net": {},
        "arc": None,
        "load": None,
        "guests": {},
    }
    base.update(kw)
    return base


def stat(*ticks):
    r = dict(zip(hpa.CHAMPS_CPU, list(ticks) + [0] * (8 - len(ticks))))
    r["n"] = 2
    return r


def compteurs_disque(reads, rd_ms, writes, wr_ms, io_ms, secteurs=0):
    return {
        "reads": reads,
        "rd_sectors": secteurs,
        "rd_ms": rd_ms,
        "writes": writes,
        "wr_sectors": secteurs,
        "wr_ms": wr_ms,
        "io_ms": io_ms,
        "weighted_ms": 0,
    }


class TestTaux(unittest.TestCase):
    def test_cpu_occupe_et_iowait(self):
        a = instant(0, cpu=stat(1000, 0, 500, 8000, 100))
        b = instant(10, cpu=stat(1400, 0, 600, 8400, 200, 0, 0, 0))
        r = hpa.taux(a, b)
        self.assertAlmostEqual(r["cpu"]["busy"], 50.0, places=3)
        self.assertAlmostEqual(r["cpu"]["iowait"], 10.0, places=3)

    def test_cpu_figee_ne_donne_pas_100(self):
        a = instant(0, cpu=stat(1000, 0, 500, 8000, 100))
        b = instant(10, cpu=stat(1000, 0, 500, 8000, 100))
        self.assertIsNone(hpa.taux(a, b)["cpu"])

    def test_vol_calcule(self):
        a = instant(0, cpu=stat(0, 0, 0, 0, 0, 0, 0, 0))
        b = instant(10, cpu=stat(50, 0, 0, 40, 0, 0, 0, 10))
        self.assertAlmostEqual(hpa.taux(a, b)["cpu"]["steal"], 10.0)

    def test_disque_util_et_attentes(self):
        a = instant(0, disks={"sda": compteurs_disque(0, 0, 0, 0, 0, 0)})
        b = instant(
            10,
            disks={"sda": compteurs_disque(100, 2000, 100, 4000, 8000, 2048)},
        )
        d = hpa.taux(a, b)["disks"]["sda"]
        self.assertAlmostEqual(d["util"], 80.0)
        self.assertAlmostEqual(d["r_await"], 20.0)
        self.assertAlmostEqual(d["w_await"], 40.0)
        self.assertAlmostEqual(d["rkb_s"], 2048 / 2.0 / 10)

    def test_sans_lecture_pas_d_attente(self):
        a = instant(0, disks={"sda": compteurs_disque(0, 0, 0, 0, 0)})
        b = instant(10, disks={"sda": compteurs_disque(0, 0, 10, 50, 100)})
        self.assertIsNone(hpa.taux(a, b)["disks"]["sda"]["r_await"])

    def test_psi_et_bornes(self):
        def psi(total):
            return {"io": {"some": {"total": total}, "full": {"total": 0}}}

        r = hpa.taux(instant(0, psi=psi(0)), instant(10, psi=psi(2000000)))
        self.assertAlmostEqual(r["psi"]["io"]["some"], 20.0)
        r = hpa.taux(instant(0, psi=psi(0)), instant(10, psi=psi(99 * 10**6)))
        self.assertEqual(r["psi"]["io"]["some"], 100.0)

    def test_compteur_qui_recule_retire_l_element(self):
        a = instant(
            0,
            disks={"sda": compteurs_disque(500, 0, 0, 0, 900)},
            net={"tap120i0": (5000, 5000, 0, 0), "eno1": (0, 0, 0, 0)},
            guests={
                "101": {
                    "cpu_usec": 9000000,
                    "io_rbytes": 0,
                    "io_wbytes": 0,
                    "io_some_us": None,
                },
            },
        )
        b = instant(
            10,
            disks={"sda": compteurs_disque(10, 0, 0, 0, 10)},
            net={"tap120i0": (100, 100, 0, 0), "eno1": (1024, 0, 0, 0)},
            guests={
                "101": {
                    "cpu_usec": 1000,
                    "io_rbytes": 0,
                    "io_wbytes": 0,
                    "io_some_us": None,
                },
            },
        )
        r = hpa.taux(a, b)
        self.assertEqual(r["disks"], {})
        self.assertEqual(list(r["net"]), ["eno1"])
        self.assertEqual(r["guests"], {})

    def test_arc(self):
        a = instant(0, arc={"hits": 9000, "misses": 1000, "size": 1})
        b = instant(
            10,
            arc={
                "hits": 9900,
                "misses": 1100,
                "size": 5,
                "c_max": 8,
                "memory_throttle_count": 2,
            },
        )
        r = hpa.taux(a, b)["arc"]
        self.assertAlmostEqual(r["hit"], 90.0)
        self.assertEqual(r["size"], 5)
        self.assertEqual(r["throttle"], 2)
        self.assertIsNone(r["l2_hit"])
        immobile = hpa.taux(a, instant(10, arc=dict(a["arc"])))["arc"]
        self.assertIsNone(immobile["hit"])
        l2 = hpa.taux(
            instant(0, arc={"l2_hits": 10, "l2_misses": 10}),
            instant(10, arc={"l2_hits": 40, "l2_misses": 20}),
        )["arc"]
        self.assertAlmostEqual(l2["l2_hit"], 75.0)

    def test_swap_en_kio_par_seconde(self):
        a = instant(0, swap={"pswpin": 0, "pswpout": 100})
        b = instant(10, swap={"pswpin": 250, "pswpout": 600})
        r = hpa.taux(a, b, page_kib=4.0)
        self.assertAlmostEqual(r["swap_in"], 100.0)
        self.assertAlmostEqual(r["swap_out"], 200.0)

    def test_invite(self):
        commun = {"io_rbytes": 0, "io_wbytes": 0, "mem": 7, "mem_max": None}
        a = instant(0, guests={"101": dict(commun, cpu_usec=0, io_some_us=0)})
        b = instant(
            10,
            guests={
                "101": dict(
                    commun,
                    cpu_usec=5000000,
                    io_some_us=1000000,
                    io_rbytes=1024,
                    io_wbytes=1024,
                )
            },
        )
        g = hpa.taux(a, b)["guests"]["101"]
        self.assertAlmostEqual(g["cpu"], 50.0)
        self.assertAlmostEqual(g["io"], 204.8)
        self.assertAlmostEqual(g["io_some"], 10.0)


# ----------------------------------------------------------------------- #
# 13. Centiles et moyennes
# ----------------------------------------------------------------------- #
class TestCentiles(unittest.TestCase):
    def test_rang_le_plus_proche(self):
        vingt = list(range(1, 21))
        self.assertEqual(hpa.pct(vingt, 95), 19)
        self.assertEqual(hpa.pct(vingt, 5), 1)
        self.assertEqual(hpa.pct(list(range(1, 41)), 95), 38)
        self.assertEqual(hpa.pct([None, 3, None, 1], 100), 3)
        self.assertIsNone(hpa.pct([], 95))
        self.assertIsNone(hpa.pct([None], 95))

    def test_moyenne_ignore_none(self):
        self.assertEqual(hpa.avg([None, 2, 4]), 3)
        self.assertIsNone(hpa.avg([None]))


# ----------------------------------------------------------------------- #
# 14-18. Verdicts
# ----------------------------------------------------------------------- #
def psi_cpu(some):
    return {"cpu": {"some": some}}


class TestVerdictCpu(unittest.TestCase):
    def test_seuils_psi(self):
        for some, attendu in ((9.9, "ok"), (10, "watch"), (25, "limiting")):
            with self.subTest(some=some):
                v, _c = niveau_cpu([ech(cpu=cpu(), psi=psi_cpu(some))])
                self.assertEqual(v["level"], attendu)

    def test_occupation_p95(self):
        v, _c = niveau_cpu([ech(cpu=cpu(busy=90), psi=psi_cpu(0))])
        self.assertEqual(v["level"], "watch")

    def test_vol(self):
        v, c = niveau_cpu([ech(cpu=cpu(steal=5), psi=psi_cpu(0))])
        self.assertEqual(v["level"], "limiting")
        self.assertEqual([x["id"] for x in c.liste], ["steal"])

    def test_gouverneur(self):
        _v, c = niveau_cpu(
            [ech(cpu=cpu(), psi=psi_cpu(12))], governor="powersave"
        )
        self.assertIn("governor", [x["id"] for x in c.liste])
        _v, c = niveau_cpu(
            [ech(cpu=cpu(), psi=psi_cpu(0))], governor="powersave"
        )
        self.assertEqual(c.liste, [])

    def test_charge_sans_psi(self):
        v, _c = niveau_cpu([ech(cpu=cpu(), load=12.0)], cores=8)
        self.assertEqual(v["level"], "watch")
        self.assertIn("load", v["reason"])
        v, _c = niveau_cpu([ech(cpu=cpu(), load=20.0)], cores=8)
        self.assertEqual(v["level"], "limiting")
        v, _c = niveau_cpu(
            [ech(cpu=cpu(), load=20.0, psi=psi_cpu(0))], cores=8
        )
        self.assertEqual(v["level"], "watch")


def mem(dispo=16 * 1048576, swap_libre=8 * 1048576):
    m = {
        "MemTotal": 32 * 1048576,
        "SwapTotal": 8 * 1048576,
        "SwapFree": swap_libre,
    }
    if dispo is not None:
        m["MemAvailable"] = dispo
    return m


def niveau_memoire(echantillons, **kw):
    conseils = hpa.Conseils()
    res, verdict = hpa.analyser_memoire(echantillons, faits(**kw), conseils)
    return res, verdict, conseils


class TestVerdictMemoire(unittest.TestCase):
    def test_seuils(self):
        for some, attendu in ((1.9, "ok"), (2, "watch"), (10, "limiting")):
            with self.subTest(some=some):
                _r, v, _c = niveau_memoire(
                    [ech(mem=mem(), psi={"memory": {"some": some}})]
                )
                self.assertEqual(v["level"], attendu)

    def test_disponible_minimal(self):
        _r, v, _c = niveau_memoire([ech(mem=mem(dispo=1048576))])
        self.assertEqual(v["level"], "watch")

    def test_memavailable_absent_partout(self):
        r, v, _c = niveau_memoire([ech(mem=mem(dispo=None))] * 3)
        self.assertIsNone(r["available_min_kib"])
        self.assertEqual(v["level"], "ok")

    def test_swappiness(self):
        swap = mem(swap_libre=8 * 1048576 - 600 * 1024)
        _r, _v, c = niveau_memoire([ech(mem=swap)], swappiness="60")
        conseil = [x for x in c.liste if x["id"] == "swappiness"]
        self.assertEqual(len(conseil), 1)
        self.assertTrue(
            any("vm.swappiness=10" in x for x in conseil[0]["commands"])
        )
        _r, _v, c = niveau_memoire([ech(mem=swap)], swappiness="10")
        self.assertEqual(c.liste, [])

    def test_echange_actif(self):
        _r, v, _c = niveau_memoire(
            [ech(mem=mem(), swap_in=200.0, swap_out=100.0)]
        )
        self.assertEqual(v["level"], "watch")


def arc_ech(c_max_gib, hit, dispo_gib=16):
    return ech(
        mem=mem(dispo=dispo_gib * 1048576),
        arc={
            "hit": hit,
            "size": 4 * GIB,
            "c_max": c_max_gib * GIB,
            "c_min": GIB,
            "throttle": 0,
            "l2_hit": None,
        },
    )


class TestArc(unittest.TestCase):
    def conseils(self, echantillons, niveau):
        c = hpa.Conseils()
        memoire, _v = hpa.analyser_memoire(echantillons, faits(), c)
        c.liste = []
        with (
            mock.patch.object(hpa.subprocess, "run") as run,
            mock.patch("builtins.open") as ouvrir,
        ):
            hpa.analyser_arc(echantillons, memoire, niveau, c)
        self.assertFalse(run.called)
        self.assertFalse(ouvrir.called)
        return c.liste

    def test_baisse_quand_la_memoire_est_tendue(self):
        liste = self.conseils([arc_ech(20, 95)], "watch")
        self.assertEqual([x["id"] for x in liste], ["arc_max_lower"])
        self.assertIn("8 GiB", liste[0]["text"])
        commandes = " ".join(liste[0]["commands"])
        self.assertIn(str(8 * GIB), commandes)
        self.assertIn("zfs_arc_max", commandes)
        self.assertIn("/etc/modprobe.d", commandes)

    def test_hausse_quand_le_cache_rate(self):
        liste = self.conseils([arc_ech(8, 80)], "ok")
        self.assertEqual([x["id"] for x in liste], ["arc_max_raise"])
        self.assertIn("16 GiB", liste[0]["text"])

    def test_pas_de_hausse_sans_marge(self):
        self.assertEqual(self.conseils([arc_ech(15, 80)], "ok"), [])


def disques_juges(types, echantillons, faits_disques=None):
    c = hpa.Conseils()
    res = hpa.analyser_disques(
        echantillons,
        faits(disks=faits_disques or {}),
        FauxBlocs(types),
        c,
    )
    return res, c


class TestVerdictDisques(unittest.TestCase):
    def niveau(self, genre, util, attente, ops=10.0):
        res, _c = disques_juges(
            {"sdx": genre}, [ech(disks={"sdx": dsk(util, attente, ops)})]
        )
        return res["sdx"]["level"]

    def test_rotatif(self):
        self.assertEqual(self.niveau("HDD", 92, 1), "limiting")
        self.assertEqual(self.niveau("HDD", 65, 30), "limiting")
        self.assertEqual(self.niveau("HDD", 65, 10), "watch")
        self.assertEqual(self.niveau("HDD", 10, 30), "watch")
        self.assertEqual(self.niveau("HDD", 10, 10), "ok")

    def test_ssd_jugee_sur_l_attente(self):
        self.assertEqual(self.niveau("SSD", 95, 1), "ok")
        self.assertEqual(self.niveau("NVMe", 99, 1), "ok")
        self.assertEqual(self.niveau("SSD", 10, 6), "watch")

    def test_type_inconnu_au_seuil_des_rotatifs(self):
        self.assertEqual(hpa.juger_disque("?", 0, 10, 0), "ok")
        self.assertEqual(hpa.juger_disque("?", 0, 30, 0), "watch")
        self.assertEqual(hpa.juger_disque("?", 99, 1, 1), "ok")

    def test_attentes_sans_activite_ignorees(self):
        self.assertEqual(self.niveau("HDD", 10, 300, ops=0.2), "ok")

    def test_virtuel_jamais_juge_et_cache_s_il_dort(self):
        res, _c = disques_juges(
            {"zd0": "virtual", "dm-0": "virtual"},
            [ech(disks={"zd0": dsk(0.5), "dm-0": dsk(50)})],
        )
        self.assertNotIn("zd0", res)
        self.assertIsNone(res["dm-0"]["level"])

    def test_pression_de_l_hote(self):
        for psi, attendu in (
            ({"some": 15, "full": 0}, "limiting"),
            ({"some": 0, "full": 5}, "limiting"),
            ({"some": 6, "full": 0}, "watch"),
        ):
            with self.subTest(psi=psi):
                io_psi = hpa.analyser_io_psi([ech(psi={"io": psi})])
                v = hpa.verdict_disques({}, io_psi)
                self.assertEqual(v["level"], attendu)

    def test_smart_et_ordonnanceur(self):
        defaillant = dict(info_disque("HDD"), smart="FAILED")
        ssd = dict(info_disque("SSD"), scheduler="bfq")
        _res, c = disques_juges({}, [], {"sda": defaillant, "sdb": ssd})
        ids = {x["id"]: x for x in c.liste}
        self.assertEqual(ids["smart_failed"]["priority"], "high")
        self.assertEqual(ids["scheduler"]["priority"], "low")


class TestVerdictReseau(unittest.TestCase):
    def setUp(self):
        self.a = Arbre(self)
        self.a.dossier("/sys/class/net/eno1/device")
        self.a.ecrire("/sys/class/net/eno1/speed", "1000\n")
        self.a.dossier("/sys/class/net/eno2/device")
        self.a.ecrire("/sys/class/net/eno2/speed", "-1\n")

    def juger(self, net):
        return hpa.analyser_reseau([ech(net=net)], self.a.racine)

    def lien(self, pct, erreurs=0):
        kib = pct / 100.0 * 1000 * 1e6 / 8 / 1024
        return {
            "rx_kib_s": kib,
            "tx_kib_s": 0.0,
            "errors": erreurs,
            "drops": 0,
        }

    def test_utilisation_du_lien(self):
        res, v = self.juger({"eno1": self.lien(95)})
        self.assertEqual(res["eno1"]["level"], "limiting")
        self.assertEqual(v["level"], "limiting")
        res, v = self.juger({"eno1": self.lien(75)})
        self.assertEqual(v["level"], "watch")

    def test_vitesse_inconnue(self):
        res, v = self.juger({"eno2": self.lien(95)})
        self.assertIsNone(res["eno2"]["speed_mbps"])
        self.assertEqual(v["level"], "ok")

    def test_erreurs(self):
        _res, v = self.juger({"eno1": self.lien(1, erreurs=3)})
        self.assertEqual(v["level"], "watch")

    def test_interface_oisive_cachee_et_invites_groupees(self):
        oisive = {"rx_kib_s": 0.1, "tx_kib_s": 0.1, "errors": 0, "drops": 0}
        tap = {"rx_kib_s": 50.0, "tx_kib_s": 5.0, "errors": 0, "drops": 0}
        res, _v = self.juger(
            {"eno1": oisive, "tap120i0": tap, "veth101i0": tap}
        )
        self.assertEqual(list(res), [hpa.GROUPE_INVITES])
        self.assertAlmostEqual(res[hpa.GROUPE_INVITES]["rx_kib_s_avg"], 100.0)


# ----------------------------------------------------------------------- #
# 19-22. « Des SSD ? »
# ----------------------------------------------------------------------- #
def ligne(genre, util, niveau, kib=100.0):
    return {
        "kind": genre,
        "util_avg": util,
        "util_p95": util,
        "util_max": util,
        "r_s_avg": 1.0,
        "w_s_avg": 1.0,
        "rkb_s_avg": kib,
        "wkb_s_avg": kib,
        "r_await_p95": 30.0,
        "w_await_p95": 30.0,
        "level": niveau,
    }


def pool(donnees, medias, special=()):
    return {
        "data_disks": list(donnees),
        "media": list(medias),
        "special_disks": list(special),
        "log_disks": [],
        "has_log": False,
        "has_special": bool(special),
        "scrub": "",
        "health": "ONLINE",
        "cap_pct": 40,
        "frag_pct": 10,
        "ashift": "12",
        "latency_ms": {},
    }


class TestReponseSsd(unittest.TestCase):
    def test_disque_rotatif_sature(self):
        zfs = {"pools": {"tank": pool(["sda"], ["HDD"])}}
        r = hpa.reponse_ssd(
            faits(disks={"sda": info_disque("HDD")}),
            {"sda": ligne("HDD", 92, "limiting")},
            zfs,
            {"some_avg": 20, "full_avg": 6},
            [],
        )
        self.assertEqual(r["answer"], "yes")
        etapes = " ".join(r["steps"])
        self.assertIn("special", etapes)
        self.assertIn("SLOG", etapes)
        self.assertIn("ARC", etapes)

    def test_rotatif_calme(self):
        r = hpa.reponse_ssd(
            faits(disks={"sda": info_disque("HDD")}),
            {"sda": ligne("HDD", 20, "ok")},
            None,
            {"some_avg": 1, "full_avg": 0},
            [],
        )
        self.assertEqual(r["answer"], "no")
        self.assertIn("cold cache", r["reason"])

    def test_rotatif_oisif_pools_illisibles(self):
        """Pools non lus alors que ZFS est chargé : la raison ne prétend
        pas que le disque n'appartient à aucun pool."""
        disques = {"sda": ligne("HDD", 1, "ok")}
        inconnu = hpa.reponse_ssd(
            faits(disks={"sda": info_disque("HDD")}, zfs_loaded=True),
            disques,
            None,
            {"some_avg": 0, "full_avg": 0},
            [],
        )
        self.assertEqual(inconnu["answer"], "not_applicable")
        self.assertIn("unknown", inconnu["reason"])
        self.assertNotIn("belong to no ZFS pool", inconnu["reason"])
        sans_zfs = hpa.reponse_ssd(
            faits(disks={"sda": info_disque("HDD")}, zfs_loaded=False),
            disques,
            None,
            {"some_avg": 0, "full_avg": 0},
            [],
        )
        self.assertIn("belong to no ZFS pool", sans_zfs["reason"])

    def test_pointes_seulement(self):
        r = hpa.reponse_ssd(
            faits(disks={"sda": info_disque("HDD")}),
            {"sda": ligne("HDD", 30, "ok")},
            None,
            {"some_avg": 6, "full_avg": 0},
            [],
        )
        self.assertEqual(r["answer"], "not_yet")
        self.assertIn("24h", r["reason"])

    def test_pool_nvme_sature_et_hdd_oisif_hors_pool(self):
        """La pression d'E/S d'un pool NVMe saturé n'est pas imputée à un
        HDD oisif hors de tout pool : pas de réponse « SSD »."""
        disques_faits = {
            "nvme0n1": info_disque("NVMe"),
            "nvme1n1": info_disque("NVMe"),
            "sdb": info_disque("HDD"),
        }
        zfs = {"pools": {"rpool": pool(["nvme0n1", "nvme1n1"], ["NVMe"])}}
        mesures = {
            "nvme0n1": ligne("NVMe", 99, "ok", kib=50000),
            "nvme1n1": ligne("NVMe", 99, "ok", kib=50000),
            "sdb": ligne("HDD", 0, "ok", kib=0),
        }
        io_psi = {"some_avg": 20, "full_avg": 0}
        r = hpa.reponse_ssd(
            faits(disks=disques_faits), mesures, zfs, io_psi, []
        )
        self.assertEqual(r["answer"], "not_applicable")
        c = hpa.Conseils()
        hpa.analyser_zfs(dict(zfs, datasets={}), io_psi, c)
        self.assertNotIn("special_vdev", [x["id"] for x in c.liste])
        self.assertFalse(any("rotational" in x["text"] for x in c.liste))

    def test_toutes_les_taches_attendent_et_les_rotatifs_portent_le_debit(
        self,
    ):
        """PSI full seul suffit, et la majorité du débit suffit quand
        l'utilisation mesurée est surtout celle du flash."""
        disques_faits = {
            "sda": info_disque("HDD"),
            "nvme0n1": info_disque("NVMe"),
        }
        zfs = {"pools": {"tank": pool(["sda"], ["HDD"])}}
        mesures = {
            "sda": ligne("HDD", 2, "ok", kib=90000),
            "nvme0n1": ligne("NVMe", 90, "ok", kib=10),
        }
        r = hpa.reponse_ssd(
            faits(disks=disques_faits),
            mesures,
            zfs,
            {"some_avg": 0, "full_avg": 6},
            [],
        )
        self.assertEqual(r["answer"], "yes")

    def test_pression_imputee_aux_rotatifs_seulement_s_ils_portent_la_charge(
        self,
    ):
        disques_faits = {
            "sda": info_disque("HDD"),
            "nvme0n1": info_disque("NVMe"),
        }
        zfs = {"pools": {"tank": pool(["sda"], ["HDD"])}}
        mesures = {
            "sda": ligne("HDD", 2, "ok", kib=10),
            "nvme0n1": ligne("NVMe", 90, "ok", kib=90000),
        }
        r = hpa.reponse_ssd(
            faits(disks=disques_faits),
            mesures,
            zfs,
            {"some_avg": 20, "full_avg": 0},
            [],
        )
        self.assertEqual(r["answer"], "no")


# ----------------------------------------------------------------------- #
# 23-29. ZFS
# ----------------------------------------------------------------------- #
STATUS = """  pool: rpool
 state: ONLINE
config:

\tNAME                STATE     READ WRITE CKSUM
\trpool               ONLINE       0     0     0
\t  mirror-0          ONLINE       0     0     0
\t    /dev/nvme1n1p3  ONLINE       0     0     0
\t    /dev/dm-1       ONLINE       0     0     0

errors: No known data errors

  pool: tank
 state: DEGRADED
  scan: scrub in progress since Sun Oct 11 00:24:01 2026
config:

\tNAME                STATE     READ WRITE CKSUM
\ttank                DEGRADED     0     0     0
\t  raidz1-0          DEGRADED     0     0     0
\t    /dev/sda3       ONLINE       0     0     0
\t    /dev/sdb3       ONLINE       0     0     0
\t    /dev/sdc        ONLINE       0     0     0
\t    /var/tmp/x.img  ONLINE       0     0     0
\tlogs
\t  /dev/nvme0n1p1    ONLINE       0     0     0
\tcache
\t  /dev/nvme0n1p2    ONLINE       0     0     0
\tspares
\t  /dev/sdd          AVAIL

errors: No known data errors
"""

LISTE = (
    "rpool\t1000000000000\t400\t600\t-\t40\tONLINE\n"
    "tank\t4000000000000\t3400\t600\t55\t85\tDEGRADED\n"
)
ASHIFT = "rpool\t0\ntank\t9\n"
IOSTAT = (
    "rpool\t1\t2\t3\t4\t5\t6\t100000\t200000\t1\t1\t-\t40000000\t-\t1\t0\n"
    "tank\t1\t2\t3\t4\t5\t6\t1\t1\t1\t1\t-\t40000000\t-\t1\t0\t0\t0\n"
)
ZFS_GET = (
    "rpool\ttype\tfilesystem\t-\n"
    "rpool\tcompression\ton\tdefault\n"
    "rpool\tatime\toff\tlocal\n"
    "rpool\tsync\tstandard\tdefault\n"
    "tank\ttype\tfilesystem\t-\n"
    "tank\tcompression\ton\tdefault\n"
    "tank/data\ttype\tfilesystem\t-\n"
    "tank/data\tcompression\toff\tlocal\n"
    "tank/data/a\ttype\tfilesystem\t-\n"
    "tank/data/a\tcompression\toff\tinherited from tank/data\n"
    "tank/data/b\ttype\tfilesystem\t-\n"
    "tank/data/b\tcompression\toff\tinherited from tank/data\n"
    "tank/vol\ttype\tvolume\t-\n"
    "tank/vol\tatime\ton\tlocal\n"
    "tank/fast\ttype\tfilesystem\t-\n"
    "tank/fast\tsync\tdisabled\tlocal\n"
)
CMD_LIST = (
    "zpool",
    "list",
    "-H",
    "-p",
    "-o",
    "name,size,alloc,free,frag,cap,health",
)
CMD_STATUS = ("zpool", "status", "-P", "-L")
CMD_ASHIFT = ("zpool", "get", "-H", "-p", "-o", "name,value", "ashift")
CMD_IOSTAT = ("zpool", "iostat", "-l", "-H", "-p")
CMD_STATUS_X = ("zpool", "status", "-x")
CMD_ZFS_GET = (
    "zfs",
    "get",
    "-H",
    "-p",
    "-o",
    "name,property,value,source",
    "-t",
    "filesystem,volume",
    "type,compression,atime,relatime,sync",
)


def arbre_zfs(test):
    a = Arbre(test)
    for nom in ("sda", "sdb", "sdc", "sdd"):
        a.disque(nom, rotatif=True, modele="EXAMPLE-HDD-4T")
    a.partition("sda", "sda3")
    a.partition("sdb", "sdb3")
    for nom in ("nvme0n1", "nvme1n1", "nvme2n1"):
        a.disque(nom, rotatif=False, modele="EXAMPLE-SSD-1T")
    a.partition("nvme0n1", "nvme0n1p1")
    a.partition("nvme0n1", "nvme0n1p2")
    a.partition("nvme1n1", "nvme1n1p3")
    a.partition("nvme2n1", "nvme2n1p3")
    a.disque("dm-1", physique=False)
    a.dossier("/sys/block/dm-1/slaves/nvme2n1p3")
    return a


def sorties_zfs(status=STATUS):
    return {
        CMD_LIST: (0, LISTE),
        CMD_STATUS: (0, status),
        CMD_STATUS_X: (0, "pool 'tank' is degraded\n"),
        CMD_ASHIFT: (0, ASHIFT),
        CMD_IOSTAT: (0, IOSTAT),
        CMD_ZFS_GET: (0, ZFS_GET),
    }


class TestZfs(unittest.TestCase):
    def faits_zfs(self, arbre, systeme=None):
        systeme = systeme or FauxSysteme(
            sorties_zfs(), binaires=("zpool", "zfs")
        )
        notes = []
        z = hpa.faits_zfs(
            arbre.racine, systeme, hpa.Blocs(arbre.racine), notes
        )
        return z, notes, systeme

    def test_disques_des_pools_par_leurs_vdevs(self):
        z, _notes, _s = self.faits_zfs(arbre_zfs(self))
        tank, rpool = z["pools"]["tank"], z["pools"]["rpool"]
        self.assertEqual(tank["data_disks"], ["sda", "sdb", "sdc"])
        self.assertEqual(tank["log_disks"], ["nvme0n1"])
        self.assertEqual(tank["cache_disks"], ["nvme0n1"])
        self.assertEqual(tank["spare_disks"], ["sdd"])
        self.assertEqual(tank["media"], ["HDD"])
        self.assertEqual(tank["vdev_types"], ["raidz1"])
        self.assertEqual(tank["unresolved_vdevs"], ["/var/tmp/x.img"])
        self.assertEqual(rpool["data_disks"], ["nvme1n1", "nvme2n1"])
        self.assertEqual(rpool["media"], ["NVMe"])
        self.assertEqual(rpool["vdev_types"], ["mirror"])
        self.assertEqual(z["summary"], "pool 'tank' is degraded")

    def test_lien_by_id_resolu_sous_la_racine(self):
        a = arbre_zfs(self)
        a.lien("/dev/disk/by-id/ata-EXAMPLE-part3", "../../sda3")
        blocs = hpa.Blocs(a.racine)
        self.assertEqual(
            blocs.vdev("/dev/disk/by-id/ata-EXAMPLE-part3"), ["sda"]
        )
        self.assertEqual(blocs.vdev("sdb3"), ["sdb"])
        self.assertEqual(blocs.vdev("/dev/inconnu"), [])

    def test_regles_des_pools(self):
        z, _notes, _s = self.faits_zfs(arbre_zfs(self))
        self.assertEqual(z["pools"]["rpool"]["ashift"], "auto")
        self.assertIsNone(z["pools"]["rpool"]["frag_pct"])
        self.assertAlmostEqual(
            z["pools"]["rpool"]["latency_ms"]["syncq_w"], 40.0
        )
        c = hpa.Conseils()
        hpa.analyser_zfs(z, {"some_avg": 0}, c)
        par_id = {}
        for x in c.liste:
            par_id.setdefault(x["id"], []).append(x)
        self.assertIn("scrub_running", par_id)
        self.assertEqual(par_id["pool_health"][0]["priority"], "high")
        self.assertEqual(par_id["pool_capacity"][0]["priority"], "medium")
        self.assertEqual(par_id["pool_fragmentation"][0]["priority"], "low")
        self.assertEqual(len(par_id["pool_fragmentation"]), 1)
        self.assertEqual(len(par_id["pool_ashift"]), 1)
        self.assertIn("tank", par_id["pool_ashift"][0]["text"])
        slog = par_id["slog"]
        self.assertEqual(len(slog), 1)
        self.assertIn("rpool", slog[0]["text"])

    def test_remplissage_haut(self):
        z, _notes, _s = self.faits_zfs(arbre_zfs(self))
        z["pools"]["tank"]["cap_pct"] = 92
        c = hpa.Conseils()
        hpa.analyser_zfs(z, {"some_avg": 0}, c)
        cap = [x for x in c.liste if x["id"] == "pool_capacity"]
        self.assertEqual(cap[0]["priority"], "high")

    def test_iostat_tiret_et_colonnes(self):
        r = hpa.analyser_iostat(
            "p\t1\t2\t3\t4\t5\t6\t-\t-\t-\t-\t-\t-\t-\t-\ncourt\t1\t2\t3\n"
        )
        self.assertEqual(list(r), ["p"])
        self.assertIsNone(r["p"]["syncq_w"])

    def test_datasets(self):
        z, _notes, _s = self.faits_zfs(arbre_zfs(self))
        c = hpa.Conseils()
        hpa.analyser_datasets(z, c)
        compression = [x for x in c.liste if x["id"] == "zfs_compression"]
        self.assertEqual(len(compression), 1)
        self.assertEqual(
            compression[0]["commands"], ["zfs set compression=lz4 tank/data"]
        )
        self.assertEqual([x for x in c.liste if x["id"] == "zfs_atime"], [])
        sync = [x for x in c.liste if x["id"] == "sync_disabled"]
        self.assertEqual(sync[0]["priority"], "high")
        self.assertEqual(len(z["datasets_flagged"]), 2)

    def test_pool_hdd_sans_special(self):
        z, _notes, _s = self.faits_zfs(arbre_zfs(self))
        c = hpa.Conseils()
        hpa.analyser_zfs(z, {"some_avg": 6}, c)
        special = [x for x in c.liste if x["id"] == "special_vdev"]
        self.assertEqual(len(special), 1)
        self.assertIn("tank", special[0]["text"])

    def test_zpool_absent_l_arc_reste(self):
        a = hote_complet(self)
        code, sortie, _e, _s = lancer_main(
            self, a, ["--duration", "10", "--interval", "10", "--json"]
        )
        self.assertEqual(code, 0)
        donnees = json.loads(sortie)
        self.assertEqual(donnees["zfs"]["pools"], {})
        self.assertIsNotNone(donnees["zfs"]["arc"])
        self.assertAlmostEqual(donnees["zfs"]["arc"]["hit_avg"], 90.0)

    def test_sans_arc_ni_zpool_zfs_est_null(self):
        a = hote_complet(self)
        os.remove(a.chemin("/proc/spl/kstat/zfs/arcstats"))
        systeme = FauxSysteme(
            apres_dormir=lambda k: (
                ecrire_compteurs(a, k),
                os.remove(a.chemin("/proc/spl/kstat/zfs/arcstats")),
            )
        )
        code, sortie, _e, _s = lancer_main(
            self,
            a,
            ["--duration", "10", "--interval", "10", "--json"],
            systeme,
        )
        self.assertEqual(code, 0)
        self.assertIsNone(json.loads(sortie)["zfs"])

    def test_zpool_introuvable_module_charge_note(self):
        """ZFS chargé mais zpool introuvable : une note le dit, au lieu
        d'une section des pools qui disparaît sans un mot."""
        for trace in ("/sys/module/zfs", "/proc/spl/kstat/zfs/arcstats"):
            with self.subTest(trace=trace):
                a = arbre_zfs(self)
                if trace.startswith("/sys"):
                    a.dossier(trace)
                else:
                    a.ecrire(trace, "")
                z, notes, _s = self.faits_zfs(a, FauxSysteme(binaires=()))
                self.assertIsNone(z)
                self.assertEqual(len(notes), 1, notes)
                self.assertIn("zpool was not found", notes[0])
                self.assertIn("/usr/sbin", notes[0])

    def test_zpool_introuvable_sans_zfs_aucune_note(self):
        z, notes, _s = self.faits_zfs(
            arbre_zfs(self), FauxSysteme(binaires=())
        )
        self.assertIsNone(z)
        self.assertEqual(notes, [])

    def test_zpool_refuse(self):
        systeme = FauxSysteme(
            {CMD_LIST: (1, "permission denied")}, binaires=("zpool",)
        )
        z, notes, _s = self.faits_zfs(arbre_zfs(self), systeme)
        self.assertIsNone(z)
        self.assertTrue(any("zpool not usable" in n for n in notes))

    def test_chaque_commande_une_seule_fois(self):
        a = hote_complet(self)
        sorties = sorties_zfs()
        sorties[("pveversion",)] = (0, "pve-manager/8.2.2 (running kernel)\n")
        systeme = FauxSysteme(
            sorties,
            binaires=("zpool", "zfs", "pveversion", "smartctl"),
            uid=0,
        )
        code, _o, _e, systeme = lancer_main(
            self, a, ["--duration", "30", "--interval", "10"], systeme
        )
        self.assertEqual(code, 0)
        vus = [tuple(x) for x in systeme.appels]
        for commande in (
            CMD_LIST,
            CMD_STATUS,
            CMD_STATUS_X,
            CMD_ASHIFT,
            CMD_IOSTAT,
            CMD_ZFS_GET,
            ("pveversion",),
        ):
            self.assertEqual(vus.count(commande), 1, commande)
        smart = [x for x in vus if x[0] == "smartctl"]
        self.assertEqual(
            sorted(smart),
            [
                ("smartctl", "-n", "standby", "-H", "/dev/nvme0n1"),
                ("smartctl", "-n", "standby", "-H", "/dev/sda"),
            ],
        )

    def test_pool_nomme_comme_une_section(self):
        """La ligne du pool n'ouvre jamais une section : un pool nommé
        « logs » ou « cache » garde ses disques de données."""
        for nom in ("logs", "cache", "special", "dedup", "spares"):
            with self.subTest(nom=nom):
                texte = (
                    "  pool: %s\n state: ONLINE\nconfig:\n\n"
                    "\tNAME          STATE     READ WRITE CKSUM\n"
                    "\t%-13s ONLINE       0     0     0\n"
                    "\t  mirror-0    ONLINE       0     0     0\n"
                    "\t    /dev/sda1 ONLINE       0     0     0\n"
                    "\t    /dev/sdb1 ONLINE       0     0     0\n"
                    "\nerrors: No known data errors\n" % (nom, nom)
                )
                p = hpa.analyser_zpool_status(texte)[nom]
                self.assertEqual(
                    p["feuilles"]["data"], ["/dev/sda1", "/dev/sdb1"]
                )
                self.assertEqual(p["vdev_types"], ["mirror"])
                self.assertEqual(p["sections"], [])

    def test_special_dedup_draid_et_remplacement(self):
        """Un vdev special ou dedup n'est pas un disque de données ; draid,
        spare-N et replacing-N sont des vdevs intérieurs, et seul le type
        des vdevs de données est compté."""
        a = Arbre(self)
        for nom in ("sda", "sdb", "sdc", "sdd", "sde", "sdf", "sdg"):
            a.disque(nom, rotatif=True)
        for nom in ("nvme0n1", "nvme1n1", "nvme2n1"):
            a.disque(nom, rotatif=False)
            a.partition(nom, nom + "p1")
        texte = (
            "  pool: big\n state: DEGRADED\nconfig:\n\n"
            "\tNAME                   STATE     READ WRITE CKSUM\n"
            "\tbig                    DEGRADED     0     0     0\n"
            "\t  draid2:4d:1s:7c-0    DEGRADED     0     0     0\n"
            "\t    /dev/sda           ONLINE       0     0     0\n"
            "\t    /dev/sdb           ONLINE       0     0     0\n"
            "\t    spare-2            DEGRADED     0     0     0\n"
            "\t      /dev/sdc         FAULTED      0     0     0\n"
            "\t      draid2-0-0       ONLINE       0     0     0\n"
            "\t    /dev/sdd           ONLINE       0     0     0\n"
            "\t  mirror-1             ONLINE       0     0     0\n"
            "\t    replacing-0        ONLINE       0     0     0\n"
            "\t      /dev/sde         ONLINE       0     0     0\n"
            "\t      /dev/sdf         ONLINE       0     0     0\n"
            "\t    /dev/sdg           ONLINE       0     0     0\n"
            "\tspecial\n"
            "\t  mirror-2             ONLINE       0     0     0\n"
            "\t    /dev/nvme0n1p1     ONLINE       0     0     0\n"
            "\t    /dev/nvme1n1p1     ONLINE       0     0     0\n"
            "\tdedup\n"
            "\t  /dev/nvme2n1p1       ONLINE       0     0     0\n"
            "\tspares\n"
            "\t  draid2-0-0           INUSE     currently in use\n"
            "\nerrors: No known data errors\n"
        )
        sorties = {
            CMD_LIST: (0, "big\t7000\t100\t6900\t1\t10\tDEGRADED\n"),
            CMD_STATUS: (0, texte),
        }
        z, _notes, _s = self.faits_zfs(
            a, FauxSysteme(sorties, binaires=("zpool",))
        )
        big = z["pools"]["big"]
        self.assertEqual(
            big["data_disks"],
            ["sda", "sdb", "sdc", "sdd", "sde", "sdf", "sdg"],
        )
        self.assertEqual(
            big["special_disks"], ["nvme0n1", "nvme1n1", "nvme2n1"]
        )
        self.assertEqual(big["media"], ["HDD"])
        self.assertTrue(big["has_special"])
        self.assertEqual(big["vdev_types"], ["draid2", "mirror"])
        self.assertEqual(sorted(set(big["unresolved_vdevs"])), ["draid2-0-0"])
        c = hpa.Conseils()
        hpa.analyser_zfs(z, {"some_avg": 20}, c)
        self.assertNotIn("special_vdev", [x["id"] for x in c.liste])

    def test_atime_sans_relatime(self):
        z = {
            "datasets": hpa.analyser_zfs_get(
                "tank/home\ttype\tfilesystem\t-\n"
                "tank/home\tatime\ton\tlocal\n"
                "tank/home\trelatime\toff\tdefault\n"
                "tank/logs\ttype\tfilesystem\t-\n"
                "tank/logs\tatime\ton\tlocal\n"
                "tank/logs\trelatime\ton\tlocal\n"
            )
        }
        c = hpa.Conseils()
        hpa.analyser_datasets(z, c)
        atime = [x for x in c.liste if x["id"] == "zfs_atime"]
        self.assertEqual(len(atime), 1)
        self.assertEqual(atime[0]["commands"], ["zfs set atime=off tank/home"])
        self.assertEqual(
            z["datasets_flagged"],
            [{"dataset": "tank/home", "property": "atime", "value": "on"}],
        )

    def test_plafond_des_conseils_de_datasets(self):
        texte = "".join(
            "tank/d%d\ttype\tfilesystem\t-\n"
            "tank/d%d\tcompression\toff\tlocal\n" % (i, i)
            for i in range(hpa.CONSEILS_DATASETS_MAX + 2)
        )
        z = {"datasets": hpa.analyser_zfs_get(texte)}
        c = hpa.Conseils()
        hpa.analyser_datasets(z, c)
        compression = [x for x in c.liste if x["id"] == "zfs_compression"]
        self.assertEqual(len(compression), hpa.CONSEILS_DATASETS_MAX)
        self.assertEqual(
            len(z["datasets_flagged"]), hpa.CONSEILS_DATASETS_MAX + 2
        )

    def test_noms_avec_espace_cites_dans_les_commandes(self):
        """ZFS admet une espace dans un nom ; `zfs set` prend plusieurs
        datasets : un nom non cité viserait un autre dataset."""
        z = {
            "datasets": hpa.analyser_zfs_get(
                "tank/vm data\ttype\tfilesystem\t-\n"
                "tank/vm data\tcompression\toff\tlocal\n"
                "tank/vm data\tatime\ton\tlocal\n"
                "tank/vm data\tsync\tdisabled\tlocal\n"
            ),
            "pools": {
                "my pool": dict(
                    pool(["sda"], ["HDD"]),
                    scrub="scrub in progress",
                    health="DEGRADED",
                    cap_pct=95,
                    latency_ms={"syncq_w": 50.0},
                )
            },
        }
        c = hpa.Conseils()
        hpa.analyser_zfs(z, {"some_avg": 20}, c)
        commandes = [cmd for x in c.liste for cmd in x["commands"]]
        for attendu in (
            "zfs set compression=lz4 'tank/vm data'",
            "zfs set atime=off 'tank/vm data'",
            "zfs set sync=standard 'tank/vm data'",
            "zpool status 'my pool'",
            "zpool status -v 'my pool'",
            "zfs list -o space -r 'my pool'",
            "zpool add 'my pool' log mirror <ssd-1> <ssd-2>",
            "zpool add 'my pool' special mirror <ssd-1> <ssd-2>",
            "zfs set special_small_blocks=16K 'my pool'",
        ):
            self.assertIn(attendu, commandes)

    def test_faits_lus_des_commandes(self):
        """pveversion, smartctl et /proc/stat nourrissent les faits ; un
        SMART FAILED, dans sa forme ATA, mène au conseil prioritaire."""
        a = hote_complet(self)
        sorties = {
            ("pveversion",): (0, "pve-manager/8.2.2 (running kernel)\n"),
            ("smartctl", "-n", "standby", "-H", "/dev/sda"): (
                8,
                "SMART overall-health self-assessment test result: FAILED!\n",
            ),
            ("smartctl", "-n", "standby", "-H", "/dev/nvme0n1"): (
                0,
                "SMART Health Status: OK\n",
            ),
        }
        systeme = FauxSysteme(
            sorties, binaires=("pveversion", "smartctl"), uid=0
        )
        code, sortie, _e, _s = lancer_main(
            self,
            a,
            ["--duration", "10", "--interval", "10", "--json"],
            systeme,
        )
        self.assertEqual(code, 0)
        donnees = json.loads(sortie)
        f = donnees["facts"]
        self.assertEqual(f["pve"], "pve-manager/8.2.2 (running kernel)")
        self.assertEqual(f["cores"], 2)
        self.assertEqual(f["disks"]["sda"]["smart"], "FAILED")
        self.assertEqual(f["disks"]["nvme0n1"]["smart"], "OK")
        self.assertFalse(
            any("not a Proxmox VE host" in n for n in donnees["notes"])
        )
        smart = [
            x for x in donnees["suggestions"] if x["id"] == "smart_failed"
        ]
        self.assertEqual(len(smart), 1)
        self.assertEqual(smart[0]["priority"], "high")
        self.assertIn("sda", smart[0]["text"])

    def test_sante_smart_veille_et_disques_ignores(self):
        """`-n standby` : un disque en veille n'est pas réveillé, et le
        rapport dit STANDBY ; une ouverture impossible (même bit du code)
        reste vide ; un disque virtuel ou non physique n'est pas
        interrogé."""
        disques = {
            "sda": info_disque("HDD"),
            "sdb": info_disque("HDD"),
            "sdc": info_disque("SSD"),
            "dm-0": info_disque("virtual", physique=False),
            "vda": info_disque("virtual"),
            "sdz": info_disque("HDD", physique=False),
        }

        def cmd(nom):
            return ("smartctl", "-n", "standby", "-H", "/dev/" + nom)

        systeme = FauxSysteme(
            {
                cmd("sda"): (2, "Device is in STANDBY mode, exit(2)\n"),
                cmd("sdb"): (2, "Smartctl open device: /dev/sdb failed\n"),
                cmd("sdc"): (
                    0,
                    "SMART overall-health self-assessment test result:"
                    " PASSED\n",
                ),
            },
            binaires=("smartctl",),
            uid=0,
        )
        hpa.sante_smart(systeme, disques)
        self.assertEqual(
            sorted(tuple(x) for x in systeme.appels),
            [cmd("sda"), cmd("sdb"), cmd("sdc")],
        )
        self.assertEqual(disques["sda"]["smart"], "STANDBY")
        self.assertEqual(disques["sdb"]["smart"], "")
        self.assertEqual(disques["sdc"]["smart"], "PASSED")

    def test_smartctl_ni_sans_root_ni_absent(self):
        a = hote_complet(self)
        for systeme in (
            FauxSysteme(binaires=("smartctl",), uid=1000),
            FauxSysteme(binaires=(), uid=0),
        ):
            _c, _o, _e, systeme = lancer_main(
                self, a, ["--duration", "10", "--interval", "10"], systeme
            )
            self.assertFalse(any(x[0] == "smartctl" for x in systeme.appels))


# ----------------------------------------------------------------------- #
# 30-33. Invités
# ----------------------------------------------------------------------- #
class TestInvites(unittest.TestCase):
    def test_noms(self):
        a = Arbre(self)
        a.ecrire(
            "/etc/pve/lxc/101.conf",
            "hostname: ct-web\n\n[snap1]\nhostname: old-name\n",
        )
        a.ecrire("/etc/pve/qemu-server/120.conf", "name: vm-demo\n")
        a.ecrire("/etc/pve/qemu-server/121.conf", "memory: 1024\n")
        noms = hpa.noms_invites(a.racine)
        self.assertEqual(noms["101"][:2], ("lxc", "ct-web"))
        self.assertEqual(noms["120"][:2], ("vm", "vm-demo"))
        self.assertEqual(noms["121"][1], "")

    def test_compteurs_cgroup(self):
        c = hpa.analyser_cgroup(
            {
                "cpu.stat": "usage_usec 5000000\nuser_usec 1\n",
                "memory.current": "1024\n",
                "memory.max": "max\n",
                "io.stat": "8:0 rbytes=10 wbytes=20\n259:0 rbytes=1 wbytes=2\n",
                "io.pressure": "some avg10=0.00 avg60=0.00 avg300=0.00"
                " total=77\n",
            }
        )
        self.assertEqual(c["cpu_usec"], 5000000)
        self.assertIsNone(c["mem_max"])
        self.assertEqual((c["io_rbytes"], c["io_wbytes"]), (11, 22))
        self.assertEqual(c["io_some_us"], 77)

    def test_mesure_et_invite_arrive_en_cours(self):
        a = hote_complet(self)

        def apres(k):
            ecrire_compteurs(a, k)
            if k == 2:
                base = "/sys/fs/cgroup/qemu.slice/130.scope/"
                a.ecrire(base + "cpu.stat", "usage_usec 0\n")
            if k == 3:
                base = "/sys/fs/cgroup/qemu.slice/130.scope/"
                a.ecrire(base + "cpu.stat", "usage_usec 1000000\n")

        systeme = FauxSysteme(apres_dormir=apres)
        echantillons, interrompu, _debut = hpa.echantillonner(
            a.racine,
            systeme,
            hpa.Blocs(a.racine),
            30,
            10.0,
            True,
            None,
            io.StringIO(),
        )
        self.assertFalse(interrompu)
        self.assertEqual(len(echantillons), 3)
        g = echantillons[0]["guests"]
        self.assertAlmostEqual(g["101"]["cpu"], 50.0)
        self.assertEqual(g["120"]["kind"], "vm")
        self.assertIsNone(g["101"]["mem_max"])
        self.assertNotIn("130", echantillons[1]["guests"])
        self.assertAlmostEqual(echantillons[2]["guests"]["130"]["cpu"], 10.0)

    def test_noms_dans_le_json(self):
        a = hote_complet(self)
        code, sortie, _e, _s = lancer_main(
            self, a, ["--duration", "20", "--interval", "10", "--json"]
        )
        self.assertEqual(code, 0)
        donnees = json.loads(sortie)
        noms = {g["vmid"]: g["name"] for g in donnees["guests"]}
        self.assertEqual(noms, {"101": "ct-web", "120": "vm-demo"})
        self.assertIsNone(donnees["guests_skipped"])

    def test_raisons_de_ne_pas_mesurer(self):
        for options, attendu, kw in (
            ([], "cgroup_v1", {"cgroup_v2": False}),
            ([], "no_pve", {"pve": False}),
            (["--no-guests"], "disabled", {}),
        ):
            with self.subTest(attendu=attendu):
                a = hote_complet(self, **kw)
                code, sortie, _e, _s = lancer_main(
                    self,
                    a,
                    ["--duration", "10", "--interval", "10", "--json"]
                    + options,
                )
                self.assertEqual(code, 0)
                donnees = json.loads(sortie)
                self.assertIsNone(donnees["guests"])
                self.assertEqual(donnees["guests_skipped"], attendu)
        a = hote_complet(self, cgroup_v2=False)
        _c, sortie, _e, _s = lancer_main(
            self, a, ["--duration", "10", "--interval", "10", "--json"]
        )
        self.assertTrue(
            any("cgroup v1" in n for n in json.loads(sortie)["notes"])
        )
        a = hote_complet(self)
        _c, texte, _e, _s = lancer_main(
            self, a, ["--duration", "10", "--interval", "10", "--no-guests"]
        )
        self.assertNotIn("GUESTS", texte)

    def test_conseils_de_configuration_de_vm(self):
        noms = {
            "120": (
                "vm",
                "vm-demo",
                "name: vm-demo\nsata1: local:vm-120-disk-1,size=8G\n"
                "scsi0: local-zfs:vm-120-disk-0,cache=writeback,size=32G\n"
                "ide2: local:iso/example.iso,media=cdrom\ncpu: kvm64\n",
            ),
            "101": ("lxc", "ct-web", "hostname: ct-web\ncpu: kvm64\n"),
        }
        c = hpa.Conseils()
        hpa.conseils_config_vm(noms, c)
        ids = sorted(x["id"] for x in c.liste)
        self.assertEqual(
            ids, ["vm_bus", "vm_cache", "vm_cpu_type", "vm_iothread"]
        )
        cache = [x for x in c.liste if x["id"] == "vm_cache"][0]
        self.assertIn("cache=none", cache["commands"][0])
        self.assertTrue(all("ide2" not in x["text"] for x in c.liste))


# ----------------------------------------------------------------------- #
# 34-35. Durée, intervalle, arguments
# ----------------------------------------------------------------------- #
class TestDuree(unittest.TestCase):
    def test_formes_admises(self):
        for texte, attendu in (
            ("90", 90),
            ("90.5", 90),
            ("30s", 30),
            ("10m", 600),
            ("10min", 600),
            ("2h", 7200),
            ("1h30m", 5400),
            (" 1H ", 3600),
        ):
            with self.subTest(texte=texte):
                self.assertEqual(hpa.parse_duration(texte), attendu)

    def test_formes_refusees(self):
        for texte in ("", "soon", "-5", "10m; touch x", "1d", "m"):
            with self.subTest(texte=texte):
                with self.assertRaises(ValueError):
                    hpa.parse_duration(texte)

    def test_bornes(self):
        a = hote_complet(self)
        for duree in ("0", "8d", "604801"):
            with self.subTest(duree=duree):
                with mock.patch("sys.stderr", io.StringIO()):
                    code, _o, _e, systeme = lancer_main(
                        self, a, ["--duration", duree], compteurs=False
                    )
                self.assertEqual(code, 2)
                self.assertEqual(systeme.dormis, [])

    def test_intervalle(self):
        self.assertEqual(hpa.choisir_intervalle(60, None), (5.0, None))
        self.assertEqual(hpa.choisir_intervalle(3, None)[0], 3.0)
        self.assertEqual(hpa.choisir_intervalle(60, 0.2)[0], 1.0)
        self.assertEqual(hpa.choisir_intervalle(60, 600)[0], 60.0)
        intervalle, note = hpa.choisir_intervalle(7 * 86400, None)
        self.assertLessEqual(7 * 86400 / intervalle, hpa.ECHANTILLONS_MAX)
        self.assertIn("raised", note)
        intervalle, note = hpa.choisir_intervalle(7 * 86400, 1.0)
        self.assertGreaterEqual(intervalle, 210.0)
        self.assertLessEqual(7 * 86400 / intervalle, hpa.ECHANTILLONS_MAX)
        self.assertIn("raised from 1 s", note)


# ----------------------------------------------------------------------- #
# 36-41. Boucle, Ctrl-C, priorité, coût, progression
# ----------------------------------------------------------------------- #
class TestBoucle(unittest.TestCase):
    def test_ctrl_c_garde_le_rapport(self):
        a = hote_complet(self)
        code, sortie, erreur, _s = lancer_main(
            self,
            a,
            ["--duration", "60", "--interval", "10", "--json"],
            FauxSysteme(interrompre_dormir=3),
        )
        self.assertEqual(code, 0)
        donnees = json.loads(sortie)
        self.assertEqual(donnees["samples"], 2)
        self.assertTrue(donnees["interrupted"])
        self.assertIn("interrupted", erreur)

    def test_ctrl_c_avant_le_premier_echantillon(self):
        a = hote_complet(self)
        code, sortie, _e, _s = lancer_main(
            self,
            a,
            ["--duration", "60", "--interval", "10"],
            FauxSysteme(interrompre_dormir=1),
        )
        self.assertEqual(code, 0)
        self.assertIn("No sample taken", sortie)
        self.assertIn("no sample", sortie)

    def test_ctrl_c_avant_le_premier_echantillon_json(self):
        a = hote_complet(self)
        code, sortie, _e, _s = lancer_main(
            self,
            a,
            ["--duration", "60", "--interval", "10", "--json"],
            FauxSysteme(interrompre_dormir=1),
        )
        self.assertEqual(code, 0)
        donnees = json.loads(sortie)
        self.assertEqual(donnees["samples"], 0)
        self.assertEqual(donnees["verdicts"], {})

    def test_ctrl_c_pendant_les_faits(self):
        a = hote_complet(self)
        code, _o, erreur, systeme = lancer_main(
            self,
            a,
            ["--duration", "60"],
            FauxSysteme(interrompre_lancer=True),
        )
        self.assertEqual(code, 130)
        self.assertEqual(systeme.dormis, [])

    def test_ctrl_c_au_premier_instantane(self):
        a = hote_complet(self)
        systeme = FauxSysteme()
        systeme.horloge = mock.Mock(side_effect=KeyboardInterrupt)
        code, _o, erreur, _s = lancer_main(
            self, a, ["--duration", "60"], systeme
        )
        self.assertEqual(code, 130)
        self.assertIn("Interrupted", erreur)

    def test_priorite_baissee_par_le_systeme_injecte(self):
        a = hote_complet(self)
        _c, _o, _e, systeme = lancer_main(
            self, a, ["--duration", "10", "--interval", "10"]
        )
        self.assertEqual(systeme.priorite, 1)
        sans = FauxSysteme()
        with mock.patch.object(hpa.os, "nice") as nice:
            hpa.main(
                ["--root", a.racine, "--duration", "10"],
                systeme=sans,
                sortie=io.StringIO(),
                erreur=io.StringIO(),
                priorite_basse=False,
            )
        self.assertEqual(sans.priorite, 0)
        self.assertFalse(nice.called)

    def test_fonction_de_priorite_ne_casse_jamais(self):
        appels = []
        hpa.baisser_priorite(
            nice=appels.append,
            which=lambda nom: None,
            run=lambda *a, **k: appels.append("run"),
            pid=4242,
        )
        self.assertEqual(appels, [10])

        def nice_refuse(_n):
            raise OSError("refused")

        for erreur in (OSError("x"), subprocess.TimeoutExpired("ionice", 5)):
            with self.subTest(erreur=type(erreur).__name__):
                vus = []

                def run(argv, **kw):
                    vus.append((argv, kw))
                    raise erreur

                hpa.baisser_priorite(
                    nice=nice_refuse,
                    which=lambda nom: "/usr/bin/ionice",
                    run=run,
                    pid=4242,
                )
                self.assertEqual(
                    vus[0][0], ["/usr/bin/ionice", "-c3", "-p", "4242"]
                )
                self.assertIn("timeout", vus[0][1])

    def test_cout(self):
        a = hote_complet(self)
        code, sortie, _e, _s = lancer_main(
            self,
            a,
            ["--duration", "10", "--interval", "10"],
            FauxSysteme(temps=(1.00, 1.12)),
        )
        self.assertEqual(code, 0)
        self.assertIn("used 0.12 s of processor", sortie)
        _c, sortie, _e, _s = lancer_main(
            self,
            a,
            ["--duration", "10", "--interval", "10", "--json"],
            FauxSysteme(temps=(1.00, 1.12)),
        )
        self.assertEqual(json.loads(sortie)["cost_cpu_s"], 0.12)

    def test_progression_sur_stderr_sans_terminal(self):
        a = hote_complet(self)
        _c, _o, erreur, _s = lancer_main(
            self, a, ["--duration", "130", "--interval", "10", "--json"]
        )
        self.assertEqual(len(re.findall(r"sample \d+: CPU", erreur)), 2)
        _c, _o, erreur, _s = lancer_main(
            self, a, ["--duration", "300", "--interval", "100", "--json"]
        )
        self.assertEqual(len(re.findall(r"sample \d+: CPU", erreur)), 3)

    def test_tube_rompu_sans_trace(self):
        class Rompu(io.StringIO):
            def write(self, _texte):
                raise BrokenPipeError

        a = hote_complet(self)
        for cote in ("sortie", "erreur"):
            with self.subTest(cote=cote):
                flux = {"sortie": io.StringIO(), "erreur": io.StringIO()}
                flux[cote] = Rompu()
                systeme = FauxSysteme(
                    apres_dormir=lambda k: ecrire_compteurs(a, k)
                )
                code = hpa.main(
                    [
                        "--root",
                        a.racine,
                        "--duration",
                        "120",
                        "--interval",
                        "60",
                    ],
                    systeme=systeme,
                    priorite_basse=False,
                    **flux,
                )
                self.assertEqual(code, 0)


# ----------------------------------------------------------------------- #
# 42-45. Sorties
# ----------------------------------------------------------------------- #
class TestSorties(unittest.TestCase):
    def test_json(self):
        a = hote_complet(self)
        code, sortie, erreur, _s = lancer_main(
            self, a, ["--duration", "30", "--interval", "10", "--json"]
        )
        self.assertEqual(code, 0)
        donnees = json.loads(sortie)
        self.assertEqual(list(donnees), list(hpa.CLES_JSON))
        self.assertEqual(
            set(donnees),
            {
                "schema",
                "tool",
                "host",
                "started",
                "duration_s",
                "interval_s",
                "samples",
                "interrupted",
                "cost_cpu_s",
                "notes",
                "facts",
                "cpu",
                "memory",
                "disks",
                "io_psi",
                "network",
                "zfs",
                "guests",
                "guests_skipped",
                "verdicts",
                "ssd",
                "suggestions",
            },
        )
        self.assertEqual(donnees["schema"], 1)
        self.assertEqual(donnees["tool"], "host_perf_audit")
        self.assertEqual(donnees["samples"], 3)
        self.assertEqual(donnees["duration_s"], 30.0)
        self.assertEqual(
            set(donnees["verdicts"]), {"cpu", "memory", "disks", "network"}
        )
        for v in donnees["verdicts"].values():
            self.assertIn(v["level"], ("ok", "watch", "limiting"))
        self.assertIn(
            donnees["ssd"]["answer"],
            ("yes", "not_yet", "no", "not_applicable"),
        )
        for c in donnees["suggestions"]:
            self.assertEqual(set(c), {"priority", "id", "text", "commands"})
        sda = donnees["disks"]["sda"]
        self.assertEqual(sda["kind"], "HDD")
        self.assertAlmostEqual(sda["util_avg"], 80.0)
        self.assertEqual(sda["level"], "limiting")
        self.assertEqual(donnees["ssd"]["answer"], "yes")
        self.assertAlmostEqual(donnees["cpu"]["busy_avg"], 50.0)
        self.assertAlmostEqual(donnees["io_psi"]["some_avg"], 20.0)
        self.assertEqual(
            donnees["facts"]["disks"]["sda"]["model"], "EXAMPLE-HDD-4T"
        )
        self.assertIn("eno1", donnees["network"])
        self.assertIn(hpa.GROUPE_INVITES, donnees["network"])
        self.assertNotIn("Measuring", sortie)
        self.assertIn("Measuring", erreur)

    def test_texte(self):
        a = hote_complet(self)
        code, sortie, _e, _s = lancer_main(
            self, a, ["--duration", "30", "--interval", "10"]
        )
        self.assertEqual(code, 0)
        for section in (
            "PROCESSOR",
            "MEMORY",
            "DISKS",
            "ZFS",
            "NETWORK",
            "GUESTS",
            "VERDICT",
            "ARE SSD DISKS JUSTIFIED?",
            "SUGGESTED SETTINGS",
            "Short measurement",
        ):
            self.assertIn(section, sortie)
        self.assertNotIn("--apply", sortie)
        self.assertNotIn("\x1b[", sortie)
        self.assertIn("ct-web", sortie)
        lignes = sortie.splitlines()
        commandes = [x for x in lignes if x.strip().startswith("$ ")]
        self.assertTrue(commandes)

    def test_chaque_commande_sur_sa_ligne(self):
        r = {
            "suggestions": [
                {
                    "priority": "medium",
                    "id": "swappiness",
                    "text": "t",
                    "commands": ["sysctl -w vm.swappiness=10", "echo x"],
                }
            ],
            "duration_s": 4000,
        }
        lignes = hpa._texte_conseils(r)
        self.assertIn("       $ sysctl -w vm.swappiness=10", lignes)
        self.assertIn("       $ echo x", lignes)

    def test_csv(self):
        a = hote_complet(self)
        chemin_csv = os.path.join(a.racine, "echantillons.csv")

        def apres(k):
            ecrire_compteurs(a, k)
            if k == 2:
                with open(a.chemin("/proc/diskstats")) as f:
                    texte = f.read()
                a.ecrire(
                    "/proc/diskstats",
                    "".join(
                        x
                        for x in texte.splitlines(True)
                        if " nvme0n1 " not in x
                    ),
                )

        code, _o, _e, _s = lancer_main(
            self,
            a,
            ["--duration", "30", "--interval", "10", "--csv", chemin_csv],
            FauxSysteme(apres_dormir=apres),
        )
        self.assertEqual(code, 0)
        import csv

        with open(chemin_csv, newline="") as f:
            lignes = list(csv.reader(f))
        entete = lignes[0]
        self.assertEqual(
            entete,
            [
                "time",
                "epoch",
                "cpu_busy",
                "iowait",
                "steal",
                "psi_cpu",
                "psi_io_some",
                "psi_io_full",
                "psi_mem",
                "mem_available_mb",
                "swap_in_kib_s",
                "swap_out_kib_s",
                "arc_mb",
                "arc_hit",
                "nvme0n1_util",
                "sda_util",
                "nvme0n1_r_await",
                "sda_r_await",
                "nvme0n1_w_await",
                "sda_w_await",
            ],
        )
        self.assertEqual(len(lignes), 4)
        self.assertTrue(all(len(x) == len(entete) for x in lignes))
        self.assertEqual(lignes[2][entete.index("nvme0n1_util")], "")
        self.assertRegex(lignes[1][0], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]")
        self.assertTrue(lignes[1][1].isdigit())

    def test_csv_non_inscriptible(self):
        a = hote_complet(self)
        code, _o, erreur, systeme = lancer_main(
            self,
            a,
            ["--duration", "30", "--csv", a.chemin("/absent/x/y.csv")],
        )
        self.assertEqual(code, 2)
        self.assertIn("CSV", erreur)
        self.assertEqual(systeme.dormis, [])
        self.assertEqual(systeme.appels, [])

    def test_fumee_dans_un_processus_enfant(self):
        """Le vrai Systeme dans un enfant, sous un PATH vide : `--root` ne
        redirige que les lectures, et ni zpool, ni zfs, ni pveversion, ni
        smartctl, ni ionice de la machine de test ne sont atteints."""
        a = hote_complet(self)
        vide = tempfile.mkdtemp(prefix="test-hpa-path-")
        self.addCleanup(shutil.rmtree, vide, True)
        fini = subprocess.run(
            [
                sys.executable,
                "-I",
                FICHIER,
                "--root",
                a.racine,
                "--duration",
                "1",
                "--interval",
                "1",
                "--json",
                "--no-guests",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            env={"PATH": vide, "LANG": "C"},
        )
        self.assertEqual(fini.returncode, 0, fini.stderr)
        donnees = json.loads(fini.stdout)
        self.assertEqual(donnees["schema"], 1)
        self.assertEqual(donnees["facts"]["pve"], "")
        self.assertIn(
            "not a Proxmox VE host (pveversion not found)", donnees["notes"]
        )
        self.assertEqual((donnees["zfs"] or {}).get("pools", {}), {})

    def test_top_limite_les_invites(self):
        a = hote_complet(self)
        code, sortie, _e, _s = lancer_main(
            self, a, ["--duration", "20", "--interval", "10", "--top", "1"]
        )
        self.assertEqual(code, 0)
        lignes = sortie.splitlines()
        debut = next(i for i, x in enumerate(lignes) if x.startswith("GUESTS"))
        fin = lignes.index("", debut)
        section = lignes[debut:fin]
        self.assertIn("the 1 busiest", section[0])
        noms = [x for x in section if "ct-web" in x or "vm-demo" in x]
        self.assertEqual(len(noms), 1)

    def test_aide(self):
        sortie = io.StringIO()
        with mock.patch("sys.stdout", sortie):
            self.assertEqual(hpa.main(["--help"]), 0)
        self.assertIn("--duration", sortie.getvalue())
        self.assertNotIn("--root", sortie.getvalue())
        self.assertNotIn("--apply", sortie.getvalue())


# ----------------------------------------------------------------------- #
# 45. Robustesse : CSV en panne, commandes sans réponse, mémoire bornée
# ----------------------------------------------------------------------- #
class FichierQuiLache:
    """Un fichier dont l'écriture lève OSError (disque plein) à partir de
    la `bonnes + 1`-ième ; sa fermeture échoue aussi tant qu'une écriture
    a échoué, comme un tampon qui ne se vide plus."""

    def __init__(self, bonnes=0):
        self.bonnes = bonnes
        self.lignes = []
        self.echec = False
        self.ferme = False

    def write(self, texte):
        if len(self.lignes) >= self.bonnes:
            self.echec = True
            raise OSError(28, "No space left on device")
        self.lignes.append(texte)
        return len(texte)

    def flush(self):
        if self.echec:
            raise OSError(28, "No space left on device")

    def close(self):
        self.ferme = True
        if self.echec:
            raise OSError(28, "No space left on device")


class TestCsvEnPanne(unittest.TestCase):
    def lancer(self, fichier, args=("--json",)):
        a = hote_complet(self)
        chemin_csv = os.path.join(a.racine, "x.csv")
        vrai_open = open

        def ouvrir(chemin, mode="r", *reste, **nommes):
            if chemin == chemin_csv:
                self.assertEqual(mode, "w")
                return fichier
            return vrai_open(chemin, mode, *reste, **nommes)

        with mock.patch.object(hpa, "open", ouvrir, create=True):
            return lancer_main(
                self,
                a,
                ["--duration", "30", "--interval", "10", "--csv", chemin_csv]
                + list(args),
            )

    def test_panne_en_cours_de_mesure_le_rapport_sort(self):
        fichier = FichierQuiLache(bonnes=2)
        code, sortie, erreur, systeme = self.lancer(fichier)
        self.assertEqual(code, 0)
        donnees = json.loads(sortie)
        self.assertEqual(donnees["samples"], 3)
        self.assertEqual(len(systeme.dormis), 3)
        self.assertEqual(erreur.count("CSV disabled"), 1)
        self.assertTrue(
            any(
                "CSV file" in n and "incomplete" in n for n in donnees["notes"]
            )
        )
        self.assertEqual(len(fichier.lignes), 2)
        self.assertTrue(fichier.ferme)

    def test_panne_des_l_entete(self):
        fichier = FichierQuiLache(bonnes=0)
        code, sortie, erreur, _s = self.lancer(fichier, args=())
        self.assertEqual(code, 0)
        self.assertIn("VERDICT", sortie)
        self.assertNotIn("Samples written to", sortie)
        self.assertIn("incomplete", sortie)
        self.assertEqual(erreur.count("CSV disabled"), 1)

    def test_panne_a_la_fermeture_seulement(self):
        class FermetureEnPanne(FichierQuiLache):
            def close(self):
                self.ferme = True
                raise OSError(5, "Input/output error")

        fichier = FermetureEnPanne(bonnes=100)
        code, sortie, erreur, _s = self.lancer(fichier)
        self.assertEqual(code, 0)
        self.assertEqual(len(fichier.lignes), 4)
        self.assertTrue(
            any("incomplete" in n for n in json.loads(sortie)["notes"])
        )
        self.assertEqual(erreur.count("CSV disabled"), 1)

    def test_la_mesure_continue_sans_le_csv(self):
        a = hote_complet(self)
        erreur = io.StringIO()
        ecrivain = hpa.EcrivainCsv(FichierQuiLache(bonnes=1), ["sda"], erreur)
        systeme = FauxSysteme(apres_dormir=lambda k: ecrire_compteurs(a, k))
        echantillons, interrompu, _d = hpa.echantillonner(
            a.racine,
            systeme,
            hpa.Blocs(a.racine),
            40,
            10,
            False,
            ecrivain,
            erreur,
        )
        self.assertEqual(len(echantillons), 4)
        self.assertFalse(interrompu)
        self.assertIn("No space left", ecrivain.panne)
        self.assertEqual(erreur.getvalue().count("CSV disabled"), 1)


class FauxPopen:
    """Un enfant qui ne répond pas : communicate dépasse son délai, et
    l'attente après KILL aussi, comme un processus en sommeil non
    interruptible."""

    def __init__(self, sortie=None, immortel=True):
        self.sortie = sortie
        self.immortel = immortel
        self.returncode = None
        self.tue = False
        self.attentes = []
        self.stdout = io.StringIO()
        self.stderr = None

    def __call__(self, argv, **options):
        self.argv = argv
        self.options = options
        return self

    def communicate(self, timeout=None):
        self.attentes.append(("communicate", timeout))
        if self.sortie is None:
            raise subprocess.TimeoutExpired(self.argv, timeout)
        self.returncode = 0
        return self.sortie, None

    def kill(self):
        self.tue = True

    def wait(self, timeout=None):
        self.attentes.append(("wait", timeout))
        if self.immortel:
            raise subprocess.TimeoutExpired(self.argv, timeout)
        self.returncode = -9
        return -9


class TestRechercheBinaires(unittest.TestCase):
    """zpool, zfs et smartctl vivent dans /usr/sbin ou /sbin, hors du PATH
    d'un compte non root : ces dossiers sont ajoutés à la recherche et la
    commande est lancée par son chemin absolu."""

    def executable(self, dossier, nom):
        p = os.path.join(dossier, nom)
        with open(p, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n")
        os.chmod(p, 0o755)
        return p

    def dossiers(self, n):
        res = []
        for _i in range(n):
            d = tempfile.mkdtemp(prefix="test-hpa-bin-")
            self.addCleanup(shutil.rmtree, d, True)
            res.append(d)
        return res

    def test_dossiers_d_administration_par_defaut(self):
        self.assertEqual(hpa.CHEMINS_ADMIN, ("/usr/sbin", "/sbin"))

    def test_trouve_hors_du_path_herite(self):
        path, admin = self.dossiers(2)
        attendu = self.executable(admin, "zpool")
        with mock.patch.object(hpa, "CHEMINS_ADMIN", (admin,)):
            self.assertEqual(hpa.trouver_binaire("zpool", path), attendu)
            self.assertEqual(hpa.trouver_binaire("zpool", ""), attendu)
            self.assertIsNone(hpa.trouver_binaire("smartctl", path))

    def test_le_path_herite_passe_d_abord(self):
        path, admin = self.dossiers(2)
        attendu = self.executable(path, "zpool")
        self.executable(admin, "zpool")
        with mock.patch.object(hpa, "CHEMINS_ADMIN", (admin,)):
            self.assertEqual(hpa.trouver_binaire("zpool", path), attendu)

    def test_path_herite_par_defaut(self):
        path, admin = self.dossiers(2)
        attendu = self.executable(admin, "zpool")
        with mock.patch.object(hpa, "CHEMINS_ADMIN", (admin,)):
            with mock.patch.dict(os.environ, {"PATH": path}):
                self.assertEqual(hpa.trouver_binaire("zpool"), attendu)
            with mock.patch.dict(os.environ, clear=True):
                self.assertEqual(hpa.trouver_binaire("zpool"), attendu)

    def test_systeme_lance_le_chemin_absolu(self):
        path, admin = self.dossiers(2)
        attendu = self.executable(admin, "zpool")
        faux = FauxPopen(sortie="tank\n")
        systeme = hpa.Systeme(popen=faux)
        with mock.patch.object(hpa, "CHEMINS_ADMIN", (admin,)):
            with mock.patch.dict(os.environ, {"PATH": path}):
                self.assertEqual(systeme.which("zpool"), attendu)
                self.assertEqual(
                    systeme.lancer(["zpool", "list", "-H"], 5),
                    (0, "tank\n"),
                )
        self.assertEqual(faux.argv, [attendu, "list", "-H"])

    def test_introuvable_rien_n_est_lance(self):
        (path,) = self.dossiers(1)
        faux = FauxPopen(sortie="")
        systeme = hpa.Systeme(popen=faux)
        with mock.patch.object(hpa, "CHEMINS_ADMIN", (path,)):
            with mock.patch.dict(os.environ, {"PATH": path}):
                self.assertEqual(systeme.lancer(["zpool", "list"]), (None, ""))
        self.assertFalse(hasattr(faux, "argv"))


class TestCommandeBornee(unittest.TestCase):
    def test_enfant_sans_reponse_abandonne_apres_une_attente_bornee(self):
        faux = FauxPopen()
        systeme = hpa.Systeme(popen=faux)
        argv = [sys.executable, "status"]
        self.assertEqual(systeme.lancer(argv, 20), (None, ""))
        self.assertTrue(faux.tue)
        self.assertEqual(
            faux.attentes,
            [("communicate", 20), ("wait", hpa.ATTENTE_KILL_S)],
        )
        self.assertTrue(faux.stdout.closed)
        self.assertEqual(systeme.sans_reponse, [(argv, 20)])

    def test_reponse_dans_le_delai(self):
        faux = FauxPopen(sortie="ONLINE\n")
        systeme = hpa.Systeme(popen=faux)
        self.assertEqual(
            systeme.lancer([sys.executable, "x"], 5), (0, "ONLINE\n")
        )
        self.assertFalse(faux.tue)
        self.assertEqual(faux.attentes, [("communicate", 5)])
        self.assertEqual(faux.options["stdin"], subprocess.DEVNULL)
        self.assertEqual(systeme.sans_reponse, [])

    def test_note_du_rapport(self):
        a = hote_complet(self)
        systeme = FauxSysteme(
            {("pveversion",): (0, "pve-manager/8.2.2\n")},
            binaires=("zpool", "pveversion"),
            muettes=(CMD_LIST,),
        )
        code, sortie, _e, _s = lancer_main(
            self,
            a,
            ["--duration", "10", "--interval", "10", "--json"],
            systeme,
        )
        self.assertEqual(code, 0)
        notes = json.loads(sortie)["notes"]
        self.assertTrue(
            any(
                n.startswith("zpool list -H")
                and "did not answer within 20 s" in n
                for n in notes
            ),
            notes,
        )


class TestMemoireBornee(unittest.TestCase):
    """Sur un hyperviseur chargé, les interfaces d'invités et les volumes
    zd se comptent par centaines : un échantillon garde une taille bornée
    par les interfaces et disques de l'hôte."""

    def instantanes(self, k):
        net = {"eno1": (1024 * k, 0, 0, 0)}
        disques = {"sda": compteurs_disque(10 * k, 10 * k, 0, 0, 100 * k)}
        for i in range(100):
            for prefixe in ("tap", "fwbr", "fwpr", "fwln"):
                net["%s%di0" % (prefixe, 100 + i)] = (1024 * k, 0, k, 0)
        for i in range(200):
            disques["zd%d" % (16 * i)] = compteurs_disque(
                k, k, 0, 0, 100 * k * (i % 2)
            )
        return instant(10 * k, net=net, disks=disques)

    def test_un_echantillon_ne_grossit_pas_avec_les_invites(self):
        types = {"sda": "HDD"}
        types.update({"zd%d" % (16 * i): "virtual" for i in range(200)})
        cumul = hpa.CumulVirtuels(FauxBlocs(types))
        echantillons = []
        for k in range(1, 4):
            r = hpa.taux(self.instantanes(k - 1), self.instantanes(k))
            cumul.retirer(r)
            echantillons.append(r)
            self.assertEqual(sorted(r["net"]), ["eno1", hpa.GROUPE_INVITES])
            self.assertEqual(list(r["disks"]), ["sda"])
            groupe = r["net"][hpa.GROUPE_INVITES]
            self.assertAlmostEqual(groupe["rx_kib_s"], 400 / 10.0)
            self.assertEqual(groupe["errors"], 400)
        self.assertEqual(len(cumul.cumuls), 200)
        self.assertEqual(cumul.cumuls["zd16"]["n"], 3)
        res = hpa.analyser_disques(
            echantillons, faits(), FauxBlocs(types), hpa.Conseils(), cumul
        )
        self.assertNotIn("zd0", res)
        self.assertAlmostEqual(res["zd16"]["util_avg"], 1.0)
        self.assertIsNone(res["zd16"]["util_p95"])
        self.assertIsNone(res["zd16"]["level"])
        self.assertEqual(len(res), 101)

    def test_la_boucle_resume_les_volumes_zd(self):
        a = hote_complet(self)
        a.disque("zd0", physique=False)

        def zd(k):
            with open(a.chemin("/proc/diskstats"), "a") as f:
                f.write(
                    ligne_disque(
                        "zd0", [k, 0, 8 * k, k, 0, 0, 0, 0, 0, 500 * k, 0]
                    )
                )

        zd(0)
        systeme = FauxSysteme(
            apres_dormir=lambda k: (ecrire_compteurs(a, k), zd(k))
        )
        blocs = hpa.Blocs(a.racine)
        cumul = hpa.CumulVirtuels(blocs)
        echantillons, _i, _d = hpa.echantillonner(
            a.racine,
            systeme,
            blocs,
            20,
            10,
            False,
            None,
            io.StringIO(),
            cumul,
        )
        self.assertEqual(len(echantillons), 2)
        self.assertFalse(any("zd0" in r["disks"] for r in echantillons))
        self.assertTrue(all("sda" in r["disks"] for r in echantillons))
        self.assertEqual(cumul.cumuls["zd0"]["n"], 2)
        self.assertAlmostEqual(cumul.lignes()["zd0"]["util_avg"], 5.0)

    def test_le_groupe_d_invites_reste_une_ligne_d_invites(self):
        """Les erreurs comptées sur les interfaces d'invités ne relèvent
        jamais le verdict du réseau."""
        r = hpa.taux(self.instantanes(0), self.instantanes(1))
        res, verdict = hpa.analyser_reseau([r], Arbre(self).racine)
        self.assertEqual(res[hpa.GROUPE_INVITES]["kind"], "guest")
        self.assertEqual(res[hpa.GROUPE_INVITES]["errors"], 400)
        self.assertEqual(res[hpa.GROUPE_INVITES]["level"], "ok")
        self.assertEqual(verdict["level"], "ok")


# ----------------------------------------------------------------------- #
# 46. Fichier unique, Python 3.7
# ----------------------------------------------------------------------- #
def imbrications_pep701(source):
    """Chaînes imbriquées dans une f-string avec le même guillemet — légal
    seulement depuis Python 3.12 (PEP 701)."""
    fautes = []
    pile = []
    debut_f = getattr(tokenize, "FSTRING_START", None)
    fin_f = getattr(tokenize, "FSTRING_END", None)
    if debut_f is None:
        return fautes
    for jeton in tokenize.generate_tokens(io.StringIO(source).readline):
        if jeton.type in (debut_f, tokenize.STRING):
            guillemet = jeton.string.lstrip("rRbBuUfF")
            if pile and any(guillemet.startswith(g) for g in pile):
                fautes.append(jeton.start)
            if jeton.type == debut_f:
                pile.append(guillemet)
        elif jeton.type == fin_f:
            pile.pop()
    return fautes


STDLIB_37 = {
    "__future__",
    "argparse",
    "csv",
    "datetime",
    "glob",
    "json",
    "math",
    "os",
    "re",
    "shlex",
    "shutil",
    "socket",
    "subprocess",
    "sys",
    "time",
}


class TestFichierUnique(unittest.TestCase):
    def setUp(self):
        with open(FICHIER, encoding="utf-8") as f:
            self.source = f.read()
        self.arbre = ast.parse(self.source)

    def test_syntaxe_37(self):
        ast.parse(self.source, feature_version=(3, 7))
        self.assertEqual(imbrications_pep701(self.source), [])

    def test_api_posterieures_a_37(self):
        for motif in (
            r"\.removeprefix\(",
            r"\.removesuffix\(",
            r"shlex\.join",
            r"math\.prod",
            r"cached_property",
            r"functools\.cache\b",
            r"zoneinfo",
            r"importlib\.metadata",
            r"""f["'][^"'\n]*\{[^}]*=\}""",
        ):
            with self.subTest(motif=motif):
                self.assertIsNone(re.search(motif, self.source))

    def test_imports_de_la_bibliotheque_standard_seulement(self):
        modules = set()
        for noeud in ast.walk(self.arbre):
            if isinstance(noeud, ast.Import):
                modules.update(a.name.split(".")[0] for a in noeud.names)
            elif isinstance(noeud, ast.ImportFrom):
                self.assertEqual(noeud.level, 0)
                modules.add((noeud.module or "").split(".")[0])
        self.assertLessEqual(modules, STDLIB_37)
        self.assertFalse(any(m.startswith("script") for m in modules))
        self.assertNotIn("todo_i18n", self.source)

    def test_aucun_travail_a_l_import(self):
        """Le menu importe le module pour valider une durée : au niveau du
        module, rien que des définitions, la docstring et le garde
        `__main__`."""
        permis = (
            ast.Import,
            ast.ImportFrom,
            ast.Assign,
            ast.FunctionDef,
            ast.ClassDef,
        )
        for noeud in self.arbre.body[1:-1]:
            self.assertIsInstance(noeud, permis, ast.dump(noeud)[:80])
        self.assertIsInstance(self.arbre.body[-1], ast.If)

    def test_lecture_seule(self):
        """Aucune écriture hors du CSV demandé : pas d'--apply, aucun
        open() en écriture ailleurs."""
        self.assertNotIn("--apply", self.source)
        ouvertures = re.findall(r"open\([^)]*\"w\"", self.source)
        self.assertEqual(len(ouvertures), 1)

    def test_entete_et_executable(self):
        self.assertTrue(self.source.startswith("#!/usr/bin/env python3\n"))
        self.assertIn("TechnoLibre", self.source.splitlines()[1])
        self.assertTrue(os.access(FICHIER, os.X_OK))


if __name__ == "__main__":
    unittest.main()
