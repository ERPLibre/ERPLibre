#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'installateur ntfy, fonction par fonction, sans root ni service.

Chaque fonction shell est extraite du script et jouee dans un bac a sable :
les commandes systeme (`systemctl`, `pacman`, `ntfy`, `chown`...) y sont des
bouchons qui notent leurs appels. Le script annonce un acces refuse par
defaut : une configuration en place qui pose des reglages sans declarer de
controle d'acces l'arrete, car ntfy autorise alors la lecture ET l'ecriture
anonymes sur tous les sujets, sur toutes les interfaces. Un fichier sans
aucun reglage actif, celui que livre un paquet, est mis de cote et remplace.
"""
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(RACINE, "script/install/install_ntfy.sh")


def extraire_fonction(nom):
    """Rend la fonction shell demandee, seule, executable dans un bac a sable.

    Le script entier exige root et installe pour de vrai : on en extrait la
    decision a eprouver. La definition est cherchee en debut de ligne
    (`nom() {`), un commentaire qui cite le nom ne la remplace donc pas.
    """
    with open(SCRIPT, encoding="utf-8") as flux:
        texte = flux.read()
    trouve = re.search(r"^%s\(\) \{" % re.escape(nom), texte, re.M)
    if trouve is None:
        raise AssertionError("fonction absente de install_ntfy.sh : %s" % nom)
    debut = trouve.start()
    fin = texte.index("\n}\n", debut) + 3
    return texte[debut:fin]


def constantes():
    """Les chemins que le script fixe en tete (INSTALL_DIR, CONFIG_DIR,
    CACHE_DIR, DATA_DIR), tels qu'il les ecrit."""
    with open(SCRIPT, encoding="utf-8") as flux:
        texte = flux.read()
    return "".join(
        re.search(r'^%s="[^"]*"\n' % nom, texte, re.M).group(0)
        for nom in ("INSTALL_DIR", "CONFIG_DIR", "CACHE_DIR", "DATA_DIR")
    )


def jouer(enveloppe, env=None, timeout=30):
    """Lance `enveloppe` sous bash ; rend le CompletedProcess."""
    complet = dict(os.environ)
    complet.update(env or {})
    return subprocess.run(["bash", "-c", enveloppe], capture_output=True,
                          text=True, env=complet, timeout=timeout)


def lignes(chemin):
    """Lignes d'un journal de bouchons, liste vide s'il n'existe pas."""
    if not os.path.exists(chemin):
        return []
    with open(chemin, encoding="utf-8") as flux:
        return flux.read().splitlines()


