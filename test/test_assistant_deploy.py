#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Une installation déjà là n'est jamais écrasée, et rien ne nomme la cible.

Ce que ces tests défendent est le mode de défaillance le plus cher de la
fonctionnalité : poser un ERPLibre sur un chemin qui en porte déjà un. La
pose clone ou recopie par-dessus, et ce qui s'y trouvait est perdu sans que
rien ne lève. Deux règles l'empêchent, et les deux se testent ici.

Le chemin est sondé AVANT toute écriture, et CE QUI N'A PAS ÉTÉ LU COMPTE
POUR OCCUPÉ. Une sortie vide se produit aussi bien sur un hôte injoignable
que sur une clé refusée ou un lien coupé, et aucun de ces cas ne prouve que
le chemin est libre. Traiter le silence comme une autorisation d'écrire est
la régression que `JETON` existe pour empêcher.

Six marqueurs, parce qu'aucun n'est là dans tous les cas : un arbre poussé
par rsync n'a pas de dépôt, un clone frais n'a pas les fichiers de version —
ils se génèrent à l'installation —, et une pose interrompue n'a ni l'un ni
l'autre. Réduire la liste à `.git` rendrait « rien là » sur une installation
vivante.

Le shell fabriqué est éprouvé par `bash -n` : une suite mal groupée
installerait après un clone échoué, et « cmd && a; b » ne lie que son
premier maillon.

Enfin, rien de ce qui désigne une machine ne sort : `resume` rend une
poignée, et le détecteur du dépôt ne voit passer ni un alias SSH ni un chemin
sans nom de compte.

