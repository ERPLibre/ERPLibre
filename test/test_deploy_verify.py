#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce qu'un déploiement affirme, COUCHE PAR COUCHE — la station d'abord.

Un code unique perd ce qui sert le plus, et deux faits sur la même station
n'ont pas la même gravité : sans le groupe libvirt rien ne se déploie, sans
accélération tout se déploie encore — simplement émulé.

Les deux entrées se passent en paramètre : être hors du groupe ne se simule
pas en y étant, et une station sans accélération ne se fabrique pas. Rien
ici ne lance de sous-processus, rien n'exige de privilège.
"""

import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.todo import deploy_verify as V  # noqa: E402
from script.todo import devstack_report as R  # noqa: E402
from script.remote import host_probe as P  # noqa: E402
from script.todo import host_os  # noqa: E402


class TestLesDeuxGravites(unittest.TestCase):
    def couches(self, groupe=(True, True), kvm=True):
        return V.host_layers(groupe=groupe, kvm=kvm)

    def test_a_station_that_can_drive_and_accelerate_is_green(self):
        self.assertEqual(R.DS_OK, R.aggregate_layers(self.couches()))

    def test_without_the_group_nothing_deploys(self):
        """Le suivi d'installation tourne DÉTACHÉ, sans terminal : il ne
        peut répondre à aucune demande de mot de passe."""
        self.assertEqual(
            R.DS_ERR, R.aggregate_layers(self.couches(groupe=(False, False)))
        )

    def test_without_acceleration_everything_still_deploys(self):
        """Une lenteur n'est pas une panne : rendre ERR ici ferait refuser
        un hôte qui marche."""
        codes = [c.code for c in self.couches(kvm=False)]
        self.assertIn(R.DS_SKIP, codes)
        self.assertNotIn(R.DS_ERR, codes)

    def test_a_session_older_than_the_group_is_its_own_case(self):
        """Les groupes d'un processus sont figés à l'ouverture de session :
        proposer un usermod déjà fait envoie corriger ce qui l'est."""
        declaree = self.couches(groupe=(True, False))
        absente = self.couches(groupe=(False, False))
        self.assertEqual(R.DS_ERR, declaree[0].code)
        self.assertNotEqual(declaree[0].detail, absente[0].detail)
        self.assertNotEqual(declaree[0].remedy, absente[0].remedy)

    def test_every_failure_says_what_to_do(self):
        for groupe in ((True, False), (False, False)):
            for kvm in (True, False):
                for couche in self.couches(groupe=groupe, kvm=kvm):
                    if couche.code == R.DS_OK:
                        continue
                    with self.subTest(groupe=groupe, kvm=kvm):
                        self.assertTrue(couche.remedy)

    def test_both_facts_are_always_reported(self):
        """Taire celui qui va bien laisserait croire qu'il n'a pas été
        regardé — et un bloc muet se lit comme « tout va bien »."""
        for groupe in ((True, True), (True, False), (False, False)):
            for kvm in (True, False):
                with self.subTest(groupe=groupe, kvm=kvm):
                    self.assertEqual(
                        2, len(self.couches(groupe=groupe, kvm=kvm))
                    )

    def test_every_layer_is_in_the_closed_vocabulary(self):
        for couche in self.couches(groupe=(False, False), kvm=False):
            self.assertIn(couche.layer, R.LAYERS)

    def test_it_composes_and_does_not_probe(self):
        """Une deuxième mesure à côté de la première est ce qui les fait
        diverger, et c'est le chemin recopié qui dérive en silence."""
        import ast

        chemin = os.path.join(RACINE, "script", "todo", "deploy_verify.py")
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        importes = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                importes.update(a.name for a in noeud.names)
            elif isinstance(noeud, ast.ImportFrom) and noeud.module:
                importes.add(noeud.module)
        self.assertNotIn("subprocess", importes)
        appels = [
            noeud.func.id
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name)
        ]
        for interdit in ("print", "input", "open"):
            self.assertNotIn(interdit, appels)


