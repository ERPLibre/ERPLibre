#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les réglages de production côté todo : éditeur, enregistrement, secrets.

L'éditeur ligne par ligne ne pose une valeur qu'après `profil.convertir`,
n'écrit qu'à l'enregistrement, et l'enregistrement s'arrête à chaque refus
(vérification par les outils, rétention, coffre, verrou optimiste) sans
rien écrire. Un secret ne va jamais dans le profil ni sur argv : le coffre
reçoit la valeur, le profil sa référence, l'outil le chemin d'un fichier
0600 d'un tmpfs retiré dans tous les cas.

`profil_isole` arme la couture des profils ; les préférences, le coffre,
le dossier des unités et les tmpfs sont des dossiers temporaires ou des
doublures. Les valeurs sont inventées (`odoo-exemple.service`,
`exemple_db`, `example.org`).
"""

import contextlib
import datetime
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE_DEPOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE_DEPOT))
# Importé par son dossier et non par `test.` : sous le python3 du système,
# `test` est le paquet des tests de la bibliothèque standard.
sys.path.insert(0, str(RACINE_DEPOT / "test"))
sys.argv = ["todo.py"]

from profil_isole import profil_isole  # noqa: E402

from script.lib_ops import profil, retention  # noqa: E402
from script.todo import ops_settings, todo_prefs  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

SERVICE = "odoo-exemple.service"
SECRET = "valeur-secrete-inventee-7c1d"
REFERENCE = f"ERPLibre/Production/{SERVICE}/warmup.api_key"
DOSSIER_PROFILS = None
CATALOGUE = None


def setUpModule():
    global DOSSIER_PROFILS, CATALOGUE
    DOSSIER_PROFILS = profil_isole()
    preferences = tempfile.TemporaryDirectory(prefix="erplibre-prefs-")
    unittest.addModuleCleanup(preferences.cleanup)
    patch = mock.patch.object(
        todo_prefs,
        "_path",
        lambda: Path(preferences.name) / "todo_prefs.json",
    )
    patch.start()
    unittest.addModuleCleanup(patch.stop)
    CATALOGUE = ops_settings.charger_catalogue()


class FausseConfig:
    def __init__(self, kdbx):
        self.kdbx = kdbx

    def get_config_value(self, cles):
        return self.kdbx if cles == ["kdbx", "path"] else None


class FauxCoffre:
    """Un `SecretStore` en mémoire qui retient ses appels."""

    def __init__(self, valeurs=None):
        self.valeurs = dict(valeurs or {})
        self.appels = []

    def get(self, ref):
        self.appels.append(("get", ref))
        return self.valeurs.get(ref)

    def set(self, ref, valeur):
        self.appels.append(("set", ref))
        self.valeurs[ref] = valeur

    def delete(self, ref):
        self.appels.append(("delete", ref))
        self.valeurs.pop(ref, None)


def nouveau_todo(kdbx=None):
    todo = TODO.__new__(TODO)
    todo.config_file = FausseConfig(kdbx)
    todo.kdbx_manager = mock.Mock()
    todo._ops_service_devine = None
    return todo


def chemin_profil():
    return os.path.join(DOSSIER_PROFILS, SERVICE + ".json")


def ecrire_profil(**groupes):
    doc = {"version": profil.VERSION, "service": SERVICE}
    doc.update(groupes)
    profil.ecrire(chemin_profil(), doc)
    return doc


def lire_profil():
    with open(chemin_profil(), encoding="utf-8") as fichier:
        return json.load(fichier)


def champ(groupe, cle):
    return ops_settings.champ_cible(CATALOGUE, groupe, cle)


def t_(texte):
    """Le libellé que todo affiche, dans la langue courante."""
    return ops_settings.t(texte)


class Base(unittest.TestCase):
    def setUp(self):
        todo_prefs._save({})
        ops_settings.OpsSettingsMixin._ops_retenir_service(SERVICE)
        if os.path.lexists(chemin_profil()):
            os.unlink(chemin_profil())
        unites = tempfile.TemporaryDirectory(prefix="erplibre-unites-")
        self.addCleanup(unites.cleanup)
        self.unites = unites.name
        patch = mock.patch.object(profil, "DOSSIER_UNITES", unites.name)
        patch.start()
        self.addCleanup(patch.stop)

    def jouer(self, methode, choix=(), saisies=(), confirmations=(), **kw):
        """Joue `methode` du todo avec ces réponses ; rend (résultat,
        sortie, confirm)."""
        todo = kw.pop("todo", None) or nouveau_todo(kw.pop("kdbx", None))
        sortie = io.StringIO()
        with (
            mock.patch(
                "script.todo.ops_settings.click.prompt",
                side_effect=list(choix),
            ),
            mock.patch("builtins.input", side_effect=list(saisies)),
            mock.patch(
                "script.todo.ops_settings.click.confirm",
                side_effect=list(confirmations),
            ) as confirm,
            mock.patch.object(todo, "_menu_header", return_value=""),
            contextlib.redirect_stdout(sortie),
        ):
            resultat = getattr(todo, methode)(*kw.pop("args", ()))
        return resultat, sortie.getvalue(), confirm


class TestCatalogue(unittest.TestCase):
    def test_une_ligne_par_champ(self):
        lignes = ops_settings.lignes_reglages(CATALOGUE, {})
        attendus = [
            (groupe, cle)
            for groupe, cles in profil.CHAMPS.items()
            if groupe != profil.GROUPE_HOTE
            for cle in cles
        ]
        self.assertEqual([(l.groupe, l.champ.cle) for l in lignes], attendus)
        hote = ops_settings.charger_catalogue(hote=True)
        self.assertEqual(
            [l.champ.cle for l in ops_settings.lignes_reglages(hote, {})],
            list(profil.CHAMPS[profil.GROUPE_HOTE]),
        )

    def test_origine_et_valeur(self):
        doc = {"backup": {"keep_daily": 10}}
        lignes = {
            (l.groupe, l.champ.cle): l
            for l in ops_settings.lignes_reglages(CATALOGUE, doc)
        }
        ligne = lignes[("backup", "keep_daily")]
        self.assertEqual((ligne.valeur, ligne.origine), (10, "profil"))
        self.assertEqual(lignes[("backup", "keep_weekly")].origine, "defaut")
        self.assertEqual(lignes[("backup", "dest")].portee, "installation")

    def test_aides_audit_couvrent_exactement_les_champs(self):
        self.assertEqual(
            set(ops_settings.AIDES_AUDIT),
            set(profil.CHAMPS[profil.GROUPE_HOTE]),
        )

    def test_chaque_groupe_a_un_nom(self):
        for groupe in profil.CHAMPS:
            self.assertNotEqual(ops_settings.nom_groupe(groupe), groupe)

    def test_defaut_detecte_ou_aucun(self):
        from script.todo.todo_i18n import t

        self.assertEqual(
            ops_settings.defaut_affiche(champ("instance", "db")),
            t("(detected)"),
        )
        self.assertEqual(
            ops_settings.defaut_affiche(champ("health_check", "mail_domain")),
            t("(none)"),
        )


class TestSaisie(unittest.TestCase):
    def test_entier_en_chiffres_ascii_seulement(self):
        keep = champ("backup", "keep_daily")
        self.assertEqual(ops_settings.convertir_saisie(keep, "10"), 10)
        for texte in ("²", "٣", "-1", "1.5", "abc"):
            with self.subTest(texte=texte):
                with self.assertRaises(profil.ErreurProfil):
                    ops_settings.convertir_saisie(keep, texte)

    def test_nombre_a_virgule_et_texte(self):
        delai = champ("warmup", "timeout")
        self.assertEqual(ops_settings.convertir_saisie(delai, "2.5"), 2.5)
        self.assertEqual(ops_settings.convertir_saisie(delai, "30"), 30)
        calendrier = champ("backup_timer", "on_calendar")
        self.assertEqual(
            ops_settings.convertir_saisie(calendrier, "*-*-* 02:30:00"),
            "*-*-* 02:30:00",
        )

    def test_regles_du_profil(self):
        with self.assertRaises(profil.ErreurProfil):
            ops_settings.convertir_saisie(champ("backup", "keep_daily"), "0")
        with self.assertRaises(profil.ErreurProfil):
            ops_settings.convertir_saisie(champ("backup", "dest"), "relatif")

    def test_somme_des_retentions(self):
        brouillon = ops_settings.Brouillon.ouvrir(
            chemin_profil(), CATALOGUE, service=SERVICE
        )
        for cle in ("keep_weekly", "keep_monthly", "keep_recent_days"):
            brouillon.definir(champ("backup", cle), 0)
        with self.assertRaises(profil.ErreurProfil):
            brouillon.definir(champ("backup", "keep_daily"), 1)
        self.assertNotIn("keep_daily", brouillon.doc["backup"])


class TestEditeurLigneParLigne(Base):
    """Groupes : [3] Sauvegardes, [9] Enregistrer, [10] Différences."""

    def test_entier_invalide_puis_valide(self):
        ecrit, sortie, _ = self.jouer(
            "_ops_reglages_groupes",
            choix=["3", "3", "0", "9"],
            saisies=["abc", "²", "10"],
            args=(self.brouillon(),),
        )
        self.assertTrue(ecrit)
        self.assertEqual(lire_profil()["backup"], {"keep_daily": 10})
        self.assertEqual(sortie.count("✗"), 2)

    def test_tiret_revient_au_defaut(self):
        ecrire_profil(backup={"keep_daily": 10})
        ecrit, _sortie, _ = self.jouer(
            "_ops_reglages_groupes",
            choix=["3", "3", "0", "9"],
            saisies=["-"],
            args=(self.brouillon(),),
        )
        self.assertTrue(ecrit)
        self.assertNotIn("backup", lire_profil())

    def test_booleen(self):
        ecrit, _sortie, _ = self.jouer(
            "_ops_reglages_groupes",
            choix=["2", "6", "0", "9"],
            confirmations=[True],
            args=(self.brouillon(),),
        )
        self.assertTrue(ecrit)
        self.assertEqual(lire_profil()["update_module"], {"verbose": True})

    def test_liste_ajouter_retirer(self):
        ecrit, sortie, _ = self.jouer(
            "_ops_reglages_groupes",
            # Mise à jour › --ignore-error : ajouter deux fois, un motif
            # trop large refusé, retirer le premier.
            choix=["2", "3", "1", "1", "1", "2", "0", "0", "9"],
            saisies=["motif_a: x", "motif_b: y", ".*", "1"],
            args=(self.brouillon(),),
        )
        self.assertTrue(ecrit)
        self.assertEqual(
            lire_profil()["update_module"], {"ignore_error": ["motif_b: y"]}
        )
        self.assertIn("✗", sortie)

    def test_liste_vider(self):
        ecrire_profil(update_module={"ignore_error": ["motif_a: x"]})
        ecrit, _sortie, _ = self.jouer(
            "_ops_reglages_groupes",
            choix=["2", "3", "3", "0", "0", "9"],
            args=(self.brouillon(),),
        )
        self.assertTrue(ecrit)
        self.assertNotIn("update_module", lire_profil())

    def test_retour_avec_changements_defaut_non(self):
        ecrit, _sortie, confirm = self.jouer(
            "_ops_reglages_groupes",
            choix=["3", "3", "0", "0"],
            saisies=["10"],
            confirmations=[False],
            args=(self.brouillon(),),
        )
        self.assertFalse(ecrit)
        self.assertFalse(os.path.lexists(chemin_profil()))
        self.assertIs(confirm.call_args.kwargs["default"], False)

    def test_retour_sans_changement(self):
        ecrit, _sortie, confirm = self.jouer(
            "_ops_reglages_groupes", choix=["0"], args=(self.brouillon(),)
        )
        self.assertFalse(ecrit)
        self.assertFalse(confirm.called)

    def test_differences(self):
        _ecrit, sortie, _ = self.jouer(
            "_ops_reglages_groupes",
            choix=["3", "3", "0", "10", "0"],
            saisies=["10"],
            confirmations=[False],
            args=(self.brouillon(),),
        )
        self.assertIn("keep_daily : — → 10", sortie)

    def test_alias_mene_a_sa_cible(self):
        # Mise à jour : 6 champs, puis --db (→ Instance), --backup-dest…
        ecrit, _sortie, _ = self.jouer(
            "_ops_reglages_groupes",
            choix=["2", "7", "0", "9"],
            saisies=["exemple_db"],
            args=(self.brouillon(),),
        )
        self.assertTrue(ecrit)
        self.assertEqual(lire_profil()["instance"], {"db": "exemple_db"})

    def brouillon(self):
        return ops_settings.Brouillon.ouvrir(
            chemin_profil(), CATALOGUE, service=SERVICE
        )


class TestEnregistrer(Base):
    def brouillon(self):
        return ops_settings.Brouillon.ouvrir(
            chemin_profil(), CATALOGUE, service=SERVICE
        )

    def enregistrer(self, brouillon, confirmations=(), **kw):
        return self.jouer(
            "_ops_enregistrer",
            confirmations=confirmations,
            args=(brouillon,),
            **kw,
        )

    def test_conflit_d_empreinte(self):
        brouillon = self.brouillon()
        brouillon.definir(champ("backup", "keep_daily"), 10)
        ecrire_profil(log_check={"days": 3})
        ecrit, sortie, _ = self.enregistrer(brouillon)
        self.assertFalse(ecrit)
        self.assertEqual(lire_profil()["log_check"], {"days": 3})
        self.assertNotIn("backup", lire_profil())

    def test_verification_bloquante(self):
        brouillon = self.brouillon()
        brouillon.definir(champ("backup", "keep_daily"), 10)
        refus = [ops_settings.Echec("backup", 2, "refus inventé")]
        with mock.patch.object(ops_settings, "verifier", return_value=refus):
            ecrit, sortie, _ = self.enregistrer(brouillon)
        self.assertFalse(ecrit)
        self.assertFalse(os.path.lexists(chemin_profil()))
        self.assertIn("refus inventé", sortie)

    def test_verification_vraie_sur_une_copie(self):
        """Les outils de ce checkout lisent la copie, sous le nom que le
        profil exige, et un profil correct passe."""
        brouillon = self.brouillon()
        brouillon.definir(champ("log_check", "days"), 14)
        self.assertEqual(ops_settings.verifier_brouillon(brouillon), [])
        # Un service qui ne correspond plus au nom du fichier : chaque
        # outil d'instance refuse, en code 2, et l'audit n'est pas lancé.
        brouillon.doc["service"] = "odoo-autre.service"
        echecs = ops_settings.verifier_brouillon(brouillon)
        self.assertEqual(
            {e.groupe for e in echecs},
            {o.groupe for o in profil.OUTILS} - {profil.GROUPE_HOTE},
        )
        self.assertEqual({e.code for e in echecs}, {2})

    def test_apercu_de_retention(self):
        sauvegardes = tempfile.TemporaryDirectory(prefix="erplibre-sauv-")
        self.addCleanup(sauvegardes.cleanup)
        dossier = os.path.join(sauvegardes.name, "exemple_db")
        os.mkdir(dossier)
        maintenant = datetime.datetime(2026, 1, 20, 3, 0, 0)
        for jours in range(10):
            nom = retention.nom_sauvegarde(
                "exemple_db", maintenant - datetime.timedelta(days=jours)
            )
            Path(dossier, nom).touch()
        ecrire_profil(
            instance={"db": "exemple_db"},
            backup={"dest": sauvegardes.name},
        )
        brouillon = self.brouillon()
        for cle, valeur in (
            ("keep_daily", 1),
            ("keep_weekly", 0),
            ("keep_monthly", 0),
            ("keep_recent_days", 1),
        ):
            brouillon.definir(champ("backup", cle), valeur)
        avant = lire_profil()
        ecrit, sortie, confirm = self.enregistrer(
            brouillon, confirmations=[False]
        )
        self.assertFalse(ecrit)
        self.assertEqual(lire_profil(), avant)
        self.assertIn("9 ", sortie)
        self.assertIs(confirm.call_args.kwargs["default"], False)

    def test_reinstallation_proposee(self):
        ecrire_profil(instance={"db": "exemple_db"})
        Path(self.unites, "erplibre-backup-exemple_db.service").write_text(
            f"[Service]\nWorkingDirectory={ops_settings.RACINE}\n"
            f"ExecStart=/usr/bin/python3 x.py --profile {chemin_profil()}\n",
            encoding="utf-8",
        )
        brouillon = self.brouillon()
        brouillon.definir(
            champ("backup", "copy_to"),
            "sauvegarde@backup.example.org:/srv/hors-site",
        )
        todo = nouveau_todo()
        todo._ops_backup_timer_install = mock.Mock()
        ecrit, sortie, confirm = self.enregistrer(
            brouillon, confirmations=[True], todo=todo
        )
        self.assertTrue(ecrit)
        self.assertTrue(todo._ops_backup_timer_install.called)
        self.assertIn("erplibre-backup-exemple_db.service", sortie)

    def test_champ_direct_ne_propose_rien(self):
        ecrire_profil()
        Path(self.unites, "erplibre-backup-exemple_db.service").write_text(
            f"ExecStart=x --profile {chemin_profil()}\n", encoding="utf-8"
        )
        brouillon = self.brouillon()
        brouillon.definir(champ("backup", "keep_daily"), 9)
        todo = nouveau_todo()
        todo._ops_backup_timer_install = mock.Mock()
        ecrit, _sortie, confirm = self.enregistrer(brouillon, todo=todo)
        self.assertTrue(ecrit)
        self.assertFalse(todo._ops_backup_timer_install.called)

    def test_cles_inconnues_retirees(self):
        doc = {
            "version": profil.VERSION,
            "service": SERVICE,
            "update_module": {"db": "exemple_db", "verbose": True},
            "inconnu": {"x": 1},
        }
        Path(chemin_profil()).write_text(json.dumps(doc), encoding="utf-8")
        brouillon = self.brouillon()
        self.assertEqual(brouillon.ignorees, ["update_module.db", "inconnu"])
        ecrit, _sortie, _ = self.enregistrer(brouillon)
        self.assertTrue(ecrit)
        self.assertEqual(
            lire_profil(),
            {
                "version": 1,
                "service": SERVICE,
                "update_module": {"verbose": True},
            },
        )


class TestSecrets(Base):
    def test_secret_saisi_range_dans_le_coffre(self):
        coffre = FauxCoffre()
        with (
            mock.patch(
                "script.todo.mail.secrets.SecretStore", return_value=coffre
            ),
            mock.patch("getpass.getpass", return_value=SECRET),
        ):
            # Préchauffage approfondi [8] › --api-key-file [5] › [1] saisir.
            ecrit, sortie, _ = self.jouer(
                "_ops_reglages_groupes",
                choix=["8", "5", "1", "0", "9"],
                kdbx="/var/tmp/exemple.kdbx",
                args=(
                    ops_settings.Brouillon.ouvrir(
                        chemin_profil(), CATALOGUE, service=SERVICE
                    ),
                ),
            )
        self.assertTrue(ecrit)
        self.assertIn(("set", "kdbx:" + REFERENCE), coffre.appels)
        self.assertEqual(coffre.valeurs["kdbx:" + REFERENCE], SECRET)
        self.assertEqual(
            lire_profil()["warmup"], {"api_key_file": {"kdbx": REFERENCE}}
        )
        self.assertNotIn(SECRET, Path(chemin_profil()).read_text())
        self.assertNotIn(SECRET, sortie)

    def test_coffre_non_configure_sans_selecteur(self):
        todo = nouveau_todo(kdbx=None)
        with mock.patch("getpass.getpass") as saisie:
            _r, sortie, _ = self.jouer(
                "_ops_reglage_secret",
                choix=["1"],
                todo=todo,
                args=(
                    ops_settings.Brouillon.ouvrir(
                        chemin_profil(), CATALOGUE, service=SERVICE
                    ),
                    champ("warmup", "api_key_file"),
                ),
            )
        self.assertFalse(saisie.called)
        self.assertFalse(todo.kdbx_manager.get_kdbx.called)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(todo._ops_coffre())
        self.assertFalse(todo.kdbx_manager.get_kdbx.called)

    def test_retirer_avec_l_entree_du_coffre(self):
        ecrire_profil(warmup={"api_key_file": {"kdbx": REFERENCE}})
        coffre = FauxCoffre({"kdbx:" + REFERENCE: SECRET})
        with mock.patch(
            "script.todo.mail.secrets.SecretStore", return_value=coffre
        ):
            ecrit, _sortie, _ = self.jouer(
                "_ops_settings_secrets",
                choix=["3"],
                saisies=["1"],
                confirmations=[True],
                kdbx="/var/tmp/exemple.kdbx",
            )
        self.assertTrue(ecrit)
        self.assertIn(("delete", "kdbx:" + REFERENCE), coffre.appels)
        self.assertNotIn("warmup", lire_profil())


class TestCoffreEtEcriture(Base):
    """Une entrée définie est rangée avant l'écriture, une entrée retirée
    n'est supprimée qu'après : un profil refusé (verrou optimiste) laisse
    le coffre lisible par le profil resté sur disque."""

    def brouillon(self):
        return ops_settings.Brouillon.ouvrir(
            chemin_profil(), CATALOGUE, service=SERVICE
        )

    def enregistrer(self, brouillon, coffre):
        todo = nouveau_todo()
        todo._ops_coffre = lambda: coffre
        return self.jouer("_ops_enregistrer", args=(brouillon,), todo=todo)

    def test_retrait_apres_l_ecriture_seulement(self):
        ecrire_profil(warmup={"api_key_file": {"kdbx": REFERENCE}})
        coffre = FauxCoffre({"kdbx:" + REFERENCE: SECRET})
        brouillon = self.brouillon()
        brouillon.retirer(champ("warmup", "api_key_file"))
        brouillon.secrets_a_retirer.add(REFERENCE)
        # Le profil change ailleurs : l'écriture se refuse.
        ecrire_profil(
            warmup={"api_key_file": {"kdbx": REFERENCE}},
            log_check={"days": 3},
        )
        ecrit, _sortie, _ = self.enregistrer(brouillon, coffre)
        self.assertFalse(ecrit)
        self.assertNotIn(("delete", "kdbx:" + REFERENCE), coffre.appels)
        self.assertEqual(coffre.valeurs["kdbx:" + REFERENCE], SECRET)
        # Relu, le même retrait passe : l'entrée part après l'écriture.
        brouillon = self.brouillon()
        brouillon.retirer(champ("warmup", "api_key_file"))
        brouillon.secrets_a_retirer.add(REFERENCE)
        ecrit, _sortie, _ = self.enregistrer(brouillon, coffre)
        self.assertTrue(ecrit)
        self.assertIn(("delete", "kdbx:" + REFERENCE), coffre.appels)
        self.assertNotIn("warmup", lire_profil())

    def test_ecriture_refusee_apres_un_rangement_le_dit(self):
        coffre = FauxCoffre()
        brouillon = self.brouillon()
        brouillon.definir(champ("warmup", "api_key_file"), {"kdbx": REFERENCE})
        brouillon.secrets_a_definir[REFERENCE] = SECRET
        ecrire_profil(log_check={"days": 3})
        ecrit, sortie, _ = self.enregistrer(brouillon, coffre)
        self.assertFalse(ecrit)
        self.assertIn(("set", "kdbx:" + REFERENCE), coffre.appels)
        self.assertIn("[ATTN]", sortie)
        self.assertIn(REFERENCE, sortie)
        self.assertNotIn(SECRET, sortie)

    def test_definir_et_retirer_la_meme_entree_la_garde(self):
        coffre = FauxCoffre()
        brouillon = self.brouillon()
        brouillon.definir(champ("warmup", "api_key_file"), {"kdbx": REFERENCE})
        brouillon.secrets_a_definir[REFERENCE] = SECRET
        brouillon.secrets_a_retirer.add(REFERENCE)
        ecrit, _sortie, _ = self.enregistrer(brouillon, coffre)
        self.assertTrue(ecrit)
        self.assertEqual(coffre.valeurs["kdbx:" + REFERENCE], SECRET)


class TestFormulaire(Base):
    """Le chemin Textual hors de Textual : `run_settings_form` est une
    doublure qui rend un `Resultat`. Un enregistrement refusé rouvre le
    formulaire sur le même brouillon ; « retirer » ne supprime l'entrée
    KeePass que sur accord."""

    def setUp(self):
        super().setUp()
        self.coffre = FauxCoffre()
        self.contextes = []
        patch = mock.patch(
            "script.todo.modem.code_messagerie.kdbx_configure",
            return_value=True,
        )
        patch.start()
        self.addCleanup(patch.stop)

    def todo(self):
        todo = nouveau_todo()
        todo._ops_coffre = lambda: self.coffre
        return todo

    def jouer_formulaire(self, reponses, confirmations=(), refus=()):
        """`reponses` : une fonction par ouverture du formulaire, qui
        reçoit le `Contexte` et rend le `Resultat` ; `refus` : les
        vérifications successives (une liste d'échecs chacune)."""
        from script.todo import ops_settings_form

        reponses = list(reponses)

        def formulaire(contexte):
            self.contextes.append(contexte)
            return reponses.pop(0)(contexte)

        verifications = list(refus)

        def verifier(brouillon, hote=False):
            return verifications.pop(0) if verifications else []

        brouillon = ops_settings.Brouillon.ouvrir(
            chemin_profil(), CATALOGUE, service=SERVICE
        )
        with (
            mock.patch.object(
                ops_settings_form, "run_settings_form", side_effect=formulaire
            ),
            mock.patch.object(
                ops_settings, "verifier_brouillon", side_effect=verifier
            ),
            mock.patch("getpass.getpass", return_value=SECRET) as saisie,
        ):
            ecrit, sortie, confirm = self.jouer(
                "_ops_reglages_formulaire",
                confirmations=confirmations,
                todo=self.todo(),
                args=(brouillon,),
            )
        return ecrit, sortie, confirm, saisie

    @staticmethod
    def resultat(doc, a_definir=(), a_retirer=()):
        from script.todo import ops_settings_form

        return ops_settings_form.Resultat(
            doc, list(a_definir), list(a_retirer)
        )

    def test_refus_revient_au_formulaire_sans_rien_perdre(self):
        def premier(contexte):
            doc = dict(contexte.doc)
            doc["log_check"] = {"days": 14}
            doc["warmup"] = {"api_key_file": {"kdbx": REFERENCE}}
            return self.resultat(doc, a_definir=[REFERENCE])

        def second(contexte):
            return self.resultat(contexte.doc)

        refus = [[ops_settings.Echec("log_check", 2, "refus inventé")]]
        ecrit, sortie, confirm, saisie = self.jouer_formulaire(
            [premier, second], confirmations=[True], refus=refus
        )
        self.assertTrue(ecrit)
        self.assertEqual(len(self.contextes), 2)
        rouvert = self.contextes[1]
        self.assertEqual(rouvert.doc["log_check"], {"days": 14})
        self.assertEqual(
            rouvert.etats_secrets[("warmup", "api_key_file")],
            "kdbx_attente",
        )
        # Le secret tapé au premier tour n'est pas redemandé.
        self.assertEqual(saisie.call_count, 1)
        self.assertEqual(confirm.call_args.args[0], t_("Back to the form?"))
        self.assertEqual(lire_profil()["log_check"], {"days": 14})
        self.assertEqual(self.coffre.valeurs["kdbx:" + REFERENCE], SECRET)
        self.assertIn("refus inventé", sortie)
        self.assertNotIn(SECRET, sortie)

    def test_refus_puis_abandon_n_ecrit_rien(self):
        def premier(contexte):
            doc = dict(contexte.doc)
            doc["log_check"] = {"days": 14}
            return self.resultat(doc)

        refus = [[ops_settings.Echec("log_check", 2, "refus inventé")]]
        ecrit, _sortie, _confirm, _saisie = self.jouer_formulaire(
            [premier], confirmations=[False], refus=refus
        )
        self.assertFalse(ecrit)
        self.assertEqual(len(self.contextes), 1)
        self.assertFalse(os.path.lexists(chemin_profil()))

    def test_retirer_demande_avant_de_supprimer_l_entree(self):
        for accord in (False, True):
            with self.subTest(accord=accord):
                ecrire_profil(warmup={"api_key_file": {"kdbx": REFERENCE}})
                self.coffre = FauxCoffre({"kdbx:" + REFERENCE: SECRET})

                def premier(contexte):
                    doc = dict(contexte.doc)
                    del doc["warmup"]
                    return self.resultat(doc, a_retirer=[REFERENCE])

                ecrit, _sortie, confirm, _saisie = self.jouer_formulaire(
                    [premier], confirmations=[accord]
                )
                self.assertTrue(ecrit)
                self.assertNotIn("warmup", lire_profil())
                self.assertEqual(
                    confirm.call_args.args[0],
                    t_("Also delete the entry from KeePass?"),
                )
                self.assertIs(confirm.call_args.kwargs["default"], False)
                self.assertEqual(
                    ("delete", "kdbx:" + REFERENCE) in self.coffre.appels,
                    accord,
                )
                os.unlink(chemin_profil())


class TestProfilHote(Base):
    def test_editer_le_profil_de_ce_poste(self):
        todo_prefs.set("ops_settings_ui", "cli")
        chemin = ops_settings.chemin_hote("local")
        self.addCleanup(lambda: os.path.lexists(chemin) and os.unlink(chemin))
        # Un seul groupe : [1] Audit, [2] Enregistrer ; --duration en [1].
        _r, _sortie, _ = self.jouer(
            "_ops_settings_host_local",
            choix=["1", "1", "0", "2"],
            saisies=["10m"],
        )
        self.assertEqual(
            os.path.dirname(chemin), os.path.join(DOSSIER_PROFILS, "host")
        )
        doc = json.loads(Path(chemin).read_text(encoding="utf-8"))
        self.assertEqual(
            doc,
            {
                "version": 1,
                "host": "local",
                profil.GROUPE_HOTE: {"duration": "10m"},
            },
        )
        self.assertEqual(ops_settings.argv_audit(doc), ["--duration", "600"])


class TestSupprimer(Base):
    def test_refuse_si_une_unite_cite_le_profil(self):
        ecrire_profil()
        Path(self.unites, "erplibre-backup-exemple_db.service").write_text(
            f"ExecStart=x --profile {chemin_profil()}\n", encoding="utf-8"
        )
        supprime, sortie, _ = self.jouer("_ops_settings_delete")
        self.assertFalse(supprime)
        self.assertTrue(os.path.exists(chemin_profil()))
        self.assertIn("erplibre-backup-exemple_db.service", sortie)

    def test_nom_a_taper(self):
        ecrire_profil()
        supprime, _sortie, _ = self.jouer(
            "_ops_settings_delete", saisies=["odoo-exemple"]
        )
        self.assertFalse(supprime)
        self.assertTrue(os.path.exists(chemin_profil()))
        supprime, _sortie, _ = self.jouer(
            "_ops_settings_delete", saisies=[SERVICE]
        )
        self.assertTrue(supprime)
        self.assertFalse(os.path.exists(chemin_profil()))


class TestAfficherVerifier(Base):
    def test_afficher(self):
        ecrire_profil(backup={"keep_daily": 10})
        _r, sortie, _ = self.jouer("_ops_settings_show")
        self.assertIn("--keep-daily   10", sortie)
        self.assertIn("--backup-dest   →", sortie)
        self.assertIn("--force", sortie)

    def test_verifier(self):
        ecrire_profil(log_check={"days": 14})
        _r, sortie, _ = self.jouer("_ops_settings_check")
        self.assertIn("✓", sortie)
        self.assertNotIn("✗", sortie)


class TestInterface(unittest.TestCase):
    def demander(self, preference, reponse, pref_key="ops_settings_ui", **kw):
        todo_prefs._save({pref_key: preference})
        todo = nouveau_todo()
        with (
            mock.patch("builtins.input", return_value=reponse) as saisie,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            return todo._ask_ui(pref_key, **kw), saisie

    def test_routage(self):
        self.assertEqual(self.demander("ask", "2")[0], "cli")
        self.assertEqual(self.demander("ask", "")[0], "tui")
        for preference in ("tui", "cli"):
            choix, saisie = self.demander(preference, "2")
            self.assertEqual(choix, preference)
            self.assertFalse(saisie.called)

    def test_preferences_independantes(self):
        todo_prefs._save({"ops_settings_ui": "cli", "qemu_deploy_ui": "tui"})
        todo = nouveau_todo()
        self.assertEqual(todo._ask_ui("qemu_deploy_ui"), "tui")
        self.assertEqual(todo._ask_ui("ops_settings_ui"), "cli")

    def test_meme_question_qu_avant(self):
        from script.todo.todo_i18n import t

        _choix, saisie = self.demander("ask", "1", pref_key="qemu_deploy_ui")
        self.assertEqual(
            saisie.call_args.args[0], t("Choice (1-2, default 1): ")
        )

    def test_migration(self):
        from script.todo.todo_i18n import t
        from script.todo.todo_upgrade import TodoUpgrade

        todo_prefs._save({"migration_ui": "ask"})
        for reponse, attendu in (("3", "stats"), ("0", None), ("2", "cli")):
            with (
                mock.patch(
                    "script.todo.auto_ask.ask", return_value=reponse
                ) as demander,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(TodoUpgrade.ask_ui(), attendu)
            self.assertEqual(
                demander.call_args.args[0], t("Choice (0-3, default 1): ")
            )


class TestInstance(Base):
    def test_memorisee_par_checkout(self):
        todo_prefs._save({PREF_AUTRE: "odoo-autre.service"})
        ops_settings.OpsSettingsMixin._ops_retenir_service(SERVICE)
        memo = todo_prefs.get("ops_service")
        self.assertEqual(memo[ops_settings.RACINE], SERVICE)
        self.assertEqual(todo_prefs.get(PREF_AUTRE), "odoo-autre.service")
        self.assertEqual(nouveau_todo()._ops_service(), SERVICE)

    def test_autre_checkout_ne_compte_pas(self):
        todo_prefs._save({"ops_service": {"/srv/autre": SERVICE}})
        todo = TODO.__new__(TODO)

        def lanceur(argv, timeout=60):
            return 0, ""

        self.assertIsNone(todo._ops_service(lanceur))

    def test_choisir(self):
        def lanceur(argv, timeout=60):
            return 0, (
                "odoo-exemple.service loaded active running x\n"
                "cron.service loaded active running y\n"
            )

        todo = nouveau_todo()
        retenu, _sortie, _ = self.jouer(
            "_ops_choisir_instance", saisies=["1"], todo=todo, args=(lanceur,)
        )
        self.assertEqual(retenu, SERVICE)
        retenu, sortie, _ = self.jouer(
            "_ops_choisir_instance",
            saisies=["odoo-ailleurs"],
            todo=todo,
            args=(lanceur,),
        )
        self.assertEqual(retenu, "odoo-ailleurs.service")
        self.assertIn("[ATTN]", sortie)
        self.assertEqual(
            todo_prefs.get("ops_service")[ops_settings.RACINE],
            "odoo-ailleurs.service",
        )

    def test_un_nombre_n_est_jamais_un_nom_d_unite(self):
        """« 0 » garde l'instance retenue ; un rang hors de la liste est
        refusé. Aucun ne devient `0.service` ni `5.service`, et rien n'est
        mémorisé."""

        def lanceur(argv, timeout=60):
            return 0, "odoo-exemple.service loaded active running x\n"

        for saisie in ("0", "5"):
            with self.subTest(saisie=saisie):
                todo = nouveau_todo()
                retenu, sortie, _ = self.jouer(
                    "_ops_choisir_instance",
                    saisies=[saisie],
                    todo=todo,
                    args=(lanceur,),
                )
                self.assertEqual(retenu, SERVICE)
                self.assertEqual(
                    todo_prefs.get("ops_service")[ops_settings.RACINE],
                    SERVICE,
                )
                self.assertNotIn(f"{saisie}.service", sortie)
        self.assertIn(t_("No such number in the list."), sortie)


PREF_AUTRE = "qemu_deploy_ui"


class TestCommandes(Base):
    def test_commande_avec_profil_et_service(self):
        ecrire_profil()
        todo = nouveau_todo()
        argv = todo._ops_commande("backup", ["--dry-run"])
        self.assertEqual(
            argv[1], os.path.join("script", "database", "odoo_backup.py")
        )
        self.assertEqual(argv[2:4], ["--service", SERVICE])
        self.assertEqual(argv[4:6], ["--profile", chemin_profil()])
        self.assertTrue(os.path.isabs(argv[5]))
        self.assertEqual(argv[-1], "--dry-run")

    def test_sans_service_pour_une_url_publique(self):
        ecrire_profil()
        argv = nouveau_todo()._ops_commande(
            "health_check", ["--url", "https://erp.example.org"]
        )
        self.assertNotIn("--service", argv)
        self.assertIn("--profile", argv)
        argv = nouveau_todo()._ops_commande("health_check", ["--local"])
        self.assertIn("--service", argv)

    def test_sans_fichier_pas_de_profile(self):
        argv = nouveau_todo()._ops_commande("log_check", ["--since-last"])
        self.assertNotIn("--profile", argv)

    def test_audit_lit_le_profil_d_hote(self):
        chemin = ops_settings.chemin_hote("local")
        profil.ecrire(
            chemin,
            {
                "version": 1,
                "host": "local",
                profil.GROUPE_HOTE: {"duration": 90},
            },
        )
        self.addCleanup(os.unlink, chemin)
        argv = nouveau_todo()._ops_commande(profil.GROUPE_HOTE, [])
        self.assertEqual(argv[2:], ["--profile", chemin])

    def test_valeur_par_alias(self):
        ecrire_profil(
            instance={"db": "exemple_db"}, backup={"dest": "/srv/sauvegardes"}
        )
        todo = nouveau_todo()
        self.assertEqual(
            todo._ops_valeur("update_module", "backup_dest"),
            "/srv/sauvegardes",
        )
        self.assertEqual(todo._ops_valeur("warmup", "database"), "exemple_db")
        self.assertIsNone(todo._ops_valeur("log_check", "state_dir"))

    def test_ligne_profil(self):
        ecrire_profil(
            backup={"keep_daily": 10, "copy_to": "s@backup.example.org:/x"}
        )
        ligne = nouveau_todo()._ops_ligne_profil("backup")
        self.assertIn("--keep-daily 10", ligne)
        self.assertIn("--copy-to s@backup.example.org:/x", ligne)
        self.assertIsNone(nouveau_todo()._ops_ligne_profil("mail_retry"))

    def test_argv_audit_valide(self):
        argv = ops_settings.argv_audit(
            {profil.GROUPE_HOTE: {"duration": "10m", "no_guests": True}}
        )
        self.assertEqual(argv, ["--duration", "600", "--no-guests"])
        with self.assertRaises(profil.ErreurProfil):
            ops_settings.argv_audit(
                {profil.GROUPE_HOTE: {"duration": "1; reboot"}}
            )

    def test_slug(self):
        self.assertEqual(ops_settings.slug_hote(None), "local")
        self.assertEqual(
            ops_settings.slug_hote("root@pve.example.org"),
            "pve-root@pve.example.org",
        )
        self.assertEqual(ops_settings.slug_hote("a/b c"), "pve-a_b_c")


class TestFichiersSecrets(unittest.TestCase):
    DOC = {
        "warmup": {"login": "warmup-bot", "api_key_file": {"kdbx": REFERENCE}}
    }

    def setUp(self):
        tmpfs = tempfile.TemporaryDirectory(prefix="erplibre-tmpfs-")
        self.addCleanup(tmpfs.cleanup)
        self.tmpfs = tmpfs.name
        self.environ = {"XDG_RUNTIME_DIR": self.tmpfs}
        self.coffre = FauxCoffre({"kdbx:" + REFERENCE: SECRET})

    def bloc(self, **kw):
        kw.setdefault("coffre", self.coffre)
        kw.setdefault("environ", self.environ)
        return ops_settings.fichiers_secrets(self.DOC, "warmup", **kw)

    def test_fichier_0600_dans_le_tmpfs_puis_retire(self):
        with self.bloc() as fournis:
            option, chemin = fournis.argv
            self.assertEqual(option, "--api-key-file")
            self.assertTrue(chemin.startswith(self.tmpfs + os.sep))
            dossier = os.path.dirname(chemin)
            self.assertTrue(
                os.path.basename(dossier).startswith("erplibre-secret-")
            )
            self.assertEqual(stat.S_IMODE(os.stat(chemin).st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(os.stat(dossier).st_mode), 0o700)
            self.assertEqual(Path(chemin).read_text(), SECRET)
            self.assertNotIn(SECRET, fournis.argv)
        self.assertFalse(os.path.exists(dossier))
        self.assertEqual(os.listdir(self.tmpfs), [])

    def test_retire_apres_exception_et_ctrl_c(self):
        for erreur in (RuntimeError, KeyboardInterrupt):
            with self.subTest(erreur=erreur):
                with self.assertRaises(erreur):
                    with self.bloc() as fournis:
                        chemin = fournis.argv[1]
                        raise erreur()
                self.assertFalse(os.path.exists(chemin))
                self.assertEqual(os.listdir(self.tmpfs), [])

    def test_simulation_sans_fichier(self):
        with self.bloc(simulation=True) as fournis:
            self.assertEqual(fournis.argv, [])
            self.assertEqual(fournis.simules, ["warmup.api_key"])
        self.assertEqual(self.coffre.appels, [])
        self.assertEqual(os.listdir(self.tmpfs), [])

    def test_refus_sans_tmpfs(self):
        sortie = io.StringIO()
        with (
            mock.patch.object(ops_settings, "DEV_SHM", "/nulle/part"),
            contextlib.redirect_stdout(sortie),
            self.bloc(environ={}) as fournis,
        ):
            self.assertEqual(fournis.argv, [])
            self.assertEqual(fournis.manquants, ["warmup.api_key"])
        self.assertIn("tmpfs", sortie.getvalue())
        self.assertNotIn(SECRET, sortie.getvalue())

    def test_coffre_absent(self):
        with self.bloc(coffre=lambda: None) as fournis:
            self.assertEqual(fournis.argv, [])
            self.assertEqual(fournis.manquants, ["warmup.api_key"])
        self.assertEqual(os.listdir(self.tmpfs), [])

    def test_option_deja_sur_la_ligne(self):
        with self.bloc(
            args_lancement=["--deep", "--api-key-file=/srv/cle"]
        ) as fournis:
            self.assertEqual(fournis.argv, [])
        self.assertEqual(self.coffre.appels, [])

    def test_forme_credential(self):
        with self.bloc(forme="credential") as fournis:
            option, valeur = fournis.argv
            self.assertEqual(option, "--credential")
            self.assertTrue(valeur.startswith("warmup.api_key=" + self.tmpfs))

    def test_purge_des_restes(self):
        reste = os.path.join(self.tmpfs, "erplibre-secret-abc123")
        os.mkdir(reste)
        Path(reste, "warmup.api_key").write_text(SECRET)
        autre = os.path.join(self.tmpfs, "autre")
        os.mkdir(autre)
        with mock.patch.object(ops_settings, "DEV_SHM", "/nulle/part"):
            self.assertEqual(
                ops_settings.purger_secrets_restants(self.environ), 1
            )
            self.assertEqual(
                ops_settings.purger_secrets_restants(self.environ), 0
            )
        self.assertEqual(os.listdir(self.tmpfs), ["autre"])

    def test_dossier_nomme_par_le_pid(self):
        with self.bloc() as fournis:
            dossier = os.path.basename(os.path.dirname(fournis.argv[1]))
        self.assertTrue(
            dossier.startswith(f"erplibre-secret-{os.getpid()}-"), dossier
        )

    def test_purge_epargne_une_session_vivante(self):
        vivant = f"erplibre-secret-{os.getpid()}-abc123"
        mort = "erplibre-secret-4242424-def456"
        for nom in (vivant, mort):
            os.mkdir(os.path.join(self.tmpfs, nom))
            Path(self.tmpfs, nom, "warmup.api_key").write_text(SECRET)
        vrai_kill = os.kill

        def kill(pid, signal):
            if pid == 4242424:
                raise ProcessLookupError(pid)
            return vrai_kill(pid, signal)

        with (
            mock.patch.object(ops_settings, "DEV_SHM", "/nulle/part"),
            mock.patch.object(ops_settings.os, "kill", side_effect=kill),
        ):
            self.assertEqual(
                ops_settings.purger_secrets_restants(self.environ), 1
            )
        self.assertEqual(os.listdir(self.tmpfs), [vivant])

    def test_mixin_demande_sans_le_secret(self):
        ecrire_profil(**self.DOC)
        self.addCleanup(os.unlink, chemin_profil())
        todo_prefs._save({})
        ops_settings.OpsSettingsMixin._ops_retenir_service(SERVICE)
        todo = nouveau_todo(kdbx=None)
        sortie = io.StringIO()
        with (
            mock.patch(
                "script.todo.ops_settings.click.confirm", return_value=False
            ) as confirm,
            contextlib.redirect_stdout(sortie),
            todo._ops_fichiers_secrets(
                "warmup", ["--deep", "--local"]
            ) as fournis,
        ):
            self.assertEqual(fournis.argv, [])
            self.assertTrue(fournis.abandon)
        self.assertIs(confirm.call_args.kwargs["default"], True)
        self.assertFalse(todo.kdbx_manager.get_kdbx.called)


if __name__ == "__main__":
    unittest.main()
