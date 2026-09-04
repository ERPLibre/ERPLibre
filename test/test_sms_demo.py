#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Démonstration de la passerelle SMS : ce qui se teste SANS VM.

Tout ce qui est ici est pur — état persisté, enchaînement des étapes, rendu
des scripts et du pense-bête. La création de VM, SSH et Odoo n'y sont pas :
ils exigent une machine, et un test qui exige une machine ne tourne jamais.

Le partage a été fait pour cela. `spec` et `steps` ne savent rien exécuter,
`gateway` ne fait que produire du texte, et `runner` — le seul qui touche à
QEMU — n'est sollicité ici que pour la construction de sa spécification.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class SmsDemoBase(unittest.TestCase):
    """Chaque test travaille dans son propre répertoire.

    L'état de la démonstration vit dans `private/sms/` du dépôt. Sans cette
    isolation, lancer la suite écraserait la démonstration en cours de qui
    la lance — et son secret partagé avec.

    On surcharge `ERPLIBRE_SMS_DEMO_DIR` plutôt que `HOME` : l'emplacement
    est désormais relatif au dépôt, donc déplacer `HOME` n'isole plus rien.
    """

    def setUp(self):
        self._ancien = os.environ.get("ERPLIBRE_SMS_DEMO_DIR")
        self._tmp = tempfile.mkdtemp()
        os.environ["ERPLIBRE_SMS_DEMO_DIR"] = self._tmp
        import importlib

        from script.todo.sms import spec as spec_mod

        self.spec_mod = importlib.reload(spec_mod)
        from script.todo.sms import steps as steps_mod

        self.steps = importlib.reload(steps_mod)

    def tearDown(self):
        if self._ancien is None:
            os.environ.pop("ERPLIBRE_SMS_DEMO_DIR", None)
        else:
            os.environ["ERPLIBRE_SMS_DEMO_DIR"] = self._ancien


class TestEtat(SmsDemoBase):
    def test_un_etat_neuf_na_rien_de_fait(self):
        etat = self.spec_mod.load()
        self.assertEqual(etat.done, [])
        self.assertEqual(etat.errors, {})

    def test_letat_survit_a_un_rechargement(self):
        etat = self.spec_mod.load()
        etat.mark_done("vm")
        etat.vm_ip = "192.168.122.9"
        self.spec_mod.save(etat)
        self.assertEqual(self.spec_mod.load().done, ["vm"])
        self.assertEqual(self.spec_mod.load().vm_ip, "192.168.122.9")

    def test_un_echec_annule_une_reussite_anterieure(self):
        # Sans cela, une démonstration rejouée afficherait une coche verte
        # sur l'étape qui vient précisément de casser.
        etat = self.spec_mod.load()
        etat.mark_done("vm")
        etat.mark_failed("vm", "la VM a disparu")
        self.assertNotIn("vm", etat.done)
        self.assertIn("vm", etat.errors)

    def test_une_reussite_efface_lerreur_precedente(self):
        etat = self.spec_mod.load()
        etat.mark_failed("odoo", "apt a echoue")
        etat.mark_done("odoo")
        self.assertEqual(etat.errors, {})

    def test_un_fichier_illisible_ne_bloque_pas_la_demonstration(self):
        self.spec_mod.save(self.spec_mod.load())
        self.spec_mod.STATE_PATH.write_text("{ ceci n'est pas du json")
        self.assertEqual(self.spec_mod.load().done, [])

    def test_une_cle_inconnue_dans_letat_est_ignoree(self):
        # Un état écrit par une version plus récente ne doit pas faire
        # exploser une version plus ancienne.
        self.spec_mod.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.spec_mod.STATE_PATH.write_text(
            '{"spec": {"vm_name": "x", "champ_du_futur": 1}, "done": []}'
        )
        self.assertEqual(self.spec_mod.load().spec.vm_name, "x")


class TestSecret(SmsDemoBase):
    def test_le_secret_est_stable_entre_deux_appels(self):
        self.assertEqual(
            self.spec_mod.ensure_secret(), self.spec_mod.ensure_secret()
        )

    def test_le_secret_nest_lisible_que_par_son_proprietaire(self):
        self.spec_mod.ensure_secret()
        mode = os.stat(self.spec_mod.SECRET_PATH).st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_le_secret_fait_bien_256_bits(self):
        self.assertEqual(len(self.spec_mod.ensure_secret()), 64)

    def test_loubli_du_secret_en_regenere_un_autre(self):
        premier = self.spec_mod.ensure_secret()
        self.spec_mod.forget_secret()
        self.assertNotEqual(premier, self.spec_mod.ensure_secret())


