#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""L'entrée « cache QEMU » du menu Déploiement mène-t-elle où elle le dit ?

Le sous-menu est écrit deux fois — une liste de `prompt_description` qui
numérote l'affichage, et une chaîne d'`elif status == "N"` qui dispatche.
Insérer une entrée au milieu décale les deux, et une seule erreur envoie
l'opérateur dans un autre écran sans que rien ne proteste : l'entrée du cache
est arrivée en 8, ce qui a poussé le VPN en 9.

Le test vérifie aussi que chaque clé i18n de l'entrée résout DANS LES DEUX
LANGUES. Une clé absente rend sa propre chaîne anglaise, donc un menu
français qui affiche de l'anglais est le symptôme d'une clé oubliée, et rien
ne lève.
"""

import ast
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parent.parent
TODO_PY = RACINE / "script" / "todo" / "todo.py"
sys.path.insert(0, str(RACINE / "script" / "todo"))

import todo_i18n  # noqa: E402

# Les clés que l'entrée emploie. Les tenir ICI, et non les relire du code,
# fait échouer le test quand une clé disparaît du dictionnaire.
CLES = (
    "QEMU cache - Download mirror for local VMs",
    "QEMU download cache for local VMs",
    "Cache - Install or reinstall",
    "Cache - Diagnose: does it serve?",
    "Cache - Service state",
    "Cache - VMs kept out of the cache",
    "Cache - Git mirrors: fill them ahead",
    "Cache - Age and cleanup",
    "Cache - Guide: how it works",
    "Cache - Tests and performance report",
    "Install the download cache shared by the QEMU VMs of this host",
    "HTTP port of the cache (default: 8898): ",
    "TLS port of the cache (default: 8899): ",
    "Cache directory (default: /var/cache/erplibre_go_qemu_cache): ",
    "Will write network rules on the host bridge:",
    "Only what leaves the VM subnet is redirected",
    "The rules exist only while the service runs",
    "Go is absent; the installer lays it down",
    "Install the QEMU download cache?",
    "Installing the QEMU download cache (requires sudo)...",
    "QEMU download cache installed and started",
    "Certificate authority a VM must trust: ",
    "The cache install failed, nothing is started",
    "QEMU cache install script not found: ",
    "No eviction is written: this cache never shrinks by itself",
    # Le sous-menu du service : allumer, éteindre, lire.
    "State of the cache service",
    "Stopping it removes the rules: no VM is redirected.",
    "starts at boot",
    "not at boot",
    "Service - Start (start)",
    "Service - Start at boot (enable)",
    "Service - Do not start at boot (disable)",
    "Service - Stop (stop)",
    "Service - Detailed state (status)",
    "Service - Logs (log)",
    "Access log, last requests:",
    # Âge et nettoyage : ce qui occupe, depuis quand, et de quoi en rendre.
    "Age of the cache, and cleanup",
    "Age - By day",
    "Age - By week",
    "Age - By month",
    "Clean - What has not served for a while",
    "Clean - Everything",
    "Not served since (e.g. 30j, 12h)",
    "Erase what is listed above?",
    "Erase the whole cache?",
    # Les exceptions par adresse MAC : une VM soustraite au détournement.
    "VMs kept out of the download cache",
    "Exceptions - Remove the stale ones",
    "Exceptions - Remove one by its MAC",
    "No exception: every VM goes through the cache.",
    "MAC to give back to the cache",
    "VM gone",
    "Keep this VM out of the download cache",
    "Keep this VM out of the download cache? (y/N): ",
    # Combler ce qui a manqué hors ligne : l'entrée 9 et ses verdicts.
    "Cache - Fill what offline runs lacked",
    "What offline runs lacked",
    "Start it from entry 3 of this menu.",
    "A replay now would only record more misses.",
    "No offline miss in the recent window: nothing to fill.",
    "Everything that was missed is held now.",
    "according to the log: a purge can make it wrong",
    "replay through the cache",
    "never kept: the cache keeps only GET and HEAD",
    "the cache does not keep this address",
    "host in tunnel: nothing to keep",
    "git negotiation: fill the mirror from entry 5",
    "not a host name: a replay could loop back into the cache",
    "Nothing here can be replayed.",
    "The replay sends curl's own headers: a server that varies on",
    "User-Agent or Accept may keep another answer than the VM's.",
    "Replay these addresses through the cache now?",
    "held",
    "not held",
    "not re-checked: this binary has no --detient",
    "Tunnel refusals learned by the service:",
    "curl got no answer",
    # La coupure que le guet tient, et celle qu'on ne peut pas lire :
    # diagnostic et entrée 9.
    "Upstream CUT by an offline deployment still installing,",
    "held until its last installation ends (12 h at most).",
    "Lifting it now makes those installations finish online.",
    "Lift it now with:",
    "The lift watcher still runs, with no cut left to lift.",
    "Stop it with:",
    "Cannot tell whether the upstream is cut: reading nft needs a sudo"
    " password here.",
    "Under the cut, a replay would only record more misses.",
    "Replay anyway?",
)

CACHE_PY = RACINE / "script" / "todo" / "qemu_cache_menu.py"


def corps_de(nom, suivant):
    """Le corps d'une méthode de qemu_cache_menu.py, dispatch compris."""
    src = CACHE_PY.read_text(encoding="utf-8")
    debut = src.index(f"def {nom}(self):")
    return src[debut : src.index(f"def {suivant}(self", debut)]


