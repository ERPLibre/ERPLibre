#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un volume Proxmox n'est libéré que s'il se PROUVE orphelin.

Deux modes de défaillance, une même racine : une liste de VM qu'on n'a pas
lue, prise pour une liste vide.

- « qm list » en échec, lu comme [], rend tous les volumes orphelins, et un
  « o » les libère tous.
- Les volumes viennent de TOUS les stockages d'images, dont les stockages
  partagés, qui portent aussi les disques des VM des autres nœuds. Les
  confronter au seul « qm list » du nœud courant fait passer ces disques
  pour orphelins.

Ce que ces épreuves tiennent : la liste de référence est celle de toute la
grappe, jointe à celle du nœud ; l'une ou l'autre illisible, ou la liste
des volumes, rien n'est offert, et le refus montre la commande à rejouer
avec son code et la raison qu'elle donne ; seul un disque de VM est
offert, jamais une sauvegarde, un ISO ou un gabarit ; chaque
« pvesm free » est lu, et un échec est nommé. Les autres lecteurs
de la liste du nœud distinguent « illisible » de « aucune VM ». Chaque
destruction de VM est lue de même : l'écran ne dit détruite que la VM dont
la suite a réussi, et nomme les autres avec leur code. Un délai dépassé
n'est ni un succès ni un échec : son issue est dite inconnue.

Ni hôte ni réseau : chaque commande envoyée à l'hôte reçoit une réponse
écrite ici ; les commandes dont la forme compte sont jouées par sh contre
de faux « pvesm », « pvesh », « qm » et « ssh ». Les noms (stockage,
nœuds, VM, hôte) sont inventés.
"""

import functools
import io
import itertools
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import ExitStack, contextmanager, redirect_stdout
from unittest import mock

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

sys.argv = ["todo.py"]

from script.proxmox import proxmox_deploy as pve  # noqa: E402
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

# Trois volumes sur un stockage partagé : celui d'une VM du nœud courant,
# celui d'une VM d'un AUTRE nœud, et un vrai orphelin, qu'aucune VM ne
# réclame. La forme est celle de « pvesm list ».
VOL_LOCALE = "stock-partage-essai:vm-201-disk-0"
VOL_VOISINE = "stock-partage-essai:vm-305-disk-0"
VOL_ORPHELIN = "stock-partage-essai:vm-907-disk-0"
VOL_ORPHELIN_2 = "stock-partage-essai:vm-908-disk-0"
VOLUMES = (
    "Volid                              Format  Type          Size VMID\n"
    f"{VOL_LOCALE}  raw     images  8589934592 201\n"
    f"{VOL_VOISINE}  raw     images  4294967296 305\n"
    f"{VOL_ORPHELIN}  raw     images  2147483648 907\n"
)

# « qm list » du nœud courant : il ne connaît QUE la 201.
QM_LIST = (
    "      VMID NAME                 STATUS     MEM(MB)    BOOTDISK(GB) PID\n"
    "       201 vm-locale-essai      running    2048              32.00 4242\n"
)

# « qm list » en échec, sous les formes que rend le transport : sudo qui
# refuse, commande absente, ssh qui n'aboutit pas. Chaque sortie, lue par
# parse_qm_list, donnerait [] : seul le code dit qu'on ne sait pas.
PANNES_QM = (
    (1, "sudo: a password is required"),
    (127, "sh: 1: qm: not found"),
    (255, "Connection refused"),
)

# Un hôte sans aucune VM : « qm list » réussit et ne rend que son en-tête.
QM_VIDE = (0, QM_LIST.splitlines()[0] + "\n")

# La grappe entière : la 201 d'ici, la 305 d'un nœud voisin, et un gabarit
# qui y figure aussi.
GRAPPE = json.dumps(
    [
        {
            "id": "qemu/201",
            "vmid": 201,
            "name": "vm-locale-essai",
            "node": "noeud-essai-a",
            "type": "qemu",
            "status": "running",
        },
        {
            "id": "qemu/305",
            "vmid": 305,
            "name": "vm-voisine-essai",
            "node": "noeud-essai-b",
            "type": "qemu",
            "status": "running",
        },
        {
            "id": "qemu/9000",
            "vmid": 9000,
            "name": "gabarit-essai",
            "node": "noeud-essai-b",
            "type": "qemu",
            "template": 1,
            "status": "stopped",
        },
    ]
)


class Hote:
    """Un hôte Proxmox écrit à la main : une réponse par commande.

    `qm` et `grappe` sont les réponses (code, sortie) de « qm list » et de
    la liste de grappe ; `echecs` nomme les volumes dont « pvesm free »
    échoue, et `code_echec` est ce qu'il rend alors. Chaque commande reçue
    est gardée, dans l'ordre.
    """

    def __init__(
        self,
        qm=(0, QM_LIST),
        grappe=(0, GRAPPE),
        volumes=(0, VOLUMES),
        echecs=(),
        code_echec=(1, ""),
    ):
        self.qm = qm
        self.grappe = grappe
        self.volumes = volumes
        self.echecs = set(echecs)
        self.code_echec = code_echec
        self.recues = []
        self.liberes = []

    def __call__(self, cmd, timeout=120, quiet=False):
        self.recues.append(cmd)
        if cmd == "qm list":
            return self.qm
        if cmd == pve.orphan_disks_cmd():
            return self.volumes
        if cmd == pve.cluster_vms_cmd():
            return self.grappe
        if cmd.startswith("pvesm free "):
            volid = cmd.split()[-1].strip("'")
            self.liberes.append(volid)
            # Le marqueur sépare ce que l'écran dit AVANT la libération de
            # ce qu'il en rapporte.
            print("<<LIBERATION>>")
            return self.code_echec if volid in self.echecs else (0, "")
        return 127, ""


def menu(hote):
    todo = TODO.__new__(TODO)
    todo._pve_show = hote
    todo._pve_host = lambda ask=True: {"target": "root@hote-essai-pve"}
    return todo


def jouer(methode, reponse="o", *args, **kwargs):
    """Lance `methode` ; rend (résultat, écran, questions posées)."""
    questions = []

    def repondre(invite=""):
        questions.append(invite)
        return reponse

    tampon = io.StringIO()
    with mock.patch("builtins.input", repondre), redirect_stdout(tampon):
        resultat = methode(*args, **kwargs)
    return resultat, tampon.getvalue(), questions


@contextmanager
def faux_path(faux):
    """PATH dont la tête porte les faux exécutables `faux` ({nom: script}).

    Le dossier vit le temps du bloc : ce qui s'y lance doit avoir fini."""
    with tempfile.TemporaryDirectory() as bac:
        for nom, script in faux.items():
            chemin = os.path.join(bac, nom)
            with open(chemin, "w", encoding="utf-8") as fh:
                fh.write(script)
            os.chmod(chemin, 0o755)
        yield bac + os.pathsep + os.environ["PATH"]


def executer(commande, faux):
    """`commande` jouée par sh, les faux exécutables en tête du PATH ; rend
    (code, sortie) sous la forme du transport : l'erreur standard APRÈS la
    sortie."""
    with faux_path(faux) as chemin:
        fini = subprocess.run(
            ["sh", "-c", commande],
            env=dict(os.environ, PATH=chemin),
            capture_output=True,
            text=True,
            timeout=30,
        )
    return fini.returncode, fini.stdout + fini.stderr


def par_le_transport(ssh, remote="qm list", delai=30):
    """(code, sortie) du VRAI `run` pour `remote`, contre un faux « ssh »
    écrit ici, qui ne joue pas `remote` : c'est le transport qu'on éprouve."""
    with faux_path({"ssh": ssh}) as chemin, mock.patch.dict(
        os.environ, {"PATH": chemin}
    ):
        return pve.run({"target": "root@hote-essai-pve"}, remote, delai)


