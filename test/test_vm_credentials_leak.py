#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le mot de passe du compte de la VM, suivi de bout en bout : du formulaire
jusqu'à l'entrée standard du ssh qui le dépose dans l'invité.

Chaque classe déroule UNE chaîne réelle, une seule fois, puis la passe au
crible :

- le formulaire QEMU/KVM, monté sans terminal, reçoit un compte et une
  sonde ; son historique, son aperçu (F3), son vidage (F9) et sa spec (F5)
  sont relevés ;
- cette spec part dans _qemu_deploie_spec avec trois VM — GNOME (servie par
  GNOME Remote Desktop), Cinnamon (xrdp) et serveur. Seules la création des
  VM, la résolution des IP et le lancement détaché sont remplacés : les
  commandes de création, ~/.ssh/config, session.json, les .spec.json et les
  journaux s'écrivent pour de vrai, sous un HOME temporaire ;
- l'enveloppe détachée de la VM GNOME est ensuite JOUÉE par bash, avec un
  ssh simulé qui note ses arguments et son entrée standard ;
- la voie Proxmox suit le même trajet, du _pve_deploy_spec au suivi.

Ce qui est tenu : la sonde ne paraît dans aucun fichier, aucune commande,
aucune sortie, aucun texte d'historique ; redact_secrets n'a donc rien à
rattraper, et masque l'empreinte qui, elle, est dans les commandes ;
l'empreinte se vérifie contre la sonde ; le compte choisi arrive partout où
un ssh part vers la VM ; la sonde n'atteint l'invité que par l'entrée
standard de ssh, et seulement là où elle sert. Sans rien changer, la chaîne
donne le compte « erplibre » et son mot de passe public, qu'aucune commande
distante ne porte en clair.

La sonde est inventée et n'existe nulle part ailleurs dans le dépôt.
"""

import asyncio
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.argv = ["todo.py"]

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.execute.execute import redact_secrets  # noqa: E402
from script.todo import deploy_form_lib  # noqa: E402
from script.todo import qemu_install_monitor as mon  # noqa: E402
from script.todo.deploy_form_history import describe  # noqa: E402
from script.todo.deploy_form_lib import (  # noqa: E402
    VM_PASSWORD_DEFAULT,
    VM_LOGIN_FILE,
    VM_LOGIN_READ_CMD,
    VM_USER_DEFAULT,
    t,
)
from script.todo.todo import TODO  # noqa: E402

try:
    import textual  # noqa: F401

    TEXTUAL = True
except Exception:  # pragma: no cover - dépend de l'environnement
    TEXTUAL = False

SONDE = "Wb8fuiteHq"
COMPTE = "devops"

# Trois VM, une par façon de servir un bureau : GNOME Remote Desktop (qui
# veut le clair), xrdp (qui ne le veut pas) et aucun bureau.
SAVEURS = {"fuite-gnome": "gnome", "fuite-cinnamon": "cinnamon"}
SAVEURS["fuite-serveur"] = ""
IPS = {
    "fuite-gnome": "192.0.2.11",
    "fuite-cinnamon": "192.0.2.12",
    "fuite-serveur": "192.0.2.13",
}


def _verifie(clair, empreinte):
    """Vrai si `empreinte` ($6$sel$…) est celle de `clair`, recalculée par
    openssl avec le même sel."""
    sel = empreinte.split("$")[2]
    res = subprocess.run(
        ["openssl", "passwd", "-6", "-salt", sel, "-stdin"],
        input=clair + "\n",
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip() == empreinte


def _fichiers(racine):
    """{chemin: contenu} de tout ce qui est écrit sous `racine`, lu en
    octets puis décodé sans échec : un binaire ne cache pas une chaîne."""
    vus = {}
    for dossier, _sous, noms in os.walk(racine):
        for nom in noms:
            chemin = os.path.join(dossier, nom)
            with open(chemin, "rb") as fh:
                vus[chemin] = fh.read().decode("utf-8", "replace")
    return vus


class _SubprocessSansPopen:
    """Le module subprocess vu par le suivi, à Popen près : le lancement
    détaché est noté dans une liste, sans rien lancer. Patcher Popen
    lui-même toucherait aussi openssl, qui calcule l'empreinte."""

    def __init__(self, releve):
        self._releve = releve

    def Popen(self, argv, *a, **k):  # noqa: N802 - nom de l'API imitée
        self._releve.append({"argv": list(argv), "env": k.get("env")})

    def __getattr__(self, nom):
        return getattr(subprocess, nom)


