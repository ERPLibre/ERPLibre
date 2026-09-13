#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""La case « cache » du formulaire QEMU, et ce qu'elle change à la commande.

Trois propriétés, chacune pour une panne :

  1. la case n'est offerte que là où elle a un effet — une case qui ne change
     rien apprend au lecteur une chose fausse ;
  2. cochée, la commande porte « --cache-bypass » et JAMAIS l'autorité en
     même temps : une VM exceptée ne rencontrera pas le cache, et cette
     signature n'aurait rien à faire dans son magasin ;
  3. le chemin de l'autorité est le MÊME que celui où l'installateur la pose.
     Les deux séparés, la VM approuverait un fichier qui n'existe pas — et
     rien ne le dirait.

L'écran Proxmox n'a pas cette case, et c'est voulu : sa VM naît sur un hôte
distant, que le cache local ne sert pas.
"""

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

QEMU_FORM = RACINE / "script" / "todo" / "qemu_deploy_form.py"
PROXMOX_FORM = RACINE / "script" / "todo" / "proxmox_deploy_form.py"
QEMU_DEPLOY = RACINE / "script" / "todo" / "qemu_deploy.py"
INSTALLATEUR = RACINE / "script" / "install" / "install_qemu_cache.sh"

from script.todo.qemu_deploy import QemuDeployMixin  # noqa: E402
from script.todo.todo import TODO  # noqa: E402


class TestLaCaseNePrometQueCeQuElleTient(unittest.TestCase):
    """Une case a existé qui ne tenait pas sa promesse, et c'est l'histoire
    de celle-ci.

    Décocher n'omettait que l'AUTORITÉ. L'interception étant transparente et
    couvrant tout le pont, la VM était détournée quand même et échouait sur
    « self-signed certificate in certificate chain » à chaque téléchargement
    HTTPS : la case fabriquait une machine cassée.

    La case revient parce qu'elle a désormais de quoi tenir : une exception
    par adresse MAC, posée sur l'hôte avant la création. Ce qui se vérifie
    ici, c'est donc le lien — cochée, la commande porte « --cache-bypass »,
    et jamais l'autorité en même temps.
    """

    def test_la_case_mene_a_lexception_et_non_au_seul_retrait(self):
        src = QEMU_FORM.read_text(encoding="utf-8")
        self.assertIn("f_cache_bypass", src, "la case a disparu du formulaire")
        self.assertIn(
            "cache_bypass",
            QEMU_DEPLOY.read_text(encoding="utf-8"),
            "la case ne mène à rien dans la commande",
        )

    def test_lecran_proxmox_ne_loffre_pas(self):
        """Sa VM naît sur un hôte distant, que le cache local ne sert pas."""
        self.assertNotIn(
            "cache_bypass", PROXMOX_FORM.read_text(encoding="utf-8")
        )

    def test_la_case_est_gardee_par_letat_du_cache(self):
        """Sans service actif rien n'intercepte : une case qui ne change rien
        apprend au lecteur une chose fausse.

        Le drapeau est lu du CONTEXTE. La version d'avant le cherchait dans
        « defaults », qui ne porte que ce qu'on veut pré-cocher et reste vide
        au premier affichage : la case ne s'affichait jamais, et ce contrôle —
        qui ne lisait que le source — l'attestait quand même.
        """
        src = QEMU_FORM.read_text(encoding="utf-8")
        self.assertIn('cache_offert = bool(ctx.get("cache_offert"))', src)
        bloc = src[: src.index("f_cache_bypass")]
        self.assertIn(
            "if cache_offert:",
            bloc[-500:],
            "la case s'affiche sans égard à l'état du cache",
        )

    def test_lautorite_suit_le_service_et_non_une_case(self):
        src = QEMU_DEPLOY.read_text(encoding="utf-8")
        self.assertIn("_qemu_cache_active()", src)
        self.assertNotIn(
            'spec.get("use_cache")',
            src,
            "l'autorité dépend encore d'un choix qui ne peut pas être tenu",
        )


class TestCommandeProduite(unittest.TestCase):
    """Le drapeau passe par le POINT DE PASSAGE UNIQUE des deux interfaces."""

    def vm(self):
        return {
            "distro": "arch",
            "version": "latest",
            "arch": "amd64",
            "name": "essai",
            "ram": 4096,
            "vcpus": 2,
            "disk": "20G",
        }

    def parts(self, spec, ca="", actif=True):
        # « TODO.__new__ » sans __init__ : l'idiome des tests du dépôt, qui
        # donne toutes les méthodes du menu sans ouvrir d'écran.
        todo = TODO.__new__(TODO)
        # Ni l'autorité ni le service ne sont ceux de la machine de test : la
        # détection est remplacée, le reste du chemin reste intact.
        todo._qemu_cache_ca_path = lambda: ca
        todo._qemu_cache_active = lambda: actif and bool(ca)
        return todo._qemu_deploy_parts_for(self.vm(), spec, dry_run=True)

    def test_service_arrete_aucun_drapeau(self):
        """Sans interception, l'autorité n'a rien à faire dans la VM."""
        parts = self.parts({"install": None}, ca="/tmp/ca.crt", actif=False)
        self.assertNotIn("--cache-ca", parts)

    def test_service_actif_le_drapeau_et_le_chemin(self):
        """Le service tourne : la VM SERA détournée, donc elle doit approuver
        l'autorité, quoi qu'on ait coché."""
        parts = self.parts({"install": None}, ca="/tmp/essai-ca.crt")
        self.assertIn("--cache-ca", parts)
        self.assertEqual(
            parts[parts.index("--cache-ca") + 1],
            "/tmp/essai-ca.crt",
            "le chemin de l'autorité ne suit pas le drapeau",
        )

    def test_cache_disparu_entre_temps(self):
        """Le chemin est relu à CHAQUE commande : un cache désinstallé entre
        le formulaire et le déploiement ne doit pas faire approuver une
        autorité qui n'existe plus."""
        parts = self.parts({"install": None}, ca="")
        self.assertNotIn("--cache-ca", parts)


