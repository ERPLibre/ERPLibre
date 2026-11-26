#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu OpenTofu : entrées, confirmations, après-apply et outil `tofu`.

Chaque action se joue sur un TODO sans __init__, avec un moteur factice
inscrit sous le nom `tofu` le temps du test (la validation de la spec
n'accepte que ce moteur) et des parcs dans un dossier temporaire. HOME
pointe sur un dossier temporaire quand ~/.ssh/config est écrit. Aucun ssh,
aucun sudo, aucun réseau.

Valeurs inventées : hôtes en .invalid, adresses du bloc de documentation
192.0.2.0/24.
"""

import ast
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

DEPOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DEPOT))
sys.argv = ["todo.py"]

from script.opentofu import moteur as mo  # noqa: E402
from script.opentofu import spec as sp  # noqa: E402
from script.todo import opentofu_menu, todo_i18n  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

_LANGUE_ORIGINE = todo_i18n._current_lang
CIBLE = "admin@hote.invalid"
ALIAS = "hote.invalid+parc-a-vm-1"
VM = "parc-a-vm-1"
IP = "192.0.2.10"
CONF = {
    "version": "1.13.10",
    "required_version": ">= 1.10",
    "gpg_fingerprint": "0" * 40,
    "cle_gpg_url": "https://cle.invalid/cle.asc",
    "providers": {},
}


def setUpModule():
    todo_i18n._current_lang = "fr"


def tearDownModule():
    todo_i18n._current_lang = _LANGUE_ORIGINE


class Faux(mo.Moteur):
    """Moteur factice : retient ses appels, rend le plan et les sorties
    posés sur la classe."""

    nom = "faux"
    plan = []
    sorties_ = {}
    appels = []
    kw = {}

    def __init__(self, **kw):
        Faux.kw = kw

    def disponible(self):
        return True, "0"

    def preparer(self, spec):
        return mo.Resultat(True)

    def planifier(self, spec, journal):
        Faux.appels.append("planifier")
        journal("ligne du moteur")
        return mo.Resultat(True, "plan prêt"), list(Faux.plan)

    def appliquer(self, spec, journal):
        Faux.appels.append("appliquer")
        return mo.Resultat(True, "appliqué")

    def detruire(self, spec, journal):
        Faux.appels.append("detruire")
        return mo.Resultat(True, "détruit")

    def etat(self, spec):
        Faux.appels.append("etat")
        return ["proxmox_virtual_environment_vm.vm_a"]

    def sorties(self, spec):
        Faux.appels.append("sorties")
        return dict(Faux.sorties_)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.racine = self.tmp / "parcs"
        for patch in (
            mock.patch.object(sp, "RACINE_PARCS", self.racine),
            mock.patch.dict(mo._REGISTRE, {"tofu": Faux}),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        Faux.plan, Faux.sorties_, Faux.appels, Faux.kw = [], {}, [], {}
        self.todo = TODO.__new__(TODO)
        self.todo.config_file = mock.Mock()
        self.todo.config_file.get_config.return_value = None
        self.todo._menu_header = lambda: ""
        self.todo._tofu_executer = lambda spec: lambda cmd: (0, "")

    def parc(self, nom="parc-a", **vm):
        spec = sp.nouvelle_spec(nom, CIBLE)
        spec["compte"]["ssh_key"] = ""
        spec["vms"][0].update(vm)
        sp.sauver(spec, self.racine)
        return spec

    def lancer(self, methode, saisies=(), *args):
        """Sortie de `methode(*args)` avec `saisies` pour input()."""
        sortie = io.StringIO()
        with (
            mock.patch("builtins.input", side_effect=list(saisies)),
            redirect_stdout(sortie),
        ):
            getattr(self.todo, methode)(*args)
        return sortie.getvalue()

    def home(self):
        """HOME temporaire : ~/.ssh/config s'écrit sous self.tmp."""
        patch = mock.patch.dict(os.environ, {"HOME": str(self.tmp)})
        patch.start()
        self.addCleanup(patch.stop)
        return self.tmp / ".ssh" / "config"


class TestLeMenu(Base):
    def _choix(self, saisies=("0",)):
        with (
            mock.patch.object(TODO, "fill_help_info", return_value="") as aide,
            mock.patch("click.prompt", side_effect=list(saisies)),
            redirect_stdout(io.StringIO()),
        ):
            self.assertFalse(self.todo.prompt_execute_opentofu())
        return aide.call_args.args[0]

    def test_quatre_sections_et_dix_entrees(self):
        choix = self._choix()
        sections = [c["section"] for c in choix if "section" in c]
        self.assertEqual(
            [t for t in sections],
            [
                todo_i18n.t("Fleets"),
                todo_i18n.t("Operations"),
                todo_i18n.t("Proxmox"),
                todo_i18n.t("Tool"),
            ],
        )
        entrees = [c for c in choix if "section" not in c]
        self.assertEqual(len(entrees), 10)
        for entree in entrees:
            self.assertTrue(hasattr(TODO, entree["method"]), entree)

    def test_zero_rend_false(self):
        self._choix(["0"])

    def test_un_numero_lance_sa_methode(self):
        with mock.patch.object(TODO, "_tofu_lister_parcs") as lister:
            self._choix(["3", "0"])
        lister.assert_called_once_with()

    def test_un_numero_inconnu_le_dit(self):
        sortie = io.StringIO()
        with (
            mock.patch("click.prompt", side_effect=["99", "x", "0"]),
            redirect_stdout(sortie),
        ):
            self.todo.prompt_execute_opentofu()
        self.assertEqual(
            sortie.getvalue().count(todo_i18n.t("Command not found !")), 2
        )

    def test_le_supplement_de_todo_json_se_lance(self):
        entree = {"prompt_description": "extra", "bash_command": "true"}
        self.todo.config_file.get_config.return_value = [entree]
        self.todo.execute_from_configuration = mock.Mock()
        with (
            mock.patch("click.prompt", side_effect=["11", "0"]),
            redirect_stdout(io.StringIO()),
        ):
            self.todo.prompt_execute_opentofu()
        self.todo.config_file.get_config.assert_called_with(
            "opentofu_from_makefile"
        )
        self.todo.execute_from_configuration.assert_called_once_with(entree)

    def test_le_fil_d_ariane_le_nomme(self):
        self.assertEqual(
            "OpenTofu", TODO._MENU_LABELS["prompt_execute_opentofu"]
        )

    def test_todo_json_declare_le_supplement(self):
        conf = json.loads(
            (DEPOT / "script/todo/todo.json").read_text(encoding="utf-8")
        )
        self.assertEqual(conf["opentofu_from_makefile"], [])

    def test_chaque_libelle_a_ses_deux_langues(self):
        source = Path(opentofu_menu.__file__).read_text("utf-8")
        cles = {
            n.args[0].value
            for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.Call)
            and getattr(n.func, "id", None) == "t"
            and n.args
            and isinstance(n.args[0], ast.Constant)
        }
        self.assertGreater(len(cles), 30)
        manques = sorted(
            c
            for c in cles
            if set(todo_i18n.TRANSLATIONS.get(c, {})) < {"fr", "en"}
        )
        self.assertEqual([], manques)