class _Home:
    """Un HOME temporaire, avec une paire de clés SSH factice : le
    formulaire en tire sa clé par défaut, ~/.ssh/config et le suivi y
    écrivent."""

    def __init__(self, test_cls):
        self.dir = tempfile.mkdtemp()
        test_cls.addClassCleanup(shutil.rmtree, self.dir, True)
        patch = mock.patch.dict(os.environ, {"HOME": self.dir})
        patch.start()
        test_cls.addClassCleanup(patch.stop)
        ssh = Path(self.dir) / ".ssh"
        ssh.mkdir(mode=0o700)
        (ssh / "id_ed25519").write_text("cle privee factice\n")
        (ssh / "id_ed25519.pub").write_text(
            "ssh-ed25519 AAAAfactice essai@exemple\n"
        )
        self.pub = str(ssh / "id_ed25519.pub")


async def _remplit(app, compte, sonde, garder, apercu):
    """Monte le formulaire, coche la première VM du catalogue, règle le
    compte puis relève ce que le formulaire montre et garde, et déploie
    (F5). `apercu` : liste qui reçoit les commandes de l'aperçu F3."""
    from textual.widgets import SelectionList

    vu = {}
    async with app.run_test(size=(200, 60)) as pilote:
        for _ in range(3):
            await pilote.pause()
        liste = app.query_one(SelectionList)
        liste.select(liste.get_option_at_index(0).value)
        for _ in range(3):
            await pilote.pause()
        app._hist_settle()
        origine = app._hist_snapshot()
        if compte:
            app.query_one("#f_vm_user").value = compte
        if sonde:
            champ = app.query_one("#f_password")
            champ.focus()
            await pilote.pause()
            # Les dernières lettres tapées au clavier : une frappe passe par
            # les messages Input.Changed que l'historique écoute.
            champ.value = sonde[:-2]
            await pilote.pause()
            # Le focus sélectionne le texte : « end » pose le curseur en
            # bout, et la frappe s'ajoute au lieu de remplacer.
            await pilote.press("end")
            for lettre in sonde[-2:]:
                await pilote.press(lettre)
        app.query_one("#f_keep_pw").value = garder
        await pilote.pause()
        app._hist_settle()
        vu["historique"] = repr(app._hist.entries)
        vu["libelles"] = [e["label"] for e in app._hist.entries]
        vu["describe"] = describe(
            origine, app._hist_snapshot(), app._hist_info()
        )
        vu["valeurs"] = repr(app._form_values())
        app.action_preview()
        await pilote.pause()
        app.pop_screen()
        await pilote.pause()
        app.action_dump_state()
        await pilote.pause()
        vu["notifications"] = " ".join(
            str(n.message) for n in app._notifications
        )
        app.action_deploy()
        await pilote.pause()
    vu["spec"] = app._result["spec"]
    vu["apercu"] = list(apercu)
    return vu


def _deploie(todo, spec):
    """_qemu_deploie_spec sur `spec`, la création des VM, la résolution des
    IP et le lancement détaché remplacés. Rend ce que la chaîne a produit :
    les commandes de création, les lancements détachés et la sortie."""
    vu = {"jobs": [], "lancements": []}

    def jobs_cli(jobs, workers, stdin=None):
        vu["jobs"].extend(jobs)
        return [(nom, 0, "", 0.1) for _id, nom, _parts in jobs]

    todo._qemu_deploy_jobs_cli = jobs_cli
    todo._qemu_deploy_jobs_tui = lambda *a, **k: None
    todo._qemu_resolve_ips = lambda noms, labels=None, **k: {
        n: IPS[n] for n in noms if n in IPS
    }
    todo._qemu_vm_meta = lambda nom, mod: ("debian", "13", "amd64")
    sortie = io.StringIO()
    with (
        mock.patch.object(
            mon, "subprocess", _SubprocessSansPopen(vu["lancements"])
        ),
        mock.patch.object(mon, "local_uuid", lambda nom: "uuid-essai"),
        mock.patch.object(mon, "run_monitor", lambda *a, **k: None),
        contextlib.redirect_stdout(sortie),
    ):
        todo._qemu_deploie_spec(spec)
    vu["stdout"] = sortie.getvalue()
    return vu