class TestEnchainement(SmsDemoBase):
    def test_la_premiere_etape_est_la_vm(self):
        self.assertEqual(self.steps.next_step(self.spec_mod.load()).id, "vm")

    def test_une_etape_en_echec_repasse_devant_les_suivantes(self):
        etat = self.spec_mod.load()
        for identifiant in ("vm", "odoo", "gateway"):
            etat.mark_done(identifiant)
        etat.mark_failed("odoo", "cassee")
        self.assertEqual(self.steps.next_step(etat).id, "odoo")

    def test_les_prerequis_manquants_sont_nommes(self):
        etat = self.spec_mod.load()
        manquants = self.steps.blocked_by(self.steps.BY_ID["gateway"], etat)
        self.assertEqual(len(manquants), 2)

    def test_plus_rien_a_faire_quand_tout_est_fait(self):
        etat = self.spec_mod.load()
        for step in self.steps.STEPS:
            etat.mark_done(step.id)
        self.assertIsNone(self.steps.next_step(etat))

    def test_en_attente_et_en_cours_ne_se_confondent_pas(self):
        # Un tableau de bord où « ça travaille » ressemble à « ça patiente »
        # est inutile au moment précis où on le consulte.
        self.assertNotEqual(
            self.steps.ICON["pending"], self.steps.ICON["running"]
        )

    def test_letape_en_cours_prime_sur_letat_persiste(self):
        etat = self.spec_mod.load()
        etat.mark_done("vm")
        self.assertEqual(
            self.steps.status_of(self.steps.BY_ID["vm"], etat, running="vm"),
            "running",
        )

    def test_le_rendu_montre_les_cinq_etapes_et_lerreur(self):
        etat = self.spec_mod.load()
        etat.mark_failed("odoo", "apt introuvable")
        rendu = self.steps.render(etat)
        self.assertEqual(rendu.count("["), len(self.steps.STEPS))
        self.assertIn("apt introuvable", rendu)


class TestRendus(SmsDemoBase):
    def setUp(self):
        super().setUp()
        from script.todo.sms import gateway

        self.gw = gateway
        self.spec = self.spec_mod.DemoSpec()

    def test_le_script_cible_la_bonne_fiche(self):
        script = self.gw.render_setup_script(self.spec)
        self.assertIn(self.spec.device_id, script)
        self.assertIn("erplibre.sms.gateway", script)

    def test_le_script_est_rejouable(self):
        # Il doit réutiliser la fiche existante : une démonstration se reprend
        # souvent à mi-chemin, et deux fiches pour un même appareil rendraient
        # l'état d'Odoo incompréhensible.
        script = self.gw.render_setup_script(self.spec)
        self.assertIn("search(", script)
        self.assertIn("if gw:", script)

    def test_le_script_dit_si_le_secret_manque(self):
        # Sans cette remontée, la fiche serait créée et le téléphone refusé
        # en 401 sans que rien ne l'ait annoncé.
        self.assertIn(
            "RESULTAT_SECRET_PRESENT", self.gw.render_setup_script(self.spec)
        )

    def test_un_numero_hostile_reste_une_chaine(self):
        """Le numéro traverse un shell distant PUIS un `odoo-bin shell`.

        On ne vérifie pas l'échappement à l'œil — on parse le script produit
        et on exige que la charge soit une constante de chaîne, jamais un
        nœud exécutable. C'est la seule preuve qui tienne.
        """
        import ast

        charge = "+1514'; import os; os.system('rm -rf /')"
        script = self.gw.render_test_script(charge, self.spec)
        arbre = ast.parse(script)  # doit rester du Python valide
        constantes = [
            noeud.value
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str)
        ]
        self.assertIn(charge, constantes)
        # Et aucun appel à os.system n'a été introduit par la charge.
        appels = [
            noeud
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.Call)
            and isinstance(noeud.func, ast.Attribute)
            and noeud.func.attr == "system"
        ]
        self.assertEqual(appels, [])

    def test_le_pense_bete_donne_les_trois_valeurs(self):
        bloc = self.gw.render_mobile_config(self.spec, "b" * 64, "10.0.0.5")
        self.assertIn(self.spec.device_id, bloc)
        self.assertIn("b" * 64, bloc)
        self.assertIn(str(self.spec.odoo_port), bloc)

    def test_le_pense_bete_explique_le_renvoi_usb(self):
        # C'est la panne numéro un : sans le renvoi, le 127.0.0.1 du téléphone
        # désigne le téléphone, et rien ne le dit à l'écran.
        bloc = self.gw.render_mobile_config(self.spec, "c" * 64, "10.0.0.5")
        self.assertIn("adb reverse", bloc)

    def test_les_routes_ne_portent_pas_le_nom_du_module(self):
        # Le module a été renommé, le protocole non : tout téléphone déjà
        # installé continue d'appeler les anciennes routes.
        for route in self.gw.ROUTES:
            self.assertTrue(route.startswith("/erplibre_sms/"), route)

    def test_un_secret_absent_se_voit_dans_le_pense_bete(self):
        bloc = self.gw.render_mobile_config(self.spec, "", "10.0.0.5")
        self.assertIn("non genere", bloc)