def affichage_et_dispatch(corps):
    """Rend (nombre d'entrées affichées, numéros atteignables, triés).

    Un numéro s'atteint de deux façons : une branche « status == "N" », ou
    une entrée d'une table qui associe le numéro à un verbe. Ne compter que
    les branches ferait passer pour un trou ce qu'une table couvre.

    Le zéro sort : il ferme le menu et n'est jamais affiché.
    """
    affichees = len(re.findall(r'"prompt_description": t\(', corps))
    numeros = set(re.findall(r'if status == "(\d+)":', corps))
    # Toute table qui associe un numéro à quelque chose compte : le dispatch
    # passe tantôt par une branche, tantôt par une table de verbes ou de
    # granularités. N'en connaître qu'une ferait passer pour un trou ce
    # qu'une autre couvre.
    for table in re.findall(r"=\s*\{([^}]*)\}", corps):
        numeros |= set(re.findall(r'"(\d+)"\s*:', table))
    numeros.discard("0")
    return affichees, sorted(int(n) for n in numeros)


def corps_du_sous_menu():
    """Le corps de prompt_execute_deploy(), affichage et dispatch compris."""
    src = TODO_PY.read_text(encoding="utf-8")
    debut = src.index("def prompt_execute_deploy(self):")
    fin = src.index("def prompt_execute_deploy_ssh(self):", debut)
    return src[debut:fin]


class TestEntreeDuCache(unittest.TestCase):
    def setUp(self):
        self.corps = corps_du_sous_menu()

    def test_entree_affichee(self):
        self.assertIn(
            "QEMU cache - Download mirror for local VMs",
            self.corps,
            "l'entrée du cache ne s'affiche pas dans le menu Déploiement",
        )

    def test_entree_dispatchee(self):
        self.assertRegex(
            self.corps,
            r'elif status == "8":\s*\n\s*self\.prompt_execute_qemu_cache\(\)',
            "l'entrée 8 ne mène pas au sous-menu du cache",
        )

    def test_vpn_decale_en_neuf(self):
        """L'entrée insérée pousse le VPN : sans quoi deux entrées se
        partagent le numéro 8 et la seconde est inatteignable."""
        self.assertRegex(
            self.corps,
            r'elif status == "9":\s*\n\s*self\.prompt_execute_vpn\(\)',
            "le VPN n'a pas été décalé en 9",
        )

    def test_numeros_sans_trou_ni_doublon(self):
        numeros = [
            int(n) for n in re.findall(r'elif status == "(\d+)":', self.corps)
        ]
        self.assertEqual(
            numeros,
            sorted(numeros),
            f"les numéros du dispatch ne sont pas croissants : {numeros}",
        )
        self.assertEqual(
            len(numeros),
            len(set(numeros)),
            f"un numéro est dispatché deux fois : {numeros}",
        )
        self.assertEqual(
            numeros,
            list(range(1, len(numeros) + 1)),
            f"les numéros ne sont pas consécutifs à partir de 1 : {numeros}",
        )

    def test_methode_existe(self):
        src = TODO_PY.read_text(encoding="utf-8")
        self.assertIn(
            "def _deploy_qemu_cache(self):",
            src,
            "la méthode que le dispatch appelle n'existe pas",
        )


class TestSousMenusDuCache(unittest.TestCase):
    """Affichage et dispatch sont écrits deux fois, et rien ne les relie.

    La liste de `prompt_description` numérote l'écran ; la chaîne d'`elif
    status` décide où l'on va. Une entrée insérée au milieu de l'une sans
    l'autre envoie l'opérateur ailleurs qu'où il a lu, ou rend la dernière
    entrée inatteignable — dans les deux cas sans un mot d'erreur.
    """

    def verifier(self, nom, suivant, attendues):
        affichees, numeros = affichage_et_dispatch(corps_de(nom, suivant))
        self.assertEqual(
            affichees, attendues, f"{nom} n'affiche pas {attendues} entrées"
        )
        self.assertEqual(
            numeros,
            list(range(1, attendues + 1)),
            f"{nom} : le dispatch {numeros} ne suit pas l'affichage",
        )

    def test_le_menu_du_cache(self):
        self.verifier("prompt_execute_qemu_cache", "_cache_systemctl", 12)

    def test_le_menu_du_service(self):
        self.verifier("_cache_service", "_cache_journal_service", 6)

    def test_le_menu_des_exceptions(self):
        self.verifier("_cache_exceptions", "_cache_miroir_git", 2)

    def test_le_menu_des_miroirs(self):
        self.verifier("_cache_miroir_git", "_cache_miroir_remplir", 5)

    def test_le_menu_du_nettoyage(self):
        self.verifier("_cache_nettoyage_auto", "_cache_nettoyage_etat", 4)

    def test_le_menu_de_lage(self):
        self.verifier("_cache_age", "_cache_lancer", 5)

    def test_letat_du_service_est_la_troisieme(self):
        """Sous le diagnostic, comme demandé : le décalage du guide et des
        tests est la moitié du changement, et c'est celle qui casse."""
        corps = corps_de("prompt_execute_qemu_cache", "_cache_systemctl")
        for numero, methode in (
            ("3", "_cache_service"),
            ("4", "_cache_exceptions"),
            ("5", "_cache_miroir_git"),
            ("6", "_cache_age"),
            ("7", "_cache_guide"),
            ("8", "_cache_tests"),
            ("9", "_cache_combler"),
            ("10", "_cache_journaux"),
            ("11", "_cache_transfert"),
            ("12", "_cache_nettoyage_auto"),
        ):
            self.assertRegex(
                corps,
                rf'elif status == "{numero}":\s*\n\s*self\.{methode}\(\)',
                f"l'entrée {numero} ne mène pas à {methode}",
            )

    def test_les_quatre_verbes_systemd(self):
        """start, enable, disable et stop, et pas un cinquième par erreur."""
        corps = corps_de("_cache_service", "_cache_journal_service")
        verbes = re.search(r"verbes = \{([^}]*)\}", corps)
        self.assertIsNotNone(verbes, "la table des verbes a disparu")
        self.assertEqual(
            re.findall(r'"(\w+)"', verbes.group(1))[1::2],
            ["start", "enable", "disable", "stop"],
        )