class TestLeMenuDeploiement(Base):
    def test_opentofu_en_huit_et_le_vpn_dernier(self):
        with (
            mock.patch.object(TODO, "fill_help_info", return_value="") as aide,
            mock.patch.object(TODO, "prompt_execute_opentofu") as tofu,
            mock.patch.object(TODO, "prompt_execute_vpn") as vpn,
            mock.patch.object(TODO, "_deploy_ntfy_server") as ntfy,
            mock.patch("click.prompt", side_effect=["8", "9", "12", "0"]),
            redirect_stdout(io.StringIO()),
        ):
            self.assertFalse(self.todo.prompt_execute_deploy())
        reelles = [c for c in aide.call_args.args[0] if "section" not in c]
        self.assertEqual(
            reelles[7]["prompt_description"],
            todo_i18n.t("OpenTofu - Deploy a fleet from a spec"),
        )
        self.assertEqual(
            reelles[-1]["prompt_description"],
            todo_i18n.t("VPN - Tunnels (L2TP/IPsec, WireGuard, OpenVPN...)"),
        )
        self.assertEqual(len(reelles), 12)
        tofu.assert_called_once_with()
        ntfy.assert_called_once_with()
        vpn.assert_called_once_with()


class TestChoixEtChargement(Base):
    def test_aucun_parc(self):
        sortie = self.lancer("_tofu_plan")
        self.assertIn(todo_i18n.t("No fleet yet: create one first."), sortie)
        self.assertEqual(Faux.appels, [])

    def test_spec_abimee_liste_ses_erreurs_sans_trace(self):
        dossier = self.racine / "parc-a"
        dossier.mkdir(parents=True)
        (dossier / "spec.json").write_text("{pas du json", encoding="utf-8")
        sortie = self.lancer("_tofu_plan", ["1"])
        self.assertIn("parc-a", sortie)
        self.assertNotIn("Traceback", sortie)
        self.assertEqual(Faux.appels, [])

    def test_lister_les_parcs(self):
        self.parc()
        self.parc("parc-b")
        sortie = self.lancer("_tofu_lister_parcs")
        self.assertIn("parc-a", sortie)
        self.assertIn("parc-b", sortie)
        self.assertIn(CIBLE, sortie)