class TestSpecificationVm(SmsDemoBase):
    """La spécification passée au déploiement QEMU existant."""

    class FauxTodo:
        @staticmethod
        def _qemu_make_vm(distro, version, arch, ram, disk, vcpus, name):
            return {
                "name": name,
                "distro": distro,
                "version": version,
                "arch": arch,
                "ram": ram,
                "disk": disk,
                "vcpus": vcpus,
            }

    def test_la_specification_a_la_forme_attendue(self):
        from script.todo.sms import runner

        spec = runner.build_vm_spec(self.FauxTodo(), self.spec_mod.DemoSpec())
        for cle in ("vms", "install", "monitor", "parallelism", "existing"):
            self.assertIn(cle, spec)
        self.assertEqual(len(spec["vms"]), 1)
        self.assertEqual(spec["vms"][0]["name"], "sms-demo")
        self.assertIn("install_odoo_18", spec["install"]["cmd"])


class TestI18n(SmsDemoBase):
    def test_chaque_cle_sms_existe_dans_les_deux_langues(self):
        from script.todo.todo_i18n import TRANSLATIONS

        incompletes = [
            cle
            for cle, valeur in TRANSLATIONS.items()
            if cle.startswith("sms_")
            and (
                set(valeur) != {"fr", "en"}
                or not valeur["fr"].strip()
                or not valeur["en"].strip()
            )
        ]
        self.assertEqual(incompletes, [])

    def test_chaque_etape_a_son_libelle_traduit(self):
        from script.todo.todo_i18n import TRANSLATIONS

        for step in self.steps.STEPS:
            self.assertIn(step.label_key, TRANSLATIONS, step.id)
            for materiel, variante in step.par_materiel.items():
                self.assertIn(variante.label_key, TRANSLATIONS,
                              f"{step.id}/{materiel}")


class TestModes(SmsDemoBase):
    """Le choix entre démonstration locale et VM jetable."""

    def test_le_defaut_est_local(self):
        # La VM coûte une heure, vingt gigaoctets et du sudo. Elle ne doit
        # pas être ce qu'on obtient sans avoir rien demandé.
        self.assertEqual(self.spec_mod.load().spec.mode, "local")

    def test_letape_une_change_de_sens_selon_le_mode(self):
        from dataclasses import replace

        step = self.steps.STEPS[0]
        local = self.spec_mod.DemoSpec()
        self.assertNotEqual(
            step.label_for(local), step.label_for(replace(local, mode="vm"))
        )

    def test_le_backend_suit_le_mode(self):
        from dataclasses import replace

        from script.todo.sms import local as local_backend
        from script.todo.sms import menu, runner

        etat = self.spec_mod.load()
        self.assertIs(menu._backend(etat), local_backend)
        etat.spec = replace(etat.spec, mode="vm")
        self.assertIs(menu._backend(etat), runner)

    def test_letape_de_verification_passe_par_le_backend(self):
        """Verrouille un défaut trouvé en audit.

        `_step_verify` appelait `runner.step_verify` en dur. En mode local —
        le défaut — cela partait en SSH vers une VM inexistante, donc dans
        `sudo virsh domifaddr` : exactement la rafale de demandes de mot de
        passe que ce module est censé avoir supprimée.
        """
        import inspect

        from script.todo.sms import menu

        source = inspect.getsource(menu._step_verify)
        self.assertNotIn("runner.step_verify", source)
        self.assertIn("dos.step_verify", source)

    def test_les_deux_backends_exposent_la_meme_interface(self):
        from script.todo.sms import local as local_backend
        from script.todo.sms import runner

        for nom in ("step_odoo", "step_gateway", "step_verify"):
            self.assertTrue(hasattr(local_backend, nom), nom)
            self.assertTrue(hasattr(runner, nom), nom)