class TestLInstallationNeSannonceQueSiElleAEuLieu(unittest.TestCase):
    """Un code de sortie non nul n'est pas une réussite.

    Vécu : l'installateur est mort sur « réseau libvirt default introuvable »,
    a rendu 1, et l'entrée a imprimé « Cache de téléchargement QEMU installé
    et démarré » juste en dessous, avec le chemin d'une autorité qui n'existe
    pas. Un succès annoncé à tort coûte plus qu'une panne : on cherche
    ensuite partout sauf là où elle est.
    """

    def _installer(self, code):
        """Joue l'entrée 1 avec un installateur qui rend `code`."""
        import contextlib
        import io

        import click

        todo = TODO.__new__(TODO)
        todo.execute = mock.Mock()
        todo.execute.exec_command_live = mock.Mock(return_value=code)
        with mock.patch("builtins.input", return_value=""), mock.patch.object(
            click, "confirm", return_value=True
        ):
            with contextlib.redirect_stdout(io.StringIO()) as sortie:
                todo._deploy_qemu_cache()
        return sortie.getvalue()

    def test_un_echec_ne_sannonce_pas_comme_une_reussite(self):
        dit = self._installer(1)
        self.assertNotIn("installed and started", dit)
        self.assertNotIn("installé et démarré", dit)
        self.assertNotIn("ca.crt", dit, "une autorité inexistante est nommée")

    def test_un_echec_dit_quoi_faire(self):
        self.assertIn("1", self._installer(1))

    def test_une_reussite_sannonce_et_nomme_lautorite(self):
        dit = self._installer(0)
        self.assertIn("ca.crt", dit)


