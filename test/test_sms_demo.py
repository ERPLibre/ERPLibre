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
        self.spec_mod.chemin_etat("mobile").write_text(
            "{ ceci n'est pas du json"
        )
        self.assertEqual(self.spec_mod.load().done, [])

    def test_une_cle_inconnue_dans_letat_est_ignoree(self):
        # Un état écrit par une version plus récente ne doit pas faire
        # exploser une version plus ancienne.
        self.spec_mod.chemin_etat("mobile").parent.mkdir(
            parents=True, exist_ok=True
        )
        self.spec_mod.chemin_etat("mobile").write_text(
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
        mode = os.stat(self.spec_mod.chemin_secret("mobile")).st_mode & 0o777
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

    def test_le_script_ecrit_le_champ_du_module(self):
        """Le champ appartient au module, et son nom se lit dans une seule
        source.

        `res.company.sms_provider` appartient aux connecteurs du coeur : il
        n'existe pas sans eux, et y ecrire une valeur inconnue de sa selection
        fait lever toute lecture de la societe. Un renommage cote module
        laisserait sinon ce script ecrire dans le vide, et la passerelle
        resterait inerte sans que rien ne le dise.

        Le script LIT ce champ et peut le ramener au defaut d'Odoo, mais n'y
        ecrit jamais la valeur du module.
        """
        from script.todo.sms.gateway import CHAMP_PROVIDER, PROVIDER

        script = self.gw.render_setup_script(self.spec)
        self.assertIn(f"company.{CHAMP_PROVIDER} = {PROVIDER!r}", script)
        self.assertNotIn(f"company.sms_provider = {PROVIDER!r}", script)
        self.assertNotIn(f'"sms_provider": {PROVIDER!r}', script)

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


class TestAppairageUsb(SmsDemoBase):
    """Poser la configuration dans l'application par le cable.

    Le coeur est une fonction PURE sur du XML : il se teste sans telephone,
    ce qui est la seule facon d'eprouver le cas qui casse — un fichier deja
    rempli, dont il ne faut rien perdre.
    """

    EXISTANT = (
        "<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n"
        "<map>\n"
        '    <string name="device_id">ancien-01</string>\n'
        '    <int name="poll_seconds" value="30" />\n'
        '    <boolean name="enabled" value="false" />\n'
        '    <string name="odoo_base_url">http://10.0.0.1:8169</string>\n'
        "</map>"
    )

    class AdbNonBouchonne(BaseException):
        """Un appel a `adb` qu'aucun test n'a bouchonne.

        BaseException et non Exception : le menu rapporte toute Exception
        levee par une etape comme un echec de l'etape, et un test qui attend
        cet echec passerait sur la garde elle-meme.
        """

    def setUp(self):
        """Ferme `_adb`, seule porte du module vers `adb`, pour toute la
        classe : un test l'ouvre en la bouchonnant lui-meme.

        Ouverte, un appel non bouchonne atteint l'`adb` du poste, et par lui
        le telephone qui y est branche : `pm grant` et `am broadcast` y
        agissent pour de vrai. Fermee, elle echoue de la meme facon sur tous
        les postes et nomme la commande.
        """
        super().setUp()
        from unittest.mock import patch

        def porte_fermee(args, *_a, **_kw):
            raise self.AdbNonBouchonne("adb " + " ".join(map(str, args)))

        garde = patch.object(self._module(), "_adb", porte_fermee)
        garde.start()
        self.addCleanup(garde.stop)

    def _module(self):
        from script.todo.sms import appairage

        return appairage

    def test_une_cle_presente_est_remplacee_une_fois(self):
        xml = self._module().poser_valeurs(
            self.EXISTANT, {"device_id": "demo-01"}, {}
        )
        self.assertIn('<string name="device_id">demo-01</string>', xml)
        self.assertNotIn("ancien-01", xml)
        self.assertEqual(xml.count('name="device_id"'), 1)

    def test_une_cle_absente_sajoute_avant_la_fin(self):
        xml = self._module().poser_valeurs(
            self.EXISTANT, {"hmac_secret": "a" * 64}, {}
        )
        self.assertIn('<string name="hmac_secret">' + "a" * 64, xml)
        self.assertTrue(xml.rstrip().endswith("</map>"))

    def test_ce_que_le_serveur_a_pose_nest_pas_perdu(self):
        """Le fichier porte aussi le rythme d'interrogation et les quotas :
        les ecraser les remettrait a des valeurs d'usine."""
        xml = self._module().poser_valeurs(
            self.EXISTANT, {"device_id": "demo-01"}, {"enabled": True}
        )
        self.assertIn('<int name="poll_seconds" value="30" />', xml)
        self.assertIn('<boolean name="enabled" value="true" />', xml)
        self.assertEqual(xml.count('name="enabled"'), 1)

    def test_une_valeur_qui_porte_une_esperluette_reste_lisible(self):
        """Un « & » nu rend le fichier illisible, et l'application repart
        alors de zero sans rien dire."""
        from xml.etree import ElementTree

        xml = self._module().poser_valeurs(
            self.EXISTANT, {"odoo_base_url": "http://h/a?x=1&y=2"}, {}
        )
        racine = ElementTree.fromstring(xml)
        valeurs = {
            n.get("name"): n.text for n in racine.findall("string")
        }
        self.assertEqual(valeurs["odoo_base_url"], "http://h/a?x=1&y=2")

    def test_le_tube_et_la_redirection_restent_dans_le_shell_interne(self):
        """`adb shell` recolle ses arguments sans les citer : laisses nus, le
        « > » revient au shell d'adbd, dont le repertoire courant n'est pas
        celui de l'application."""
        from unittest.mock import patch

        app = self._module()
        with patch.object(app, "_adb", return_value=(0, "")) as adb:
            app.ecrire_prefs("<map />")
        args = adb.call_args[0][0]
        self.assertEqual(args[0], "shell")
        # Une seule commande, et non « sh », « -c », puis le reste en vrac.
        self.assertEqual(len(args), 2)
        commande = args[1]
        self.assertIn("run-as " + app.PAQUET, commande)
        tube = commande.index("|")
        debut = commande.index("'")
        fin = commande.rindex("'")
        self.assertTrue(debut < tube < fin, commande)
        self.assertTrue(debut < commande.index(">") < fin, commande)

    def test_une_ecriture_refusee_est_rapportee(self):
        from unittest.mock import patch

        app = self._module()
        with patch.object(app, "_adb", return_value=(1, "Permission denied")):
            with self.assertRaises(app.AppairageError) as leve:
                app.ecrire_prefs("<map />")
        self.assertIn("Permission denied", str(leve.exception))

    def test_la_boucle_locale_nest_pas_du_reseau_en_clair(self):
        sort = self._module().url_sort_du_poste
        self.assertFalse(sort("http://127.0.0.1:8169"))
        self.assertFalse(sort("http://localhost:8169"))
        self.assertTrue(sort("http://192.168.50.10:8169"))

    def _spec(self):
        return self.spec_mod.spec_par_defaut("mobile")

    def test_sans_appareil_rien_nest_ecrit(self):
        from unittest.mock import patch

        app = self._module()
        with patch.object(app, "appareils", return_value=[]), \
                patch.object(app, "ecrire_prefs") as ecrit:
            ok, _detail = app.appairer(self._spec(), "a" * 64, "http://h:1")
        self.assertFalse(ok)
        self.assertFalse(ecrit.called)

    def test_un_paquet_ferme_est_refuse_avec_le_motif_dadb(self):
        """« unknown package » et « not debuggable » demandent deux gestes."""
        from unittest.mock import patch

        app = self._module()
        with patch.object(app, "appareils", return_value=["x"]), \
                patch.object(
                    app, "run_as_ouvre", return_value=(False, "not debuggable")
                ), \
                patch.object(app, "ecrire_prefs") as ecrit:
            ok, detail = app.appairer(self._spec(), "a" * 64, "http://h:1")
        self.assertFalse(ok)
        self.assertIn("not debuggable", detail)
        self.assertFalse(ecrit.called)

    def test_lapplication_est_arretee_avant_lecriture(self):
        """`SharedPreferences` garde sa copie en memoire et reecrirait le
        fichier par-dessus."""
        from unittest.mock import patch

        app = self._module()
        ordre = []
        with patch.object(app, "appareils", return_value=["x"]), \
                patch.object(app, "run_as_ouvre", return_value=(True, "")), \
                patch.object(app, "lire_prefs", return_value=self.EXISTANT), \
                patch.object(
                    app, "arreter_application",
                    side_effect=lambda: ordre.append("arret")
                ), \
                patch.object(
                    app, "ecrire_prefs",
                    side_effect=lambda _x: ordre.append("ecriture")
                ), \
                patch.object(app, "accorder_permissions", return_value=[]), \
                patch.object(app, "reveiller_passerelle"):
            ok, _detail = app.appairer(
                self._spec(), "a" * 64, "http://127.0.0.1:8169"
            )
        self.assertTrue(ok)
        self.assertEqual(ordre, ["arret", "ecriture"])

    def test_une_url_de_reseau_en_clair_pose_sa_tolerance(self):
        """Poser l'URL sans le drapeau donnerait un refus au premier envoi,
        loin d'ici."""
        from unittest.mock import patch

        app = self._module()
        ecrits = []
        for url, attendu in (
            ("http://192.168.50.10:8169", "true"),
            ("http://127.0.0.1:8169", "false"),
        ):
            with patch.object(app, "appareils", return_value=["x"]), \
                    patch.object(app, "run_as_ouvre", return_value=(True, "")), \
                    patch.object(
                        app, "lire_prefs", return_value=self.EXISTANT
                    ), \
                    patch.object(app, "arreter_application"), \
                    patch.object(
                        app, "ecrire_prefs",
                        side_effect=lambda x: ecrits.append(x)
                    ), \
                    patch.object(
                        app, "accorder_permissions", return_value=[]
                    ), \
                    patch.object(app, "reveiller_passerelle"):
                app.appairer(self._spec(), "a" * 64, url)
            self.assertIn(
                '<boolean name="allow_plain_lan" value="%s" />' % attendu,
                ecrits[-1],
                url,
            )

    def test_la_configuration_precedente_est_copiee_avant_decriture(self):
        from unittest.mock import patch

        app = self._module()
        copie = Path(self._tmp) / "avant.xml"
        with patch.object(app, "appareils", return_value=["x"]), \
                patch.object(app, "run_as_ouvre", return_value=(True, "")), \
                patch.object(app, "lire_prefs", return_value=self.EXISTANT), \
                patch.object(app, "arreter_application"), \
                patch.object(app, "ecrire_prefs"), \
                patch.object(app, "accorder_permissions", return_value=[]), \
                patch.object(app, "reveiller_passerelle"):
            app.appairer(
                self._spec(), "a" * 64, "http://h:1", copie_vers=copie
            )
        self.assertIn("ancien-01", copie.read_text(encoding="utf-8"))
        self.assertEqual(os.stat(copie).st_mode & 0o777, 0o600)

    def test_un_refus_dhier_ne_survit_pas_a_lappairage(self):
        """Le laisser ferait lire « HTTP 403 » sur une passerelle saine."""
        from unittest.mock import patch

        app = self._module()
        avant = self.EXISTANT.replace(
            "</map>",
            '    <string name="last_error">HTTP 403</string>\n</map>',
        )
        ecrits = []
        with patch.object(app, "appareils", return_value=["x"]), \
                patch.object(app, "run_as_ouvre", return_value=(True, "")), \
                patch.object(app, "lire_prefs", return_value=avant), \
                patch.object(app, "arreter_application"), \
                patch.object(
                    app, "ecrire_prefs", side_effect=lambda x: ecrits.append(x)
                ), \
                patch.object(app, "accorder_permissions", return_value=[]), \
                patch.object(app, "reveiller_passerelle"):
            app.appairer(self._spec(), "a" * 64, "http://h:1")
        self.assertNotIn("HTTP 403", ecrits[-1])

    def test_en_cable_la_config_posee_vise_la_boucle_locale(self):
        """La politique reseau d'un APK ordinaire refuse le HTTP en clair
        partout ailleurs, et le refus vient d'Android : aucun reglage dans
        l'application ne le leve."""
        from dataclasses import replace

        from script.todo.sms import menu

        spec = replace(
            self.spec_mod.spec_par_defaut("mobile"), transport="cable"
        )
        url = menu.url_pour_le_telephone(spec)
        self.assertEqual(url, f"http://127.0.0.1:{spec.odoo_port}")

    def test_en_wifi_la_config_posee_vise_linterface(self):
        from dataclasses import replace
        from unittest.mock import patch

        from script.todo.sms import menu, phone

        spec = replace(
            self.spec_mod.spec_par_defaut("mobile"), transport="wifi"
        )
        with patch.object(phone, "host_lan_ip", return_value="192.168.50.10"):
            url = menu.url_pour_le_telephone(spec)
        self.assertEqual(url, f"http://192.168.50.10:{spec.odoo_port}")

    def test_le_renvoi_usb_est_pose_avant_decrire_la_boucle(self):
        """Sans le renvoi, le 127.0.0.1 du telephone designe le telephone."""
        from unittest.mock import patch

        from script.todo.sms import appairage, menu

        etat = self.spec_mod.load("mobile")
        with patch.object(
                menu.runner, "adb_reverse", return_value=(True, "")
        ) as renvoi, \
                patch.object(
                    appairage, "appairer", return_value=(True, "ok")
                ) as pose:
            ok, _detail = menu.poser_la_config_par_usb(etat)
        self.assertTrue(ok)
        self.assertTrue(renvoi.called)
        self.assertIn("127.0.0.1", pose.call_args[0][2])

    def test_un_renvoi_refuse_arrete_avant_decrire(self):
        """Ecrire une adresse que rien ne dessert ferait chercher la panne
        dans Odoo."""
        from unittest.mock import patch

        from script.todo.sms import appairage, menu

        etat = self.spec_mod.load("mobile")
        with patch.object(
                menu.runner, "adb_reverse", return_value=(False, "adb absent")
        ), patch.object(appairage, "appairer") as pose:
            ok, detail = menu.poser_la_config_par_usb(etat)
        self.assertFalse(ok)
        self.assertIn("adb absent", detail)
        self.assertFalse(pose.called)

    def test_la_chaine_pose_la_config_par_le_cable_sans_rien_demander(self):
        """« Tout enchainer » ne doit pas s'arreter sur une saisie que le
        cable sait faire."""
        from unittest.mock import patch

        from script.todo.sms import appairage, menu

        etat = self.spec_mod.load("mobile")
        with patch.object(
                appairage, "possible", return_value=(True, "")
        ), \
                patch.object(
                    menu, "poser_la_config_par_usb",
                    return_value=(True, "demo-01")
                ) as pose, \
                patch.object(
                    menu, "_attendre_interrogation",
                    return_value=(True, "interroge")
                ), \
                patch.object(
                    menu.local_backend, "start_server", return_value=(True, "")
                ), \
                patch("builtins.input", side_effect=AssertionError("saisie")), \
                patch("builtins.print"):
            ok, detail = menu._step_mobile(etat)
        self.assertTrue(ok, detail)
        self.assertTrue(pose.called)

    def test_sans_cable_la_chaine_revient_au_pense_bete(self):
        """Un paquet de production ou aucun appareil : la saisie reste le
        seul chemin, et le motif est dit."""
        from unittest.mock import patch

        from script.todo.sms import appairage, menu

        etat = self.spec_mod.load("mobile")
        dits = []
        with patch.object(
                appairage, "possible", return_value=(False, "not debuggable")
        ), \
                patch.object(
                    menu, "poser_la_config_par_usb"
                ) as pose, \
                patch.object(
                    menu.local_backend, "start_server", return_value=(True, "")
                ), \
                patch.object(menu.runner, "adb_reverse",
                             return_value=(True, "")), \
                patch("builtins.input", return_value="n"), \
                patch(
                    "builtins.print",
                    lambda *a, **k: dits.append(" ".join(map(str, a)))
                ):
            ok, _detail = menu._step_mobile(etat)
        self.assertFalse(ok)
        self.assertFalse(pose.called)
        ecran = "\n".join(dits)
        self.assertIn("not debuggable", ecran)
        self.assertIn("A SAISIR DANS L'APPLICATION", ecran)

    def test_lappairage_ne_force_aucun_ecran_au_premier_plan(self):
        """Forcer l'activite depuis le cable la laisse par moments derriere la
        fenetre de lancement du systeme : l'application parait ne plus
        demarrer. La passerelle, elle, interroge sans interface."""
        from unittest.mock import patch

        app = self._module()
        self.assertFalse(hasattr(app, "relancer_application"))
        with patch.object(app, "appareils", return_value=["x"]), \
                patch.object(app, "run_as_ouvre", return_value=(True, "")), \
                patch.object(app, "lire_prefs", return_value=self.EXISTANT), \
                patch.object(app, "arreter_application"), \
                patch.object(app, "ecrire_prefs"), \
                patch.object(app, "reveiller_passerelle") as reveil, \
                patch.object(app, "accorder_permissions", return_value=[]), \
                patch.object(app, "_adb") as adb:
            ok, _detail = app.appairer(self._spec(), "a" * 64, "http://h:1")
        self.assertTrue(ok)
        self.assertTrue(reveil.called)
        lances = [a for a, _k in [(c[0][0], c[1]) for c in adb.call_args_list]]
        self.assertFalse(
            any("am" in args and "start" in args for args in lances), lances
        )

    def test_lappareil_dit_lui_meme_son_dernier_defaut(self):
        from unittest.mock import patch

        app = self._module()
        prefs = self.EXISTANT.replace(
            "</map>",
            '    <string name="last_error">Cleartext HTTP &amp; co</string>\n'
            "</map>",
        )
        with patch.object(app, "possible", return_value=(True, "")), \
                patch.object(app, "lire_prefs", return_value=prefs):
            self.assertEqual(app.dernier_defaut(), "Cleartext HTTP & co")

    def test_sans_cable_lappareil_ne_dit_rien(self):
        from unittest.mock import patch

        app = self._module()
        with patch.object(app, "possible", return_value=(False, "absent")):
            self.assertEqual(app.dernier_defaut(), "")

    def test_la_chaine_avertit_du_rcs_avant_la_premiere_etape(self):
        """Elle s'arrete au premier echec : ce qui ne s'affiche qu'en cas de
        reussite n'est jamais lu par qui en a le plus besoin."""
        from unittest.mock import Mock, patch

        from script.todo.sms import menu

        etat = self.spec_mod.load("mobile")
        dits = []
        with patch.object(menu, "_run_one", return_value=False), \
                patch("builtins.print",
                      lambda *a, **k: dits.append(" ".join(map(str, a)))):
            menu.enchainer(Mock(), etat)
        ecran = "\n".join(dits)
        self.assertIn("RCS", ecran)
        # Affiche AVANT l'echec, donc present malgre l'arret immediat.
        self.assertIn("Google Messages", ecran)

    def test_le_modem_na_pas_a_lire_un_avis_sur_le_rcs(self):
        """Le modem n'a ni Google Messages ni application de messagerie."""
        from unittest.mock import Mock, patch

        from script.todo.sms import menu

        etat = self.spec_mod.load("modem")
        dits = []
        with patch.object(menu, "_run_one", return_value=False), \
                patch("builtins.print",
                      lambda *a, **k: dits.append(" ".join(map(str, a)))):
            menu.enchainer(Mock(), etat)
        self.assertNotIn("RCS", "\n".join(dits))

    def test_lattente_sarrete_des_que_lappareil_dit_son_refus(self):
        """Il l'inscrit des le premier cycle, une trentaine de secondes :
        attendre les deux minutes entieres fait payer le reste pour rien."""
        from unittest.mock import patch

        from script.todo.sms import appairage, menu

        etat = self.spec_mod.load("mobile")
        horloge = iter([0, 0, 0, 25, 25, 25, 25, 25, 25])
        with patch.object(
                menu.local_backend, "gateway_poll_age", return_value=None
        ), patch.object(
                menu.local_backend, "taille_journal", return_value=0
        ), patch.object(
                appairage, "dernier_defaut", return_value="Cleartext refuse"
        ), patch("time.time", lambda: next(horloge)), \
                patch("time.sleep"), patch("builtins.print"):
            ok, detail = menu._attendre_interrogation(etat)
        self.assertFalse(ok)
        self.assertIn("Cleartext refuse", detail)

    def test_un_refus_de_clair_porte_le_geste_qui_le_leve(self):
        """Le motif seul laisse chercher du cote du serveur, alors que rien
        dans l'application ne peut lever cette politique."""
        from script.todo.sms import menu

        detail = menu._avec_remede(
            "IOException : Cleartext HTTP traffic to 10.0.0.2 not permitted"
        )
        self.assertIn("--lan-cleartext", detail)

    def test_un_autre_refus_nest_pas_affuble_dun_remede(self):
        from script.todo.sms import menu

        self.assertEqual(menu._avec_remede("HTTP 403"), "HTTP 403")

    def test_le_defaut_de_lappareil_passe_avant_le_journal_partage(self):
        """Le journal du serveur porte aussi les refus des AUTRES agents :
        les lire comme ceux du telephone fait corriger un secret qui va
        bien."""
        from unittest.mock import patch

        from script.todo.sms import appairage, menu

        etat = self.spec_mod.load("mobile")
        with patch.object(
                menu.local_backend, "gateway_poll_age", return_value=None
        ), patch.object(
                menu.local_backend, "taille_journal", return_value=0
        ), patch.object(
                menu.local_backend, "refus_recents",
                return_value=["sms_diag_signature"]
        ), patch.object(
                appairage, "dernier_defaut", return_value="refus de l appareil"
        ), patch("time.time", side_effect=[0, 0, 9999]), \
                patch("time.sleep"), patch("builtins.print"):
            ok, detail = menu._attendre_interrogation(etat)
        self.assertFalse(ok)
        self.assertEqual(detail, "refus de l appareil")

    def test_lappairage_accorde_les_permissions_de_la_passerelle(self):
        """Une reinstallation les remet toutes a « refusee », et l'ecran qui
        les demande est celui qu'on ne peut pas atteindre."""
        from unittest.mock import patch

        app = self._module()
        with patch.object(app, "appareils", return_value=["x"]), \
                patch.object(app, "run_as_ouvre", return_value=(True, "")), \
                patch.object(app, "lire_prefs", return_value=self.EXISTANT), \
                patch.object(app, "arreter_application"), \
                patch.object(app, "ecrire_prefs"), \
                patch.object(app, "reveiller_passerelle"), \
                patch.object(
                    app, "accorder_permissions", return_value=["SEND_SMS"]
                ) as accorde:
            ok, detail = app.appairer(self._spec(), "a" * 64, "http://h:1")
        self.assertTrue(ok)
        self.assertTrue(accorde.called)
        # Jamais en silence : ce qui a ete accorde est dit.
        self.assertIn("SEND_SMS", detail)

    DUMPSYS = (
        "    requested permissions:\n"
        "      android.permission.SEND_SMS: restricted=true\n"
        "    runtime permissions:\n"
        "      android.permission.SEND_SMS: granted=true, flags=[ X|Y ]\n"
    )

    def test_letat_se_lit_sur_la_ligne_qui_porte_granted(self):
        """`dumpsys` donne plusieurs lignes par permission : s'arreter a la
        premiere conclut « refusee » apres un octroi reussi."""
        from unittest.mock import patch

        app = self._module()
        with patch.object(app, "_adb", return_value=(0, self.DUMPSYS)):
            self.assertTrue(
                app.etat_permission("android.permission.SEND_SMS")
            )

    def test_une_permission_refusee_se_lit_comme_telle(self):
        from unittest.mock import patch

        app = self._module()
        refus = self.DUMPSYS.replace("granted=true", "granted=false")
        with patch.object(app, "_adb", return_value=(0, refus)):
            self.assertFalse(
                app.etat_permission("android.permission.SEND_SMS")
            )

    def test_une_permission_deja_accordee_nest_pas_reposee(self):
        from unittest.mock import patch

        app = self._module()
        with patch.object(app, "etat_permission", return_value=True), \
                patch.object(app, "_adb") as adb:
            self.assertEqual(app.accorder_permissions(), [])
        self.assertFalse(adb.called)

    def test_les_deux_permissions_de_la_passerelle_sont_posees(self):
        """Sans elles, la passerelle accepte le travail puis refuse de
        l'executer, sur « GATEWAY_NO_PERMISSION »."""
        from unittest.mock import patch

        app = self._module()
        appels = []
        with patch.object(app, "etat_permission", side_effect=[False, True,
                                                              False, True]), \
                patch.object(
                    app, "_adb",
                    side_effect=lambda a, **k: (appels.append(a), (0, ""))[1]
                ):
            posees = app.accorder_permissions()
        self.assertEqual(posees, ["SEND_SMS", "RECEIVE_SMS"])
        for args in appels:
            self.assertIn("grant", args)

    def test_le_service_de_passerelle_est_reveille(self):
        """Arreter l'application tue son service, et rouvrir son ecran ne le
        relance pas : la configuration serait posee et plus rien
        n'interrogerait le serveur."""
        from unittest.mock import patch

        app = self._module()
        with patch.object(app, "appareils", return_value=["x"]), \
                patch.object(app, "run_as_ouvre", return_value=(True, "")), \
                patch.object(app, "lire_prefs", return_value=self.EXISTANT), \
                patch.object(app, "arreter_application"), \
                patch.object(app, "ecrire_prefs"), \
                patch.object(app, "accorder_permissions", return_value=[]), \
                patch.object(app, "reveiller_passerelle") as reveil:
            ok, _detail = app.appairer(self._spec(), "a" * 64, "http://h:1")
        self.assertTrue(ok)
        self.assertTrue(reveil.called)

    def test_le_reveil_passe_par_une_action_non_protegee(self):
        """`BOOT_COMPLETED` et `MY_PACKAGE_REPLACED` sont des diffusions que
        seul le systeme a le droit d'emettre."""
        from unittest.mock import patch

        app = self._module()
        with patch.object(app, "_adb", return_value=(0, "")) as adb:
            app.reveiller_passerelle()
        args = adb.call_args[0][0]
        self.assertIn(f"{app.PAQUET}/{app.RECEPTEUR}", args)
        self.assertNotIn("android.intent.action.BOOT_COMPLETED", args)
        self.assertNotIn("android.intent.action.MY_PACKAGE_REPLACED", args)

    def test_lentree_nexiste_que_pour_le_telephone(self):
        """Un modem n'a pas d'application : l'entree n'aurait rien a poser."""
        from unittest.mock import Mock

        from script.todo.sms import menu

        faux = Mock()
        libelles = {
            materiel: [
                libelle
                for libelle, _a in menu._entrees_de_queue(
                    faux, self.spec_mod.load(materiel), materiel
                )
            ]
            for materiel in ("mobile", "modem")
        }
        from script.todo.todo_i18n import t

        cle = t("sms_pair_menu")
        self.assertIn(cle, libelles["mobile"])
        self.assertNotIn(cle, libelles["modem"])


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

        spec = self.spec_mod.spec_par_defaut("mobile")
        local.pid_serveur(spec).parent.mkdir(parents=True, exist_ok=True)
        local.pid_serveur(spec).write_text("999999999")
        self.assertEqual(local.server_pid(spec), 0)

    def test_un_fichier_pid_illisible_ne_fait_pas_tomber(self):
        from script.todo.sms import local

        spec = self.spec_mod.spec_par_defaut("mobile")
        local.pid_serveur(spec).parent.mkdir(parents=True, exist_ok=True)
        local.pid_serveur(spec).write_text("ceci n'est pas un nombre")
        self.assertEqual(local.server_pid(spec), 0)

    def test_le_serveur_part_avec_le_secret_de_sa_passerelle(self):
        """Le lancement du serveur n'est joue par aucun autre test : il part
        detache. Une seule ligne fausse y dort jusqu'a la demonstration."""
        from unittest.mock import Mock, patch

        from script.todo.sms import gateway as gw
        from script.todo.sms import local

        spec = self.spec_mod.spec_par_defaut("modem")
        processus = Mock()
        processus.pid = 424242
        processus.poll.return_value = None
        # Libre avant le lancement, ouvert ensuite : c'est la vie normale.
        with patch.object(local, "find_venv", return_value=Path("/tmp/venv")), \
                patch.object(
                    local, "_port_ouvert", side_effect=[False, True]
                ), \
                patch.object(
                    local.subprocess, "Popen", return_value=processus
                ) as lance, \
                patch.object(local, "server_pid", return_value=0):
            ok, detail = local.start_server(spec)
        self.assertTrue(ok, detail)
        env = lance.call_args.kwargs["env"]
        self.assertEqual(
            env[gw.ENV_SECRET], self.spec_mod.read_secret("modem")
        )
        self.assertTrue(env[gw.ENV_SECRET])

    def test_un_port_tenu_par_un_etranger_nest_pas_un_serveur_pret(self):
        """Odoo s'arrete sur « port in use » pendant que le port repond : lire
        le port seul annoncait pret pour un processus deja mort."""
        from unittest.mock import patch

        from script.todo.sms import local

        spec = self.spec_mod.spec_par_defaut("mobile")
        with patch.object(local, "server_pid", return_value=0), \
                patch.object(local, "_port_ouvert", return_value=True), \
                patch.object(local.subprocess, "Popen") as lance:
            ok, detail = local.start_server(spec)
        self.assertFalse(ok)
        self.assertIn(str(spec.odoo_port), detail)
        self.assertFalse(lance.called, "un second Odoo a ete lance pour rien")

    def test_chaque_materiel_a_son_fichier_pid(self):
        # Un PID commun ferait qu'arreter un serveur abattrait l'autre.
        from script.todo.sms import local

        self.assertNotEqual(
            local.pid_serveur(self.spec_mod.spec_par_defaut("mobile")),
            local.pid_serveur(self.spec_mod.spec_par_defaut("modem")),
        )

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

    def test_le_pense_bete_porte_ladresse_de_linterface(self):
        """C'est elle qu'on saisit : la boucle locale ne designe le poste que
        depuis le poste, et seulement si le renvoi USB tient."""
        from script.todo.sms import gateway

        spec = self.spec_mod.spec_par_defaut("mobile")
        bloc = gateway.render_mobile_config(spec, "a" * 64, "", "192.168.50.10")
        premiere = [
            ligne for ligne in bloc.splitlines() if "URL du serveur" in ligne
        ][0]
        self.assertIn("192.168.50.10", premiere)
        self.assertNotIn("127.0.0.1", premiere)
        # La boucle reste dite, nommee pour ce qu'elle vaut.
        self.assertIn("renvoi USB", bloc)
        self.assertIn("127.0.0.1", bloc)
        # Sortir du cable exige les memes deux conditions que le Wi-Fi.
        self.assertIn("lanCleartext", bloc)

    def test_sans_adresse_connue_la_boucle_reste_lurl(self):
        """Pas d'interface lisible : le renvoi USB est le seul chemin sur."""
        from script.todo.sms import gateway

        spec = self.spec_mod.spec_par_defaut("mobile")
        bloc = gateway.render_mobile_config(spec, "a" * 64, "", "")
        premiere = [
            ligne for ligne in bloc.splitlines() if "URL du serveur" in ligne
        ][0]
        self.assertIn("127.0.0.1", premiere)

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
        brut = json.loads(
            self.spec_mod.chemin_etat("mobile").read_text(encoding="utf-8")
        )
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

        chemin = local.journal_serveur(self.spec_mod.spec_par_defaut("mobile"))
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(contenu, encoding="utf-8")

    def _refus(self):
        from script.todo.sms import local

        return local.refus_recents(self.spec_mod.spec_par_defaut("mobile"))

    def test_une_signature_invalide_est_nommee(self):
        # C'est la panne vecue : le telephone signait avec un secret perime,
        # Odoo refusait en 403, et la chaine annoncait cinq etapes sur six.
        from script.todo.sms import local

        self._journal(self.JOURNAL)
        self.assertIn("sms_diag_signature", self._refus())

    def test_un_appareil_inconnu_est_distingue(self):
        # Meme symptome a l'ecran qu'une signature invalide, geste different :
        # l'un se corrige par le secret, l'autre par l'identifiant.
        from script.todo.sms import local

        self._journal(self.JOURNAL)
        self.assertIn("sms_diag_device", self._refus())

    def test_un_journal_sans_refus_ne_signale_rien(self):
        from script.todo.sms import local

        self._journal("2026-08-29 08:00:00 INFO tout va bien\n")
        self.assertEqual(self._refus(), [])

    def test_un_journal_absent_ne_fait_pas_tomber(self):
        from script.todo.sms import local

        chemin = local.journal_serveur(self.spec_mod.spec_par_defaut("mobile"))
        if chemin.exists():
            chemin.unlink()
        self.assertEqual(self._refus(), [])

    def test_un_refus_anterieur_a_lattente_nest_pas_sa_cause(self):
        """Le journal est partage par tout ce qui interroge ce serveur : sans
        borne, on va regler l'horloge d'un telephone dont l'horloge est
        juste."""
        from script.todo.sms import local

        self._journal(self.JOURNAL)
        spec = self.spec_mod.spec_par_defaut("mobile")
        marque = local.taille_journal(spec)
        self.assertEqual(local.refus_recents(spec, depuis_octet=marque), [])
        # Ce qui s'ajoute ensuite, lui, decrit bien l'attente.
        with open(local.journal_serveur(spec), "a", encoding="utf-8") as fh:
            fh.write(
                "2026-08-29 09:00:00 WARNING demo ...: erplibre:"
                " horodatage hors fenetre (900s)\n"
            )
        self.assertIn(
            "sms_diag_clock",
            local.refus_recents(spec, depuis_octet=marque),
        )

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
        return self.spec_mod.spec_par_defaut(materiel)

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

    def test_le_script_neutralise_un_fournisseur_odoo_perime(self):
        """Un connecteur disparu bloque la pose de la fiche pour toujours."""
        from script.todo.sms import gateway as gw

        script = gw.render_setup_script(self._spec("mobile"))
        self.assertIn("sms_provider", script)
        self.assertIn("_description_selection", script)
        self.assertIn("RESULTAT_PROVIDER_PERIME", script)
        # Ce qui est ENCORE offert reste a l'humain : la contrainte le dit
        # deja, et l'ecraser volerait un choix delibere.
        self.assertIn("not in offertes", script)

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
        self.assertEqual(
            environnement[agent_mod.VARIABLE_APPAREIL], "demo-modem-01"
        )
        self.assertEqual(environnement[agent_mod.VARIABLE_SECRET], "abc")
        self.assertTrue(environnement[agent_mod.VARIABLE_URL].startswith("http"))

    def test_avancer_une_passerelle_ne_defait_pas_lautre(self):
        """Les deux demonstrations tiennent cote a cote, chacune son etat."""
        mobile = self.spec_mod.load("mobile")
        for etape in ("vm", "odoo", "gateway", "mobile"):
            mobile.mark_done(etape)
        self.spec_mod.save(mobile)

        modem = self.spec_mod.load("modem")
        self.assertEqual(modem.done, [])
        modem.mark_done("vm")
        self.spec_mod.save(modem)

        self.assertEqual(len(self.spec_mod.load("mobile").done), 4)
        self.assertEqual(self.spec_mod.load("modem").done, ["vm"])

    def test_les_deux_odoo_ne_se_marchent_pas_dessus(self):
        """Meme port ou meme base : configurer l'un deferait l'autre."""
        mobile = self.spec_mod.spec_par_defaut("mobile")
        modem = self.spec_mod.spec_par_defaut("modem")
        self.assertNotEqual(mobile.odoo_port, modem.odoo_port)
        self.assertNotEqual(mobile.db_name, modem.db_name)
        self.assertNotEqual(mobile.vm_name, modem.vm_name)
        self.assertNotEqual(mobile.device_id, modem.device_id)

    def test_chaque_passerelle_a_son_secret(self):
        """Deux Odoo : une cle commune ferait qu'en oublier une changerait."""
        self.assertNotEqual(
            self.spec_mod.ensure_secret("mobile"),
            self.spec_mod.ensure_secret("modem"),
        )

    def test_le_dossier_dit_le_materiel_plus_fort_quun_vieux_fichier(self):
        """Un etat recopie a la main ne doit pas faire juger l'autre fiche."""
        import json

        self.spec_mod._ensure_dossier("modem")
        self.spec_mod.chemin_etat("modem").write_text(
            json.dumps({"spec": {"materiel": "mobile"}, "done": []}),
            encoding="utf-8",
        )
        self.assertEqual(self.spec_mod.load("modem").spec.materiel, "modem")

    def _poser_ancien_etat_unique(self, spec, done):
        import json

        self.spec_mod.BASE.mkdir(parents=True, exist_ok=True)
        (self.spec_mod.BASE / "demo.json").write_text(
            json.dumps({"spec": spec, "done": done}), encoding="utf-8"
        )
        (self.spec_mod.BASE / "hmac.secret").write_text(
            "abc\n", encoding="utf-8"
        )

    def test_letat_dun_seul_dossier_est_repris_par_son_materiel(self):
        """Une demonstration a moitie faite ne doit pas repartir de zero."""
        self._poser_ancien_etat_unique(
            {"materiel": "mobile", "test_number": "+15550123"},
            ["vm", "odoo"],
        )
        self.assertEqual(self.spec_mod.load("modem").done, [])
        repris = self.spec_mod.load("mobile")
        self.assertEqual(repris.done, ["vm", "odoo"])
        self.assertEqual(repris.spec.test_number, "+15550123")
        self.assertEqual(self.spec_mod.read_secret("mobile"), "abc")

    def test_letat_repris_prend_le_port_et_lidentifiant_du_materiel(self):
        """L'ancien jeu unique portait ceux des deux : les garder mettrait les
        deux demonstrations sur un meme port, et la seconde ne demarrerait
        pas."""
        mobile = self.spec_mod.spec_par_defaut("mobile")
        self._poser_ancien_etat_unique(
            {
                "materiel": "modem",
                "odoo_port": mobile.odoo_port,
                "device_id": mobile.device_id,
            },
            ["vm", "odoo", "gateway"],
        )
        repris = self.spec_mod.load("modem")
        modem = self.spec_mod.spec_par_defaut("modem")
        self.assertEqual(repris.spec.odoo_port, modem.odoo_port)
        self.assertEqual(repris.spec.device_id, modem.device_id)
        # Ce qu'un serveur avait fait ne decrivait pas cet Odoo-la.
        self.assertEqual(repris.done, ["vm"])
        self.assertEqual(self.spec_mod.read_secret("modem"), "abc")

    def test_le_menu_ne_pose_pas_la_question_du_cable_sur_un_modem(self):
        """Le transport dit comment le TELEPHONE joint Odoo."""
        from unittest.mock import patch

        from script.todo.sms import menu

        with patch.object(menu.click, "prompt", side_effect=["12", "0"]), \
                patch.object(menu, "_choose_mode"), \
                patch.object(menu, "_choose_transport") as transport, \
                patch("builtins.print"):
            menu.prompt_execute_sms(self._todo(), "modem")
        self.assertFalse(transport.called)

    def test_lire_les_sms_lit_lappareil_quon_demontre(self):
        """Sur le modem, aucun telephone n'est branche : adb ne rend rien."""
        from unittest.mock import patch

        from script.todo.sms import menu

        with patch.object(menu.click, "prompt", side_effect=["8", "0"]), \
                patch.object(menu, "_read_phone") as telephone, \
                patch("script.todo.modem.menu._lister_sms") as modem, \
                patch("builtins.print"):
            menu.prompt_execute_sms(self._todo(), "modem")
        self.assertFalse(telephone.called)
        self.assertTrue(modem.called)

    def _todo(self):
        from unittest.mock import Mock

        faux = Mock()
        faux._menu_header.return_value = ""
        return faux

    def test_le_menu_modem_ouvre_la_demonstration_du_modem(self):
        """Arriver par la ne doit jamais montrer la passerelle du telephone."""
        from unittest.mock import patch

        from script.todo.modem import menu as modem_menu

        with patch("script.todo.sms.menu.prompt_execute_sms") as ouvre:
            modem_menu._passerelle(todo=None)
        ouvre.assert_called_once_with(None, "modem")

    def test_le_module_se_cherche_au_lieu_de_se_deviner(self):
        """Plus de cent depots d'addons : lequel porte le module ne se devine pas."""
        from script.todo.sms import spec as vrai_spec

        trouve = vrai_spec.trouver_module("erplibre_mobile_gateway")
        self.assertIsNotNone(trouve, "le module de la demonstration est introuvable")
        self.assertTrue(trouve.is_dir())
        self.assertIsNone(vrai_spec.trouver_module("module_qui_nexiste_pas"))

    def test_letape_une_trouve_le_module_ou_il_est(self):
        from script.todo.sms import local as backend

        etat = self.spec_mod.load()
        ok, detail = backend.step_env(None, etat)
        self.assertTrue(ok, detail)

    def test_un_module_renomme_ne_bloque_pas_pour_toujours(self):
        """Le nom vit dans un JSON de `private/` : personne ne le corrigera."""
        import json

        from script.todo.sms import spec as vrai_spec

        etat = self.spec_mod.load()
        self.spec_mod.save(etat)
        brut = json.loads(
            self.spec_mod.chemin_etat("mobile").read_text(encoding="utf-8")
        )
        brut["spec"]["module"] = "erplibre_mobile_passerelle_sms"
        self.spec_mod.chemin_etat("mobile").write_text(
            json.dumps(brut), encoding="utf-8"
        )

        repris = self.spec_mod.load()
        self.assertEqual(repris.spec.module, vrai_spec.DemoSpec.module)

    def test_un_nom_valide_mais_different_est_respecte(self):
        """On rattrape ce qui est INTROUVABLE, pas ce qui deplait."""
        from dataclasses import replace

        from script.todo.sms import spec as vrai_spec

        temoin = "erplibre_devops"
        if vrai_spec.trouver_module(temoin) is None:
            self.skipTest("ce depot n'a pas ce module temoin")
        autre = replace(vrai_spec.DemoSpec(), module=temoin)
        self.assertEqual(vrai_spec._rattraper_le_module(autre).module, temoin)

    def test_letape_annoncee_porte_le_nom_du_materiel(self):
        """Annoncer « application mobile » ferait chercher un appareil absent."""
        from dataclasses import replace
        from unittest.mock import patch

        from script.todo.sms import menu

        etat = self.spec_mod.load()
        etat.spec = replace(etat.spec, materiel="modem")
        for etape in ("vm", "odoo", "gateway"):
            etat.mark_done(etape)
        dit = []
        with patch("builtins.print", lambda *a, **k: dit.append(" ".join(map(str, a)))), \
                patch.object(menu, "_dispatch", return_value=(True, "")):
            menu._run_one(None, etat, self.steps.BY_ID["mobile"])
        annonce = " ".join(dit)
        self.assertIn("agent", annonce.lower())
        self.assertNotIn("application mobile", annonce.lower())


if __name__ == "__main__":
    unittest.main()