class TestLeTransfertDuCache(unittest.TestCase):
    """Le magasin s'emporte ; les réglages restent.

    Un objet est rangé sous une clé tirée de l'URL, jamais de la machine qui
    l'a pris : il vaut donc ailleurs. Le pont, le sous-réseau et l'autorité,
    eux, appartiennent à l'hôte — emporter l'autorité ferait servir là-bas
    une signature dont aucune VM locale n'a la clé.
    """

    def _menu(self):
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        return TODO.__new__(TODO)

    def test_le_flux_va_dun_tar_a_lautre_sans_fichier_intermediaire(self):
        """Un magasin de dizaines de gigaoctets n'a pas à exister deux fois."""
        cmd = self._menu()._cache_transfert_cmd("op@ailleurs", "/var/cache/x")
        # Un chemin sans caractère spécial ressort tel quel : c'est la forme
        # RENDUE qu'on éprouve, pas celle qu'on imagine.
        self.assertIn("tar -C /var/cache/x -cf - .", cmd)
        self.assertIn("| zstd", cmd)
        self.assertIn("ssh op@ailleurs", cmd)
        self.assertIn("tar -C /var/cache/x -xf -", cmd)
        self.assertNotIn(">", cmd, "un fichier intermédiaire est écrit")

    def test_larrivee_rend_les_fichiers_au_compte_du_service(self):
        """Le même compte porte rarement le même numéro d'une machine à
        l'autre : sans ce « chown », le service ne lirait pas son magasin."""
        from script.qemu import cache_offline

        cmd = self._menu()._cache_transfert_cmd("op@ailleurs", "/var/cache/x")
        self.assertIn("--numeric-owner", cmd)
        self.assertIn(
            f"chown -R {cache_offline.SERVICE_USER}:"
            f"{cache_offline.SERVICE_USER}",
            cmd,
        )

    def test_une_cible_hostile_ne_secrit_pas_dans_la_commande(self):
        """Le nom vient d'une invite : une apostrophe y casserait la ligne,
        et le reste s'exécuterait sur CETTE machine."""
        import shlex

        mechant = "op@x'; rm -rf /; #"
        cmd = self._menu()._cache_transfert_cmd(mechant, "/var/c")
        # La preuve de l'échappement : le shell rend la cible en UN seul
        # argument, identique à ce qui a été tapé. Chercher le texte dangereux
        # dans la ligne ne prouverait rien — il y est, enfermé.
        mots = shlex.split(cmd[cmd.index("ssh ") :])
        self.assertEqual(mots[0], "ssh")
        self.assertEqual(mots[1], mechant)

    def test_larrivee_ne_demande_le_privilege_quune_fois(self):
        """Un ticket sudo se périme ; le transfert, lui, dure. En deux
        invocations, la seconde — le « chown » — tomberait après des
        dizaines de minutes sur une demande que plus rien ne peut saisir :
        le magasin serait posé, et illisible pour le compte qui le sert."""
        import shlex

        cmd = self._menu()._cache_transfert_cmd("op@ailleurs", "/var/cache/x")
        distant = shlex.split(cmd[cmd.index("ssh ") :])[2]
        self.assertEqual(distant.count("sudo "), 1, distant)
        self.assertIn("chown -R", distant)

    def test_le_premier_temps_ne_demande_aucun_privilege_a_larrivee(self):
        """C'est ce qui rend ce mode possible sans terminal : « cat » écrit
        dans le répertoire personnel du compte ssh, qui lui appartient. Un
        sudo à l'arrivée y ramènerait la panne qu'on contourne."""
        import shlex

        cmd = self._menu()._cache_envoi_fichier_cmd(
            "op@ailleurs", "/var/cache/x"
        )
        distant = shlex.split(cmd[cmd.index("ssh ") :])[2]
        self.assertNotIn("sudo", distant, distant)
        self.assertIn("cat > ~/", distant)

    def test_le_second_temps_extrait_rend_et_retire(self):
        """Trois gestes, dans cet ordre : extraire, rendre au compte du
        service, retirer le fichier. En oublier le dernier laisse le double
        de l'occupation sur une machine qui n'avait déjà que la place."""
        cmd = self._menu()._cache_finir_la_bas_cmd("/var/cache/x")
        self.assertIn("zstd -dc ~/", cmd)
        self.assertIn("tar -C /var/cache/x -xf -", cmd)
        self.assertIn("chown -R", cmd)
        self.assertIn("rm -f ~/", cmd)
        self.assertEqual(cmd.count("sudo "), 1, cmd)

    def test_les_reglages_ne_voyagent_pas(self):
        """Ni l'autorité, ni le pont, ni le sous-réseau."""
        cmd = self._menu()._cache_transfert_cmd("op@ailleurs", "/var/cache/x")
        for reste in ("ca.crt", "EL_BRIDGE", "EL_SUBNET", "/etc/"):
            self.assertNotIn(reste, cmd)


