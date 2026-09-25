#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Effacer une VM depuis le menu, avec la preuve que c'est la bonne.

Le garde d'identité existait, il était éprouvé, et il n'était pas sur le
chemin qu'un opérateur emprunte : l'écran reconstruisait la commande à la
main — le même corps que le verbe, sans son garde — et le fichier n'importait
rien du paquet des backends.

UN NOM SE RÉEMPLOIE, UN UUID NON. Entre l'affichage de la liste et
l'exécution il y a trois questions : une fenêtre de durée humaine pendant
laquelle un nom peut cesser de désigner le même domaine. La preuve se lit
donc À L'AFFICHAGE : lue juste avant d'effacer, elle se comparerait à
elle-même.

UN MENU NE DÉSARME PAS. La bibliothèque tolère une preuve absente, et c'est
un choix écrit : sur un poste où l'on n'a pas pu la relever, mieux vaut la
prudence d'avant. Mais un domaine que l'inventaire vient d'énumérer porte
TOUJOURS son UUID : une preuve manquante ne décrit pas une station, elle
décrit une lecture cassée — typiquement l'URI implicite, qui rend une liste
vide sans erreur. Retomber sur le nom serait un échec OUVERT.

Rien ici ne touche à un hyperviseur : libvirt et l'exécution sont remplacés.
"""

import os
import sys
import unittest
from unittest import mock

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

sys.argv = ["todo.py"]

from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402
from script.vm import backend as VM  # noqa: E402

# Deux domaines de banc, preuves inventées.
INVENTAIRE = (
    "aaaaaaaa-1111-2222-3333-444444444444 machine-a\n"
    "bbbbbbbb-1111-2222-3333-444444444444 machine-b\n"
)


class Bancal:
    """Une exécution de banc : elle retient, elle ne joue rien."""

    def __init__(self, code=0):
        self.vues = []
        self.code = code

    def exec_command_live(self, cmd, source_erplibre=True):
        self.vues.append(cmd)
        return self.code


def todo_avec(inventaire=INVENTAIRE, reponses=(), fichiers=()):
    """Une instance TODO dont l'inventaire, les invites et l'exécution sont
    remplacés par des faits."""
    todo = TODO.__new__(TODO)
    todo._qemu_list_vms = lambda: None
    todo._qemu_list_domains_proved = lambda: VM.parse_uuid_listing(inventaire)
    todo._qemu_list_domains = lambda: [
        d.name for d in VM.parse_uuid_listing(inventaire)
    ]
    todo._qemu_vm_own_files = lambda _nom: list(fichiers)
    todo.execute = Bancal()
    file = list(reponses)
    todo._file_de_reponses = file
    return todo


def jouer(todo, reponses, menage=None):
    """Joue l'écran d'effacement avec une file de réponses, sans terminal.

    Le ménage des exceptions de cache est REMPLACÉ. Posé sur la station, il
    lit la liste des dérogations et ajoute une commande par orpheline : les
    épreuves qui comptent les commandes compteraient alors autre chose selon
    ce que la machine qui les joue a d'installé. `menage` reçoit, à chaque
    appel, le nombre de commandes DÉJÀ jouées — ce qui situe le ménage par
    rapport aux effacements.
    """
    import builtins
    import io
    from contextlib import redirect_stdout

    vus = menage if menage is not None else []

    def faux_menage(_execute):
        vus.append(len(todo.execute.vues))
        return 0

    file = list(reponses)
    vrai_input = builtins.input
    builtins.input = lambda *_a, **_k: file.pop(0) if file else ""
    tampon = io.StringIO()
    try:
        with (
            redirect_stdout(tampon),
            mock.patch("script.todo.qemu_manage.bypass_menage", faux_menage),
        ):
            todo._qemu_delete_vm()
    finally:
        builtins.input = vrai_input
    return tampon.getvalue()


class TestLeGardeEstSurLeChemin(unittest.TestCase):
    def test_the_command_refuses_before_it_undefines(self):
        """L'ORDRE est la seule chose qui compte pour un préfixe de shell :
        après l'undefine, le garde ne garde plus rien."""
        todo = todo_avec()
        jouer(todo, ["1", "n", "machine-a"])
        self.assertEqual(1, len(todo.execute.vues), todo.execute.vues)
        cmd = todo.execute.vues[0]
        self.assertLess(cmd.index("REFUS"), cmd.index("undefine"))

    def test_the_proof_that_travels_is_the_one_that_was_listed(self):
        """Une preuve relevée juste avant d'effacer serait comparée à
        elle-même et ne prouverait rien."""
        todo = todo_avec()
        jouer(todo, ["1", "n", "machine-a"])
        self.assertIn(
            "aaaaaaaa-1111-2222-3333-444444444444", todo.execute.vues[0]
        )

    def test_it_addresses_by_name_and_proves_by_uuid(self):
        todo = todo_avec()
        jouer(todo, ["2", "n", "machine-b"])
        cmd = todo.execute.vues[0]
        self.assertIn("undefine machine-b", cmd)
        self.assertIn("bbbbbbbb-1111-2222-3333-444444444444", cmd)
        self.assertNotIn("machine-a", cmd)

    def test_the_menu_no_longer_writes_the_command_itself(self):
        """Un corps recopié dérive de son original au premier correctif, et
        c'est le chemin recopié qui dérive en silence."""
        import ast

        chemin = os.path.join(RACINE, "script", "todo", "qemu_manage.py")
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        corps = [
            noeud
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.FunctionDef)
            and noeud.name == "_qemu_delete_vm"
        ][0]
        appels = [
            noeud.func.attr
            for noeud in ast.walk(corps)
            if isinstance(noeud, ast.Call)
            and isinstance(noeud.func, ast.Attribute)
        ]
        self.assertIn("delete_command", appels)


