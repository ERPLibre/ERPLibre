#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les paquets qui fournissent les outils de la réduction sûre.

La réduction d'un disque de VM refuse de partir sans huit binaires. Le nom du
binaire n'est presque jamais celui du paquet, et il change de famille en
famille : sgdisk vit dans « gdisk » chez Debian et Fedora, dans « gptfdisk »
chez Arch et openSUSE. Une table pareille se démode sans bruit — un trou n'y
fait rien planter, il fait juste proposer une installation qui n'installe pas
ce qui manque.

Ce qui se vérifie ici sans VM et sans toucher au système : que chaque outil a
un paquet dans les quatre familles, que la commande construite est celle du
gestionnaire présent, que les paquets ne sont pas demandés deux fois, et qu'un
refus comme un échec laissent l'appelant renoncer plutôt que continuer sans
ses outils.
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402
from script.todo import qemu_manage  # noqa: E402
from script.todo import todo_install  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

FAMILIES = ("apt-get", "dnf", "pacman", "zypper")


class _Exec:
    """Le lanceur de commandes, qui retient au lieu d'exécuter."""

    def __init__(self, status=0):
        self.ran = []
        self.status = status

    def exec_command_live(self, cmd, source_erplibre=False):
        self.ran.append(cmd)
        return self.status