class TestConfigurationDejaEnPlace(unittest.TestCase):
    def _jouer(self, contenu_yml, environnement=None, variables="",
               origine=None):
        """Joue la fonction de configuration sur un server.yml donne.

        `variables` : affectations shell posees apres les defauts du
        bac a sable, donc prioritaires sur eux. `origine` : contenu d'un
        server.yml.origine pose d'avance. Avec `origine` donne, rend aussi
        le contenu de server.yml.origine apres coup (None s'il n'existe pas).
        """
        with tempfile.TemporaryDirectory() as dossier:
            if contenu_yml is not None:
                with open(os.path.join(dossier, "server.yml"), "w") as flux:
                    flux.write(contenu_yml)
            sauvegarde = os.path.join(dossier, "server.yml.origine")
            if origine:
                with open(sauvegarde, "w") as flux:
                    flux.write(origine)
            enveloppe = (
                "set -e\n"
                "log() { echo \"$*\"; }\n"
                "die() { echo \"ERREUR: $*\" >&2; exit 1; }\n"
                # Le compte systeme et les droits ne sont pas ce qu'on
                # eprouve ici, et les poser demanderait root.
                "id() { return 1; }\n"
                "chown() { :; }\n"
                "CONFIG_DIR=%s\n"
                "CACHE_DIR=%s/cache\n"
                "DATA_DIR=%s/lib\n"
                "AUTH_FILE=%s/lib/user.db\n"
                "NTFY_PORT=8080\nNTFY_BASE_URL=http://localhost:8080\n"
                "NTFY_PUBLIC=0\nNTFY_CERT_FILE=\nNTFY_KEY_FILE=\n"
                "NTFY_HTTPS_PORT=\n"
                % (dossier, dossier, dossier, dossier)
            ) + variables.replace("@D@", dossier) + "\n" + extraire_fonction(
                "configure_ntfy") + "\nconfigure_ntfy\n"
            fait = jouer(enveloppe, environnement)
            yml = os.path.join(dossier, "server.yml")
            ecrit = open(yml).read() if os.path.exists(yml) else ""
            if origine is None:
                return fait, ecrit
            garde = (open(sauvegarde).read() if os.path.exists(sauvegarde)
                     else None)
            return fait, ecrit, garde

    def test_une_config_permissive_arrete_l_installateur(self):
        """Des reglages poses sans aucun controle d'acces."""
        fait, ecrit = self._jouer('listen-http: ":8080"\n')
        self.assertNotEqual(fait.returncode, 0, fait.stdout)
        self.assertIn("aucun controle d'acces", fait.stderr.lower())
        # Elle n'est pas remplacee en silence : le script dit comment faire.
        self.assertIn("server.yml.origine", fait.stderr)
        self.assertEqual(ecrit, 'listen-http: ":8080"\n')

    def test_une_config_qui_declare_son_acces_est_respectee(self):
        """Elle peut porter des reglages d'exploitation qu'on ignore."""
        posee = 'listen-http: ":8080"\nauth-default-access: "deny-all"\n'
        fait, ecrit = self._jouer(posee)
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(ecrit, posee)

    def test_on_peut_garder_la_permissive_en_le_disant(self):
        """Un choix, pas un oubli : il faut le declarer."""
        fait, _ = self._jouer('listen-http: ":8080"\n',
                              {"NTFY_GARDER_CONFIG": "1"})
        self.assertEqual(fait.returncode, 0, fait.stderr)

    # Celle que livre un paquet : chaque cle en commentaire.
    COMMENTEE = ('# ntfy server config file\n#\n'
                 '# base-url: "https://ntfy.exemple.test"\n\n'
                 '  # listen-http: ":80"\n')

    def test_une_config_sans_aucune_cle_est_remplacee_et_gardee(self):
        """Elle ne porte aucun reglage : la remplacer ne perd rien, et une
        installation neuve par paquet n'exige aucune variable."""
        fait, ecrit, garde = self._jouer(self.COMMENTEE, origine="")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn('auth-default-access: "deny-all"', ecrit)
        self.assertEqual(garde, self.COMMENTEE)

    def test_une_sauvegarde_deja_la_n_est_pas_ecrasee(self):
        fait, ecrit, garde = self._jouer(self.COMMENTEE, origine="avant\n")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("deny-all", ecrit)
        self.assertEqual(garde, "avant\n")

    def test_garder_la_config_vaut_aussi_pour_celle_sans_cle(self):
        fait, ecrit, garde = self._jouer(self.COMMENTEE,
                                         {"NTFY_GARDER_CONFIG": "1"},
                                         origine="")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(ecrit, self.COMMENTEE)
        self.assertIsNone(garde)

    def test_une_seule_cle_sans_controle_d_acces_arrete_encore(self):
        fait, ecrit = self._jouer(self.COMMENTEE + 'listen-http: ":80"\n')
        self.assertNotEqual(fait.returncode, 0, fait.stdout)
        self.assertIn("aucun controle d'acces", fait.stderr.lower())

    def test_sans_config_l_installateur_ecrit_la_sienne(self):
        fait, ecrit = self._jouer(None)
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("auth-default-access", ecrit)
        self.assertIn("deny-all", ecrit)
        # La base des comptes ne va PAS sous /etc : le service tourne sous un
        # compte qui n'y ecrit pas, et il sortirait en erreur au demarrage.
        self.assertNotIn('auth-file: "/etc/', ecrit)
        self.assertIn("/lib/user.db", ecrit)


    def _jouer_tls(self, port):
        """Configuration neuve avec un certificat et une cle fournis."""
        variables = (
            "printf c > @D@/ntfy.crt; printf k > @D@/ntfy.key\n"
            "NTFY_CERT_FILE=@D@/ntfy.crt\nNTFY_KEY_FILE=@D@/ntfy.key\n"
            "NTFY_HTTPS_PORT=%s\n" % port
        )
        return self._jouer(None, variables=variables)

    def test_https_ecoute_sur_le_port_demande(self):
        fait, ecrit = self._jouer_tls("9443")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn('listen-https: ":9443"', ecrit)
        self.assertRegex(ecrit, r'cert-file: ".*/ntfy\.crt"')
        self.assertRegex(ecrit, r'key-file: ".*/ntfy\.key"')

    def test_https_sans_port_prend_8443_jamais_443(self):
        # 443 est le port de nginx en production, et un port sous 1024
        # demande une capacite que l'unite du paquet ne donne pas.
        fait, ecrit = self._jouer_tls("")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn('listen-https: ":8443"', ecrit)
        self.assertNotIn('":443"', ecrit)

    def test_un_port_https_non_numerique_est_refuse(self):
        fait, ecrit = self._jouer_tls("'8443; x'")
        self.assertNotEqual(fait.returncode, 0)
        self.assertIn("NTFY_HTTPS_PORT", fait.stderr)
        self.assertEqual(ecrit, "")

    def test_sans_certificat_aucune_ecoute_https(self):
        fait, ecrit = self._jouer(None, variables="NTFY_HTTPS_PORT=8443\n")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertNotIn("listen-https:", ecrit)


