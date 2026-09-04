#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Lecture d'un profil AnyConnect : les trois balises qui comptent.

Ni root, ni réseau. Le fichier est construit dans le test.

Ce que ce fichier protège : la distinction entre `<UserGroup>`, qui est un
CHEMIN D'URL et décide quel service du concentrateur on joint, et
`<HostName>`, qui n'est qu'un libellé d'affichage. Les confondre ne donne
pas une erreur de syntaxe — cela donne le formulaire d'authentification
d'un autre service, donc un refus sur des identifiants justes.
"""

import os
import sys
import tempfile
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.vpn.anyconnect_xml import (  # noqa: E402
    ProfileXmlError,
    parse,
    parse_file,
    slug,
)

# Passerelle INVENTÉE : la règle du dépôt interdit d'illustrer avec un vrai
# site, et un test fige pour toujours l'exemple qu'il choisit.
XML = """<?xml version="1.0" encoding="UTF-8"?>
<AnyConnectProfile xmlns="http://schemas.xmlsoap.org/encoding/">
    <ClientInitialization>
        <AuthenticationTimeout>12</AuthenticationTimeout>
        <LocalLanAccess UserControllable="true">true</LocalLanAccess>
    </ClientInitialization>
    <ServerList>
        <HostEntry>
            <HostName>CampusLab</HostName>
            <HostAddress>ssl.vpn.example-campus.net</HostAddress>
            <UserGroup>SSLProfileLab</UserGroup>
        </HostEntry>
    </ServerList>