class TestDestroy(Base):
    def test_un_mauvais_nom_n_appelle_pas_le_moteur(self):
        self.parc()
        with mock.patch.object(TODO, "_tofu_apres_destroy") as apres:
            self.lancer("_tofu_destroy", ["1", "parc-b"])
        self.assertNotIn("detruire", Faux.appels)
        apres.assert_not_called()

    def test_le_nom_retape_detruit_puis_retire_les_alias(self):
        self.parc()
        with mock.patch.object(TODO, "_tofu_apres_destroy") as apres:
            self.lancer("_tofu_destroy", ["1", "parc-a"])
        self.assertIn("detruire", Faux.appels)
        apres.assert_called_once()
        self.assertEqual(apres.call_args.args[0]["nom"], "parc-a")


class TestApply(Base):
    def _apply(self, saisies):
        self.parc()
        Faux.sorties_ = {VM: {"vmid": 101, "ip": IP}}
        with mock.patch.object(TODO, "_tofu_apres_apply") as apres:
            sortie = self.lancer("_tofu_apply", saisies)
        return apres, sortie

    def test_plan_destructeur_sans_confirmation_n_applique_pas(self):
        Faux.plan = [mo.Changement("remplacer", VM, "vm")]
        apres, _ = self._apply(["1", ""])
        self.assertIn("planifier", Faux.appels)
        self.assertNotIn("appliquer", Faux.appels)
        apres.assert_not_called()

    def test_plan_destructeur_refuse_un_simple_oui(self):
        Faux.plan = [mo.Changement("detruire", VM, "vm")]
        self._apply(["1", "o"])
        self.assertNotIn("appliquer", Faux.appels)

    def test_plan_destructeur_avec_le_nom_applique(self):
        Faux.plan = [mo.Changement("remplacer", VM, "vm")]
        apres, _ = self._apply(["1", "parc-a"])
        self.assertIn("appliquer", Faux.appels)
        apres.assert_called_once()
        self.assertEqual(
            apres.call_args.args[1], {VM: {"vmid": 101, "ip": IP}}
        )

    def test_plan_sans_destruction_demande_oui(self):
        Faux.plan = [mo.Changement("creer", VM, "vm")]
        apres, sortie = self._apply(["1", "o"])
        self.assertIn("appliquer", Faux.appels)
        apres.assert_called_once()
        self.assertIn("ligne du moteur", sortie)
        self.assertIn(mo.formater_plan(Faux.plan)[0], sortie)

    def test_plan_sans_destruction_refuse(self):
        Faux.plan = [mo.Changement("creer", VM, "vm")]
        apres, _ = self._apply(["1", "n"])
        self.assertNotIn("appliquer", Faux.appels)
        apres.assert_not_called()

    def test_plan_vide_n_applique_rien(self):
        apres, _ = self._apply(["1"])
        self.assertNotIn("appliquer", Faux.appels)

    def test_hote_refuse_pas_de_plan(self):
        self.todo._tofu_executer = lambda spec: None
        apres, _ = self._apply(["1"])
        self.assertEqual(Faux.appels, [])

    def test_le_moteur_recoit_l_executeur_et_la_racine(self):
        executer = mock.Mock()
        self.todo._tofu_executer = lambda spec: executer
        Faux.plan = [mo.Changement("creer", VM, "vm")]
        self._apply(["1", "n"])
        self.assertIs(Faux.kw["executer"], executer)
        self.assertEqual(Path(Faux.kw["racine"]), self.racine)


class TestEtatEtAdresses(Base):
    def test_etat(self):
        self.parc()
        sortie = self.lancer("_tofu_etat", ["1"])
        self.assertIn("proxmox_virtual_environment_vm.vm_a", sortie)

    def test_adresses(self):
        self.parc()
        Faux.sorties_ = {VM: {"vmid": 101, "ip": IP}}
        sortie = self.lancer("_tofu_adresses", ["1"])
        self.assertIn(IP, sortie)
        self.assertIn("101", sortie)
        self.assertIn(ALIAS, sortie)


