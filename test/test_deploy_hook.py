#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le hook de deploiement certbot, joue dans une racine temporaire.

`ERPLIBRE_CALL_ROOT` prefixe chaque chemin du hook ; `systemctl`, `nginx`,
`chown` et `kill` sont des bouchons qui notent leurs appels dans un
journal. Le hook est lance tel quel, comme certbot le lance, avec
RENEWED_LINEAGE pointant sur une lignee inventee.
"""
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(RACINE, "script/install/erplibre_call_deploy_hook.sh")
INSTALLATEUR = os.path.join(RACINE, "script/install/install_coturn.sh")

# Contenus inventes : ni certificat ni cle reels, le hook ne fait que copier.
ANCIEN_CRT = "ancien certificat invente\n"
ANCIENNE_CLE = "ancienne cle inventee\n"
NOUVEAU_CRT = "nouveau certificat invente, serie 2\n"
NOUVELLE_CLE = "nouvelle cle inventee, serie 2\n"
CONFIGURATION = "# erplibre-call: managed\nlistening-port=3478\n"

BOUCHONS = {
    # is-active lit l'etat voulu dans ETAT_<unite> ; tout le reste est note.
    "systemctl": (
        '#!/bin/sh\necho "systemctl $*" >> "$J"\n'
        'if [ "$1" = is-active ]; then\n'
        "  for u; do :; done\n"
        '  eval "e=\\${ETAT_$u:-inactive}"\n'
        '  [ "$e" = active ]\n'
        "fi\n"
    ),
    "nginx": (
        '#!/bin/sh\necho "nginx $*" >> "$J"\n'
        'if [ "${NGINX_T:-0}" != 0 ]; then\n'
        '  echo "nginx: [emerg] directive inventee en echec" >&2\n'
        "  exit 1\n"
        "fi\n"
    ),
    "chown": '#!/bin/sh\necho "chown $*" >> "$J"\n',
    "kill": '#!/bin/sh\necho "kill $*" >> "$J"\n',
}


def fonction(chemin, nom):
    """Le texte de la fonction shell `nom` dans le fichier `chemin`."""
    with open(chemin, encoding="utf-8") as flux:
        texte = flux.read()
    trouve = re.search(r"^%s\(\) \{" % re.escape(nom), texte, re.M)
    if trouve is None:
        raise AssertionError("fonction absente de %s : %s" % (chemin, nom))
    return texte[trouve.start() : texte.index("\n}\n", trouve.start()) + 3]


def lire(chemin):
    with open(chemin, encoding="utf-8") as flux:
        return flux.read()


def ecrire(chemin, texte):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as flux:
        flux.write(texte)


class Racine:
    """Une racine temporaire : etat, configuration coturn, copies servies,
    empreinte appliquee et une lignee renouvelee."""

    def __init__(
        self,
        dossier,
        unite="coturn",
        config="/etc/turnserver.conf",
        services=("coturn",),
        tls=True,
        etat=True,
        source="letsencrypt",
    ):
        self.dossier = dossier
        self.r = os.path.join(dossier, "racine")
        self.journal = os.path.join(dossier, "appels")
        self.bouchons = os.path.join(dossier, "bouchons")
        self.call = os.path.join(self.r, "etc/erplibre-call")
        self.tls = os.path.join(self.call, "tls")
        self.applied = os.path.join(self.call, "coturn.applied")
        self.conf = self.r + config
        os.makedirs(self.call)
        os.makedirs(self.bouchons)
        for nom, texte in BOUCHONS.items():
            chemin = os.path.join(self.bouchons, nom)
            ecrire(chemin, texte)
            os.chmod(chemin, 0o755)
        ecrire(self.conf, CONFIGURATION)
        if tls:
            os.makedirs(self.tls)
            ecrire(os.path.join(self.tls, "turn.crt"), ANCIEN_CRT)
            ecrire(os.path.join(self.tls, "turn.key"), ANCIENNE_CLE)
        if etat:
            ecrire(
                os.path.join(self.call, "state.json"),
                json.dumps(
                    {
                        "version": 1,
                        "mode": "production",
                        "services": {
                            nom: {
                                "unit": unite if nom == "coturn" else "ntfy",
                                "config": (
                                    config
                                    if nom == "coturn"
                                    else "/etc/ntfy/server.yml"
                                ),
                                "settings": {"tls": source},
                            }
                            for nom in services
                        },
                    }
                ),
            )
        self.lignee = os.path.join(dossier, "live", "erplibre-call")
        ecrire(os.path.join(self.lignee, "fullchain.pem"), NOUVEAU_CRT)
        ecrire(os.path.join(self.lignee, "privkey.pem"), NOUVELLE_CLE)

    def empreinte_installateur(self):
        """Ce qu'`applied_digest` d'install_coturn.sh imprime pour les
        fichiers presents de cette racine."""
        enveloppe = (
            "set -euo pipefail\nTLS_DIR=%s\n" % self.tls
            + fonction(INSTALLATEUR, "applied_digest")
            + "applied_digest %s\n" % self.conf
        )
        fait = subprocess.run(
            ["bash", "-c", enveloppe],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert fait.returncode == 0, fait.stderr
        return fait.stdout

    def synchroniser(self):
        """coturn.applied dit chargee la paire actuelle, comme l'ecrit
        l'installateur apres un redemarrage reussi."""
        ecrire(self.applied, self.empreinte_installateur())

    def lancer(self, lignee=None, coturn="active", nginx="active", nginx_t=0):
        env = dict(os.environ)
        env.update(
            PATH=self.bouchons + os.pathsep + env.get("PATH", ""),
            J=self.journal,
            ERPLIBRE_CALL_ROOT=self.r,
            RENEWED_LINEAGE=self.lignee if lignee is None else lignee,
            ETAT_coturn=coturn,
            ETAT_turnserver=coturn,
            ETAT_nginx=nginx,
            NGINX_T=str(nginx_t),
        )
        self.fait = subprocess.run(
            [HOOK], capture_output=True, text=True, env=env, timeout=30
        )
        self.appels = (
            lire(self.journal).splitlines()
            if os.path.exists(self.journal)
            else []
        )
        self.marqueurs = [
            ligne
            for ligne in self.fait.stdout.splitlines()
            if ligne.startswith("@@HOOK ")
        ]
        return self.fait

    def servi(self, nom):
        return lire(os.path.join(self.tls, nom))