Les valeurs sont INVENTÉES, comme `.claude/rules/04-code-conventions.md`
l'exige, et vérifiées absentes du reste du dépôt.
"""

import os
import subprocess
import sys
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.todo.assistant import deploy  # noqa: E402
from script.todo.todo_i18n import TRANSLATIONS  # noqa: E402

# Un alias, un chemin et une adresse qui ne désignent rien.
ALIAS = "atelier-nord"
CHEMIN = "/srv/fonderie/erplibre"
DEPOT = "https://exemple.invalid/erplibre.git"
MAKE = "install_odoo_18"


def une_cible(**changes):
    champs = {"handle": "cible-1", "alias": ALIAS, "path": CHEMIN}
    champs.update(changes)
    return deploy.Cible(**champs)


def parse(bloc):
    """Le bloc passe-t-il `bash -n` ? Rend (code, erreur)."""
    res = subprocess.run(
        ["bash", "-n"], input=bloc, text=True, capture_output=True
    )
    return res.returncode, res.stderr.strip()


class LeRefusDEcraser(unittest.TestCase):
    def test_chaque_marqueur_suffit_seul_a_refuser(self):
        """Aucun marqueur n'est présent dans tous les cas : chacun doit
        refuser à lui seul, sans quoi une installation poussée par rsync —
        qui n'a pas de dépôt — se lirait comme un chemin libre."""
        for marqueur in deploy.MARQUEURS:
            with self.subTest(marqueur):
                attendu = os.path.join(CHEMIN, marqueur)
                etat = deploy.etat_local(
                    CHEMIN,
                    exists=lambda p: p in (CHEMIN, attendu),
                    listdir=lambda p: [marqueur],
                )
                self.assertEqual(etat, deploy.ERPLIBRE)

    def test_un_repertoire_non_vide_refuse_meme_sans_marqueur(self):
        """Ce qui s'y trouve appartient à quelqu'un, ERPLibre ou non."""
        etat = deploy.etat_local(
            CHEMIN,
            exists=lambda p: p == CHEMIN,
            listdir=lambda p: ["notes.txt"],
        )
        self.assertEqual(etat, deploy.OCCUPE)

    def test_un_chemin_absent_ou_vide_est_libre(self):
        self.assertEqual(
            deploy.etat_local(CHEMIN, exists=lambda p: False),
            deploy.LIBRE,
        )
        self.assertEqual(
            deploy.etat_local(
                CHEMIN, exists=lambda p: p == CHEMIN, listdir=lambda p: []
            ),
            deploy.LIBRE,
        )

    def test_un_repertoire_illisible_compte_pour_occupe(self):
        """Ne pas avoir pu lire n'est pas avoir lu que c'était vide."""

        def refuse(_):
            raise OSError("permission denied")

        self.assertEqual(
            deploy.etat_local(
                CHEMIN, exists=lambda p: p == CHEMIN, listdir=refuse
            ),
            deploy.MUET,
        )

    def test_une_sonde_sans_jeton_est_muette_quel_que_soit_le_code(self):
        """Un hôte injoignable, une clé refusée et un lien coupé rendent
        tous une sortie vide. Aucun ne prouve qu'il n'y a rien là-bas, et se
        tromper dans ce sens détruit le travail de quelqu'un."""
        for code in (0, 1, 255):
            with self.subTest(code=code):
                self.assertEqual(deploy.lire_sonde(code, ""), deploy.MUET)
        self.assertEqual(
            deploy.lire_sonde(0, "un message d'erreur"), deploy.MUET
        )

    def test_le_jeton_seul_dit_libre(self):
        self.assertEqual(
            deploy.lire_sonde(0, f"{deploy.JETON}\n"), deploy.LIBRE
        )

    def test_un_marqueur_nomme_l_occupant(self):
        sortie = f"{deploy.MARQUE} .git\n{deploy.PLEIN}\n{deploy.JETON}\n"
        self.assertEqual(deploy.lire_sonde(0, sortie), deploy.ERPLIBRE)
        self.assertEqual(deploy.marqueurs_vus(sortie), [".git"])

    def test_plein_sans_marqueur_reste_occupe(self):
        sortie = f"{deploy.PLEIN}\n{deploy.JETON}\n"
        self.assertEqual(deploy.lire_sonde(0, sortie), deploy.OCCUPE)
        self.assertEqual(deploy.marqueurs_vus(sortie), [])

    def test_la_sonde_et_le_verdict_local_disent_la_meme_chose(self):
        """Les deux chemins de code jugent le même arbre : s'ils divergent,
        une pose locale refuse là où une pose distante accepte."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cas = {}
            cas["absent"] = os.path.join(tmp, "rien")
            cas["vide"] = os.path.join(tmp, "vide")
            os.mkdir(cas["vide"])
            cas["occupe"] = os.path.join(tmp, "occupe")
            os.mkdir(cas["occupe"])
            open(os.path.join(cas["occupe"], "note.txt"), "w").close()
            cas["erplibre"] = os.path.join(tmp, "el")
            os.makedirs(os.path.join(cas["erplibre"], "script", "todo"))
            open(
                os.path.join(cas["erplibre"], "script", "todo", "todo.py"),
                "w",
            ).close()
            for nom, chemin in cas.items():
                with self.subTest(nom):
                    res = subprocess.run(
                        ["bash", "-c", deploy.sonde_shell(chemin)],
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(
                        deploy.lire_sonde(res.returncode, res.stdout),
                        deploy.etat_local(chemin),
                    )


class LeTilde(unittest.TestCase):
    """Le chemin sondé doit être le chemin écrit.

    `shlex.quote` protège le tilde, qui y perd son sens : « '~/erplibre' »
    désigne un répertoire NOMMÉ « ~ ». Une spécification distante de rsync, au
    contraire, laisse le shell de là-bas le développer. Les deux formes se
    côtoyaient, et le chemin par défaut est justement « ~/erplibre » : la
    sonde jugeait un répertoire que personne n'habite pendant que rsync
    écrivait sur l'installation vivante.
    """

    def test_le_tilde_de_tete_devient_le_compte_de_la_cible(self):
        self.assertEqual(deploy.chemin_shell("~"), '"$HOME"')
        self.assertEqual(deploy.chemin_shell("~/erplibre"), '"$HOME"/erplibre')
        self.assertEqual(deploy.chemin_shell("/srv/el"), "/srv/el")

    def test_un_tilde_ailleurs_qu_en_tete_reste_cite(self):
        self.assertEqual(deploy.chemin_shell("/srv/~x"), "'/srv/~x'")

    def test_le_compte_d_autrui_se_reconnait_pour_etre_refuse(self):
        """Personne ici ne sait où vit le compte d'autrui sur la cible."""
        self.assertTrue(deploy.tilde_etranger("~bob/erplibre"))
        self.assertFalse(deploy.tilde_etranger("~/erplibre"))
        self.assertFalse(deploy.tilde_etranger("~"))
        self.assertFalse(deploy.tilde_etranger("/srv/el"))

    def test_aucun_bloc_ne_cite_le_tilde_de_tete(self):
        """La régression se voit à un « '~ » dans n'importe quel bloc."""
        blocs = (
            deploy.sonde_shell("~/erplibre"),
            deploy.bloc_clone(
                "~/erplibre", git_url=DEPOT, branche="master", cible_make=MAKE
            ),
            deploy.bloc_local_copie("~/erplibre", cible_make=MAKE),
            deploy.bloc_ecrire_config("~/erplibre", ["assistant"]),
            deploy.bloc_commandes_claude("~/erplibre", (("c", "t.md"),)),
        )
        for bloc in blocs:
            with self.subTest(bloc[:40]):
                self.assertNotIn("'~", bloc)
                self.assertIn('"$HOME"', bloc)

    def test_la_sonde_lit_bien_le_compte_et_non_un_repertoire_nomme(self):
        """Le cas réel : une installation sous le compte de la cible doit
        être VUE par une sonde qui reçoit « ~/erplibre »."""
        import tempfile

        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, "erplibre", "script", "todo"))
            open(
                os.path.join(home, "erplibre", "script", "todo", "todo.py"),
                "w",
            ).close()
            res = subprocess.run(
                ["bash", "-c", deploy.sonde_shell("~/erplibre")],
                capture_output=True,
                text=True,
                env=dict(os.environ, HOME=home),
            )
            self.assertEqual(
                deploy.lire_sonde(res.returncode, res.stdout),
                deploy.ERPLIBRE,
            )

    def test_le_clone_ne_cree_pas_un_repertoire_nomme_tilde(self):
        import tempfile

        with tempfile.TemporaryDirectory() as home:
            subprocess.run(
                [
                    "bash",
                    "-c",
                    deploy.bloc_clone(
                        "~/nulle-part",
                        git_url="https://exemple.invalid/x.git",
                        branche="master",
                        cible_make=MAKE,
                    ),
                ],
                capture_output=True,
                text=True,
                env=dict(os.environ, HOME=home),
                cwd=home,
                timeout=60,
            )
            self.assertFalse(os.path.exists(os.path.join(home, "~")))