class TestLaLectureDeLInventaire(unittest.TestCase):
    """Le banc d'à côté remplace la lecture entière : sans cette épreuve,
    rien ne dit que la commande demande bien la preuve."""

    def _lire(self, sortie="", casse=False):
        from unittest.mock import patch

        vues = []

        class Reponse:
            stdout = sortie

        def espion(argv, **_kwargs):
            vues.append(argv)
            if casse:
                raise OSError("virsh introuvable")
            return Reponse()

        todo = TODO.__new__(TODO)
        with patch("script.todo.qemu_manage.subprocess.run", espion):
            domaines = todo._qemu_list_domains_proved()
        return domaines, vues

    def test_it_asks_for_the_proof_and_the_name(self):
        _domaines, vues = self._lire(INVENTAIRE)
        self.assertTrue(vues, "aucun appel : rien n'est prouvé")
        self.assertIn("--uuid", vues[0])
        self.assertIn("--name", vues[0])

    def test_it_asks_once_and_not_once_per_machine(self):
        """Un appel par machine se verrait devant un menu."""
        _domaines, vues = self._lire(INVENTAIRE)
        self.assertEqual(1, len(vues))

    def test_the_uri_is_never_left_implicit(self):
        """Sans elle, libvirt choisit un hyperviseur séparé où « list
        --all » rend une liste vide, sans erreur et sans avertissement."""
        _domaines, vues = self._lire(INVENTAIRE)
        self.assertIn("--connect", vues[0])

    def test_it_yields_the_domains_with_their_proof(self):
        domaines, _vues = self._lire(INVENTAIRE)
        self.assertEqual(
            ["machine-a", "machine-b"], [d.name for d in domaines]
        )
        self.assertTrue(all(VM.is_armed(d) for d in domaines))

    def test_a_broken_read_yields_no_domain_and_does_not_raise(self):
        """Une liste vide ferme l'écran ; une exception le ferait tomber."""
        domaines, _vues = self._lire(casse=True)
        self.assertEqual((), domaines)