@functools.lru_cache(maxsize=None)
def delai_depasse():
    """Ce que rend le transport quand le délai expire : un faux « ssh »
    qui dort plus longtemps que le délai accordé. « exec » : le processus
    tué est celui qui dort, et rien ne garde la sortie ouverte après lui."""
    return par_le_transport("#!/bin/sh\nexec sleep 30\n", delai=0.3)


class TestLaListeDeGrappeSeLitFermee(unittest.TestCase):
    """L'analyseur est PUR et fermé par défaut : ce qui n'a pas la forme
    attendue rend None, jamais un ensemble partiel — un VMID omis ferait
    passer ses disques pour orphelins."""

    def test_every_vm_of_the_cluster_is_read_templates_included(self):
        self.assertEqual({201, 305, 9000}, pve.parse_cluster_vmids(GRAPPE))

    def test_an_empty_cluster_is_an_answer(self):
        """Contrôle positif : une grappe sans VM n'est pas une panne."""
        self.assertEqual(set(), pve.parse_cluster_vmids("[]"))

    def test_an_unexpected_form_is_unknown_not_empty(self):
        for texte in (
            "",
            "pas du JSON",
            '{"data": []}',
            '[{"name": "vm-sans-vmid"}]',
            '[{"vmid": "201"}]',
            '[{"vmid": true}]',
            '["201"]',
            GRAPPE[:-1],
            "bruit avant le document\n" + GRAPPE,
            None,
        ):
            with self.subTest(texte=texte):
                self.assertIsNone(pve.parse_cluster_vmids(texte))

    def test_what_follows_the_document_is_not_read(self):
        """Le transport colle l'erreur standard APRÈS la sortie : une
        bannière sshd, un avertissement du client ssh ou de sudo suit le
        document, et ne le rend pas illisible."""
        for suite in (
            "\n** WARNING: connection is not using a post-quantum key"
            " exchange algorithm.\n",
            "\nAcces reserve au banc d'essai.\n",
        ):
            with self.subTest(suite=suite):
                self.assertEqual(
                    {201, 305, 9000}, pve.parse_cluster_vmids(GRAPPE + suite)
                )

    def test_the_transport_puts_the_banner_after_the_document(self):
        """La lecture ci-dessus suppose l'ordre du transport : la sortie
        d'abord, l'erreur standard ensuite. Joué par le vrai `run`, contre
        un faux « ssh » qui écrit une bannière sur l'erreur standard."""
        ssh = (
            "#!/bin/sh\n"
            "echo 'Acces reserve au banc d essai.' >&2\n"
            f"cat <<'FIN'\n{GRAPPE}\nFIN\n"
            "echo 'Fin de la banniere du banc.' >&2\n"
        )
        code, sortie = par_le_transport(ssh, pve.cluster_vms_cmd())
        self.assertEqual(0, code, sortie)
        self.assertIn("Acces reserve", sortie)
        self.assertEqual({201, 305, 9000}, pve.parse_cluster_vmids(sortie))

    def test_one_bad_entry_voids_the_whole_list(self):
        """Une entrée illisible parmi des bonnes : l'ensemble serait
        partiel, donc faux."""
        entrees = json.loads(GRAPPE) + [{"node": "noeud-essai-b"}]
        self.assertIsNone(pve.parse_cluster_vmids(json.dumps(entrees)))


class TestNeLibererQueCeQuiSeProuveOrphelin(unittest.TestCase):
    def test_a_failing_qm_list_offers_nothing(self):
        """LE mode de défaillance : « qm list » en échec, lu comme [], rend
        tout volume orphelin."""
        for panne in PANNES_QM:
            with self.subTest(panne=panne):
                hote = Hote(qm=panne)
                _r, ecran, questions = jouer(menu(hote)._pve_cleanup)
                self.assertEqual([], questions)
                self.assertEqual([], hote.liberes)
                self.assertNotIn(VOL_ORPHELIN, ecran)
                self.assertIn(
                    t("Unreadable VM list: « qm list » failed."), ecran
                )

    def test_a_vm_of_another_node_keeps_its_disk(self):
        """Le stockage est partagé : la 305 vit sur un nœud voisin, absente
        du « qm list » d'ici, présente dans la liste de grappe."""
        hote = Hote()
        _r, ecran, _q = jouer(menu(hote)._pve_cleanup)
        self.assertNotIn(VOL_VOISINE, hote.liberes)
        self.assertNotIn(VOL_VOISINE, ecran)
        self.assertNotIn(VOL_LOCALE, hote.liberes)

    def test_a_vm_known_only_to_the_node_keeps_its_disk(self):
        """L'autre moitié de la jonction : une VM que « qm list » voit et
        que la liste de grappe omet garde son disque."""
        sans_201 = json.dumps(
            [e for e in json.loads(GRAPPE) if e["vmid"] != 201]
        )
        hote = Hote(grappe=(0, sans_201))
        _r, ecran, _q = jouer(menu(hote)._pve_cleanup)
        self.assertNotIn(VOL_LOCALE, hote.liberes)
        self.assertNotIn(VOL_LOCALE, ecran)
        # Contrôle positif : ce n'est pas un refus global.
        self.assertEqual([VOL_ORPHELIN], hote.liberes)

    def test_an_unreadable_cluster_list_is_a_refusal(self):
        for grappe in (
            (0, "pas du JSON"),
            (0, ""),
            (0, '{"vmid": 305}'),
            (255, GRAPPE),
            (2, ""),
        ):
            with self.subTest(grappe=grappe):
                hote = Hote(grappe=grappe)
                _r, ecran, questions = jouer(menu(hote)._pve_cleanup)
                self.assertEqual([], questions)
                self.assertEqual([], hote.liberes)
                self.assertNotIn(VOL_ORPHELIN, ecran)
                self.assertIn(t("Unreadable cluster VM list."), ecran)

    def test_a_true_orphan_is_still_offered_and_freed(self):
        """Contrôle positif : refuser toujours passerait les trois
        épreuves précédentes, et la commande ne servirait plus à rien."""
        hote = Hote()
        _r, ecran, questions = jouer(menu(hote)._pve_cleanup)
        self.assertEqual(1, len(questions))
        self.assertIn(VOL_ORPHELIN, ecran)
        self.assertEqual([VOL_ORPHELIN], hote.liberes)

    def test_a_banner_after_the_cluster_list_still_offers_the_orphan(self):
        """Une bannière que le transport colle après le document ne fait
        pas refuser un hôte sain, ni offrir le disque d'une voisine."""
        hote = Hote(grappe=(0, GRAPPE + "\nAcces reserve au banc d'essai.\n"))
        _r, ecran, questions = jouer(menu(hote)._pve_cleanup)
        self.assertEqual(1, len(questions))
        self.assertEqual([VOL_ORPHELIN], hote.liberes)
        self.assertNotIn(VOL_VOISINE, ecran)

    def test_the_volumes_are_listed_before_the_vms_are(self):
        """Une VM créée entre les deux lectures doit avoir son disque
        ABSENT de la première liste : lu après, il serait pris pour
        orphelin, sa VM n'étant pas dans une liste lue avant lui."""
        hote = Hote()
        # Seul l'ordre des commandes reçues compte ici ; « n » ne libère rien.
        jouer(menu(hote)._pve_cleanup, "n")
        rang = hote.recues.index
        self.assertLess(rang(pve.orphan_disks_cmd()), rang("qm list"))
        self.assertLess(
            rang(pve.orphan_disks_cmd()), rang(pve.cluster_vms_cmd())
        )

    def test_a_refused_offer_frees_nothing(self):
        """L'offre est faite, puis refusée : rien ne part. Un nettoyage qui
        n'offrirait rien ne passe pas pour un refus respecté."""
        hote = Hote()
        _r, ecran, questions = jouer(menu(hote)._pve_cleanup, "n")
        self.assertEqual(1, len(questions))
        self.assertIn(t("Cancelled."), ecran)
        self.assertEqual([], hote.liberes)