class LaGardeEstRejoueePartout(unittest.TestCase):
    """Entre la sonde du menu et l'écriture, il y a le temps de lire une
    commande et de retaper un chemin. Le shell est le seul des deux à tourner
    là où l'on écrit, et les TROIS méthodes doivent le rejouer."""

    def test_les_trois_blocs_portent_la_garde(self):
        blocs = {
            "clone": deploy.bloc_clone(
                CHEMIN, git_url=DEPOT, branche="master", cible_make=MAKE
            ),
            "copie ssh": deploy.bloc_copie(une_cible(), cible_make=MAKE),
            "copie locale": deploy.bloc_local_copie(CHEMIN, cible_make=MAKE),
        }
        for nom, bloc in blocs.items():
            with self.subTest(nom):
                self.assertIn(deploy.GARDE, bloc)
                self.assertIn("exit 3", bloc)

    def test_la_garde_precede_l_ecriture_dans_chaque_bloc(self):
        for nom, bloc, ecriture in (
            (
                "clone",
                deploy.bloc_clone(
                    CHEMIN,
                    git_url=DEPOT,
                    branche="master",
                    cible_make=MAKE,
                ),
                "git clone",
            ),
            (
                "copie ssh",
                deploy.bloc_copie(une_cible(), cible_make=MAKE),
                "rsync",
            ),
            (
                "copie locale",
                deploy.bloc_local_copie(CHEMIN, cible_make=MAKE),
                "rsync",
            ),
        ):
            with self.subTest(nom):
                self.assertLess(bloc.index(deploy.GARDE), bloc.index(ecriture))

    def test_la_garde_dit_la_meme_chose_que_la_sonde(self):
        """Un répertoire VIDE est libre pour la sonde : la garde doit le
        laisser passer, sans quoi le menu accepte et le shell refuse."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            vide = os.path.join(tmp, "vide")
            os.mkdir(vide)
            self.assertEqual(deploy.etat_local(vide), deploy.LIBRE)
            res = subprocess.run(
                ["bash", "-c", f"{deploy._garde_shell(vide)}; echo PASSE"],
                capture_output=True,
                text=True,
            )
            self.assertIn("PASSE", res.stdout)

    def test_la_garde_arrete_un_repertoire_occupe(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            plein = os.path.join(tmp, "plein")
            os.mkdir(plein)
            open(os.path.join(plein, "note.txt"), "w").close()
            res = subprocess.run(
                ["bash", "-c", f"{deploy._garde_shell(plein)}; echo PASSE"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 3)
            self.assertNotIn("PASSE", res.stdout)

    def test_la_copie_distante_cree_le_repertoire_avant_rsync(self):
        """rsync sans `--mkpath` ne crée que le dernier segment."""
        bloc = deploy.bloc_copie(une_cible(), cible_make=MAKE)
        self.assertIn('mkdir -p "$p"', bloc)
        self.assertLess(bloc.index("mkdir -p"), bloc.index("rsync"))


class LeShellFabrique(unittest.TestCase):
    def test_tous_les_blocs_sont_du_shell_valide(self):
        blocs = {
            "sonde": deploy.sonde_shell(CHEMIN),
            "clone": deploy.bloc_clone(
                CHEMIN, git_url=DEPOT, branche="master", cible_make=MAKE
            ),
            "copie": deploy.bloc_copie(une_cible(), cible_make=MAKE),
            "copie_locale": deploy.bloc_local_copie(CHEMIN, cible_make=MAKE),
            "config": deploy.bloc_ecrire_config(
                CHEMIN, ["assistant", "servers"]
            ),
            "claude": deploy.bloc_commandes_claude(
                CHEMIN, (("commit", "template_claude_commands_commit.md"),)
            ),
        }
        for nom, bloc in blocs.items():
            with self.subTest(nom):
                code, erreur = parse(bloc)
                self.assertEqual(code, 0, f"{nom} : {erreur}")

    def test_un_chemin_avec_une_espace_survit(self):
        """Un chemin cité de travers découperait la commande en deux."""
        for bloc in (
            deploy.sonde_shell("/srv/atelier nord/el"),
            deploy.bloc_clone(
                "/srv/atelier nord/el",
                git_url=DEPOT,
                branche="master",
                cible_make=MAKE,
            ),
        ):
            code, erreur = parse(bloc)
            self.assertEqual(code, 0, erreur)

    def test_la_garde_precede_le_clone(self):
        """La garde est rejouée là où l'écriture aura lieu, et AVANT elle :
        entre l'écran et le shell, le temps de retaper un chemin."""
        bloc = deploy.bloc_clone(
            CHEMIN, git_url=DEPOT, branche="master", cible_make=MAKE
        )
        self.assertLess(bloc.index("[ -e "), bloc.index("git clone"))
        self.assertIn(deploy.GARDE, bloc)

    def test_l_installation_est_groupee_par_accolades(self):
        """« cmd && a; b » ne lie que son premier maillon : b tournerait
        après un clone échoué."""
        bloc = deploy.bloc_clone(
            CHEMIN, git_url=DEPOT, branche="master", cible_make=MAKE
        )
        self.assertIn("&& {", bloc)

    def test_la_copie_emporte_le_depot(self):
        """Sans `.git`, l'installation ne sait pas résoudre la branche de
        son manifeste : « make ssh_push » exclut le dépôt, et l'installation
        qui suit s'arrête. La copie d'ici ne l'exclut donc pas."""
        bloc = deploy.bloc_copie(une_cible(), cible_make=MAKE)
        self.assertNotIn("--exclude='.git/'", bloc)
        self.assertNotIn(".git", deploy.EXCLUS)

    def test_la_copie_laisse_le_prive_et_les_environnements(self):
        """`private/` porte le coffre et les identifiants ; les
        environnements virtuels se reconstruisent et pèsent des
        gigaoctets."""
        bloc = deploy.bloc_copie(une_cible(), cible_make=MAKE)
        for exclu in ("private/", ".venv.*/", "addons/"):
            with self.subTest(exclu):
                self.assertIn(exclu, bloc)

    def test_la_source_porte_sa_barre_oblique(self):
        """Sans elle, rsync crée `dst/src/` et l'installation ne trouve
        plus son Makefile."""
        bloc = deploy.bloc_local_copie(
            CHEMIN, source="/tmp/x", cible_make=MAKE
        )
        self.assertIn("/tmp/x/", bloc)

    def test_la_commande_distante_part_en_un_seul_argument(self):
        """Sans la citation, l'interpréteur d'ici découperait la commande et
        ssh n'en recevrait que le premier mot."""
        bloc = deploy.bloc_distant(ALIAS, "echo un deux trois")
        self.assertIn("BatchMode=yes", bloc)
        self.assertIn("'echo un deux trois'", bloc)


