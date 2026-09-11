#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Déployer avec l'amont du cache coupé.

Ce qui tombe n'est PAS le réseau de la VM : elle en a besoin pour joindre le
cache, qui vit sur l'orchestrateur. Seul le service perd son accès sortant,
si bien que tout ce qui arrive encore dans la VM vient du disque.

Les règles sont VÉRIFIÉES au caractère près et jamais appliquées : la machine
qui exécute les tests garde son pare-feu intact.
"""

import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from script.qemu import cache_offline  # noqa: E402


class TestLesRegles(unittest.TestCase):
    def test_la_coupure_vise_le_compte_et_non_le_port(self):
        """Une règle générale sur le 443 de l'orchestrateur emporterait la
        session ssh depuis laquelle le déploiement est lancé."""
        regles = cache_offline.nft_rules()
        self.assertIn(f"meta skuid {cache_offline.SERVICE_USER}", regles)
        self.assertIn("hook output", regles)
        self.assertNotIn("hook input", regles)

    def test_les_deux_ports_tombent(self):
        """Ne couper que le 443 laisserait passer tout un miroir en clair."""
        self.assertIn("tcp dport { 80, 443 }", cache_offline.nft_rules())

    def test_la_politique_reste_permissive(self):
        """« policy accept » : seule la ligne ciblée jette. Une politique
        « drop » couperait tout ce que l'hôte émet."""
        self.assertIn("policy accept", cache_offline.nft_rules())

    def test_la_table_est_distincte_de_celle_du_detournement(self):
        """Les mêler ferait tomber la redirection de tout le pont en
        rebranchant l'amont."""
        self.assertNotEqual(cache_offline.TABLE, "erplibre_qemu_cache")

    def test_le_retrait_est_muet_sur_une_table_absente(self):
        """Il se fait dans un « finally » : une erreur y masquerait celle
        d'origine."""
        self.assertIn("|| true", cache_offline.restore_cmd())
        self.assertIn(cache_offline.TABLE, cache_offline.restore_cmd())


class TestLeCompteDuService(unittest.TestCase):
    """Le script d'installation est en shell et ne peut pas lire la valeur
    d'ici : les deux copies doivent dire la même chose, sans quoi la coupure
    viserait un compte qui n'émet rien et le test passerait pour hors ligne
    en étant en ligne."""

    def test_le_meme_compte_que_le_script_dinstallation(self):
        src = (
            RACINE / "script" / "install" / "install_qemu_cache.sh"
        ).read_text(encoding="utf-8")
        trouve = re.search(r'^SERVICE_USER="([^"]+)"', src, re.M)
        self.assertIsNotNone(trouve, "SERVICE_USER absent du script")
        self.assertEqual(trouve.group(1), cache_offline.SERVICE_USER)


