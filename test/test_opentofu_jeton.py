#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Préparation de l'hôte Proxmox : commandes, jeton, sudo, secret."""

import copy
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.argv = ["todo.py"]
from script.opentofu import coffre  # noqa: E402
from script.opentofu import jeton_proxmox as jp  # noqa: E402
from script.opentofu import spec as sp  # noqa: E402
from script.todo import todo_i18n  # noqa: E402

_LANGUE_ORIGINE = todo_i18n._current_lang
SECRET = "11111111-2222-3333-4444-555555555555"
AJOUT = json.dumps(
    {
        "full-tokenid": "tofu@pve!parc-a",
        "info": {"privsep": "0"},
        "value": SECRET,
    }
)


PRIVILEGES_ATTENDUS = (
    "Realm.AllocateUser",
    "VM.PowerMgmt",
    "VM.GuestAgent.Unrestricted",
    "Sys.Console",
    "Sys.Audit",
    "Sys.AccessNetwork",
    "VM.Config.Cloudinit",
    "VM.Replicate",
    "Pool.Allocate",
    "SDN.Audit",
    "Realm.Allocate",
    "SDN.Use",
    "Mapping.Modify",
    "VM.Config.Memory",
    "VM.GuestAgent.FileSystemMgmt",
    "VM.Allocate",
    "SDN.Allocate",
    "VM.Console",
    "VM.Clone",
    "VM.Backup",
    "Datastore.AllocateTemplate",
    "VM.Snapshot",
    "VM.Config.Network",
    "Sys.Incoming",
    "Sys.Modify",
    "VM.Snapshot.Rollback",
    "VM.Config.Disk",
    "Datastore.Allocate",
    "VM.Config.CPU",
    "VM.Config.CDROM",
    "Group.Allocate",
    "Datastore.Audit",
    "VM.Migrate",
    "VM.GuestAgent.FileWrite",
    "Mapping.Use",
    "Datastore.AllocateSpace",
    "Sys.Syslog",
    "VM.Config.Options",
    "Pool.Audit",
    "User.Modify",
    "VM.Config.HWType",
    "VM.Audit",
    "Sys.PowerMgmt",
    "VM.GuestAgent.Audit",
    "Mapping.Audit",
    "VM.GuestAgent.FileRead",
    "Permissions.Modify",
)


def setUpModule():
    todo_i18n._current_lang = "fr"


def tearDownModule():
    todo_i18n._current_lang = _LANGUE_ORIGINE


class Hote:
    """Exécuteur factice : sorties selon le préfixe, journal des commandes."""

    def __init__(self, uid="0", sudo_ok=True, jetons=(), users=(), content="iso"):
        self.uid, self.sudo_ok = uid, sudo_ok
        self.jetons, self.users, self.content = list(jetons), list(users), content
        self.journal = []

    def __call__(self, cmd):
        self.journal.append(cmd)
        if cmd == "id -u":
            return 0, self.uid + "\n"
        if cmd == "sudo -n true":
            return (0 if self.sudo_ok else 1), ""
        if "token list" in cmd:
            if "tofu@pve" not in self.users:
                return 2, "user does not exist"
            return 0, json.dumps([{"tokenid": j} for j in self.jetons])
        if "user list" in cmd:
            return 0, json.dumps([{"userid": u} for u in self.users])
        if "pvesh get" in cmd:
            return 0, json.dumps({"content": self.content})
        if "token add" in cmd:
            return 0, AJOUT
        return 0, ""


class TestPur(unittest.TestCase):
    def test_contenus(self):
        self.assertEqual(
            jp.contenus_requis("iso,vztmpl,backup"),
            "backup,import,iso,snippets,vztmpl",
        )

    def test_extraire(self):
        self.assertEqual(
            jp.extraire_jeton(AJOUT, "parc-a"), f"tofu@pve!parc-a={SECRET}"
        )
        with self.assertRaises(ValueError) as c:
            jp.extraire_jeton('{"x": 1}', "parc-a")
        self.assertNotIn(SECRET, str(c.exception))

    def test_commandes(self):
        self.assertEqual(jp.PRIVILEGES, PRIVILEGES_ATTENDUS)
        privs = ",".join(jp.PRIVILEGES)
        self.assertIn("SDN.Use", jp.PRIVILEGES)
        self.assertIn("SDN.Audit", jp.PRIVILEGES)
        self.assertEqual(
            jp.commandes_preparation("parc-a", "local", "import,snippets", True),
            [
                f'pveum role add ERPLibreTofu -privs "{privs}"'
                f' || pveum role modify ERPLibreTofu -privs "{privs}"',
                "pveum user add tofu@pve",
                "pveum aclmod / -user tofu@pve -role ERPLibreTofu",
                "pveum user token remove tofu@pve parc-a",
                "pveum user token add tofu@pve parc-a --privsep 0"
                " --output-format json",
                "pvesm set local --content import,snippets",
            ],
        )
        self.assertEqual(len(jp.commandes_preparation("p", "local", "x", False)), 5)


