#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Préréglages de site VPN : chargement, priorité, application.

Ni root, ni réseau, ni serveur VPN. Les répertoires de préréglages sont
déplacés dans un temporaire, et les trois fichiers de configuration avec eux :
un test qui lirait `private/vpn/presets/` verrait les préréglages de la
personne qui le lance, et un test qui écrirait dans le fichier privé
détruirait ses profils.

Le fichier couvre aussi la borne de longueur de mot de passe — elle n'a de
sens qu'avec un préréglage qui la porte, et c'est le seul réglage du dépôt
qui décrit le CONCENTRATEUR plutôt que le client.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.vpn import presets, profiles  # noqa: E402
from script.vpn.drivers import get_driver  # noqa: E402
from script.vpn.drivers.openconnect import OpenconnectDriver  # noqa: E402
from script.vpn.profiles import ProfileError  # noqa: E402
from script.vpn.vault import PLACEHOLDER  # noqa: E402

# Passerelle INVENTÉE. La règle du dépôt interdit de nommer une organisation
# tierce, et un test fige pour toujours l'exemple qu'il choisit : prendre un
# vrai site « parce qu'il est parlant » est exactement le réflexe à éviter.
PRESET = {
    "preset": "campus",
    "label": "Campus SSL VPN",
    "hint": "AnyConnect gateway",
    "driver": "openconnect",
    "server": "ssl.vpn.example-campus.net",
    "oc_protocol": "anyconnect",
    "oc_authgroup": "CampusSSL",
    "oc_user": "",
    "oc_password_len": 8,
}


def write_preset(directory, filename, payload):
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, filename)
    with open(path, "w") as fh:
        if isinstance(payload, str):
            fh.write(payload)
        else:
            json.dump(payload, fh)
    return path