class TestUnDelaiDepasseNEstNiSuccesNiEchec(unittest.TestCase):
    """Le délai expiré, le client ssh est tué, pas la commande : sans
    terminal, elle continue sur l'hôte ou s'interrompt à mi-course. Son
    issue est inconnue, et seul le transport sait la marquer."""

    def test_what_the_transport_renders_is_recognized(self):
        self.assertTrue(pve.timed_out(*delai_depasse()))

    def test_a_failure_of_the_host_is_not_a_timeout(self):
        """Contrôle positif : ssh qui n'aboutit pas, et « qm » ou
        « pvesm » qui échouent, rendent 255 eux aussi — et y compris avec
        « timeout » dans leur message."""
        injoignable = par_le_transport(
            "#!/bin/sh\n"
            "echo 'ssh: connect to host hote-essai-pve port 22:"
            " Connection refused' >&2\n"
            "exit 255\n"
        )
        self.assertEqual(255, injoignable[0])
        for reponse in (
            injoignable,
            (
                255,
                "can't lock file '/var/lock/qemu-server/lock-411.conf'"
                " - got timeout",
            ),
            (0, "timeout"),
            (0, ""),
        ):
            with self.subTest(reponse=reponse):
                self.assertFalse(pve.timed_out(*reponse))


# Faux « pvesm » en panne. Le premier : deux stockages d'images, dont le
# dernier est hors ligne et le dit sur l'erreur standard. Le second :
# « pvesm status » lui-même échoue.
PVESM_DERNIER_HORS_LIGNE = f"""#!/bin/sh
case "$1" in
status)
    echo "Name  Type  Status  Total  Used  Available  %"
    echo "stock-partage-essai  dir  active  100  50  50  50.00%"
    echo "stock-hors-ligne-essai  nfs  inactive  0  0  0  0.00%"
    ;;
list)
    if [ "$2" = stock-hors-ligne-essai ]; then
        echo "raison-stockage-essai" >&2
        exit 255
    fi
    printf '%s' "{VOLUMES}"
    ;;
esac
"""
# Le PREMIER des deux stockages est hors ligne ; le second répond.
PVESM_PREMIER_HORS_LIGNE = f"""#!/bin/sh
case "$1" in
status)
    echo "Name  Type  Status  Total  Used  Available  %"
    echo "stock-en-panne-essai  nfs  inactive  0  0  0  0.00%"
    echo "stock-partage-essai  dir  active  100  50  50  50.00%"
    ;;
list)
    if [ "$2" = stock-en-panne-essai ]; then
        echo "raison-premier-stockage-essai" >&2
        exit 255
    fi
    printf '%s' "{VOLUMES}"
    ;;
esac
"""
PVESM_SANS_STATUT = """#!/bin/sh
if [ "$1" = status ]; then
    echo "raison-status-essai" >&2
    exit 2
fi
echo "Volid  Format  Type  Size VMID"
"""


class TestUnRefusSeRejoueALaMain(unittest.TestCase):
    """Les lectures du nettoyage se font en silence ; quand l'une manque,
    le refus montre la commande telle qu'envoyée, son code et la fin de sa
    sortie — de quoi la rejouer à la main sans lire le source."""

    HOTE = {
        "target": "root@hote-essai-pve",
        "jump": "rebond-essai",
        "sudo": "sudo",
    }

    SANS_ELLE = (
        "Without it, no volume can be shown to be orphaned:"
        " nothing is offered."
    )

    def refus(self, hote):
        """Écran du nettoyage refusé sur `hote`, vu par l'hôte HOTE : rien
        n'est offert, et l'écran dit pourquoi rien ne peut l'être."""
        todo = menu(hote)
        todo._pve_host = lambda ask=True: dict(self.HOTE)
        _r, ecran, questions = jouer(todo._pve_cleanup)
        self.assertEqual([], questions)
        self.assertEqual([], hote.liberes)
        self.assertIn(t(self.SANS_ELLE), ecran)
        return ecran

    def rejouee(self, ecran):
        """argv de la ligne « Command: » de l'écran, lue comme le shell."""
        lignes = [l for l in ecran.splitlines() if t("Command:") in l]
        self.assertEqual(1, len(lignes), ecran)
        return shlex.split(lignes[0].split(t("Command:"), 1)[1])

    def envoyee(self, remote):
        """argv que le transport lance pour `remote` sur l'hôte HOTE."""
        return pve.ssh_argv(self.HOTE, pve.wrap_privilege(remote, "sudo"))

    def verifier(self, ecran, remote, code, raison):
        self.assertEqual(self.envoyee(remote), self.rejouee(ecran))
        if code:
            self.assertIn(f"{t('exit code')} {code}", ecran)
        else:
            self.assertIn(t("exit code 0, unreadable output"), ecran)
        self.assertIn(raison, ecran)

    def volumes_de(self, pvesm):
        """(code, sortie) de la VRAIE liste des volumes, jouée par sh contre
        le faux « pvesm » `pvesm`."""
        return executer(pve.orphan_disks_cmd(), {"pvesm": pvesm})

    def test_the_volume_list_refusal(self):
        """Le dernier stockage est hors ligne : « pvesm list » dit pourquoi
        sur l'erreur standard, et c'est cette raison que montre le refus,
        après les lignes de volume des stockages lus."""
        code, sortie = self.volumes_de(PVESM_DERNIER_HORS_LIGNE)
        ecran = self.refus(Hote(volumes=(code, sortie)))
        self.assertIn(t("Unreadable volume list."), ecran)
        self.verifier(
            ecran, pve.orphan_disks_cmd(), 255, "raison-stockage-essai"
        )

    def test_a_failing_storage_status_is_a_refusal(self):
        """« pvesm status » en échec ne nomme aucun stockage : la boucle
        tournerait à vide, et l'écran dirait qu'il n'y a rien d'orphelin."""
        code, sortie = self.volumes_de(PVESM_SANS_STATUT)
        ecran = self.refus(Hote(volumes=(code, sortie)))
        self.assertNotIn(t("Nothing orphaned."), ecran)
        self.assertIn(t("Unreadable volume list."), ecran)
        self.verifier(ecran, pve.orphan_disks_cmd(), 2, "raison-status-essai")

    def test_the_vm_list_refusal(self):
        ecran = self.refus(Hote(qm=(2, "raison-qm-essai")))
        self.verifier(ecran, "qm list", 2, "raison-qm-essai")

    def test_the_cluster_list_refusal(self):
        for code, sortie in (
            (0, "sortie-illisible-essai"),
            (255, "raison-grappe-essai"),
            (2, "Unknown option: output-format"),
        ):
            with self.subTest(code=code, sortie=sortie):
                ecran = self.refus(Hote(grappe=(code, sortie)))
                self.verifier(ecran, pve.cluster_vms_cmd(), code, sortie)

    def test_the_reason_after_a_long_output_is_shown(self):
        """Le transport colle l'erreur standard APRÈS la sortie : sur une
        sortie longue, la raison vient en dernier, et c'est la fin qui est
        montrée, jamais le début."""
        corps = "premiere-ligne-essai\n" + "".join(
            f"volume-long-essai-{i}\n" for i in range(7)
        )
        raison = "raison-apres-sortie-essai"
        ecran = self.refus(Hote(volumes=(2, corps + raison)))
        self.verifier(ecran, pve.orphan_disks_cmd(), 2, raison)
        self.assertNotIn("premiere-ligne-essai", ecran)

    def test_each_line_shown_is_bounded(self):
        """Une ligne sans fin — un document JSON tient sur une seule — est
        montrée par son début, tronquée à 200 caractères."""
        longue = "motif-long-essai-" * 80
        ecran = self.refus(Hote(volumes=(2, longue)))
        montrees = [
            l.strip() for l in ecran.splitlines() if "motif-long-essai-" in l
        ]
        self.assertEqual(1, len(montrees), ecran)
        self.assertTrue(longue.startswith(montrees[0]), montrees[0])
        self.assertLessEqual(len(montrees[0]), 200)

    def test_a_reading_that_succeeds_stays_silent(self):
        """Contrôle positif : un écran qui montrerait toujours la commande
        et le code passerait les épreuves précédentes."""
        _r, ecran, _q = jouer(menu(Hote())._pve_cleanup)
        self.assertNotIn(t("Command:"), ecran)
        self.assertNotIn(t("exit code"), ecran)
        self.assertNotIn(t(self.SANS_ELLE), ecran)


