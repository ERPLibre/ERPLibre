#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Installation hors ligne de l'ISO : le service du live
(erplibre_offline), son branchement dans le cœur, l'interface, l'étape
ERPLibre (erplibre-stage.sh), et la fabrique du paquet côté hôte
(offline_payload).

Tout est hermétique : les manifestes, profils, adresses de dépôt,
empreintes et certificats sont INVENTÉS ; aucune commande du système
n'est lancée hors bash, sur des fichiers temporaires.
"""

import base64
import io
import json
import os
import re
import subprocess
import tarfile
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from test import iso_installer_modules as m
from test import test_iso_installer_core as ct

mp, facts, dk, ai, pl, ei = m.load()
import erplibre_offline as om  # noqa: E402
import erplibre_ui_flow as flow  # noqa: E402
import erplibre_ui_i18n as i18n  # noqa: E402

STAGE = m.SHARE_DIR / "erplibre-stage.sh"
GO_MAIN = m.REPO / "script" / "qemu_cache" / "main.go"
PAYLOAD_TOOL = m.ARCHLINUX / "offline_payload.py"

FAUX_PEM = (
    "-----BEGIN CERTIFICATE-----\n"
    "TUlJQ2ludmVudMOpcG91cmxlc3Rlc3Rz\n"
    "-----END CERTIFICATE-----\n"
)
FAUX_COMMIT = "0123456789abcdef0123456789abcdef01234567"
FAUX_SHA = "ab" * 32


def manifest(**extra):
    doc = {
        "schema": 1,
        "erplibre_profile": "odoo18",
        "created": "2001-02-03T04:05:06Z",
        "arch": "x86_64",
        "erplibre": {
            "git_url": "https://forge.example.invalid/erplibre",
            "branch": "branche-inventee",
            "commit": FAUX_COMMIT,
        },
        "archinstall_version": "4.5.1",
        "arch_snapshot": "2001-02-01",
        "proxy_version": "0.0.0",
        "parts": {
            "proxy": {
                "path": "bin/erplibre_go_qemu_cache",
                "sha256": FAUX_SHA,
            },
            "ca_cert": {"path": "ca/ca.crt", "sha256": FAUX_SHA},
            "ca_key": {"path": "ca/ca.key", "sha256": FAUX_SHA},
            "repo": {"path": "repo", "size": 1, "files": 1},
            "store": {"path": "store", "size": 1, "files": 1},
        },
    }
    doc.update(extra)
    return doc


def bash(script, env=None):
    """Lance `script` après avoir sourcé l'étape ERPLibre ; rend la
    sortie standard."""
    res = subprocess.run(
        ["bash", "-c", f"source {STAGE}\n{script}"],
        capture_output=True,
        text=True,
        env=dict(os.environ, **(env or {})),
        check=False,
    )
    if res.returncode != 0:
        raise AssertionError(res.stderr)
    return res.stdout


def make_db(path, paquets, signed=()):
    """Une base pacman inventée : paquets = {nom: (fichier, provides,
    groupes)} ; `signed` porte une signature (%PGPSIG%) inventée."""
    with tarfile.open(path, "w:gz") as tar:
        for nom, (fichier, fournis, groupes) in paquets.items():
            desc = f"%FILENAME%\n{fichier}\n\n%NAME%\n{nom}\n\n"
            if nom in signed:
                desc += "%PGPSIG%\nc2lnbmF0dXJlIGludmVudMOpZQ==\n\n"
            if fournis:
                desc += "%PROVIDES%\n" + "\n".join(fournis) + "\n\n"
            if groupes:
                desc += "%GROUPS%\n" + "\n".join(groupes) + "\n\n"
            data = desc.encode()
            info = tarfile.TarInfo(f"{nom}-1.0-1/desc")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


class TestManifest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(om.check_manifest(manifest()), [])

    def test_refusals(self):
        cas = {
            "schema": manifest(schema=2),
            "erplibre.commit": manifest(
                erplibre={"git_url": "u", "branch": "b", "commit": "court"}
            ),
            "arch": manifest(arch="aarch64"),
            "created": manifest(created="hier"),
        }
        for cle, doc in cas.items():
            erreurs = om.check_manifest(doc)
            self.assertTrue(
                any(e.startswith(cle) for e in erreurs), (cle, erreurs)
            )
        doc = manifest()
        doc["parts"]["proxy"]["path"] = "../dehors"
        self.assertIn(
            "parts.proxy.path: relative path required",
            om.check_manifest(doc),
        )
        doc = manifest()
        doc["parts"]["ca_key"]["path"] = "/etc/absolu"
        self.assertTrue(om.check_manifest(doc))
        doc = manifest()
        del doc["parts"]["store"]
        self.assertIn("parts.store: missing", om.check_manifest(doc))
        doc = manifest()
        doc["parts"]["proxy"].pop("sha256")
        self.assertIn("parts.proxy.sha256: required", om.check_manifest(doc))
        self.assertEqual(om.check_manifest([]), ["manifest: not an object"])

    def test_match_profile(self):
        self.assertEqual(
            om.match_profile(manifest(), "home"),
            (False, "profile-mismatch", []),
        )
        self.assertEqual(
            om.match_profile(manifest(), "odoo18", "4.5.1"), (True, None, [])
        )
        self.assertEqual(
            om.match_profile(manifest(), "odoo18", "9.9"),
            (True, None, ["archinstall-mismatch"]),
        )
        self.assertEqual(
            om.match_profile(manifest(), "odoo18", "4.5.7"), (True, None, [])
        )
        # La commande du profil : comparée si le manifeste l'a, sinon dite.
        avec = manifest()
        avec["erplibre"][om.COMMAND_KEY] = om.command_sha256("make essai")
        self.assertEqual(
            om.match_profile(avec, "odoo18", None, "make essai"),
            (True, None, []),
        )
        self.assertEqual(
            om.match_profile(avec, "odoo18", None, "make autre"),
            (False, "profile-command-mismatch", []),
        )
        self.assertEqual(
            om.match_profile(manifest(), "odoo18", None, "make essai"),
            (True, None, ["profile-command-unrecorded"]),
        )
        # Sans commande donnée (start, TODO), rien n'est comparé.
        self.assertEqual(om.match_profile(avec, "odoo18"), (True, None, []))
        avec["erplibre"][om.COMMAND_KEY] = "pas-une-empreinte"
        self.assertIn(
            f"erplibre.{om.COMMAND_KEY}: sha256 required",
            om.check_manifest(avec),
        )
        self.assertEqual(om.manifest_label(manifest()), "odoo18, 2001-02-03")

    def test_data_devices(self):
        lsblk = {
            "blockdevices": [
                {
                    "path": "/dev/sdz",
                    "children": [
                        {"path": "/dev/sdz1", "label": "ARCH_200102"},
                        {
                            "path": "/dev/sdz3",
                            "label": "ERPLIBRE_DATA",
                            "fstype": "ext4",
                        },
                    ],
                },
                {
                    "path": "/dev/sdy1",
                    "label": "ERPLIBRE_DATA",
                    "fstype": "vfat",
                },
            ]
        }
        self.assertEqual(om.data_devices(lsblk), ["/dev/sdz3"])
        self.assertEqual(om.data_devices({}), [])


class TestBuilders(unittest.TestCase):
    def test_nft_ruleset(self):
        texte = om.nft_ruleset(uid=4242, http_port=1080, tls_port=1443)
        lignes = texte.splitlines()
        # Remplacement atomique : déclarer, effacer, redéfinir.
        self.assertEqual(lignes[0], "table inet erplibre_offline")
        self.assertEqual(lignes[1], "delete table inet erplibre_offline")
        self.assertIn("meta skuid 4242 return", texte)
        self.assertIn(
            "meta nfproto ipv4 tcp dport 80 redirect to :1080", texte
        )
        self.assertIn(
            "meta nfproto ipv4 tcp dport 443 redirect to :1443", texte
        )
        self.assertIn("ip daddr 127.0.0.0/8 return", texte)
        self.assertIn("meta nfproto ipv6 tcp dport { 80, 443 } reject", texte)
        # L'exemption du mandataire précède chaque détournement.
        nat = texte.index("chain sortie_nat")
        self.assertLess(
            texte.index("meta skuid 4242", nat), texte.index("redirect", nat)
        )
        self.assertEqual(
            om.nft_delete_argv(),
            ["nft", "delete", "table", "inet", "erplibre_offline"],
        )

    def test_dns(self):
        texte = om.resolved_dropin("127.0.0.1")
        for ligne in ("DNS=127.0.0.1", "Domains=~.", "DNSSEC=no", "Cache=no"):
            self.assertIn(ligne, texte.splitlines())
        argv = om.dnsmasq_argv(fake="198.18.0.9", listen="127.0.0.1")
        self.assertIn("--address=/#/198.18.0.9", argv)
        self.assertIn("--listen-address=127.0.0.1", argv)
        self.assertIn("--no-resolv", argv)
        self.assertIn("--bind-interfaces", argv)

    def test_proxy_argv_flags_exist_in_go(self):
        """Chaque option passée au mandataire est déclarée dans main.go :
        les deux côtés ne dérivent pas."""
        argv = om.proxy_argv("/bin/x", "/data", "/ca", "/log")
        source = GO_MAIN.read_text(encoding="utf-8")
        declarees = set(re.findall(r'flag\.\w+\(\s*"([a-z-]+)"', source))
        for opt in [a[2:] for a in argv if a.startswith("--")]:
            self.assertIn(opt, declarees)
        self.assertIn("--hors-ligne", argv)
        self.assertEqual(argv[argv.index("--ecoute") + 1], "127.0.0.1")
        self.assertEqual(argv[argv.index("--depot-pacman") + 1], "/data/repo")
        self.assertEqual(
            argv[argv.index("--git-mirror-dir") + 1], "/data/store/git"
        )

    def test_systemd_run(self):
        argv = om.systemd_run_argv("u", ["prog", "-x"], ("User=4242",))
        self.assertEqual(argv[:2], ["systemd-run", "--unit=u"])
        self.assertEqual(argv[-3:], ["--", "prog", "-x"])
        self.assertIn("User=4242", argv)
        props = om.proxy_properties("/run/x/log", uid=4242)
        self.assertIn("NoNewPrivileges=yes", props)
        self.assertIn("ReadWritePaths=/run/x/log", props)
        self.assertIn("CapabilityBoundingSet=", props)

    def test_mirrorlist(self):
        actif = "## Monde\nServer = https://miroir.example.invalid/$repo/os/$arch\n"
        self.assertEqual(om.mirrorlist_with_server(actif), (actif, False))
        commente = "## Monde\n#Server = https://miroir.example.invalid/x\n"
        texte, change = om.mirrorlist_with_server(commente)
        self.assertTrue(change)
        self.assertIn(f"Server = {om.FALLBACK_SERVER}", texte)
        self.assertTrue(texte.endswith(commente))
        self.assertTrue(om.mirrorlist_with_server("")[1])

    def test_selftest_url(self):
        self.assertEqual(
            om.selftest_url("https://m.example.invalid/$repo/os/$arch"),
            "https://m.example.invalid/core/os/x86_64/core.db",
        )

    def test_required_packages(self):
        config = {
            "kernels": ["linux", "linux-lts"],
            "packages": ["git", "base", "postgresql"],
            "bootloader_config": {"bootloader": "Grub"},
        }
        noms = om.required_packages(config, "amd")
        for n in ("base", "linux-lts", "git", "amd-ucode", "grub", "gdm"):
            self.assertIn(n, noms)
        self.assertNotIn("intel-ucode", noms)
        self.assertEqual(len(noms), len(set(noms)))
        noms = om.required_packages(
            {"bootloader_config": {"bootloader": "Systemd-boot"}}, None
        )
        self.assertNotIn("grub", noms)
        self.assertIn("linux", noms)


class TestPacmanDb(unittest.TestCase):
    def test_index_and_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            core = Path(tmp, "core.db")
            extra = Path(tmp, "extra.db")
            make_db(
                core,
                {
                    "base": ("base-1-1-any.pkg.tar.zst", [], []),
                    "outil": ("outil-1-1-x86_64.pkg.tar.zst", [], []),
                },
            )
            make_db(
                extra,
                {
                    "outil": ("outil-2-1-x86_64.pkg.tar.zst", [], []),
                    "bureau-a": ("bureau-a-1.pkg.tar.zst", [], ["bureau"]),
                    "bureau-b": ("bureau-b-1.pkg.tar.zst", [], ["bureau"]),
                    "sh-inventé": (
                        "sh-inventé-1.pkg.tar.zst",
                        ["sh-virtuel=1.0"],
                        [],
                    ),
                },
            )
            index = om.merge_indexes(
                [("core", om.read_db(core)), ("extra", om.read_db(extra))]
            )
        # core l'emporte sur extra pour un même nom.
        self.assertEqual(index["repo"]["outil"], "core")
        self.assertEqual(
            index["packages"]["outil"], "outil-1-1-x86_64.pkg.tar.zst"
        )
        presents = {
            ("core", "base-1-1-any.pkg.tar.zst"),
            ("core", "outil-1-1-x86_64.pkg.tar.zst"),
            ("extra", "bureau-a-1.pkg.tar.zst"),
            ("extra", "sh-inventé-1.pkg.tar.zst"),
        }

        def existe(depot, fichier):
            return (depot, fichier) in presents

        self.assertEqual(
            om.missing_packages(
                ["base", "outil>=1", "sh-virtuel", "bureau", "absent"],
                index,
                existe,
            ),
            [("bureau", "file-missing"), ("absent", "unknown")],
        )


class TestTarget(unittest.TestCase):
    def test_residues_and_cleanup(self):
        with tempfile.TemporaryDirectory() as cible:
            self.assertEqual(om.target_residues(cible), [])
            ancre = Path(cible, om.ANCHOR_DIR.lstrip("/"), om.ANCHOR_NAME)
            ancre.parent.mkdir(parents=True)
            ancre.write_text(FAUX_PEM)
            npmrc = Path(cible, om.NPMRC)
            npmrc.parent.mkdir(parents=True, exist_ok=True)
            npmrc.write_text("registry=https://registre.example.invalid/\n")
            # Un npmrc qui n'est pas le nôtre reste.
            self.assertEqual(om.target_residues(cible), ["anchor"])
            npmrc.write_text(f"{om.NPMRC_MARK}\ncafile=/x\n")
            restes = om.target_residues(cible)
            self.assertEqual(restes, ["anchor", "npmrc"])
            etapes = om.target_cleanup_steps(cible, restes)
            self.assertEqual(
                [e["kind"] for e in etapes], ["remove", "remove", "run"]
            )
            self.assertEqual(
                etapes[-1]["argv"],
                ["arch-chroot", cible, "trust", "extract-compat"],
            )
            appels = []

            def run(argv, **_kw):
                appels.append(argv)
                return subprocess.CompletedProcess(argv, 0, b"", b"")

            self.assertEqual(
                om.clean_target(cible, run=run, log=lambda _m: None),
                (restes, []),
            )
            self.assertFalse(ancre.exists())
            self.assertFalse(npmrc.exists())
            self.assertEqual(appels, [etapes[-1]["argv"]])
            self.assertEqual(om.target_residues(cible), [])


def autre_pem(octets):
    """Un bloc PEM inventé autour de `octets`, base64 coupé à 16
    caractères : un faisceau se compare par DER, pas par texte."""
    b64 = base64.b64encode(octets).decode()
    lignes = [b64[i : i + 16] for i in range(0, len(b64), 16)]
    return (
        "-----BEGIN CERTIFICATE-----\n"
        + "\n".join(lignes)
        + "\n-----END CERTIFICATE-----\n"
    )


FAUX_DER = base64.b64decode(FAUX_PEM.split("\n")[1])


class TestTargetBundle(unittest.TestCase):
    """L'autorité cherchée dans les faisceaux extraits de la cible, pas
    seulement son ancre : une ancre effacée dont l'extraction a échoué
    (disque plein, étape tuée) laisse l'autorité approuvée."""

    def _cible(self, tmp):
        cible = Path(tmp, "cible")
        extrait = cible / "etc/ca-certificates/extracted"
        (extrait / "cadir").mkdir(parents=True)
        (cible / "etc/ssl/certs").mkdir(parents=True)
        (cible / "usr/bin").mkdir(parents=True)
        (cible / om.TARGET_TRUST).write_text("#!/bin/sh\n")
        autre = autre_pem(b"autorite-inventee-qui-reste")
        (extrait / "tls-ca-bundle.pem").write_text(autre)
        return cible, extrait, autre

    def test_hits_pem_der_and_ignores_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            cible, extrait, autre = self._cible(tmp)
            self.assertEqual(om.bundle_hits(str(cible), FAUX_DER), [])
            # Un lien absolu lu depuis le live désignerait le live : il
            # n'est pas suivi, même vers un fichier qui contient l'autorité.
            dehors = Path(tmp, "faisceau-du-live.pem")
            dehors.write_text(FAUX_PEM)
            (cible / "etc/ssl/certs/ca-certificates.crt").symlink_to(dehors)
            self.assertEqual(om.bundle_hits(str(cible), FAUX_DER), [])
            (extrait / "tls-ca-bundle.pem").write_text(
                autre + autre_pem(FAUX_DER)
            )
            # Le faisceau OpenSSL : DER suivi des attributs de confiance.
            (extrait / "openssl").mkdir()
            confiance = autre_pem(FAUX_DER + b"attributs-inventes").replace(
                "CERTIFICATE", "TRUSTED CERTIFICATE"
            )
            (extrait / "openssl/ca-bundle.trust.crt").write_text(confiance)
            (extrait / "java").mkdir()
            (extrait / "java/cacerts").write_bytes(b"\xfe\xed" + FAUX_DER)
            self.assertEqual(
                om.bundle_hits(str(cible), FAUX_DER),
                [
                    "etc/ca-certificates/extracted/java/cacerts",
                    "etc/ca-certificates/extracted/openssl/ca-bundle.trust.crt",
                    "etc/ca-certificates/extracted/tls-ca-bundle.pem",
                ],
            )
            self.assertEqual(
                om.target_residues(str(cible), ca_pem=FAUX_PEM), ["bundle"]
            )
            self.assertEqual(om.target_residues(str(cible)), [])

    def test_clean_regenerates_and_reports_what_stays(self):
        with tempfile.TemporaryDirectory() as tmp:
            cible, extrait, autre = self._cible(tmp)
            faisceau = extrait / "tls-ca-bundle.pem"
            faisceau.write_text(autre + FAUX_PEM)
            appels = []

            def echoue(argv, **_kw):
                appels.append(argv)
                return subprocess.CompletedProcess(argv, 1, b"ENOSPC", b"")

            restes, encore = om.clean_target(
                str(cible), run=echoue, log=lambda _m: None, ca_pem=FAUX_PEM
            )
            self.assertEqual((restes, encore), (["bundle"], ["bundle"]))
            self.assertEqual(
                appels,
                [["arch-chroot", str(cible), "trust", "extract-compat"]],
            )

            def reussit(argv, **_kw):
                faisceau.write_text(autre)
                return subprocess.CompletedProcess(argv, 0, b"", b"")

            self.assertEqual(
                om.clean_target(
                    str(cible),
                    run=reussit,
                    log=lambda _m: None,
                    ca_pem=FAUX_PEM,
                ),
                (["bundle"], []),
            )

    def test_clean_always_regenerates_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            cible, _extrait, _autre = self._cible(tmp)
            run = FakeRun()
            self.assertEqual(
                om.clean_target(
                    str(cible), run=run, log=lambda _m: None, ca_pem=FAUX_PEM
                ),
                ([], []),
            )
            self.assertEqual(
                run.calls,
                [["arch-chroot", str(cible), "trust", "extract-compat"]],
            )
            # Sans trust (pacstrap n'a rien posé) ni autorité : rien à lancer.
            (cible / om.TARGET_TRUST).unlink()
            run = FakeRun()
            om.clean_target(
                str(cible), run=run, log=lambda _m: None, ca_pem=FAUX_PEM
            )
            om.clean_target(str(cible), run=run, log=lambda _m: None)
            self.assertEqual(run.calls, [])