class TestPreparer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.racine = Path(self.tmp.name)
        self.spec = sp.nouvelle_spec("parc-a", "pve")

    def lancer(self, hote, recreer=False):
        avant = copy.deepcopy(self.spec)
        res, neuve = jp.preparer_hote(self.spec, hote, recreer, self.racine)
        self.assertEqual(self.spec, avant)
        self.assertNotIn(SECRET, res.message)
        return res, neuve

    def test_root_cree_jeton(self):
        hote = Hote()
        res, neuve = self.lancer(hote)
        self.assertTrue(res.ok)
        self.assertEqual(neuve["cible"]["hote"]["sudo"], "")
        self.assertEqual(neuve["cible"]["stockage_snippets"], "local")
        self.assertEqual(
            coffre.lire("parc-a", self.racine)["jeton"],
            f"tofu@pve!parc-a={SECRET}",
        )
        chemin = self.racine / "parc-a" / "secrets.json"
        self.assertEqual(stat.S_IMODE(os.stat(chemin).st_mode), 0o600)
        self.assertTrue(any(c.startswith("pveum role add") for c in hote.journal))
        self.assertIn("pvesm set local --content import,iso,snippets", hote.journal)
        self.assertFalse(any(c.startswith("sudo") for c in hote.journal[2:]))

    def test_non_root_sudo(self):
        hote = Hote(uid="1000")
        res, neuve = self.lancer(hote)
        self.assertTrue(res.ok)
        self.assertEqual(neuve["cible"]["hote"]["sudo"], "sudo ")
        ecrits = [c for c in hote.journal if "pveum role add" in c]
        self.assertTrue(ecrits[0].startswith("sudo sh -c "))

    def test_non_root_sans_sudo(self):
        hote = Hote(uid="1000", sudo_ok=False)
        res, _ = self.lancer(hote)
        self.assertFalse(res.ok)
        self.assertIn("NOPASSWD", res.message)
        self.assertEqual(hote.journal, ["id -u", "sudo -n true"])

    def test_stockage_choisi(self):
        self.spec["cible"]["stockage_snippets"] = "dir1"
        hote = Hote()
        res, neuve = self.lancer(hote)
        self.assertEqual(neuve["cible"]["stockage_snippets"], "dir1")
        self.assertTrue(any("pvesh get /storage/dir1" in c for c in hote.journal))

    def test_utilisateur_present_non_recree(self):
        hote = Hote(users=["tofu@pve"])
        self.lancer(hote)
        self.assertNotIn("pveum user add tofu@pve", hote.journal)

    def test_jeton_connu_contenus_manquants(self):
        coffre.ecrire("parc-a", {"jeton": "tofu@pve!parc-a=zz"}, self.racine)
        hote = Hote(jetons=["parc-a"], users=["tofu@pve"], content="iso")
        res, _ = self.lancer(hote)
        self.assertTrue(res.ok)
        self.assertFalse(any("token add" in c for c in hote.journal))
        self.assertIn("pvesm set local --content import,iso,snippets", hote.journal)
        self.assertTrue(any("role add" in c for c in hote.journal))
        self.assertTrue(any("aclmod" in c for c in hote.journal))

    def test_tout_en_place_aucune_ecriture(self):
        coffre.ecrire("parc-a", {"jeton": "tofu@pve!parc-a=zz"}, self.racine)
        hote = Hote(
            jetons=["parc-a"], users=["tofu@pve"], content="import,iso,snippets"
        )
        res, _ = self.lancer(hote)
        self.assertTrue(res.ok)
        self.assertEqual(res.message, "Hôte déjà préparé.")
        for ecriture in ("token add", "token remove", "user add", "pvesm set"):
            self.assertFalse(any(ecriture in c for c in hote.journal), ecriture)

    def test_premiere_preparation_utilisateur_absent(self):
        hote = Hote(users=[])
        res, _ = self.lancer(hote)
        self.assertTrue(res.ok)
        self.assertFalse(any("token list" in c for c in hote.journal))

    def test_coffre_illisible_apres_ajout(self):
        from unittest import mock

        with mock.patch.object(coffre, "ecrire", side_effect=OSError("x")):
            res, _ = self.lancer(Hote())
        self.assertFalse(res.ok)
        self.assertIn("recréant", res.message)

    def test_existe_sans_secret_propose_recreer(self):
        hote = Hote(jetons=["parc-a"], users=["tofu@pve"])
        res, _ = self.lancer(hote)
        self.assertFalse(res.ok)
        self.assertIn("Recréer", res.message)
        self.assertFalse(any("role add" in c for c in hote.journal))
        self.assertEqual(coffre.lire("parc-a", self.racine), {})

    def test_recreer(self):
        coffre.ecrire("parc-a", {"phrase_etat": "p" * 20}, self.racine)
        hote = Hote(jetons=["parc-a"], users=["tofu@pve"])
        res, _ = self.lancer(hote, recreer=True)
        self.assertTrue(res.ok)
        self.assertLess(
            hote.journal.index("pveum user token remove tofu@pve parc-a"),
            next(i for i, c in enumerate(hote.journal) if "token add" in c),
        )
        donnees = coffre.lire("parc-a", self.racine)
        self.assertEqual(donnees["phrase_etat"], "p" * 20)
        self.assertEqual(donnees["jeton"], f"tofu@pve!parc-a={SECRET}")

    def test_echec_commande_nomme_sans_secret(self):
        class Casse(Hote):
            def __call__(self, cmd):
                if "aclmod" in cmd:
                    return 2, SECRET
                return super().__call__(cmd)

        res, _ = self.lancer(Casse())
        self.assertFalse(res.ok)
        self.assertIn("aclmod", res.message)


if __name__ == "__main__":
    unittest.main()