class TestApresApply(Base):
    def setUp(self):
        super().setUp()
        self.config = self.home()
        cle = self.tmp / ".ssh" / "id_essai"
        cle.parent.mkdir()
        cle.write_text("privée")
        (self.tmp / ".ssh" / "id_essai.pub").write_text("publique")
        self.cle = str(cle)
        self.todo._pve_attendre_ssh = mock.Mock(return_value=True)
        self.todo._pve_guest_ip = mock.Mock(return_value="192.0.2.20")
        self.todo._qemu_install_erplibre_monitored = mock.Mock()
        self.todo._pve_host_cache = {"target": "autre.invalid"}

    def spec(self, **vm):
        spec = sp.nouvelle_spec("parc-a", CIBLE)
        spec["compte"]["ssh_key"] = self.cle + ".pub"
        spec["vms"][0].update(vm)
        return spec

    def apres(self, spec, sorties):
        with redirect_stdout(io.StringIO()):
            self.todo._tofu_apres_apply(spec, sorties)

    def test_l_alias_rebondit_par_l_hote(self):
        self.apres(self.spec(), {VM: {"vmid": 101, "ip": IP}})
        texte = self.config.read_text(encoding="utf-8")
        self.assertIn(f"Host {ALIAS}\n", texte)
        self.assertIn(f"HostName {IP}\n", texte)
        self.assertIn("User erplibre\n", texte)
        self.assertIn(f"ProxyJump {CIBLE}\n", texte)
        self.assertIn(f"IdentityFile {self.cle}\n", texte)
        self.todo._pve_guest_ip.assert_not_called()
        self.todo._pve_attendre_ssh.assert_called_once_with(ALIAS)
        self.todo._qemu_install_erplibre_monitored.assert_not_called()

    def test_sans_ip_l_hote_de_la_spec_est_interroge(self):
        vu = {}

        def adresse(vmid):
            vu["hote"] = self.todo._pve_host(ask=False)
            vu["vmid"] = vmid
            return "192.0.2.20"

        self.todo._pve_guest_ip = adresse
        self.apres(self.spec(), {VM: {"vmid": 101, "ip": ""}})
        self.assertEqual(vu["vmid"], 101)
        self.assertEqual(vu["hote"]["target"], CIBLE)
        self.assertEqual(vu["hote"]["sudo"], "sudo ")
        self.assertEqual(
            self.todo._pve_host_cache, {"target": "autre.invalid"}
        )
        self.assertIn("HostName 192.0.2.20\n", self.config.read_text("utf-8"))

    def test_installer_erplibre_passe_par_le_suivi(self):
        spec = self.spec(installer_erplibre=True, branche="12.0")
        self.apres(spec, {VM: {"vmid": 101, "ip": IP}})
        appel = self.todo._qemu_install_erplibre_monitored.call_args
        self.assertEqual(appel.args[0], [VM])
        self.assertEqual(appel.args[1], "12.0")
        self.assertEqual(appel.args[2], {VM: ALIAS})
        self.assertEqual(
            appel.kwargs["pve"],
            {
                VM: {
                    "target": CIBLE,
                    "sudo": "sudo ",
                    "jump": "",
                    "vmid": 101,
                    "addr": IP,
                }
            },
        )

    def test_une_vm_muette_n_est_pas_installee(self):
        self.todo._pve_attendre_ssh.return_value = False
        spec = self.spec(installer_erplibre=True)
        self.apres(spec, {VM: {"vmid": 101, "ip": IP}})
        self.todo._qemu_install_erplibre_monitored.assert_not_called()

    def test_une_vm_sans_sortie_est_sautee(self):
        self.apres(self.spec(), {})
        self.assertFalse(self.config.exists())


class TestApresDestroy(Base):
    def test_retire_les_alias_du_parc_seulement(self):
        config = self.home()
        config.parent.mkdir()
        config.write_text(
            "Host autre\n    HostName 192.0.2.99\n\n"
            f"Host {ALIAS}\n    HostName {IP}\n    ProxyJump {CIBLE}\n",
            encoding="utf-8",
        )
        spec = sp.nouvelle_spec("parc-a", CIBLE)
        with redirect_stdout(io.StringIO()):
            self.todo._tofu_apres_destroy(spec)
        texte = config.read_text(encoding="utf-8")
        self.assertNotIn(ALIAS, texte)
        self.assertIn("Host autre", texte)

    def test_un_homonyme_d_un_autre_rebond_reste(self):
        config = self.home()
        config.parent.mkdir()
        avant = f"Host {ALIAS}\n    HostName {IP}\n    ProxyJump ailleurs\n"
        config.write_text(avant, encoding="utf-8")
        spec = sp.nouvelle_spec("parc-a", CIBLE)
        with redirect_stdout(io.StringIO()):
            self.todo._tofu_apres_destroy(spec)
        self.assertEqual(config.read_text(encoding="utf-8"), avant)