class TestLignee(unittest.TestCase):
    def test_une_autre_lignee_ne_change_rien(self):
        with tempfile.TemporaryDirectory() as dossier:
            r = Racine(dossier)
            r.synchroniser()
            avant = lire(r.applied)
            autre = os.path.join(dossier, "live", "autre-site")
            ecrire(os.path.join(autre, "fullchain.pem"), NOUVEAU_CRT)
            ecrire(os.path.join(autre, "privkey.pem"), NOUVELLE_CLE)
            fait = r.lancer(lignee=autre)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertEqual(r.servi("turn.crt"), ANCIEN_CRT)
            self.assertEqual(r.servi("turn.key"), ANCIENNE_CLE)
            self.assertEqual(lire(r.applied), avant)
            # Ni signal, ni nginx, ni meme une question a systemd.
            self.assertEqual(r.appels, [])
            self.assertEqual(r.marqueurs, ["@@HOOK skip autre-site"])

    def test_sans_lignee_rien(self):
        with tempfile.TemporaryDirectory() as dossier:
            r = Racine(dossier)
            fait = r.lancer(lignee="")
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertEqual(r.appels, [])
            self.assertEqual(r.servi("turn.crt"), ANCIEN_CRT)


class TestCopie(unittest.TestCase):
    def test_la_lignee_renouvelee_passe_a_coturn(self):
        with tempfile.TemporaryDirectory() as dossier:
            r = Racine(dossier)
            r.synchroniser()
            fait = r.lancer()
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            self.assertEqual(r.servi("turn.crt"), NOUVEAU_CRT)
            self.assertEqual(r.servi("turn.key"), NOUVELLE_CLE)
            for nom in ("turn.crt", "turn.key"):
                chemin = os.path.join(r.tls, nom)
                self.assertFalse(os.path.islink(chemin))
                self.assertEqual(stat.S_IMODE(os.stat(chemin).st_mode), 0o640)
            # Groupe du dossier TLS, celui que l'installateur y a pose.
            gid = os.stat(r.tls).st_gid
            chowns = [a for a in r.appels if a.startswith("chown ")]
            self.assertTrue(chowns, r.appels)
            for appel in chowns:
                self.assertTrue(
                    appel.startswith("chown root:%d " % gid), appel
                )
            # Les deux temporaires, avant leur renommage.
            for nom in (".turn.crt.", ".turn.key."):
                self.assertTrue([a for a in chowns if nom in a], chowns)
            # Aucun fichier temporaire laisse a cote des copies.
            self.assertEqual(
                sorted(os.listdir(r.tls)), ["turn.crt", "turn.key"]
            )

    def test_l_empreinte_est_celle_de_l_installateur(self):
        """Une relance d'install_coturn.sh trouve coturn.applied a jour et
        ne redemarre pas coturn pour un certificat deja recharge."""
        with tempfile.TemporaryDirectory() as dossier:
            r = Racine(dossier)
            r.synchroniser()
            avant = lire(r.applied)
            fait = r.lancer()
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertEqual(lire(r.applied), r.empreinte_installateur())
            self.assertNotEqual(lire(r.applied), avant)
            self.assertEqual(stat.S_IMODE(os.stat(r.applied).st_mode), 0o600)
            self.assertIn("@@HOOK applied", r.marqueurs)

    def test_sigusr2_et_jamais_de_redemarrage(self):
        """SIGUSR2 fait relire a coturn son certificat ; les allocations
        en cours survivent, un redemarrage les couperait."""
        with tempfile.TemporaryDirectory() as dossier:
            r = Racine(dossier)
            r.synchroniser()
            fait = r.lancer()
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertIn("systemctl kill -s SIGUSR2 coturn", r.appels)
            self.assertFalse(
                [
                    a
                    for a in r.appels
                    if "restart" in a or a.startswith("systemctl stop")
                ],
                r.appels,
            )
            self.assertIn("@@HOOK signal coturn", r.marqueurs)
            # Le signal suit les deux copies.
            self.assertLess(
                max(
                    i for i, a in enumerate(r.appels) if a.startswith("chown ")
                ),
                r.appels.index("systemctl kill -s SIGUSR2 coturn"),
            )

    def test_unite_arch_lue_dans_l_etat(self):
        with tempfile.TemporaryDirectory() as dossier:
            r = Racine(
                dossier,
                unite="turnserver",
                config="/etc/turnserver/turnserver.conf",
            )
            r.synchroniser()
            fait = r.lancer()
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertIn("systemctl kill -s SIGUSR2 turnserver", r.appels)
            self.assertEqual(lire(r.applied), r.empreinte_installateur())

    def test_empreinte_perimee_laissee_telle_quelle(self):
        """coturn.applied qui ne dit pas la paire en place : coturn tourne
        sur une autre configuration que celle du disque. Le hook copie et
        signale, mais ne la dit pas chargee : la prochaine installation
        redemarre."""
        with tempfile.TemporaryDirectory() as dossier:
            r = Racine(dossier)
            perime = "0" * 64 + "  /ailleurs/turnserver.conf\n"
            ecrire(r.applied, perime)
            fait = r.lancer()
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertEqual(r.servi("turn.crt"), NOUVEAU_CRT)
            self.assertEqual(lire(r.applied), perime)
            self.assertIn("systemctl kill -s SIGUSR2 coturn", r.appels)
            self.assertIn("@@HOOK applied-stale", r.marqueurs)

    def test_coturn_arrete_copie_sans_signal(self):
        with tempfile.TemporaryDirectory() as dossier:
            r = Racine(dossier)
            r.synchroniser()
            avant = lire(r.applied)
            fait = r.lancer(coturn="inactive")
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertEqual(r.servi("turn.crt"), NOUVEAU_CRT)
            self.assertFalse(
                [
                    a
                    for a in r.appels
                    if " kill " in a or a.startswith("kill ")
                ],
                r.appels,
            )
            self.assertEqual(lire(r.applied), avant)

    def test_coturn_absent_de_l_etat_rien_pour_coturn(self):
        with tempfile.TemporaryDirectory() as dossier:
            r = Racine(dossier, services=("ntfy",))
            fait = r.lancer()
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertEqual(r.servi("turn.crt"), ANCIEN_CRT)
            self.assertFalse([a for a in r.appels if "kill" in a])
            # nginx sert toujours la lignee : il est recharge.
            self.assertIn("systemctl reload nginx", r.appels)

    def test_coturn_sur_un_certificat_fourni_garde_le_sien(self):
        """Un etat dont coturn ne sert pas la lignee (certificat fourni, ou
        aucun) : un renouvellement de l'ancienne lignee ne remplace pas la
        paire de coturn, nginx est recharge."""
        for source in ("supplied", "none", None):
            with self.subTest(
                source=source
            ), tempfile.TemporaryDirectory() as dossier:
                r = Racine(dossier, source=source)
                fait = r.lancer()
                self.assertEqual(fait.returncode, 0, fait.stderr)
                self.assertEqual(r.servi("turn.crt"), ANCIEN_CRT)
                self.assertEqual(r.servi("turn.key"), ANCIENNE_CLE)
                self.assertFalse([a for a in r.appels if "kill" in a])
                self.assertIn(
                    "@@HOOK coturn-skip not-letsencrypt", r.marqueurs
                )
                self.assertIn("systemctl reload nginx", r.appels)

    def test_sans_etat_ni_dossier_tls_rien_pour_coturn(self):
        for options in ({"etat": False}, {"tls": False}):
            with self.subTest(
                options=options
            ), tempfile.TemporaryDirectory() as dossier:
                r = Racine(dossier, **options)
                fait = r.lancer()
                self.assertEqual(fait.returncode, 0, fait.stderr)
                self.assertFalse([a for a in r.appels if "kill" in a])
                self.assertFalse([a for a in r.appels if "chown" in a])

    def test_etat_illisible_ou_unite_inconnue_refuse(self):
        """L'unite et le chemin de l'etat finissent dans des commandes
        root : une valeur hors de ce que l'outil ecrit arrete la copie."""
        for unite, config in (
            ("sshd", "/etc/turnserver.conf"),
            ("coturn", "/etc/../tmp/turn.conf"),
            ("coturn", "/etc/turn server.conf"),
            ("coturn", "relatif.conf"),
        ):
            with self.subTest(
                unite=unite, config=config
            ), tempfile.TemporaryDirectory() as dossier:
                r = Racine(dossier, unite=unite, config="/etc/turnserver.conf")
                etat = json.loads(lire(os.path.join(r.call, "state.json")))
                etat["services"]["coturn"]["config"] = config
                ecrire(os.path.join(r.call, "state.json"), json.dumps(etat))
                fait = r.lancer()
                self.assertNotEqual(fait.returncode, 0, fait.stdout)
                self.assertEqual(r.servi("turn.crt"), ANCIEN_CRT)
                self.assertFalse([a for a in r.appels if "kill" in a])

    def test_un_etat_qui_n_est_pas_du_json_echoue(self):
        with tempfile.TemporaryDirectory() as dossier:
            r = Racine(dossier)
            ecrire(os.path.join(r.call, "state.json"), "{pas du json")
            fait = r.lancer()
            self.assertNotEqual(fait.returncode, 0, fait.stdout)
            self.assertEqual(r.servi("turn.crt"), ANCIEN_CRT)