class TestLeVerbeDeLaStation(unittest.TestCase):
    """Les couches étaient justes, éprouvées et INVISIBLES : rien ne les
    demandait depuis un écran.

    Découvrir un groupe manquant ou un réseau en collision au bout de vingt
    minutes d'installation coûte bien plus cher qu'une lecture d'une
    seconde — d'où un verbe qui ne crée rien.
    """

    def jouer(self, faits, groupe=(True, True), kvm=True):
        import io as tampon_io
        from contextlib import redirect_stdout

        from script.todo.todo import TODO
        from script.todo import deploy_verify

        todo = TODO.__new__(TODO)
        todo._qemu_station_facts = lambda mod=None: faits
        vrai = deploy_verify.host_layers
        deploy_verify.host_layers = lambda **_kw: vrai(groupe=groupe, kvm=kvm)
        self.addCleanup(setattr, deploy_verify, "host_layers", vrai)
        tampon = tampon_io.StringIO()
        with redirect_stdout(tampon):
            code = todo._qemu_verify_station()
        return code, tampon.getvalue()

    FAITS = {
        "active": True,
        "autostart": True,
        "cidr": "192.0.2.0/24",
        "collision": "",
    }

    def test_a_healthy_station_is_green_and_says_every_layer(self):
        code, vu = self.jouer(self.FAITS)
        self.assertEqual(R.DS_OK, code)
        self.assertIn("host", vu)
        self.assertIn("network", vu)

    def test_it_names_the_subject_of_the_block(self):
        """Les tirets seuls ne prouvent rien : le titre par défaut les
        porte aussi. C'est le SUJET qui doit s'y lire."""
        from script.todo import todo_i18n

        _code, vu = self.jouer(self.FAITS)
        self.assertIn(f"── {todo_i18n.t('Station')} ──", vu)
        self.assertNotIn(todo_i18n.t("Layers"), vu)

    def test_a_collision_reddens_the_verb(self):
        code, vu = self.jouer(dict(self.FAITS, collision="198.51.100.0/24"))
        self.assertEqual(R.DS_ERR, code)
        self.assertIn("198.51.100.0/24", vu)

    def test_a_missing_group_reddens_it_too(self):
        code, _vu = self.jouer(self.FAITS, groupe=(False, False))
        self.assertEqual(R.DS_ERR, code)

    def test_a_network_that_could_not_be_read_is_never_green(self):
        """Ce qui n'a pas été lu n'est pas VERT : un bloc muet se lirait
        comme « tout va bien »."""
        code, vu = self.jouer({})
        self.assertNotEqual(R.DS_OK, code)
        self.assertIn("network", vu)

    def test_it_creates_nothing(self):
        """Un verbe de vérification qui modifie n'est plus une
        vérification. Il ne compose que des lectures."""
        import ast

        chemin = os.path.join(RACINE, "script", "todo", "qemu_deploy.py")
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        corps = [
            noeud
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.FunctionDef)
            and noeud.name == "_qemu_verify_station"
        ]
        self.assertEqual(1, len(corps))
        appels = [
            noeud.func.attr
            for noeud in ast.walk(corps[0])
            if isinstance(noeud, ast.Call)
            and isinstance(noeud.func, ast.Attribute)
        ]
        for interdit in ("exec_command_live", "run", "ensure_network"):
            self.assertNotIn(interdit, appels)