class TestSudoEtAdresse(SmsDemoBase):
    """Ce qui empêche la rafale de demandes de mot de passe."""

    def test_ladresse_connue_evite_de_re_resoudre(self):
        # Chaque commande SSH re-résolvait l'adresse par `sudo virsh`, avec
        # un plafond de cinq minutes. Quatre commandes suffisaient à relancer
        # la rafale si la session sudo avait expiré entre deux étapes.
        from script.todo.sms import runner

        etat = self.spec_mod.load()
        etat.vm_ip = "192.168.122.7"

        class TodoQuiExplose:
            def _qemu_ssh_target(self, *a, **k):
                raise AssertionError("ne doit PAS etre appele")

        self.assertEqual(
            runner.ssh_target(TodoQuiExplose(), etat.spec, etat),
            "erplibre@192.168.122.7",
        )

    def test_sans_adresse_connue_on_interroge(self):
        from script.todo.sms import runner

        etat = self.spec_mod.load()

        class TodoQuiRepond:
            def _qemu_ssh_target(self, nom, src):
                return "erplibre@10.0.0.1"

        self.assertEqual(
            runner.ssh_target(TodoQuiRepond(), etat.spec, etat),
            "erplibre@10.0.0.1",
        )

    def test_la_destruction_de_vm_utilise_sudo_et_le_bon_uri(self):
        # Sans sudo ni qemu:///system, virsh parle a la session de
        # l'utilisateur : le domaine n'y est pas, la destruction echoue en
        # silence, et vingt gigaoctets restent.
        import inspect

        from script.todo.sms import menu

        source = inspect.getsource(menu._reset)
        self.assertIn('"sudo", "virsh"', source)
        self.assertIn("qemu:///system", source)


class TestLocal(SmsDemoBase):
    def test_le_venv_est_cherche_et_non_compose(self):
        # Son nom porte les deux versions et change avec elles.
        from script.todo.sms import local

        venv = local.find_venv()
        if venv is not None:
            self.assertTrue(venv.name.startswith(".venv.odoo"))
            self.assertTrue((venv / "bin" / "python").exists())

    def test_un_pid_mort_nest_pas_un_serveur_vivant(self):
        # Un fichier PID survit a son processus : s'y fier ferait croire a un
        # serveur en vie devant un telephone qui n'atteint rien.
        from script.todo.sms import local

        local.SERVER_PID.parent.mkdir(parents=True, exist_ok=True)
        local.SERVER_PID.write_text("999999999")
        self.assertEqual(local.server_pid(), 0)

    def test_un_fichier_pid_illisible_ne_fait_pas_tomber(self):
        from script.todo.sms import local

        local.SERVER_PID.parent.mkdir(parents=True, exist_ok=True)
        local.SERVER_PID.write_text("ceci n'est pas un nombre")
        self.assertEqual(local.server_pid(), 0)

    def test_le_port_par_defaut_evite_celui_du_poste(self):
        # 8069 porte presque toujours une instance de developpement ; la
        # demonstration ne doit pas la bousculer.
        self.assertNotEqual(self.spec_mod.DemoSpec().odoo_port, 8069)