class TestRefus(unittest.TestCase):
    def test_une_cible_en_lien_est_refusee(self):
        """Le renommage remplacerait le lien sans toucher le fichier vise,
        qui n'est pas celui que l'outil gere : rien n'est copie."""
        with tempfile.TemporaryDirectory() as dossier:
            r = Racine(dossier)
            r.synchroniser()
            avant = lire(r.applied)
            victime = os.path.join(dossier, "victime")
            ecrire(victime, "intact\n")
            cle = os.path.join(r.tls, "turn.key")
            os.remove(cle)
            os.symlink(victime, cle)
            fait = r.lancer()
            self.assertNotEqual(fait.returncode, 0, fait.stdout)
            self.assertEqual(lire(victime), "intact\n")
            self.assertTrue(os.path.islink(cle))
            # Aucune des deux copies : la paire servie reste coherente.
            self.assertEqual(r.servi("turn.crt"), ANCIEN_CRT)
            self.assertEqual(lire(r.applied), avant)
            self.assertFalse([a for a in r.appels if "kill" in a])
            self.assertTrue(
                [m for m in r.marqueurs if m.startswith("@@HOOK refused ")],
                r.marqueurs,
            )

    def test_un_dossier_tls_en_lien_est_refuse(self):
        with tempfile.TemporaryDirectory() as dossier:
            r = Racine(dossier, tls=False)
            ailleurs = os.path.join(dossier, "ailleurs")
            os.makedirs(ailleurs)
            os.symlink(ailleurs, r.tls)
            fait = r.lancer()
            self.assertNotEqual(fait.returncode, 0, fait.stdout)
            self.assertEqual(os.listdir(ailleurs), [])

    def test_une_source_absente_echoue_sans_signal(self):
        with tempfile.TemporaryDirectory() as dossier:
            r = Racine(dossier)
            r.synchroniser()
            os.remove(os.path.join(r.lignee, "privkey.pem"))
            fait = r.lancer()
            self.assertNotEqual(fait.returncode, 0, fait.stdout)
            self.assertEqual(r.servi("turn.key"), ANCIENNE_CLE)
            self.assertFalse([a for a in r.appels if "kill" in a])
            self.assertEqual(
                sorted(os.listdir(r.tls)), ["turn.crt", "turn.key"]
            )
            # nginx est recharge quand meme : il lit la lignee elle-meme.
            self.assertIn("systemctl reload nginx", r.appels)