def _todo():
    todo = TODO.__new__(TODO)
    todo._qemu_list_domains = lambda: []
    todo._qemu_branch_list = lambda: ["develop", "master"]
    todo._qemu_cache_active = lambda: False
    return todo


def _parts_option(parts, nom):
    return parts[parts.index(nom) + 1]


class _Chaine:
    """Le formulaire QEMU/KVM puis le déploiement, joués une fois pour la
    classe. Les sous-classes disent le compte, la sonde et l'option
    « garder »."""

    COMPTE = ""
    SONDE = ""
    GARDER = False

    @classmethod
    def setUpClass(cls):
        if not TEXTUAL:
            raise unittest.SkipTest("Textual absent")
        cls.home = _Home(cls)
        cls.todo = _todo()
        from script.todo.qemu_deploy_form import run_deploy_form

        ctx = cls.todo._qemu_form_context(cls.todo._qemu_import_module())
        ctx.update(free_disk=500, total_disk=900, free_ram=64000, host_cpu=8)
        apercu = []
        construire = ctx["build_command"]
        ctx["build_command"] = lambda vm, spec, dry: apercu.append(
            construire(vm, spec, dry)
        ) or (apercu[-1])
        app = run_deploy_form(ctx, run_app=False)
        cls.form = asyncio.run(
            _remplit(app, cls.COMPTE, cls.SONDE, cls.GARDER, apercu)
        )
        cls.secret = cls.todo._qemu_vm_secret
        spec = dict(cls.form["spec"])
        modele = spec["vms"][0]
        spec["vms"] = [
            dict(
                modele,
                name=nom,
                distro="debian",
                version="13",
                desktop=saveur,
                ram=4096,
            )
            for nom, saveur in SAVEURS.items()
        ]
        cls.spec = spec
        cls.deploie = _deploie(cls.todo, spec)
        cls.disque = _fichiers(cls.home.dir)
        session = [c for c in cls.disque if c.endswith("session.json")]
        cls.session = json.loads(cls.disque[session[0]])
        cls.entrees = {v["name"]: v for v in cls.session["vms"]}
        cls.lancements = {
            nom: lance
            for nom in SAVEURS
            for lance in cls.deploie["lancements"]
            if f"/{nom}.log" in lance["argv"][-1]
        }

    # ------------------------------------------------------------------ #
    # Ce que la chaîne produit, rassemblé
    # ------------------------------------------------------------------ #
    def commandes(self):
        """Toutes les commandes : création, aperçu, enveloppes détachées,
        commandes distantes du manifeste."""
        textes = [" ".join(p) for _i, _n, p in self.deploie["jobs"]]
        textes += self.form["apercu"]
        textes += [" ".join(x["argv"]) for x in self.deploie["lancements"]]
        textes += [e["remote_cmd"] for e in self.entrees.values()]
        return textes

    def textes_formulaire(self):
        f = self.form
        return [
            f["historique"],
            " ".join(f["libelles"]),
            " ".join(f["describe"]),
            f["valeurs"],
            repr(f["spec"]),
            f["notifications"],
        ]

    def parts(self, nom):
        return next(p for _i, n, p in self.deploie["jobs"] if n == nom)

    def mot_de_passe(self):
        return self.SONDE or VM_PASSWORD_DEFAULT

    # ------------------------------------------------------------------ #
    # La sonde
    # ------------------------------------------------------------------ #
    def test_the_chain_ran_end_to_end(self):
        """Garde des autres tests : une chaîne qui n'aurait rien produit
        passerait tous les « assertNotIn »."""
        self.assertEqual(
            set(SAVEURS), {n for _i, n, _p in self.deploie["jobs"]}
        )
        self.assertEqual(set(SAVEURS), set(self.entrees))
        self.assertEqual(3, len(self.deploie["lancements"]))
        self.assertEqual(set(SAVEURS), set(self.lancements))
        # L'aperçu ne connaît que la VM cochée au formulaire.
        self.assertEqual(1, len(self.form["apercu"]))
        suffixes = {Path(c).name for c in self.disque}
        for nom in SAVEURS:
            self.assertIn(f"{nom}.spec.json", suffixes)
            self.assertIn(f"{nom}.log", suffixes)
        self.assertIn("config", suffixes)
        self.assertIn("deploy-form-dump.txt", suffixes)

    def test_the_password_is_written_nowhere(self):
        for chemin, contenu in self.disque.items():
            self.assertNotIn(self.mot_de_passe(), contenu, chemin)

    def test_the_password_is_in_no_command(self):
        for cmd in self.commandes():
            self.assertNotIn(self.mot_de_passe(), cmd)
            self.assertNotIn(self.mot_de_passe(), redact_secrets(cmd))

    def test_the_password_is_not_printed(self):
        self.assertNotIn(self.mot_de_passe(), self.deploie["stdout"])

    def test_the_form_keeps_no_password(self):
        for texte in self.textes_formulaire():
            self.assertNotIn(self.mot_de_passe(), texte)

    def test_the_creation_never_gets_a_clear_password(self):
        for nom in SAVEURS:
            parts = self.parts(nom)
            self.assertNotIn("--password", parts)
            self.assertNotIn("--ask-password", parts)

    # ------------------------------------------------------------------ #
    # L'empreinte
    # ------------------------------------------------------------------ #
    def test_one_hash_verifies_everywhere(self):
        """La même empreinte, vérifiée contre le mot de passe, dans chaque
        commande de création, dans l'aperçu et dans chaque .spec.json."""
        empreintes = {
            _parts_option(self.parts(nom), "--password-hash")
            for nom in SAVEURS
        }
        for chemin, contenu in self.disque.items():
            if chemin.endswith(".spec.json"):
                empreintes.add(json.loads(contenu)["password_hash"])
        self.assertEqual(1, len(empreintes), empreintes)
        empreinte = empreintes.pop()
        self.assertTrue(empreinte.startswith("$6$"))
        self.assertTrue(_verifie(self.mot_de_passe(), empreinte))
        for ligne in self.form["apercu"]:
            self.assertIn(empreinte, ligne)

    def test_redaction_masks_the_hash(self):
        """L'empreinte est dans les commandes ; ce qui les affiche la
        masque (exec passe tout par redact_secrets)."""
        for nom in SAVEURS:
            ligne = " ".join(self.parts(nom))
            empreinte = _parts_option(self.parts(nom), "--password-hash")
            self.assertIn(empreinte, ligne)
            self.assertNotIn(empreinte, redact_secrets(ligne))

    # ------------------------------------------------------------------ #
    # Le compte
    # ------------------------------------------------------------------ #
    def test_the_account_reaches_every_ssh(self):
        compte = self.COMPTE or VM_USER_DEFAULT
        config = next(
            v for c, v in self.disque.items() if c.endswith(".ssh/config")
        )
        for nom, ip in IPS.items():
            self.assertEqual(compte, _parts_option(self.parts(nom), "--user"))
            self.assertRegex(
                config,
                rf"Host {nom}\n    HostName {re.escape(ip)}\n"
                rf"    User {compte}\n",
            )
            entree = self.entrees[nom]
            self.assertEqual(compte, entree["user"])
            self.assertEqual(f"ssh {compte}@{ip}", entree["ssh"])
            enveloppe = self.lancements[nom]["argv"][-1]
            self.assertIn(f"u={compte}; ", enveloppe)
            if compte != VM_USER_DEFAULT:
                self.assertNotIn(f"{VM_USER_DEFAULT}@", enveloppe)
            spec_vm = json.loads(
                Path(entree["spec_file"]).read_text(encoding="utf-8")
            )
            self.assertEqual(compte, spec_vm["user"])
        self.assertEqual(compte, self.todo._qemu_vm_user("fuite-gnome"))

    # ------------------------------------------------------------------ #
    # La commande distante
    # ------------------------------------------------------------------ #
    def test_remote_commands_carry_no_credential(self):
        """grdctl reçoit le mot de passe du fichier, sur son entrée standard
        (grdctl 47 et suivants) ou par « $(cat fichier) » (grdctl 46), et
        rien d'autre ; l'annonce ne le nomme pas. Le défaut public compris :
        il n'est plus écrit dans le script."""
        self.assertFalse(hasattr(TODO, "QEMU_DESKTOP_RDP_PASSWORD"))
        lectures = (
            "grdctl --system rdp set-credentials " f'"$1" < {VM_LOGIN_FILE}',
            "grdctl --system rdp set-credentials "
            f'"$1" "$(cat {VM_LOGIN_FILE})"',
        )
        for nom, saveur in SAVEURS.items():
            cmd = self.entrees[nom]["remote_cmd"]
            if saveur == "gnome":
                self.assertEqual(2, cmd.count("set-credentials"))
                for lecture in lectures:
                    self.assertIn(lecture, cmd)
            else:
                self.assertNotIn("set-credentials", cmd)
            self.assertNotIn(f'/ {VM_PASSWORD_DEFAULT}"', cmd)
            self.assertNotIn(f"/ {VM_PASSWORD_DEFAULT}'", cmd)

    # ------------------------------------------------------------------ #
    # Le voyage du clair jusqu'à l'invité
    # ------------------------------------------------------------------ #
    def pousse(self):
        """{nom: mot de passe remis au processus détaché, ou None}."""
        return {
            nom: (lance["env"] or {}).get(mon.VM_LOGIN_ENV)
            for nom, lance in self.lancements.items()
        }

    def joue_enveloppe(self, nom):
        """Joue l'enveloppe détachée de `nom` sous bash, avec son
        environnement, ssh et l'outillage libvirt simulés. Rend (journal,
        lignes « ENV|argv » de chaque ssh, entrée standard reçue)."""
        trace = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, trace, True)
        bin_dir = Path(trace) / "bin"
        bin_dir.mkdir()
        (bin_dir / "ssh").write_text(
            "#!/bin/sh\n"
            f'printf \'%s|%s\\n\' "${{{mon.VM_LOGIN_ENV}:+ENV}}" "$*"'
            f" >> {trace}/argv\n"
            # « -n » avant la destination branche l'entrée sur /dev/null,
            # comme le vrai ssh.
            'for a in "$@"; do case "$a" in\n'
            "  *@*) break ;;\n"
            "  -n) exec < /dev/null ;;\n"
            "esac; done\n"
            'case "$*" in\n'
            f'  *"cat > {VM_LOGIN_FILE}"*) cat >> {trace}/stdin ;;\n'
            '  *"cloud-init status"*) echo "status: done" ;;\n'
            "esac\n"
            "exit 0\n"
        )
        # Rien de l'hôte n'est joint : libvirt et sudo refusent.
        for outil in ("virsh", "sudo", "sg", "newgrp", "setsid"):
            (bin_dir / outil).write_text("#!/bin/sh\nexit 1\n")
        for f in bin_dir.iterdir():
            f.chmod(0o755)
        lance = self.lancements[nom]
        env = dict(lance["env"] or os.environ)
        env["PATH"] = f"{bin_dir}:{os.environ['PATH']}"
        subprocess.run(
            ["bash", "-c", lance["argv"][-1]],
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=60,
        )
        journal = Path(self.entrees[nom]["log"]).read_text(encoding="utf-8")
        argv = (Path(trace) / "argv").read_text(encoding="utf-8")
        stdin = Path(trace) / "stdin"
        return journal, argv, stdin.read_text() if stdin.exists() else None

    def test_the_gnome_wrapper_delivers_through_stdin_only(self):
        journal, argv, stdin = self.joue_enveloppe("fuite-gnome")
        self.assertEqual(self.mot_de_passe() + "\n", stdin)
        self.assertNotIn(self.mot_de_passe(), argv)
        self.assertNotIn(self.mot_de_passe(), journal)
        compte = self.COMPTE or VM_USER_DEFAULT
        lignes = argv.splitlines()
        depot = [x for x in lignes if f"cat > {VM_LOGIN_FILE}" in x]
        installe = [
            x for x in lignes if mon.INSTALL_TAG in x and x not in depot
        ]
        self.assertEqual(1, len(depot))
        self.assertEqual(1, len(installe))
        self.assertIn(f"{compte}@{IPS['fuite-gnome']}", depot[0])
        self.assertIn(f"{compte}@{IPS['fuite-gnome']}", installe[0])
        # Le dépôt passe la garde d'une installation en cours.
        self.assertIn(mon.INSTALL_TAG, depot[0])
        # Le dépôt avant l'installation, qui lit le fichier.
        self.assertLess(lignes.index(depot[0]), lignes.index(installe[0]))
        # Aucun ssh, le dépôt compris, n'hérite de la variable : l'enveloppe
        # l'a retirée de son environnement dès son premier pas.
        self.assertFalse(
            [x[:40] for x in lignes if x.startswith("ENV|")], argv[:200]
        )
        self.assertTrue(depot[0].startswith("|"), depot[0][:20])
        self.assertTrue(installe[0].startswith("|"), installe[0][:20])
        self.assertIn(f"{mon.EXIT_MARKER} 0", journal)