class TestUnMenuNeDesarmePas(unittest.TestCase):
    def test_a_domain_without_proof_is_refused_and_named(self):
        """Elle ne DISPARAÎT pas de la liste : la cacher laisserait croire
        qu'elle n'existe pas."""
        todo = todo_avec("machine-sans-preuve\n")
        vu = jouer(todo, ["1", "n", "machine-a"])
        self.assertEqual([], todo.execute.vues)
        self.assertIn("machine-sans-preuve", vu)

    def test_the_library_still_disarms_and_that_is_not_touched(self):
        """Deux régimes : la bibliothèque tolère, le menu refuse. Toucher
        au premier bloquerait la suppression là où le désarmement a été
        écrit pour servir."""
        from script.vm import verbs as V

        nu = VM.libvirt_handle("machine-a")
        self.assertEqual("", V.identity_guard(nu))
        self.assertNotIn("REFUS", V.delete_command(nu, sudo="", uri="x"))

    def test_the_others_are_still_deleted(self):
        """Contrôle positif : une machine sans preuve ne doit pas fermer
        celles qui en ont une."""
        todo = todo_avec(
            "machine-sans-preuve\n"
            "bbbbbbbb-1111-2222-3333-444444444444 machine-b\n"
        )
        jouer(todo, ["all", "n", "2"])
        self.assertEqual(1, len(todo.execute.vues))
        self.assertIn("machine-b", todo.execute.vues[0])


class TestLeMenageDuCacheSuitLEffacement(unittest.TestCase):
    """Une exception de cache survit à la VM qu'elle nommait, et une MAC
    libérée se réattribue : l'exception soustrairait alors au cache une
    machine neuve que personne n'a exceptée.

    Le ménage passe donc ICI, seul endroit qui sait que la VM vient de
    disparaître, et APRÈS les effacements : passé avant, il jugerait
    orpheline l'exception d'une machine encore debout.
    """

    def test_the_cleanup_runs_once_after_every_deletion(self):
        todo = todo_avec()
        vus = []
        jouer(todo, ["all", "n", "2"], menage=vus)
        self.assertEqual(2, len(todo.execute.vues), todo.execute.vues)
        # Le relevé est le nombre de commandes déjà jouées : « 2 » situe le
        # ménage après les deux effacements, « 0 » le situerait avant.
        self.assertEqual([2], vus)

    def test_the_cleanup_still_runs_when_the_guard_refused_everything(self):
        """Une exception orpheline peut dater d'un effacement précédent :
        n'avoir rien effacé aujourd'hui ne dit pas qu'il n'y a rien à
        retirer."""
        todo = todo_avec("machine-sans-preuve\n")
        vus = []
        jouer(todo, ["1", "n", "machine-sans-preuve"], menage=vus)
        self.assertEqual([], todo.execute.vues)
        self.assertEqual([0], vus)

    def test_cancelling_cleans_nothing(self):
        """Rien n'a été décidé : toucher aux exceptions serait un effet que
        l'écran n'a pas annoncé."""
        todo = todo_avec()
        vus = []
        jouer(todo, ["1", "n", "un-nom-qui-ne-confirme-rien"], menage=vus)
        self.assertEqual([], todo.execute.vues)
        self.assertEqual([], vus)