class TestUniteSystemd(unittest.TestCase):
    """L'unite ecrite pour l'installation par binaire."""

    def _unite(self, binaire=None):
        with tempfile.TemporaryDirectory() as dossier:
            unite = os.path.join(dossier, "ntfy.service")
            enveloppe = (
                "set -e\n"
                "log() { :; }\n"
                "id() { return 0; }\n"
                "useradd() { echo useradd >> %s/appels; }\n"
                "SYSTEMD_UNIT=%s\n" % (dossier, unite)
            ) + constantes() + extraire_fonction("create_systemd_service") + (
                "\ncreate_systemd_service %s\n" % (binaire or ""))
            fait = jouer(enveloppe)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            with open(unite, encoding="utf-8") as flux:
                return flux.read()

    def test_la_base_des_comptes_est_inscriptible(self):
        # ProtectSystem=strict rend tout le reste du systeme en lecture
        # seule : sans /var/lib/ntfy ici, le service ne peut ecrire user.db.
        texte = self._unite()
        ligne = re.search(r"^ReadWritePaths=(.*)$", texte, re.M)
        self.assertIsNotNone(ligne, texte)
        chemins = ligne.group(1).split()
        self.assertIn("/var/lib/ntfy", chemins)
        self.assertIn("/var/cache/ntfy", chemins)
        self.assertIn("ProtectSystem=strict", texte)

    def test_le_binaire_par_defaut_et_le_binaire_donne(self):
        self.assertIn("ExecStart=/usr/local/bin/ntfy serve", self._unite())
        self.assertIn("ExecStart=/usr/bin/ntfy serve",
                      self._unite("/usr/bin/ntfy"))


class TestUniteRelue(unittest.TestCase):
    """`refresh_systemd_service` : sur un hote deja installe, l'unite que ce
    script a ecrite autrefois est reecrite ; une autre n'est pas touchee."""

    ANCIENNE = (
        "[Unit]\nDescription=ntfy push notification server\n"
        "After=network.target\n\n[Service]\nType=simple\n"
        "ExecStart=/opt/ntfy/bin/ntfy serve\nUser=ntfy\nGroup=ntfy\n"
        "ProtectSystem=strict\n"
        "ReadWritePaths=/var/cache/ntfy /etc/ntfy\n\n"
        "[Install]\nWantedBy=multi-user.target\n"
    )

    def _jouer(self, contenu):
        """Rend (texte de l'unite apres coup ou None, CompletedProcess)."""
        with tempfile.TemporaryDirectory() as dossier:
            unite = os.path.join(dossier, "ntfy.service")
            if contenu is not None:
                with open(unite, "w", encoding="utf-8") as flux:
                    flux.write(contenu)
            enveloppe = (
                "set -e\n"
                "log() { :; }\n"
                "id() { return 0; }\n"
                "SYSTEMD_UNIT=%s\n" % unite
            ) + constantes() + extraire_fonction(
                "create_systemd_service") + extraire_fonction(
                "refresh_systemd_service") + "\nrefresh_systemd_service\n"
            fait = jouer(enveloppe)
            texte = None
            if os.path.exists(unite):
                with open(unite, encoding="utf-8") as flux:
                    texte = flux.read()
            return texte, fait

    def test_l_ancienne_unite_recoit_la_base_des_comptes(self):
        texte, fait = self._jouer(self.ANCIENNE)
        self.assertEqual(fait.returncode, 0, fait.stderr)
        chemins = re.search(r"^ReadWritePaths=(.*)$", texte, re.M).group(1)
        self.assertIn("/var/lib/ntfy", chemins.split())
        # Le binaire qu'elle lancait est garde.
        self.assertIn("ExecStart=/opt/ntfy/bin/ntfy serve", texte)

    def test_une_unite_d_une_autre_main_n_est_pas_touchee(self):
        autre = self.ANCIENNE.replace(
            "Description=ntfy push notification server",
            "Description=ntfy, reglee a la main")
        texte, fait = self._jouer(autre)
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(texte, autre)

    def test_sans_unite_rien_n_est_cree(self):
        # Celle d'un paquet vit ailleurs ; en ecrire une la masquerait.
        texte, fait = self._jouer(None)
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIsNone(texte)