class TestCeQuOnDitQuandLArriveeNeSuitPas(unittest.TestCase):
    """Un refus doit nommer le geste qui le lève, et il n'est pas ici.

    L'entrée 1 pose le cache sur CETTE machine : y renvoyer fait réinstaller
    l'hôte qui en a déjà un, pendant que la machine d'arrivée reste sans
    rien. Trois situations appellent trois gestes — un lien ssh muet, un
    cache absent, un cache privé de son compte de service — et un code de
    retour unique les confondait sous un seul message.

    Les assertions portent sur des ancres qui ne se traduisent pas : une
    commande, un chemin, un nom de variable. Comparer du texte traduit
    ferait échouer le test au premier changement de langue.
    """

    def refus(self, code, sortie, confirmer=False, taille=0):
        """Exerce l'entrée avec une sonde truquée. Rend (texte, lancées)."""
        import contextlib
        import io

        from script.todo.todo import TODO

        lancees = []
        sondes = []

        class Faux(TODO):
            def __init__(self):
                self.execute = self

            def exec_command_live(self, cmd, **_kw):
                lancees.append(cmd)
                return 0

            def _cache_ssh(self, cible, commande, timeout=30):
                sondes.append(commande)
                return code, sortie

            # La taille du magasin se lit par « sudo du » sur des dizaines
            # de gigaoctets : le test la DONNE, sinon il mesurerait la
            # machine qui l'exécute et durerait le temps d'un parcours.
            def _cache_octets(self, chemin):
                return taille

        tampon = io.StringIO()
        with contextlib.ExitStack() as pile:
            pile.enter_context(
                mock.patch("click.prompt", return_value="op@ailleurs")
            )
            pile.enter_context(
                mock.patch("click.confirm", return_value=confirmer)
            )
            # Le cache local et ses réglages ne sont pas le sujet : le test
            # doit rendre le même verdict sur une machine qui n'en a pas.
            pile.enter_context(
                mock.patch(
                    "script.todo.qemu_cache_menu.os.path.isfile",
                    return_value=True,
                )
            )
            pile.enter_context(
                mock.patch(
                    "script.qemu.cache_offline.reglage",
                    return_value="/var/cache/x",
                )
            )
            pile.enter_context(contextlib.redirect_stdout(tampon))
            Faux()._cache_transfert()
        self.sondes = sondes
        return tampon.getvalue(), lancees

    def test_un_lien_ssh_muet_nest_pas_un_cache_absent(self):
        """Sans le jeton final, c'est la sonde qui n'a pas tourné : accuser
        le cache enverrait installer ce qui est peut-être déjà là."""
        texte, lancees = self.refus(255, "")
        self.assertIn("ssh-copy-id op@ailleurs", texte)
        self.assertNotIn("install_qemu_cache.sh", texte)
        self.assertEqual(lancees, [], "le magasin est parti malgré le refus")

    def test_un_ssh_qui_rend_zero_sans_rien_dire_compte_pour_muet(self):
        """La sonde se termine TOUJOURS par son jeton. Un canal qui rend 0
        sans lui ne l'a donc pas exécutée : l'état du cache de là-bas est
        inconnu, et l'annoncer absent serait inventer."""
        texte, lancees = self.refus(0, "")
        self.assertIn("ssh-copy-id op@ailleurs", texte)
        self.assertNotIn("install_qemu_cache.sh", texte)
        self.assertEqual(lancees, [])

    def test_un_cache_absent_donne_les_gestes_a_faire_la_bas(self):
        """Le geste est SUR l'arrivée, et l'installateur y meurt sans
        libvirt : les deux issues sont nommées, pas seulement la première."""
        texte, lancees = self.refus(0, "FIN\n")
        self.assertIn("1. ssh op@ailleurs", texte)
        self.assertIn("git fetch && git switch ", texte)
        self.assertIn("sudo bash script/install/install_qemu_cache.sh", texte)
        self.assertIn("systemctl start libvirtd.socket", texte)
        self.assertIn("net-start default", texte)
        self.assertIn("EL_BRIDGE=", texte)
        self.assertNotIn("ssh-copy-id", texte)
        self.assertEqual(lancees, [])

    def test_la_branche_nommee_est_celle_de_cet_hote(self):
        """L'installateur est un FICHIER du dépôt : une machine restée sur
        une branche qui ne le porte pas répond « fichier introuvable », ce
        qui ne ressemble en rien à un cache manquant et fait chercher la
        panne ailleurs. Le nom ne se devine donc pas, il se lit ici."""
        from script.todo.todo import TODO

        branche = TODO._cache_branche_ici()
        if not branche:
            self.skipTest("dépôt en tête détachée : aucune branche à nommer")
        texte, _lancees = self.refus(0, "FIN\n")
        self.assertIn(f"git switch {branche}", texte)

    def test_un_cache_sans_son_compte_se_dit_autrement(self):
        """Les fichiers arriveraient à root : le service ne les lirait pas.
        Ce n'est pas une absence de cache, et le remède n'est pas le même."""
        from script.qemu import cache_offline

        texte, lancees = self.refus(0, "binaire\nFIN\n")
        self.assertIn(cache_offline.SERVICE_USER, texte)
        self.assertIn("sudo bash script/install/install_qemu_cache.sh", texte)
        # Les lignes de libvirt appartiennent à l'autre cas : les voir ici
        # dirait de réparer un réseau qui n'est pour rien dans la panne.
        self.assertNotIn("libvirtd.socket", texte)
        self.assertEqual(lancees, [])

    def test_une_arrivee_complete_mene_a_la_commande(self):
        """La contre-épreuve : un jeton renommé ferait refuser une machine
        prête, et le refus ne se verrait que le jour du transfert."""
        texte, lancees = self.refus(0, "binaire\ncompte\nsudo\nFIN\n")
        self.assertIn("tar -C /var/cache/x -cf - .", texte)
        self.assertNotIn("install_qemu_cache.sh", texte)
        self.assertEqual(lancees, [], "la confirmation a été refusée")

    def test_un_sudo_qui_reclame_un_mot_de_passe_offre_les_deux_issues(self):
        """Le magasin occupe l'entrée standard de ssh, qui porte des octets
        et non un terminal : sudo refuse de lire un mot de passe ailleurs.
        Un ticket pris d'avance n'y peut rien — sudo l'attache au terminal
        qui l'a obtenu — donc les deux issues offertes sont d'élargir les
        droits une fois, ou de passer par un fichier que le compte
        d'arrivée écrit lui-même."""
        texte, lancees = self.refus(0, "binaire\ncompte\ncompte_ssh=op\nFIN\n")
        self.assertIn("NOPASSWD", texte)
        self.assertIn("/etc/sudoers.d/erplibre_cache", texte)
        self.assertIn("op ALL=(root)", texte, "le compte lu n'est pas repris")
        self.assertNotIn(
            "sudo -v", texte, "le ticket ne marche pas, ne pas le conseiller"
        )
        self.assertEqual(lancees, [])

    def test_la_place_manquante_ecarte_le_mode_en_deux_temps(self):
        """Le fichier et le magasin extrait coexistent : il faut DEUX fois
        la taille. L'annoncer après l'envoi laisserait une machine pleine
        et un magasin à moitié posé."""
        texte, lancees = self.refus(
            0,
            "binaire\ncompte\nplace_magasin=1000\nplace_compte=1000\nFIN\n",
            confirmer=True,
            taille=800,
        )
        self.assertIn("✗", texte)
        self.assertEqual(lancees, [], "l'envoi est parti malgré la place")

    def test_la_sonde_annonce_les_jetons_que_la_lecture_attend(self):
        """La sonde et sa lecture sont les deux moitiés d'un accord : en
        renommer un jeton d'un seul côté ferait refuser toute machine, et
        le refus ne se verrait qu'au moment d'emporter le magasin.

        Les autres épreuves truquent la sonde pour choisir la situation :
        aucune ne regarde ce qui part vraiment sur le lien. Celle-ci le
        lit."""
        from script.qemu import cache_offline
        from script.todo import qemu_cache_menu

        self.refus(0, "binaire\ncompte\nsudo\nFIN\n")
        sonde = self.sondes[0]
        for jeton in (
            "echo binaire",
            "echo compte",
            "sudo -n true",
            "echo sudo",
            "compte_ssh=",
            "place_magasin=",
            "place_compte=",
            "echo FIN",
        ):
            self.assertIn(jeton, sonde)
        self.assertIn(qemu_cache_menu.CACHE_BIN, sonde)
        self.assertIn(cache_offline.SERVICE_USER, sonde)