class TestChosenPassword(_Chaine, unittest.TestCase):
    """Un compte et un mot de passe choisis au formulaire, sans « garder »."""

    COMPTE = COMPTE
    SONDE = SONDE

    def test_the_form_hands_the_password_to_the_process_only(self):
        self.assertEqual(SONDE, self.secret)
        self.assertFalse(self.form["spec"]["login_default"])
        self.assertEqual(COMPTE, self.form["spec"]["user"])
        self.assertTrue(
            any(COMPTE in libelle for libelle in self.form["libelles"])
        )

    def test_only_the_gnome_vm_receives_it(self):
        self.assertEqual(
            {
                "fuite-gnome": SONDE,
                "fuite-cinnamon": None,
                "fuite-serveur": None,
            },
            self.pousse(),
        )
        self.assertIs(True, self.entrees["fuite-gnome"].get("push_login"))
        self.assertNotIn("push_login", self.entrees["fuite-serveur"])

    def test_the_file_is_removed_after_use(self):
        cmd = self.entrees["fuite-gnome"]["remote_cmd"]
        self.assertIn(f"sudo rm -f {VM_LOGIN_FILE}", cmd)

    def test_the_summary_names_the_account_not_the_password(self):
        self.assertIn(
            f"{COMPTE} / {t('password chosen at deployment')}",
            self.deploie["stdout"],
        )

    def test_a_server_wrapper_pushes_nothing(self):
        _journal, argv, stdin = self.joue_enveloppe("fuite-serveur")
        self.assertIsNone(stdin)
        self.assertNotIn(f"cat > {VM_LOGIN_FILE}", argv)
        self.assertNotIn("ENV|", argv)

    def test_the_synchronous_path_hands_it_through_the_environment(self):
        """Sans suivi, l'installation passe par exec_command_live : la
        commande affichée ne porte pas le mot de passe, new_env le porte."""
        appels = []
        todo = self.todo
        todo.execute = mock.Mock()
        todo.execute.exec_command_live = lambda cmd, **k: appels.append(
            (cmd, k)
        )
        todo._qemu_wait_ssh = lambda ip, user=VM_USER_DEFAULT: True
        spec = dict(self.spec, monitor=False)
        spec["install"] = dict(spec["install"], monitor=False)
        sortie = io.StringIO()
        with (
            mock.patch.object(
                todo,
                "_qemu_deploy_jobs_cli",
                lambda jobs, w, stdin=None: [
                    (n, 0, "", 0.1) for _i, n, _p in jobs
                ],
            ),
            contextlib.redirect_stdout(sortie),
        ):
            todo._qemu_deploie_spec(spec)
        self.assertEqual(4, len(appels))
        for cmd, kw in appels:
            self.assertNotIn(SONDE, cmd)
            self.assertNotIn(SONDE, redact_secrets(cmd))
            self.assertIn(f"{COMPTE}@", cmd)
        envs = [kw["new_env"] for _c, kw in appels if "new_env" in kw]
        self.assertEqual([{mon.VM_LOGIN_ENV: SONDE}], envs)
        self.assertNotIn(SONDE, sortie.getvalue())