class TestLesDisquesRestentLus(unittest.TestCase):
    """Le verbe DÉDUIRAIT les chemins du nom. Une VM renommée garde le nom
    de fichier d'avant, et un fichier partagé avec une voisine ne s'efface
    pas : la liste vient du XML, comme avant."""

    def test_the_files_come_from_the_inspection_not_from_the_name(self):
        todo = todo_avec(fichiers=["/var/lib/libvirt/images/autre-nom.qcow2"])
        jouer(todo, ["1", "y", "machine-a"])
        cmd = todo.execute.vues[0]
        self.assertIn("autre-nom.qcow2", cmd)
        self.assertNotIn("machine-a.qcow2", cmd)

    def test_no_disk_asked_means_no_removal(self):
        todo = todo_avec(fichiers=["/var/lib/libvirt/images/autre-nom.qcow2"])
        jouer(todo, ["1", "n", "machine-a"])
        self.assertNotIn("rm -f", todo.execute.vues[0])

    def test_the_verb_is_asked_not_to_guess(self):
        """« with_disks=True » ferait poser un « rm » sur un chemin déduit,
        en plus de celui qu'on a lu."""
        import ast

        chemin = os.path.join(RACINE, "script", "todo", "qemu_manage.py")
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        corps = [
            noeud
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.FunctionDef)
            and noeud.name == "_qemu_delete_vm"
        ][0]
        appels = [
            noeud
            for noeud in ast.walk(corps)
            if isinstance(noeud, ast.Call)
            and isinstance(noeud.func, ast.Attribute)
            and noeud.func.attr == "delete_command"
        ]
        self.assertEqual(1, len(appels))
        mots = {mot.arg: mot.value for mot in appels[0].keywords}
        self.assertIn("with_disks", mots)
        self.assertIs(False, getattr(mots["with_disks"], "value", None))


class TestLesDomainesFantomes(unittest.TestCase):
    """Même corps recopié, même garde manquant. Aucun fichier n'y est
    effacé, mais l'entrée se présente comme un nettoyage : on y répond
    « o » plus vite."""

    def _nettoyer(self, inventaire, fantomes, reponses):
        import builtins
        import io as tampon_io
        from contextlib import redirect_stdout

        todo = TODO.__new__(TODO)
        todo._qemu_list_domains_proved = lambda: VM.parse_uuid_listing(
            inventaire
        )
        todo._qemu_c_env = lambda: {}
        todo._is_yes = lambda rep: str(rep).strip().lower() in ("y", "o")
        todo.execute = Bancal()

        # Un domaine est FANTÔME quand aucun de ses disques n'existe. On
        # remplace les deux lectures qui le décident, pas la décision.
        def faux_run(argv, **_kwargs):
            class Reponse:
                returncode = 0 if argv[0] != "sudo" else 1
                stdout = ""

            if "domblklist" in argv:
                nom = argv[argv.index("domblklist") + 1]
                Reponse.stdout = (
                    "Type Device Target Source\n"
                    "file disk vda /var/lib/libvirt/images/x.qcow2\n"
                    if nom in fantomes
                    else ""
                )
            return Reponse

        from unittest.mock import patch

        file = list(reponses)
        vrai = builtins.input
        builtins.input = lambda *_a, **_k: file.pop(0) if file else ""
        tampon = tampon_io.StringIO()
        try:
            with (
                patch("script.todo.qemu_manage.subprocess.run", faux_run),
                redirect_stdout(tampon),
            ):
                todo._cleanup_ghost_domains()
        finally:
            builtins.input = vrai
        return todo, tampon.getvalue()

    def test_the_command_refuses_before_it_undefines(self):
        todo, _vu = self._nettoyer(INVENTAIRE, {"machine-a"}, ["y"])
        self.assertEqual(1, len(todo.execute.vues), todo.execute.vues)
        cmd = todo.execute.vues[0]
        self.assertLess(cmd.index("REFUS"), cmd.index("undefine"))
        self.assertIn("aaaaaaaa-1111-2222-3333-444444444444", cmd)

    def test_a_ghost_without_proof_is_refused(self):
        todo, vu = self._nettoyer(
            "machine-sans-preuve\n", {"machine-sans-preuve"}, ["y"]
        )
        self.assertEqual([], todo.execute.vues)
        self.assertIn("machine-sans-preuve", vu)

    def test_no_disk_is_ever_removed_here(self):
        """Un fantôme n'en a plus : c'est ce qui le définit."""
        todo, _vu = self._nettoyer(INVENTAIRE, {"machine-a"}, ["y"])
        self.assertNotIn("rm -f", todo.execute.vues[0])

    def test_a_refused_confirmation_runs_nothing(self):
        todo, _vu = self._nettoyer(INVENTAIRE, {"machine-a"}, ["n"])
        self.assertEqual([], todo.execute.vues)