class TestUnStockageEnPanneNeRetireQueLesSiens(unittest.TestCase):
    """Un stockage en panne avant le dernier ne retire de la liste que ses
    propres volumes : aucun n'est offert, et ceux des stockages qui
    répondent le restent."""

    def test_the_other_storages_still_offer_their_orphans(self):
        volumes = executer(
            pve.orphan_disks_cmd(), {"pvesm": PVESM_PREMIER_HORS_LIGNE}
        )
        hote = Hote(volumes=volumes)
        _r, ecran, questions = jouer(menu(hote)._pve_cleanup)
        self.assertNotIn("stock-en-panne-essai:", ecran)
        self.assertEqual(1, len(questions), ecran)
        self.assertEqual([VOL_ORPHELIN], hote.liberes)


class TestChaqueLiberationEstLue(unittest.TestCase):
    """« pvesm free » peut échouer — volume verrouillé, stockage à terre :
    l'écran doit le dire, et dire LEQUEL."""

    def deux_orphelins(self, echecs, code_echec=(1, "")):
        volumes = (0, VOLUMES + f"{VOL_ORPHELIN_2}  raw  images  1024 908\n")
        hote = Hote(volumes=volumes, echecs=echecs, code_echec=code_echec)
        _r, ecran, _q = jouer(menu(hote)._pve_cleanup)
        self.assertEqual([VOL_ORPHELIN, VOL_ORPHELIN_2], hote.liberes)
        return ecran.rsplit("<<LIBERATION>>", 1)[-1]

    def nombres_liberes(self, rapport):
        """Les nombres que le rapport annonce libérés, entiers."""
        return re.findall(
            re.escape(t("Volumes freed:")) + r"\s*(\d+)", rapport
        )

    def test_a_failed_free_is_named(self):
        """Tout code non nul est un échec, pas seulement 1 : le stockage
        qui refuse et l'erreur de « pvesm » lui-même rendent autre chose."""
        for code_echec in (
            (1, ""),
            (2, ""),
            (255, "storage 'stock-partage-essai' is not online"),
        ):
            with self.subTest(code_echec=code_echec):
                rapport = self.deux_orphelins({VOL_ORPHELIN_2}, code_echec)
                self.assertIn(t("Not freed:"), rapport)
                echecs = rapport.split(t("Not freed:"), 1)[-1]
                self.assertIn(VOL_ORPHELIN_2, echecs)
                self.assertNotIn(VOL_ORPHELIN + "\n", echecs)
                self.assertEqual(["1"], self.nombres_liberes(rapport))

    def test_the_freed_count_is_the_successful_frees(self):
        """Le nombre annoncé est celui des « pvesm free » qui ont rendu 0,
        et rien n'est annoncé libéré quand tous ont échoué."""
        for echecs in ((), {VOL_ORPHELIN_2}, {VOL_ORPHELIN, VOL_ORPHELIN_2}):
            with self.subTest(echecs=echecs):
                rapport = self.deux_orphelins(echecs)
                attendu = 2 - len(echecs)
                self.assertEqual(
                    [str(attendu)] if attendu else [],
                    self.nombres_liberes(rapport),
                )

    def test_a_clean_run_reports_no_failure(self):
        """Contrôle positif : un rapport qui annoncerait toujours un échec
        passerait l'épreuve précédente."""
        rapport = self.deux_orphelins(echecs=())
        self.assertNotIn(t("Not freed:"), rapport)
        self.assertNotIn(t("Outcome unknown (timeout):"), rapport)

    def test_a_timed_out_free_is_neither_freed_nor_failed(self):
        """« pvesm free » peut tourner encore sur l'hôte : le volume n'est
        ni compté libéré ni nommé en échec, et le rapport dit quel
        stockage relire."""
        rapport = self.deux_orphelins({VOL_ORPHELIN_2}, delai_depasse())
        self.assertNotIn(t("Not freed:"), rapport)
        self.assertIn(t("Outcome unknown (timeout):"), rapport)
        inconnus = rapport.split(t("Outcome unknown (timeout):"), 1)[-1]
        self.assertIn(VOL_ORPHELIN_2, inconnus)
        stockage = VOL_ORPHELIN_2.split(":", 1)[0]
        self.assertIn(f"pvesm list {stockage}", inconnus)
        self.assertEqual(["1"], self.nombres_liberes(rapport))

    def test_each_storage_of_an_unknown_outcome_is_to_be_listed(self):
        """Deux volumes au délai dépassé, sur deux stockages, et un troisième
        libéré sur l'un d'eux : chacun des deux stockages est à relire, et
        c'est son NOM que suit « pvesm list », jamais celui du volume."""
        nord = "stock-nord-essai:vm-921-disk-0"
        sud = "stock-sud-essai:vm-922-disk-0"
        libere = "stock-nord-essai:vm-923-disk-0"
        lignes = "".join(
            f"{volid}  raw  images  1024 {vmid}\n"
            for volid, vmid in ((nord, 921), (sud, 922), (libere, 923))
        )
        hote = Hote(
            volumes=(0, f"{ENTETE_PVESM}\n{lignes}"),
            echecs={nord, sud},
            code_echec=delai_depasse(),
        )
        _r, ecran, _q = jouer(menu(hote)._pve_cleanup)
        self.assertEqual({nord, sud, libere}, set(hote.liberes))
        rapport = ecran.rsplit("<<LIBERATION>>", 1)[-1]
        self.assertEqual(["1"], self.nombres_liberes(rapport))
        inconnus = rapport.split(t("Outcome unknown (timeout):"), 1)[-1]
        self.assertEqual(
            {"stock-nord-essai", "stock-sud-essai"},
            set(re.findall(r"pvesm list ([^\s;,&|»]+)", inconnus)),
        )


# Deux VM du nœud, que la suppression peut viser ensemble.
QM_DEUX = (
    QM_LIST.splitlines()[0] + "\n"
    "       411 vm-cible-ouest-essai  running  2048  32.00 5151\n"
    "       412 vm-cible-est-essai    stopped  1024  16.00 0\n"
)


# Faux « qm » : « config » rend le nom que porte la VM SUR L'HÔTE ; toute
# autre sous-commande s'inscrit au journal, et c'est ce qui dit si la suite
# est allée plus loin que le garde.
FAUX_QM = """#!/bin/sh
if [ "$1" = config ]; then
    echo "name: {nom}"
    exit 0
fi
echo "$*" >> "{journal}"
"""


def jouer_la_suite(cmd, nom_sur_l_hote):
    """(code, sortie, journal) de la VRAIE suite de destruction `cmd`,
    jouée par sh contre un hôte où la VM porte `nom_sur_l_hote`."""
    with tempfile.TemporaryDirectory() as bac:
        journal = os.path.join(bac, "journal")
        faux = FAUX_QM.format(nom=nom_sur_l_hote, journal=journal)
        code, sortie = executer(cmd, {"qm": faux})
        inscrit = []
        if os.path.exists(journal):
            with open(journal, encoding="utf-8") as fh:
                inscrit = fh.read().splitlines()
    return code, sortie, inscrit