class TestLeVerbeDeLaMachine(unittest.TestCase):
    """Le pendant du verbe de station : celui-là dit si l'on PEUT déployer,
    celui-ci ce qu'une machine déjà là tient."""

    INVENTAIRE = "aaaaaaaa-1111-2222-3333-444444444444 vm-a\n"

    def jouer(self, adresse="198.51.100.5", bail="vm-a", sonde="loaded"):
        import builtins
        import io as tampon_io
        from contextlib import redirect_stdout

        from script.posture import plan
        from script.todo.todo import TODO
        from script.vm import backend as VMB

        todo = TODO.__new__(TODO)
        todo._qemu_list_domains_proved = lambda: VMB.parse_uuid_listing(
            self.INVENTAIRE
        )
        todo._parse_index_selection = lambda brut, noms: list(noms)
        todo._qemu_resolve_ips = lambda noms: (
            {"vm-a": adresse} if adresse else {}
        )
        todo._qemu_lease_name = lambda adr, mod=None: bail
        todo._egress_read = lambda cmd: f"{plan.MARQUEUR}{sonde}"
        vrai = builtins.input
        builtins.input = lambda *_a, **_k: "1"
        tampon = tampon_io.StringIO()
        try:
            with redirect_stdout(tampon):
                code = todo._qemu_verify_vm()
        finally:
            builtins.input = vrai
        return code, tampon.getvalue()

    def test_a_healthy_machine_names_every_layer_it_probed(self):
        code, vu = self.jouer()
        for couche in ("dns", "firewall", "tls"):
            with self.subTest(couche=couche):
                self.assertIn(couche, vu)
        self.assertNotEqual(R.DS_ERR, code)

    def test_a_lease_under_another_name_reddens_it(self):
        """Le cas où l'on croit joindre une machine et où l'on en joint
        une autre."""
        code, vu = self.jouer(bail="ancien-nom")
        self.assertEqual(R.DS_ERR, code)
        self.assertIn("ancien-nom", vu)

    def test_rules_that_did_not_load_redden_it_too(self):
        code, _vu = self.jouer(sonde="table-absent")
        self.assertEqual(R.DS_ERR, code)

    def test_without_an_address_nothing_is_claimed_about_the_rules(self):
        """Ce qui n'a pas été sondé n'est pas rendu vert, et n'est pas
        rendu rouge non plus : il n'est pas rendu."""
        _code, vu = self.jouer(adresse="", bail="")
        self.assertIn("dns", vu)
        self.assertNotIn("firewall", vu)

    def test_it_names_each_machine_it_reports_on(self):
        _code, vu = self.jouer()
        self.assertIn("── vm-a ──", vu)

    def test_the_lease_is_read_under_a_forced_locale(self):
        """L'inventaire TRADUIT ses en-têtes. L'analyseur reconnaît
        l'adresse par sa forme, mais lire la sortie d'un outil sous une
        locale inconnue est un piège que ce dépôt a déjà payé ailleurs."""
        from unittest.mock import patch

        from script.todo.todo import TODO

        vues = {}

        class Reponse:
            returncode = 0
            stdout = (
                " 2026-09-08 10:00:00   52:54:00:11:22:33   ipv4"
                "       198.51.100.5/24        vm-a       -\n"
            )

        def espion(argv, **kwargs):
            # « virsh_argv » sonde lui-même pour décider du sudo : l'espion
            # répond à tout le monde et ne retient que la lecture des baux.
            if "net-dhcp-leases" in argv:
                vues["argv"] = argv
                vues["env"] = kwargs.get("env")
                return Reponse()
            vide = Reponse()
            vide.stdout = ""
            vide.returncode = 0
            return vide

        from script.todo import qemu_privilege

        qemu_privilege.reset_cache()
        self.addCleanup(qemu_privilege.reset_cache)
        todo = TODO.__new__(TODO)
        with patch("script.todo.qemu_deploy.subprocess.run", espion):
            nom = todo._qemu_lease_name("198.51.100.5")
        self.assertEqual("vm-a", nom)
        self.assertIn("net-dhcp-leases", vues["argv"])
        self.assertEqual("C", (vues["env"] or {}).get("LC_ALL"))

    def test_a_bridge_has_no_named_network_and_nothing_is_read(self):
        """« --network bridge=br0 » ne nomme aucun réseau libvirt : lui en
        demander les baux passerait « None » à l'inventaire."""
        from unittest.mock import patch

        from script.todo.todo import TODO

        class ModuleDeBanc:
            DEFAULT_NETWORK = "bridge=br0"

            @staticmethod
            def network_name(_arg):
                return None

        appels = []
        todo = TODO.__new__(TODO)
        todo._qemu_import_module = lambda: ModuleDeBanc
        with patch(
            "script.todo.qemu_deploy.subprocess.run",
            lambda *a, **k: appels.append(a) or None,
        ):
            self.assertEqual("", todo._qemu_lease_name("198.51.100.5"))
        self.assertEqual([], appels)

    def test_no_address_reads_nothing_at_all(self):
        """Une lecture pour une adresse vide coûterait un processus pour
        une réponse connue d'avance."""
        from unittest.mock import patch

        from script.todo.todo import TODO

        appels = []
        with patch(
            "script.todo.qemu_deploy.subprocess.run",
            lambda *a, **k: appels.append(a) or None,
        ):
            self.assertEqual("", TODO.__new__(TODO)._qemu_lease_name(""))
        self.assertEqual([], appels)

    def test_it_changes_nothing_on_the_machine(self):
        """Un verbe de vérification qui modifie n'est plus une
        vérification."""
        import ast

        chemin = os.path.join(RACINE, "script", "todo", "qemu_deploy.py")
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        corps = [
            noeud
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.FunctionDef)
            and noeud.name == "_qemu_verify_vm"
        ][0]
        appels = [
            noeud.func.attr
            for noeud in ast.walk(corps)
            if isinstance(noeud, ast.Call)
            and isinstance(noeud.func, ast.Attribute)
        ]
        for interdit in ("exec_command_live", "delete_command"):
            self.assertNotIn(interdit, appels)


