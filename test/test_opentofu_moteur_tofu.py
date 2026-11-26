#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le moteur OpenTofu : traduction du plan et enchaînement des commandes.

`fixtures/opentofu/show_plan.json` est écrite à la main d'après le format
documenté de `tofu show -json` : elle est à remplacer par une sortie réelle
capturée au test long (`long_test/`), le seul qui dispose de tofu et d'un PVE.

Un faux `tofu` (script Python écrit dans un dossier temporaire) journalise
ses arguments, les NOMS des variables d'environnement utiles et un drapeau
« jeton dans argv », puis rend des lignes préparées par le test.
"""

import argparse
import json
import os
import stat
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.argv = ["todo.py"]
from script.opentofu import coffre as cf  # noqa: E402
from script.opentofu import moteur as mt  # noqa: E402
from script.opentofu import moteur_tofu as mtt  # noqa: E402
from script.opentofu import outil  # noqa: E402
from script.opentofu import spec as sp  # noqa: E402
from script.todo import todo_i18n  # noqa: E402

_LANGUE_ORIGINE = todo_i18n._current_lang


def setUpModule():
    todo_i18n._current_lang = "fr"


def tearDownModule():
    todo_i18n._current_lang = _LANGUE_ORIGINE


DEPOT = Path(__file__).resolve().parent.parent
FIXTURE = DEPOT / "test" / "fixtures" / "opentofu" / "show_plan.json"
JETON = "tofu@pve!parc-a=SECRET-0123456789"
QM_VIDE = (
    "      VMID NAME                 STATUS     MEM(MB)    BOOTDISK(GB) PID\n"
)

FAUX_TOFU = """#!{python}
import json, os, sys
ici = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(ici, "comportement.json")) as f:
    conf = json.load(f)
args = sys.argv[1:]
jeton = os.environ.get("PROXMOX_VE_API_TOKEN", "")
secret = jeton.split("=", 1)[-1]
noms = sorted(
    k for k in os.environ if k.startswith(("PROXMOX_VE_", "TF_"))
)
with open(os.path.join(ici, "appels.jsonl"), "a") as f:
    f.write(json.dumps({{
        "args": args,
        "cwd": os.getcwd(),
        "env": noms,
        "jeton_en_argv": bool(jeton) and any(
            jeton in a or secret in a for a in args
        ),
    }}) + "\\n")
cmd = " ".join(args[:2]) if args[:1] == ["state"] else (args or [""])[0]
rep = conf.get(cmd, {{}})
for ligne in rep.get("lignes", []):
    print(ligne.replace("{{JETON}}", jeton), flush=True)
for ligne in rep.get("erreurs", []):
    print(ligne, file=sys.stderr, flush=True)
if "fichier" in rep:
    with open(rep["fichier"]) as f:
        sys.stdout.write(f.read())
if "texte" in rep:
    sys.stdout.write(rep["texte"])
if cmd == "init" and not rep.get("code"):
    os.makedirs(".terraform", exist_ok=True)
if cmd == "plan" and not rep.get("code"):
    for a in args:
        if a.startswith("-out="):
            with open(a[len("-out="):], "w") as f:
                f.write("plan")