class TestOutil(Base):
    PAQUET = ("sudo pacman -S --needed --noconfirm opentofu", "opentofu")

    def outil(self, saisies, trouve=None, paquet=PAQUET, version="1.13.9"):
        trouver = trouve if isinstance(trouve, list) else [trouve]
        with (
            mock.patch.object(
                opentofu_menu.outil, "trouver_tofu", side_effect=trouver
            ),
            mock.patch.object(
                opentofu_menu.outil, "version_tofu", return_value=version
            ),
            mock.patch.object(
                opentofu_menu.outil, "commande_paquet", return_value=paquet
            ),
            mock.patch.object(
                opentofu_menu.outil,
                "installer_zip",
                return_value=mo.Resultat(True, "zip posé"),
            ) as zip_,
            mock.patch.object(
                opentofu_menu.coffre, "charger_conf", return_value=CONF
            ),
            mock.patch.object(opentofu_menu.subprocess, "run") as run,
        ):
            run.return_value.returncode = 0
            sortie = self.lancer("_tofu_outil", saisies)
        return sortie, zip_, run

    def test_absent_propose_le_paquet_puis_le_zip(self):
        sortie, zip_, run = self.outil(["n", "o"])
        self.assertIn(self.PAQUET[0], sortie)
        run.assert_not_called()
        zip_.assert_called_once_with(CONF)
        self.assertIn("zip posé", sortie)

    def test_le_paquet_accepte_tourne_sans_shell(self):
        sortie, zip_, run = self.outil(["o"], trouve=[None, "/opt/x/tofu"])
        argv = run.call_args.args[0]
        self.assertEqual(argv, self.PAQUET[0].split())
        self.assertNotIn("shell", run.call_args.kwargs)
        zip_.assert_not_called()

    def test_zip_refuse(self):
        _sortie, zip_, _run = self.outil(["n", "n"])
        zip_.assert_not_called()

    def test_sans_gestionnaire_le_zip_seul(self):
        _sortie, zip_, run = self.outil(["o"], paquet=(None, None))
        run.assert_not_called()
        zip_.assert_called_once_with(CONF)

    def test_present_et_suffisant_ne_propose_rien(self):
        sortie, zip_, run = self.outil([], trouve="/opt/x/tofu")
        self.assertIn("/opt/x/tofu", sortie)
        self.assertIn("1.13.9", sortie)
        zip_.assert_not_called()
        run.assert_not_called()

    def test_trop_vieux_propose_l_installation(self):
        _sortie, zip_, _run = self.outil(
            ["n", "o"], trouve="/opt/x/tofu", version="1.9.0"
        )
        zip_.assert_called_once_with(CONF)


class TestCreerParc(Base):
    def test_hote_memorise_par_defaut(self):
        self.todo._pve_host = lambda ask=True: {"target": "root@pve.invalid"}
        self.lancer("_tofu_creer_parc", ["parc-b", "", "n"])
        spec = sp.charger("parc-b", self.racine)
        self.assertEqual(spec["cible"]["hote"]["target"], "root@pve.invalid")

    def test_saisie_libre_sans_hote_memorise(self):
        self.todo._pve_host = lambda ask=True: None
        self.lancer("_tofu_creer_parc", ["parc-c", "admin@x.invalid", "n"])
        spec = sp.charger("parc-c", self.racine)
        self.assertEqual(spec["cible"]["hote"]["target"], "admin@x.invalid")

    def test_nom_invalide_rien_n_est_ecrit(self):
        self.todo._pve_host = lambda ask=True: None
        sortie = self.lancer("_tofu_creer_parc", ["Parc_B"])
        self.assertIn("Parc_B", sortie)
        self.assertEqual(sp.lister(self.racine), [])

    def test_parc_existant_refuse(self):
        self.parc()
        self.todo._pve_host = lambda ask=True: None
        self.lancer("_tofu_creer_parc", ["parc-a"])
        self.assertEqual(sp.lister(self.racine), ["parc-a"])

    def test_ouvrir_le_formulaire(self):
        self.todo._pve_host = lambda ask=True: {"target": "root@pve.invalid"}
        with mock.patch.object(TODO, "_tofu_editer_parc") as editer:
            self.lancer("_tofu_creer_parc", ["parc-b", "", "o"])
        editer.assert_called_once_with("parc-b")