class TestCompteAdministrateur(unittest.TestCase):
    """`ensure_admin_user` : la CLI, son environnement, la base des comptes."""

    BOUCHON_NTFY = """#!/bin/sh
# Note ses arguments et ses variables NTFY_*, puis joue « user list » ou
# « user add » sur un fichier d'etat du bac a sable.
J="$BAC/ntfy.log"
echo "ARGS $*" >> "$J"
env | grep '^NTFY_' | sed 's/^/ENV /' >> "$J"
case " $* " in
  *" list "*)
    [ -f "$BAC/admin" ] && echo "user erplibre (role: admin, tier: none)" >&2
    exit 0 ;;
  *" add "*) : > "$BAC/lib/user.db"; exit 0 ;;
esac
exit 0
"""

    # runuser -u <compte> -- <commande>... : note l'argv, lance la commande.
    BOUCHON_RUNUSER = ('#!/bin/sh\necho "runuser $*" >> "$BAC/argv.log"\n'
                       'while [ "$1" != "--" ]; do shift; done\nshift\n'
                       'exec "$@"\n')

    def _jouer(self, deja_present=False, public="0", compte=True):
        """`compte` : le compte « ntfy » existe sur l'hote."""
        dossier = tempfile.mkdtemp()
        self.addCleanup(subprocess.run, ["rm", "-rf", dossier])
        os.makedirs(os.path.join(dossier, "bin"))
        os.makedirs(os.path.join(dossier, "lib"))
        bouchon = os.path.join(dossier, "bin", "ntfy")
        with open(bouchon, "w") as flux:
            flux.write(self.BOUCHON_NTFY)
        os.chmod(bouchon, stat.S_IRWXU)
        # `env` passe devant le vrai sur PATH et note ses arguments : un
        # secret donne en NOM=valeur a env se lit dans /proc/<pid>/cmdline.
        bouchon_env = os.path.join(dossier, "bin", "env")
        with open(bouchon_env, "w") as flux:
            flux.write('#!/bin/sh\necho "ENVARGV $*" >> "$BAC/argv.log"\n'
                       'exec %s "$@"\n' % shutil.which("env"))
        os.chmod(bouchon_env, stat.S_IRWXU)
        bouchon_runuser = os.path.join(dossier, "bin", "runuser")
        with open(bouchon_runuser, "w") as flux:
            flux.write(self.BOUCHON_RUNUSER)
        os.chmod(bouchon_runuser, stat.S_IRWXU)
        if deja_present:
            open(os.path.join(dossier, "admin"), "w").close()
            open(os.path.join(dossier, "lib", "user.db"), "w").close()
        with open(os.path.join(dossier, "server.yml"), "w") as flux:
            flux.write('listen-http: ":8080"\n'
                       'auth-file: "%s/lib/user.db"\n'
                       'auth-default-access: "deny-all"\n' % dossier)
        enveloppe = (
            "set -e\n"
            "log() { echo \"$*\"; }\n"
            "id() { return %d; }\n"
            "chown() { echo \"chown $*\" >> %s/chown.log; }\n"
            "CONFIG_DIR=%s\n"
            "AUTH_FILE=/inexistant/user.db\n"
            "NTFY_PUBLIC=%s\n"
            "NTFY_ADMIN_USER=erplibre\n"
            "NTFY_NON_INTERACTIVE=1\n"
            % (0 if compte else 1, dossier, dossier, public)
        ) + extraire_fonction("ntfy_cli") + extraire_fonction(
            "ensure_admin_user") + "\nensure_admin_user\n"
        env = {
            "BAC": dossier,
            "PATH": os.path.join(dossier, "bin") + os.pathsep
            + os.environ.get("PATH", ""),
            # Ce que l'appelant de l'installateur exporte : la CLI ntfy le
            # lirait AVANT --config.
            "NTFY_BASE_URL": "http://ntfy.exemple.test:8080",
            "NTFY_AUTH_FILE": "/tmp/autre.db",
        }
        fait = jouer(enveloppe, env)
        self.argv = lignes(os.path.join(dossier, "argv.log"))
        return (fait, lignes(os.path.join(dossier, "ntfy.log")),
                lignes(os.path.join(dossier, "chown.log")), dossier)

    def test_chaque_appel_porte_config_et_aucune_variable_ntfy(self):
        fait, journal, _, dossier = self._jouer()
        self.assertEqual(fait.returncode, 0, fait.stderr)
        appels = [l for l in journal if l.startswith("ARGS ")]
        self.assertEqual(len(appels), 2, journal)
        config = "--config %s/server.yml" % dossier
        for appel in appels:
            self.assertIn(config, appel)
        self.assertIn(" list", appels[0])
        self.assertIn(" add --role=admin erplibre", appels[1])
        variables = [l for l in journal if l.startswith("ENV ")]
        # Seul le mot de passe passe, et seulement a la creation.
        self.assertEqual([v.split("=")[0] for v in variables],
                         ["ENV NTFY_PASSWORD"])

    def test_le_mot_de_passe_sort_une_fois_en_marqueur(self):
        fait, journal, _, _ = self._jouer()
        marqueurs = [l for l in fait.stdout.splitlines()
                     if l.startswith("@@ADMIN_PASSWORD ")]
        self.assertEqual(len(marqueurs), 1, fait.stdout)
        motdepasse = marqueurs[0].split(" ", 1)[1]
        self.assertRegex(motdepasse, r"^[A-Za-z0-9]{24}$")
        self.assertIn("ENV NTFY_PASSWORD=" + motdepasse, journal)
        # Le marqueur suffit au menu : pas de second affichage en clair.
        self.assertEqual(fait.stdout.count(motdepasse), 1)

    def test_le_mot_de_passe_ne_passe_dans_aucun_argv(self):
        """Tout compte local lit les arguments d'un processus (`ps`), pas
        son environnement : le mot de passe ne voyage que par ce dernier."""
        fait, journal, _, _ = self._jouer()
        self.assertEqual(fait.returncode, 0, fait.stderr)
        motdepasse = [l for l in fait.stdout.splitlines()
                      if l.startswith("@@ADMIN_PASSWORD ")][0].split()[1]
        arguments = self.argv + [l for l in journal if l.startswith("ARGS ")]
        self.assertTrue(arguments, journal)
        for ligne in arguments:
            self.assertNotIn(motdepasse, ligne)
        # Il arrive bien a la CLI, par l'environnement.
        self.assertIn("ENV NTFY_PASSWORD=" + motdepasse, journal)

    def test_la_cli_tourne_sous_le_compte_du_service(self):
        """Le dossier de la base appartient au compte « ntfy », qui peut y
        poser user.db-wal ou -shm en lien vers un fichier de root : SQLite
        suit ces liens. Lancee sous ce compte, la CLI n'ecrit rien que ce
        compte ne puisse deja ecrire, et root n'a rien a lui rendre."""
        fait, journal, chowns, _ = self._jouer()
        self.assertEqual(fait.returncode, 0, fait.stderr)
        sous_compte = [a for a in self.argv if a.startswith("runuser ")]
        self.assertEqual(len(sous_compte), 2, self.argv)
        for appel in sous_compte:
            self.assertTrue(appel.startswith("runuser -u ntfy -- ntfy user "),
                            appel)
        self.assertEqual(chowns, [])

    def test_compte_present_aucun_mot_de_passe_ni_chown(self):
        fait, journal, chowns, _ = self._jouer(deja_present=True)
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertNotIn("@@ADMIN_PASSWORD", fait.stdout)
        self.assertFalse([l for l in journal if " add " in l], journal)
        self.assertEqual(chowns, [])

    def test_sans_compte_ntfy_la_cli_tourne_en_root(self):
        """Sans compte « ntfy », aucun autre compte ne possede le dossier."""
        fait, journal, chowns, _ = self._jouer(compte=False)
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertFalse([a for a in self.argv if a.startswith("runuser ")])
        self.assertEqual(len([l for l in journal if l.startswith("ARGS ")]), 2)
        self.assertEqual(chowns, [])

    def test_public_aucun_compte(self):
        fait, journal, chowns, _ = self._jouer(public="1")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(journal, [])
        self.assertNotIn("@@ADMIN_PASSWORD", fait.stdout)