class TestKeptPassword(_Chaine, unittest.TestCase):
    """L'option « garder dans la VM » : chaque VM créée reçoit le fichier,
    et il reste en place."""

    COMPTE = COMPTE
    SONDE = SONDE
    GARDER = True

    def test_every_created_vm_receives_it(self):
        self.assertEqual(dict.fromkeys(SAVEURS, SONDE), self.pousse())

    def test_the_file_stays_and_its_reading_is_named(self):
        cmd = self.entrees["fuite-gnome"]["remote_cmd"]
        self.assertNotIn(f"sudo rm -f {VM_LOGIN_FILE}", cmd)
        self.assertIn(VM_LOGIN_READ_CMD, cmd)

    def test_a_server_wrapper_delivers_it_too(self):
        _journal, argv, stdin = self.joue_enveloppe("fuite-serveur")
        self.assertEqual(SONDE + "\n", stdin)
        self.assertNotIn(SONDE, argv)


class TestDefaultAccount(_Chaine, unittest.TestCase):
    """Le formulaire laissé tel quel : « erplibre » et son mot de passe
    public, et rien en mémoire."""

    def test_nothing_is_held_in_memory(self):
        self.assertIsNone(self.secret)
        self.assertTrue(self.form["spec"]["login_default"])
        self.assertEqual(VM_USER_DEFAULT, self.form["spec"]["user"])

    def test_the_gnome_vm_still_gets_the_public_password(self):
        """GNOME Remote Desktop le lit dans le fichier, comme un mot de
        passe choisi : le défaut ne fait pas d'exception."""
        self.assertEqual(
            {
                "fuite-gnome": VM_PASSWORD_DEFAULT,
                "fuite-cinnamon": None,
                "fuite-serveur": None,
            },
            self.pousse(),
        )

    def test_the_summary_names_the_public_default(self):
        self.assertIn(
            f"{VM_USER_DEFAULT} / {VM_PASSWORD_DEFAULT}",
            self.deploie["stdout"],
        )

    # Le mot de passe public ressemble au nom du produit : « erplibre » est
    # dans les chemins, les services et le compte. Les tests de fuite de la
    # chaîne cherchent donc ici sa seule forme d'identifiant.
    def test_the_password_is_written_nowhere(self):
        lecture = f'set-credentials "$(id -un)" {VM_PASSWORD_DEFAULT}'
        for chemin, contenu in self.disque.items():
            self.assertNotIn(lecture, contenu, chemin)
            self.assertNotIn(f'/ {VM_PASSWORD_DEFAULT}"', contenu, chemin)

    def test_the_password_is_in_no_command(self):
        for cmd in self.commandes():
            self.assertNotIn("--password ", cmd)
            self.assertNotRegex(
                cmd, rf"set-credentials \S+ '?{VM_PASSWORD_DEFAULT}"
            )

    def test_the_password_is_not_printed(self):
        """Le sommaire nomme le défaut public, à dessein ; rien d'autre."""
        sortie = self.deploie["stdout"].replace(
            f"{VM_USER_DEFAULT} / {VM_PASSWORD_DEFAULT}", ""
        )
        self.assertNotIn(f"/ {VM_PASSWORD_DEFAULT}", sortie)

    def test_the_form_keeps_no_password(self):
        self.assertNotIn("f_password", self.form["historique"])

    def test_the_gnome_wrapper_delivers_through_stdin_only(self):
        _journal, argv, stdin = self.joue_enveloppe("fuite-gnome")
        self.assertEqual(VM_PASSWORD_DEFAULT + "\n", stdin)
        self.assertNotIn(
            f'set-credentials "$(id -un)" {VM_PASSWORD_DEFAULT}', argv
        )