class TestEditerParc(Base):
    def test_sans_le_tui_un_message(self):
        with mock.patch.dict(sys.modules, {"script.todo.opentofu_form": None}):
            sortie = self.lancer("_tofu_editer_parc")
        self.assertIn(
            todo_i18n.t("The fleet form (TUI) is not available yet."), sortie
        )


class TestPreparerHote(Base):
    def test_executeur_brut_et_spec_sauvee(self):
        self.parc()
        vus = []

        def executer_ssh(hote):
            vus.append(dict(hote))
            return mock.Mock()

        def preparer(spec, executer_brut, recreer=False, racine=None):
            neuve = json.loads(json.dumps(spec))
            neuve["cible"]["hote"]["sudo"] = ""
            neuve["cible"]["stockage_snippets"] = "local"
            preparer.args = (recreer, racine)
            return mo.Resultat(True, "hôte prêt"), neuve

        with (
            mock.patch.object(
                opentofu_menu.resolution, "executer_ssh", executer_ssh
            ),
            mock.patch.object(
                opentofu_menu.jeton_proxmox, "preparer_hote", preparer
            ),
        ):
            sortie = self.lancer("_tofu_preparer_hote", ["1", "n"])
        self.assertEqual(vus[0]["sudo"], "")
        self.assertEqual(vus[0]["target"], CIBLE)
        self.assertEqual(preparer.args[0], False)
        self.assertEqual(Path(preparer.args[1]), self.racine)
        self.assertIn("hôte prêt", sortie)
        spec = sp.charger("parc-a", self.racine)
        self.assertEqual(spec["cible"]["hote"]["sudo"], "")
        self.assertEqual(spec["cible"]["stockage_snippets"], "local")

    def test_un_echec_ne_sauve_rien(self):
        self.parc()

        def preparer(spec, executer_brut, recreer=False, racine=None):
            neuve = json.loads(json.dumps(spec))
            neuve["cible"]["hote"]["sudo"] = ""
            return mo.Resultat(False, "refusé"), neuve

        with (
            mock.patch.object(
                opentofu_menu.resolution, "executer_ssh", mock.Mock()
            ),
            mock.patch.object(
                opentofu_menu.jeton_proxmox, "preparer_hote", preparer
            ),
        ):
            sortie = self.lancer("_tofu_preparer_hote", ["1", "o"])
        self.assertIn("refusé", sortie)
        spec = sp.charger("parc-a", self.racine)
        self.assertEqual(spec["cible"]["hote"]["sudo"], "sudo ")


class TestExecuteur(Base):
    """`_tofu_executer` vérifie l'élévation comme le choix d'hôte Proxmox."""

    def executer(self, reponses):
        del self.todo._tofu_executer
        commandes = []

        def run(hote, cmd, timeout=120):
            commandes.append(cmd)
            return reponses[cmd]

        spec = sp.nouvelle_spec("parc-a", CIBLE)
        with (
            mock.patch.object(opentofu_menu.resolution.pve, "run", run),
            redirect_stdout(io.StringIO()),
        ):
            executer = self.todo._tofu_executer(spec)
            if executer:
                executer("qm list")
        return executer, commandes

    def test_root_sans_sudo(self):
        executer, commandes = self.executer(
            {"id -u": (0, "0\n"), "qm list": (0, "")}
        )
        self.assertIsNotNone(executer)
        self.assertEqual(commandes[-1], "qm list")

    def test_sudo_sans_mot_de_passe(self):
        executer, commandes = self.executer(
            {
                "id -u": (0, "1000\n"),
                "sudo -n true": (0, ""),
                "sudo sh -c 'qm list'": (0, ""),
            }
        )
        self.assertIsNotNone(executer)
        self.assertEqual(commandes[-1], "sudo sh -c 'qm list'")

    def test_sudo_qui_demande_un_mot_de_passe(self):
        executer, _ = self.executer(
            {"id -u": (0, "1000\n"), "sudo -n true": (1, "")}
        )
        self.assertIsNone(executer)

    def test_hote_injoignable(self):
        executer, _ = self.executer({"id -u": (255, "")})
        self.assertIsNone(executer)


if __name__ == "__main__":
    unittest.main()