class TestArch(unittest.TestCase):
    """`install_arch` : le depot officiel d'abord, jamais d'AUR sans tty."""

    def _jouer(self, dans_depot, non_interactif):
        with tempfile.TemporaryDirectory() as dossier:
            journal = os.path.join(dossier, "appels")
            enveloppe = (
                "set -e\n"
                "log() { :; }\n"
                "J=%s\n"
                "pacman() { echo \"pacman $*\" >> $J;"
                " [ \"$1\" = -Si ] && return %d; return 0; }\n"
                # yay et paru sont presents : seul le choix les ecarte.
                "yay() { echo \"yay $*\" >> $J; }\n"
                "paru() { echo \"paru $*\" >> $J; }\n"
                "sudo() { shift 2; \"$@\"; }\n"
                "systemctl() { echo \"systemctl $*\" >> $J; }\n"
                "get_latest_version() { echo 2.0.0; }\n"
                "install_binary() { echo \"install_binary $*\" >> $J; }\n"
                "create_systemd_service() { echo \"unit $*\" >> $J; }\n"
                "NTFY_NON_INTERACTIVE=%s\n"
                % (journal, 0 if dans_depot else 1, non_interactif)
            ) + extraire_fonction("non_interactive") + extraire_fonction(
                "install_arch") + "\ninstall_arch\n"
            fait = jouer(enveloppe)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            return lignes(journal)

    def test_paquet_du_depot_installe_par_pacman_sans_aur(self):
        appels = self._jouer(dans_depot=True, non_interactif="1")
        self.assertIn("pacman -Si ntfy", appels)
        self.assertIn("pacman -S --noconfirm ntfy", appels)
        self.assertFalse([a for a in appels if a.startswith(("yay", "paru"))])
        self.assertFalse([a for a in appels if a.startswith("install_binary")])

    def test_hors_depot_non_interactif_le_binaire_jamais_l_aur(self):
        appels = self._jouer(dans_depot=False, non_interactif="1")
        self.assertIn("install_binary 2.0.0", appels)
        self.assertFalse([a for a in appels if a.startswith(("yay", "paru"))])
        self.assertNotIn("pacman -S --noconfirm ntfy", appels)

    def test_le_depot_passe_avant_l_aur_meme_en_interactif(self):
        appels = self._jouer(dans_depot=True, non_interactif="0")
        self.assertIn("pacman -S --noconfirm ntfy", appels)
        self.assertFalse([a for a in appels if a.startswith("yay")])

    def test_hors_depot_interactif_l_aur_reste_possible(self):
        appels = self._jouer(dans_depot=False, non_interactif="0")
        self.assertIn("yay -S --noconfirm ntfy", appels)