sys.exit(rep.get("code", 0))
"""


def _faux_qemu():
    """Module `deploy_qemu` réduit à ce que `donnees_vm` consomme."""

    def build_parser():
        p = argparse.ArgumentParser()
        for opt in ("--distro", "--hostname", "--user"):
            p.add_argument(opt)
        return p

    return types.SimpleNamespace(
        DISTROS={"debian": ({"13": ("trixie",)},)},
        image_url=lambda d, c, a, v: (
            "https://images.example.invalid/debian-13-genericcloud-amd64.qcow2"
        ),
        default_image_name=lambda d, c, a, v: (
            "debian-13-genericcloud-amd64.qcow2"
        ),
        pinned_sha256=lambda d: "",
        requiert_uefi=lambda d: False,
        build_parser=build_parser,
        build_cloud_config=lambda args, x, cles: (
            "#cloud-config\nhostname: " + args.hostname + "\n"
        ),
    )


def _charger_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class TestTraduirePlan(unittest.TestCase):
    def setUp(self):
        self.changements = mtt.traduire_plan(_charger_fixture())

    def test_quatre_changements(self):
        vus = [(c.action, c.vm, c.ressource) for c in self.changements]
        self.assertEqual(
            vus,
            [
                ("creer", "essai-vm-2", "vm"),
                ("modifier", "essai-vm-1", "vm"),
                ("remplacer", "essai-vm-1", "cloud-init"),
                ("detruire", "ancienne", "vm"),
            ],
        )

    def test_ram_2048_4096(self):
        modif = self.changements[1]
        self.assertEqual(modif.details, [("ram", "2048", "4096")])
        self.assertIn("    ram : 2048 → 4096", mt.formater_plan([modif]))

    def test_remplacement_valeur_apres_apply(self):
        details = dict((c, (a, b)) for c, a, b in self.changements[2].details)
        self.assertEqual(details["id"][1], "(après apply)")
        self.assertIn("source_raw.data", details)

    def test_creer_et_detruire_sans_details(self):
        self.assertEqual(self.changements[0].details, [])
        self.assertEqual(self.changements[3].details, [])

    def _un(self, actions, before, after, **change):
        change.update(actions=actions)
        if before is not ...:
            change["before"] = before
        if after is not ...:
            change["after"] = after
        return mtt.traduire_plan(
            {
                "resource_changes": [
                    {
                        "type": "proxmox_virtual_environment_vm",
                        "name": "vm_web_1",
                        "change": change,
                    }
                ]
            }
        )

    def test_actions_ignorees(self):
        for actions in (["no-op"], ["read"], ["forget"], []):
            self.assertEqual(self._un(actions, {}, {}), [], actions)

    def test_create_puis_delete_est_un_remplacement(self):
        (c,) = self._un(["create", "delete"], {"a": 1}, {"a": 2})
        self.assertEqual(c.action, "remplacer")
        self.assertEqual(c.vm, "web-1")

    def test_avant_absent_ou_null(self):
        absent = self._un(["update"], ..., {"a": 1})
        nul = self._un(["update"], None, {"a": 1})
        self.assertEqual(absent[0].details, nul[0].details)
        self.assertEqual(absent[0].details, [("a", "null", "1")])

    def test_sensible(self):
        (c,) = self._un(
            ["update"],
            {"pwd": "ancien", "x": 1},
            {"pwd": "nouveau", "x": 1},
            before_sensitive={"pwd": True},
            after_sensitive={"pwd": True},
        )
        self.assertEqual(c.details, [("pwd", "(sensible)", "(sensible)")])

    def test_noms_des_ressources(self):
        show = {
            "resource_changes": [
                {
                    "type": "proxmox_download_file",
                    "name": "img_debian_13_amd64_qcow2",
                    "change": {"actions": ["create"]},
                },
                {
                    "type": "proxmox_virtual_environment_file",
                    "name": "ud_web_1",
                    "change": {"actions": ["delete"]},
                },
            ]
        }
        vus = [(c.vm, c.ressource) for c in mtt.traduire_plan(show)]
        self.assertEqual(
            vus,
            [("debian_13_amd64_qcow2", "image"), ("web-1", "cloud-init")],
        )


class _Base(unittest.TestCase):
    """Parc dans une racine temporaire, faux `tofu` et faux hôte."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.racine = self.tmp / "parcs"
        ancien = cf.CACHE_PLUGINS
        cf.CACHE_PLUGINS = self.tmp / "plugins"
        self.addCleanup(setattr, cf, "CACHE_PLUGINS", ancien)
        self.cle = self.tmp / "id.pub"
        self.cle.write_text("ssh-ed25519 AAAAtest cle@test\n")
        self.outil = self.tmp / "outil"
        self.outil.mkdir()
        self.binaire = self.outil / "tofu"
        self.binaire.write_text(FAUX_TOFU.format(python=sys.executable))
        self.binaire.chmod(0o755)
        self.comportement({"show": {"fichier": str(FIXTURE)}})
        self.commandes = []
        self.spec = sp.nouvelle_spec("parc-a", "hote-x")
        self.spec["cible"].update(
            api_url="https://192.0.2.10:8006/",
            noeud="pve1",
            stockage="local-lvm",
            stockage_snippets="local",
            pont="vmbr0",
            ssh_user="admin",
            ssh_port=22,
        )
        self.spec["compte"]["ssh_key"] = str(self.cle)
        self.spec["vms"][0].update(
            vmid=None, ip="192.0.2.50/24", passerelle="192.0.2.1"
        )
        sp.sauver(self.spec, self.racine)
        self.lignes = []
        self.moteur = mtt.MoteurTofu(
            binaire=str(self.binaire),
            executer=self._executer,
            mod_qemu=_faux_qemu(),
            racine=self.racine,
        )

    def _executer(self, cmd):
        self.commandes.append(cmd)
        if cmd == "qm list":
            return 0, QM_VIDE
        return 1, ""

    def comportement(self, conf):
        (self.outil / "comportement.json").write_text(json.dumps(conf))

    def appels(self):
        chemin = self.outil / "appels.jsonl"
        if not chemin.exists():
            return []
        return [json.loads(x) for x in chemin.read_text().splitlines()]

    def sous_commandes(self):
        return [a["args"][0] for a in self.appels()]

    def planifier(self):
        return self.moteur.planifier(self.spec, self.lignes.append)