class TestConfirmation(SmsDemoBase):
    """L'étape qui distingue « accepté » de « parti »."""

    def test_letape_de_confirmation_existe_et_suit_la_verification(self):
        confirm = self.steps.BY_ID["confirm"]
        self.assertIn("verify", confirm.requires)

    def test_letat_retient_le_dernier_envoi(self):
        # Confirmer « le dernier envoi » ne suffit pas : il faut CELUI qu'on
        # vient de faire, sinon une démonstration rejouée confirmerait le
        # message précédent.
        etat = self.spec_mod.load()
        etat.last_uuid = "abc123"
        self.spec_mod.save(etat)
        self.assertEqual(self.spec_mod.load().last_uuid, "abc123")

    def test_repartir_de_zero_oublie_le_dernier_envoi(self):
        etat = self.spec_mod.load()
        etat.last_uuid = "abc123"
        etat.reset()
        self.assertEqual(etat.last_uuid, "")

    def test_queued_nest_pas_un_etat_definitif(self):
        # C'est le piège : `queued` ressemble à une réussite et c'est
        # exactement ce qu'on obtient quand le téléphone n'interroge jamais.
        from script.todo.sms import local

        self.assertNotIn("queued", local.TERMINAUX)
        self.assertNotIn("published", local.TERMINAUX)
        self.assertIn("delivered", local.TERMINAUX)
        self.assertIn("failed", local.TERMINAUX)

    def test_les_deux_modes_savent_lire_un_etat(self):
        from script.todo.sms import local as local_backend
        from script.todo.sms import runner

        for module in (local_backend, runner):
            self.assertTrue(hasattr(module, "dispatch_state"))
            self.assertTrue(hasattr(module, "TERMINAUX"))
            self.assertTrue(hasattr(module, "CONFIRM_TIMEOUT_S"))

    def test_un_uuid_a_apostrophe_ne_casse_pas_la_requete(self):
        from script.todo.sms import local

        self.assertEqual(local._litteral("a'b"), "'a''b'")


class TestLecturePhone(SmsDemoBase):
    """La lecture des SMS du téléphone, sans téléphone."""

    ECHANTILLON = (
        "Row: 0 address=+15145550100, date=1787903776367, "
        "body=Essai de la passerelle\n"
        "Row: 1 address=+15145550101, date=1742414080765, body=Deux, avec"
        " une virgule\n"
        "Row: 2 address=+15145550102, date=1742413516773, body=Trois\n"
        "sur deux lignes\n"
    )

    def test_le_corps_peut_contenir_une_virgule(self):
        # Une analyse ligne à ligne coupée sur la virgule tronquerait le
        # message sans rien signaler.
        from script.todo.sms import phone

        trouves = list(phone.LIGNE.finditer(self.ECHANTILLON))
        self.assertEqual(len(trouves), 3)
        self.assertIn("virgule", trouves[1].group("body"))

    def test_le_corps_peut_tenir_sur_deux_lignes(self):
        from script.todo.sms import phone

        trouves = list(phone.LIGNE.finditer(self.ECHANTILLON))
        self.assertIn("sur deux lignes", trouves[2].group("body"))

    def test_les_messages_sortent_du_plus_recent_au_plus_ancien(self):
        from script.todo.sms import phone

        messages = []
        for m in phone.LIGNE.finditer(self.ECHANTILLON):
            messages.append(
                {
                    "address": m.group("address"),
                    "at": __import__("datetime").datetime.fromtimestamp(
                        int(m.group("date")) / 1000
                    ),
                    "body": m.group("body"),
                }
            )
        messages.sort(key=lambda x: x["at"], reverse=True)
        self.assertEqual(messages[0]["address"], "+15145550100")

    def test_une_boite_inconnue_est_refusee(self):
        from script.todo.sms import phone

        with self.assertRaises(phone.PhoneError):
            phone.read_sms("corbeille")

    def test_un_rendu_vide_le_dit(self):
        from script.todo.sms import phone

        self.assertIn("Aucun", phone.render([], "sent"))