class PresetLoading(unittest.TestCase):
    """Les répertoires de préréglages, dans un temporaire."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.shared = os.path.join(self.tmp.name, "shared")
        self.private = os.path.join(self.tmp.name, "private")
        base = os.path.join(self.tmp.name, "todo.json")
        with open(base, "w") as fh:
            json.dump({"vpn": []}, fh)
        self.patches = [
            patch(
                "script.vpn.presets.PRESET_DIRS",
                (self.shared, self.private),
            ),
            patch("script.config.config_file.CONFIG_FILE", base),
            patch(
                "script.config.config_file.CONFIG_OVERRIDE_FILE",
                os.path.join(self.tmp.name, "override.json"),
            ),
            patch(
                "script.config.config_file.CONFIG_OVERRIDE_PRIVATE_FILE",
                os.path.join(self.tmp.name, "private.json"),
            ),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.tmp.cleanup()

    def test_a_directory_is_read(self):
        write_preset(self.shared, "campus.json", PRESET)
        found, errors = presets.load_all()
        self.assertEqual(errors, [])
        self.assertEqual([p["preset"] for p in found], ["campus"])
        self.assertEqual(found[0]["server"], PRESET["server"])

    def test_a_file_can_hold_several_presets(self):
        """Un site qui en distribue trois n'a pas à ouvrir trois fichiers."""
        write_preset(
            self.shared,
            "many.json",
            [PRESET, dict(PRESET, preset="campus_lab", label="Lab")],
        )
        found, errors = presets.load_all()
        self.assertEqual(errors, [])
        self.assertEqual(
            sorted(p["preset"] for p in found), ["campus", "campus_lab"]
        )

    def test_the_latest_directory_wins(self):
        """C'est ce qui permet de corriger un gabarit du dépôt — passerelle
        déménagée, groupe renommé — sans toucher un fichier suivi par git,
        donc sans conflit au prochain `git pull`."""
        write_preset(self.shared, "campus.json", PRESET)
        write_preset(
            self.private,
            "campus.json",
            dict(PRESET, server="ssl2.vpn.example-campus.net"),
        )
        found, _ = presets.load_all()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["server"], "ssl2.vpn.example-campus.net")

    def test_a_broken_file_does_not_hide_the_others(self):
        """Sinon la panne se lit « aucun préréglage » alors qu'il y en a
        dix, et on cherche du côté du répertoire."""
        write_preset(self.shared, "broken.json", "{ pas du JSON")
        write_preset(self.shared, "campus.json", PRESET)
        found, errors = presets.load_all()
        self.assertEqual([p["preset"] for p in found], ["campus"])
        self.assertEqual(len(errors), 1)
        self.assertIn("broken.json", errors[0])

    def test_a_refused_identifier_is_named(self):
        write_preset(self.shared, "bad.json", dict(PRESET, preset="Campus!"))
        found, errors = presets.load_all()
        self.assertEqual(found, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("Campus!", errors[0])

    def test_extra_directories_come_from_the_configuration(self):
        """Un dépôt privé cloné ailleurs qu'au point de montage."""
        elsewhere = os.path.join(self.tmp.name, "elsewhere")
        write_preset(elsewhere, "campus.json", PRESET)
        with open(os.path.join(self.tmp.name, "override.json"), "w") as fh:
            json.dump({"vpn_preset_paths": [elsewhere]}, fh)
        found, errors = presets.load_all()
        self.assertEqual(errors, [])
        self.assertEqual([p["preset"] for p in found], ["campus"])

    def test_a_missing_directory_is_not_an_error(self):
        """Le cas normal : `private/vpn/presets/` n'existe pas encore."""
        found, errors = presets.load_all()
        self.assertEqual((found, errors), ([], []))

    def test_load_finds_one_by_identifier(self):
        write_preset(self.shared, "campus.json", PRESET)
        self.assertEqual(presets.load("campus")["server"], PRESET["server"])
        self.assertIsNone(presets.load("nowhere"))


class PresetApplication(unittest.TestCase):
    """`apply` : d'un préréglage à un profil que la validation accepte."""

    def test_the_identity_is_what_is_still_missing(self):
        """Un préréglage sans identifiant est refusé, et c'est le contrat :
        `apply` rend un profil INCOMPLET, le formulaire demande le reste.
        Le valider tel quel passerait à côté de ce que le préréglage
        promet — tout sauf ce qui est personnel."""
        with self.assertRaises(ProfileError):
            profiles.validate(presets.apply(PRESET, "campus_me"))

    def test_it_validates_once_the_identity_is_given(self):
        profile = presets.apply(PRESET, "campus_me")
        profile["oc_user"] = "someone"
        clean = profiles.validate(profile)
        self.assertEqual(clean["name"], "campus_me")
        self.assertEqual(clean["oc_authgroup"], "CampusSSL")

    def test_the_description_keys_are_dropped(self):
        """`preset`, `label` et `hint` nomment le préréglage. Laissés dans
        le profil, ils seraient écrits dans la configuration et traîneraient
        là sans que rien ne les lise."""
        profile = presets.apply(PRESET, "campus_me")
        for key in presets.META_KEYS:
            self.assertNotIn(key, profile)

    def test_what_is_personal_stays_empty(self):
        """Un préréglage ne porte ni identifiant ni secret : c'est ce qui
        lui permet de se distribuer. Ce qui manque est donc ce que le
        formulaire demande ensuite."""
        profile = presets.apply(PRESET, "campus_me")
        self.assertEqual(profile["oc_user"], "")

    def test_the_driver_defaults_are_filled_in(self):
        profile = presets.apply(PRESET, "campus_me")
        self.assertEqual(profile["port"], 443)
        self.assertFalse(profile["oc_sso"])

    def test_a_preset_without_a_label_is_still_choosable(self):
        self.assertEqual(presets.label({"preset": "campus"}), "campus")
        self.assertEqual(presets.label(PRESET), "Campus SSL VPN")


class ShippedPresets(unittest.TestCase):
    """Garde-fou sur ce que le dépôt livre dans `conf/vpn_presets/`.

    Un gabarit cassé se verrait autrement chez l'utilisateur, au moment où
    il essaie de s'en servir.
    """

    def test_every_shipped_preset_validates(self):
        """Chaque gabarit livré donne un profil valide dès qu'on lui donne
        l'identifiant que le formulaire demanderait. L'identité est remplie
        par le champ que le PILOTE désigne : le garde-fou reste vrai pour un
        gabarit d'une autre technologie."""
        with patch("script.vpn.presets.PRESET_DIRS", ("./conf/vpn_presets",)):
            found, errors = presets.load_all()
        self.assertEqual(errors, [])
        self.assertTrue(found, "aucun gabarit livré")
        for preset in found:
            with self.subTest(preset=preset["preset"]):
                profile = presets.apply(preset, "shipped_check")
                driver_cls = get_driver(profile["driver"])
                self.assertIsNotNone(
                    driver_cls, f"pilote inconnu : {profile['driver']}"
                )
                if driver_cls.user_field:
                    profile[driver_cls.user_field] = "someone"
                profiles.validate(profile)


class PasswordLengthLimit(unittest.TestCase):
    """La borne que certains concentrateurs imposent au mot de passe.

    Elle est INFORMATIVE : le coffre reste la source de vérité de ce qui
    part. Un outil qui tronquerait en silence rendrait indébrouillable le
    jour où le site lève la limite.
    """

    def mount(self, secret, dry_run=False):
        """Le pilote monté jusqu'à la commande, prérequis court-circuités.

        `ensure_ready` juge les binaires de la machine : le laisser décider
        ferait passer ce test là où openconnect est installé et échouer
        ailleurs, alors que ce qui est en jeu est la décision du PILOTE.
        """
        driver = OpenconnectDriver(self.profile(), {"password": secret})
        runner = FakeRunner(dry_run=dry_run)
        with patch.object(
            OpenconnectDriver, "ensure_ready", return_value=True
        ):
            with redirect_stdout(io.StringIO()):
                driver.up(runner)
        return runner

    def profile(self, **overrides):
        base = {
            "name": "campus",
            "driver": "openconnect",
            "server": "ssl.vpn.example-campus.net",
            "oc_user": "someone",
            "oc_password_len": 8,
        }
        base.update(overrides)
        return profiles.with_defaults(base)

    def test_zero_means_no_limit(self):
        profile = self.profile(oc_password_len=0)
        self.assertEqual(profiles.validate(profile)["oc_password_len"], 0)
        self.assertEqual(OpenconnectDriver(profile).secret_notes(), [])

    def test_out_of_bounds_is_refused(self):
        for value in (-1, 129):
            with self.subTest(value=value):
                with self.assertRaises(ProfileError):
                    profiles.validate(self.profile(oc_password_len=value))

    def test_the_note_is_rendered_before_the_prompt(self):
        notes = OpenconnectDriver(self.profile()).secret_notes()
        self.assertEqual(len(notes), 1)
        self.assertIn("8", notes[0])

    def test_sso_gets_no_note(self):
        """En SSO il n'y a aucun mot de passe à déposer : une consigne sur
        sa longueur y serait sans objet."""
        profile = self.profile(oc_sso=True, oc_user="")
        self.assertEqual(OpenconnectDriver(profile).secret_notes(), [])

    def test_the_password_is_warned_about_but_sent_whole(self):
        runner = self.mount("0123456789")
        self.assertTrue(
            any("10" in w and "8" in w for w in runner.warnings),
            runner.warnings,
        )
        self.assertEqual(runner.stdin, "0123456789\n")

    def test_a_short_enough_password_says_nothing(self):
        self.assertEqual(self.mount("01234567").warnings, [])

    def test_sso_closes_standard_input(self):
        """En SSO, openconnect n'attend rien sur l'entrée standard — il
        attend la redirection sur son port. Mais un concentrateur qui ne
        fait PAS de SSO répond par un formulaire mot de passe, et
        openconnect se met à le demander sur le terminal, sans que
        `--non-inter` soit là pour l'en empêcher. Une entrée standard
        FERMÉE transforme cette boucle de cinq minutes en échec immédiat.
        """
        profile = self.profile(oc_sso=True, oc_user="")
        driver = _NoHelper(profile, {})
        runner = FakeRunner()
        with patch.object(
            OpenconnectDriver, "ensure_ready", return_value=True
        ):
            with redirect_stdout(io.StringIO()):
                driver.up(runner)
        self.assertEqual(runner.stdin, "")

    def test_the_dry_run_placeholder_is_not_judged(self):
        """En mode à blanc sans coffre joignable, le secret est un marqueur.
        Le mesurer rendrait un verdict sur une valeur qui n'est pas celle de
        l'utilisateur."""
        runner = self.mount(PLACEHOLDER, dry_run=True)
        self.assertEqual(runner.warnings, [])


class _NoHelper(OpenconnectDriver):
    """Le pilote sans greffon SSO, quoi que porte la machine.

    L'attribut de classe masque la propriété du parent, qui chercherait
    openconnect-sso dans le PATH — et le test passerait ou non selon ce qui
    est installé là où la suite tourne.
    """

    sso_helper = ""


class ConnectionGroups(unittest.TestCase):
    """Les deux « groupes » d'openconnect, et leurs deux options.

    `--usergroup` pose le chemin d'URL, `--authgroup` choisit dans un menu
    déroulant. Les confondre ne donne pas une erreur de syntaxe : cela
    donne le formulaire d'authentification d'un AUTRE service, donc un
    refus d'identifiants sur des identifiants justes. C'est ce que ce test
    empêche de réintroduire.
    """

    def profile(self, **overrides):
        base = {
            "name": "campus",
            "driver": "openconnect",
            "server": "ssl.vpn.example-campus.net",
            "oc_user": "someone",
        }
        base.update(overrides)
        return profiles.validate(profiles.with_defaults(base))

    def test_the_usergroup_becomes_the_url_path_option(self):
        command = OpenconnectDriver(
            self.profile(oc_usergroup="SSLProfileLab")
        ).command()
        self.assertIn("--usergroup=SSLProfileLab", command)
        self.assertNotIn("--authgroup", command)

    def test_the_authgroup_stays_the_dropdown_option(self):
        command = OpenconnectDriver(
            self.profile(oc_authgroup="CampusSSL")
        ).command()
        self.assertIn("--authgroup=CampusSSL", command)
        self.assertNotIn("--usergroup", command)

    def test_both_can_coexist(self):
        """Un site peut exiger le chemin ET un choix dans la liste."""
        command = OpenconnectDriver(
            self.profile(oc_usergroup="SSLProfileLab", oc_authgroup="Staff")
        ).command()
        self.assertIn("--usergroup=SSLProfileLab", command)
        self.assertIn("--authgroup=Staff", command)

    def test_neither_appears_when_empty(self):
        command = OpenconnectDriver(self.profile()).command()
        self.assertNotIn("group", command)

    def test_a_multi_segment_path_is_accepted(self):
        clean = self.profile(oc_usergroup="tunnel/lab")
        self.assertEqual(clean["oc_usergroup"], "tunnel/lab")

    def test_what_would_break_a_url_or_a_shell_is_refused(self):
        for bad in (
            "/leading",
            "trailing/",
            "with space",
            "a?b",
            "a#b",
            "../etc",
            "a;rm -rf",
            "a&b",
        ):
            with self.subTest(value=bad):
                with self.assertRaises(ProfileError):
                    self.profile(oc_usergroup=bad)


class DelegatedSso(unittest.TestCase):
    """SSO délégué : le greffon authentifie, le PILOTE monte.

    C'est toute la valeur du dispositif. Un tunnel monté par le greffon
    lui-même s'appellerait `tun0`, ne laisserait aucun état dans /run, et
    `status`, `diagnose` et `down` ne le verraient pas. Ces tests vérifient
    que la frontière tient : le greffon ne rend qu'un cookie, le reste
    vient du profil.
    """

    # Un exécutable qui existe partout : ce qui est testé est la DÉCISION
    # du pilote, pas openconnect-sso.
    HELPER = "/bin/echo"

    def driver(self, **overrides):
        base = {
            "name": "campus",
            "driver": "openconnect",
            "server": "ssl.vpn.example-campus.net",
            "oc_sso": True,
            "oc_user": "",
            "oc_usergroup": "SSLProfileLab",
            "oc_sso_helper": self.HELPER,
        }
        base.update(overrides)
        return OpenconnectDriver(profiles.validate(base), {})

    # -- la ligne du greffon ------------------------------------------
    def test_the_helper_gets_the_url_path_appended_to_the_host(self):
        """`--server hôte/chemin` : c'est la forme que le greffon accepte,
        et le chemin décide QUEL service du concentrateur on joint."""
        command = self.driver().helper_command()
        self.assertIn(
            "--server=ssl.vpn.example-campus.net/SSLProfileLab", command
        )

    def test_the_helper_line_carries_no_secret(self):
        command = self.driver().helper_command()
        self.assertNotIn("cookie", command.lower())
        self.assertIn("--authenticate json", command)

    def test_the_announced_identity_is_the_same_on_both_steps(self):
        """Le concentrateur délivre le cookie à un client qui s'est
        présenté sous une version donnée ; monter sous une autre le fait
        refuser. Les deux lignes doivent donc porter la MÊME."""
        driver = self.driver(oc_ac_version="4.10.07061")
        self.assertIn("--ac-version=4.10.07061", driver.helper_command())
        mount = driver.cookie_command("")
        self.assertIn("--version-string=4.10.07061", mount)
        self.assertIn("AnyConnect Linux_64 4.10.07061", mount)

    def test_the_render_flags_are_dropped_when_already_set(self):
        """Qui a posé ces variables sait mieux que ce pilote."""
        with patch.dict(
            os.environ, {"LIBGL_ALWAYS_SOFTWARE": "0"}, clear=False
        ):
            command = self.driver().helper_command()
        self.assertNotIn("LIBGL_ALWAYS_SOFTWARE=", command)
        self.assertIn("QTWEBENGINE_CHROMIUM_FLAGS=", command)

    # -- la ligne de montage ------------------------------------------
    def test_the_cookie_never_reaches_the_command_line(self):
        """`/proc/<pid>/cmdline` est lisible par tout utilisateur de la
        machine, et ce cookie ouvre le tunnel à lui seul."""
        command = self.driver().cookie_command("sha256:aa")
        self.assertIn("--cookie-on-stdin", command)
        self.assertNotIn("--cookie=", command)

    def test_the_profile_owns_the_interface_and_the_pid_file(self):
        command = self.driver().cookie_command("")
        self.assertIn("--interface=vpn-campus", command)
        self.assertIn("--pid-file=/run/erplibre-vpn/campus.pid", command)

    def test_the_helper_fingerprint_wins_over_the_profile(self):
        """Le greffon rend l'empreinte contre laquelle il a AUTHENTIFIÉ ;
        celle du profil peut dater."""
        driver = self.driver(oc_servercert="sha256:vieille")
        command = driver.cookie_command("sha256:fraiche")
        self.assertIn("--servercert=sha256:fraiche", command)
        self.assertNotIn("vieille", command)

    def test_the_profile_fingerprint_serves_when_the_helper_gives_none(self):
        driver = self.driver(oc_servercert="sha256:duprofil")
        self.assertIn(
            "--servercert=sha256:duprofil", driver.cookie_command("")
        )

    # -- le déroulé ----------------------------------------------------
    def test_the_cookie_is_masked_as_soon_as_it_exists(self):
        """Il naît en cours de route : le masquage monté au démarrage ne le
        connaît pas, et il va traverser des affichages."""
        driver = self.driver()
        runner = FakeRunner()
        runner.stdout = '{"host": "h", "cookie": "S3cr3t-C00k13-long", '
        runner.stdout += '"fingerprint": "sha256:aa"}'
        with patch.object(
            OpenconnectDriver, "ensure_ready", return_value=True
        ):
            with redirect_stdout(io.StringIO()):
                driver.up(runner)
        self.assertEqual(runner.stdin, "S3cr3t-C00k13-long\n")
        self.assertNotIn(
            "S3cr3t-C00k13-long", runner.redactor("S3cr3t-C00k13-long")
        )

    def test_the_helper_runs_without_sudo(self):
        """Il ouvre un navigateur : sous sudo il perdrait l'affichage et le
        trousseau de l'utilisateur."""
        driver = self.driver()
        runner = FakeRunner()
        runner.stdout = '{"host": "h", "cookie": "abcdefghij"}'
        with patch.object(
            OpenconnectDriver, "ensure_ready", return_value=True
        ):
            with redirect_stdout(io.StringIO()):
                driver.up(runner)
        helper_calls = [
            call
            for call in runner.calls
            if "openconnect-sso" in call["cmd"] or "/bin/echo" in call["cmd"]
        ]
        self.assertTrue(helper_calls, runner.calls)
        self.assertIs(helper_calls[0]["sudo"], False)

    def test_the_json_is_extracted_from_output_mixed_with_logs(self):
        """Le processus navigateur du greffon journalise sur sa SORTIE
        STANDARD, mêlée au JSON final. `json.loads` sur le tout échoue même
        quand l'authentification a RÉUSSI — c'est ce qui rendait
        l'intégration inopérante, et aucun test ne le voyait parce qu'ils
        nourrissaient tous un JSON propre.
        """
        mixed = (
            "2026-01-01 [info ] Browser started"
            " startup_info=StartupInfo(url='https://gw/x')\n"
            "2026-01-01 [debug] Cookie set name=JSESSIONID\n"
            '{\n    "host": "https://gw/Grp",\n'
            '    "cookie": "le-cookie-de-session",\n'
            '    "fingerprint": "pin-sha256:abc"\n}\n'
        )
        answer = OpenconnectDriver.extract_json(mixed)
        self.assertEqual(answer["cookie"], "le-cookie-de-session")
        self.assertEqual(answer["fingerprint"], "pin-sha256:abc")

    def test_the_last_object_wins_over_a_brace_in_a_log_line(self):
        text = '{"cookie": "vieux"}\nbruit {pas du json}\n{"cookie": "neuf"}'
        self.assertEqual(
            OpenconnectDriver.extract_json(text)["cookie"], "neuf"
        )

    def test_an_object_without_a_cookie_is_not_an_answer(self):
        self.assertIsNone(OpenconnectDriver.extract_json('{"host": "h"}'))
        self.assertIsNone(OpenconnectDriver.extract_json("rien"))

    def test_the_helper_output_stays_visible(self):
        """Capturer sans dupliquer laisse l'utilisateur devant un terminal
        muet pendant qu'une fenêtre attend son geste."""
        self.assertTrue(
            self.driver().helper_command().endswith("| tee /dev/stderr")
        )

    def test_a_timeout_says_what_expired(self):
        """Un délai dépassé n'est pas un refus d'identifiants : le dire
        ferait chercher un mot de passe là où il manquait un geste."""
        driver = self.driver()
        runner = FakeRunner()
        runner.stdout = ""
        runner.capture_code = 124
        with patch.object(
            OpenconnectDriver, "ensure_ready", return_value=True
        ):
            with redirect_stdout(io.StringIO()):
                self.assertFalse(driver.up(runner))
        self.assertTrue(
            any("délai" in f for f in runner.failures), runner.failures
        )

    def test_strays_are_closed_after_a_failure(self):
        """Le greffon laisse ses navigateurs derrière lui quand il est tué,
        et le suivant repartirait sur une machine encombrée."""
        driver = self.driver()
        runner = FakeRunner()
        runner.stdout = ""
        with patch.object(
            OpenconnectDriver, "ensure_ready", return_value=True
        ):
            with redirect_stdout(io.StringIO()):
                driver.up(runner)
        self.assertTrue(
            any("pkill" in call["cmd"] for call in runner.calls),
            runner.calls,
        )

    def test_the_interface_is_awaited_not_merely_observed(self):
        """`--background` fait sortir openconnect dès la session ouverte ;
        `vpnc-script` crée l'interface un instant PLUS TARD. Constater tout
        de suite déclare absent un tunnel qui monte — et accuse
        `vpnc-script` d'être absent alors qu'il travaille.

        Le montage réel est tombé exactement là : le tunnel portait son
        adresse, et l'outil annonçait « montage incomplet » sans écrire son
        fichier d'état, si bien que `status` le croyait déconnecté.
        """
        driver = self.driver()
        runner = FakeRunner()
        runner.stdout = '{"host": "h", "cookie": "un-cookie-valide"}'
        runner.code = 0  # le montage réussit
        # Adresse INVENTÉE, dans la plage documentaire que le dépôt
        # reconnaît : un test fige pour toujours l'exemple qu'il
        # choisit, et prendre celle qu'un concentrateur venait
        # d'attribuer est exactement le réflexe que la règle combat.
        appearances = [[], [], ["192.0.2.10"]]

        def slowly(iface, timeout=25, interval=0.5):
            # L'interface n'apparaît qu'au troisième regard.
            for value in appearances:
                if value:
                    return value
                appearances.pop(0)
            return []

        with patch.object(
            OpenconnectDriver, "ensure_ready", return_value=True
        ):
            with patch(
                "script.vpn.drivers.openconnect." "wait_for_interface_address",
                side_effect=slowly,
            ) as waited:
                with redirect_stdout(io.StringIO()):
                    self.assertTrue(driver.up(runner))
        self.assertTrue(waited.called, "l'interface n'est pas ATTENDUE")
        self.assertFalse(runner.failures, runner.failures)
        self.assertIn(
            "iface", [w["key"] for w in runner.states], runner.states
        )

    def test_a_truly_absent_interface_is_still_a_failure(self):
        """L'attente ne doit pas rendre le diagnostic muet : une interface
        qui n'arrive JAMAIS reste une panne, et vpnc-script en est la
        cause la plus fréquente."""
        driver = self.driver()
        runner = FakeRunner()
        runner.stdout = '{"host": "h", "cookie": "un-cookie-valide"}'
        runner.code = 0  # le montage réussit
        with patch.object(
            OpenconnectDriver, "ensure_ready", return_value=True
        ):
            with patch(
                "script.vpn.drivers.openconnect." "wait_for_interface_address",
                return_value=[],
            ):
                with patch(
                    "script.vpn.drivers.openconnect.interface_exists",
                    return_value=False,
                ):
                    with redirect_stdout(io.StringIO()):
                        self.assertFalse(driver.up(runner))
        self.assertTrue(
            any("vpnc-script" in f for f in runner.failures),
            runner.failures,
        )

    def test_unparsable_helper_output_is_refused(self):
        driver = self.driver()
        runner = FakeRunner()
        runner.stdout = "ce n'est pas du JSON"
        with patch.object(
            OpenconnectDriver, "ensure_ready", return_value=True
        ):
            with redirect_stdout(io.StringIO()):
                self.assertFalse(driver.up(runner))
        self.assertTrue(runner.failures)

    def test_a_declared_helper_that_cannot_run_is_named(self):
        """Basculer en silence sur l'autre chemin ferait échouer le montage
        sur « No SSO handler », trois étages au-dessus de la vraie cause."""
        driver = self.driver(oc_sso_helper="/nowhere/openconnect-sso")
        runner = FakeRunner()
        with patch.object(
            OpenconnectDriver, "ensure_ready", return_value=True
        ):
            with redirect_stdout(io.StringIO()):
                self.assertFalse(driver.up(runner))
        self.assertTrue(
            any("/nowhere/openconnect-sso" in f for f in runner.failures),
            runner.failures,
        )


class FakeRunner:
    """Un exécuteur qui n'exécute rien et retient ce qu'on lui a passé.

    Le vrai `Runner` appelle sudo et lance openconnect : ce test porte sur
    ce que le pilote DÉCIDE, pas sur ce que la machine fait.
    """

    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.quiet = False
        self.failures = []
        self.warnings = []
        self.stdin = None
        # Ce que la prochaine commande capturée rendra sur sa sortie, et la
        # trace de tous les appels : le SSO délégué se juge sur ce que le
        # pilote DEMANDE, pas sur ce que la machine ferait.
        self.stdout = ""
        self.capture_code = 0
        # Code des commandes NON capturées — le montage. Non nul par
        # défaut : la plupart des tests n'ont rien à vérifier après lui, et
        # le laisser réussir les ferait attendre une interface qui
        # n'existera jamais sur la machine de test.
        self.code = 1
        self.calls = []
        self.states = []
        self.redactor = lambda text: text

    def add_secret(self, value):
        value = str(value or "")
        if len(value) < 8:
            return
        previous = self.redactor
        self.redactor = lambda text: previous(text).replace(value, "***")

    def info(self, message):
        pass

    def ok(self, message):
        pass

    def warn(self, message):
        self.warnings.append(message)

    def fail(self, message):
        self.failures.append(message)

    def propose(self, constat, command, sudo=True, question=None):
        return False

    def mkdir(self, path, mode):
        pass

    def write(self, path, content, mode=None):
        # Les fichiers d'état sont nommés « <profil>.<clé> » : c'est ce que
        # `status` relit dans un autre processus, donc ce qu'un test doit
        # pouvoir vérifier.
        self.states.append(
            {"key": path.rsplit(".", 1)[-1], "path": path, "value": content}
        )

    def remove(self, path):
        pass

    def cmd(self, label, command, **kwargs):
        self.calls.append(
            {
                "label": label,
                "cmd": command,
                "sudo": kwargs.get("sudo"),
                "capture": kwargs.get("capture"),
                "secret_stdin": kwargs.get("secret_stdin", False),
            }
        )
        if "stdin" in kwargs:
            self.stdin = kwargs["stdin"]
        if kwargs.get("capture"):
            # Le greffon rend ce qu'on lui a fait dire, sous le code qu'on
            # lui a fait rendre.
            return self.capture_code, self.stdout
        return self.code, ""


if __name__ == "__main__":
    unittest.main()