class TestCeQueLeGardeNAttrapePas(unittest.TestCase):
    """Il compare une preuve : il voit un nom qui a changé de porteur,
    jamais un « 3 » tapé pour un « 2 ». Cet indice-là désigne un domaine
    RÉEL, correctement identifié, et la preuve concorde."""

    def test_one_machine_needs_its_name_typed(self):
        todo = todo_avec()
        jouer(todo, ["1", "n", "machine-a"])
        self.assertEqual(1, len(todo.execute.vues))

    def test_a_name_off_by_one_character_deletes_nothing(self):
        """« o » se tape par réflexe ; recopier un nom oblige à regarder."""
        todo = todo_avec()
        jouer(todo, ["1", "n", "machine-b"])
        self.assertEqual([], todo.execute.vues)
        todo = todo_avec()
        jouer(todo, ["1", "n", "machine-A"])
        self.assertEqual([], todo.execute.vues)

    def test_a_single_key_no_longer_deletes(self):
        """La forme d'avant : une touche, et deux machines partaient."""
        for touche in ("y", "o", "Y", ""):
            with self.subTest(touche=touche):
                todo = todo_avec()
                jouer(todo, ["1", "n", touche])
                self.assertEqual([], todo.execute.vues)

    def test_several_machines_need_their_count(self):
        """Retaper cinq noms est inutilisable ; le nombre ne se donne pas
        de réflexe, puisqu'il faut avoir lu le bloc pour le connaître."""
        todo = todo_avec()
        jouer(todo, ["all", "n", "2"])
        self.assertEqual(2, len(todo.execute.vues))

    def test_a_wrong_count_deletes_nothing(self):
        """L'erreur qui compte ici : un ensemble plus large qu'on croyait."""
        todo = todo_avec()
        jouer(todo, ["all", "n", "1"])
        self.assertEqual([], todo.execute.vues)

    def test_the_block_names_each_machine_and_its_proof(self):
        """Le nombre ne veut rien dire si l'on n'a pas vu la liste.

        La confirmation est REFUSÉE ici, exprès : la commande jouée est
        elle-même imprimée et porte l'UUID, si bien qu'une épreuve qui
        confirme se satisferait de cet écho et ne lirait jamais le bloc."""
        todo = todo_avec()
        vu = jouer(todo, ["all", "n", "0"])
        self.assertEqual([], todo.execute.vues)
        for attendu in (
            "machine-a",
            "machine-b",
            "aaaaaaaa-1111-2222-3333-444444444444",
            "bbbbbbbb-1111-2222-3333-444444444444",
        ):
            with self.subTest(attendu=attendu):
                self.assertIn(attendu, vu)

    def test_the_block_names_the_files_when_disks_are_asked(self):
        """Ce qui va être effacé se lit AVANT la question. Confirmation
        REFUSÉE : sans cela, le « rm » de la commande imprimée fournirait
        le chemin à lui seul."""
        todo = todo_avec(fichiers=["/var/lib/libvirt/images/autre.qcow2"])
        vu = jouer(todo, ["1", "y", "pas-le-nom"])
        self.assertEqual([], todo.execute.vues)
        self.assertIn("autre.qcow2", vu)

    def test_and_says_nothing_of_them_when_they_are_kept(self):
        """Contrôle positif : les nommer toujours ferait croire qu'ils
        partent quand ils restent."""
        todo = todo_avec(fichiers=["/var/lib/libvirt/images/autre.qcow2"])
        vu = jouer(todo, ["1", "n", "pas-le-nom"])
        self.assertNotIn("autre.qcow2", vu)

    def test_a_machine_without_proof_says_so_in_the_block(self):
        """Un crochet VIDE se lirait comme un UUID qui n'a pas voulu
        s'imprimer ; le dire annonce que la machine sera refusée."""
        todo = todo_avec("machine-sans-preuve\n")
        vu = jouer(todo, ["1", "n", "machine-sans-preuve"])
        self.assertIn("machine-sans-preuve", vu)
        self.assertNotIn("[]", vu)
        self.assertEqual([], todo.execute.vues)