class HoteQuiDetruit(Hote):
    """L'hôte répond aussi à la destruction d'une VM de sa liste.

    `codes` donne, par VMID, ce que rend la suite de destruction : un code
    seul, ou (code, sortie) ; 0 sinon. Pour un VMID de `refusees`, la VM
    porte maintenant un autre nom sur l'hôte, et la VRAIE suite est jouée :
    c'est le garde d'identité qui répond. `rendus` garde, par VMID, le code
    qu'il a rendu, et `journal` ce que la suite a demandé à « qm » au-delà
    du garde. Une commande qui ne vise pas une VM de la liste retombe sur
    `Hote`."""

    def __init__(self, codes=None, refusees=(), **kwargs):
        super().__init__(qm=(0, QM_DEUX), **kwargs)
        self.codes = codes or {}
        self.refusees = set(refusees)
        self.detruites = []
        self.rendus = {}
        self.journal = []

    def __call__(self, cmd, timeout=120, quiet=False):
        for vm in pve.parse_qm_list(self.qm[1]):
            if cmd == pve.destroy_cmd(vm["vmid"], vm["name"]):
                self.recues.append(cmd)
                self.detruites.append(vm["vmid"])
                # Le rapport est ce que l'écran dit après la dernière.
                print("<<DESTRUCTION>>")
                if vm["vmid"] in self.refusees:
                    code, sortie, inscrit = jouer_la_suite(
                        cmd, "vm-renommee-essai"
                    )
                    self.rendus[vm["vmid"]] = code
                    self.journal += inscrit
                    return code, sortie
                reponse = self.codes.get(vm["vmid"], 0)
                return reponse if isinstance(reponse, tuple) else (reponse, "")
        return super().__call__(cmd, timeout, quiet)


class TestChaqueDestructionEstLue(unittest.TestCase):
    """La suite de destruction peut échouer — garde d'identité, VM
    verrouillée, hôte injoignable. L'écran ne dit supprimé que ce qui l'a
    été, et nomme chaque VM restée en place avec son code."""

    DETRUITES = t("VMs destroyed:")
    RESTEES = t("VMs not destroyed:")
    INCONNUES = t("Outcome unknown (timeout):")

    def detruire(self, hote, selection, todo=None):
        reponses = iter([selection, "o", "o"])
        tampon = io.StringIO()
        with mock.patch(
            "builtins.input", lambda _invite="": next(reponses)
        ), redirect_stdout(tampon):
            (todo or menu(hote))._pve_delete()
        self.assertTrue(hote.detruites, "aucune destruction n'est partie")
        return tampon.getvalue().rsplit("<<DESTRUCTION>>", 1)[-1]

    def sections(self, rapport):
        """{titre: [lignes]} du rapport, quel que soit l'ordre des titres.

        Le titre le plus long est cherché d'abord : l'un pourrait contenir
        l'autre dans une langue."""
        titres = sorted(
            (self.DETRUITES, self.RESTEES, self.INCONNUES),
            key=len,
            reverse=True,
        )
        out, courant = {}, None
        for ligne in rapport.splitlines():
            titre = next((x for x in titres if x in ligne), None)
            if titre:
                courant = out.setdefault(titre, [])
            elif courant is not None and ligne.strip():
                courant.append(ligne)
        return out

    def test_a_failure_is_named_with_its_code_and_never_announced(self):
        """Tout code non nul range la VM parmi celles qui restent : le
        garde sort en 1, une VM verrouillée fait échouer « qm » en 255."""
        for reponse in (
            1,
            2,
            (
                255,
                "can't lock file '/var/lock/qemu-server/lock-411.conf'"
                " - got timeout",
            ),
        ):
            with self.subTest(reponse=reponse):
                hote = HoteQuiDetruit(codes={411: reponse})
                sections = self.sections(self.detruire(hote, "1"))
                self.assertNotIn(self.DETRUITES, sections)
                restees = sections.get(self.RESTEES, [])
                self.assertEqual(1, len(restees), restees)
                self.assertIn("vm-cible-ouest-essai", restees[0])
                code = reponse[0] if isinstance(reponse, tuple) else reponse
                self.assertIn(str(code), restees[0].split())

    def test_a_vm_the_guard_refused_is_never_announced(self):
        """La VM porte maintenant un autre nom : la vraie suite est jouée,
        le garde refuse, et l'écran le dit avec le code qu'il a rendu."""
        hote = HoteQuiDetruit(refusees={411})
        sections = self.sections(self.detruire(hote, "1"))
        code = hote.rendus[411]
        self.assertNotEqual(0, code)
        self.assertEqual([], hote.journal, "la suite a dépassé le garde")
        self.assertNotIn(self.DETRUITES, sections)
        restees = sections.get(self.RESTEES, [])
        self.assertEqual(1, len(restees), restees)
        self.assertIn("vm-cible-ouest-essai", restees[0])
        self.assertIn(str(code), restees[0].split())

    def test_the_fake_host_lets_the_right_name_through(self):
        """Contrôle du banc : le même faux « qm », quand le nom concorde,
        laisse la suite aller jusqu'à la destruction — le refus vient donc
        bien du nom."""
        cmd = pve.destroy_cmd(411, "vm-cible-ouest-essai")
        code, sortie, journal = jouer_la_suite(cmd, "vm-cible-ouest-essai")
        self.assertEqual(0, code, sortie)
        self.assertTrue([l for l in journal if l.startswith("destroy 411")])

    def test_a_timed_out_destruction_is_neither_destroyed_nor_kept(self):
        """La suite peut tourner encore sur l'hôte : ni « détruite » ni
        « non détruite » ne serait prouvé."""
        hote = HoteQuiDetruit(codes={411: delai_depasse()})
        sections = self.sections(self.detruire(hote, "1"))
        self.assertNotIn(self.DETRUITES, sections)
        self.assertNotIn(self.RESTEES, sections)
        inconnues = sections.get(self.INCONNUES, [])
        self.assertTrue(
            [l for l in inconnues if "vm-cible-ouest-essai" in l], inconnues
        )
        # La commande qui dit où l'hôte en est : « qm list », entre les
        # guillemets du conseil, dans les deux langues.
        conseillees = re.findall(r"«\s*([^»]*?)\s*»", "\n".join(inconnues))
        self.assertEqual(["qm list"], conseillees, inconnues)

    def test_a_success_is_announced(self):
        """Contrôle positif : un écran qui ne dirait jamais rien de réussi
        passerait l'épreuve précédente."""
        hote = HoteQuiDetruit()
        sections = self.sections(self.detruire(hote, "1"))
        self.assertNotIn(self.RESTEES, sections)
        self.assertNotIn(self.INCONNUES, sections)
        detruites = sections.get(self.DETRUITES, [])
        self.assertEqual(1, len(detruites), detruites)
        self.assertIn("vm-cible-ouest-essai", detruites[0])

    def test_a_vm_without_name_is_counted_among_the_kept(self):
        """Sans nom, pas de preuve d'identité : rien ne part vers la VM, et
        le bilan la compte parmi celles qui restent."""
        hote = HoteQuiDetruit()
        todo = menu(hote)
        vms = pve.parse_qm_list(QM_DEUX)
        vms[1]["name"] = ""
        todo._pve_vms = lambda: vms
        sections = self.sections(self.detruire(hote, "all", todo))
        self.assertEqual([411], hote.detruites)
        restees = sections.get(self.RESTEES, [])
        self.assertEqual(["412"], [l.split()[0] for l in restees], restees)
        self.assertIn(t("no identity proof; refused"), restees[0])

    def test_a_mixed_run_puts_each_vm_on_its_side(self):
        hote = HoteQuiDetruit(codes={412: 2})
        sections = self.sections(self.detruire(hote, "all"))
        self.assertEqual([411, 412], hote.detruites)
        detruites = sections.get(self.DETRUITES, [])
        restees = sections.get(self.RESTEES, [])
        self.assertEqual(1, len(detruites), detruites)
        self.assertIn("vm-cible-ouest-essai", detruites[0])
        self.assertEqual(1, len(restees), restees)
        self.assertIn("vm-cible-est-essai", restees[0])
        self.assertIn("2", restees[0].split())