class TestProxmoxChain(unittest.TestCase):
    """La voie Proxmox, de _pve_deploy_spec au suivi : le mot de passe posé
    en mémoire par l'écran (vm_secret_sink), le compte dans la spec."""

    @classmethod
    def setUpClass(cls):
        cls.home = _Home(cls)
        todo = _todo()
        todo._qemu_set_vm_secret(SONDE)
        todo._pve_confirm_spec = lambda host, spec: True
        todo._pve_push_key = lambda cle: True
        todo._pve_attendre_ssh = lambda alias: True
        todo._pve_write_guide = lambda *a, **k: True
        todo._pve_set_timezone = lambda *a, **k: True
        todo._pve_guest_ip = lambda vmid, attente=120: ""
        cls.todo = todo
        cls.travaux = []

        def progression(travaux, parallele, **k):
            cls.travaux.extend(travaux)
            return [(nom, 0, "", 1.0) for nom, _l, _argv in travaux]

        host = {"target": "root@192.0.2.40", "sudo": ""}
        cls.spec = {
            "host": host,
            "storage": "local",
            "bridge": "vmbr1",
            "vms": [
                {
                    "name": nom,
                    "vmid": 200 + k,
                    "distro": "debian",
                    "version": "13",
                    "arch": "amd64",
                    "ram": 4096,
                    "vcpus": 2,
                    "disk": "20G",
                    "desktop": saveur,
                    "ipconfig": f"ip=10.10.10.{150 + k}/24,gw=10.10.10.1",
                    "install_cmd": "",
                }
                for k, (nom, saveur) in enumerate(SAVEURS.items())
            ],
            "existing": [],
            "user": COMPTE,
            "password_hash": "",
            "login_default": False,
            "keep_login_in_vm": False,
            "add_ssh_config": True,
            "install": None,
            "monitor": True,
            "ssh_key": cls.home.pub,
            "ssh_key_local": cls.home.pub,
        }
        cls.lancements = []
        sortie = io.StringIO()
        with (
            mock.patch.object(
                deploy_form_lib, "run_deploy_progress", progression
            ),
            mock.patch.object(
                mon, "subprocess", _SubprocessSansPopen(cls.lancements)
            ),
            mock.patch.object(mon, "run_monitor", lambda *a, **k: None),
            contextlib.redirect_stdout(sortie),
        ):
            todo._pve_deploy_spec(host, cls.spec, todo._qemu_import_module())
        cls.stdout = sortie.getvalue()
        cls.disque = _fichiers(cls.home.dir)
        session = next(c for c in cls.disque if c.endswith("session.json"))
        cls.entrees = {
            v["name"]: v for v in json.loads(cls.disque[session])["vms"]
        }

    def creation(self, nom):
        return next(" ".join(a) for n, _l, a in self.travaux if n == nom)

    def test_the_chain_ran_end_to_end(self):
        self.assertEqual(set(SAVEURS), {n for n, _l, _a in self.travaux})
        self.assertEqual(set(SAVEURS), set(self.entrees))
        self.assertEqual(3, len(self.lancements))

    def test_the_password_leaks_nowhere(self):
        for chemin, contenu in self.disque.items():
            self.assertNotIn(SONDE, contenu, chemin)
        textes = [self.stdout, repr(self.spec)]
        textes += [" ".join(a) for _n, _l, a in self.travaux]
        textes += [" ".join(x["argv"]) for x in self.lancements]
        for texte in textes:
            self.assertNotIn(SONDE, texte)
            self.assertNotIn(SONDE, redact_secrets(texte))

    def test_user_data_carries_the_account_and_a_verified_hash(self):
        empreinte = self.spec["password_hash"]
        self.assertTrue(_verifie(SONDE, empreinte))
        for nom in SAVEURS:
            creation = self.creation(nom)
            self.assertIn(f"name: {COMPTE}", creation)
            self.assertIn(empreinte, creation)
            self.assertNotIn(empreinte, redact_secrets(creation))

    def test_the_account_reaches_every_ssh(self):
        config = next(
            v for c, v in self.disque.items() if c.endswith(".ssh/config")
        )
        for nom in SAVEURS:
            self.assertRegex(
                config, rf"Host \S+\+{nom}\n(    .*\n)*?    User {COMPTE}\n"
            )
            entree = self.entrees[nom]
            self.assertEqual(COMPTE, entree["user"])
            self.assertTrue(entree["ssh"].startswith(f"ssh {COMPTE}@"))
            self.assertTrue(
                mon.vm_ssh_prefix(entree).endswith(
                    f" {COMPTE}@{entree['pve']['addr']}"
                )
            )
        for lance in self.lancements:
            self.assertIn(f"u={COMPTE}; ", lance["argv"][-1])

    def test_only_the_gnome_vm_receives_it(self):
        recus = {
            nom: (x["env"] or {}).get(mon.VM_LOGIN_ENV)
            for x in self.lancements
            for nom in SAVEURS
            if f"/{nom}.log" in x["argv"][-1]
        }
        self.assertEqual(
            {
                "fuite-gnome": SONDE,
                "fuite-cinnamon": None,
                "fuite-serveur": None,
            },
            recus,
        )

    def test_the_kept_spec_holds_the_hash_not_the_password(self):
        for nom in SAVEURS:
            spec_vm = json.loads(
                Path(self.entrees[nom]["spec_file"]).read_text()
            )
            self.assertEqual(
                self.spec["password_hash"], spec_vm["password_hash"]
            )
            self.assertEqual(COMPTE, spec_vm["user"])
            self.assertFalse(spec_vm["login_default"])


if __name__ == "__main__":
    unittest.main()