class TestLeTestLongEtLeFormulaireCoupentPareil(unittest.TestCase):
    """Une seule source : ce que la case « Sans connexion internet » fait est
    exactement ce que la contre-épreuve du test long mesure."""

    def test_le_test_long_ne_recopie_pas_les_regles(self):
        src = (RACINE / "long_test" / "qemu_cache.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("cache_offline.cut_cmd()", src)
        self.assertNotIn("meta skuid", src)


class TestLeCablageDuDeploiement(unittest.TestCase):
    """La coupure couvre la spec ENTIÈRE, installation comprise, et se retire
    quoi qu'il arrive."""

    def _lance(self, offline, echec_coupure=False, plante=False):
        sys.argv = ["todo.py"]
        from script.todo.qemu_deploy import _SansInternetImpossible  # noqa
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        vu = {"shell": [], "ordre": []}

        def shell(cmd, timeout=60):
            vu["shell"].append(cmd)
            # Les relevés ne comptent pas dans l'ordre : aucun guet ne
            # tourne, aucune table n'est posée avant ni après.
            if "systemctl is-active" in cmd or "nft list tables" in cmd:
                return 1
            if "nft -f -" in cmd:
                vu["ordre"].append("coupure")
                return 1 if echec_coupure else 0
            vu["ordre"].append("rebranchement")
            return 0

        todo._qemu_shell = shell

        def deploie(spec, **kw):
            vu["ordre"].append("déploiement")
            if plante:
                raise RuntimeError("le déploiement a échoué")
            return "fait"

        todo._qemu_deploie_spec = deploie
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            if plante:
                with self.assertRaises(RuntimeError):
                    todo._qemu_run_spec({"offline": offline})
            else:
                vu["rendu"] = todo._qemu_run_spec({"offline": offline})
        vu["ecrit"] = sortie.getvalue()
        return vu

    def test_sans_la_case_rien_nest_touche(self):
        """Seul l'état du guet est relu, sans sudo : une coupure tenue par un
        autre déploiement ferait tourner celui-ci hors ligne."""
        vu = self._lance(offline=False)
        self.assertEqual(vu["ordre"], ["déploiement"])
        self.assertEqual(vu["shell"], [cache_offline.guet_actif_cmd()])

    def test_la_coupure_precede_le_deploiement(self):
        """Après lui, elle ne mesurerait plus rien : c'est l'installation qui
        télécharge."""
        vu = self._lance(offline=True)
        self.assertEqual(
            vu["ordre"], ["coupure", "déploiement", "rebranchement"]
        )

    def test_le_rebranchement_a_lieu_meme_si_le_deploiement_plante(self):
        """Une coupure laissée en place prive le cache de réseau bien après,
        et la panne se découvre ailleurs."""
        vu = self._lance(offline=True, plante=True)
        self.assertEqual(
            vu["ordre"], ["coupure", "déploiement", "rebranchement"]
        )

    def test_une_coupure_impossible_ne_deploie_rien(self):
        """Une VM bâtie avec l'amont debout se bâtit toujours : son succès se
        lirait comme une preuve hors ligne qu'elle n'est pas."""
        vu = self._lance(offline=True, echec_coupure=True)
        self.assertEqual(vu["ordre"], ["coupure"])
        self.assertIn("✗", vu["ecrit"])

    def test_la_spec_porte_bien_la_cle(self):
        from script.todo.deploy_form_lib import build_spec

        spec = build_spec(
            [],
            set(),
            {
                "res_label": "",
                "ssh_key": "",
                "install": None,
                "add_ssh_config": True,
                "parallelism": 1,
                "offline": True,
            },
        )
        self.assertIs(spec["offline"], True)


class TestLeDiagnosticVoitLaCoupure(unittest.TestCase):
    """Une coupure restée en place est muette là où on la cherche.

    Le rebranchement est dans un « finally », mais un « finally » ne court
    pas sur un processus tué net. Le cache rend alors « 504 » à chaque VM et
    l'installation échoue sur « failed retrieving file … 504 » depuis TOUS
    les miroirs — un message qui accuse les miroirs, jamais une règle de
    pare-feu posée sur l'hôte.

    Le journal du cache écrivait bien « offline-miss », et le diagnostic le
    montrait ; encore fallait-il savoir le lire. Il le dit maintenant.
    """

    TABLE_POSEE = (
        f"table inet {cache_offline.TABLE} {{\n"
        "  chain sortie {\n"
        "    type filter hook output priority filter; policy accept;\n"
        "    meta skuid 959 tcp dport { 80, 443 } drop\n"
        "  }\n"
        "}\n"
    )
    TABLE_ABSENTE = "Error: No such file or directory"

    def _menu(self, listing):
        sys.argv = ["todo.py"]
        from script.todo.qemu_cache_menu import QemuCacheMenuMixin

        class Faux(QemuCacheMenuMixin):
            @staticmethod
            def _cache_lire(cmd, delai=15):
                return listing if cache_offline.TABLE in cmd else ""

        return Faux

    def test_elle_est_vue_quand_elle_est_posee(self):
        self.assertTrue(self._menu(self.TABLE_POSEE)._cache_amont_coupe())

    def test_rien_nest_annonce_quand_elle_ne_lest_pas(self):
        self.assertFalse(self._menu(self.TABLE_ABSENTE)._cache_amont_coupe())

    def test_une_lecture_impossible_ne_crie_pas_au_loup(self):
        """Sans sudo, « nft list » ne rend rien : annoncer une coupure
        enverrait chercher une règle qui n'existe pas."""
        self.assertFalse(self._menu("")._cache_amont_coupe())

    def test_le_diagnostic_la_nomme_et_donne_le_geste(self):
        import contextlib
        import io as _io

        menu = self._menu(self.TABLE_POSEE)
        faux = menu.__new__(menu)
        faux._cache_actif = lambda: True
        with mock.patch("os.path.isfile", return_value=True), mock.patch(
            "script.todo.qemu_cache_menu.QemuCacheMenuMixin._cache_par_machine",
            return_value=[],
        ), mock.patch(
            "script.todo.qemu_cache_menu.QemuCacheMenuMixin"
            "._cache_compte_issues",
            return_value={},
        ), mock.patch(
            "script.todo.qemu_cache_menu.QemuCacheMenuMixin"
            "._cache_bypass_lire",
            return_value=[],
        ), contextlib.redirect_stdout(
            _io.StringIO()
        ) as sortie:
            faux._cache_diagnostic()
        ecrit = sortie.getvalue()
        self.assertIn(
            "504", ecrit, "le symptôme n'est pas rattaché à sa cause"
        )
        self.assertIn(
            cache_offline.restore_cmd(),
            ecrit,
            "le diagnostic constate sans donner le geste qui lève la coupure",
        )


class TestCeQueLeCacheDetient(unittest.TestCase):
    """Savoir AVANT de couper si une VM hors ligne a une chance.

    Une VM déployée hors ligne sur une suite que le cache n'a jamais servie
    échoue une heure plus tard, sur « Impossible de trouver le paquet » — un
    message qui ne parle ni du cache ni du hors ligne.
    """

    def _journal(self, lignes):
        import json
        import tempfile

        fh = tempfile.NamedTemporaryFile(
            "w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        for l in lignes:
            fh.write(json.dumps(l) + "\n")
        fh.close()
        return fh.name

    def test_le_nom_de_code_vient_du_catalogue(self):
        """Le recopier ici le ferait dériver du déploiement, qui l'a déjà."""
        self.assertEqual(
            cache_offline.jeton_de_suite("ubuntu", "26.04"),
            "/dists/resolute/",
        )
        self.assertEqual(
            cache_offline.jeton_de_suite("debian", "13"), "/dists/trixie/"
        )

    def test_aucun_verdict_hors_des_familles_apt(self):
        """« /repodata/ » ne dit pas quelle VERSION il sert : un cache rempli
        pour l'une passerait pour rempli pour toutes."""
        for d, v in (("arch", "latest"), ("fedora", "42"), ("rocky", "9")):
            self.assertEqual(cache_offline.jeton_de_suite(d, v), "", d)

    def test_une_suite_servie_est_vue_en_reserve(self):
        chemin = self._journal(
            [
                {
                    "url": "http://m/ubuntu/dists/resolute/InRelease",
                    "outcome": "stored",
                }
            ]
        )
        self.assertTrue(
            cache_offline.detient_la_suite("ubuntu", "26.04", chemin)
        )

    def test_une_suite_jamais_servie_est_signalee(self):
        chemin = self._journal(
            [
                {
                    "url": "http://m/ubuntu/dists/noble/InRelease",
                    "outcome": "stored",
                }
            ]
        )
        self.assertFalse(
            cache_offline.detient_la_suite("ubuntu", "26.04", chemin)
        )

    def test_un_304_ne_compte_pas_pour_une_reserve(self):
        """« fetched » couvre aussi la revalidation, qui n'a pas de corps :
        c'est exactement le cas qui laissait le cache vide."""
        chemin = self._journal(
            [
                {
                    "url": "http://m/ubuntu/dists/resolute/InRelease",
                    "outcome": "fetched",
                    "status": 304,
                }
            ]
        )
        self.assertFalse(
            cache_offline.detient_la_suite("ubuntu", "26.04", chemin)
        )

    def test_un_journal_illisible_ne_crie_pas_au_loup(self):
        """Un avertissement qui se déclenche sans savoir apprend à passer
        outre, et c'est alors celui qui compte qu'on ne lit plus."""
        self.assertTrue(
            cache_offline.detient_la_suite("ubuntu", "26.04", "/pas/la.jsonl")
        )

    def test_les_manquantes_sont_nommees_sans_doublon(self):
        chemin = self._journal(
            [
                {
                    "url": "http://m/ubuntu/dists/noble/InRelease",
                    "outcome": "hit",
                }
            ]
        )
        with mock.patch.object(
            cache_offline,
            "detient_la_suite",
            lambda d, v, c="": (d, v) == ("ubuntu", "24.04"),
        ):
            manquantes = cache_offline.suites_absentes(
                [
                    {"distro": "ubuntu", "version": "24.04"},
                    {"distro": "ubuntu", "version": "26.04"},
                    {"distro": "ubuntu", "version": "26.04"},
                    {"distro": "", "version": "x"},
                ]
            )
        self.assertEqual(manquantes, [("ubuntu", "26.04")])
        self.assertEqual(chemin, chemin)


class _SansSysteme:
    """Garde de CLASSE : aucune commande ne part vers l'hôte.

    Le code sous test pose et lève des règles de pare-feu et des unités
    systemd. Une régression qui contournerait un faux `_qemu_shell` les
    poserait pour de bon sur la machine de test ; l'espion les intercepte
    toutes et rend un échec.
    """

    def setUp(self):
        self.lancees = []

        def espion(cmd, *a, **kw):
            texte = cmd if isinstance(cmd, str) else " ".join(map(str, cmd))
            self.lancees.append(texte)
            return subprocess.CompletedProcess(cmd, 1, "", "")

        for cible in ("subprocess.run", "subprocess.Popen"):
            patch = mock.patch(cible, espion)
            patch.start()
            self.addCleanup(patch.stop)


class _FauxHote:
    """L'hôte vu par `_qemu_shell` : la table et le guet sont deux booléens.

    Chaque commande rendue par cache_offline y est reconnue à sa forme, et
    son effet simulé ; rien n'est exécuté.
    """

    def __init__(self, table=False, guet=False, retrait=True, lecture=True):
        self.table, self.guet = table, guet
        self.retrait, self.lecture = retrait, lecture
        self.ordre = []

    def shell(self, cmd, timeout=60):
        if "systemctl is-active" in cmd:
            return 0 if self.guet else 1
        if "nft list tables" in cmd:
            if not self.lecture:
                return 2
            return 0 if self.table else 1
        if "systemd-run" in cmd:
            self.ordre.append("guet")
            self.guet = True
            return 0
        if "nft -f -" in cmd:
            self.ordre.append("coupure")
            self.table = True
            return 0
        if "nft delete" in cmd:
            self.ordre.append("rebranchement")
            if self.retrait:
                self.table = False
            return 0
        self.ordre.append(f"? {cmd}")
        return 0


def _todo():
    sys.argv = ["todo.py"]
    from script.todo.todo import TODO

    return TODO.__new__(TODO)


def _joue_la_spec(
    hote, guet_pendant=False, reponse=None, hors_ligne=True, pendant=None
):
    """`_qemu_run_spec`, le déploiement remplacé par un faux.

    `guet_pendant` : le faux déploiement pose le guet, comme la voie suivie
    le fait après le lancement. `reponse` : ce que l'utilisateur tape si on
    lui pose une question ; None la rend interdite. `hors_ligne` : la case
    de la spec. `pendant(vu)` : appelé DANS le bloc, par le faux
    déploiement. Chaque commande passée à `_qemu_shell` est ajoutée à
    vu["lances"] ; le code d'un SystemExit sorti du bloc va dans
    vu["sortie"].
    """
    import contextlib
    import io

    todo = _todo()
    lances = []

    def shell(cmd, timeout=60):
        lances.append(cmd)
        return hote.shell(cmd, timeout)

    todo._qemu_shell = shell
    vu = {"lances": lances, "todo": todo}

    def deploie(spec, **kw):
        hote.ordre.append("déploiement")
        vu["kw"] = kw
        if guet_pendant:
            hote.shell(cache_offline.guet_cmd(["/srv/essai/vm-a.log"], "X"))
        if pendant:
            pendant(vu)

    todo._qemu_deploie_spec = deploie
    question = (
        mock.patch("builtins.input", return_value=reponse)
        if reponse is not None
        else mock.patch(
            "builtins.input",
            side_effect=AssertionError("question posée sans motif"),
        )
    )
    try:
        with question, contextlib.redirect_stdout(io.StringIO()) as sortie:
            todo._qemu_run_spec({"offline": hors_ligne})
    except SystemExit as fin:
        vu["sortie"] = fin.code
    vu["ecrit"] = sortie.getvalue()
    return vu


class TestLeGuetRendu(unittest.TestCase):
    """La levée confiée à root est une commande RENDUE : lue ici au
    caractère près, jamais lancée."""

    JOURNAUX = [
        "/srv/essai/journaux d'installation/vm-a.log",
        '/srv/essai/un "autre" dossier/vm b.log',
    ]
    MARQUEUR = "__FIN_ESSAI__"

    def _argv(self):
        import shlex

        return shlex.split(
            cache_offline.guet_cmd(self.JOURNAUX, self.MARQUEUR)
        )

    def _attente(self, argv):
        """Le script d'attente : l'argument qui suit « /bin/sh -c »."""
        debut = argv.index("/bin/sh")
        self.assertEqual(argv[debut + 1], "-c")
        return debut + 2

    def test_une_unite_nommee_posee_par_root(self):
        argv = self._argv()
        self.assertEqual(argv[:2], ["sudo", "systemd-run"])
        self.assertIn(f"--unit={cache_offline.UNITE_GUET}", argv)
        self.assertIn(
            "--collect", argv, "une unité en échec garderait son nom pris"
        )

    def test_elle_ne_vit_pas_plus_de_douze_heures(self):
        """Un marqueur qui ne vient jamais ne prive pas le cache d'amont
        indéfiniment."""
        argv = self._argv()
        self.assertEqual(cache_offline.DUREE_MAX_GUET, 12 * 3600)
        rang = argv.index("RuntimeMaxSec=43200")
        self.assertEqual(argv[rang - 1], "-p")

    def test_sa_fin_leve_la_table_de_la_coupure(self):
        """ExecStopPost court à la fin, au dépassement et à l'arrêt."""
        argv = self._argv()
        post = [a for a in argv if a.startswith("ExecStopPost=")]
        self.assertEqual(len(post), 1)
        self.assertEqual(argv[argv.index(post[0]) - 1], "-p")
        self.assertIn(f"nft delete table inet {cache_offline.TABLE} ", post[0])

    def test_lattente_couvre_chaque_journal_tel_quel(self):
        """Espaces, apostrophes et guillemets : les chemins voyagent en
        arguments et arrivent intacts, un par VM."""
        argv = self._argv()
        rang = self._attente(argv)
        self.assertEqual(argv[rang + 1], "sh")
        self.assertEqual(argv[rang + 2 :], self.JOURNAUX)
        script = argv[rang]
        self.assertIn('for f in "$@"', script)
        self.assertIn(self.MARQUEUR, script)
        self.assertNotIn("vm-a.log", script, "un chemin est dans le script")

    def test_rien_que_systemd_remplacerait(self):
        """systemd remplace « ${VAR} » et « $$ » dans ce qu'il exécute, et
        « % » dans ce qu'il lit d'une unité : le script tomberait en
        morceaux sans que rien ne le dise."""
        argv = self._argv()
        script = argv[self._attente(argv)]
        post = next(a for a in argv if a.startswith("ExecStopPost="))
        for texte in (script, post):
            for motif in ("${", "$$", "%"):
                self.assertNotIn(motif, texte)

    def test_la_commande_est_du_shell_valide(self):
        """« bash -n » lit sans exécuter."""
        argv = self._argv()
        for texte in (
            cache_offline.guet_cmd(self.JOURNAUX, self.MARQUEUR),
            argv[self._attente(argv)],
            cache_offline.table_posee_cmd(),
        ):
            res = subprocess.run(
                ["bash", "-n"], input=texte, text=True, capture_output=True
            )
            self.assertEqual(res.returncode, 0, res.stderr)

    def test_les_releves_et_la_levee_immediate(self):
        actif = cache_offline.guet_actif_cmd()
        self.assertIn("systemctl is-active --quiet", actif)
        self.assertIn(cache_offline.UNITE_GUET, actif)
        self.assertNotIn("sudo", actif, "lire un état n'a pas besoin de root")
        self.assertEqual(
            cache_offline.lever_maintenant_cmd(),
            f"sudo systemctl stop {cache_offline.UNITE_GUET}",
        )

    def test_une_lecture_ratee_nest_pas_une_absence(self):
        """« ! nft list table » conclurait à l'absence dès que sudo refuse,
        et un rebranchement raté se lirait comme réussi."""
        cmd = cache_offline.table_posee_cmd()
        self.assertIn("$(sudo nft list tables) || exit 2", cmd)
        self.assertIn(f"grep -qxF 'table inet {cache_offline.TABLE}'", cmd)
        self.assertNotIn("!", cmd)


class TestLaLeveeConfieeAuGuet(_SansSysteme, unittest.TestCase):
    """Sur la voie suivie, la levée part chez root APRÈS le lancement — les
    journaux existent alors — et AVANT le tableau de bord, qui prend le
    terminal : une invite de mot de passe n'y aurait nulle part où
    s'afficher."""

    def _suivi(self, guet, rc_guet=0):
        import contextlib
        import io
        import json
        import shlex
        import tempfile
        from pathlib import Path

        import script.todo.qemu_install_monitor as mon

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        journal = str(Path(tmp.name) / "journal d'essai" / "vm-a.log")
        vu = {"ordre": [], "guet": []}

        def lance(vms, branche, remote):
            vu["ordre"].append("lancement")
            Path(journal).parent.mkdir()
            Path(journal).write_text("", encoding="utf-8")
            manifeste = Path(tmp.name) / "session.json"
            manifeste.write_text(
                json.dumps({"vms": [{"name": "vm-a", "log": journal}]}),
                encoding="utf-8",
            )
            return str(manifeste)

        def shell(cmd, timeout=60):
            if "systemd-run" in cmd:
                vu["ordre"].append("guet")
                vu["guet"].append(shlex.split(cmd))
                return rc_guet
            vu["ordre"].append(f"? {cmd}")
            return 1

        todo = _todo()
        todo._qemu_shell = shell
        todo._qemu_import_module = lambda: None
        todo._qemu_erplibre_remote_cmd = lambda *a, **kw: "true"
        with mock.patch.object(
            mon, "launch_installs", lance
        ), mock.patch.object(
            mon, "run_monitor", lambda m: vu["ordre"].append("tableau")
        ), contextlib.redirect_stdout(
            io.StringIO()
        ) as sortie:
            todo._qemu_install_erplibre_monitored(
                ["vm-a"],
                "develop",
                {"vm-a": "192.0.2.10"},
                guet_hors_ligne=guet,
            )
        vu["ecrit"] = sortie.getvalue()
        vu["journal"] = journal
        return vu

    def test_le_guet_part_entre_le_lancement_et_le_tableau(self):
        vu = self._suivi(guet=True)
        self.assertEqual(vu["ordre"], ["lancement", "guet", "tableau"])
        self.assertEqual(
            vu["guet"][0][-1],
            vu["journal"],
            "le guet n'attend pas le journal du manifeste",
        )
        self.assertEqual(self.lancees, [])

    def test_sans_coupure_aucun_guet(self):
        vu = self._suivi(guet=False)
        self.assertEqual(vu["ordre"], ["lancement", "tableau"])

    def test_un_guet_refuse_le_dit_et_le_suivi_souvre_quand_meme(self):
        """La coupure reste alors au « finally » : fermer le tableau de bord
        avant la fin fait finir les installations en ligne, et on le dit."""
        from script.todo.todo_i18n import t

        vu = self._suivi(guet=True, rc_guet=1)
        self.assertEqual(vu["ordre"], ["lancement", "guet", "tableau"])
        self.assertIn(
            t("closes; closing it early finishes the installs online."),
            vu["ecrit"],
        )

    def test_la_spec_coupee_arme_le_guet_du_suivi(self):
        """Le drapeau vient du bloc de la coupure, pas d'une relecture de la
        spec : sans coupure posée, aucun guet."""
        import contextlib
        import io

        for hors_ligne in (True, False):
            with self.subTest(hors_ligne=hors_ligne):
                hote = _FauxHote()
                todo = _todo()
                todo._qemu_shell = hote.shell
                vus = []
                todo._qemu_install_erplibre_monitored = (
                    lambda *a, **kw: vus.append(kw)
                )
                todo._qemu_resolve_ips = lambda names, labels=None: {}
                with contextlib.redirect_stdout(io.StringIO()):
                    todo._qemu_run_spec(
                        {
                            "vms": [],
                            "existing": ["vm-a"],
                            "install": None,
                            "add_ssh_config": False,
                            "parallelism": 1,
                            "monitor": True,
                            "offline": hors_ligne,
                        }
                    )
                self.assertIs(vus[0]["guet_hors_ligne"], hors_ligne)
                self.assertIs(vus[0].get("hors_ligne"), hors_ligne)


class TestLeFinallyDuGuet(_SansSysteme, unittest.TestCase):
    """À la sortie du bloc : ne pas lever sous un guet actif, et ne dire
    « rebranché » que constaté."""

    def test_guet_actif_la_coupure_reste_et_le_geste_est_donne(self):
        """Les installations tournent encore, détachées : lever ici les ferait
        finir en ligne."""
        hote = _FauxHote()
        vu = _joue_la_spec(hote, guet_pendant=True)
        self.assertEqual(hote.ordre, ["coupure", "déploiement", "guet"])
        self.assertTrue(hote.table)
        self.assertIn(cache_offline.lever_maintenant_cmd(), vu["ecrit"])
        self.assertIn("12 h", vu["ecrit"])
        self.assertIs(vu["kw"]["coupee"], True)

    def test_sans_guet_le_finally_leve_et_constate(self):
        from script.todo.todo_i18n import t

        hote = _FauxHote()
        vu = _joue_la_spec(hote)
        self.assertEqual(
            hote.ordre, ["coupure", "déploiement", "rebranchement"]
        )
        self.assertFalse(hote.table)
        self.assertIn(t("Cache upstream restored."), vu["ecrit"])

    def test_un_retrait_refuse_ne_se_dit_pas_rebranche(self):
        """`restore_cmd` rend 0 même quand sudo refuse."""
        from script.todo.todo_i18n import t

        hote = _FauxHote(retrait=False)
        vu = _joue_la_spec(hote)
        self.assertNotIn(t("Cache upstream restored."), vu["ecrit"])
        self.assertIn(cache_offline.restore_cmd(), vu["ecrit"])

    def test_une_table_illisible_ne_se_dit_pas_rebranchee(self):
        from script.todo.todo_i18n import t

        hote = _FauxHote(lecture=False)
        vu = _joue_la_spec(hote)
        self.assertEqual(
            hote.ordre, ["coupure", "déploiement", "rebranchement"]
        )
        self.assertNotIn(t("Cache upstream restored."), vu["ecrit"])


class TestUneSecondeCoupure(_SansSysteme, unittest.TestCase):
    """La table est unique : deux coupures n'en font qu'une, et la première
    levée ôte les deux."""

    def test_un_guet_actif_refuse_tout(self):
        """Sa fin lèverait la coupure de ce déploiement en cours de route."""
        from script.todo.todo_i18n import t

        hote = _FauxHote(table=True, guet=True)
        vu = _joue_la_spec(hote)
        self.assertEqual(hote.ordre, [], "une seconde coupure a été posée")
        self.assertIn(
            t("An offline deployment is still running: the cut"), vu["ecrit"]
        )

    def test_un_guet_actif_refuse_meme_table_levee_a_la_main(self):
        hote = _FauxHote(table=False, guet=True)
        _joue_la_spec(hote)
        self.assertEqual(hote.ordre, [])

    def test_un_reste_sans_guet_se_demande_et_non_ne_deploie_rien(self):
        from script.todo.todo_i18n import t

        hote = _FauxHote(table=True)
        vu = _joue_la_spec(hote, reponse="n")
        self.assertEqual(hote.ordre, [])
        self.assertTrue(hote.table, "le reste a été levé sans accord")
        self.assertIn(t("Nothing deployed."), vu["ecrit"])

    def test_un_reste_leve_sur_accord_puis_la_coupure_suit(self):
        hote = _FauxHote(table=True)
        _joue_la_spec(hote, reponse="o")
        self.assertEqual(
            hote.ordre,
            ["rebranchement", "coupure", "déploiement", "rebranchement"],
        )

    def test_rien_nest_demande_quand_la_voie_est_libre(self):
        # `_joue_la_spec` sans réponse rend toute question fatale.
        hote = _FauxHote()
        _joue_la_spec(hote)
        self.assertEqual(hote.ordre[0], "coupure")


class TestUnCheminQueSystemdReecrirait(unittest.TestCase):
    """Le guet reçoit les chemins de journaux en arguments, que systemd
    réécrit quand ils portent « $ » ou « % » : le journal ne serait jamais
    trouvé et la coupure tiendrait douze heures. Un tel chemin ne part donc
    pas au guet, et la levée revient au « finally »."""

    def _confier(self, chemin_journal):
        import contextlib
        import io as _io
        import json
        import tempfile

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        lances = []
        todo._qemu_shell = lambda cmd, timeout=60: lances.append(cmd) or 0
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            json.dump({"vms": [{"log": chemin_journal}]}, fh)
            manifeste = fh.name
        with contextlib.redirect_stdout(_io.StringIO()):
            rendu = todo._qemu_confier_la_levee(manifeste)
        return rendu, lances

    def test_les_caracteres_reecrits_sont_refuses(self):
        self.assertTrue(cache_offline.chemins_surs(["/srv/run/vm-a.log"]))
        for piege in ("/srv/$HOME/vm.log", "/srv/run/%h.log", "/a/${X}/b"):
            self.assertFalse(cache_offline.chemins_surs([piege]), piege)

    def test_un_chemin_sur_part_au_guet(self):
        rendu, lances = self._confier("/srv/run/vm-a.log")
        self.assertTrue(rendu)
        self.assertTrue(any("systemd-run" in c for c in lances), lances)

    def test_un_chemin_reecrit_ne_part_pas_au_guet(self):
        rendu, lances = self._confier("/srv/run/$HOME/vm-a.log")
        self.assertFalse(rendu, "le guet a été posé sur un chemin réécrit")
        self.assertFalse(
            any("systemd-run" in c for c in lances),
            f"systemd-run a été lancé : {lances}",
        )


class TestLeGuetAttendLesJournauxQuiNExistentPasEncore(unittest.TestCase):
    """Le script du guet est EXÉCUTÉ ici, par un « sh » local : ni root, ni
    systemd, ni pare-feu. Le guet part juste après le lancement des
    installations ; un journal qui n'existe pas encore compté pour fini
    lèverait la coupure sur-le-champ, et l'installation finirait en ligne."""

    MARQUEUR = "__FIN_DE_TEST__"

    def _lancer(self, *journaux):
        import subprocess as sp

        script = cache_offline.script_attente(self.MARQUEUR, pas=1)
        proc = sp.Popen(["sh", "-c", script, "sh", *journaux])
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        return proc

    def _tmp(self):
        import tempfile

        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d, True))
        return d

    def test_un_journal_absent_nest_pas_fini(self):
        import os
        import time

        proc = self._lancer(os.path.join(self._tmp(), "pas-encore.log"))
        time.sleep(1.5)
        self.assertIsNone(
            proc.poll(), "le guet a rendu la main sur un journal absent"
        )

    def test_un_journal_fini_et_un_absent_attendent_encore(self):
        import os
        import time

        d = self._tmp()
        fini = os.path.join(d, "a.log")
        with open(fini, "w", encoding="utf-8") as fh:
            fh.write(f"installation\n{self.MARQUEUR} 0\n")
        proc = self._lancer(fini, os.path.join(d, "b.log"))
        time.sleep(1.5)
        self.assertIsNone(proc.poll())

    def test_le_guet_rend_la_main_quand_tous_sont_finis(self):
        import os
        import time

        d = self._tmp()
        a, b = os.path.join(d, "a.log"), os.path.join(d, "b.log")
        proc = self._lancer(a, b)
        time.sleep(0.3)
        for chemin in (a, b):
            with open(chemin, "w", encoding="utf-8") as fh:
                fh.write(f"installation\n{self.MARQUEUR} 2\n")
        self.assertEqual(proc.wait(timeout=5), 0)