class TestPlanifier(_Base):
    def test_planifier_enchaine_init_plan_show(self):
        res, changements = self.planifier()
        self.assertTrue(res.ok, res.message)
        self.assertEqual(self.sous_commandes(), ["init", "plan", "show"])
        init, plan, show = (a["args"] for a in self.appels())
        self.assertIn("-input=false", init)
        self.assertIn("-input=false", plan)
        self.assertIn("-out=plan.bin", plan)
        self.assertEqual(show[1:], ["-json", "-no-color", "plan.bin"])
        for args in (init, plan, show):
            self.assertIn("-no-color", args)
        dossier = self.moteur.dossier_travail(self.spec)
        self.assertEqual(dossier, self.racine / "parc-a" / ".tofu")
        for appel in self.appels():
            self.assertEqual(Path(appel["cwd"]), dossier)
            self.assertIn("TF_ENCRYPTION", appel["env"])
        self.assertEqual(changements, mtt.traduire_plan(_charger_fixture()))
        texte = (dossier / "main.tf.json").read_text()
        doc = json.loads(texte)
        self.assertEqual(
            texte, json.dumps(doc, indent=2, sort_keys=True) + "\n"
        )
        self.assertIn("proxmox_virtual_environment_vm", doc["resource"])

    def test_spec_resolue_sauvee_et_rendue_a_l_appelant(self):
        res, _ = self.planifier()
        self.assertTrue(res.ok, res.message)
        self.assertEqual(self.spec["vms"][0]["vmid"], 100)
        self.assertEqual(
            sp.charger("parc-a", self.racine)["vms"][0]["vmid"], 100
        )
        self.assertEqual(self.commandes, ["qm list"])

    def test_ssh_g_lu_pour_les_champs_ssh_vides(self):
        self.spec["cible"].update(api_url="", ssh_user="", ssh_port=None)
        lu = {"adresse": "192.0.2.10", "user": "ops", "port": 2222}
        with mock.patch.object(
            mtt.resolution, "ssh_hote", return_value=lu
        ) as ssh_hote:
            res, _ = self.planifier()
        self.assertTrue(res.ok, res.message)
        ssh_hote.assert_called_once_with("hote-x", "")
        cible = sp.charger("parc-a", self.racine)["cible"]
        self.assertEqual(
            (cible["api_url"], cible["ssh_user"], cible["ssh_port"]),
            ("https://192.0.2.10:8006/", "ops", 2222),
        )
        doc = json.loads(
            (
                self.moteur.dossier_travail(self.spec) / "main.tf.json"
            ).read_text()
        )
        ssh = doc["provider"]["proxmox"]["ssh"]
        self.assertEqual(ssh["username"], "ops")
        self.assertEqual(ssh["node"][0]["port"], 2222)

    def test_init_seulement_si_necessaire(self):
        self.planifier()
        self.planifier()
        self.assertEqual(
            self.sous_commandes(), ["init", "plan", "show", "plan", "show"]
        )
        self.assertNotIn("-upgrade", self.appels()[0]["args"])
        dossier = self.moteur.dossier_travail(self.spec)
        (dossier / ".init_providers.json").write_text('{"autre": {}}')
        self.planifier()
        self.assertEqual(self.sous_commandes()[5], "init")
        # Fournisseur changé : le verrou `.terraform.lock.hcl` épingle
        # l'ancien, et seul `-upgrade` le laisse monter.
        self.assertIn("-upgrade", self.appels()[5]["args"])

    def test_init_sans_upgrade_quand_rien_n_est_connu(self):
        self.planifier()
        dossier = self.moteur.dossier_travail(self.spec)
        (dossier / ".init_providers.json").unlink()
        self.planifier()
        inits = [a["args"] for a in self.appels() if a["args"][0] == "init"]
        self.assertEqual(len(inits), 2)
        for args in inits:
            self.assertNotIn("-upgrade", args)

    def test_sous_processus_sans_entree_standard(self):
        vrai = mtt.subprocess.Popen
        with mock.patch.object(mtt.subprocess, "Popen", wraps=vrai) as popen:
            res, _ = self.planifier()
        self.assertTrue(res.ok, res.message)
        self.assertEqual(popen.call_count, 3)
        for appel in popen.call_args_list:
            self.assertIs(appel.kwargs.get("stdin"), mtt.subprocess.DEVNULL)

    def test_phrase_perdue_a_cote_d_un_etat(self):
        self.planifier()
        dossier = self.moteur.dossier_travail(self.spec)
        (dossier / "terraform.tfstate").write_text("{}")
        cf.ecrire("parc-a", {}, self.racine)
        n = len(self.appels())
        res, _ = self.planifier()
        self.assertFalse(res.ok)
        self.assertIn("README", res.message)
        self.assertEqual(len(self.appels()), n)

    def test_resolution_impossible_sans_exception(self):
        self.moteur = mtt.MoteurTofu(
            binaire=str(self.binaire),
            executer=lambda cmd: (255, ""),
            mod_qemu=_faux_qemu(),
            racine=self.racine,
        )
        res, changements = self.planifier()
        self.assertFalse(res.ok)
        self.assertIn("qm list", res.message)
        self.assertEqual(changements, [])
        self.assertEqual(self.appels(), [])

    def test_spec_invalide_sans_exception(self):
        self.spec["vms"][0]["ram"] = 1
        res, changements = self.planifier()
        self.assertFalse(res.ok)
        self.assertIn("ram", res.message)
        self.assertEqual(self.appels(), [])

    def test_champ_retire_rend_un_echec_sans_exception(self):
        chemins = (
            ("nom",),
            ("cible",),
            ("cible", "hote"),
            ("cible", "insecure"),
            ("compte",),
            ("compte", "user"),
            ("compte", "ssh_key"),
            ("vms",),
            ("vms", 0, "nom"),
            ("vms", 0, "arch"),
            ("vms", 0, "distro"),
            ("vms", 0, "version"),
            ("vms", 0, "demarrer"),
            ("vms", 0, "installer_erplibre"),
            ("vms", 0, "disque"),
        )
        for chemin in chemins:
            spec = json.loads(json.dumps(self.spec))
            noeud = spec
            for cle in chemin[:-1]:
                noeud = noeud[cle]
            del noeud[chemin[-1]]
            res, changements = self.moteur.planifier(spec, self.lignes.append)
            self.assertFalse(res.ok, chemin)
            self.assertTrue(res.message, chemin)
            self.assertEqual(changements, [], chemin)
        self.assertEqual(self.appels(), [])

    def test_erreur_de_cle_au_rendu_devient_spec_invalide(self):
        with mock.patch.object(
            mtt.rendu_proxmox, "rendre", side_effect=KeyError("pont")
        ):
            res, changements = self.planifier()
        self.assertFalse(res.ok)
        self.assertIn("Spec invalide", res.message)
        self.assertEqual(changements, [])

    def test_plan_en_echec(self):
        self.comportement({"plan": {"lignes": ["Error: boom"], "code": 1}})
        res, changements = self.planifier()
        self.assertFalse(res.ok)
        self.assertEqual(res.code, 1)
        self.assertIn("Error: boom", self.lignes)
        self.assertNotIn("show", self.sous_commandes())

    def test_plan_en_echec_invalide_le_plan_precedent(self):
        res, _ = self.planifier()
        self.assertTrue(res.ok, res.message)
        self.spec["vms"][0]["ram"] = 1
        res, _ = self.planifier()
        self.assertFalse(res.ok)
        res = self.moteur.appliquer(self.spec, self.lignes.append)
        self.assertEqual(res.message, "Planifier d'abord.")
        self.assertNotIn("apply", self.sous_commandes())

    def test_phrase_de_verrou_sans_echec_ignoree(self):
        self.comportement(
            {
                "plan": {"lignes": ["note: Error acquiring the state lock"]},
                "show": {"fichier": str(FIXTURE)},
            }
        )
        res, _ = self.planifier()
        self.assertTrue(res.ok, res.message)

    def test_nom_de_parc_invalide_sans_exception(self):
        self.spec["nom"] = "../evade"
        self.assertEqual(len(self.moteur.etat(self.spec)), 1)
        self.assertEqual(self.moteur.sorties(self.spec), {})
        res, changements = self.planifier()
        self.assertFalse(res.ok)
        self.assertEqual(self.appels(), [])

    def test_show_illisible_efface_le_plan(self):
        self.comportement({"show": {"texte": "pas du json"}})
        res, _ = self.planifier()
        self.assertFalse(res.ok)
        dossier = self.moteur.dossier_travail(self.spec)
        self.assertFalse((dossier / "plan.bin").exists())

    def test_journal_masque_le_jeton(self):
        cf.ecrire("parc-a", {"jeton": JETON}, self.racine)
        self.comportement(
            {
                "plan": {"lignes": ["Authorization: PVEAPIToken={JETON}"]},
                "show": {"fichier": str(FIXTURE)},
            }
        )
        res, _ = self.planifier()
        self.assertTrue(res.ok, res.message)
        journal = "\n".join(self.lignes)
        self.assertIn("PVEAPIToken=***", journal)
        self.assertNotIn("SECRET-0123456789", journal)

    def test_verrou_donne_le_remede(self):
        self.comportement(
            {
                "plan": {
                    "lignes": [
                        "╷",
                        "│ Error: Error acquiring the state lock",
                        "│ Lock Info:",
                        "│   ID:        abc",
                        "│   Path:      terraform.tfstate",
                        "╵",
                    ],
                    "code": 1,
                }
            }
        )
        res, changements = self.planifier()
        self.assertFalse(res.ok)
        self.assertIn("tofu force-unlock abc", res.message)
        for appel in self.appels():
            self.assertNotIn("force-unlock", appel["args"])

    def test_interruption_attend_tofu(self):
        self.comportement(
            {"plan": {"lignes": ["debut", "Interrupt received.", "fin"]}}
        )
        recues = []

        def journal(ligne):
            recues.append(ligne)
            if ligne == "debut":
                raise KeyboardInterrupt

        res, changements = self.moteur.planifier(self.spec, journal)
        self.assertFalse(res.ok)
        self.assertIn("Interrompu", res.message)
        self.assertEqual(changements, [])
        self.assertIn("fin", recues)
        self.assertNotIn("show", self.sous_commandes())