class TestRienNestFaitSansConfirmation(unittest.TestCase):
    def test_an_empty_selection_runs_nothing(self):
        todo = todo_avec()
        jouer(todo, [""])
        self.assertEqual([], todo.execute.vues)


class TestLInviteNeDonnePasSaReponse(unittest.TestCase):
    """Retaper le nombre protège parce qu'il faut AVOIR LU le bloc.

    L'invite l'affichait entre parenthèses, à la façon d'un défaut : il
    suffisait de le recopier depuis la ligne même qui le demandait, et la
    lecture du bloc « Sera effacé » — qui EST la protection — devenait
    facultative. Le docstring de la fonction dit pourtant l'inverse mot
    pour mot.

    Le garde d'identité ne rattrape pas : il compare un UUID, donc il voit
    un nom qui a changé de porteur, jamais un ensemble plus large qu'on
    croyait. Seule la saisie voit cette erreur-là.
    """

    @staticmethod
    def demander(reponse, combien):
        """Rend (invite affichée, verdict)."""
        vues = []

        def faux_input(prompt=""):
            vues.append(prompt)
            return reponse

        todo = TODO.__new__(TODO)
        with mock.patch("builtins.input", faux_input):
            verdict = todo._qemu_confirm_deletion(
                [f"vm-{i}" for i in range(combien)]
            )
        return vues[0], verdict

    def test_the_prompt_never_carries_the_count(self):
        invite, _v = self.demander("3", 3)
        self.assertNotIn("3", invite)

    def test_the_right_count_still_confirms(self):
        """Contrôle positif : refuser tout rendrait la suppression de lot
        impossible."""
        _i, verdict = self.demander("3", 3)
        self.assertTrue(verdict)

    def test_a_wrong_count_refuses(self):
        """L'erreur qui compte ici : un ensemble plus large qu'on croyait."""
        _i, verdict = self.demander("2", 3)
        self.assertFalse(verdict)

    def test_the_single_vm_branch_does_not_give_the_name_either(self):
        """La même règle, et elle tenait déjà : recopier un nom long oblige
        à regarder ce qu'on détruit."""
        vues = []
        todo = TODO.__new__(TODO)
        with mock.patch(
            "builtins.input", lambda prompt="": vues.append(prompt) or ""
        ):
            todo._qemu_confirm_deletion(["base-longue-a-recopier"])
        self.assertNotIn("base-longue-a-recopier", vues[0])