</AnyConnectProfile>
"""


def with_entries(*blocks):
    inner = "".join(blocks)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<AnyConnectProfile xmlns="http://schemas.xmlsoap.org/encoding/">'
        f"<ServerList>{inner}</ServerList></AnyConnectProfile>"
    )


def entry(name="CampusLab", address="ssl.vpn.example-campus.net", group=""):
    parts = []
    if name is not None:
        parts.append(f"<HostName>{name}</HostName>")
    if address is not None:
        parts.append(f"<HostAddress>{address}</HostAddress>")
    if group is not None:
        parts.append(f"<UserGroup>{group}</UserGroup>")
    return f"<HostEntry>{''.join(parts)}</HostEntry>"


class ParseProfile(unittest.TestCase):
    def test_the_three_tags_that_matter(self):
        (preset,) = parse(XML)
        self.assertEqual(preset["label"], "CampusLab")
        self.assertEqual(preset["server"], "ssl.vpn.example-campus.net")
        self.assertEqual(preset["oc_usergroup"], "SSLProfileLab")

    def test_the_usergroup_is_not_the_authgroup(self):
        """`<UserGroup>` est un chemin d'URL (`--usergroup`), pas une valeur
        de menu déroulant (`--authgroup`). Le mettre dans le mauvais champ
        mène au formulaire d'un autre service."""
        (preset,) = parse(XML)
        self.assertEqual(preset.get("oc_authgroup", ""), "")

    def test_the_hostname_is_a_label_not_a_host(self):
        """La balise dit « HostName » et ne porte pas un nom d'hôte : c'est
        `<HostAddress>` qui le porte. Le raccourci se paie en résolution
        DNS impossible."""
        (preset,) = parse(XML)
        self.assertNotEqual(preset["label"], preset["server"])
        self.assertNotIn(".", preset["label"])

    def test_the_openconnect_driver_is_filled_in(self):
        """Le fichier ne dit pas quel client l'utilisera : le pilote et le
        protocole sont ajoutés pour que le préréglage soit complet dès sa
        lecture."""
        (preset,) = parse(XML)
        self.assertEqual(preset["driver"], "openconnect")
        self.assertEqual(preset["oc_protocol"], "anyconnect")
        self.assertEqual(preset["port"], 443)

    def test_the_client_behaviour_is_not_translated(self):
        """`ClientInitialization` décrit le client graphique de Cisco.
        Rien n'y a d'équivalent chez openconnect, et prétendre le traduire
        donnerait des champs que rien ne lit."""
        (preset,) = parse(XML)
        for absent in ("AuthenticationTimeout", "LocalLanAccess", "mtu"):
            self.assertNotIn(absent, preset)

    def test_a_file_without_a_namespace_is_read_too(self):
        """Les fichiers du parc en déclarent un, mais rien n'y oblige un
        site : les balises sont cherchées sur leur nom local."""
        naked = XML.replace(
            ' xmlns="http://schemas.xmlsoap.org/encoding/"', ""
        )
        (preset,) = parse(naked)
        self.assertEqual(preset["oc_usergroup"], "SSLProfileLab")

    def test_several_host_entries_become_several_presets(self):
        text = with_entries(
            entry("CampusLab", group="SSLProfileLab"),
            entry("CampusStaff", group="SSLProfileStaff"),
        )
        found = parse(text)
        self.assertEqual(
            [p["preset"] for p in found], ["campuslab", "campusstaff"]
        )

    def test_two_entries_with_the_same_label_stay_distinct(self):
        """Deux entrées peuvent porter le même libellé, et deux préréglages
        ne peuvent pas porter le même identifiant."""
        text = with_entries(
            entry("Campus", group="SSLProfileA"),
            entry("Campus", group="SSLProfileB"),
        )
        found = parse(text)
        self.assertEqual([p["preset"] for p in found], ["campus", "campus_2"])

    def test_an_entry_without_an_address_is_skipped_not_fatal(self):
        """Elle ne mène nulle part ; les autres restent utilisables."""
        text = with_entries(
            entry("Broken", address=None, group="SSLProfileX"),
            entry("CampusLab", group="SSLProfileLab"),
        )
        found = parse(text)
        self.assertEqual([p["preset"] for p in found], ["campuslab"])

    def test_a_usergroup_is_optional(self):
        """Un site peut n'en pas avoir : le concentrateur n'héberge alors
        qu'un service, et la racine suffit."""
        (preset,) = parse(with_entries(entry(group="")))
        self.assertEqual(preset["oc_usergroup"], "")

    def test_broken_xml_is_refused_with_a_message(self):
        with self.assertRaises(ProfileXmlError):
            parse("<AnyConnectProfile><ServerList>")

    def test_a_file_that_is_not_a_profile_is_named_as_such(self):
        with self.assertRaises(ProfileXmlError) as caught:
            parse("<?xml version='1.0'?><something><else/></something>")
        self.assertIn("HostEntry", str(caught.exception))

    def test_every_entry_without_an_address_is_refused(self):
        with self.assertRaises(ProfileXmlError):
            parse(with_entries(entry(address=None)))


class Slug(unittest.TestCase):
    """L'identifiant doit passer `NAME_RE`, quoi que porte le libellé."""

    def test_the_label_gives_the_identifier(self):
        self.assertEqual(slug("CampusLab", "ssl.vpn.example.net"), "campuslab")

    def test_spaces_and_punctuation_fold_to_underscores(self):
        self.assertEqual(
            slug("Campus Lab (SSL)", "ssl.vpn.example.net"), "campus_lab_ssl"
        )

    def test_an_unusable_label_falls_back_to_the_host(self):
        """Un libellé entièrement accentué ou vide ne doit pas rendre le
        fichier inimportable."""
        self.assertEqual(slug("", "ssl.vpn.example.net"), "ssl")
        self.assertEqual(slug("—", "gw1.vpn.example.net"), "gw1")

    def test_a_digit_leading_host_still_yields_a_valid_name(self):
        self.assertEqual(slug("", "1gw.vpn.example.net"), "1gw")


class ParseFromDisk(unittest.TestCase):
    def test_a_real_file_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "campus.xml")
            with open(path, "w") as fh:
                fh.write(XML)
            (preset,) = parse_file(path)
            self.assertEqual(preset["oc_usergroup"], "SSLProfileLab")

    def test_a_missing_file_is_refused_with_its_path(self):
        with self.assertRaises(ProfileXmlError) as caught:
            parse_file("/nowhere/campus.xml")
        self.assertIn("campus.xml", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