# Un stockage répertoire porte, à côté des disques, des sauvegardes, des ISO
# et des gabarits de conteneur. La colonne VMID d'une sauvegarde est celle de
# la VM sauvegardée : la 907 n'existe plus, son disque est orphelin, sa
# sauvegarde ne l'est pas — elle est souvent tout ce qui reste de la VM.
STOCK_MIXTE = "stock-mixte-essai"
DISQUE_MIXTE = f"{STOCK_MIXTE}:907/vm-907-disk-0.qcow2"
SAUVEGARDE = f"{STOCK_MIXTE}:backup/vzdump-qemu-907-sauvegarde-essai.vma.zst"
ISO = f"{STOCK_MIXTE}:iso/distribution-essai.iso"
GABARIT_CT = f"{STOCK_MIXTE}:vztmpl/gabarit-ct-essai.tar.zst"
LIGNES_MIXTES = {
    "images": f"{DISQUE_MIXTE}  qcow2  images  2147483648 907",
    "backup": f"{SAUVEGARDE}  vma.zst  backup  1073741824 907",
    "iso": f"{ISO}  iso  iso  657457152",
    "vztmpl": f"{GABARIT_CT}  tzst  vztmpl  126000000",
}
ENTETE_PVESM = "Volid  Format  Type  Size VMID"
STOCK_BLOC = "stock-bloc-essai"
DISQUE_BLOC = f"{STOCK_BLOC}:vm-908-disk-0"

# Faux « pvesm », en tête du PATH : « status » nomme deux stockages
# d'images ; « list » rend toutes les sortes de contenu du stockage, et
# seulement ses images quand on lui passe « --content images ».
FAUX_PVESM = f"""#!/bin/sh
case "$1" in
status)
    echo "Name  Type  Status  Total  Used  Available  %"
    echo "{STOCK_MIXTE}  dir  active  100  50  50  50.00%"
    echo "{STOCK_BLOC}  lvmthin  active  100  50  50  50.00%"
    ;;
list)
    shift
    stockage=""
    contenu=""
    while [ $# -gt 0 ]; do
        case "$1" in
        --content) contenu="$2"; shift 2 ;;
        --content=*) contenu="${{1#--content=}}"; shift ;;
        *) stockage="$1"; shift ;;
        esac
    done
    echo "{ENTETE_PVESM}"
    if [ "$stockage" = "{STOCK_MIXTE}" ]; then
        echo "{LIGNES_MIXTES['images']}"
        [ "$contenu" = images ] && exit 0
        echo "{LIGNES_MIXTES['backup']}"
        echo "{LIGNES_MIXTES['iso']}"
        echo "{LIGNES_MIXTES['vztmpl']}"
    else
        echo "{DISQUE_BLOC}  raw  images  1024 908"
    fi
    ;;
esac
"""


class TestSeulUnDisqueDeVmEstOrphelin(unittest.TestCase):
    """« pvesm free » ne reçoit qu'un disque de VM, jamais une sauvegarde.

    Deux couches, chacune éprouvée seule : l'analyseur ne retient que le
    type « images », quelle que soit la sortie qu'on lui donne ; la
    commande ne demande que les images, quel que soit le contenu du
    stockage."""

    def test_the_parser_keeps_only_vm_disks(self):
        for sorte in ("backup", "iso", "vztmpl"):
            with self.subTest(sorte=sorte):
                texte = f"{ENTETE_PVESM}\n{LIGNES_MIXTES[sorte]}\n"
                self.assertEqual([], pve.parse_orphans(texte, {201}))

    def test_an_images_line_without_vmid_is_never_offered(self):
        """Sans colonne VMID, la dernière colonne est la taille : lue comme
        un VMID, elle enverrait le volume à « pvesm free »."""
        texte = (
            f"{ENTETE_PVESM}\n{STOCK_BLOC}:volume-sans-vm-essai  raw  images"
            "  1024\n"
        )
        self.assertEqual([], pve.parse_orphans(texte, {201}))

    def test_a_true_orphan_disk_is_still_kept(self):
        """Contrôle positif : écarter toute ligne passerait l'épreuve
        précédente, et plus rien ne serait jamais libéré."""
        texte = ENTETE_PVESM + "\n" + "\n".join(LIGNES_MIXTES.values())
        self.assertEqual(
            [(DISQUE_MIXTE, 2147483648)], pve.parse_orphans(texte, {201})
        )

    def lancer(self, commande):
        """Sortie de `commande` jouée par sh, le faux « pvesm » en tête."""
        code, sortie = executer(commande, {"pvesm": FAUX_PVESM})
        self.assertEqual(0, code, sortie)
        return [l.split() for l in sortie.splitlines() if l.strip()]

    def test_the_command_asks_the_host_for_images_only(self):
        lignes = self.lancer(pve.orphan_disks_cmd())
        volumes = [l for l in lignes if l[0] != "Volid"]
        self.assertEqual(
            [],
            [l[0] for l in volumes if l[2] != "images"],
            "la commande rend autre chose que des disques de VM",
        )
        # Contrôle positif : une commande muette passerait la ligne
        # précédente ; les disques des DEUX stockages doivent venir.
        self.assertIn(DISQUE_MIXTE, [l[0] for l in volumes])
        self.assertIn(DISQUE_BLOC, [l[0] for l in volumes])

    def test_the_fake_host_does_serve_everything_else(self):
        """Contrôle du banc : un faux « pvesm » qui ne rendrait jamais que
        des images ferait passer n'importe quelle commande."""
        lignes = self.lancer(f"pvesm list {STOCK_MIXTE}")
        self.assertIn(SAUVEGARDE, [l[0] for l in lignes])


# Ce que l'API rend, par chemin : la 201 vit ici ; la 305 (QEMU) et la 612
# (LXC) vivent sur un nœud voisin, et seule la vue de la grappe les porte.
# Sans « --type vm », la grappe mêle ses nœuds et ses stockages, qui n'ont
# pas de VMID.
_VM_ICI = {
    "id": "qemu/201",
    "vmid": 201,
    "type": "qemu",
    "node": "noeud-essai-a",
}
_VM_VOISINE = {
    "id": "qemu/305",
    "vmid": 305,
    "type": "qemu",
    "node": "noeud-essai-b",
}
_CT_VOISIN = {
    "id": "lxc/612",
    "vmid": 612,
    "type": "lxc",
    "node": "noeud-essai-b",
}
_AUTRES = [
    {"id": "node/noeud-essai-a", "type": "node", "node": "noeud-essai-a"},
    {
        "id": "storage/noeud-essai-a/stock-partage-essai",
        "type": "storage",
        "node": "noeud-essai-a",
    },
]


# Faux « pvesh », en tête du PATH : « get <chemin> » avec ses options. Le
# JSON n'arrive que sur « --output-format json » ; sinon, un tableau.
FAUX_PVESH = f"""#!/bin/sh
[ "$1" = get ] || {{ echo "verbe inconnu : $1" >&2; exit 255; }}
chemin="$2"
shift 2
type=""
format=""
while [ $# -gt 0 ]; do
    case "$1" in
    --type) type="$2"; shift 2 ;;
    --type=*) type="${{1#--type=}}"; shift ;;
    --output-format) format="$2"; shift 2 ;;
    --output-format=*) format="${{1#--output-format=}}"; shift ;;
    *) shift ;;
    esac
done
case "$chemin" in
/cluster/resources)
    if [ "$type" = vm ]; then
        doc='{json.dumps([_VM_ICI, _VM_VOISINE, _CT_VOISIN])}'
    else
        doc='{json.dumps([_VM_ICI, _VM_VOISINE, _CT_VOISIN] + _AUTRES)}'
    fi
    ;;
/nodes/*/qemu) doc='{json.dumps([_VM_ICI])}' ;;
/nodes/*/lxc) doc='[]' ;;
*) echo "no such path : $chemin" >&2; exit 255 ;;
esac
if [ "$format" = json ]; then
    echo "$doc"
else
    echo "id        type  vmid  node"
    echo "qemu/201  qemu  201   noeud-essai-a"
fi
"""