class TestLesEntreesDesMiroirsVisentLeurListe(unittest.TestCase):
    """Chaque entrée de remplissage passe SA liste, et pas une voisine.

    La base, l'extra et le remplissage complet partagent tout — l'en-tête,
    la confirmation, la commande — sauf la liste qu'ils transmettent. Une
    entrée « extra » qui passerait la base remplirait des dépôts déjà
    complets et laisserait ceux qui manquent, sans que rien à l'écran ne le
    trahisse : la commande affichée a la même forme dans les deux cas.
    """

    def remplir(self, choix):
        """Pilote le sous-menu. Rend la liste reçue par le remplissage."""
        import contextlib
        import io

        from script.todo.todo import TODO

        vu = {}

        class Faux(TODO):
            def __init__(self):
                pass

            def _cache_miroir_occupation(self):
                return 0, "0 o"

            def _cache_place_libre(self):
                return "?"

            def fill_help_info(self, choices):
                return ""

            def _cache_miroir_remplir(self, liste):
                vu["liste"] = list(liste)

        reponses = iter([choix, "0"])
        with contextlib.ExitStack() as pile:
            pile.enter_context(
                mock.patch(
                    "click.prompt", side_effect=lambda *a, **k: next(reponses)
                )
            )
            # Le binaire installé et l'état des miroirs ne sont pas le sujet :
            # le verdict doit tenir sur une machine qui n'a ni l'un ni l'autre.
            pile.enter_context(
                mock.patch(
                    "script.todo.qemu_cache_menu.os.path.isfile",
                    return_value=True,
                )
            )
            pile.enter_context(
                mock.patch(
                    "script.qemu.cache_offline.miroirs_absents",
                    return_value=[],
                )
            )
            pile.enter_context(contextlib.redirect_stdout(io.StringIO()))
            Faux()._cache_miroir_git()
        return vu.get("liste")

    def version(self):
        from script.todo.qemu_cache_menu import version_active

        v = version_active(str(RACINE))
        if not v:
            self.skipTest("aucune version d'Odoo active dans ce checkout")
        return v

    def test_lentree_base_passe_la_base(self):
        from script.todo.qemu_cache_menu import depots_des_manifestes

        v = self.version()
        self.assertEqual(
            self.remplir("1"), depots_des_manifestes(str(RACINE), v)
        )

    def test_lentree_extra_passe_lextra(self):
        from script.todo.qemu_cache_menu import (
            depots_des_manifestes,
            manifeste_extra,
        )

        v = self.version()
        extra = depots_des_manifestes(
            str(RACINE), fichiers=[manifeste_extra(v)]
        )
        if not extra:
            self.skipTest(f"aucun manifeste extra pour {v}")
        self.assertEqual(self.remplir("2"), extra)

    def test_lentree_complete_passe_tous_les_manifestes(self):
        from script.todo.qemu_cache_menu import depots_des_manifestes

        self.assertEqual(self.remplir("3"), depots_des_manifestes(str(RACINE)))