class TestLeReseauDonneALaMain(unittest.TestCase):
    """Un pont nommé à la main suffit : l'installateur ne sonde plus libvirt.

    Vécu ailleurs : sur une machine dont le réseau libvirt « default » n'est
    pas démarré, l'installation mourait sur « réseau introuvable » — et le
    contournement annoncé en tête du fichier, EL_BRIDGE et EL_SUBNET, ne
    servait à rien, la sonde tombant AVANT que ces variables soient lues.
    """

    def _jouer(self, env):
        """Exécute la VRAIE fonction, extraite du script, avec un « virsh »
        qui échoue et des « log »/« die » de doublure."""
        source = INSTALLATEUR.read_text(encoding="utf-8")
        corps = re.search(
            r"^detecter_reseau\(\) \{.*?^\}", source, re.S | re.M
        )
        self.assertIsNotNone(corps, "detecter_reseau introuvable")
        script = (
            'log() { echo "LOG: $*"; }\n'
            'die() { echo "DIE: $*" >&2; exit 1; }\n'
            "virsh() { return 1; }\n"
            f"{corps.group(0)}\n"
            "detecter_reseau\n"
        )
        return subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            env=dict(os.environ, EL_NET="default", **env),
            timeout=30,
        )

    def test_les_deux_donnes_la_sonde_est_sautee(self):
        res = self._jouer({"EL_BRIDGE": "virbr9", "EL_SUBNET": "192.0.2.0/24"})
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertIn("virbr9", res.stdout)
        self.assertIn("192.0.2.0/24", res.stdout)

    def test_sans_eux_la_mort_nomme_les_deux_issues(self):
        """Mourir est juste ; mourir sans dire quoi faire ne l'est pas."""
        res = self._jouer({"EL_BRIDGE": "", "EL_SUBNET": ""})
        self.assertNotEqual(0, res.returncode)
        for issue in ("net-start", "EL_BRIDGE", "EL_SUBNET"):
            self.assertIn(issue, res.stderr, res.stderr)

    def test_un_seul_des_deux_ne_suffit_pas(self):
        """Le pont sans le sous-réseau laisserait des règles sans préfixe."""
        res = self._jouer({"EL_BRIDGE": "virbr9", "EL_SUBNET": ""})
        self.assertNotEqual(0, res.returncode)

    def test_la_garde_precede_la_sonde(self):
        """L'ordre EST le correctif : lue après, la garde ne sauverait rien."""
        source = INSTALLATEUR.read_text(encoding="utf-8")
        self.assertLess(
            source.index('if [ -n "$EL_BRIDGE" ] && [ -n "$EL_SUBNET" ]'),
            source.index("net-dumpxml"),
        )


class TestAccordAvecLInstallateur(unittest.TestCase):
    def test_meme_chemin_dautorite(self):
        """`EL_CA_DIR` du script et `QEMU_CACHE_CA` du menu doivent désigner
        le même fichier."""
        texte = INSTALLATEUR.read_text(encoding="utf-8")
        m = re.search(r'EL_CA_DIR="\$\{EL_CA_DIR:-([^}]+)\}"', texte)
        self.assertIsNotNone(m, "EL_CA_DIR introuvable dans l'installateur")
        attendu = f"{m.group(1)}/ca.crt"
        self.assertEqual(
            QemuDeployMixin.QEMU_CACHE_CA,
            attendu,
            "le menu cherche l'autorité là où l'installateur ne la pose pas",
        )

    def test_meme_nom_de_service(self):
        texte = INSTALLATEUR.read_text(encoding="utf-8")
        m = re.search(r"UNIT=\"/etc/systemd/system/([^\"]+)\"", texte)
        self.assertIsNotNone(m, "le nom de l'unité est introuvable")
        self.assertEqual(
            QemuDeployMixin.QEMU_CACHE_SERVICE,
            m.group(1),
            "le menu interroge un service que l'installateur ne pose pas",
        )


class TestDetectionHote(unittest.TestCase):
    def test_pas_dautorite_pas_de_chemin(self):
        class Absent(QemuDeployMixin):
            QEMU_CACHE_CA = "/inexistant/ca.crt"

        self.assertEqual(Absent._qemu_cache_ca_path(), "")
        self.assertFalse(
            Absent._qemu_cache_active(),
            "un service est déclaré actif alors qu'aucune autorité n'existe",
        )


try:
    import textual  # noqa: F401

    TEXTUAL = True
except Exception:  # pragma: no cover - Textual absent
    TEXTUAL = False


def contexte_du_formulaire():
    todo = TODO.__new__(TODO)
    mod = todo._qemu_import_module()
    todo._qemu_list_domains = lambda: []
    todo._qemu_branch_list = lambda: ["develop", "master"]
    return todo._qemu_form_context(mod)


def choisir_une_vm(app):
    """Coche la première entrée du catalogue et refait le plan.

    Sans sélection, « action_deploy » sort sur « Rien de sélectionné » et
    n'atteint aucun des contrôles qu'on veut éprouver.
    """
    from textual.widgets import SelectionList

    liste = app.query_one("#f_catalog", SelectionList)
    liste.select(liste.options[0].value)
    app._recompute()
    return app.vms