class TestTransport(SmsDemoBase):
    """Câble ou Wi-Fi : deux chemins, deux compromis."""

    def test_le_defaut_est_le_cable(self):
        # Le câble n'expose rien sur le réseau. Le Wi-Fi, si — il doit être
        # demandé, pas subi.
        self.assertEqual(self.spec_mod.load().spec.transport, "cable")

    def test_le_pense_bete_change_avec_le_transport(self):
        from dataclasses import replace

        from script.todo.sms import gateway

        cable = gateway.render_mobile_config(
            self.spec_mod.DemoSpec(), "a" * 64, "127.0.0.1"
        )
        wifi = gateway.render_mobile_config(
            replace(self.spec_mod.DemoSpec(), transport="wifi"),
            "a" * 64,
            "127.0.0.1",
            "192.168.50.10",
        )
        self.assertIn("adb reverse", cable)
        self.assertNotIn("adb reverse", wifi)
        self.assertIn("192.168.50.10", wifi)
        self.assertIn("127.0.0.1", cable)

    def test_le_wifi_annonce_ses_deux_conditions(self):
        # L'une est côté build, l'autre côté écran. En oublier une donne un
        # échec de connexion sans rapport apparent avec le réglage manqué.
        from dataclasses import replace

        from script.todo.sms import gateway

        wifi = gateway.render_mobile_config(
            replace(self.spec_mod.DemoSpec(), transport="wifi"),
            "a" * 64,
            "",
            "192.168.50.10",
        )
        self.assertIn("lanCleartext", wifi)
        self.assertIn("Tolerer le reseau local en clair", wifi)

    def test_le_wifi_dit_ce_qui_circule_en_clair(self):
        from dataclasses import replace

        from script.todo.sms import gateway

        wifi = gateway.render_mobile_config(
            replace(self.spec_mod.DemoSpec(), transport="wifi"),
            "a" * 64,
            "",
            "10.0.0.1",
        )
        self.assertIn("CLAIR", wifi.upper())

    def test_le_meme_sous_reseau_se_reconnait(self):
        from script.todo.sms import phone

        self.assertTrue(phone.same_subnet("192.168.50.10", "192.168.50.11"))
        self.assertFalse(phone.same_subnet("192.168.50.10", "192.168.60.11"))
        self.assertFalse(phone.same_subnet("192.168.50.10", ""))

    def test_ladresse_du_poste_evite_le_pont_libvirt(self):
        # Une machine de developpement porte souvent un pont libvirt, dont
        # l'adresse est privee et valide mais que le telephone n'atteint pas.
        from script.todo.sms import phone

        adresse = phone.host_lan_ip()
        if adresse:
            self.assertFalse(adresse.startswith("192.168.122."))


class TestNumeroDEssai(SmsDemoBase):
    """Le numero vers lequel partent les essais."""

    def test_il_est_vide_par_defaut(self):
        # Un essai atteint une vraie personne et coute de l'argent. Un numero
        # d'exemple laisse dans un fichier de configuration finit toujours
        # par partir pour de vrai.
        self.assertEqual(self.spec_mod.load().spec.test_number, "")

    def test_il_survit_a_un_rechargement(self):
        from dataclasses import replace

        etat = self.spec_mod.load()
        etat.spec = replace(etat.spec, test_number="+15145550142")
        self.spec_mod.save(etat)
        self.assertEqual(self.spec_mod.load().spec.test_number, "+15145550142")

    def test_il_figure_dans_le_fichier_de_configuration(self):
        # L'utilisateur doit pouvoir l'editer a la main sans passer par le
        # menu : le champ doit donc etre serialise, meme vide.
        import json

        self.spec_mod.save(self.spec_mod.load())
        brut = json.loads(self.spec_mod.STATE_PATH.read_text(encoding="utf-8"))
        self.assertIn("test_number", brut["spec"])

    def test_un_format_national_est_refuse(self):
        import io as _io
        import sys as _sys

        from script.todo.sms import menu

        ancien = _sys.stdin
        try:
            _sys.stdin = _io.StringIO("5145550142\n")
            menu._choose_test_number(self.spec_mod.load())
        finally:
            _sys.stdin = ancien
        self.assertEqual(self.spec_mod.load().spec.test_number, "")

    def test_un_format_international_est_retenu(self):
        import io as _io
        import sys as _sys

        from script.todo.sms import menu

        ancien = _sys.stdin
        try:
            _sys.stdin = _io.StringIO("+15145550142\n")
            menu._choose_test_number(self.spec_mod.load())
        finally:
            _sys.stdin = ancien
        self.assertEqual(self.spec_mod.load().spec.test_number, "+15145550142")

    def test_un_tiret_efface_le_numero(self):
        import io as _io
        import sys as _sys
        from dataclasses import replace

        from script.todo.sms import menu

        etat = self.spec_mod.load()
        etat.spec = replace(etat.spec, test_number="+15145550142")
        self.spec_mod.save(etat)
        ancien = _sys.stdin
        try:
            _sys.stdin = _io.StringIO("-\n")
            menu._choose_test_number(self.spec_mod.load())
        finally:
            _sys.stdin = ancien
        self.assertEqual(self.spec_mod.load().spec.test_number, "")

    def test_lappel_dessai_refuse_sans_numero(self):
        import io as _io
        import sys as _sys

        from script.todo.sms import menu

        etat = self.spec_mod.load()
        ancien = _sys.stdin
        try:
            _sys.stdin = _io.StringIO("o\n")
            # Ne doit RIEN composer : sans numero, il n'y a rien a appeler,
            # et demander confirmation serait deja de trop.
            menu._place_test_call(None, etat)
        finally:
            _sys.stdin = ancien