class TestDebianNonInteractif(unittest.TestCase):
    def test_dpkg_garde_la_config_sans_poser_de_question(self):
        # Une config modifiee sur place fait poser a dpkg une question sur
        # le tty : au bout de « ssh -t », l'installation attendrait.
        with tempfile.TemporaryDirectory() as dossier:
            journal = os.path.join(dossier, "appels")
            enveloppe = (
                "set -e\n"
                "log() { :; }\n"
                "J=%s\n"
                "dpkg() { [ \"$1\" = --print-architecture ] && echo amd64"
                " && return 0; echo \"dpkg $* FRONTEND=$DEBIAN_FRONTEND\""
                " >> $J; }\n"
                "curl() { : > \"${@: -1}\"; }\n"
                "apt-get() { echo \"apt-get $*\" >> $J; }\n"
                "NTFY_NON_INTERACTIVE=1\n" % journal
            ) + extraire_fonction("non_interactive") + extraire_fonction(
                "install_deb") + "\ninstall_deb 2.0.0\n"
            fait = jouer(enveloppe)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            appels = lignes(journal)
        self.assertEqual(len(appels), 1, appels)
        self.assertIn("--force-confold", appels[0])
        self.assertIn("FRONTEND=noninteractive", appels[0])


class TestMain(unittest.TestCase):
    """`main` : le code de sortie et la derniere ligne disent l'etat reel."""

    def _jouer(self, etats, restart_echoue=False):
        """`etats` : sorties successives de `systemctl is-active ntfy`."""
        with tempfile.TemporaryDirectory() as dossier:
            journal = os.path.join(dossier, "appels")
            with open(os.path.join(dossier, "etats"), "w") as flux:
                flux.write("\n".join(etats) + "\n")
            enveloppe = (
                "set -e\n"
                "log() { echo \"$*\"; }\n"
                "J=%s\nE=%s/etats\n"
                "check_root() { :; }\n"
                "detect_os() { OS=debian; OS_LIKE=; }\n"
                "ntfy() { return 0; }\n"
                "configure_ntfy() { echo configure >> $J; }\n"
                "ensure_admin_user() { echo admin >> $J; }\n"
                "refresh_systemd_service() { echo refresh >> $J; }\n"
                "sleep() { :; }\n"
                "hostname() { echo 192.0.2.10; }\n"
                "systemctl() {\n"
                "  if [ \"$1\" = is-active ]; then\n"
                "    e=$(head -n 1 $E); [ \"$(wc -l < $E)\" -gt 1 ]"
                " && sed -i 1d $E\n"
                "    echo \"$e\"; [ \"$e\" = active ]; return\n"
                "  fi\n"
                "  echo \"systemctl $*\" >> $J\n"
                "  [ \"$1\" != restart ] || [ %d = 0 ]\n"
                "}\n"
                "NTFY_PORT=8080\nNTFY_CERT_FILE=\nNTFY_KEY_FILE=\n"
                "NTFY_HTTPS_PORT=\nCONFIG_DIR=/x\n"
                % (journal, dossier, 1 if restart_echoue else 0)
            ) + extraire_fonction("non_interactive") + extraire_fonction(
                "enable_service") + extraire_fonction(
                "service_state") + extraire_fonction("main") + "\nmain\n"
            fait = jouer(enveloppe)
            return fait, lignes(journal)

    def test_service_en_echec_code_non_nul_et_marqueur(self):
        fait, appels = self._jouer(["failed"])
        self.assertNotEqual(fait.returncode, 0, fait.stdout)
        self.assertEqual(fait.stdout.splitlines()[-1], "@@ACTIVE ntfy failed")
        # Le compte est cree avant le premier demarrage du service.
        self.assertLess(appels.index("admin"),
                        appels.index("systemctl restart ntfy"))

    def test_deja_installe_l_unite_est_relue_avant_le_redemarrage(self):
        # Une unite ecrite par une version anterieure du script ne peut
        # ecrire user.db ; sans relecture, chaque relance finit en echec.
        _, appels = self._jouer(["active"])
        self.assertIn("refresh", appels)
        self.assertLess(appels.index("refresh"),
                        appels.index("systemctl restart ntfy"))

    def test_service_actif_code_nul_et_marqueur(self):
        fait, _ = self._jouer(["active"])
        self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
        self.assertEqual(fait.stdout.splitlines()[-1], "@@ACTIVE ntfy active")

    def test_un_demarrage_en_cours_est_attendu(self):
        fait, _ = self._jouer(["activating", "activating", "active"])
        self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
        self.assertEqual(fait.stdout.splitlines()[-1], "@@ACTIVE ntfy active")

    def test_un_redemarrage_refuse_donne_quand_meme_le_marqueur(self):
        fait, _ = self._jouer(["inactive"], restart_echoue=True)
        self.assertNotEqual(fait.returncode, 0)
        self.assertEqual(fait.stdout.splitlines()[-1],
                         "@@ACTIVE ntfy inactive")


if __name__ == "__main__":
    sys.exit(not unittest.main(exit=False).result.wasSuccessful())
