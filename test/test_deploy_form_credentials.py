#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le compte de la VM, côté interface : formulaires TUI et invites en ligne.

Ce que ces tests tiennent :

- les deux écrans portent la section (compose_credentials) ;
- « Générer » change la valeur sans la démasquer, « Copier » la met dans
  App.clipboard, « Afficher » bascule le masque ;
- la case « garder » révèle le chemin du fichier et la commande qui le lit ;
- le mot de passe en clair n'entre ni dans la spec, ni dans l'historique, ni
  dans le vidage F9 : il sort par le rappel « vm_secret_sink » seul ;
- F5 refuse un utilisateur invalide ou un mot de passe vide ;
- les invites : défaut, génération écrite hors du journal, saisie getpass
  confirmée, option « garder ».

SONDE est un mot de passe inventé : on le cherche partout où il ne doit
pas être.
"""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.argv = ["todo.py"]
sys.path.insert(0, "test")

from async_case import AsyncCase  # noqa: E402

from script.todo.deploy_form_lib import (  # noqa: E402
    VM_PASSWORD_ALPHABET,
    VM_PASSWORD_DEFAULT,
    VM_LOGIN_FILE,
    VM_PASSWORD_LENGTH,
    VM_LOGIN_READ_CMD,
    VM_USER_DEFAULT,
    t,
    vm_login_value_error,
)
from script.todo.todo import TODO  # noqa: E402

try:
    import textual  # noqa: F401

    TEXTUAL = True
except Exception:  # pragma: no cover - dépend de l'environnement
    TEXTUAL = False

SONDE = "Kp4formeTw"


def todo_muet():
    todo = TODO.__new__(TODO)
    todo._qemu_list_domains = lambda: []
    todo._qemu_branch_list = lambda: ["develop", "master"]
    return todo


def contexte_qemu(todo):
    ctx = todo._qemu_form_context(todo._qemu_import_module())
    ctx["free_disk"] = 500
    ctx["total_disk"] = 900
    ctx["free_ram"] = 64000
    ctx["host_cpu"] = 8
    return ctx


def contexte_proxmox(puits):
    from proxmox_form_context import contexte

    ctx = contexte()
    ctx["vm_secret_sink"] = puits.append
    return ctx


class TestValidation(unittest.TestCase):
    def test_a_password_must_be_usable_on_one_line(self):
        self.assertIsNone(vm_login_value_error(SONDE))
        self.assertIsNotNone(vm_login_value_error(""))
        self.assertIsNotNone(vm_login_value_error("ab\tcd"))
        self.assertIsNotNone(vm_login_value_error("ab\x7fcd"))
        self.assertIsNotNone(vm_login_value_error("-option"))

    def test_the_help_names_the_section(self):
        """F1 décrit le compte sur les deux écrans : le bloc vient du socle
        partagé, sans condition de table."""
        from script.todo.deploy_form_extras import ExtrasMixin

        class Vide(ExtrasMixin):
            pass

        vide = Vide()
        vide.extras_init({})
        blocs = dict(vide.extras_help_blocks())
        self.assertIn(t("VM account"), blocs)
        self.assertIn(f"  {VM_LOGIN_READ_CMD}", blocs[t("VM account")])


class _Base(AsyncCase):
    """Un écran monté, une VM cochée."""

    FORME = "qemu"

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.todo = todo_muet()
        self.puits = []
        if self.FORME == "qemu":
            from script.todo.qemu_deploy_form import run_deploy_form

            self.ctx = contexte_qemu(self.todo)
            self.app = run_deploy_form(self.ctx, run_app=False)
        else:
            from script.todo.proxmox_deploy_form import run_proxmox_form

            self.app = run_proxmox_form(
                contexte_proxmox(self.puits), run_app=False
            )

    async def monte(self, pilote):
        from textual.widgets import SelectionList

        for _ in range(3):
            await pilote.pause()
        liste = self.app.query_one(SelectionList)
        liste.select(liste.get_option_at_index(0).value)
        for _ in range(3):
            await pilote.pause()

    def champ(self):
        return self.app.query_one("#f_password")

    async def appuie(self, pilote, selecteur):
        """Le bouton pris au clavier : le focus le fait défiler à l'écran,
        Entrée le presse et joue son action."""
        self.app.query_one(selecteur).focus()
        await pilote.pause()
        await pilote.press("enter")
        await pilote.pause()


class _Commun:
    """Les mêmes vérifications sur les deux écrans."""

    async def test_the_section_opens_on_the_public_default(self):
        app = self.app
        async with app.run_test(size=(200, 60)) as pilote:
            await self.monte(pilote)
            self.assertEqual(VM_PASSWORD_DEFAULT, self.champ().value)
            self.assertTrue(self.champ().password)
            self.assertEqual(
                VM_USER_DEFAULT, app.query_one("#f_vm_user").value
            )
            self.assertFalse(app.query_one("#keepnote").display)
            valeurs = app._form_values()
            self.assertEqual(VM_USER_DEFAULT, valeurs["user"])
            self.assertTrue(valeurs["login_default"])
            self.assertFalse(valeurs["keep_login_in_vm"])

    async def test_generate_changes_the_value_and_keeps_the_mask(self):
        app = self.app
        async with app.run_test(size=(200, 60)) as pilote:
            await self.monte(pilote)
            await self.appuie(pilote, "#f_pw_gen")
            valeur = self.champ().value
            self.assertNotEqual(VM_PASSWORD_DEFAULT, valeur)
            self.assertEqual(VM_PASSWORD_LENGTH, len(valeur))
            self.assertTrue(set(valeur) <= set(VM_PASSWORD_ALPHABET))
            self.assertTrue(self.champ().password)
            self.assertFalse(app._form_values()["login_default"])

    async def test_copy_fills_the_clipboard(self):
        app = self.app
        async with app.run_test(size=(200, 60)) as pilote:
            await self.monte(pilote)
            self.champ().value = SONDE
            await self.appuie(pilote, "#f_pw_copy")
            self.assertEqual(SONDE, app.clipboard)
            # La notification dit que c'est copié, sans répéter la valeur.
            textes = " ".join(str(n.message) for n in app._notifications)
            self.assertNotIn(SONDE, textes)

    async def test_show_toggles_the_mask(self):
        app = self.app
        async with app.run_test(size=(200, 60)) as pilote:
            await self.monte(pilote)
            bouton = app.query_one("#f_pw_show")
            await self.appuie(pilote, "#f_pw_show")
            self.assertFalse(self.champ().password)
            self.assertEqual(t("Hide"), str(bouton.label))
            # Un bouton ignore Entrée tant que dure son effet « -active ».
            await pilote.pause(bouton.active_effect_duration + 0.1)
            await self.appuie(pilote, "#f_pw_show")
            self.assertTrue(self.champ().password)
            self.assertEqual(t("Show"), str(bouton.label))

    async def test_keep_reveals_the_file_and_the_command(self):
        app = self.app
        async with app.run_test(size=(200, 60)) as pilote:
            await self.monte(pilote)
            note = app.query_one("#keepnote")
            app.query_one("#f_keep_pw").value = True
            await pilote.pause()
            self.assertTrue(note.display)
            texte = str(note.render())
            self.assertIn(VM_LOGIN_FILE, texte)
            self.assertIn(VM_LOGIN_READ_CMD, texte)
            self.assertTrue(app._form_values()["keep_login_in_vm"])
            app.query_one("#f_keep_pw").value = False
            await pilote.pause()
            self.assertFalse(note.display)

    async def test_the_history_never_holds_the_password(self):
        app = self.app
        async with app.run_test(size=(200, 60)) as pilote:
            await self.monte(pilote)
            app._hist_settle()
            avant = len(app._hist.entries)
            self.champ().focus()
            for lettre in "xy":
                await pilote.press(lettre)
            self.champ().value = SONDE
            await pilote.pause()
            app._hist_settle()
            # Une frappe dans le mot de passe ne crée aucune entrée.
            self.assertEqual(avant, len(app._hist.entries))
            self.assertNotIn("f_password", app._hist_snapshot()["widgets"])
            # L'utilisateur, lui, s'y lit sous son nom.
            app.query_one("#f_vm_user").value = "operateur"
            await pilote.pause()
            app._hist_settle()
            self.assertEqual(avant + 1, len(app._hist.entries))
            self.assertIn("operateur", app._hist.entries[-1]["label"])
            self.assertNotIn(SONDE, repr(app._hist.entries))

    async def test_the_spec_has_no_clear_password(self):
        app = self.app
        async with app.run_test(size=(200, 60)) as pilote:
            await self.monte(pilote)
            self.champ().value = SONDE
            await pilote.pause()
            valeurs = app._form_values()
            self.assertNotIn(SONDE, repr(valeurs))
            self.assertFalse(valeurs["login_default"])

    async def test_f5_refuses_an_invalid_user(self):
        app = self.app
        async with app.run_test(size=(200, 60)) as pilote:
            await self.monte(pilote)
            app.query_one("#f_vm_user").value = "root"
            app.action_deploy()
            await pilote.pause()
            self.assertTrue(app.is_running)
            self.assertIs(app.focused, app.query_one("#f_vm_user"))

    async def test_f5_refuses_an_empty_password(self):
        app = self.app
        async with app.run_test(size=(200, 60)) as pilote:
            await self.monte(pilote)
            self.champ().value = ""
            app.action_deploy()
            await pilote.pause()
            self.assertTrue(app.is_running)
            self.assertIs(app.focused, self.champ())


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestQemu(_Commun, _Base):
    FORME = "qemu"

    async def test_deploy_hands_the_secret_over_and_not_in_the_spec(self):
        app = self.app
        async with app.run_test(size=(200, 60)) as pilote:
            await self.monte(pilote)
            self.champ().value = SONDE
            app.action_deploy()
            await pilote.pause()
        spec = app._result["spec"]
        self.assertIsNotNone(spec)
        self.assertNotIn(SONDE, repr(spec))
        self.assertFalse(spec["login_default"])
        self.assertEqual(SONDE, self.todo._qemu_vm_secret)

    async def test_the_default_password_hands_over_nothing(self):
        app = self.app
        self.todo._qemu_vm_secret = "reste"
        async with app.run_test(size=(200, 60)) as pilote:
            await self.monte(pilote)
            app.action_deploy()
            await pilote.pause()
        self.assertTrue(app._result["spec"]["login_default"])
        self.assertIsNone(self.todo._qemu_vm_secret)

    async def test_cancel_drops_a_secret_the_preview_set(self):
        app = self.app
        async with app.run_test(size=(200, 60)) as pilote:
            await self.monte(pilote)
            self.champ().value = SONDE
            app.hand_over_vm_secret()
            self.assertEqual(SONDE, self.todo._qemu_vm_secret)
            app.action_cancel()
            await pilote.pause()
        self.assertIsNone(self.todo._qemu_vm_secret)

    async def test_the_preview_shows_a_hash_not_the_password(self):
        """F3 passe par le constructeur du déploiement : il reçoit le clair
        en mémoire et n'en montre que l'empreinte."""
        app = self.app
        construire = self.ctx["build_command"]
        lignes = []
        self.ctx["build_command"] = (
            lambda vm, spec, dry: lignes.append(construire(vm, spec, dry))
            or lignes[-1]
        )
        async with app.run_test(size=(200, 60)) as pilote:
            await self.monte(pilote)
            self.champ().value = SONDE
            app.action_preview()
            await pilote.pause()
        texte = "\n".join(lignes)
        self.assertTrue(lignes)
        self.assertIn("--password-hash", texte)
        self.assertNotIn(SONDE, texte)
        self.assertNotIn("--password ", texte)

    async def test_a_hash_failure_keeps_the_screen_open(self):
        """openssl en échec : F3 le dit en notification, l'écran reste
        ouvert, et le message ne cite pas le mot de passe."""
        app = self.app
        mod = self.todo._qemu_import_module()
        echec = subprocess.CalledProcessError(1, ["openssl", "passwd"])
        with mock.patch.object(mod, "hash_password", side_effect=echec):
            async with app.run_test(size=(200, 60)) as pilote:
                await self.monte(pilote)
                self.champ().value = SONDE
                app.action_preview()
                await pilote.pause()
                self.assertTrue(app.is_running)
                erreurs = [
                    str(n.message)
                    for n in app._notifications
                    if n.severity == "error"
                ]
        self.assertTrue(erreurs)
        self.assertIn("CalledProcessError", erreurs[-1])
        self.assertNotIn(SONDE, " ".join(erreurs))

    async def test_the_dump_never_holds_the_password(self):
        app = self.app
        with tempfile.TemporaryDirectory() as home:
            with mock.patch.dict(os.environ, {"HOME": home}):
                async with app.run_test(size=(200, 60)) as pilote:
                    await self.monte(pilote)
                    self.champ().value = SONDE
                    app.action_dump_state()
                    await pilote.pause()
                chemin = os.path.join(
                    home, ".erplibre", "deploy-form-dump.txt"
                )
                with open(chemin, encoding="utf-8") as fh:
                    texte = fh.read()
        self.assertNotIn(SONDE, texte)
        self.assertIn("mdp_defaut=False", texte)


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestProxmox(_Commun, _Base):
    FORME = "proxmox"

    async def test_deploy_hands_the_secret_over_and_not_in_the_spec(self):
        app = self.app
        async with app.run_test(size=(200, 60)) as pilote:
            await self.monte(pilote)
            self.champ().value = SONDE
            app.action_deploy()
            await pilote.pause()
        self.assertIsNotNone(app.result)
        self.assertNotIn(SONDE, repr(app.result))
        self.assertEqual([SONDE], self.puits)

    async def test_cancel_drops_the_secret(self):
        app = self.app
        async with app.run_test(size=(200, 60)) as pilote:
            await self.monte(pilote)
            app.action_cancel()
            await pilote.pause()
        self.assertEqual([None], self.puits)

    async def test_a_hash_failure_keeps_the_screen_open(self):
        from script.todo.proxmox_deploy_form import run_proxmox_form

        ctx = contexte_proxmox(self.puits)
        message = t("Cannot compute the VM password hash: {reason}").format(
            reason="openssl"
        )

        def construit(vm, spec):
            raise RuntimeError(message)

        ctx["build_command"] = construit
        app = self.app = run_proxmox_form(ctx, run_app=False)
        async with app.run_test(size=(200, 60)) as pilote:
            await self.monte(pilote)
            app.action_preview()
            await pilote.pause()
            self.assertTrue(app.is_running)
            erreurs = [
                str(n.message)
                for n in app._notifications
                if n.severity == "error"
            ]
        self.assertEqual([message], erreurs)


class TestLesInvites(unittest.TestCase):
    """_qemu_ask_vm_account : ce que rendent les invites, et où va le
    clair."""

    def _demande(self, reponses, saisies=()):
        todo = TODO.__new__(TODO)
        sortie, origine = io.StringIO(), io.StringIO()
        reponses, saisies = iter(reponses), iter(saisies)
        with (
            mock.patch("builtins.input", lambda *a: next(reponses)),
            mock.patch("getpass.getpass", lambda *a: next(saisies)),
            mock.patch("sys.stdout", sortie),
            mock.patch("sys.__stdout__", origine),
        ):
            rendu = todo._qemu_ask_vm_account()
        return todo, rendu, sortie.getvalue(), origine.getvalue()

    def test_enter_everywhere_keeps_the_defaults(self):
        todo, rendu, _o, _n = self._demande(["", "", ""])
        self.assertEqual((VM_USER_DEFAULT, True, False), rendu)
        self.assertIsNone(todo._qemu_vm_secret)

    def test_an_invalid_user_is_asked_again(self):
        _t, rendu, sortie, _n = self._demande(["root", "operateur", "", ""])
        self.assertEqual("operateur", rendu[0])
        self.assertIn("root", sortie)

    def test_a_generated_password_is_shown_outside_the_journal(self):
        todo, rendu, sortie, origine = self._demande(["", "g", ""])
        secret = todo._qemu_vm_secret
        self.assertEqual(VM_PASSWORD_LENGTH, len(secret))
        self.assertFalse(rendu[1])
        self.assertIn(secret, origine)
        self.assertNotIn(secret, sortie)

    def test_a_typed_password_is_confirmed(self):
        todo, rendu, sortie, origine = self._demande(
            ["", "t", ""], [SONDE, "autre", SONDE, SONDE]
        )
        self.assertEqual(SONDE, todo._qemu_vm_secret)
        self.assertFalse(rendu[1])
        self.assertNotIn(SONDE, sortie + origine)

    def test_an_empty_typed_password_keeps_the_default(self):
        todo, rendu, _s, _o = self._demande(["", "t", ""], [""])
        self.assertIsNone(todo._qemu_vm_secret)
        self.assertTrue(rendu[1])

    def test_keep_names_the_command_that_reads_it(self):
        _t, rendu, sortie, _o = self._demande(["", "", "o"])
        self.assertTrue(rendu[2])
        self.assertIn(VM_LOGIN_READ_CMD, sortie)

    def test_the_recap_names_the_account_not_the_password(self):
        todo = TODO.__new__(TODO)
        todo._host_free_ram_mb = lambda: 0
        todo._qemu_image_lines = lambda spec: []
        todo._qemu_sudo_lines = lambda: []
        todo._qemu_vm_secret = SONDE
        spec = {
            "vms": [],
            "install": None,
            "ssh_key": "/k.pub",
            "add_ssh_config": False,
            "parallelism": 1,
            "user": "operateur",
            "login_default": False,
            "keep_login_in_vm": True,
        }
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            todo._qemu_print_recap(spec, [])
        self.assertIn("operateur", buf.getvalue())
        self.assertIn(VM_LOGIN_READ_CMD, buf.getvalue())
        self.assertNotIn(SONDE, buf.getvalue())


if __name__ == "__main__":
    unittest.main()