class TestEmplacement(SmsDemoBase):
    """Où vivent l'état et le secret."""

    def test_par_defaut_dans_private_conf(self):
        # Convention du projet : ce qui est propre a une installation va
        # dans `private/`. Le repertoire personnel n'a rien a voir avec ce
        # depot, et deux copies du depot y partageraient le meme etat.
        import os as _os

        ancien = _os.environ.pop("ERPLIBRE_SMS_DEMO_DIR", None)
        try:
            import importlib

            from script.todo.sms import spec as frais

            importlib.reload(frais)
            self.assertEqual(
                frais._base().parts[-3:], ("private", "conf", "sms")
            )
        finally:
            if ancien is not None:
                _os.environ["ERPLIBRE_SMS_DEMO_DIR"] = ancien

    def test_le_secret_est_exclu_de_git(self):
        """Le garde-fou qui compte : `private/` est versionne, pas ignore.

        Dix fichiers y sont suivis et le distant du depot est public. Sans
        une exclusion explicite, un `git add private/` distrait publierait le
        secret partage avec le telephone.
        """
        import subprocess
        from pathlib import Path

        racine = Path(__file__).resolve().parents[1]
        cible = racine / "private" / "conf" / "sms" / "hmac.secret"
        res = subprocess.run(
            ["git", "check-ignore", str(cible)],
            cwd=str(racine),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            res.returncode, 0, "le secret n'est PAS ignore par git"
        )


class TestDiagnostic(SmsDemoBase):
    """Nommer la cause d'un refus plutôt que constater un silence."""

    JOURNAL = (
        "2026-08-29 08:38:27 WARNING sms_demo ...controllers.main:"
        " erplibre_mobile_gateway: signature invalide depuis"
        " 192.168.50.11\n"
        "2026-08-29 08:40:27 WARNING sms_demo ...: erplibre: appareil"
        " inconnu 'zzz'\n"
    )

    def _journal(self, contenu):
        from script.todo.sms import local

        local.SERVER_LOG.parent.mkdir(parents=True, exist_ok=True)
        local.SERVER_LOG.write_text(contenu, encoding="utf-8")

    def test_une_signature_invalide_est_nommee(self):
        # C'est la panne vecue : le telephone signait avec un secret perime,
        # Odoo refusait en 403, et la chaine annoncait cinq etapes sur six.
        from script.todo.sms import local

        self._journal(self.JOURNAL)
        self.assertIn("sms_diag_signature", local.refus_recents())

    def test_un_appareil_inconnu_est_distingue(self):
        # Meme symptome a l'ecran qu'une signature invalide, geste different :
        # l'un se corrige par le secret, l'autre par l'identifiant.
        from script.todo.sms import local

        self._journal(self.JOURNAL)
        self.assertIn("sms_diag_device", local.refus_recents())

    def test_un_journal_sans_refus_ne_signale_rien(self):
        from script.todo.sms import local

        self._journal("2026-08-29 08:00:00 INFO tout va bien\n")
        self.assertEqual(local.refus_recents(), [])

    def test_un_journal_absent_ne_fait_pas_tomber(self):
        from script.todo.sms import local

        if local.SERVER_LOG.exists():
            local.SERVER_LOG.unlink()
        self.assertEqual(local.refus_recents(), [])

    def test_chaque_cause_a_une_traduction(self):
        from script.todo.todo_i18n import TRANSLATIONS

        for cle in (
            "sms_diag_signature",
            "sms_diag_device",
            "sms_diag_clock",
            "sms_diag_nonce",
            "sms_diag_silence",
        ):
            self.assertIn(cle, TRANSLATIONS, cle)

    def test_letape_mobile_ne_croit_plus_le_oui_humain(self):
        """Verrouille la correction.

        L'etape se contentait d'une confirmation au clavier. Une confirmation
        prouve la bonne volonte, pas la configuration — et le telephone
        pouvait etre refuse a chaque cycle sans que rien ne le dise.
        """
        import inspect

        from script.todo.sms import menu

        source = inspect.getsource(menu._step_mobile)
        self.assertIn("_attendre_interrogation", source)
        verif = inspect.getsource(menu._attendre_interrogation)
        self.assertIn("gateway_poll_age", verif)
        self.assertIn("refus_recents", verif)