class TestNginx(unittest.TestCase):
    def test_nginx_actif_teste_puis_recharge(self):
        with tempfile.TemporaryDirectory() as dossier:
            r = Racine(dossier)
            r.synchroniser()
            fait = r.lancer()
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertLess(
                r.appels.index("nginx -t"),
                r.appels.index("systemctl reload nginx"),
            )
            self.assertFalse(
                [a for a in r.appels if a.startswith("systemctl restart")]
            )
            self.assertIn("@@HOOK nginx-reloaded", r.marqueurs)

    def test_nginx_inactif_pas_de_rechargement(self):
        with tempfile.TemporaryDirectory() as dossier:
            r = Racine(dossier)
            r.synchroniser()
            fait = r.lancer(nginx="inactive")
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertNotIn("nginx -t", r.appels)
            self.assertFalse([a for a in r.appels if "reload" in a])

    def test_nginx_t_en_echec_pas_de_rechargement(self):
        with tempfile.TemporaryDirectory() as dossier:
            r = Racine(dossier)
            r.synchroniser()
            fait = r.lancer(nginx_t=1)
            self.assertNotEqual(fait.returncode, 0, fait.stdout)
            self.assertIn("nginx -t", r.appels)
            self.assertNotIn("systemctl reload nginx", r.appels)
            self.assertIn("directive inventee", fait.stderr)
            self.assertIn("@@HOOK nginx-failed", r.marqueurs)
            # coturn a eu sa paire quand meme.
            self.assertEqual(r.servi("turn.crt"), NOUVEAU_CRT)


class TestSource(unittest.TestCase):
    def test_meme_empreinte_que_l_installateur(self):
        """La fonction qui calcule coturn.applied est la meme, au caractere
        pres, dans le hook et dans install_coturn.sh."""
        self.assertEqual(
            fonction(HOOK, "applied_digest"),
            fonction(INSTALLATEUR, "applied_digest"),
        )

    def test_syntaxe_et_executable(self):
        fait = subprocess.run(
            ["bash", "-n", HOOK], capture_output=True, text=True
        )
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertTrue(os.access(HOOK, os.X_OK))
        self.assertTrue(lire(HOOK).startswith("#!/usr/bin/env bash\n"))


if __name__ == "__main__":
    sys.exit(not unittest.main(exit=False).result.wasSuccessful())