class TestAppliquerDetruire(_Base):
    def test_appliquer_sans_plan_refuse(self):
        res = self.moteur.appliquer(self.spec, self.lignes.append)
        self.assertFalse(res.ok)
        self.assertEqual(res.message, "Planifier d'abord.")
        self.assertEqual(self.appels(), [])

    def test_appliquer_plan_perime_refuse(self):
        self.planifier()
        dossier = self.moteur.dossier_travail(self.spec)
        doc = (dossier / "main.tf.json").stat()
        os.utime(
            dossier / "plan.bin",
            ns=(doc.st_atime_ns, doc.st_mtime_ns - 10**9),
        )
        res = self.moteur.appliquer(self.spec, self.lignes.append)
        self.assertFalse(res.ok)
        self.assertNotIn("apply", self.sous_commandes())

    def test_appliquer_le_plan_sauve_puis_l_efface(self):
        self.planifier()
        res = self.moteur.appliquer(self.spec, self.lignes.append)
        self.assertTrue(res.ok, res.message)
        apply = self.appels()[-1]["args"]
        self.assertEqual(
            apply, ["apply", "-input=false", "-no-color", "plan.bin"]
        )
        dossier = self.moteur.dossier_travail(self.spec)
        self.assertFalse((dossier / "plan.bin").exists())
        res = self.moteur.appliquer(self.spec, self.lignes.append)
        self.assertFalse(res.ok)

    def test_apply_en_echec_efface_le_plan(self):
        self.planifier()
        self.comportement({"apply": {"lignes": ["Error: x"], "code": 1}})
        res = self.moteur.appliquer(self.spec, self.lignes.append)
        self.assertFalse(res.ok)
        dossier = self.moteur.dossier_travail(self.spec)
        self.assertFalse((dossier / "plan.bin").exists())

    def test_jeton_jamais_en_argv(self):
        cf.ecrire("parc-a", {"jeton": JETON}, self.racine)
        self.planifier()
        self.moteur.appliquer(self.spec, self.lignes.append)
        self.moteur.detruire(self.spec, self.lignes.append)
        self.moteur.etat(self.spec)
        self.moteur.sorties(self.spec)
        appels = self.appels()
        self.assertEqual(
            [a["args"][0] for a in appels],
            ["init", "plan", "show", "apply", "destroy", "state", "output"],
        )
        for appel in appels:
            self.assertFalse(appel["jeton_en_argv"], appel["args"])
            self.assertIn("PROXMOX_VE_API_TOKEN", appel["env"])
        dossier = self.moteur.dossier_travail(self.spec)
        self.assertNotIn("SECRET", (dossier / "main.tf.json").read_text())

    def test_detruire(self):
        self.planifier()
        res = self.moteur.detruire(self.spec, self.lignes.append)
        self.assertTrue(res.ok, res.message)
        self.assertEqual(
            self.appels()[-1]["args"],
            ["destroy", "-auto-approve", "-input=false", "-no-color"],
        )

    def test_detruire_sans_etat(self):
        res = self.moteur.detruire(self.spec, self.lignes.append)
        self.assertFalse(res.ok)
        self.assertEqual(self.appels(), [])