class TestLaTraductionDeLaSonde(unittest.TestCase):
    """Elle vivait dans un ÉCRAN, éprouvée seulement à travers lui. Elle ne
    dépend d'aucune conversation, et deux écrans qui la recopieraient
    divergeraient au premier verdict ajouté."""

    @staticmethod
    def verdict(kind, **extra):
        from script.remote import host_probe

        return host_probe.Verdict(kind, **extra)

    def couches_de(self, kind, **extra):
        return V.probe_layers(self.verdict(kind, **extra))

    def test_ssh_through_and_the_product_there_is_green(self):
        couches = self.couches_de(P.OK, version="1.8.0")
        self.assertEqual(R.DS_OK, R.aggregate_layers(couches))
        self.assertIn("1.8.0", " ".join(c.detail for c in couches))

    def test_an_unknown_host_key_is_refused_not_broken(self):
        """Ce n'est pas une panne : c'est un accord qui manque, et il
        s'obtient puis se re-sonde."""
        couches = self.couches_de(P.HOSTKEY)
        self.assertEqual(R.DS_REFUSED, couches[0].code)
        self.assertEqual("transport", couches[0].layer)

    def test_unreachable_and_product_absent_are_two_sides(self):
        """LE défaut que cette répartition existe pour empêcher : l'un
        envoie vérifier le réseau, l'autre envoie installer."""
        injoignable = self.couches_de(P.UNREACHABLE, detail="timeout")
        absent = self.couches_de(P.PRODUCT_ABSENT, detail="not found")
        self.assertEqual({"transport"}, {c.layer for c in injoignable})
        self.assertIn("service", {c.layer for c in absent})
        transport = [c for c in absent if c.layer == "transport"][0]
        self.assertEqual(R.DS_OK, transport.code)

    def test_no_passwordless_sudo_is_an_absence_not_a_failure(self):
        """Deux verbes sur onze en ont besoin : refuser la machine pour eux
        fermerait les neuf autres, qui marchent."""
        couches = self.couches_de(P.NO_PRIVILEGE, version="1.8.0")
        hote = [c for c in couches if c.layer == "host"][0]
        self.assertEqual(R.DS_SKIP, hote.code)
        self.assertNotEqual(R.DS_ERR, R.aggregate_layers(couches))

    def test_root_and_elevation_are_told_apart(self):
        racine = self.couches_de(P.OK, version="1.8.0", sudo="")
        eleve = self.couches_de(P.OK, version="1.8.0", sudo="sudo ")
        dire = lambda cs: [c for c in cs if c.layer == "host"][0].detail
        self.assertNotEqual(dire(racine), dire(eleve))

    def test_a_verdict_outside_the_vocabulary_says_so(self):
        """Le vocabulaire est clos : un septième verdict se dit ici plutôt
        que de tomber en silence dans la branche du succès."""
        couches = V.probe_layers(self.verdict("jamais-un-verdict"))
        self.assertEqual(R.DS_ERR, couches[0].code)

    def test_every_verdict_of_the_vocabulary_is_translated(self):
        for kind in P.VERDICTS:
            with self.subTest(kind=kind):
                couches = self.couches_de(kind, version="1.8.0")
                self.assertTrue(couches)
                for couche in couches:
                    self.assertIn(couche.layer, R.LAYERS)