class TestLesIconesDeLAssistant(unittest.TestCase):
    """Chaque choix de l'assistant porte une icône, système compris.

    Les icônes des systèmes vivent dans le menu et non dans `distro_label`,
    qui sert aussi aux formulaires de déploiement et aux journaux. Une
    distribution ajoutée au catalogue sans icône retomberait sur l'icône de
    repli sans que rien ne le dise : c'est ce que ces épreuves surveillent.
    """

    def test_chaque_systeme_mesurable_a_son_icone(self):
        from script.todo.qemu_cache_menu import QemuCacheMenuMixin as M

        module = M._cache_module_test()
        sans = sorted(
            set(module.systemes_mesurables()) - set(M._CACHE_ICONES_SYSTEMES)
        )
        self.assertEqual(sans, [], f"systèmes sans icône : {sans}")

    def test_le_libelle_du_catalogue_reste_intact(self):
        """L'icône précède le libellé, elle ne le remplace pas."""
        from script.todo.qemu_cache_menu import QemuCacheMenuMixin as M

        module = M._cache_module_test()
        for distro, libelle in M._cache_systemes():
            self.assertEqual(
                libelle,
                f"{M._CACHE_ICONES_SYSTEMES[distro]}"
                f" {module.distro_label(distro, module.DISTROS[distro][1])}",
            )

    def test_les_essais_et_les_charges_portent_une_icone(self):
        from script.todo.qemu_cache_menu import QemuCacheMenuMixin as M

        cles = [e[1] for e in M._CACHE_ESSAIS] + [
            c[1] for c in M._CACHE_CHARGES
        ]
        cles.append("All three, one after another")
        for cle in cles:
            for langue in ("fr", "en"):
                valeur = todo_i18n.TRANSLATIONS[cle][langue]
                self.assertFalse(
                    valeur[0].isalnum(), f"« {cle} » ({langue}) sans icône"
                )


class TestLAssistantDesTests(unittest.TestCase):
    """Trois questions — quel essai, quelle charge, quel système — puis les
    essais choisis, l'un après l'autre.

    Deux propriétés que rien d'autre ne tient. « Les trois » doit lancer TROIS
    commandes, chacune portant le système et la charge choisis : en oublier un
    ferait mesurer autre chose que ce qui a été demandé, sans rien dire. Et la
    confirmation porte sur le LOT : la reposer à chaque essai la rendrait
    machinale, ce qui est exactement ce qui fait qu'on cesse de la lire.
    """

    def assistant(self, reponses):
        from script.todo.todo import TODO

        lancees = []

        class Faux(TODO):
            def __init__(self):
                self.execute = self

            def exec_command_live(self, cmd, **_kw):
                lancees.append(cmd)

        it = iter(reponses)
        # « click.confirm » et « longtest_menu.click.confirm » sont le MÊME
        # objet : un seul mock les couvre, et c'est ce qui rend le compte
        # d'appels lisible — une question en tout, pas une par essai.
        with mock.patch(
            "click.prompt", side_effect=lambda *a, **k: next(it)
        ), mock.patch("click.confirm", return_value=True) as confirme:
            Faux()._cache_assistant()
        return lancees, confirme

    def test_les_trois_lancent_trois_commandes(self):
        lancees, _c = self.assistant(["4", "1", "2"])
        self.assertEqual(len(lancees), 3, f"lancées : {lancees}")
        options = {"", "--hors-ligne", "--sans-cache"}
        for attendu in options:
            self.assertTrue(
                any(c.rstrip().endswith(attendu) for c in lancees)
                or attendu == "",
                f"« {attendu} » n'a pas été lancé : {lancees}",
            )

    def test_le_systeme_et_la_charge_suivent_chaque_essai(self):
        lancees, _c = self.assistant(["4", "2", "3"])
        for cmd in lancees:
            self.assertIn("--distro debian", cmd)
            self.assertIn("--charge erplibre", cmd)

    def test_un_seul_essai_ne_lance_que_lui(self):
        lancees, _c = self.assistant(["3", "1", "2"])
        self.assertEqual(len(lancees), 1)
        self.assertIn("--sans-cache", lancees[0])

    def test_une_seule_question_pour_tout_le_lot(self):
        """Trois essais, une question. La reposer à chaque essai la rendrait
        machinale, ce qui est exactement ce qui fait qu'on cesse de la lire."""
        lancees, confirme = self.assistant(["4", "1", "2"])
        self.assertEqual(len(lancees), 3)
        self.assertEqual(
            confirme.call_count,
            1,
            f"{confirme.call_count} confirmations pour trois essais",
        )

    def test_renoncer_ne_lance_rien(self):
        for reponses in (["0"], ["4", "0"], ["4", "1", "0"]):
            lancees, _c = self.assistant(reponses)
            self.assertEqual(lancees, [], f"réponses {reponses}")


class TestToutesLesClesDuFichier(unittest.TestCase):
    """La liste CLES est tenue à la main, donc elle oublie.

    Ce contrôle-ci ne tient aucune liste : il relève par l'ARBRE tout appel
    « t("…") » du module et vérifie que le dictionnaire répond. Une clé
    absente ne lève pas — t() rend sa propre chaîne anglaise — et le symptôme
    est un menu français qui affiche une ligne en anglais, ce qu'aucun test de
    numérotation ne voit.
    """

    def test_chaque_appel_a_sa_traduction(self):
        arbre = ast.parse(CACHE_PY.read_text(encoding="utf-8"))
        cles = {
            n.args[0].value
            for n in ast.walk(arbre)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "t"
            and n.args
            and isinstance(n.args[0], ast.Constant)
            and isinstance(n.args[0].value, str)
        }
        self.assertGreater(len(cles), 50, "le relevé n'a presque rien trouvé")
        manquantes = sorted(c for c in cles if c not in todo_i18n.TRANSLATIONS)
        self.assertEqual(
            manquantes,
            [],
            "clés employées mais absentes du dictionnaire — le menu français"
            f" affichera l'anglais : {manquantes}",
        )