def setUpModule():
    """Les sessions d'installation, et le verrou des déploiements hors ligne
    qui vit parmi elles, vont dans un répertoire temporaire : aucun test ne
    crée de fichier sous le répertoire personnel, et un déploiement réel en
    cours sur la machine de test ne tient pas le verrou des tests."""
    import tempfile

    import script.todo.qemu_install_monitor as mon

    sessions = tempfile.TemporaryDirectory()
    unittest.addModuleCleanup(sessions.cleanup)
    patch = mock.patch.object(mon, "session_dir", lambda: Path(sessions.name))
    patch.start()
    unittest.addModuleCleanup(patch.stop)


def _chemin_du_verrou():
    return _todo()._qemu_verrou_hors_ligne_chemin()


def _verrou_pris_ailleurs(test):
    """Prend le verrou comme le ferait un autre terminal : un second
    descripteur ouvert sur le même fichier, `flock` exclusif."""
    import fcntl
    import os

    fd = os.open(_chemin_du_verrou(), os.O_RDWR | os.O_CREAT, 0o600)
    test.addCleanup(os.close, fd)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _verrou_libre():
    """True si le verrou peut être pris maintenant ; il est aussitôt rendu."""
    import fcntl
    import os

    fd = os.open(_chemin_du_verrou(), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    finally:
        os.close(fd)
    return True


class TestUnDeploiementEnLigneSousLaCoupure(_SansSysteme, unittest.TestCase):
    """La table est partagée par tout le cache : un déploiement EN LIGNE
    lancé pendant qu'un autre la tient tournerait hors ligne. Il ne part
    pas en silence, et cette voie n'appelle jamais sudo."""

    def _sans_sudo(self, vu):
        for cmd in vu["lances"]:
            self.assertNotIn("sudo", cmd, "la voie en ligne a appelé sudo")

    def test_un_guet_actif_se_dit_et_non_ne_deploie_rien(self):
        from script.todo.todo_i18n import t

        hote = _FauxHote(table=True, guet=True)
        vu = _joue_la_spec(hote, reponse="n", hors_ligne=False)
        self.assertEqual(hote.ordre, [], "déployé sans accord")
        self.assertIn(
            t("This deployment would therefore run offline."), vu["ecrit"]
        )
        self.assertIn(cache_offline.lever_maintenant_cmd(), vu["ecrit"])
        self.assertIn("12 h", vu["ecrit"])
        self.assertIn(t("Nothing deployed."), vu["ecrit"])
        self._sans_sudo(vu)

    def test_sur_accord_il_part_sans_rien_couper_ni_lever(self):
        hote = _FauxHote(table=True, guet=True)
        vu = _joue_la_spec(hote, reponse="o", hors_ligne=False)
        self.assertEqual(hote.ordre, ["déploiement"])
        self.assertIs(vu["kw"]["coupee"], False)
        self.assertTrue(hote.table, "la coupure de l'autre a été levée")
        self._sans_sudo(vu)

    def test_sans_guet_ni_verrou_rien_nest_demande(self):
        # `_joue_la_spec` sans réponse rend toute question fatale.
        hote = _FauxHote()
        vu = _joue_la_spec(hote, hors_ligne=False)
        self.assertEqual(hote.ordre, ["déploiement"])
        self.assertEqual(vu["lances"], [cache_offline.guet_actif_cmd()])

    def test_un_deploiement_hors_ligne_qui_se_lance_se_dit_aussi(self):
        """Entre la coupure et le guet, seul le verrou témoigne : le guet ne
        part qu'au lancement des installations."""
        from script.todo.todo_i18n import t

        _verrou_pris_ailleurs(self)
        hote = _FauxHote(table=True)
        vu = _joue_la_spec(hote, reponse="n", hors_ligne=False)
        self.assertEqual(hote.ordre, [])
        self.assertIn(
            t("terminal: the cache upstream is cut until it ends."),
            vu["ecrit"],
        )
        self._sans_sudo(vu)

    def test_le_sondage_ne_cree_pas_le_fichier_du_verrou(self):
        # Le répertoire des sessions est commun au module : un test précédent
        # a pu y laisser le fichier.
        _chemin_du_verrou().unlink(missing_ok=True)
        hote = _FauxHote()
        _joue_la_spec(hote, hors_ligne=False)
        self.assertFalse(_chemin_du_verrou().exists())


class TestLeVerrouDesDeploiementsHorsLigne(_SansSysteme, unittest.TestCase):
    """Deux déploiements hors ligne lancés ensemble passeraient tous deux
    les relevés avant que l'un ait posé son guet : un verrou tient le bloc
    entier, relevés compris."""

    def test_un_verrou_tenu_refuse_avant_tout_releve(self):
        from script.todo.todo_i18n import t

        _verrou_pris_ailleurs(self)
        hote = _FauxHote()
        vu = _joue_la_spec(hote)
        self.assertEqual(vu["lances"], [], "un relevé a précédé le verrou")
        self.assertEqual(hote.ordre, [])
        self.assertIn(t("running in another terminal."), vu["ecrit"])
        self.assertIn(t("Nothing deployed."), vu["ecrit"])

    def test_tenu_pendant_le_bloc_et_rendu_apres(self):
        hote = _FauxHote()
        vu = _joue_la_spec(
            hote, pendant=lambda vu: vu.update(libre=_verrou_libre())
        )
        self.assertIs(vu["libre"], False, "le verrou n'est pas tenu")
        self.assertTrue(_verrou_libre(), "le verrou n'est pas rendu")

    def test_rendu_quand_la_coupure_est_refusee(self):
        hote = _FauxHote(guet=True)
        _joue_la_spec(hote)
        self.assertEqual(hote.ordre, [])
        self.assertTrue(_verrou_libre())


class TestLesSignauxPendantLaCoupure(_SansSysteme, unittest.TestCase):
    """SIGHUP et SIGTERM tuent sur place par défaut : un terminal fermé
    laisserait la coupure posée sans fin. Tant qu'elle est tenue, ils
    déroulent le « finally ». Aucun signal n'est envoyé au processus de
    test : le gestionnaire est relu et appelé directement."""

    SIGNAUX = ("SIGHUP", "SIGTERM")

    def setUp(self):
        import signal

        super().setUp()
        for nom in self.SIGNAUX:
            num = getattr(signal, nom)
            self.addCleanup(signal.signal, num, signal.getsignal(num))
            signal.signal(num, signal.SIG_DFL)

    @staticmethod
    def _releve(vu):
        import signal

        vu["pendant"] = {
            nom: signal.getsignal(getattr(signal, nom))
            for nom in ("SIGHUP", "SIGTERM")
        }

    def _rendus(self):
        import signal

        for nom in self.SIGNAUX:
            self.assertEqual(
                signal.getsignal(getattr(signal, nom)),
                signal.SIG_DFL,
                f"{nom} n'est pas rendu",
            )

    def test_le_premier_signal_sort_le_suivant_ne_coupe_pas_la_levee(self):
        import signal

        def pendant(vu):
            self._releve(vu)
            try:
                vu["pendant"]["SIGTERM"](signal.SIGTERM, None)
            except SystemExit as fin:
                vu["code"] = fin.code
            vu["second"] = vu["pendant"]["SIGHUP"](signal.SIGHUP, None)

        vu = _joue_la_spec(_FauxHote(), pendant=pendant)
        for nom in self.SIGNAUX:
            self.assertTrue(
                callable(vu["pendant"][nom]), f"{nom} non intercepté"
            )
        self.assertEqual(vu["code"], 128 + signal.SIGTERM)
        self.assertIsNone(vu["second"])
        self._rendus()

    def test_un_signal_dans_le_bloc_leve_la_coupure(self):
        import signal

        def pendant(vu):
            signal.getsignal(signal.SIGHUP)(signal.SIGHUP, None)

        hote = _FauxHote()
        vu = _joue_la_spec(hote, pendant=pendant)
        self.assertEqual(vu["sortie"], 128 + signal.SIGHUP)
        self.assertEqual(
            hote.ordre, ["coupure", "déploiement", "rebranchement"]
        )
        self.assertFalse(hote.table)
        self._rendus()
        self.assertTrue(_verrou_libre())

    def test_un_signal_pendant_la_commande_de_coupure_leve_quand_meme(self):
        """La table est posée, la commande n'a pas encore rendu la main :
        le signal reçu là doit trouver la levée sur son chemin."""
        import signal

        hote = _FauxHote()
        dessous = hote.shell

        def shell(cmd, timeout=60):
            rc = dessous(cmd, timeout)
            if cmd == cache_offline.cut_cmd():
                signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            return rc

        hote.shell = shell
        vu = _joue_la_spec(hote)
        self.assertEqual(vu["sortie"], 128 + signal.SIGTERM)
        self.assertEqual(hote.ordre, ["coupure", "rebranchement"])
        self.assertFalse(hote.table, "la coupure est restée posée")
        self._rendus()
        self.assertTrue(_verrou_libre())

    def test_une_coupure_refusee_nest_pas_levee(self):
        """Le sudo qui a refusé la coupure refuserait le retrait, et
        redemanderait un mot de passe pour rien."""
        from script.todo.todo_i18n import t

        hote = _FauxHote()
        dessous = hote.shell

        def shell(cmd, timeout=60):
            rc = dessous(cmd, timeout)
            return 1 if cmd == cache_offline.cut_cmd() else rc

        hote.shell = shell
        vu = _joue_la_spec(hote)
        self.assertEqual(hote.ordre, ["coupure"])
        self.assertIn(t("Upstream not cut: nothing deployed."), vu["ecrit"])
        self._rendus()
        self.assertTrue(_verrou_libre())

    def test_un_signal_ignore_le_reste(self):
        """Lancé sous « nohup », le déploiement survit à son terminal."""
        import signal

        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        vu = _joue_la_spec(_FauxHote(), pendant=self._releve)
        self.assertEqual(vu["pendant"]["SIGHUP"], signal.SIG_IGN)
        self.assertTrue(callable(vu["pendant"]["SIGTERM"]))
        self.assertEqual(signal.getsignal(signal.SIGHUP), signal.SIG_IGN)

    def test_en_ligne_aucun_gestionnaire_nest_pose(self):
        import signal

        vu = _joue_la_spec(_FauxHote(), hors_ligne=False, pendant=self._releve)
        self.assertEqual(
            vu["pendant"], {nom: signal.SIG_DFL for nom in self.SIGNAUX}
        )

    def test_hors_du_fil_principal_le_deploiement_passe(self):
        """`signal.signal` lève ValueError hors du fil principal."""
        import threading

        hote = _FauxHote()
        erreurs = []

        def fil():
            try:
                _joue_la_spec(hote)
            except BaseException as exc:  # noqa: B902
                erreurs.append(exc)

        fil_de_test = threading.Thread(target=fil)
        fil_de_test.start()
        fil_de_test.join(timeout=30)
        self.assertEqual(erreurs, [])
        self.assertEqual(
            hote.ordre, ["coupure", "déploiement", "rebranchement"]
        )
        self._rendus()


class TestLeDebutDuDeploiementDansLaSession(_SansSysteme, unittest.TestCase):
    """« deploy_started » ouvre la fenêtre du bilan hors ligne AVANT la
    création des VM : « started » n'est posé qu'après leur premier
    démarrage, quand cloud-init et l'agent invité ont déjà demandé."""

    VM = {
        "name": "vm-a",
        "ip": "192.0.2.10",
        "distro": "ubuntu",
        "version": "24.04",
        "arch": "amd64",
    }

    def _session(self, **kw):
        import json
        import tempfile

        import script.todo.qemu_install_monitor as mon

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.object(
            mon, "session_dir", lambda: Path(tmp.name)
        ), mock.patch.object(
            mon, "_launch_one", lambda *a, **k: None
        ), mock.patch.object(
            mon, "local_uuid", lambda nom: ""
        ):
            chemin = mon.launch_installs(
                [dict(self.VM)], "develop", "true", **kw
            )
        with open(chemin, encoding="utf-8") as fh:
            return json.load(fh)

    def test_ecrit_quand_il_est_donne(self):
        data = self._session(deploy_started=1234)
        self.assertEqual(data["deploy_started"], 1234.0)
        self.assertIsInstance(data["deploy_started"], float)
        self.assertIn("started", data)

    def test_absent_sinon(self):
        data = self._session()
        self.assertNotIn("deploy_started", data)
        self.assertNotIn("offline", data)
        self.assertIn("started", data)

    def test_le_hors_ligne_est_ecrit_quand_il_est_donne(self):
        """Seul un « offline » vrai permet au bilan de clore la lecture :
        les lignes d'amont muet naissent aussi en ligne."""
        for valeur in (True, False):
            with self.subTest(hors_ligne=valeur):
                data = self._session(hors_ligne=valeur)
                self.assertIs(data["offline"], valeur)

    def _suivi(self, **kw):
        import contextlib
        import io
        import json
        import tempfile

        import script.todo.qemu_install_monitor as mon

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        recus = []

        def lance(vms, branche, remote, **options):
            recus.append(options)
            manifeste = Path(tmp.name) / "session.json"
            manifeste.write_text(json.dumps({"vms": []}), encoding="utf-8")
            return str(manifeste)

        todo = _todo()
        todo._qemu_shell = lambda cmd, timeout=60: 1
        todo._qemu_import_module = lambda: None
        todo._qemu_erplibre_remote_cmd = lambda *a, **k: "true"
        with mock.patch.object(
            mon, "launch_installs", lance
        ), mock.patch.object(
            mon, "run_monitor", lambda m: None
        ), contextlib.redirect_stdout(
            io.StringIO()
        ):
            todo._qemu_install_erplibre_monitored(
                ["vm-a"], "develop", {"vm-a": "192.0.2.10"}, **kw
            )
        return recus

    def test_le_suivi_le_transmet_au_lanceur(self):
        self.assertEqual(
            self._suivi(deploy_started=1234.5), [{"deploy_started": 1234.5}]
        )

    def test_sans_valeur_le_lanceur_ne_recoit_rien_de_plus(self):
        self.assertEqual(self._suivi(), [{}])

    def test_le_suivi_transmet_le_hors_ligne(self):
        for valeur in (True, False):
            with self.subTest(hors_ligne=valeur):
                self.assertEqual(
                    self._suivi(hors_ligne=valeur), [{"hors_ligne": valeur}]
                )

    def test_la_spec_le_fournit(self):
        import contextlib
        import io
        import time

        todo = _todo()
        vus = []
        todo._qemu_install_erplibre_monitored = lambda *a, **k: vus.append(k)
        avant = time.time()
        with contextlib.redirect_stdout(io.StringIO()):
            todo._qemu_deploie_spec(
                {
                    "vms": [],
                    "existing": ["vm-a"],
                    "install": None,
                    "add_ssh_config": False,
                    "parallelism": 1,
                    "monitor": True,
                }
            )
        apres = time.time()
        self.assertLessEqual(avant, vus[0]["deploy_started"])
        self.assertLessEqual(vus[0]["deploy_started"], apres)
        self.assertIs(vus[0].get("hors_ligne"), False)


class TestLeSuiviDOfficeHorsLigne(_SansSysteme, unittest.TestCase):
    """Hors ligne, seule la voie suivie confie la levée au guet : sans elle,
    la voie synchrone n'a aucun guet, et une spec sans rien à installer
    lèverait la coupure dès les IP connues."""

    def _joue(self, spec):
        import contextlib
        import io

        todo = _todo()
        appels = []
        todo._qemu_install_erplibre_monitored = lambda *a, **k: appels.append(
            "suivi"
        )
        todo._qemu_install_erplibre_vm = lambda *a, **k: appels.append("muet")
        todo._qemu_resolve_ips = lambda names, labels=None: {}
        base = {
            "vms": [],
            "existing": ["vm-a"],
            "install": None,
            "add_ssh_config": False,
            "parallelism": 1,
        }
        base.update(spec)
        with contextlib.redirect_stdout(io.StringIO()):
            todo._qemu_deploie_spec(base)
        return appels

    INSTALL_MUETTE = {
        "branch": "develop",
        "prod": False,
        "cmd": "make x",
        "monitor": False,
    }

    def test_rien_a_installer_le_suivi_souvre_quand_meme(self):
        self.assertEqual(
            self._joue({"monitor": False, "offline": True}), ["suivi"]
        )
        self.assertEqual(self._joue({"monitor": False}), [])

    def test_une_install_sans_suivi_prend_la_voie_suivie(self):
        spec = {"monitor": False, "install": self.INSTALL_MUETTE}
        self.assertEqual(self._joue(dict(spec, offline=True)), ["suivi"])
        self.assertEqual(self._joue(spec), ["muet"])


if __name__ == "__main__":
    unittest.main()