class TestLaCoucheDns(unittest.TestCase):
    """Un bail au MAUVAIS nom est pire qu'aucun bail."""

    def test_a_lease_bearing_the_name_is_green(self):
        couche = V.dns_layers("vm-a", lease="vm-a", address="198.51.100.5")[0]
        self.assertEqual(R.DS_OK, couche.code)
        self.assertIn("198.51.100.5", couche.detail)

    def test_an_address_under_another_name_is_a_failure(self):
        """Une VM renommée dont le bail porte l'ancien nom d'hôte se voit
        attribuer ce que l'ancien nom désigne — et un alias ssh écrit sur
        ce nom mène ailleurs."""
        couche = V.dns_layers(
            "vm-a", lease="ancien-nom", address="198.51.100.5"
        )[0]
        self.assertEqual(R.DS_ERR, couche.code)
        self.assertIn("ancien-nom", couche.detail)

    def test_an_address_without_any_lease_is_a_failure_too(self):
        """Ce n'est PAS un demi-succès : c'est le cas où l'on croit joindre
        une machine et où l'on en joint une autre."""
        couche = V.dns_layers("vm-a", address="198.51.100.5")[0]
        self.assertEqual(R.DS_ERR, couche.code)

    def test_nothing_at_all_is_a_clean_withdrawal(self):
        """La machine peut n'avoir pas fini de démarrer : rien n'est prouvé
        ni infirmé."""
        couche = V.dns_layers("vm-a")[0]
        self.assertEqual(R.DS_SKIP, couche.code)

    def test_every_failure_says_what_to_do(self):
        for kw in (
            dict(lease="autre", address="198.51.100.5"),
            dict(address="198.51.100.5"),
            dict(),
        ):
            couche = V.dns_layers("vm-a", **kw)[0]
            with self.subTest(**kw):
                self.assertTrue(couche.remedy)
                self.assertEqual("dns", couche.layer)


class TestLaCoucheTls(unittest.TestCase):
    """Deux retraits, et non un silence : une couche omise se lit comme une
    couche tenue."""

    def test_no_domain_means_the_layer_has_no_object(self):
        couche = V.tls_layers()[0]
        self.assertEqual(R.DS_SKIP, couche.code)
        self.assertEqual("tls", couche.layer)

    def test_a_declared_domain_is_a_work_to_do_and_says_so(self):
        """La seconde situation n'est pas un non-sujet : personne ne
        regarde encore, et le taire le ferait oublier."""
        couche = V.tls_layers("exemple.invalid")[0]
        self.assertEqual(R.DS_SKIP, couche.code)
        self.assertIn("exemple.invalid", couche.detail)

    def test_the_two_withdrawals_do_not_say_the_same_thing(self):
        self.assertNotEqual(
            V.tls_layers()[0].detail,
            V.tls_layers("exemple.invalid")[0].detail,
        )

    def test_neither_is_ever_green(self):
        """Rien n'est sondé : rendre vert serait le mensonge que le
        vocabulaire existe pour empêcher."""
        for domaine in ("", "exemple.invalid"):
            with self.subTest(domaine=domaine):
                self.assertNotEqual(R.DS_OK, V.tls_layers(domaine)[0].code)


class TestLaCoucheReseau(unittest.TestCase):
    """Elle était DÉCLARÉE dans le vocabulaire et émise nulle part."""

    def test_a_network_up_and_armed_is_green(self):
        couches = V.network_layers(active=True, autostart=True)
        self.assertEqual(R.DS_OK, R.aggregate_layers(couches))

    def test_the_subnet_is_named_when_all_is_well(self):
        """Le rapport sert aussi à savoir OÙ vivent les machines."""
        couches = V.network_layers(
            active=True, autostart=True, cidr="192.0.2.0/24"
        )
        self.assertIn("192.0.2.0/24", couches[0].detail)

    def test_a_network_not_started_is_a_failure(self):
        couches = V.network_layers(active=False, autostart=True)
        self.assertEqual(R.DS_ERR, couches[0].code)

    def test_working_but_not_armed_is_a_failure_too(self):
        """La panne arriverait DÉTACHÉE de sa cause, au démarrage suivant :
        c'est ce qui coûte le plus cher à diagnostiquer."""
        couches = V.network_layers(active=True, autostart=False)
        self.assertEqual(R.DS_ERR, couches[0].code)
        # « autostart » s'écrit pareil dans les deux langues ; une phrase
        # citée en une seule tomberait sur l'autre.
        self.assertIn("autostart", couches[0].remedy.lower())
        arrete = V.network_layers(active=False, autostart=False)
        self.assertNotEqual(arrete[0].detail, couches[0].detail)

    def test_a_collision_dominates_and_speaks_alone(self):
        """L'autostart ÉTEINT est alors le BON état : le signaler ferait
        corriger ce qui protège."""
        couches = V.network_layers(
            active=True, autostart=False, collision="198.51.100.0/24"
        )
        self.assertEqual(1, len(couches))
        self.assertIn("198.51.100.0/24", couches[0].detail)
        self.assertNotIn("autostart", couches[0].detail.lower())

    def test_a_collision_is_named_and_not_merely_announced(self):
        """« il y a une collision » n'apprend rien : c'est le réseau
        recouvert qui dit quoi déplacer."""
        couches = V.network_layers(
            active=False, autostart=False, collision="198.51.100.0/24"
        )
        self.assertIn("198.51.100.0/24", couches[0].detail)

    def test_every_failure_says_what_to_do(self):
        for kw in (
            dict(active=False, autostart=False),
            dict(active=True, autostart=False),
            dict(active=True, autostart=False, collision="198.51.100.0/24"),
        ):
            for couche in V.network_layers(**kw):
                with self.subTest(**kw):
                    self.assertTrue(couche.remedy)

    def test_it_never_leaves_the_closed_vocabulary(self):
        for kw in (
            dict(active=True, autostart=True),
            dict(active=False, autostart=False),
            dict(active=True, autostart=False, collision="x"),
        ):
            for couche in V.network_layers(**kw):
                with self.subTest(**kw):
                    self.assertEqual("network", couche.layer)
                    self.assertIn(couche.code, R.CODES)