class TestClesI18n(unittest.TestCase):
    def test_cles_presentes(self):
        manquantes = [c for c in CLES if c not in todo_i18n.TRANSLATIONS]
        self.assertEqual(
            manquantes, [], f"clés absentes du dictionnaire : {manquantes}"
        )

    def test_les_deux_langues_repondent(self):
        for cle in CLES:
            entree = todo_i18n.TRANSLATIONS[cle]
            for langue in ("fr", "en"):
                self.assertIn(langue, entree, f"« {cle} » n'a pas de {langue}")
                self.assertTrue(
                    entree[langue].strip(),
                    f"« {cle} » a un {langue} vide",
                )

    def test_le_francais_est_traduit(self):
        """Une valeur française identique à l'anglaise trahit une clé posée
        sans traduction. Les libellés purement techniques y échappent."""
        sans_traduction = [
            c
            for c in CLES
            if todo_i18n.TRANSLATIONS[c]["fr"]
            == todo_i18n.TRANSLATIONS[c]["en"]
        ]
        self.assertEqual(
            sans_traduction, [], f"non traduites : {sans_traduction}"
        )

    def test_icones_des_entrees(self):
        """L'icône vit DANS la chaîne traduite, comme partout ailleurs dans le
        menu : les deux langues doivent donc la porter."""
        attendues = {
            "QEMU cache - Download mirror for local VMs": "📦",
            "Cache - Install or reinstall": "📥",
            "Cache - Diagnose: does it serve?": "🔍",
            "Cache - Service state": "⚙",
            "Cache - VMs kept out of the cache": "🎫",
            "Cache - Git mirrors: fill them ahead": "🪞",
            "Cache - Age and cleanup": "🧭",
            "Age - By day": "📅",
            "Clean - Everything": "🔥",
            "Cache - Guide: how it works": "📖",
            "Exceptions - Remove the stale ones": "🧹",
            "Exceptions - Remove one by its MAC": "✂",
            "Service - Start (start)": "▶",
            "Service - Start at boot (enable)": "🔗",
            "Service - Do not start at boot (disable)": "🚫",
            "Service - Stop (stop)": "⏹",
            "Service - Detailed state (status)": "📋",
            "Service - Logs (log)": "📜",
            "Cache - Tests and performance report": "🧪",
            "Cache - Fill what offline runs lacked": "🩹",
        }
        for cle, icone in attendues.items():
            entree = todo_i18n.TRANSLATIONS[cle]
            for langue in ("fr", "en"):
                self.assertTrue(
                    entree[langue].startswith(icone),
                    f"« {cle} » en {langue} ne porte pas {icone} :"
                    f" {entree[langue]}",
                )

    def test_aucune_cle_en_double(self):
        """Une clé en double écrase silencieusement la précédente."""
        src = (RACINE / "script" / "todo" / "todo_i18n.py").read_text(
            encoding="utf-8"
        )
        for cle in CLES:
            litteral = '    "%s": {' % cle.replace('"', '\\"')
            self.assertEqual(
                src.count(litteral),
                1,
                f"« {cle} » apparaît {src.count(litteral)} fois",
            )


class TestLesIssuesDuJournalSontToutesMontrees(unittest.TestCase):
    """Le diagnostic répond « le cache sert-il ? » : il ne peut rien taire.

    La version d'avant écrivait cinq issues en dur. Deux sont apparues depuis —
    le tunnel opaque et le miroir git — et l'écran les taisait, alors que le
    miroir portait à lui seul le tiers des lignes du journal. Une liste fermée
    dérive dès qu'on ne la relit pas.

    Ce contrôle lit les issues que le CACHE définit, en Go, et exige que
    l'ordre d'affichage les nomme toutes.
    """

    def issues_du_cache(self):
        src = (RACINE / "script" / "qemu_cache" / "proxy.go").read_text(
            encoding="utf-8"
        )
        bloc = src[
            src.index("Outcome") : src.index("\n)", src.index("Outcome"))
        ]
        return set(re.findall(r'Outcome\w+\s*=\s*"([a-z-]+)"', bloc))

    def test_lordre_nomme_toutes_les_issues(self):
        from script.todo.qemu_cache_menu import ORDRE_ISSUES

        issues = self.issues_du_cache()
        self.assertGreaterEqual(len(issues), 6, "le relevé n'a rien trouvé")
        manquantes = sorted(issues - set(ORDRE_ISSUES))
        self.assertEqual(
            manquantes,
            [],
            "des issues du journal ne seraient pas montrées à leur rang :"
            f" {manquantes}",
        )

    def test_le_diagnostic_ne_filtre_pas_sur_cet_ordre(self):
        """Une issue inconnue de l'ordre doit quand même paraître : c'est ce
        qui empêche la liste de retaire quelque chose un jour."""
        src = (RACINE / "script" / "todo" / "qemu_cache_menu.py").read_text(
            encoding="utf-8"
        )
        bloc = src[src.index("def _cache_diagnostic") :]
        bloc = bloc[: bloc.index("\n    @")]
        self.assertIn("set(compte) - set(ORDRE_ISSUES)", bloc)

    def test_les_objets_de_statut_suivent_stale(self):
        """Une redirection ou un refus gardés se lisent à côté de ce qui a
        été gardé puis resservi, et non à la fin parmi les inconnues."""
        from script.todo.qemu_cache_menu import ORDRE_ISSUES

        rang = ORDRE_ISSUES.index("stale")
        self.assertEqual(
            ORDRE_ISSUES[rang + 1 : rang + 3],
            ("stored-status", "stale-status"),
        )