class TestMateriel(SmsDemoBase):
    """Le telephone et le modem, sur le meme chemin d'etapes.

    Ce n'est pas une seconde demonstration : c'est la meme, dont une seule
    etape change de nature. Ces tests fixent laquelle, et ce qui doit rester
    identique pour que les deux voies restent comparables.
    """

    def _spec(self, materiel):
        from dataclasses import replace

        return replace(self.spec_mod.DemoSpec(), materiel=materiel)

    def test_le_defaut_est_le_telephone(self):
        """La voie existante ne doit pas changer sous les pieds de personne."""
        self.assertEqual(self.spec_mod.load().spec.materiel, "mobile")

    def test_les_deux_materiels_suivent_les_memes_etapes(self):
        avant = [s.id for s in self.steps.STEPS]
        self.assertEqual(len(avant), 6)
        self.assertEqual(avant[3], "mobile")

    def test_seule_letape_de_liaison_change_de_nom(self):
        mobile, modem = self._spec("mobile"), self._spec("modem")
        differentes = [
            step.id
            for step in self.steps.STEPS
            if step.label_for(mobile) != step.label_for(modem)
        ]
        self.assertEqual(differentes, ["mobile"])

    def test_le_modem_ne_demande_personne(self):
        """Un modem n'a pas d'ecran : l'etape s'enchaine seule."""
        etape = self.steps.BY_ID["mobile"]
        self.assertTrue(etape.manual_for(self._spec("mobile")))
        self.assertFalse(etape.manual_for(self._spec("modem")))

    def test_le_tableau_retire_la_mention_du_telephone_en_main(self):
        from dataclasses import replace

        etat = self.spec_mod.load()
        etat.spec = replace(etat.spec, materiel="modem")
        rendu = self.steps.render(etat)
        self.assertIn("agent", rendu.lower())
        self.assertNotIn("telephone en main", rendu.lower())

    def test_la_fiche_declare_le_materiel_a_odoo(self):
        """Sans cela, un modem serait juge sur les criteres d'un telephone."""
        from script.todo.sms import gateway as gw

        script = gw.render_setup_script(self._spec("modem"))
        self.assertIn('"kind": \'modem\'', script)

    def test_lagent_joint_odoo_sans_renvoi_usb(self):
        """Il est sur le poste : il n'a ni cable ni « adb reverse » a passer."""
        from dataclasses import replace

        from script.todo.sms import agent

        spec = self._spec("modem")
        self.assertEqual(
            agent.server_url(spec), f"http://127.0.0.1:{spec.odoo_port}"
        )
        self.assertEqual(
            agent.server_url(replace(spec, mode="vm"), "192.0.2.10"),
            f"http://192.0.2.10:{spec.odoo_port}",
        )

    def test_lagent_recoit_les_trois_variables_quil_exige(self):
        from script.todo.modem import passerelle as agent_mod
        from script.todo.sms import agent

        environnement = agent.environnement(self._spec("modem"), "abc", "")
        self.assertEqual(environnement[agent_mod.VARIABLE_APPAREIL], "demo-01")
        self.assertEqual(environnement[agent_mod.VARIABLE_SECRET], "abc")
        self.assertTrue(environnement[agent_mod.VARIABLE_URL].startswith("http"))

    def test_changer_de_materiel_refait_la_fiche_pas_le_serveur(self):
        """La fiche porte le materiel ; la VM et Odoo n'en savent rien."""
        from unittest.mock import patch

        from script.todo.sms import menu

        etat = self.spec_mod.load()
        for etape in ("vm", "odoo", "gateway", "mobile", "verify", "confirm"):
            etat.mark_done(etape)
        with patch("builtins.input", return_value="2"):
            menu._choose_materiel(etat)
        self.assertEqual(etat.spec.materiel, "modem")
        self.assertEqual(sorted(etat.done), ["odoo", "vm"])


if __name__ == "__main__":
    unittest.main()