def champs_affiches(ctx):
    """Les identifiants réellement montés dans le panneau, sans écran."""
    import asyncio

    from script.todo.qemu_deploy_form import run_deploy_form

    vu = []

    async def scenario():
        app = run_deploy_form(ctx, run_app=False)
        async with app.run_test(size=(200, 60)) as pilote:
            await pilote.pause()
            vu.extend(w.id for w in app.query("#fields *") if w.id)

    asyncio.run(scenario())
    return vu


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestLaCaseEstVraimentLa(unittest.TestCase):
    """La case a existé sans jamais s'afficher, et personne ne le voyait.

    Elle était gardée par « defaults.get('cache_offert') ». Or « defaults » ne
    porte que ce qu'on veut PRÉ-COCHER et il est vide au premier affichage : la
    condition valait toujours faux. Les contrôles de source, eux, la trouvaient
    bien dans le fichier — d'où un écran qui invitait à cocher une case
    introuvable.

    Ces contrôles-ci MONTENT le formulaire et regardent ce qu'il affiche.
    """

    @classmethod
    def setUpClass(cls):
        cls.ctx = contexte_du_formulaire()

    def test_elle_saffiche_quand_le_cache_tourne(self):
        champs = champs_affiches(dict(self.ctx, cache_offert=True))
        self.assertIn(
            "f_cache_bypass",
            champs,
            "la case n'est pas montée alors que le cache tourne",
        )

    def test_elle_disparait_quand_le_cache_est_eteint(self):
        """Une case sans effet apprend au lecteur une chose fausse."""
        champs = champs_affiches(dict(self.ctx, cache_offert=False))
        self.assertNotIn("f_cache_bypass", champs)

    def test_cochee_elle_arrive_dans_la_spec(self):
        """Le dernier maillon : c'est la spec qui décide de la commande.

        Une case affichée mais dont la valeur n'est pas relue serait aussi
        inutile qu'une case absente, et la panne se lirait au déploiement.
        """
        import asyncio

        from textual.widgets import Checkbox

        from script.todo.qemu_deploy_form import run_deploy_form

        vu = {}
        ctx = dict(self.ctx, cache_offert=True)

        async def scenario():
            app = run_deploy_form(ctx, run_app=False)
            async with app.run_test(size=(200, 60)) as pilote:
                await pilote.pause()
                case = app.query_one("#f_cache_bypass", Checkbox)
                vu["defaut"] = case.value
                case.value = True
                await pilote.pause()
                vu["spec"] = app._form_values().get("cache_bypass")

        asyncio.run(scenario())
        self.assertIs(
            vu["defaut"],
            False,
            "la case est cochée d'avance : le cache"
            " serait contourné sans qu'on l'ait demandé",
        )
        self.assertIs(vu["spec"], True)

    def test_le_contexte_porte_bien_la_cle(self):
        """L'autre moitié de la dérive : le menu doit la fournir là où le
        formulaire la lit, c'est-à-dire au niveau du contexte."""
        self.assertIn("cache_offert", self.ctx)
        self.assertNotIn(
            "cache_offert",
            self.ctx.get("defaults") or {},
            "la clé est repartie dans « defaults », où elle est ignorée",
        )


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestRienDeCollecteNeSePerd(unittest.TestCase):
    """Une liste blanche perd ce qu'on oublie d'y écrire, et sans un mot.

    Le formulaire collecte ses champs, puis « build_spec » assemble la spec —
    clé par clé, nommées à la main. Un champ ajouté au formulaire et pas à
    cette assemblée est réglé par l'opérateur, affiché, relu… et jeté. La
    trace en porte déjà deux : le suivi et la 3D, chacun réparé après coup.

    Le contrôle ne vérifie plus une clé mais la PROPRIÉTÉ : tout ce que le
    formulaire collecte doit se retrouver dans la spec.
    """

    def test_toute_cle_collectee_arrive_dans_la_spec(self):
        import asyncio

        from script.todo.deploy_form_lib import build_spec
        from script.todo.qemu_deploy_form import run_deploy_form

        vu = {}
        ctx = dict(contexte_du_formulaire(), cache_offert=True)

        async def scenario():
            app = run_deploy_form(ctx, run_app=False)
            async with app.run_test(size=(200, 60)) as pilote:
                await pilote.pause()
                valeurs = app._form_values()
                vu["perdues"] = sorted(
                    set(valeurs) - set(build_spec([], set(), valeurs))
                )
                vu["collectees"] = len(valeurs)

        asyncio.run(scenario())
        self.assertGreater(
            vu["collectees"], 10, "le relevé n'a presque rien trouvé"
        )
        self.assertEqual(
            vu["perdues"],
            [],
            "des réglages du formulaire n'atteignent jamais le déploiement :"
            f" {vu['perdues']}",
        )


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestLaSectionReseau(unittest.TestCase):
    """« Sans connexion internet » : la même chose que « --hors-ligne ».

    Ce n'est pas le réseau de la VM qui tombe — elle en a besoin pour joindre
    le cache — mais l'amont du service, le temps du déploiement.
    """

    @classmethod
    def setUpClass(cls):
        cls.ctx = contexte_du_formulaire()

    def setUp(self):
        """Aucun test de cette classe ne pose de règle de pare-feu.

        Ils cochent tous la case, et le jour où le formulaire régresse en
        coupant au clic, la coupure resterait sur la machine de test — aucun
        « finally » ne court sur un test qui vient d'échouer. Le cache
        rendrait 504 à toute VM déployée ensuite, et le message ne parlerait
        pas d'une règle oubliée.

        La garde est ici, sur la CLASSE, et non dans le seul test qui
        surveille : c'est celui qui ne surveillait pas qui a posé la règle.

        L'espion ne relaie RIEN à la vraie commande : ce qu'il n'attend pas
        reçoit un échec vide. Le pré-vol de F5 lit le suivi des déploiements
        et le journal du cache, puis interroge le binaire du service ; un
        ajout futur au pré-vol ne peut donc pas atteindre la machine. Le
        pré-vol par les essais précédents est remplacé pour toute la classe :
        il lirait le vrai ~/.erplibre et le vrai journal, et le résultat
        dépendrait de la machine qui lance les tests.
        """
        from script.qemu import cache_offline

        self.lancees = []

        def espion(cmd, *a, **kw):
            texte = cmd if isinstance(cmd, str) else " ".join(map(str, cmd))
            self.lancees.append(texte)
            if "nft" in texte:
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return subprocess.CompletedProcess(cmd, 127, "", "")

        for patch in (
            mock.patch("subprocess.run", espion),
            mock.patch.object(
                cache_offline, "manques_hors_ligne", lambda vms: []
            ),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def test_elle_saffiche_quand_le_cache_tourne(self):
        champs = champs_affiches(dict(self.ctx, cache_offert=True))
        self.assertIn("f_offline", champs)
        self.assertIn("t_network", champs, "la section n'a pas de titre")

    def test_elle_disparait_sans_cache(self):
        """Sans cache il n'y a pas d'amont à couper : la case ne ferait
        rien, et une case sans effet apprend une chose fausse."""
        champs = champs_affiches(dict(self.ctx, cache_offert=False))
        self.assertNotIn("f_offline", champs)

    def test_elle_vient_apres_le_parallelisme(self):
        """« à la toute fin » : la section est la dernière du panneau."""
        champs = champs_affiches(dict(self.ctx, cache_offert=True))
        self.assertLess(champs.index("f_par"), champs.index("t_network"))

    def test_cochee_elle_arrive_dans_la_spec(self):
        import asyncio

        from textual.widgets import Checkbox

        from script.todo.deploy_form_lib import build_spec
        from script.todo.qemu_deploy_form import run_deploy_form

        vu = {}
        ctx = dict(self.ctx, cache_offert=True)

        async def scenario():
            app = run_deploy_form(ctx, run_app=False)
            async with app.run_test(size=(200, 60)) as pilote:
                await pilote.pause()
                case = app.query_one("#f_offline", Checkbox)
                vu["defaut"] = case.value
                case.value = True
                await pilote.pause()
                valeurs = app._form_values()
                vu["spec"] = build_spec([], set(), valeurs)["offline"]

        asyncio.run(scenario())
        self.assertIs(
            vu["defaut"],
            False,
            "cochée d'avance, elle couperait l'amont sans qu'on l'ait"
            " demandé",
        )
        self.assertIs(vu["spec"], True)

    def test_lavertissement_ne_parait_que_cochee(self):
        """Il dit deux choses qu'on ne devine pas : la coupure vaut pour
        TOUS les usagers du cache, et elle ne tombe qu'au lancement."""
        import asyncio

        from textual.widgets import Checkbox

        from script.todo.qemu_deploy_form import run_deploy_form

        vu = {}
        ctx = dict(self.ctx, cache_offert=True)

        def visibles(app):
            return [
                w.id
                for w in app.query("#fields *")
                if str(w.id or "").startswith("t_offline_w") and w.display
            ]

        async def scenario():
            app = run_deploy_form(ctx, run_app=False)
            async with app.run_test(size=(200, 70)) as pilote:
                await pilote.pause()
                vu["decochee"] = visibles(app)
                app.query_one("#f_offline", Checkbox).value = True
                await pilote.pause()
                vu["cochee"] = visibles(app)
                app.query_one("#f_offline", Checkbox).value = False
                await pilote.pause()
                vu["redecochee"] = visibles(app)

        asyncio.run(scenario())
        self.assertEqual(
            vu["decochee"], [], "l'avertissement s'affiche sans être demandé"
        )
        self.assertEqual(len(vu["cochee"]), 7, f"vu : {vu['cochee']}")
        self.assertEqual(
            vu["redecochee"], [], "il reste affiché après décochage"
        )

    def suivi_selon_la_case(self, suivi_avant):
        """Coche puis décoche la case, le suivi réglé d'abord à
        `suivi_avant` ; rend ce que le suivi et la spec disent à chaque
        étape."""
        import asyncio

        from textual.widgets import Checkbox

        from script.todo.qemu_deploy_form import run_deploy_form

        vu = {}
        ctx = dict(self.ctx, cache_offert=True)

        def etat(app):
            case = app.query_one("#f_monitor", Checkbox)
            return (case.value, case.disabled, app._form_values()["monitor"])

        async def scenario():
            app = run_deploy_form(ctx, run_app=False)
            async with app.run_test(size=(200, 70)) as pilote:
                await pilote.pause()
                app.query_one("#f_monitor", Checkbox).value = suivi_avant
                await pilote.pause()
                vu["avant"] = etat(app)
                app.query_one("#f_offline", Checkbox).value = True
                await pilote.pause()
                vu["cochee"] = etat(app)
                app.query_one("#f_offline", Checkbox).value = False
                await pilote.pause()
                vu["decochee"] = etat(app)

        asyncio.run(scenario())
        return vu

    def test_hors_ligne_le_suivi_est_force_et_grise(self):
        """Seul le déploiement suivi confie la levée à une unité systemd :
        sans lui, la promesse de l'avertissement — l'amont revient à la fin
        de la dernière installation, 12 h au plus — ne tient pas."""
        vu = self.suivi_selon_la_case(False)
        self.assertEqual(vu["avant"], (False, False, False))
        self.assertEqual(
            vu["cochee"],
            (True, True, True),
            "hors ligne, le suivi reste décochable ou n'est pas forcé",
        )

    def test_decocher_rend_le_suivi_tel_quil_etait(self):
        vu = self.suivi_selon_la_case(False)
        self.assertEqual(
            vu["decochee"],
            (False, False, False),
            "décocher la case ne rend pas au suivi sa valeur ni sa main",
        )
        vu = self.suivi_selon_la_case(True)
        self.assertEqual(vu["decochee"], (True, False, True))

    def test_la_spec_exige_le_suivi_hors_ligne(self):
        """La défense derrière l'écran : un suivi décoché par un chemin qui
        contourne la case grisée part quand même suivi."""
        import asyncio

        from textual.widgets import Checkbox

        from script.todo.qemu_deploy_form import run_deploy_form

        vu = {}
        ctx = dict(self.ctx, cache_offert=True)

        async def scenario():
            app = run_deploy_form(ctx, run_app=False)
            async with app.run_test(size=(200, 70)) as pilote:
                await pilote.pause()
                app.query_one("#f_offline", Checkbox).value = True
                await pilote.pause()
                app.query_one("#f_monitor", Checkbox).value = False
                await pilote.pause()
                vu["valeurs"] = app._form_values()

        asyncio.run(scenario())
        self.assertIs(vu["valeurs"]["monitor"], True)
        if vu["valeurs"]["install"]:
            self.assertIs(vu["valeurs"]["install"]["monitor"], True)

    def test_cocher_la_case_ne_coupe_rien(self):
        """La coupure tombe à F5, pas au clic.

        Couper depuis le formulaire priverait le cache de réseau pendant
        qu'on remplit l'écran — et pour de bon si l'écran est annulé, aucun
        « finally » ne courant sur une case cochée.
        """
        import asyncio

        from textual.widgets import Checkbox

        from script.todo.qemu_deploy_form import run_deploy_form

        ctx = dict(self.ctx, cache_offert=True)

        async def scenario():
            app = run_deploy_form(ctx, run_app=False)
            async with app.run_test(size=(200, 70)) as pilote:
                await pilote.pause()
                app.query_one("#f_offline", Checkbox).value = True
                await pilote.pause()
                app._form_values()

        asyncio.run(scenario())
        coupures = [c for c in self.lancees if "nft" in c]
        self.assertEqual(
            coupures,
            [],
            f"le formulaire a coupé l'amont tout seul : {coupures}",
        )

    def test_f5_previent_avant_de_couper_pour_rien(self):
        """Une suite que le cache n'a jamais servie fait échouer la VM une
        heure plus tard, sur « Impossible de trouver le paquet » — un message
        qui ne parle ni du cache ni du hors ligne.

        Même idiome que les disques orphelins : on prévient une fois, F5 à
        nouveau vaut passage outre. Passer outre reste possible — le journal
        peut avoir tourné, ou le cache avoir été rempli autrement.
        """
        import asyncio

        from textual.widgets import Checkbox

        from script.qemu import cache_offline
        from script.todo.qemu_deploy_form import run_deploy_form

        vu = {}
        ctx = dict(self.ctx, cache_offert=True)

        async def scenario():
            app = run_deploy_form(ctx, run_app=False)
            async with app.run_test(size=(200, 70)) as pilote:
                await pilote.pause()
                choisir_une_vm(app)
                await pilote.pause()
                app.query_one("#f_offline", Checkbox).value = True
                await pilote.pause()
                app.action_deploy()
                vu["premier"] = app._result.get("spec")
                app.action_deploy()
                vu["second"] = app._result.get("spec")

        with mock.patch.object(
            cache_offline, "suites_absentes", lambda vms: [("ubuntu", "26.04")]
        ):
            asyncio.run(scenario())
        self.assertIsNone(
            vu["premier"], "le déploiement est parti sans prévenir"
        )
        self.assertIsNotNone(
            vu["second"], "un second F5 ne passe pas outre l'avertissement"
        )

    def test_f5_ne_previent_pas_quand_le_cache_a_de_quoi(self):
        import asyncio

        from textual.widgets import Checkbox

        from script.qemu import cache_offline
        from script.todo.qemu_deploy_form import run_deploy_form

        vu = {}
        ctx = dict(self.ctx, cache_offert=True)

        async def scenario():
            app = run_deploy_form(ctx, run_app=False)
            async with app.run_test(size=(200, 70)) as pilote:
                await pilote.pause()
                choisir_une_vm(app)
                await pilote.pause()
                app.query_one("#f_offline", Checkbox).value = True
                await pilote.pause()
                app.action_deploy()
                vu["premier"] = app._result.get("spec")

        with mock.patch.object(
            cache_offline, "suites_absentes", lambda vms: []
        ):
            asyncio.run(scenario())
        self.assertIsNotNone(
            vu["premier"], "un avertissement sans motif apprend à passer outre"
        )

    def test_le_formulaire_ne_sait_pas_couper(self):
        """La garde structurelle : le formulaire LIT ce que le cache détient
        — il en a besoin pour prévenir avant le lancement — mais il n'a
        aucun moyen de poser ni de lever la coupure, quoi qu'on y ajoute.

        La frontière est là et non sur le module entier : c'est le geste qui
        est interdit à cet écran, pas la connaissance.
        """
        src = QEMU_FORM.read_text(encoding="utf-8")
        for interdit in ("cut_cmd", "restore_cmd", "nft"):
            self.assertNotIn(
                interdit,
                src,
                f"le formulaire peut couper l'amont ({interdit})",
            )


if __name__ == "__main__":
    unittest.main()