class TestCeQueChaqueMachineATire(unittest.TestCase):
    """Un doute sur l'accélération ne s'instruit pas sur un total.

    Le journal disait ce que le cache avait fait, jamais POUR QUI. On ne
    pouvait donc pas séparer ce qu'une VM a tiré du réseau de ce qu'une autre a
    été servie du disque — et répondre demandait d'aller lire le journal à la
    main, hors de l'outil.
    """

    def journal(self, lignes):
        import json as _json
        import tempfile

        f = tempfile.NamedTemporaryFile(
            "w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        for l in lignes:
            f.write(_json.dumps(l) + "\n")
        f.close()
        self.addCleanup(lambda: Path(f.name).unlink(missing_ok=True))
        return f.name

    def par_machine(self, lignes, **kw):
        from script.todo.qemu_cache_menu import QemuCacheMenuMixin as M

        chemin = self.journal(lignes)
        with mock.patch.object(M, "_cache_journal", return_value=chemin):
            return M._cache_par_machine(**kw)

    def test_le_disque_et_lamont_sont_separes(self):
        got = self.par_machine(
            [
                {"client": "10.0.0.1", "bytes": 100, "upstream": True},
                {"client": "10.0.0.1", "bytes": 900, "upstream": False},
                {"client": "10.0.0.2", "bytes": 50, "upstream": True},
            ]
        )
        self.assertEqual(
            dict(got), {"10.0.0.1": (900, 100), "10.0.0.2": (0, 50)}
        )

    def test_les_plus_gros_dabord(self):
        """C'est la machine qui a le plus consommé qu'on cherche."""
        got = self.par_machine(
            [
                {"client": "petit", "bytes": 10, "upstream": False},
                {"client": "gros", "bytes": 10000, "upstream": False},
                {"client": "moyen", "bytes": 500, "upstream": True},
            ]
        )
        self.assertEqual([a for a, _ in got], ["gros", "moyen", "petit"])

    def test_une_ligne_sans_client_est_ecartee(self):
        """Le journal d'avant n'avait pas ce champ : ranger ses lignes sous un
        nom inventé donnerait un relevé faux, pas un relevé incomplet."""
        got = self.par_machine(
            [
                {"bytes": 5000, "upstream": True},
                {"client": "10.0.0.1", "bytes": 7, "upstream": False},
            ]
        )
        self.assertEqual(dict(got), {"10.0.0.1": (7, 0)})

    def test_la_liste_est_bornee(self):
        got = self.par_machine(
            [
                {"client": f"10.0.0.{i}", "bytes": i, "upstream": False}
                for i in range(1, 30)
            ],
            limite=3,
        )
        self.assertEqual(len(got), 3)

    def test_un_journal_absent_ne_casse_pas(self):
        from script.todo.qemu_cache_menu import QemuCacheMenuMixin as M

        with mock.patch.object(M, "_cache_journal", return_value=""):
            self.assertEqual(M._cache_par_machine(), [])
        with mock.patch.object(
            M, "_cache_journal", return_value="/nexiste/pas.jsonl"
        ):
            self.assertEqual(M._cache_par_machine(), [])

    def test_le_cache_note_le_client(self):
        """L'autre moitié : le service doit écrire le champ que ceci lit."""
        src = (RACINE / "script" / "qemu_cache" / "proxy.go").read_text(
            encoding="utf-8"
        )
        self.assertIn('Client string `json:"client,omitempty"`', src)
        self.assertGreaterEqual(
            src.count("Client: clientDe(") + src.count("Client: client,"),
            4,
            "un chemin du journal n'écrit pas le client",
        )


class TestLesReglagesDuNettoyage(unittest.TestCase):
    """Une valeur que le binaire ne lirait pas ferait échouer le minuteur chaque
    nuit, sans que personne ne regarde son journal : elle est refusée ici."""

    def test_les_delais_que_le_binaire_lit(self):
        from script.todo.qemu_cache_menu import reglage_age_valide

        for v in ("90j", "30d", "12h", "1h30m", "0.5j"):
            self.assertTrue(reglage_age_valide(v), v)
        for v in ("", "90", "jour", "0j", "-3j", "90j; rm -rf /"):
            self.assertFalse(reglage_age_valide(v), v)

    def test_les_tailles_que_le_binaire_lit(self):
        from script.todo.qemu_cache_menu import reglage_taille_valide

        for v in ("50G", "50Gio", "500M", "1.5 T", "1024"):
            self.assertTrue(reglage_taille_valide(v), v)
        for v in ("", "0G", "G", "50X", "50G|x"):
            self.assertFalse(reglage_taille_valide(v), v)

    def ecrire(self, contenu, cle, valeur):
        import shlex
        import subprocess
        import tempfile

        from script.todo.qemu_cache_menu import commande_ecrire_reglage

        with tempfile.NamedTemporaryFile(
            "w", delete=False, suffix=".env"
        ) as fh:
            fh.write(contenu)
            chemin = fh.name
        cmd = commande_ecrire_reglage(cle, valeur, chemin)
        self.assertTrue(cmd.startswith("sudo sh -c "))
        script = shlex.split(cmd[len("sudo ") :])[2]
        subprocess.run(["sh", "-c", script], check=True)
        with open(chemin, encoding="utf-8") as fh:
            return fh.read()

    def test_une_ligne_existante_est_remplacee(self):
        rendu = self.ecrire(
            "EL_LANG=fr\nEL_PURGE_AGE=30j\n", "EL_PURGE_AGE", "90j"
        )
        self.assertEqual(rendu, "EL_LANG=fr\nEL_PURGE_AGE=90j\n")

    def test_une_ligne_absente_est_ajoutee(self):
        rendu = self.ecrire("EL_LANG=fr\n", "EL_MAX_SIZE", "50G")
        self.assertEqual(rendu, "EL_LANG=fr\nEL_MAX_SIZE=50G\n")

    def test_une_valeur_vide_desactive(self):
        rendu = self.ecrire("EL_MAX_SIZE=50G\n", "EL_MAX_SIZE", "")
        self.assertEqual(rendu, "EL_MAX_SIZE=\n")

    def test_sans_reglage_rien_n_est_lance(self):
        import contextlib
        import io
        from unittest import mock

        from script.todo import qemu_cache_menu as menu

        faux = menu.QemuCacheMenuMixin.__new__(menu.QemuCacheMenuMixin)
        faux.execute = mock.MagicMock()
        with mock.patch.object(
            menu.cache_offline, "reglage", return_value=""
        ), contextlib.redirect_stdout(io.StringIO()):
            for a_blanc in (True, False):
                faux._cache_nettoyage_lancer(a_blanc=a_blanc)
        faux.execute.exec_command_live.assert_not_called()


if __name__ == "__main__":
    unittest.main()