class LeTransfert(unittest.TestCase):
    def test_la_charge_passe_par_l_entree_standard(self):
        """Elle porte des adresses, et une ligne de commande se lit dans un
        journal comme dans la table des processus."""
        bloc = deploy.bloc_ecrire_config(CHEMIN, ["assistant", "servers"])
        self.assertIn("sys.stdin", bloc)
        self.assertIn("set_config_value", bloc)

    def test_l_ecriture_passe_par_le_seul_ecrivain_autorise(self):
        """`set_config_value` vise le seul des trois fichiers fusionnés qui
        soit gitignored, crée son répertoire en 0700 et écrit atomiquement.
        Un « > » de shell ferait les trois autrement."""
        bloc = deploy.bloc_ecrire_config(CHEMIN, ["assistant", "servers"])
        self.assertIn("ConfigFile", bloc)
        self.assertNotIn("todo_override.json", bloc)

    def test_les_copies_de_commandes_sont_chainees_par_et(self):
        """Chaîné par point-virgule, le bloc rend le code du DERNIER `cp`
        seul : un échec au milieu se rapporterait comme un succès, et le
        menu n'inspecte que le code de retour."""
        bloc = deploy.bloc_commandes_claude(
            CHEMIN, (("commit", "a.md"), ("plan", "b.md"))
        )
        self.assertNotIn("; cp", bloc)
        self.assertIn("&& cp", bloc)

    def test_un_cp_rate_fait_echouer_le_bloc_entier(self):
        bloc = deploy.bloc_commandes_claude(
            "/chemin/qui/n/existe/pas", (("commit", "a.md"), ("plan", "b.md"))
        )
        import tempfile

        with tempfile.TemporaryDirectory() as home:
            # HOME détourné : le bloc commence par « mkdir -p
            # ~/.claude/commands », qui créerait le répertoire dans le vrai
            # compte de qui lance la suite.
            res = subprocess.run(
                ["bash", "-c", bloc],
                capture_output=True,
                text=True,
                env=dict(os.environ, HOME=home),
            )
        self.assertNotEqual(res.returncode, 0)

    def test_les_commandes_claude_viennent_du_checkout_de_la_cible(self):
        """Rien de `~/.claude` d'ici ne part : les gabarits d'ici portent le
        nom et le courriel de l'opérateur d'ici, déjà substitués."""
        bloc = deploy.bloc_commandes_claude(
            CHEMIN, (("commit", "template_claude_commands_commit.md"),)
        )
        # La SOURCE est sous le checkout de la cible, la DESTINATION sous le
        # compte de la cible. Aucun chemin ne part de la machine d'ici.
        self.assertIn(
            f"{CHEMIN}/conf/template_claude_commands_commit.md", bloc
        )
        self.assertIn("~/.claude/commands/commit.md", bloc)
        self.assertLess(
            bloc.index(CHEMIN), bloc.index("~/.claude/commands/commit.md")
        )

    def test_un_nom_de_commande_douteux_est_ecarte(self):
        """La destination laisse le tilde hors des guillemets pour que le
        shell le développe : ce qui n'est pas cité doit être sûr par
        construction."""
        bloc = deploy.bloc_commandes_claude(
            CHEMIN, (("; rm -rf ~", "gabarit.md"),)
        )
        self.assertNotIn("rm -rf", bloc)

    def test_la_charge_des_serveurs_ne_porte_pas_de_poignee(self):
        """La poignée se rattribue au chargement : un rang figé survivrait à
        la suppression d'un voisin."""
        from script.todo.assistant import servers

        serveur = servers.Server(
            handle="server-3",
            label="Atelier",
            host="cinabre.invalid",
            port=11434,
            software="ollama",
            model="",
            hosting="lan",
            secret_ref="",
        )
        charge = deploy.payload_serveurs([serveur])
        self.assertNotIn("handle", charge[0])
        self.assertEqual(charge[0]["host"], "cinabre.invalid")