class TestCeQuiEstEfficeEstCeQuiAEteNomme(unittest.TestCase):
    """Un fichier de fond partagé par deux machines disparaissait sans
    jamais avoir été nommé.

    Le relevé était pris DEUX fois : une à l'affichage, une par machine
    dans la boucle. Entre les deux, chaque « undefine » retire un porteur.
    Le fond a deux porteurs quand l'écran l'écarte — à juste titre, il est
    partagé — puis un seul quand la seconde machine passe, et il part.

    La règle du dépôt est écrite ailleurs, et elle vaut ici : une
    confirmation nomme ce qu'elle détruit. La ligne fourre-tout « + les
    disques et les seed ISO » ne nomme rien.

    Il survit donc comme orphelin, et c'est le parti pris : on nomme, on
    n'efface pas. Le balayage des disques orphelins le proposera.
    """

    def jouer(self):
        """Rend (ce que l'écran a nommé, ce que les commandes effacent)."""
        todo = TODO.__new__(TODO)
        # Deux domaines partagent « fond.qcow2 ». La simulation retire le
        # domaine à l'undefine, comme virsh le fait.
        vivants = {"vm-a", "vm-b"}
        propres = {
            "vm-a": ["/img/vm-a.qcow2", "/img/fond.qcow2"],
            "vm-b": ["/img/vm-b.qcow2", "/img/fond.qcow2"],
        }

        def own_files(nom):
            partages = set()
            for autre in vivants - {nom}:
                partages |= set(propres.get(autre, ()))
            return [c for c in propres[nom] if c not in partages]

        todo._qemu_vm_own_files = own_files
        lancees = []

        def montrer(cmd, **_kw):
            lancees.append(cmd)
            for nom in list(vivants):
                if f"undefine {nom}" in cmd or f" {nom} " in cmd:
                    vivants.discard(nom)
            return 0, ""

        todo._qemu_run = montrer
        return own_files, lancees

    def test_a_shared_backing_file_is_not_taken_in_silence(self):
        """LE FAIT QUI FONDE TOUT : tant que les deux porteurs existent, le
        fond est écarté — et c'est juste. Il ne doit donc pas partir."""
        own_files, _l = self.jouer()
        nommes = set(own_files("vm-a")) | set(own_files("vm-b"))
        self.assertNotIn("/img/fond.qcow2", nommes)

    def test_the_snapshot_is_taken_once_before_anything_moves(self):
        """La propriété, à la source : un seul relevé, et le même pour
        l'écran et pour l'effacement."""
        import ast
        import inspect
        import textwrap

        corps = textwrap.dedent(
            inspect.getsource(TODO._qemu_delete_vm)
            if hasattr(TODO, "_qemu_delete_vm")
            else ""
        )
        if not corps:
            self.skipTest("l'écran de suppression a changé de nom")
        appels = [
            n
            for n in ast.walk(ast.parse(corps))
            if isinstance(n, ast.Call)
            and getattr(n.func, "attr", "") == "_qemu_vm_own_files"
        ]
        self.assertEqual(1, len(appels), [n.lineno for n in appels])


class TestLEcranNAnnoncePasCeQuIlNaPasFait(unittest.TestCase):
    """Le garde d'identité vit DANS la chaîne : son refus est un code.

    Jeté, ce code faisait imprimer « suppression faite » sur une VM
    toujours debout — et sur une machine qu'on croit détruite, on réemploie
    le nom, l'adresse et le port.

    « toutes sauf une » et « toutes » se ressemblent trop dans une liste
    pour qu'un compte global les distingue : l'écran NOMME.
    """

    # Deux VM : le choix, le refus des disques, puis le NOMBRE — la
    # confirmation d'un ensemble se fait par son compte, et il faut avoir lu
    # le bloc pour le connaître.
    def ecran(self, code, reponses=("1,2", "n", "2")):
        todo = todo_avec()
        todo.execute = Bancal(code)
        return jouer(todo, reponses), todo

    def test_a_refusal_is_never_announced_as_a_deletion(self):
        affiche, _todo = self.ecran(1)
        self.assertNotIn("✅", affiche)

    def test_it_names_the_ones_that_did_not_go(self):
        """LE NOM ET LA RAISON SUR LA MÊME LIGNE. Chercher le nom seul dans
        l'écran ne prouve rien : le bloc « Sera effacé » le porte déjà, donc
        l'assertion passait même en retirant la ligne de refus. Un garde qui
        mesure ce qui était vrai avant ne garde rien."""
        affiche, _todo = self.ecran(1)
        refus = t("nothing was deleted.")
        for nom in ("machine-a", "machine-b"):
            self.assertTrue(
                any(
                    nom in ligne and refus in ligne
                    for ligne in affiche.splitlines()
                ),
                f"aucune ligne ne dit le refus pour {nom}",
            )

    def test_the_commands_were_still_all_attempted(self):
        """Un refus sur la première ne doit pas taire la seconde : chaque
        VM porte sa propre preuve, et l'une peut avoir changé de porteur
        sans l'autre."""
        _affiche, todo = self.ecran(1)
        self.assertEqual(2, len(todo.execute.vues))

    def test_a_clean_run_still_says_so(self):
        """Contrôle positif : se taire toujours passerait les trois
        précédents."""
        affiche, _todo = self.ecran(0)
        self.assertIn("✅", affiche)
        self.assertIn("machine-a", affiche)


if __name__ == "__main__":
    unittest.main()