class TestLectures(_Base):
    def test_sorties(self):
        self.planifier()
        valeur = {"parc-a-vm-1": {"vmid": 100, "ipv4": []}}
        self.comportement(
            {
                "output": {
                    "texte": json.dumps(
                        {"vms": {"sensitive": False, "value": valeur}}
                    )
                }
            }
        )
        self.assertEqual(
            self.moteur.sorties(self.spec),
            {"parc-a-vm-1": {"vmid": 100, "ip": "192.0.2.50"}},
        )
        self.spec["vms"][0]["ip"] = "dhcp"
        self.assertEqual(
            self.moteur.sorties(self.spec)["parc-a-vm-1"]["ip"], ""
        )
        self.assertIn("-json", self.appels()[-1]["args"])

    def test_sorties_sans_etat(self):
        self.assertEqual(self.moteur.sorties(self.spec), {})
        self.assertEqual(self.appels(), [])

    def test_etat(self):
        self.planifier()
        self.comportement(
            {"state list": {"lignes": ["proxmox_virtual_environment_vm.vm_a"]}}
        )
        self.assertEqual(
            self.moteur.etat(self.spec),
            ["proxmox_virtual_environment_vm.vm_a"],
        )
        self.assertEqual(self.appels()[-1]["args"], ["state", "list"])

    def test_disponible(self):
        self.comportement(
            {"version": {"texte": '{"terraform_version": "1.13.10"}'}}
        )
        self.assertEqual(self.moteur.disponible(), (True, "1.13.10"))

    def test_disponible_lit_la_version_par_l_outil(self):
        with mock.patch.object(
            mtt.outil, "version_tofu", return_value="9.9.9"
        ) as version:
            self.assertEqual(self.moteur.disponible(), (True, "9.9.9"))
        version.assert_called_once_with(str(self.binaire))
        with mock.patch.object(mtt.outil, "version_tofu", return_value=""):
            ok, raison = self.moteur.disponible()
        self.assertFalse(ok)
        self.assertIn(str(self.binaire), raison)

    def test_indisponible_sans_binaire(self):
        moteur = mtt.MoteurTofu(racine=self.racine)
        with mock.patch.object(outil.shutil, "which", return_value=None):
            with mock.patch.object(mtt.Path, "home", return_value=self.tmp):
                ok, raison = moteur.disponible()
                res, _ = moteur.planifier(self.spec, self.lignes.append)
        self.assertFalse(ok)
        self.assertIn("tofu", raison)
        self.assertFalse(res.ok)

    def test_binaire_local(self):
        local = self.tmp / ".local" / "bin" / "tofu"
        local.parent.mkdir(parents=True)
        local.write_text("#!/bin/sh\n")
        local.chmod(stat.S_IRWXU)
        moteur = mtt.MoteurTofu(racine=self.racine)
        with mock.patch.object(outil.shutil, "which", return_value=None):
            with mock.patch.object(mtt.Path, "home", return_value=self.tmp):
                self.assertEqual(moteur.binaire(), str(local))

    def test_preparer(self):
        res = self.moteur.preparer(self.spec)
        self.assertTrue(res.ok, res.message)
        self.assertEqual(self.sous_commandes(), ["init"])

    def test_enregistre(self):
        moteur = mt.moteur_pour({"moteur": "tofu"}, racine=self.racine)
        self.assertIsInstance(moteur, mtt.MoteurTofu)


if __name__ == "__main__":
    unittest.main()