class TestLaCommandeDemandeTouteLaGrappe(unittest.TestCase):
    """La commande de référence, jouée par sh contre un faux « pvesh » qui
    répond comme l'API : seule la vue de la grappe porte les VM des autres
    nœuds, et un disque de l'une d'elles sur un stockage partagé passerait
    sinon pour orphelin."""

    def test_the_command_brings_the_vms_of_every_node(self):
        code, sortie = executer(pve.cluster_vms_cmd(), {"pvesh": FAUX_PVESH})
        self.assertEqual(0, code, sortie)
        vmids = pve.parse_cluster_vmids(sortie)
        self.assertIsNotNone(vmids, sortie)
        self.assertLessEqual({201, 305, 612}, vmids)

    def test_the_reason_pvesh_gives_reaches_the_output(self):
        """Un « pvesh » qui refuse dit pourquoi sur l'erreur standard : la
        commande la laisse passer, et le refus du nettoyage la montre."""
        refus = (
            "#!/bin/sh\necho 'Unknown option: output-format' >&2\nexit 255\n"
        )
        code, sortie = executer(pve.cluster_vms_cmd(), {"pvesh": refus})
        self.assertNotEqual(0, code)
        self.assertIn("Unknown option: output-format", sortie)

    def test_the_fake_host_tells_the_node_from_the_cluster(self):
        """Contrôle du banc : un faux « pvesh » qui rendrait la grappe à
        toute demande ferait passer n'importe quelle commande."""
        _c, sortie = executer(
            "pvesh get /nodes/localhost/qemu --output-format json",
            {"pvesh": FAUX_PVESH},
        )
        self.assertEqual({201}, pve.parse_cluster_vmids(sortie))


class TestIllisibleNEstPasVide(unittest.TestCase):
    """Chaque lecteur de la liste du nœud distingue « qm list en échec » de
    « aucune VM ». Le second dit qu'il n'y a rien ; le premier ne le sait
    pas, et le dire serait faux."""

    def test_the_reader_says_unknown_with_none(self):
        """Tout code non nul vaut « illisible », pas seulement celui d'un
        ssh qui n'aboutit pas : la sortie d'un sudo qui refuse se lit
        comme une liste vide."""
        for panne in PANNES_QM:
            with self.subTest(panne=panne):
                self.assertIsNone(menu(Hote(qm=panne))._pve_vms())

    def test_and_an_empty_host_is_still_an_empty_list(self):
        """Contrôle positif : un hôte sans VM répond « qm list » avec son
        seul en-tête, et c'est une liste vide, pas une panne."""
        self.assertEqual([], menu(Hote(qm=QM_VIDE))._pve_vms())

    def lecteurs(self):
        return (
            ("_pve_list", ()),
            ("_pve_change_state", ()),
            ("_pve_pick_vm", ()),
            ("_pve_delete", ()),
            ("_pve_ssh_config", ()),
        )

    def test_no_reader_claims_there_is_no_vm(self):
        illisible = t("Unreadable VM list: « qm list » failed.")
        aucune = (
            t("No VM on this Proxmox host."),
            t("No running VM on this Proxmox host."),
        )
        for (nom, args), panne in itertools.product(
            self.lecteurs(), PANNES_QM
        ):
            with self.subTest(lecteur=nom, panne=panne):
                todo = menu(Hote(qm=panne))
                _r, ecran, questions = jouer(getattr(todo, nom), "1", *args)
                self.assertEqual([], questions)
                self.assertIn(illisible, ecran)
                for phrase in aucune:
                    self.assertNotIn(phrase, ecran)

    def test_an_empty_host_is_still_said_to_be_empty(self):
        """Contrôle positif : le message « aucune VM » n'a pas disparu,
        il est réservé à ce qu'il décrit."""
        aucune = (
            t("No VM on this Proxmox host."),
            t("No running VM on this Proxmox host."),
        )
        for nom, args in self.lecteurs():
            with self.subTest(lecteur=nom):
                todo = menu(Hote(qm=QM_VIDE))
                _r, ecran, _q = jouer(getattr(todo, nom), "1", *args)
                self.assertNotIn(
                    t("Unreadable VM list: « qm list » failed."), ecran
                )
                self.assertTrue(any(p in ecran for p in aucune), ecran)

    def changer_d_etat(self, hote):
        """Écran d'un « start » confirmé de la 201, sa liste déjà en main :
        la seule lecture de « qm list » est l'état d'APRÈS le geste."""
        reponses = iter(["1", "1", "o"])
        tampon = io.StringIO()
        with mock.patch(
            "builtins.input", lambda _invite="": next(reponses)
        ), redirect_stdout(tampon):
            menu(hote)._pve_change_state(vms=pve.parse_qm_list(QM_LIST))
        self.assertIn("qm start 201", hote.recues)
        return tampon.getvalue()

    def test_the_state_after_a_gesture_is_not_read_as_empty(self):
        """L'état d'après est la seule preuve que le geste a porté : une
        liste illisible le dit, au lieu de ne rien montrer, et montre la
        lecture qui manque — la commande telle qu'envoyée, son code et sa
        raison."""
        envoyee = pve.ssh_argv(
            {"target": "root@hote-essai-pve"},
            pve.wrap_privilege("qm list", ""),
        )
        for code, sortie in PANNES_QM:
            with self.subTest(code=code, sortie=sortie):
                ecran = self.changer_d_etat(Hote(qm=(code, sortie)))
                self.assertIn(
                    t("Unreadable VM list: « qm list » failed."), ecran
                )
                lignes = [l for l in ecran.splitlines() if t("Command:") in l]
                self.assertEqual(1, len(lignes), ecran)
                rejouee = lignes[0].split(t("Command:"), 1)[1]
                self.assertEqual(envoyee, shlex.split(rejouee))
                self.assertIn(f"{t('exit code')} {code}", ecran)
                self.assertIn(sortie, ecran)

    def test_the_state_after_a_gesture_is_still_shown(self):
        """Contrôle positif : une liste lisible montre l'état de la VM
        visée, et rien d'illisible."""
        ecran = self.changer_d_etat(Hote())
        self.assertNotIn(t("Unreadable VM list: « qm list » failed."), ecran)
        self.assertNotIn(t("Command:"), ecran)
        apres = [
            l.split()
            for l in ecran.splitlines()
            if l.split()[:1] == ["vm-locale-essai"]
        ]
        self.assertEqual([["vm-locale-essai", "running"]], apres)

    def test_an_empty_node_still_offers_its_orphans(self):
        """Un nœud dont toutes les VM sont parties sans « --purge » : le
        cas même des orphelins. Sa liste vide est une réponse."""
        entete, *lignes = VOLUMES.splitlines()
        orphelin = next(l for l in lignes if l.startswith(VOL_ORPHELIN))
        hote = Hote(
            qm=QM_VIDE,
            grappe=(0, "[]"),
            volumes=(0, f"{entete}\n{orphelin}\n"),
        )
        _r, ecran, questions = jouer(menu(hote)._pve_cleanup)
        self.assertNotIn(t("Unreadable VM list: « qm list » failed."), ecran)
        self.assertEqual(1, len(questions))
        self.assertEqual([VOL_ORPHELIN], hote.liberes)

    def test_the_form_reads_an_empty_host_as_an_answer(self):
        """Premier déploiement sur un hôte neuf : sa liste vide n'arrête
        pas la lecture du contexte. Toute lecture de l'hôte qui SUIT la
        liste lève une sentinelle : la porte est passée, et le reste n'a
        pas à être joué. Les lectures locales sont neutres, et leur place
        avant ou après la liste ne change rien."""

        class PorteFranchie(Exception):
            pass

        hote = Hote(qm=QM_VIDE)
        todo = menu(hote)

        def lire(cmd, timeout=120, quiet=False):
            if "qm list" in hote.recues:
                raise PorteFranchie
            return hote(cmd, timeout, quiet)

        todo._pve_show = lire
        todo._native_arch = lambda: "amd64"
        todo._qemu_arch_distros = lambda _arch: None
        todo._qemu_catalog_entries = lambda *_args: []
        tampon = io.StringIO()
        with redirect_stdout(tampon), self.assertRaises(PorteFranchie):
            todo._pve_form_context(
                types.SimpleNamespace(DISTROS=()),
                {"target": "root@hote-essai-pve"},
            )
        self.assertNotIn(
            t("Unreadable VM list: « qm list » failed."), tampon.getvalue()
        )

    def test_the_picker_returns_nothing_to_act_on(self):
        todo = menu(Hote(qm=PANNES_QM[0]))
        seule, _e, _q = jouer(todo._pve_pick_vm)
        plusieurs, _e, _q = jouer(todo._pve_pick_vm, "all", multiple=True)
        self.assertIsNone(seule)
        self.assertFalse(plusieurs)