class TestLaRegleDeLAcceleration(unittest.TestCase):
    """La présence suffit HORS root : libvirt tourne en root et se moque
    de notre appartenance au groupe kvm."""

    def test_an_absent_node_is_never_available(self):
        vrai = host_os.CHEMIN_KVM
        host_os.CHEMIN_KVM = "/n-existe-pas.invalid/kvm"
        self.addCleanup(setattr, host_os, "CHEMIN_KVM", vrai)
        self.assertFalse(host_os.kvm_available(euid=0))
        self.assertFalse(host_os.kvm_available(euid=1000))

    def test_presence_is_enough_when_we_are_not_root(self):
        """Tester nos propres droits ferait crier « pas de KVM » à un
        utilisateur simplement hors du groupe, dont les machines
        s'accéléreraient très bien."""
        vrai = host_os.CHEMIN_KVM
        host_os.CHEMIN_KVM = os.devnull
        self.addCleanup(setattr, host_os, "CHEMIN_KVM", vrai)
        self.assertTrue(host_os.kvm_available(euid=1000))

    def test_as_root_the_access_is_what_decides(self):
        """Un nœud présent mais illisible donne une émulation intégrale,
        sans que rien ne le signale."""
        import tempfile

        with tempfile.NamedTemporaryFile() as fichier:
            os.chmod(fichier.name, 0o000)
            vrai = host_os.CHEMIN_KVM
            host_os.CHEMIN_KVM = fichier.name
            self.addCleanup(setattr, host_os, "CHEMIN_KVM", vrai)
            lisible = os.access(fichier.name, os.R_OK | os.W_OK)
            self.assertEqual(lisible, host_os.kvm_available(euid=0))
            self.assertTrue(host_os.kvm_available(euid=1000))

    def test_the_capability_and_the_layer_agree_here(self):
        """La couche d'accélération est la SECONDE : la première dit le
        groupe, et les confondre ferait passer l'épreuve sur un hôte où
        l'une des deux va bien."""
        capacite = [c for c in host_os.capabilities() if c.name == "kvm"][0]
        couche = V.host_layers(groupe=(True, True))[1]
        self.assertEqual(capacite.present, couche.code == R.DS_OK)

    def test_and_they_read_it_through_the_same_function(self):
        """Elles ne diffèrent QUE sous root, sur un nœud présent et
        illisible — un cas qu'une épreuve sans privilège ne peut pas
        montrer. L'invariant se tient donc sur l'ARBRE : la capacité passe
        par la règle, elle ne relit pas le système de fichiers."""
        import ast

        chemin = os.path.join(RACINE, "script", "todo", "host_os.py")
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        corps = [
            noeud
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.FunctionDef)
            and noeud.name == "capabilities"
        ][0]
        appels = [
            noeud.func.id
            for noeud in ast.walk(corps)
            if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name)
        ]
        self.assertIn("kvm_available", appels)
        attributs = [
            f"{getattr(n.func.value, 'id', '')}.{n.func.attr}"
            for n in ast.walk(corps)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        ]
        self.assertNotIn("path.exists", attributs)


if __name__ == "__main__":
    unittest.main()