class ShrinkToolsBase(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.todo.execute = _Exec()

    def _which(self, package_manager, missing, installed_after=()):
        """shutil.which vu depuis qemu_manage : un seul gestionnaire de
        paquets sur le PATH, et les outils manquants qui le restent tant que
        l'installation n'a pas tourné."""
        done = self.todo.execute

        def which(binaire):
            if binaire in FAMILIES:
                return (
                    f"/usr/bin/{binaire}"
                    if binaire == package_manager
                    else None
                )
            if binaire in missing:
                if done.ran and binaire in installed_after:
                    return f"/usr/bin/{binaire}"
                return None
            return f"/usr/bin/{binaire}"

        return which

    def _run(self, package_manager, missing, answer="y", installed_after=()):
        which = self._which(package_manager, missing, installed_after)
        buf = io.StringIO()

        # input() écrit son invite sur stdout comme le vrai : sans cela la
        # question n'apparaît nulle part et l'ORDRE des deux ne se voit pas.
        def demande(invite=""):
            print(invite, end="")
            return answer

        # `shutil` est UN seul objet module partagé : patcher son « which »
        # par n'importe quel importateur le patche pour todo_install aussi,
        # qui est le vrai lecteur du PATH depuis le refactor.
        with patch("script.todo.qemu_manage.shutil.which", which), patch(
            "builtins.input", demande
        ), redirect_stdout(buf):
            left = self.todo._qemu_install_shrink_tools(list(missing))
        return self.todo.execute.ran, left, buf.getvalue()


class TestPackageTable(ShrinkToolsBase):
    def test_every_tool_has_a_package_in_every_family(self):
        """Un trou ne plante pas : il propose une installation inutile."""
        for family in FAMILIES:
            per_family = TODO._SHRINK_PKG_FAMILY[family]
            for binaire in TODO._SHRINK_TOOLS:
                paquet = per_family.get(binaire) or TODO._SHRINK_PKG.get(
                    binaire
                )
                self.assertTrue(
                    paquet,
                    f"{family} : aucun paquet connu pour « {binaire} »",
                )

    def test_the_overrides_cover_every_system_family(self):
        """Une famille système sans surcharge ici proposerait « gdisk » à
        un Arch, qui ne l'a pas."""
        systeme = {
            f
            for f in todo_install.FAMILIES
            if f not in todo_install.USER_LEVEL
        }
        self.assertEqual(set(TODO._SHRINK_PKG_FAMILY), systeme)
        self.assertEqual(systeme, set(FAMILIES))

    def test_a_user_level_family_is_deliberately_absent(self):
        """L'omission est AFFIRMÉE, pas laissée en creux. Ces deux outils
        découpent un qcow2 que libvirt monte en local, et cette pile
        n'existe pas là où le gestionnaire est celui d'un utilisateur — y
        nommer un paquet laisserait croire que le rétrécissement s'y fait."""
        self.assertTrue(todo_install.USER_LEVEL)
        for famille in todo_install.USER_LEVEL:
            with self.subTest(famille=famille):
                self.assertNotIn(famille, TODO._SHRINK_PKG_FAMILY)

    def test_sgdisk_is_the_one_that_changes_name(self):
        """Le cas qui a motivé la table, gardé explicitement."""
        noms = {f: TODO._SHRINK_PKG_FAMILY[f]["sgdisk"] for f in FAMILIES}
        self.assertEqual(noms["apt-get"], "gdisk")
        self.assertEqual(noms["dnf"], "gdisk")
        self.assertEqual(noms["pacman"], "gptfdisk")
        self.assertEqual(noms["zypper"], "gptfdisk")

    def test_no_family_override_repeats_the_common_table(self):
        """Un doublon entre les deux tables est une divergence en attente."""
        for family in FAMILIES:
            for binaire in TODO._SHRINK_PKG_FAMILY[family]:
                self.assertNotIn(
                    binaire,
                    TODO._SHRINK_PKG,
                    f"{family} : « {binaire} » est dans les deux tables",
                )


class TestInstallCommand(ShrinkToolsBase):
    def test_each_family_builds_its_own_command(self):
        attendu = {
            "apt-get": "sudo apt-get install -y gdisk",
            "dnf": "sudo dnf install -y gdisk",
            "pacman": "sudo pacman -S --needed --noconfirm gptfdisk",
            "zypper": "sudo zypper --non-interactive install gptfdisk",
        }
        for family, cmd in attendu.items():
            self.setUp()
            ran, left, _ = self._run(
                family, ["sgdisk"], installed_after=("sgdisk",)
            )
            self.assertEqual(ran, [cmd])
            self.assertEqual(left, [])

    def test_a_package_is_asked_for_once(self):
        """e2fsck, resize2fs et dumpe2fs sortent du même paquet."""
        ran, _, _ = self._run(
            "apt-get",
            ["e2fsck", "resize2fs", "dumpe2fs", "sgdisk"],
            installed_after=("e2fsck", "resize2fs", "dumpe2fs", "sgdisk"),
        )
        self.assertEqual(ran, ["sudo apt-get install -y e2fsprogs gdisk"])

    def test_the_command_is_shown_before_the_question(self):
        """On approuve ce qu'on a lu : la commande passe AVANT la question.

        L'ordre est le fond de l'affaire, pas la simple présence des deux :
        une question posée avant la commande fait approuver à l'aveugle.
        """
        ran, _, out = self._run("apt-get", ["sgdisk"], answer="n")
        commande = out.index("sudo apt-get install -y gdisk")
        question = out.index(t("Install them? (y/N): "))
        self.assertLess(commande, question)
        self.assertEqual(ran, [])


class TestGivingUp(ShrinkToolsBase):
    def test_a_refusal_installs_nothing_and_keeps_the_list(self):
        ran, left, _ = self._run("apt-get", ["sgdisk"], answer="n")
        self.assertEqual(ran, [])
        self.assertEqual(left, ["sgdisk"])

    def test_an_unknown_package_manager_gives_up(self):
        ran, left, _ = self._run("brew", ["sgdisk"])
        self.assertEqual(ran, [])
        self.assertEqual(left, ["sgdisk"])

    def test_the_list_is_re_read_from_disk_not_assumed(self):
        """Une installation qui ne pose rien doit rester un échec."""
        ran, left, _ = self._run("apt-get", ["sgdisk"], installed_after=())
        self.assertEqual(len(ran), 1)
        self.assertEqual(left, ["sgdisk"])

    def test_a_failing_install_is_reported_and_not_swallowed(self):
        """exec_command_live REND le code de sortie, il ne lève rien."""
        self.todo.execute = _Exec(status=100)
        ran, left, out = self._run("apt-get", ["sgdisk"])
        self.assertEqual(len(ran), 1)
        self.assertEqual(left, ["sgdisk"])
        self.assertIn("100", out)


class TestUnFsckQuiAEcritNEstPasRien(unittest.TestCase):
    """« e2fsck -f -y » RÉPARE : il écrit, et « -y » répond oui à tout.

    Deux abandons qui viennent APRÈS lui déclaraient pourtant
    « changed=False ». Or ce drapeau décide du sort de la sauvegarde : à
    faux, elle est SUPPRIMÉE comme inutile. Le disque restait donc tel que
    fsck l'avait laissé, et la seule copie d'avant partait avec.

    Les trois abandons qui précèdent le fsck gardent « False » à juste
    titre : là, rien n'a touché le disque, et garder une sauvegarde
    inutile encombrerait le répertoire d'images à chaque essai.
    """

    RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

    @classmethod
    def corps(cls):
        import ast

        chemin = os.path.join(cls.RACINE, "script", "todo", "qemu_manage.py")
        source = open(chemin, encoding="utf-8").read()
        for noeud in ast.walk(ast.parse(source)):
            if (
                isinstance(noeud, ast.FunctionDef)
                and noeud.name == "_qemu_safe_shrink"
            ):
                return source.splitlines(), noeud
        raise AssertionError("_qemu_safe_shrink introuvable")

    def premier_fsck(self, lignes, fonction):
        """La ligne du PREMIER fsck de la fonction.

        DÉRIVÉE, et c'est la correction d'un piège. Le contrôle positif
        d'en dessous bornait son intervalle par un numéro de ligne ÉCRIT EN
        DUR : une modification quelconque plus haut dans le fichier
        décalait la fonction sous cette borne, l'intervalle devenait vide,
        et le test rougissait sur un changement qui ne le concernait pas.
        Un garde qui rougit à tort est un garde qu'on apprend à désarmer.
        """
        fscks = [
            n
            for n in range(fonction.lineno, fonction.end_lineno + 1)
            if '"e2fsck"' in lignes[n - 1] and "subprocess" in lignes[n - 1]
        ]
        self.assertTrue(fscks, "le fsck a disparu de la réduction")
        return min(fscks)

    def test_no_abandon_after_the_fsck_claims_nothing_changed(self):
        """Le contrôle porte sur la POSITION, que rien d'autre ne tient :
        déplacer un abandon sous le fsck ne casse aucune autre épreuve."""
        import re

        lignes, fonction = self.corps()
        fautifs = [
            n
            for n in range(
                self.premier_fsck(lignes, fonction), fonction.end_lineno + 1
            )
            if re.search(r"changed=False", lignes[n - 1])
        ]
        self.assertEqual([], fautifs)

    def test_the_abandons_before_the_fsck_still_drop_the_backup(self):
        """Contrôle positif : tout passer à « True » ferait garder une
        sauvegarde inutile à chaque essai qui n'a rien touché."""
        import re

        lignes, fonction = self.corps()
        avant = [
            n
            for n in range(
                fonction.lineno, self.premier_fsck(lignes, fonction)
            )
            if re.search(r"changed=False", lignes[n - 1])
        ]
        self.assertTrue(avant, "plus aucun abandon ne rend la sauvegarde")


class TestLaRestaurationQuiEchoue(unittest.TestCase):
    """La réparation était ANNONCÉE et n'était jamais vérifiée.

    Une réduction qui casse à mi-parcours laisse un disque à moitié
    réduit, donc incohérent. L'écran disait « Restauration du disque
    d'origine depuis la sauvegarde… », puis lançait un « mv » dont
    PERSONNE ne lisait le code de retour, et rendait la même valeur qu'en
    cas de succès. L'appelant, ne pouvant distinguer les deux, enchaînait
    sur « Start the VM now? ».

    Quelqu'un qui répond oui démarre un disque cassé. Et la seule copie
    saine — la sauvegarde restée à côté — n'est jamais nommée.

    Le « mv » est un renommage dans le même répertoire : il ne peut pas
    manquer de place. Ce qui le fait échouer, c'est un jeton sudo expiré
    en cours d'opération — un e2fsck suivi d'un resize2fs sur un gros
    disque dépasse les quinze minutes par défaut — ou un remontage en
    lecture seule après l'erreur d'E/S qui a fait échouer la réduction.
    """

    def menu(self):
        todo = TODO.__new__(TODO)
        todo._is_yes = lambda rep: (rep or "").strip().lower() in ("o", "y")
        return todo

    def revert(self, code_mv, changed=True, bak="/d/vm.qcow2.bak"):
        todo = self.menu()
        lances = []

        def faux_run(argv, **_k):
            lances.append(argv)

            class R:
                returncode = code_mv

            return R()

        with patch.object(qemu_manage.subprocess, "run", faux_run):
            tampon = io.StringIO()
            with redirect_stdout(tampon):
                rendu = todo._qemu_shrink_revert(bak, "/d/vm.qcow2", changed)
        return todo, rendu, tampon.getvalue(), lances

    def test_a_successful_restore_says_so(self):
        """L'écran annonce la restauration puis se tait : sans un mot de
        fin, rien ne distingue une restauration faite d'une interrompue."""
        _t, rendu, ecran, lances = self.revert(0)
        self.assertFalse(rendu)
        self.assertTrue(any("mv" in a for a in lances))
        self.assertIn(t("Original disk restored from backup."), ecran)

    def test_a_failed_restore_is_named_and_names_the_backup(self):
        """C'est la seule copie saine : ne pas la nommer laisse la
        détruire au prochain nettoyage."""
        _t, _r, ecran, _l = self.revert(1)
        self.assertIn("✗", ecran)
        self.assertIn("/d/vm.qcow2.bak", ecran)

    def test_a_failed_restore_forbids_the_offer_to_start(self):
        """L'ENCHAÎNEMENT est le défaut : l'écran proposait de démarrer
        un disque qu'il venait de ne pas réparer."""
        todo, _r, _e, _l = self.revert(1)
        # `input` EST BOUCHONNÉ, et il doit rester INTACT : une épreuve
        # qui ne le bouchonne pas attend sur l'entrée standard — elle
        # rougit là où stdin est fermé, et FIGE dans un terminal. C'est
        # aussi ce qui prouve le contrat : la question n'est pas posée.
        saisie = MagicMock(return_value="")
        with patch("builtins.input", saisie):
            tampon = io.StringIO()
            with redirect_stdout(tampon):
                todo._qemu_offer_start("vm-essai", was_shut_down=True)
        saisie.assert_not_called()
        self.assertNotIn("Start the VM now?", tampon.getvalue())
        self.assertIn("✗", tampon.getvalue())

    def test_a_successful_restore_still_offers_to_start(self):
        """Contrôle positif : refuser toujours ferait perdre le service
        d'une VM qu'on a éteinte pour l'opération."""
        todo, _r, _e, _l = self.revert(0)
        saisies = iter(["n"])
        with patch("builtins.input", lambda *_a: next(saisies)):
            tampon = io.StringIO()
            with redirect_stdout(tampon):
                todo._qemu_offer_start("vm-essai", was_shut_down=True)
        self.assertIn(
            t("The VM was shut down for the resize."), tampon.getvalue()
        )

    def test_nothing_was_changed_so_nothing_is_restored(self):
        """Le disque est intact : le toucher serait le seul vrai risque."""
        _t, _r, ecran, lances = self.revert(0, changed=False)
        self.assertEqual([], [a for a in lances if "mv" in a])
        self.assertNotIn("✗", ecran)


class TestBackupSpace(unittest.TestCase):
    """La sauvegarde avant réduction, et la place qu'elle demande.

    Elle doublait l'occupation sans rien annoncer : sur un disque presque
    plein la copie s'arrête à mi-course et laisse un .bak tronqué, sur un
    système de fichiers désormais saturé. Les deux chiffres passent donc
    avant la question, et le défaut bascule quand la place manque — une
    entrée distraite ne doit pas remplir le disque.
    """

    GIB = 1 << 30

    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def test_the_need_is_the_allocated_size_not_the_apparent_one(self):
        """« cp --sparse=always » ne recopie pas les trous d'un qcow2 : un
        disque de 60 Go apparents mais 8 Go alloués ne demande que 8 Go."""
        faux = os.stat_result((0o644, 0, 0, 1, 0, 0, 60 * self.GIB, 0, 0, 0))
        # st_blocks n'est pas dans le tuple : on le pose à part.
        with patch("script.todo.qemu_manage.os.stat") as stat, patch(
            "script.todo.qemu_manage.shutil.disk_usage"
        ) as du:
            stat.return_value = type(
                "S", (), {"st_blocks": 8 * self.GIB // 512}
            )()
            du.return_value = type("U", (), {"free": 99 * self.GIB})()
            besoin, libre = TODO._qemu_backup_need_and_free("/x/d.qcow2")
        self.assertEqual(besoin, 8 * self.GIB)
        self.assertEqual(libre, 99 * self.GIB)
        self.assertNotEqual(besoin, faux.st_size)

    def _decision(self, besoin, libre, answer):
        """(question posée, sauvegarde retenue) — par le VRAI code.

        Ce helper appelle _qemu_ask_backup et ne réimplémente rien : une
        copie de la logique dans le test aurait laissé passer un défaut
        remis à OUI sans place, ce qui est précisément le défaut à garder.
        """
        vu = []

        def demande(invite=""):
            vu.append(invite)
            return answer

        with patch.object(
            TODO,
            "_qemu_backup_need_and_free",
            staticmethod(lambda d: (besoin, libre)),
        ), patch("builtins.input", demande), redirect_stdout(io.StringIO()):
            retenu = self.todo._qemu_ask_backup("/x/d.qcow2")
        return vu[-1], retenu

    def test_with_room_the_default_stays_yes(self):
        question, retenu = self._decision(12 * self.GIB, 40 * self.GIB, "")
        self.assertIn("(O/n", question)
        self.assertTrue(retenu)

    def test_without_room_the_default_flips_to_no(self):
        """Le cœur du correctif : entrée vide ne doit PAS remplir le disque."""
        question, retenu = self._decision(12 * self.GIB, 3 * self.GIB, "")
        self.assertIn("(y/N", question)
        self.assertFalse(retenu)

    def test_without_room_insisting_still_works(self):
        """On informe, on ne décide pas à la place de l'opérateur."""
        _, retenu = self._decision(12 * self.GIB, 3 * self.GIB, "y")
        self.assertTrue(retenu)

    def test_a_margin_guards_the_exactly_equal_case(self):
        """Une place égale au besoin n'en laisse aucune : refusé."""
        _, retenu = self._decision(12 * self.GIB, 12 * self.GIB, "")
        self.assertFalse(retenu)


if __name__ == "__main__":
    unittest.main()