class LaRedaction(unittest.TestCase):
    def test_le_resume_ne_nomme_ni_l_alias_ni_le_chemin(self):
        """Le détecteur du dépôt reconnaît les adresses, les courriels et
        les chemins de compte, et ne voit passer NI un alias SSH NI un nom
        d'hôte nu : seule la structure protège ces noms."""
        resume = deploy.resume(une_cible())
        self.assertIn("cible-1", resume)
        self.assertNotIn(ALIAS, resume)
        self.assertNotIn(CHEMIN, resume)

    def test_une_cible_locale_se_distingue_sans_se_nommer(self):
        self.assertIn("local", deploy.resume(une_cible(alias="")))


class LesClesDePanne(unittest.TestCase):
    def test_la_garde_est_traduite(self):
        self.assertIn(deploy.GARDE, TRANSLATIONS)


class LaFrontiere(unittest.TestCase):
    def test_le_deploiement_ne_tire_pas_todo(self):
        """Importer `script.todo.todo` coûte près d'une seconde et imprime
        sur la sortie : le paquet doit rester importable seul."""
        # Dans un interpréteur NEUF : la suite complète importe todo par
        # ailleurs, et le sys.modules de ce processus en garderait la trace
        # quel que soit le module éprouvé ici.
        sortie = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys, script.todo.assistant.deploy;"
                " print('script.todo.todo' in sys.modules)",
            ],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(sortie.returncode, 0, sortie.stderr)
        self.assertEqual(sortie.stdout.strip(), "False")


if __name__ == "__main__":
    unittest.main()