class FakeRun:
    """Le `run` du service : chaque argv est gardé ; ceux dont le premier
    mot est dans `echecs` échouent."""

    def __init__(self, echecs=(), lsblk=None):
        self.calls = []
        self.echecs = set(echecs)
        self.lsblk = lsblk or {"blockdevices": []}

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        if argv[0] == "lsblk":
            return subprocess.CompletedProcess(
                argv, 0, json.dumps(self.lsblk), ""
            )
        rc = 1 if argv[0] in self.echecs else 0
        return subprocess.CompletedProcess(argv, rc, b"", b"")


class TestPlan(unittest.TestCase):
    def test_start_plan_shape(self):
        paths = om.paths_for("/run/essai")
        plan = om.start_plan(paths, manifest())
        ids = [s["id"] for s in plan]
        self.assertEqual(len(ids), len(set(ids)))
        for avant, apres in (
            ("anchor", "trust"),
            ("proxy", "proxy-ready"),
            ("proxy-ready", "dns"),
            ("dns", "resolved"),
            ("nft-rules", "nft"),
            ("nft", "selftest"),
        ):
            self.assertLess(ids.index(avant), ids.index(apres))
        self.assertEqual(ids[-2:], ["selftest", "keyring-update"])
        # Le trousseau d'abord : sans réseau, pacman-init attend l'heure ;
        # l'heure est avancée avant lui et avant toute vérification.
        self.assertLess(ids.index("time-wait"), ids.index("keyring"))
        self.assertLess(ids.index("clock"), ids.index("keyring"))
        self.assertEqual(
            plan[ids.index("clock")]["not_before"],
            om.clock_floor(manifest()),
        )
        self.assertLess(ids.index("keyring"), ids.index("proxy"))
        par_id = {s["id"]: s for s in plan}
        self.assertEqual(par_id["nft"]["undo"]["argv"], om.nft_delete_argv())
        self.assertIn("--hors-ligne", par_id["proxy"]["argv"])
        self.assertEqual(par_id["ca-key"]["mode"], 0o600)
        self.assertEqual(par_id["ca-key"]["uid"], om.PROXY_UID)
        # Toute pièce copiée est vérifiée par son empreinte.
        for step in plan:
            if step["kind"] == "install":
                self.assertEqual(step["sha256"], FAUX_SHA)
        # L'interface factice porte l'adresse et la route : la retirer
        # retire les deux.
        self.assertEqual(
            par_id["fake-link"]["undo"]["argv"],
            ["ip", "link", "del", om.DUMMY_LINK],
        )
        for etape in ("fake-address", "fake-up", "fake-route"):
            self.assertIsNone(par_id[etape]["undo"])
        self.assertLess(ids.index("fake-route"), ids.index("dns"))

    def _paths(self, tmp):
        paths = om.paths_for(os.path.join(tmp, "run"))
        paths["mirrorlist"] = os.path.join(tmp, "mirrorlist")
        paths["resolved"] = os.path.join(tmp, "resolved.conf.d", "x.conf")
        Path(paths["mirrorlist"]).write_text("#Server = rien\n")
        return paths

    def test_execute_records_undo_and_stop_reverses(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(tmp)
            plan = [
                s
                for s in om.start_plan(paths, manifest())
                if s["kind"] in ("run", "write", "mirrorlist")
            ]
            etat = {"undo": []}
            run = FakeRun()
            om.execute_plan(paths, plan, etat, run, log=lambda _m: None)
            self.assertIn(
                f"Server = {om.FALLBACK_SERVER}",
                Path(paths["mirrorlist"]).read_text(),
            )
            self.assertTrue(Path(paths["resolved"]).exists())
            self.assertEqual(
                len(om.load_state(paths)["undo"]),
                len([s for s in plan if s["undo"]]),
            )
            run.calls.clear()
            om.stop(paths, run, log=lambda _m: None)
            # Défait en ordre inverse : nft d'abord, l'adresse de lo après
            # le mandataire.
            self.assertEqual(run.calls[0], om.nft_delete_argv())
            self.assertEqual(
                run.calls[-1], ["ip", "link", "del", om.DUMMY_LINK]
            )
            self.assertEqual(
                Path(paths["mirrorlist"]).read_text(), "#Server = rien\n"
            )
            self.assertFalse(Path(paths["resolved"]).exists())
            self.assertIsNone(om.load_state(paths))

    def test_failure_stops_and_keeps_undo(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(tmp)
            plan = [
                s
                for s in om.start_plan(paths, manifest())
                if s["kind"] in ("run", "mirrorlist")
            ]
            etat = {"undo": []}
            with self.assertRaises(om.OfflineError) as ctx:
                om.execute_plan(
                    paths, plan, etat, FakeRun(echecs={"ip"}), lambda _m: None
                )
            self.assertEqual(ctx.exception.details["step"], "fake-link")
            # Liste de miroirs déjà faite : son inverse est noté, l'adresse
            # ratée ne l'est pas.
            genres = [u["kind"] for u in om.load_state(paths)["undo"]]
            self.assertEqual(genres, ["restore"])

    def test_anchor_undo_removes_then_regenerates(self):
        """Le faisceau se régénère APRÈS l'effacement de l'ancre : dans
        l'autre ordre, l'autorité y resterait approuvée."""
        plan = {
            s["id"]: s
            for s in om.start_plan(om.paths_for("/run/essai"), manifest())
        }
        self.assertIsNone(plan["trust"]["undo"])
        self.assertIsNone(plan["resolved"]["undo"])
        self.assertEqual(
            plan["resolved-dropin"]["undo"]["after"],
            ["systemctl", "restart", "systemd-resolved.service"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            ancre = Path(tmp, "ancre.crt")
            ancre.write_text(FAUX_PEM)
            vus = []

            def run(argv, **_kw):
                vus.append((list(argv), ancre.exists()))
                return subprocess.CompletedProcess(argv, 0, b"", b"")

            undo = dict(plan["anchor"]["undo"], path=str(ancre))
            om.undo_step(undo, run, lambda _m: None)
            self.assertEqual(vus, [(["trust", "extract-compat"], False)])

    def test_clock_floor_and_argv(self):
        self.assertEqual(om.clock_floor(manifest()), 981173106)
        self.assertEqual(
            om.clock_floor(manifest(created="2001-02-03")), 981158400
        )
        self.assertIsNone(om.clock_floor(manifest(created="hier")))
        # Avancée seulement, jamais reculée.
        self.assertEqual(
            om.clock_argv(981173106, 1000.0),
            ["date", "-u", "-s", "@981173106"],
        )
        self.assertIsNone(om.clock_argv(981173106, 981173106.5))
        self.assertIsNone(om.clock_argv(None, 1000.0))

    def test_execute_clock_and_keyring(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(tmp)
            plan = [
                {"id": "clock", "kind": "clock", "not_before": 2000},
                {"id": "keyring-update", "kind": "keyring_update"},
            ]
            for heure, plus_recent, attendu in (
                (1000.0, True, ["date", "pacman", "pacman", "pacman"]),
                (3000.0, False, ["pacman", "pacman"]),
            ):
                appels = []

                def run(argv, _r=plus_recent, _a=appels, **_kw):
                    _a.append(list(argv))
                    rc = 0
                    if argv[:2] == ["pacman", "-Qu"] and not _r:
                        rc = 1
                    return subprocess.CompletedProcess(argv, rc, b"", b"")

                with unittest.mock.patch.object(
                    om.time, "time", return_value=heure
                ):
                    om.execute_plan(
                        paths, plan, {"undo": []}, run, lambda _m: None
                    )
                self.assertEqual([a[0] for a in appels], attendu)
                if plus_recent:
                    self.assertEqual(
                        appels[-1],
                        ["pacman", "-S", "--noconfirm", "archlinux-keyring"],
                    )

    def test_keyring_refusal_before_erase(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(tmp)
            plan = [{"id": "keyring-update", "kind": "keyring_update"}]

            def run(argv, **_kw):
                rc = 1 if argv[:2] == ["pacman", "-S"] else 0
                return subprocess.CompletedProcess(argv, rc, b"", b"")

            with self.assertRaises(om.OfflineError) as ctx:
                om.execute_plan(
                    paths, plan, {"undo": []}, run, lambda _m: None
                )
            self.assertEqual(ctx.exception.code, "keyring-update-failed")
            self.assertEqual(ctx.exception.details, {"step": "install"})

    def test_start_undoes_on_any_exception(self):
        """Une exception hors OfflineError/OSError (réponse HTTP mal
        formée, Ctrl-C) défait aussi la mise en service."""
        import http.client

        for exc, attendue in (
            (http.client.BadStatusLine("x"), om.OfflineError),
            (KeyboardInterrupt(), KeyboardInterrupt),
        ):
            with self.subTest(exc=type(exc).__name__):
                with tempfile.TemporaryDirectory() as tmp:
                    paths = self._paths(tmp)
                    os.makedirs(paths["data"])
                    Path(paths["data"], om.MANIFEST_NAME).write_text(
                        json.dumps(manifest())
                    )

                    def execute(_p, _plan, etat, _run, _log, _e=exc):
                        etat["undo"].append(
                            {"kind": "run", "argv": ["defaire", "nft"]}
                        )
                        _save(paths, etat)
                        raise _e

                    _save = om._save_state
                    run = FakeRun()
                    with (
                        unittest.mock.patch.object(
                            om, "_mounted", return_value=True
                        ),
                        unittest.mock.patch.object(
                            om, "execute_plan", side_effect=execute
                        ),
                    ):
                        with self.assertRaises(attendue):
                            om.start("odoo18", paths, run, log=lambda _m: None)
                    self.assertIn(["defaire", "nft"], run.calls)
                    self.assertEqual(om.load_state(paths)["undo"], [])

    def test_selftest_survives_bad_http(self):
        import http.client

        with unittest.mock.patch.object(
            om.urllib.request,
            "urlopen",
            side_effect=http.client.IncompleteRead(b""),
        ):
            ok, cause = om._selftest(sleep=lambda _s: None)
        self.assertFalse(ok)
        self.assertTrue(cause)

    def test_sysusers_account_matches_uid(self):
        conf = (
            m.AIROOTFS / "usr/lib/sysusers.d/erplibre-offline.conf"
        ).read_text()
        ligne = [x for x in conf.splitlines() if x.startswith("u ")][0]
        self.assertEqual(
            ligne.split()[1:3], [om.PROXY_USER, str(om.PROXY_UID)]
        )

    def test_start_refusals(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = om.paths_for(os.path.join(tmp, "run"))
            with self.assertRaises(om.OfflineError) as ctx:
                om.start("odoo18", paths, FakeRun(), log=lambda _m: None)
            self.assertEqual(ctx.exception.code, "no-data-partition")
            lsblk = {
                "blockdevices": [
                    {"path": p, "label": "ERPLIBRE_DATA", "fstype": "ext4"}
                    for p in ("/dev/sdx3", "/dev/sdw3")
                ]
            }
            self.assertEqual(
                om.probe(paths, FakeRun(lsblk=lsblk))["reason"], "ambiguous"
            )
            os.makedirs(paths["data"])
            Path(paths["data"], om.MANIFEST_NAME).write_text(
                json.dumps(manifest())
            )
            with unittest.mock.patch.object(om, "_mounted", return_value=True):
                sonde = om.probe(paths, FakeRun())
                self.assertTrue(sonde["ok"], sonde)
                with self.assertRaises(om.OfflineError) as ctx:
                    om.start("home", paths, FakeRun(), log=lambda _m: None)
                self.assertEqual(ctx.exception.code, "profile-mismatch")
                Path(paths["data"], om.MANIFEST_NAME).write_text("{")
                self.assertEqual(
                    om.probe(paths, FakeRun())["reason"],
                    "manifest-unreadable",
                )

    def test_probe_mounts_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = om.paths_for(os.path.join(tmp, "run"))
            lsblk = {
                "blockdevices": [
                    {
                        "path": "/dev/sdx3",
                        "label": "ERPLIBRE_DATA",
                        "fstype": "ext4",
                    }
                ]
            }
            run = FakeRun(lsblk=lsblk)
            om.probe(paths, run)
            montage = [c for c in run.calls if c[0] == "mount"][0]
            # noload : même un journal ext4 en attente n'est pas rejoué.
            self.assertIn("ro,noload,nodev,nosuid,noexec", montage)
            self.assertEqual(montage[-2:], ["/dev/sdx3", paths["data"]])
            self.assertTrue(om.load_state(paths)["mounted"])


class TestStage(unittest.TestCase):
    """erplibre-stage.sh, sourcé dans bash sur une racine temporaire."""

    def test_env_matches_python(self):
        sortie = bash("EL_OFFLINE_ACTIVE=1\nel_offline_env")
        attendu = [f"{k}={v}" for k, v in om.stage_env().items()]
        self.assertEqual(sortie.splitlines(), attendu)
        self.assertEqual(bash("el_offline_env"), "")

    def test_prepare_and_release(self):
        with tempfile.TemporaryDirectory() as racine:
            b64 = base64.b64encode(FAUX_PEM.encode()).decode()
            script = (
                "EL_IN_CHROOT=1\n"
                'el_trust_extract() { echo extract >>"$EL_ROOT/trace"; }\n'
                "el_network_source_prepare >/dev/null || exit 9\n"
                'cat "$EL_OFFLINE_ANCHOR"\n'
                'cat "$EL_OFFLINE_NPMRC"\n'
                "el_network_source_release\n"
                'test -e "$EL_OFFLINE_ANCHOR" && echo ANCRE-RESTEE\n'
                'test -e "$EL_OFFLINE_NPMRC" && echo NPMRC-RESTE\n'
                'cat "$EL_ROOT/trace"\n'
            )
            sortie = bash(
                script,
                {
                    "EL_ROOT": racine,
                    "EL_OFFLINE": "1",
                    "EL_OFFLINE_CA_B64": b64,
                    "EL_IN_CHROOT": "1",
                },
            )
            self.assertIn(FAUX_PEM, sortie)
            self.assertIn("cafile=/etc/ssl/certs/ca-certificates.crt", sortie)
            self.assertNotIn("RESTE", sortie)
            self.assertEqual(sortie.count("extract"), 2)

    def test_prepare_keeps_foreign_npmrc_and_skips_online(self):
        with tempfile.TemporaryDirectory() as racine:
            npmrc = Path(racine, om.NPMRC)
            npmrc.parent.mkdir(parents=True)
            npmrc.write_text("prefix=/opt/inventé\n")
            b64 = base64.b64encode(FAUX_PEM.encode()).decode()
            bash(
                "EL_IN_CHROOT=1\n"
                "el_trust_extract() { :; }\n"
                "el_network_source_prepare >/dev/null || exit 9\n"
                "el_network_source_release\n",
                {
                    "EL_ROOT": racine,
                    "EL_OFFLINE": "1",
                    "EL_OFFLINE_CA_B64": b64,
                    "EL_IN_CHROOT": "1",
                },
            )
            self.assertEqual(npmrc.read_text(), "prefix=/opt/inventé\n")
            # En ligne, ou hors du chroot (relance), rien n'est posé.
            for env in (
                {"EL_OFFLINE": "0", "EL_IN_CHROOT": "1"},
                {"EL_OFFLINE": "1", "EL_IN_CHROOT": "0"},
            ):
                bash(
                    f"EL_IN_CHROOT={env.pop('EL_IN_CHROOT')}\n"
                    "el_trust_extract() { exit 7; }\n"
                    "el_network_source_prepare >/dev/null\n",
                    dict(env, EL_ROOT=racine, EL_OFFLINE_CA_B64=b64),
                )
                self.assertFalse(
                    Path(
                        racine,
                        om.ANCHOR_DIR.lstrip("/"),
                        om.ANCHOR_NAME,
                    ).exists()
                )

    def test_relaunch_copy_drops_offline_prelude(self):
        outil = ei.load_config_tool(str(m.CONFIG_TOOL))
        doc = ct.ERPLIBRE_DOC
        profil = outil.find_profile(doc, "odoo18")
        prelude = om.stage_prelude(manifest(), FAUX_PEM)
        texte = outil.stage_command(
            doc, profil, STAGE.read_text(), "", "fr", prelude
        )
        b64 = base64.b64encode(FAUX_PEM.encode()).decode()
        self.assertIn(f"\nEL_OFFLINE_CA_B64={b64}\n", texte)
        self.assertIn("\nEL_OFFLINE=1\n", texte)
        # La source git est celle du paquet, une seule fois.
        self.assertEqual(texte.count("\nEL_GIT_URL=https"), 1)
        self.assertIn(
            "EL_GIT_URL=https://forge.example.invalid/erplibre", texte
        )
        self.assertIn("EL_GIT_BRANCH=branche-inventee", texte)
        copie = subprocess.run(
            ["bash", "-c", f"source {STAGE}\nel_relaunch_filter"],
            input=texte,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertNotIn(b64, copie)
        self.assertIn("\nEL_OFFLINE=0\n", copie)
        # Les défauts du corps du script restent.
        self.assertIn('EL_OFFLINE="${EL_OFFLINE:-0}"', copie)
        self.assertIn('EL_OFFLINE_CA_B64="${EL_OFFLINE_CA_B64:-}"', copie)
        self.assertEqual(
            subprocess.run(["bash", "-n"], input=copie, text=True).returncode,
            0,
        )


class TestCore(unittest.TestCase):
    """Le cœur avec le service hors ligne simulé : le refus vient avant
    tout effacement, la mise en service encadre archinstall."""

    def setUp(self):
        self.base = ct.TestRunInstall("test_full_install")
        self.base.setUp()
        self.addCleanup(self.base.tmp.cleanup)

    def doc(self):
        return ct.answers(erplibre_profile="odoo18", offline=True)

    def test_offline_requested(self):
        # Le lanceur le demande avant d'attendre le réseau : rien n'est
        # journalisé, aucun marqueur de fin n'est écrit.
        def b64(doc):
            return "b64:" + base64.b64encode(json.dumps(doc).encode()).decode(
                "ascii"
            )

        self.assertTrue(ei.offline_requested(b64(self.doc())))
        self.assertFalse(ei.offline_requested(b64(ct.answers())))
        self.assertFalse(ei.offline_requested("b64:pas-du-base64"))
        self.assertFalse(ei.offline_requested(b64(["liste"])))
        self.assertFalse(ei.offline_requested(None))
        with tempfile.TemporaryDirectory() as tmp:
            chemin = os.path.join(tmp, "reponses.json")
            Path(chemin).write_text(json.dumps(self.doc()))
            sortie = io.StringIO()
            with (
                unittest.mock.patch("sys.stdout", sortie),
                unittest.mock.patch("sys.stderr", sortie),
            ):
                rc = ei.main(["--answers", chemin, "--offline-requested"])
                Path(chemin).write_text(json.dumps(ct.answers()))
                rc_en_ligne = ei.main(
                    ["--answers", chemin, "--offline-requested"]
                )
            self.assertEqual((rc, rc_en_ligne), (0, 1))
            self.assertEqual(sortie.getvalue(), "")

    def test_argv(self):
        argv = ei.archinstall_argv(ei.DEFAULT_PATHS, offline=True)
        for opt in ("--offline", "--skip-ntp", "--skip-wkd"):
            self.assertIn(opt, argv)
        self.assertNotIn("--offline", ei.archinstall_argv(ei.DEFAULT_PATHS))

    def _patch(
        self, sonde=None, manquants=(), start_exc=None, restes=(), encore=()
    ):
        sonde = sonde or {
            "found": True,
            "ok": True,
            "reason": None,
            "manifest": manifest(),
            "errors": [],
        }
        ordre = []
        patches = {
            "probe": unittest.mock.patch.object(
                om, "probe", return_value=sonde
            ),
            "check": unittest.mock.patch.object(
                om, "check_packages", return_value=list(manquants)
            ),
            "start": unittest.mock.patch.object(
                om,
                "start",
                side_effect=start_exc
                or (lambda *a, **k: ordre.append("start")),
            ),
            "stop": unittest.mock.patch.object(
                om, "stop", side_effect=lambda *a, **k: ordre.append("stop")
            ),
            "state": unittest.mock.patch.object(
                om, "load_state", return_value={"manifest": manifest()}
            ),
            "pem": unittest.mock.patch.object(
                om, "ca_pem", return_value=FAUX_PEM
            ),
            "clean": unittest.mock.patch.object(
                om,
                "clean_target",
                side_effect=lambda *a, **k: (
                    ordre.append("clean") or (list(restes), list(encore))
                ),
            ),
        }
        mocks = {k: p.start() for k, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)
        return mocks, ordre

    def test_refusals_erase_nothing(self):
        cas = [
            (
                {
                    "found": False,
                    "ok": False,
                    "reason": "no-data-partition",
                    "errors": [],
                },
                (),
            ),
            (
                {
                    "found": True,
                    "ok": True,
                    "reason": None,
                    "errors": [],
                    "manifest": manifest(erplibre_profile="home"),
                },
                (),
            ),
            (None, [("gnome", "unknown")]),
        ]
        for sonde, manquants in cas:
            with self.subTest(sonde=sonde, manquants=manquants):
                mocks, ordre = self._patch(sonde, manquants)
                rc, system = self.base.install(doc=self.doc())
                self.assertEqual(rc, ei.EXIT_OFFLINE)
                self.assertEqual(system.calls, [])
                self.assertEqual(ordre, [])
                unittest.mock.patch.stopall()

    def test_start_failure_erases_nothing(self):
        self._patch(start_exc=om.OfflineError("selftest-failed"))
        rc, system = self.base.install(doc=self.doc())
        self.assertEqual(rc, ei.EXIT_OFFLINE)
        self.assertEqual(system.calls, [])

    def test_dry_run_checks_without_starting(self):
        mocks, ordre = self._patch()
        rc, system = self.base.install(doc=self.doc(), dry_run=True)
        self.assertEqual(rc, 0, self.base.logs())
        self.assertEqual(ordre, [])
        noms = mocks["check"].call_args[0][0]
        self.assertIn("postgresql", noms)
        self.assertIn("amd-ucode", noms)

    def test_offline_install(self):
        mocks, ordre = self._patch()
        rc, system = self.base.install(doc=self.doc())
        self.assertEqual(rc, 0, self.base.logs())
        self.assertEqual(ordre, ["start", "clean", "stop"])
        archinstall = next(
            a for a in system.commands() if a[0] == "archinstall"
        )
        self.assertIn("--offline", archinstall)
        config = json.loads(
            Path(self.base.paths["run"], "config.json").read_text()
        )
        etape = config["custom_commands"][0]
        self.assertIn("\nEL_OFFLINE=1\n", etape)
        self.assertIn(base64.b64encode(FAUX_PEM.encode()).decode(), etape)
        self.assertIn("forge.example.invalid", etape)
        outils = [a[0] for a in system.commands()]
        self.assertLess(outils.index("archinstall"), outils.index("umount"))

    def test_residue_left_fails_the_install(self):
        mocks, ordre = self._patch(restes=["bundle"], encore=["bundle"])
        rc, _system = self.base.install(doc=self.doc())
        self.assertEqual(rc, ei.EXIT_OFFLINE_RESIDUE, self.base.logs())
        self.assertEqual(ordre, ["start", "clean", "stop"])
        self.assertEqual(mocks["clean"].call_args.kwargs["ca_pem"], FAUX_PEM)
        self.assertIn("STILL in the target", self.base.logs())

    def test_residue_removed_is_only_logged(self):
        self._patch(restes=["anchor"])
        rc, _system = self.base.install(doc=self.doc())
        self.assertEqual(rc, 0, self.base.logs())
        self.assertIn("residues removed", self.base.logs())

    def test_profile_command_mismatch_erases_nothing(self):
        autre = manifest()
        autre["erplibre"][om.COMMAND_KEY] = FAUX_SHA
        sonde = {
            "found": True,
            "ok": True,
            "reason": None,
            "manifest": autre,
            "errors": [],
        }
        _mocks, ordre = self._patch(sonde)
        rc, system = self.base.install(doc=self.doc())
        self.assertEqual(rc, ei.EXIT_OFFLINE)
        self.assertEqual(system.calls, [])
        self.assertEqual(ordre, [])
        self.assertIn("profile-command-mismatch", self.base.logs())
        self.assertIn("not the one the payload recorded", self.base.logs())

    def test_online_install_untouched(self):
        mocks, ordre = self._patch()
        rc, system = self.base.install(
            doc=ct.answers(erplibre_profile="odoo18")
        )
        self.assertEqual(rc, 0, self.base.logs())
        self.assertEqual(ordre, [])
        mocks["probe"].assert_not_called()
        config = json.loads(
            Path(self.base.paths["run"], "config.json").read_text()
        )
        self.assertNotIn("\nEL_OFFLINE=1\n", config["custom_commands"][0])
        self.assertNotIn(
            "--offline",
            next(a for a in system.commands() if a[0] == "archinstall"),
        )

    def test_record_skips_package_check(self):
        sonde = {
            "found": True,
            "ok": True,
            "reason": None,
            "manifest": record_manifest(erplibre_profile="odoo18"),
            "errors": [],
        }
        mocks, ordre = self._patch(sonde, [("tout", "unknown")])
        rc, system = self.base.install(doc=self.doc())
        self.assertEqual(rc, 0, self.base.logs())
        mocks["check"].assert_not_called()
        self.assertEqual(ordre, ["start", "clean", "stop"])


class TestFlow(unittest.TestCase):
    def ctx(self, tmp, sonde):
        from test import test_iso_installer_ui as ut

        return ut.context(tmp, offline=sonde), ut

    def sonde(self, **extra):
        out = {"found": True, "ok": True, "manifest": manifest()}
        out.update(extra)
        return out

    def test_profile_field_and_document(self):
        tr = i18n.Translator("en")
        with tempfile.TemporaryDirectory() as tmp:
            ctx, ut = self.ctx(tmp, self.sonde())
            champ = [
                c
                for c in flow.form_fields(ctx, tr)
                if c["key"] == "erplibre_profile"
            ][0]
            self.assertEqual(champ["default"], "odoo18")
            libelle = dict(champ["choices"])["odoo18"]
            self.assertIn(
                "offline install (payload odoo18, 2001-02-03)", libelle
            )
            self.assertNotIn("offline", dict(champ["choices"])["home"])
            doc, erreurs = flow.collect(
                ctx, ut.good_values(erplibre_profile="odoo18"), tr
            )
            self.assertEqual(erreurs, [])
            self.assertTrue(doc["offline"])
            self.assertFalse(flow.needs_network(doc))
            doc, _e = flow.collect(ctx, ut.good_values(), tr)
            self.assertFalse(doc["offline"])
            self.assertTrue(flow.needs_network(doc))

    def test_no_or_bad_payload_is_online(self):
        tr = i18n.Translator("en")
        with tempfile.TemporaryDirectory() as tmp:
            for sonde in (
                {"found": False, "ok": False},
                self.sonde(ok=False, reason="manifest-invalid"),
            ):
                ctx, ut = self.ctx(tmp, sonde)
                doc, _e = flow.collect(
                    ctx, ut.good_values(erplibre_profile="odoo18"), tr
                )
                self.assertFalse(doc["offline"])
                self.assertIsNone(flow.offline_text(ctx, tr))

    def test_wait_ready_offline_skips_network(self):
        """Sans réseau du tout, l'installation hors ligne n'attend pas."""
        lignes = []

        def run(argv, **_kw):
            return subprocess.CompletedProcess(
                argv, 2 if argv[0] == "getent" else 0
            )

        tr = i18n.Translator("en")
        self.assertTrue(
            flow.wait_ready(
                lignes.append,
                tr,
                run=run,
                sleep=lambda _s: None,
                network=False,
            )
        )
        self.assertNotIn(tr("Waiting for the network…"), lignes)
        self.assertFalse(
            flow.wait_ready(
                lignes.append,
                tr,
                run=run,
                sleep=lambda _s: None,
                network_s=2,
            )
        )

    def test_offline_context_not_root(self):
        with unittest.mock.patch.object(os, "geteuid", return_value=1000):
            self.assertFalse(flow.offline_context({}, run=None)["ok"])


class TestPayloadTool(unittest.TestCase):
    def load(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "offline_payload", PAYLOAD_TOOL
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_build_command(self):
        op = self.load()
        argv, env = op.proxy_build_command("/sortie/x")
        self.assertEqual(env["CGO_ENABLED"], "0")
        self.assertIn("-trimpath", argv)
        self.assertEqual(argv[argv.index("-o") + 1], "/sortie/x")

    def test_manifest_and_image(self):
        op = self.load()
        with tempfile.TemporaryDirectory() as racine:
            for rel, contenu in (
                ("bin/erplibre_go_qemu_cache", "binaire inventé".encode()),
                ("ca/ca.crt", FAUX_PEM.encode()),
                ("ca/ca.key", b"clef inventee"),
                ("repo/core/os/x86_64/core.db", b"base"),
                ("store/ab/cd/x.body", b"corps"),
            ):
                chemin = Path(racine, rel)
                chemin.parent.mkdir(parents=True, exist_ok=True)
                chemin.write_bytes(contenu)
            doc = op.manifest_document(
                racine,
                "home",
                {
                    "git_url": "https://forge.example.invalid/e",
                    "branch": "b",
                    "commit": FAUX_COMMIT,
                },
                "4.5",
                "2001-02-01",
                "0.0.0",
            )
            self.assertEqual(om.check_manifest(doc), [])
            self.assertEqual(doc["parts"]["store"]["files"], 1)
            self.assertEqual(
                doc["parts"]["proxy"]["sha256"],
                om.sha256_file(Path(racine, "bin/erplibre_go_qemu_cache")),
            )
            with self.assertRaises(ValueError):
                op.manifest_document(
                    racine, "home", {"git_url": "u"}, "4.5", "x", ""
                )
            # Le magasin écrit en 0600 devient lisible ; la clé, non.
            corps = Path(racine, "store/ab/cd/x.body")
            corps.chmod(0o600)
            Path(racine, "ca/ca.key").chmod(0o600)
            Path(racine, "store/ab").chmod(0o700)
            self.assertGreaterEqual(op.readable_modes(racine), 2)
            self.assertEqual(corps.stat().st_mode & 0o777, 0o644)
            self.assertEqual(
                Path(racine, "store/ab").stat().st_mode & 0o777, 0o755
            )
            self.assertEqual(
                Path(racine, "ca/ca.key").stat().st_mode & 0o777, 0o600
            )
            self.assertEqual(op.readable_modes(racine), 0)
        argv = op.mkfs_argv("/src", "/img")
        self.assertEqual(argv[argv.index("-L") + 1], "ERPLIBRE_DATA")
        self.assertIn("^has_journal", argv)
        self.assertEqual(op.image_bytes(0) % (1024**2), 0)
        self.assertGreater(op.image_bytes(10 * 1024**3), 10 * 1024**3)


def record_manifest(**extra):
    """Un manifeste d'enregistrement inventé."""
    doc = {
        "schema": 1,
        "mode": "record",
        "erplibre_profile": "gnome",
        "created": "2001-02-03T04:05:06Z",
        "arch": "x86_64",
        "erplibre": {
            "git_url": "https://forge.example.invalid/erplibre",
            "branch": "branche-inventee",
        },
        "record": {"proxy": "10.0.2.2", "http_port": 40001, "tls_port": 40002},
        "parts": {"ca_cert": {"path": "ca/ca.crt", "sha256": FAUX_SHA}},
    }
    doc.update(extra)
    return doc


class TestRecordMode(unittest.TestCase):
    """Le live en mode enregistrement : mêmes inverses, nft vers le
    mandataire de l'hôte, ni DNS factice ni mandataire local."""

    def test_manifest(self):
        self.assertEqual(om.check_manifest(record_manifest()), [])
        self.assertTrue(om.is_record(record_manifest()))
        self.assertFalse(om.is_record(manifest()))
        self.assertIn("record", om.manifest_label(record_manifest()))
        self.assertEqual(
            om.match_profile(record_manifest(), "gnome", "4.5"),
            (True, None, []),
        )
        for record, attendu in (
            (None, "record: object required"),
            (
                {"proxy": "127.0.0.1", "http_port": 1, "tls_port": 2},
                "record.proxy: not a host address",
            ),
            (
                {
                    "proxy": "nom.example.invalid",
                    "http_port": 1,
                    "tls_port": 2,
                },
                "record.proxy: IPv4 address required",
            ),
            (
                {"proxy": "10.0.2.2", "http_port": 0, "tls_port": True},
                "record.http_port: port required",
            ),
        ):
            with self.subTest(record=record):
                self.assertIn(
                    attendu, om.check_manifest(record_manifest(record=record))
                )
        self.assertIn(
            "mode: record or absent expected",
            om.check_manifest(manifest(mode="autre")),
        )
        # Un manifeste hors ligne garde toutes ses exigences.
        incomplet = manifest()
        del incomplet["parts"]["store"]
        self.assertIn("parts.store: missing", om.check_manifest(incomplet))

    def test_ruleset(self):
        texte = om.nft_record_ruleset("10.0.2.2", 40001, 40002)
        self.assertIn("dnat ip to 10.0.2.2:40001", texte)
        self.assertIn("dnat ip to 10.0.2.2:40002", texte)
        self.assertIn("ip daddr 10.0.2.2 return", texte)
        self.assertIn(f"delete table inet {om.NFT_TABLE}", texte)
        self.assertNotIn("skuid", texte)

    def test_plan(self):
        paths = om.paths_for("/run/essai")
        plan = om.plan_for(paths, record_manifest())
        ids = [s["id"] for s in plan]
        for absent in ("account", "proxy", "dns", "fake-link", "ca-key"):
            self.assertNotIn(absent, ids)
        for avant, apres in (
            ("keyring", "upstream"),
            ("upstream", "anchor"),
            ("anchor", "trust"),
            ("trust", "nft"),
            ("nft", "selftest"),
        ):
            self.assertLess(ids.index(avant), ids.index(apres))
        par_id = {s["id"]: s for s in plan}
        self.assertEqual(par_id["upstream"]["host"], "10.0.2.2")
        self.assertIn("dnat", par_id["nft-rules"]["text"])
        # L'ancre se défait comme hors ligne : effacée PUIS le faisceau.
        hors_ligne = {s["id"]: s for s in om.start_plan(paths, manifest())}
        self.assertEqual(
            par_id["anchor"]["undo"], hors_ligne["anchor"]["undo"]
        )
        self.assertEqual(
            par_id["ca-cert"]["dest"], os.path.join(paths["ca"], "ca.crt")
        )
        self.assertEqual(
            [s["id"] for s in om.plan_for(paths, manifest())],
            [s["id"] for s in om.start_plan(paths, manifest())],
        )

    def test_wait_upstream_gives_up(self):
        with unittest.mock.patch.object(
            om.socket, "create_connection", side_effect=OSError("refusé")
        ):
            self.assertFalse(
                om._wait_upstream("10.0.2.2", 1, 3, sleep=lambda _s: None)
            )

    def test_read_db_signed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp, "core.db")
            make_db(
                base, {"a": ("a-1-1-any.pkg.tar.zst", [], [])}, signed=("a",)
            )
            self.assertEqual(om.read_db(base)["signed"], {"a"})


def load_payload_tool():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "offline_payload", PAYLOAD_TOOL
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def store_object(
    store, url, body, method="GET", stored_at="2001-02-03T00:00:00Z", **meta
):
    """Un objet de magasin inventé, rangé comme le mandataire le range
    (deux casiers hexadécimaux) ; la clé est l'empreinte de l'URL."""
    import hashlib

    cle = hashlib.sha256(f"{method} {url}".encode()).hexdigest()
    dossier = Path(store, cle[:2], cle[2:4])
    dossier.mkdir(parents=True, exist_ok=True)
    doc = {
        "url": url,
        "method": method,
        "status": 200,
        "size": len(body),
        "stored_at": stored_at,
        "header": {},
    }
    doc.update(meta)
    Path(dossier, cle + ".meta").write_text(json.dumps(doc))
    Path(dossier, cle + ".body").write_bytes(body)
    return dossier / (cle + ".body")


class TestPayloadFactory(unittest.TestCase):
    """La fabrique côté hôte : planification, élagage, dépôt, manifeste.
    Les URL, miroirs et paquets sont inventés."""

    def setUp(self):
        self.op = load_payload_tool()

    def test_mirror_rel_and_manifests(self):
        op = self.op
        self.assertEqual(
            op.mirror_rel("https://forge.example.invalid/Org/depot.git/"),
            "forge.example.invalid/Org/depot.git",
        )
        self.assertEqual(
            op.mirror_rel("https://forge.example.invalid/Org/depot"),
            "forge.example.invalid/Org/depot.git",
        )
        for mauvais in (
            "https://forge.example.invalid/",
            "depot",
            "https://forge.example.invalid/a/../b",
        ):
            self.assertIsNone(op.mirror_rel(mauvais))
        xml = (
            '<manifest><remote name="r" fetch="https://forge.example.invalid/Org/"/>'
            '<remote name="s" fetch="https://autre.example.invalid/"/>'
            '<default remote="r"/>'
            '<project name="un.git" path="x"/>'
            '<project name="deux" remote="s" path="y"/></manifest>'
        )
        self.assertEqual(
            op.manifest_repos(xml),
            [
                "https://forge.example.invalid/Org/un.git",
                "https://autre.example.invalid/deux",
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            for nom in op.SEED_MANIFESTS["home"]:
                Path(tmp, nom).write_text(xml)
            urls = op.seed_repos(
                "home", "https://forge.example.invalid/e", tmp
            )
            self.assertEqual(urls[0], "https://forge.example.invalid/e")
            # Le même dépôt dans deux manifestes n'est compté qu'une fois.
            self.assertEqual(len(urls), 2 + len(op.SEED_EXTRA) + 1)
            self.assertEqual(
                op.seed_repos("gnome", "https://f.invalid/e", tmp), []
            )
            seed = Path(tmp, "seed")
            Path(seed, "forge.example.invalid/Org/un.git").mkdir(parents=True)
            dest = Path(tmp, "dest")
            Path(dest, "autre.example.invalid/deux.git").mkdir(parents=True)
            Path(seed, "autre.example.invalid/deux.git").mkdir(parents=True)
            plan = op.seed_plan(urls, str(seed), str(dest))
            self.assertEqual(
                plan,
                [
                    (
                        str(seed / "forge.example.invalid/Org/un.git"),
                        str(dest / "forge.example.invalid/Org/un.git"),
                    )
                ],
            )
        argv = op.seed_argv("/a", "/b")
        self.assertIn("--reflink=auto", argv)
        self.assertEqual(argv[-3:], ["--", "/a", "/b"])

    def test_record_manifest_and_answers(self):
        op = self.op
        import datetime

        doc = op.record_manifest(
            "home",
            {"git_url": "https://forge.example.invalid/e", "branch": "b"},
            FAUX_SHA,
            (40001, 40002),
            datetime.datetime(2001, 2, 3, 4, 5, 6),
        )
        self.assertEqual(om.check_manifest(doc), [])
        self.assertEqual(doc["record"]["proxy"], op.RECORD_GATEWAY)
        with self.assertRaises(ValueError):
            op.record_manifest(
                "home",
                {"git_url": "", "branch": ""},
                FAUX_SHA,
                (1, 2),
                datetime.datetime(2001, 2, 3),
            )
        reponses = op.answers_document("home", "mot-de-passe-invente")
        self.assertTrue(reponses["offline"])
        self.assertEqual(reponses["confirm"]["disk"], "vda")
        ligne = op.kernel_cmdline("2001-02-03-04-05-06-00", reponses)
        self.assertIn("copytoram=n", ligne)
        self.assertIn("archisosearchuuid=2001-02-03-04-05-06-00", ligne)
        b64 = ligne.split("erplibre.answers=b64:", 1)[1]
        self.assertNotIn(" ", b64)
        relu, permis = ei.decode_answers("b64:" + b64, "/run/inexistant")
        self.assertEqual(relu, reponses)
        self.assertTrue(permis)

    def test_qemu_and_proxy_argv(self):
        op = self.op
        chemins = op.work_paths("/fab/essai")
        chemins["iso"] = "/iso/x.iso"
        argv = op.qemu_argv(chemins, 2048, 2, "ligne", ("/code", "/vars"))
        self.assertEqual(argv[argv.index("-append") + 1], "ligne")
        self.assertIn("-no-reboot", argv)
        self.assertIn("user,model=virtio-net-pci", argv)
        lecteurs = [argv[i + 1] for i, a in enumerate(argv) if a == "-drive"]
        self.assertTrue(
            any("readonly=on" in d and "record.img" in d for d in lecteurs)
        )
        self.assertEqual(
            [d for d in lecteurs if d.startswith("if=virtio")],
            [f"if=virtio,file={chemins['target']},format=qcow2"],
        )
        self.assertNotIn("pflash", " ".join(op.qemu_argv(chemins, 1, 1, "l")))
        proxy = op.proxy_record_argv("/b/p", "/fab/w", (40001, 40002))
        self.assertNotIn("--hors-ligne", proxy)
        self.assertEqual(proxy[proxy.index("--ecoute") + 1], "127.0.0.1")
        self.assertEqual(
            proxy[proxy.index("--bypass-file") + 1], "/fab/w/bypass"
        )
        texte = GO_MAIN.read_text()
        for opt in proxy[1:]:
            if opt.startswith("--"):
                self.assertIn(f'"{opt[2:]}"', texte, opt)

    def test_build_plan_has_no_secret(self):
        op = self.op
        import datetime

        with tempfile.TemporaryDirectory() as tmp:
            plan = op.build_plan(
                {
                    "profile": "gnome",
                    "iso": "/iso/x.iso",
                    "out": tmp,
                    "git_url": "https://forge.example.invalid/e",
                    "branch": "b",
                    "seed": None,
                    "memory": 2048,
                    "cpus": 2,
                    "disk_gib": None,
                    "timeout_min": 5,
                },
                datetime.datetime(2001, 2, 3, 4, 5, 6),
                (40001, 40002),
                "2001-02-03-04-05-06-00",
            )
            self.assertEqual(plan["disk_gib"], op.DEFAULT_DISK_GIB)
            self.assertTrue(
                plan["paths"]["root"].endswith("gnome-20010203-040506")
            )
            texte = "\n".join(op.describe_plan(plan))
            self.assertNotIn("password", json.dumps(plan))
            self.assertIn("40001", texte)
            self.assertFalse(os.listdir(tmp))
            self.assertNotIn(om.COMMAND_KEY, plan["source"])
            plan = op.build_plan(
                {
                    "profile": "gnome",
                    "iso": "/iso/x.iso",
                    "out": tmp,
                    "git_url": "https://forge.example.invalid/e",
                    "branch": "b",
                    "seed": None,
                    "memory": 2048,
                    "cpus": 2,
                    "disk_gib": None,
                    "timeout_min": 5,
                    "command_sha256": FAUX_SHA,
                },
                datetime.datetime(2001, 2, 3, 4, 5, 6),
                (40001, 40002),
                "2001-02-03-04-05-06-00",
            )
            # La source passe telle quelle au manifeste (assemble).
            self.assertEqual(plan["source"][om.COMMAND_KEY], FAUX_SHA)

    def test_payload_authority_argv(self):
        """L'autorité du paquet est créée avec le profil de paquet du
        mandataire (nom distinct, deux ans) : l'option existe dans
        main.go."""
        argv = self.op.proxy_init_ca_argv("/bin/x", "/ca")
        self.assertEqual(argv[:3], ["/bin/x", "--init-ca", "--ca-paquet"])
        source = GO_MAIN.read_text(encoding="utf-8")
        declarees = set(re.findall(r'flag\.\w+\(\s*"([a-z-]+)"', source))
        for opt in [a[2:] for a in argv if a.startswith("--")]:
            self.assertIn(opt, declarees)

    def test_profile_command_matches_iso_profiles(self):
        """L'empreinte enregistrée est celle de la commande que
        build_iso.py écrit dans profiles.json, pour chaque profil."""
        op = self.op

        class FauxBuildIso:
            def iso_profiles(self, _par_langue, suffixe):
                return [
                    {"key": "gnome", "command": ""},
                    {"key": "odoo18", "command": "make essai " + suffixe},
                ]

            def qemu_profiles_by_lang(self):
                return {}

            def _qemu_mixin(self):
                return type("M", (), {"_QEMU_QEMU_PKGS": "fin"})

        faux = FauxBuildIso()
        self.assertEqual(op.profile_command("gnome", faux), "")
        self.assertEqual(op.profile_command("odoo18", faux), "make essai fin")
        with self.assertRaises(LookupError):
            op.profile_command("inconnu", faux)

    def test_pacman_target_and_names(self):
        op = self.op
        self.assertEqual(
            op.pacman_target(
                "https://miroir.example.invalid/archlinux/core/os/x86_64/"
                "a-1-1-x86_64.pkg.tar.zst"
            ),
            ("core", "x86_64", "a-1-1-x86_64.pkg.tar.zst"),
        )
        # L'époque d'une version garde son deux-points dans le nom.
        self.assertEqual(
            op.pacman_target(
                "https://m.example.invalid/core/os/x86_64/"
                "outil-2:1.0-1-x86_64.pkg.tar.zst"
            )[2],
            "outil-2:1.0-1-x86_64.pkg.tar.zst",
        )
        self.assertEqual(
            op.pkg_name("outil-2:1.0-1-x86_64.pkg.tar.zst"), "outil"
        )
        for autre in (
            "https://pypi.example.invalid/simple/a/",
            "https://m.example.invalid/core/xx/x86_64/a",
            "https://m.example.invalid/core/os/x86_64/.cache",
        ):
            self.assertIsNone(op.pacman_target(autre))
        self.assertEqual(
            op.pkg_name("lib-a-2.0-3-x86_64.pkg.tar.zst"), "lib-a"
        )
        self.assertIsNone(op.pkg_name("core.db"))
        self.assertEqual(
            op.pkglist_version("bash 5-1\narchinstall 4.5.1-2\n"), "4.5.1"
        )
        self.assertEqual(
            op.snapshot_date(
                {
                    "header": {
                        "Last-Modified": ["Sat, 03 Feb 2001 04:05:06 GMT"]
                    }
                }
            ),
            "2001-02-03",
        )
        self.assertEqual(
            op.snapshot_date({"stored_at": "2001-02-04T00:00Z"}), "2001-02-04"
        )
        self.assertEqual(
            op.not_found(
                "error: target not found: x\nerror: target not found: y"
            ),
            ["x", "y"],
        )
        conf = op.curl_config(
            ["https://m.example.invalid/a", "https://m.example.invalid/b"],
            40002,
            "/ca",
        )
        self.assertEqual(conf.count("connect-to"), 1)
        self.assertIn('"m.example.invalid:443:127.0.0.1:40002"', conf)
        self.assertEqual(conf.count('output = "/dev/null"'), 2)

    def test_db_choice(self):
        op = self.op
        vieux = {
            "packages": {
                "a": "a-1-1-any.pkg.tar.zst",
                "b": "b-1-1-any.pkg.tar.zst",
            },
            "signed": set(),
        }
        neuf = {
            "packages": {
                "a": "a-2-1-any.pkg.tar.zst",
                "b": "b-1-1-any.pkg.tar.zst",
                "c": "c-1-1-any.pkg.tar.zst",
            },
            "signed": {"b"},
        }
        fichiers = {
            "a-1-1-any.pkg.tar.zst",
            "a-1-1-any.pkg.tar.zst.sig",
            "b-1-1-any.pkg.tar.zst",
        }
        self.assertEqual(op.db_gaps(neuf, fichiers), ["a"])
        self.assertEqual(op.db_gaps(vieux, fichiers), [])
        choisi, manques = op.choose_db(
            [("2001-02-02", "neuf", neuf), ("2001-02-01", "vieux", vieux)],
            fichiers,
        )
        self.assertEqual((choisi, manques), ("vieux", []))
        gardes, sans = op.repo_files(vieux, fichiers)
        self.assertEqual(sorted(gardes), sorted(fichiers))
        self.assertEqual(sans, ["b"])
        self.assertEqual(op.repo_files(neuf, fichiers)[1], [])
        choisi, manques = op.choose_db(
            [("2001-02-02", "neuf", neuf)], fichiers
        )
        self.assertEqual(manques, ["a"])
        self.assertEqual(
            op.newest_per_package(
                {
                    "a-1-1-any.pkg.tar.zst": "1",
                    "a-1-1-any.pkg.tar.zst.sig": "1",
                    "a-2-1-any.pkg.tar.zst": "2",
                }
            ),
            {"a-2-1-any.pkg.tar.zst": "2"},
        )
        self.assertEqual(
            op.git_repos_used(
                [
                    {
                        "url": "https://forge.example.invalid/O/d.git/info/refs"
                        "?service=git-upload-pack"
                    },
                    {
                        "url": "https://forge.example.invalid/O/e/git-upload-pack"
                    },
                    {"url": "https://forge.example.invalid/O/f.tar.gz"},
                ]
            ),
            {"forge.example.invalid/O/d.git", "forge.example.invalid/O/e.git"},
        )

    def test_assemble(self):
        """Un travail inventé : magasin avec base, paquets, .sig, une
        ancienne version, un objet PyPI, deux miroirs dont un servi."""
        op = self.op
        with tempfile.TemporaryDirectory() as tmp:
            chemins = op.work_paths(tmp)
            store = chemins["store"]
            miroir = "https://miroir.example.invalid/archlinux"
            base = Path(tmp, "core.db")
            make_db(
                base,
                {
                    "a": ("a-2-1-any.pkg.tar.zst", [], []),
                    "base": ("base-1-1-any.pkg.tar.zst", [], []),
                },
            )
            store_object(
                store,
                f"{miroir}/core/os/x86_64/core.db",
                base.read_bytes(),
                stored_at="2001-02-03T00:00:00Z",
                header={"Last-Modified": ["Sat, 03 Feb 2001 04:05:06 GMT"]},
            )
            for nom, quand in (
                ("a-1-1-any.pkg.tar.zst", "2001-02-01"),
                ("a-2-1-any.pkg.tar.zst", "2001-02-02"),
                ("a-2-1-any.pkg.tar.zst.sig", "2001-02-02"),
                ("base-1-1-any.pkg.tar.zst", "2001-02-02"),
                ("base-1-1-any.pkg.tar.zst.sig", "2001-02-02"),
            ):
                store_object(
                    store,
                    f"{miroir}/core/os/x86_64/{nom}",
                    nom.encode(),
                    stored_at=quand,
                )
            store_object(
                store,
                f"{miroir}/core/os/x86_64/core.db",
                b"",
                method="HEAD",
                status_only=True,
            )
            pypi = store_object(
                store, "https://pypi.example.invalid/simple/a/", b"<html/>"
            )
            Path(store, "sentinelle").write_text("x")
            for rel in (
                "forge.example.invalid/O/servi.git",
                "forge.example.invalid/O/inutile.git",
            ):
                Path(store, "git", rel, "objects").mkdir(parents=True)
                # Un miroir dont les références sont toutes dans
                # packed-refs : refs/heads et refs/tags restent vides, et
                # git ne reconnaît plus un dépôt sans refs/.
                Path(store, "git", rel, "refs", "heads").mkdir(parents=True)
                Path(store, "git", rel, "refs", "tags").mkdir()
                Path(store, "git", rel, "packed-refs").write_text(
                    FAUX_COMMIT + " refs/heads/b\n"
                )
                Path(store, "git", rel, "HEAD").write_text(
                    "ref: refs/heads/b\n"
                )
            Path(chemins["access"]).write_text(
                json.dumps(
                    {
                        "url": "https://forge.example.invalid/O/servi.git/info/refs"
                        "?service=git-upload-pack"
                    }
                )
                + "\n"
            )
            Path(chemins["ca"]).mkdir(parents=True)
            Path(chemins["ca"], "ca.crt").write_text(FAUX_PEM)
            Path(chemins["ca"], "ca.key").write_text("clef inventee")
            Path(chemins["proxy"]).parent.mkdir(parents=True)
            Path(chemins["proxy"]).write_bytes(b"binaire")
            Path(chemins["state"]).write_text(
                json.dumps(
                    {
                        "plan": {
                            "profile": "gnome",
                            "created": "2001-02-03T04:05:06Z",
                            "source": {
                                "git_url": "https://forge.example.invalid/e",
                                "branch": "b",
                            },
                            "paths": {"iso": "/iso/x.iso"},
                            "image": os.path.join(tmp, "data.img"),
                        },
                        "times": {"install_s": 1},
                        "archinstall_version": "4.5",
                    }
                )
            )
            appels = []

            def run(argv, **kw):
                appels.append(argv[0])
                sortie = ""
                if argv[0] == "git":
                    sortie = FAUX_COMMIT + "\trefs/heads/b\n"
                elif argv[0] == chemins["proxy"]:
                    sortie = "erplibre_go_qemu_cache 0.0.1\n"
                return subprocess.CompletedProcess(argv, 0, sortie, "")

            with unittest.mock.patch.object(
                op, "gate_packages", return_value=["a", "base"]
            ):
                releve = op.assemble(chemins, log=lambda _m: None, run=run)
            charge = Path(chemins["payload"])
            depot = charge / "repo/core/os/x86_64"
            self.assertEqual(
                sorted(os.listdir(depot)),
                [
                    "a-2-1-any.pkg.tar.zst",
                    "a-2-1-any.pkg.tar.zst.sig",
                    "base-1-1-any.pkg.tar.zst",
                    "base-1-1-any.pkg.tar.zst.sig",
                    "core.db",
                ],
            )
            self.assertEqual(releve["repo"]["core"]["db"], "official")
            self.assertEqual(releve["repo"]["core"]["dropped"], 1)
            self.assertEqual(releve["repo"]["core"]["snapshot"], "2001-02-03")
            # Le magasin du paquet : l'objet PyPI seul, et le miroir servi.
            corps = [p.name for p in (charge / "store").rglob("*.body")]
            self.assertEqual(corps, [pypi.name])
            self.assertTrue(
                (
                    charge / "store/git/forge.example.invalid/O/servi.git/HEAD"
                ).exists()
            )
            self.assertFalse(
                (
                    charge / "store/git/forge.example.invalid/O/inutile.git"
                ).exists()
            )
            for vide in ("refs/heads", "refs/tags"):
                self.assertTrue(
                    (
                        charge
                        / "store/git/forge.example.invalid/O/servi.git"
                        / vide
                    ).is_dir(),
                    vide,
                )
            self.assertFalse((charge / "store/sentinelle").exists())
            doc = json.loads((charge / "manifest.json").read_text())
            self.assertEqual(om.check_manifest(doc), [])
            self.assertEqual(doc["erplibre"]["commit"], FAUX_COMMIT)
            self.assertEqual(doc["proxy_version"], "0.0.1")
            self.assertEqual(doc["arch_snapshot"], "2001-02-03")
            self.assertEqual(releve["missing_for_gate"], [])
            self.assertTrue(releve["ok"])
            self.assertIn("mkfs.ext4", appels)
            self.assertTrue(
                Path(tmp, "data.img.sha256")
                .read_text()
                .endswith("  data.img\n")
            )
            self.assertEqual(
                Path(chemins["payload"], "ca/ca.key").read_text(),
                "clef inventee",
            )


if __name__ == "__main__":
    unittest.main()