class TestAucuneCreationSurUnVmidDevine(unittest.TestCase):
    """Sans la liste, le premier VMID libre est inconnu : « 100 » serait
    une supposition, que « qm create » refuse une fois l'image
    téléchargée si le VMID est pris."""

    def test_the_form_is_not_opened(self):
        from script.todo import textual_setup

        todo = menu(Hote(qm=(255, "")))
        todo._qemu_import_module = lambda: object()
        vus = []
        todo._pve_deploy_prompts = lambda *_a: vus.append("questions")
        with mock.patch.object(
            textual_setup, "ensure", return_value=True
        ), mock.patch(
            "script.todo.proxmox_deploy_form.run_proxmox_form",
            side_effect=lambda ctx: vus.append("écran") or {},
        ):
            _r, ecran, questions = jouer(todo._pve_deploy)
        self.assertEqual([], vus)
        self.assertEqual([], questions)
        self.assertIn(t("Unreadable VM list: « qm list » failed."), ecran)

    def test_the_prompts_stop_before_a_vmid_is_chosen(self):
        hote = Hote(qm=(255, ""))
        todo = menu(hote)
        todo._qemu_import_module = lambda: object()
        todo._deploy_ask_posture = lambda after_boot=False: {}
        todo._pve_posture_refused = lambda _p: False
        todo._qemu_prompt_distro = lambda: "debian"
        todo._qemu_prompt_version = lambda _d: "13"
        todo._qemu_ask_ram = lambda _l, _d: 2048
        todo._qemu_ask_cpu = lambda _l, _d, _h: 2
        # Le nom et le disque se demandent avant le VMID ; toute question
        # au-delà veut dire que la création a continué sans la liste.
        reponses = iter(["vm-essai-sans-liste", "20G"])

        def repondre(invite=""):
            try:
                return next(reponses)
            except StopIteration:
                raise AssertionError(f"question après le refus : {invite}")

        faux = {
            "parse_storages": lambda _o: [{"name": "local", "actif": True}],
            "parse_bridges": lambda _o: ["vmbr0"],
            "parse_bridge_config": lambda _o: {},
            "pick_storage": lambda _s, voulu="": "local",
            "pick_bridge": lambda _p, voulu="": "vmbr0",
        }
        tampon = io.StringIO()
        with ExitStack() as pile:
            for nom, bouchon in faux.items():
                pile.enter_context(mock.patch.object(pve, nom, bouchon))
            pile.enter_context(mock.patch("builtins.input", repondre))
            pile.enter_context(redirect_stdout(tampon))
            todo._pve_deploy_prompts()
        self.assertIn(
            t("Unreadable VM list: « qm list » failed."), tampon.getvalue()
        )
        self.assertFalse([c for c in hote.recues if c.startswith("qm create")])


class TestLeNettoyageSshNeJugePasSansLaListe(unittest.TestCase):
    """Une entrée ~/.ssh/config vit tant que son nom est celui d'une VM de
    l'hôte Proxmox retenu. Liste illisible, cette preuve manque : l'entrée
    semblerait morte, et partirait."""

    CONFIG = (
        "Host erplibre-vm-fictive-pve\n"
        "    HostName 192.0.2.77\n"
        "    User erplibre\n"
    )

    def nettoyer(self, todo):
        """(fichier restant, écran, questions) du nettoyage par `todo`,
        dans un HOME dont ~/.ssh/config porte CONFIG."""
        with tempfile.TemporaryDirectory() as maison:
            os.makedirs(os.path.join(maison, ".ssh"))
            chemin = os.path.join(maison, ".ssh", "config")
            with open(chemin, "w", encoding="utf-8") as fh:
                fh.write(self.CONFIG)
            with mock.patch.dict(os.environ, {"HOME": maison}):
                _r, ecran, questions = jouer(todo._cleanup_ssh_config, "o", [])
            with open(chemin, encoding="utf-8") as fh:
                reste = fh.read()
        return reste, ecran, questions

    def test_an_unreadable_list_removes_nothing(self):
        for panne in PANNES_QM:
            with self.subTest(panne=panne):
                reste, ecran, questions = self.nettoyer(menu(Hote(qm=panne)))
                self.assertEqual(self.CONFIG, reste)
                self.assertEqual([], questions)
                self.assertIn(
                    t("Unreadable VM list: « qm list » failed."), ecran
                )
                self.assertIn(
                    t(
                        "~/.ssh/config left as is: an entry may lead to a"
                        " VM of the host."
                    ),
                    ecran,
                )

    def test_a_vm_of_the_host_keeps_its_entry(self):
        """Contrôle : la preuve par la liste tient toujours."""
        qm = (
            0,
            QM_LIST.splitlines()[0]
            + "\n       142 erplibre-vm-fictive-pve  running  2048  32.00 7\n",
        )
        reste, _e, questions = self.nettoyer(menu(Hote(qm=qm)))
        self.assertEqual(self.CONFIG, reste)
        self.assertEqual([], questions)

    def test_a_readable_list_still_lets_a_dead_entry_go(self):
        """Contrôle positif : refuser toujours passerait les deux autres."""
        reste, _e, questions = self.nettoyer(menu(Hote()))
        self.assertEqual(1, len(questions))
        self.assertNotIn("erplibre-vm-fictive-pve", reste)

    def test_an_empty_host_still_lets_a_dead_entry_go(self):
        """Un hôte sans VM est une réponse : l'entrée qui ne tenait qu'à
        lui ne mène plus à rien."""
        reste, ecran, questions = self.nettoyer(menu(Hote(qm=QM_VIDE)))
        self.assertNotIn(t("Unreadable VM list: « qm list » failed."), ecran)
        self.assertEqual(1, len(questions))
        self.assertNotIn("erplibre-vm-fictive-pve", reste)

    def test_without_a_retained_host_a_dead_entry_still_goes(self):
        """Sans hôte Proxmox retenu, la preuve « VM de l'hôte » n'existe
        pas, et son absence n'est pas une panne : l'entrée morte est
        offerte, sans demander d'hôte à l'opérateur ni rien envoyer."""
        todo = TODO.__new__(TODO)
        demandes, envois = [], []
        # Rend None : aucun hôte retenu. `_pve_show` reste le vrai.
        todo._pve_host = lambda ask=True: demandes.append(ask)

        def envoyer(*args, **_kwargs):
            envois.append(args)
            return 0, ""

        with mock.patch.object(pve, "run", envoyer):
            reste, ecran, questions = self.nettoyer(todo)
        self.assertNotIn(t("Unreadable VM list: « qm list » failed."), ecran)
        self.assertEqual(1, len(questions))
        self.assertNotIn("erplibre-vm-fictive-pve", reste)
        self.assertNotIn(True, demandes)
        self.assertEqual([], envois)


if __name__ == "__main__":
    unittest.main()
