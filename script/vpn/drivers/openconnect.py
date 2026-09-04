#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""OpenConnect : le seul pilote où aucun secret ne touche un fichier.

`--passwd-on-stdin` fait lire le mot de passe sur l'entrée standard. Il ne
passe donc ni par un argument (`/proc/<pid>/cmdline`, lisible par tous), ni
par un fichier, même en tmpfs. C'est le cas idéal, et il vaut la peine d'être
nommé : les autres pilotes composent avec des technologies qui EXIGENT un
fichier, celui-ci n'en a pas besoin.

Un client, plusieurs protocoles : AnyConnect (Cisco), Pulse/Juniper,
GlobalProtect (Palo Alto), Fortinet, F5, Array. `--protocol` décide.

`--non-inter` est passé volontairement. Sans lui, un certificat serveur
inconnu déclenche une question — et openconnect la lirait sur l'entrée
standard, celle par laquelle arrive justement le mot de passe. Le tunnel
échouerait sur un « certificate verify failed » incompréhensible. Avec
`--non-inter`, openconnect refuse tout de suite ET imprime la ligne
`--servercert sha256:…` à recopier dans le champ `oc_servercert` du profil.

Les routes appartiennent au serveur : c'est `vpnc-script` qui les pose, à
partir de ce que le concentrateur pousse. Le profil peut en AJOUTER, il ne
les remplace pas — d'où `needs_routes = False`.

Deux « groupes » que rien ne distingue au premier regard
--------------------------------------------------------
Un même concentrateur héberge plusieurs services, et deux mécanismes tout
à fait différents servent à en désigner un. Les confondre ne donne pas une
erreur de syntaxe : cela donne le formulaire d'authentification d'un AUTRE
service, donc un refus d'identifiants sur des identifiants justes.

`oc_usergroup` → `--usergroup` : le CHEMIN D'URL de la connexion initiale.
`--usergroup=X` et `https://hôte/X` sont la même chose. C'est ce que porte
la balise `<UserGroup>` d'un profil AnyConnect (`.xml`), à ne pas confondre
avec son `<HostName>`, qui n'est qu'un libellé d'affichage.

`oc_authgroup` → `--authgroup` : une valeur à choisir dans un MENU
DÉROULANT du formulaire, quand le serveur en présente un. Cisco l'appelle
authgroup, Juniper et Fortinet realm, F5 domain, GlobalProtect gateway.

Un site qui remet un profil `.xml` désigne son service par le chemin ; un
site qui décrit une liste à choisir dans une capture d'écran désigne le
sien par le menu déroulant. Les deux champs coexistent parce que les deux
cas existent.

SSO / SAML — le cas du « formulaire web »
-----------------------------------------
Quand le concentrateur authentifie par un fournisseur d'identité (Azure AD,
Okta, Duo…), il n'y a pas de mot de passe à envoyer : il faut compléter une
page web. Cisco annonce ce besoin de DEUX façons, et openconnect n'en sait
traiter qu'une seule depuis un CLI :

· `single-sign-on-external-browser` — openconnect lance le programme donné à
  `--external-browser`, écoute sur son port local 29786 et attend la
  redirection. Fonctionne avec un paquet de distribution ;
· `sso-v2` — le concentrateur exige un navigateur INTÉGRÉ au client. Il faut
  alors une webview compilée dans openconnect (libwebkit2gtk), et Debian,
  Ubuntu, Fedora et Arch la compilent tous sans. openconnect s'arrête sur
  « No SSO handler », et `--external-browser` n'y change rien : il ne prend
  ce chemin que si le SERVEUR a annoncé la méthode « navigateur externe ».

C'est la passerelle qui choisit, groupe de connexion par groupe de connexion.
Pour le second cas, `oc_sso_helper` délègue la seule étape que ce pilote ne
sait pas faire.

Déléguer l'authentification, garder le tunnel
---------------------------------------------
`openconnect-sso --authenticate json` pilote un vrai navigateur, laisse
l'humain s'authentifier, et rend `{host, cookie, fingerprint}` sans monter
aucun tunnel. Le pilote reprend alors la main et monte lui-même, avec
`--cookie-on-stdin`.

La frontière est là, et elle est le tout de ce dispositif : le greffon ne
fait que la danse SAML ; le PROFIL reste la source de vérité pour le nom
d'interface, les routes ajoutées, les fichiers d'état et le diagnostic. Un
tunnel monté par le greffon lui-même s'appellerait `tun0`, ne laisserait
rien dans /run, et `status`, `diagnose` et `down` ne le verraient pas.

Deux détails qui font échouer le cookie si on les néglige :

· l'IDENTITÉ annoncée doit être la même aux deux étapes. Le concentrateur
  délivre le cookie à un client qui s'est présenté sous une version donnée ;
  monter ensuite sous une autre le fait refuser. D'où `oc_ac_version`, passé
  au greffon ET à openconnect ;
· l'EMPREINTE que rend le greffon est celle contre laquelle il a authentifié.
  Elle est préférée à `oc_servercert` du profil, qui peut dater. Beaucoup de
  ces passerelles présentent une chaîne que le magasin du système ne valide
  pas (« signer not found »), et `--non-inter` la refuserait sans elle.

Le greffon lance un navigateur : il tourne donc SANS sudo, sous
l'utilisateur, avec son affichage. Le cookie qu'il rend ne touche aucun
fichier — il vit dans une variable, part par l'entrée standard, et est
masqué de tout affichage dès qu'il existe.

Les concentrateurs qui tronquent le mot de passe
------------------------------------------------
Certains ne comparent que les N premiers caractères — un reste d'annuaire
qui borne la longueur, dont le site documente la valeur. Un mot de passe
plus long est alors refusé, et le refus se lit « identifiants invalides » :
rien n'y met la longueur en cause, et on cherche du côté du groupe
d'authentification ou du certificat.

`oc_password_len` déclare cette borne. Le champ ne TRONQUE rien : le coffre
reste la source de vérité de ce qu'on envoie, et un outil qui couperait un
mot de passe en silence rendrait un jour un « ça marchait pourtant »
indébrouillable — le jour où le site lève la limite. Il fait deux choses,
toutes deux à un moment où l'humain peut agir : le menu l'annonce avant la
saisie du secret, et le montage compare les longueurs si ce qui est déposé
la dépasse. Zéro = aucune limite.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil

from script.todo.todo_i18n import t
from script.vpn import valid
from script.vpn.drivers.base import (
    VpnDriver,
    interface_exists,
    wait_for_interface_address,
)
from script.vpn.vault import PLACEHOLDER

# Emplacements conventionnels du greffon SSO, essayés dans l'ordre après
# le PATH. `pipx install openconnect-sso` pose le premier ; une install en
# environnement virtuel dédié n'est trouvable que par `oc_sso_helper`.
SSO_HELPER_NAME = "openconnect-sso"
SSO_HELPER_PATHS = (
    "~/.local/bin/openconnect-sso",
    "~/.local/share/openconnect-sso-venv/bin/openconnect-sso",
)

# Réglages de rendu que le greffon hérite, SAUF s'ils sont déjà dans
# l'environnement — qui les a posés sait mieux.
#
# Le navigateur du greffon est un Chromium embarqué. Sur une machine
# virtuelle, il n'y a pas d'accélération exploitable : il se rabat sur
# Vulkan, échoue à importer sa mémoire graphique et la fenêtre MEURT au
# milieu de l'authentification. Le rendu logiciel est plus lent et il
# aboutit, ce qui est le seul critère ici.
SSO_RENDER_ENV = {
    "QTWEBENGINE_CHROMIUM_FLAGS": (
        "--disable-gpu --disable-gpu-compositing"
        " --disable-features=Vulkan --disable-dev-shm-usage"
    ),
    "LIBGL_ALWAYS_SOFTWARE": "1",
}

SSO_RENDER_ENV_HINT = " ".join(f"{k}={v!r}" for k, v in SSO_RENDER_ENV.items())

# Ce que ce client sait parler. La liste vient de `openconnect --protocol`.
PROTOCOLS = ("anyconnect", "nc", "pulse", "gp", "f5", "fortinet", "array")


class OpenconnectDriver(VpnDriver):
    name = "openconnect"
    label = "OpenConnect"
    binaries = ("openconnect", "ip")
    # Non obligatoire : en SSO il n'y a AUCUN mot de passe à déposer, et le
    # menu ne doit pas réclamer un secret que la méthode n'utilise pas. La
    # vraie exigence dépend du mode, elle est donc dans `up`.
    secret_fields = (("password", "VPN password", False),)
    iface_kind = "tun"
    hint = "Cisco AnyConnect, Pulse, GlobalProtect, Fortinet appliances"
    user_field = "oc_user"
    # Le MTU vient du serveur (ou du .ovpn), pas du profil.
    uses_mtu = False
    # Le serveur pousse les routes : exiger une route déclarée serait une
    # fausse exigence.
    needs_routes = False
    defaults = {
        "port": 443,
        "oc_user": "",
        "oc_protocol": "anyconnect",
        "oc_authgroup": "",
        "oc_servercert": "",
        # SSO : le concentrateur authentifie par un fournisseur d'identité,
        # dans un navigateur. Voir l'en-tête du fichier.
        "oc_sso": False,
        # Programme lancé avec l'URL de connexion. Vide = `echo`, qui
        # l'affiche : c'est ce qu'on veut sur une machine sans écran.
        "oc_external_browser": "",
        # Nombre de caractères du mot de passe que le concentrateur compare.
        # 0 = aucune limite. Voir l'en-tête du fichier.
        "oc_password_len": 0,
        # Chemin d'URL de la connexion initiale. Voir l'en-tête : ce n'est
        # PAS `oc_authgroup`, et les confondre mène à un formulaire
        # d'authentification qui n'est pas celui du service visé.
        "oc_usergroup": "",
        # Greffon qui pilote un navigateur pour l'étape SAML. Vide : cherché
        # dans le PATH puis aux emplacements conventionnels. Voir l'en-tête.
        "oc_sso_helper": "",
        # Version de client AnyConnect annoncée. Elle doit être la MÊME à
        # l'authentification et au montage : le concentrateur délivre le
        # cookie à un client qui s'est présenté ainsi.
        "oc_ac_version": "4.7.00136",
    }
    form_fields = (
        ("oc_user", "VPN user", "text", False),
        (
            "oc_protocol",
            "Protocol (anyconnect, nc, pulse, gp, f5, fortinet, array)",
            "text",
            False,
        ),
        (
            "oc_usergroup",
            "Connection group in the URL — <UserGroup> of an AnyConnect"
            " profile (optional)",
            "text",
            False,
        ),
        (
            "oc_authgroup",
            "Authentication group / realm (optional)",
            "text",
            True,
        ),
        (
            "oc_servercert",
            "Pinned server certificate (sha256:... , printed on first refusal)",
            "text",
            True,
        ),
        (
            "oc_sso",
            "Authentication through a web form (SAML / SSO)?",
            "flag",
            False,
        ),
        (
            "oc_external_browser",
            "Browser command for SSO (empty: show the URL to open yourself)",
            "path",
            True,
        ),
        (
            "oc_sso_helper",
            "SSO helper driving a real browser (empty: openconnect-sso from"
            " the PATH)",
            "path",
            True,
        ),
        (
            "oc_ac_version",
            "AnyConnect version announced to the gateway",
            "text",
            True,
        ),
        (
            "oc_password_len",
            "Password characters the server compares (0: no limit)",
            "int",
            True,
        ),
        ("port", "HTTPS port", "int", True),
    )

    # ------------------------------------------------------------------
    @property
    def iface(self):
        """Interface NOMMÉE, et non découverte : openconnect sait le faire
        (`--interface`), et un nom connu d'avance rend `status` fiable même
        après un redémarrage du CLI. Tronqué à 15 caractères."""
        return f"vpn-{self.name_tag}"[:15]

    @classmethod
    def validate_profile(cls, profile):
        # Le mode d'abord : en SSO, c'est le fournisseur d'identité qui
        # décide de qui on est, et exiger un utilisateur ici refuserait un
        # profil parfaitement valide.
        valid.flag(profile, "oc_sso")
        valid.text(
            profile,
            "oc_user",
            "Utilisateur VPN",
            required=not profile["oc_sso"],
        )
        protocol = valid.text(profile, "oc_protocol", "Protocole")
        if protocol not in PROTOCOLS:
            raise valid.ProfileError(
                f"Protocole inconnu : « {protocol} »."
                f" Connus : {', '.join(PROTOCOLS)}."
            )
        valid.text(
            profile,
            "oc_usergroup",
            "Groupe de connexion (chemin d'URL)",
            required=False,
            pattern=valid.URL_PATH_RE,
        )
        valid.text(
            profile,
            "oc_authgroup",
            "Groupe d'authentification",
            required=False,
        )
        valid.text(
            profile,
            "oc_servercert",
            "Empreinte du certificat serveur",
            required=False,
        )
        valid.port(profile, "port", "Port HTTPS")
        # 128 comme plafond : au-delà, ce n'est plus une borne d'annuaire
        # mais une valeur tapée de travers, et l'accepter ferait taire
        # l'avertissement pour tous les mots de passe.
        valid.integer(
            profile,
            "oc_password_len",
            "Longueur de mot de passe comparée",
            0,
            128,
        )
        valid.path(
            profile,
            "oc_external_browser",
            "Programme navigateur",
            required=False,
        )
        valid.path(profile, "oc_sso_helper", "Greffon SSO", required=False)
        valid.text(
            profile,
            "oc_ac_version",
            "Version AnyConnect annoncée",
            required=False,
        )

    @property
    def browser(self):
        """Programme lancé avec l'URL de connexion SSO.

        `echo` par défaut : sur une machine sans écran, afficher l'URL est
        exactement ce qu'on veut — openconnect attend ensuite la redirection
        sur son port 29786."""
        return self.profile.get("oc_external_browser") or "echo"

    @property
    def password_len(self):
        """Longueur comparée par le concentrateur, 0 si aucune limite."""
        try:
            return int(self.profile.get("oc_password_len") or 0)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def wants_secrets(cls, profile):
        """Rien à lire au coffre en SSO : c'est le fournisseur d'identité
        qui authentifie, dans un navigateur, et aucun mot de passe stocké
        n'entre dans l'échange."""
        return not profile.get("oc_sso")

    def secret_notes(self):
        """La borne de longueur, dite avant la saisie du mot de passe.

        En SSO il n'y a pas de mot de passe à déposer : annoncer une borne
        de longueur y serait une consigne sans objet.
        """
        limit = self.password_len
        if not limit or self.profile.get("oc_sso"):
            return []
        return [
            t(
                "This gateway compares only the first {limit} characters of"
                " the password: store just those, a longer one is refused."
            ).format(limit=limit)
        ]

    # ------------------------------------------------------------------
    # SSO délégué : le greffon authentifie, ce pilote monte
    # ------------------------------------------------------------------
    @property
    def sso_helper(self):
        """Chemin du greffon SSO, "" s'il est introuvable.

        Le champ du profil d'abord — c'est le seul moyen de désigner une
        installation en environnement virtuel dédié. Puis le PATH, puis les
        emplacements conventionnels.

        Un chemin déclaré mais inexécutable rend "" ; c'est `up` qui le DIT,
        plutôt que de se replier sans bruit sur un autre chemin
        d'authentification.
        """
        declared = self.profile.get("oc_sso_helper") or ""
        if declared:
            path = os.path.expanduser(declared)
            return path if os.access(path, os.X_OK) else ""
        found = shutil.which(SSO_HELPER_NAME)
        if found:
            return found
        for candidate in SSO_HELPER_PATHS:
            path = os.path.expanduser(candidate)
            if os.access(path, os.X_OK):
                return path
        return ""

    @property
    def ac_version(self):
        return self.profile.get("oc_ac_version") or "4.7.00136"

    def helper_command(self):
        """La ligne du greffon : elle ne porte AUCUN secret.

        Les variables de rendu sont préfixées plutôt que posées dans
        l'environnement de ce processus : la commande affichée est alors
        exactement celle qui s'exécute, ce que `--dry-run` promet.
        """
        p = self.profile
        target = p["server"]
        if p.get("oc_usergroup"):
            target = f"{target}/{p['oc_usergroup']}"
        parts = []
        for key, value in SSO_RENDER_ENV.items():
            if key not in os.environ:
                parts.append(f"{key}={shlex.quote(value)}")
        parts += [
            shlex.quote(self.sso_helper),
            "--authenticate",
            "json",
            f"--server={shlex.quote(target)}",
            f"--ac-version={shlex.quote(self.ac_version)}",
        ]
        if p.get("oc_authgroup"):
            parts.append(f"--authgroup={shlex.quote(p['oc_authgroup'])}")
        # `| tee /dev/stderr` : la sortie standard du greffon est à la fois
        # LUE par nous et VUE par l'utilisateur.
        #
        # Le processus navigateur du greffon journalise sur sa SORTIE
        # STANDARD — il n'a pas de configuration propre et hérite du
        # journaliseur par défaut de structlog, qui imprime là. Le parent,
        # lui, journalise sur l'erreur standard. Capturer la sortie sans la
        # dupliquer laisse donc l'utilisateur devant un terminal muet
        # pendant qu'une fenêtre attend son geste, et mélange ces lignes au
        # JSON qu'on doit lire.
        return " ".join(parts) + " | tee /dev/stderr"

    @staticmethod
    def extract_json(text):
        """Le dernier objet JSON de `text`, ou None.

        La sortie du greffon MÊLE ses lignes de journal au JSON final :
        `json.loads` sur le tout échoue même quand l'authentification a
        réussi. On isole donc les accolades équilibrées, et on retient le
        dernier objet qui parse et qui porte un cookie — le dernier, parce
        qu'une ligne de journal peut elle aussi contenir des accolades.
        """
        best = None
        depth = 0
        start = -1
        for index, char in enumerate(text):
            if char == "{":
                if depth == 0:
                    start = index
                depth += 1
            elif char == "}" and depth:
                depth -= 1
                if depth == 0 and start >= 0:
                    try:
                        candidate = json.loads(text[start : index + 1])
                    except ValueError:
                        continue
                    if isinstance(candidate, dict) and candidate.get("cookie"):
                        best = candidate
        return best

    def _kill_helper_strays(self, runner):
        """Les navigateurs que le greffon laisse derrière lui.

        Le greffon lance son navigateur dans des processus séparés. Quand
        il est tué — délai dépassé — eux survivent, et le suivant repart
        sur une machine déjà encombrée. Reconnaissables sans ambiguïté :
        QtWebEngine porte `--application-name=openconnect-sso`.
        """
        # `[Q]t…` et non `Qt…` : `pkill -f` compare le motif à TOUTES les
        # lignes de commande, y compris celle du shell qui le porte. Le
        # motif écrit en clair s'y trouve donc lui-même, et pkill tuerait
        # son propre parent avant d'avoir servi. Entre crochets, le motif
        # désigne toujours « Qt… » mais ne se reconnaît plus dans le texte
        # qui le contient.
        runner.cmd(
            "fermer les navigateurs laissés par le greffon",
            "pkill -f '[Q]tWebEngineProcess.*application-name=openconnect-sso'",
            sudo=False,
            check=False,
        )

    def authenticate_with_helper(self, runner):
        """(cookie, empreinte) rendus par le greffon, ou (None, None).

        Sans sudo, et c'est essentiel : le greffon ouvre un navigateur, donc
        il lui faut l'affichage et le trousseau de l'UTILISATEUR. Sous sudo
        il perdrait les deux.

        `capture="stdout"` : le JSON est LU, les messages de progression du
        greffon restent VUS. L'authentification réclame un geste humain —
        taper un mot de passe, approuver une notification — et une attente
        muette de plusieurs minutes ressemble à un blocage.
        """
        helper = self.sso_helper
        if not helper:
            report = runner.warn if runner.dry_run else runner.fail
            report(
                "Greffon SSO introuvable. Ce concentrateur exige un"
                " navigateur intégré, que l'openconnect des distributions"
                " n'a pas. Installer openconnect-sso, ou renseigner"
                " oc_sso_helper avec son chemin."
            )
            return None, None
        self._explain_the_web_form(runner)
        code, out = runner.cmd(
            "authentifier par formulaire web (navigateur du greffon)",
            self.helper_command(),
            sudo=False,
            check=False,
            capture="stdout",
            timeout=600,
        )
        if runner.dry_run:
            runner.info(
                "      (à blanc : le greffon rendrait un cookie de session"
                " et l'empreinte du certificat qu'il a vu)"
            )
            # L'empreinte du profil, faute de mieux : à blanc on ne peut pas
            # savoir celle que le greffon verrait, et une empreinte n'est
            # pas un secret — lui donner le marqueur des secrets ferait
            # lire au plan une nature qu'elle n'a pas.
            return PLACEHOLDER, self.profile.get("oc_servercert") or ""
        # Le VERDICT est le cookie, pas le code de retour : la commande est
        # un tube, et son code est celui de `tee`. Un cookie obtenu vaut
        # succès, quoi qu'ait rendu le tube.
        answer = self.extract_json(out)
        if answer is None:
            if code == 124:
                runner.fail(
                    "Le formulaire web n'a pas abouti dans le délai"
                    " imparti (10 min) : personne ne l'a complété, ou la"
                    " fenêtre ne s'est jamais affichée."
                )
            else:
                runner.fail(
                    f"Le greffon SSO n'a rendu aucun cookie (code {code})."
                )
            self._explain_helper_failure(runner)
            self._kill_helper_strays(runner)
            return None, None
        cookie = answer["cookie"]
        fingerprint = answer.get("fingerprint") or ""
        # Masqué DÈS qu'il existe : ce cookie ouvre le tunnel à lui seul, et
        # il va traverser des affichages et un enregistrement d'opérations.
        runner.add_secret(cookie)
        runner.ok("Authentification web réussie, cookie de session obtenu.")
        return cookie, fingerprint

    def cookie_command(self, fingerprint):
        """Le montage à partir d'un cookie. Le cookie N'Y EST PAS : il
        arrive par l'entrée standard, via `--cookie-on-stdin`.

        L'identité annoncée est celle sous laquelle le cookie a été délivré,
        sinon le concentrateur le refuse. L'empreinte du greffon prime sur
        celle du profil : c'est celle contre laquelle il a authentifié.
        """
        p = self.profile
        pinned = fingerprint or p.get("oc_servercert") or ""
        parts = [
            "openconnect",
            f"--protocol={shlex.quote(p['oc_protocol'])}",
            f"--useragent={shlex.quote(f'AnyConnect Linux_64 {self.ac_version}')}",
            f"--version-string={shlex.quote(self.ac_version)}",
            "--cookie-on-stdin",
            "--non-inter",
            "--background",
            f"--pid-file={shlex.quote(self.pid_file)}",
            f"--interface={shlex.quote(self.iface)}",
        ]
        if p.get("oc_usergroup"):
            parts.append(f"--usergroup={shlex.quote(p['oc_usergroup'])}")
        if pinned:
            parts.append(f"--servercert={shlex.quote(pinned)}")
        parts.append(shlex.quote(f"{p['server']}:{p['port']}"))
        return " ".join(parts)

    def _explain_the_web_form(self, runner):
        """Dit ce qui va s'ouvrir, AVANT que ça s'ouvre.

        Le greffon lance un navigateur et attend, silencieusement du point
        de vue du terminal. Sans cette annonce, la fenêtre surgit sans
        raison apparente et l'attente ressemble à un blocage.
        """
        runner.info(
            "      Une fenêtre de navigateur va s'ouvrir pour"
            " l'authentification. La compléter à l'écran ; le tunnel monte"
            " ensuite tout seul."
        )
        runner.info(
            "      Le mot de passe et le second facteur ne passent que par"
            " cette fenêtre : ni ce terminal ni le coffre ne les voient."
        )

    def _explain_helper_failure(self, runner):
        runner.info(
            "      → Fenêtre morte en cours de route ? Le navigateur"
            " embarqué échoue au rendu sur une machine sans accélération"
            f" exploitable. Relancer avec {SSO_RENDER_ENV_HINT}."
        )
        runner.info(
            "      → Identifiants refusés ? Ce service authentifie par le"
            " fournisseur d'identité, qui prend le mot de passe ENTIER."
            " Une limite oc_password_len ne s'applique PAS ici."
        )

    def command(self):
        """La ligne de commande, dans l'une de ses deux formes.

        Classique : le mot de passe arrive par l'entrée standard, grâce à
        `--passwd-on-stdin` — il n'est jamais dans la ligne de commande.

        SSO : il n'y a pas de mot de passe. Pas de `--non-inter` non plus,
        car l'échange avec le navigateur EST l'interaction ; l'interdire
        ferait échouer la seule étape qui compte.
        """
        p = self.profile
        parts = [
            "openconnect",
            f"--protocol={shlex.quote(p['oc_protocol'])}",
        ]
        if p["oc_user"]:
            parts.append(f"--user={shlex.quote(p['oc_user'])}")
        if p["oc_sso"]:
            parts.append(f"--external-browser={shlex.quote(self.browser)}")
        else:
            parts += ["--passwd-on-stdin", "--non-inter"]
        parts += [
            "--background",
            f"--pid-file={shlex.quote(self.pid_file)}",
            f"--interface={shlex.quote(self.iface)}",
        ]
        if p.get("oc_usergroup"):
            parts.append(f"--usergroup={shlex.quote(p['oc_usergroup'])}")
        if p.get("oc_authgroup"):
            parts.append(f"--authgroup={shlex.quote(p['oc_authgroup'])}")
        if p.get("oc_servercert"):
            parts.append(f"--servercert={shlex.quote(p['oc_servercert'])}")
        parts.append(shlex.quote(f"{p['server']}:{p['port']}"))
        return " ".join(parts)

    # ------------------------------------------------------------------
    def up(self, runner):
        """Trois chemins, un seul aboutissement.

        Le choix est explicite et se lit ici : greffon si le profil est en
        SSO et qu'un greffon existe, `--external-browser` en SSO sans
        greffon, mot de passe sinon. Un greffon sait faire les DEUX formes
        de SSO ; `--external-browser` n'en fait qu'une. D'où l'ordre.
        """
        p = self.profile
        if not self.ensure_ready(runner):
            return False
        # `secrets=False` : ce pilote n'écrit AUCUN fichier de secret, et
        # créer un répertoire pour rien serait laisser croire qu'il en a un.
        self.prepare_dirs(runner, secrets=False)

        if p["oc_sso"]:
            # Un greffon DÉCLARÉ mais inexécutable est une erreur, pas une
            # invitation à prendre l'autre chemin : basculer en silence
            # ferait échouer le montage sur « No SSO handler », trois
            # étages au-dessus de la vraie cause — un chemin fautif.
            declared = p.get("oc_sso_helper") or ""
            if declared and not self.sso_helper:
                report = runner.warn if runner.dry_run else runner.fail
                report(
                    f"Greffon SSO déclaré mais inexécutable : {declared}."
                    " Corriger oc_sso_helper, ou le vider pour chercher"
                    " openconnect-sso dans le PATH."
                )
                if not runner.dry_run:
                    return False
            monte = (
                self._up_delegated(runner)
                if self.sso_helper
                else self._up_external_browser(runner)
            )
        else:
            monte = self._up_password(runner)
        if not monte:
            return False
        if runner.dry_run:
            runner.info(f"      (à blanc : l'interface serait {self.iface})")
            return True
        return self._settle(runner)

    def _up_delegated(self, runner):
        """Le greffon authentifie, ce pilote monte. Voir l'en-tête."""
        cookie, fingerprint = self.authenticate_with_helper(runner)
        if cookie is None:
            return False
        code, _ = runner.cmd(
            f"monter le tunnel sur {self.profile['server']} avec le cookie",
            self.cookie_command(fingerprint),
            stdin=f"{cookie}\n",
            secret_stdin=True,
            check=False,
            timeout=120,
        )
        if code != 0 and not runner.dry_run:
            runner.fail("openconnect a refusé le cookie.")
            runner.info(
                "      → Un cookie de session est à usage unique et de"
                " courte durée. S'il a été délivré à un client annonçant"
                " une autre version que oc_ac_version, ou si le montage"
                " arrive trop tard, il est refusé : relancer."
            )
            return False
        return True

    def _up_external_browser(self, runner):
        """SSO sans greffon : openconnect s'en charge, s'il peut."""
        self._explain_the_sso_round_trip(runner)
        # Entrée standard VIDE, et non héritée du terminal. En SSO
        # openconnect ne lit jamais l'entrée standard : il attend la
        # redirection sur son port. Mais un concentrateur qui ne fait PAS de
        # SSO répond par un formulaire mot de passe, et openconnect se met
        # alors à le demander — sur le terminal, puisqu'il en a un, et sans
        # que `--non-inter` soit là pour l'en empêcher (en SSO la
        # redirection EST l'interaction).
        #
        # L'attente ressemble alors à l'attente normale du SSO, et chaque
        # essai revient en « Login failed » jusqu'au délai. Une entrée
        # standard fermée transforme cette boucle en un échec immédiat, que
        # le message d'aide ci-dessous explique.
        code, _ = runner.cmd(
            f"ouvrir la session {self.profile['oc_protocol']} sur"
            f" {self.profile['server']}",
            self.command(),
            stdin="",
            check=False,
            timeout=300,
        )
        if code != 0 and not runner.dry_run:
            runner.fail("openconnect a refusé.")
            # Les causes sont classées par ce que le message d'openconnect
            # permet de reconnaître, et non par fréquence : chacune se lit
            # sur une ligne précise de la sortie ci-dessus.
            runner.info(
                "      → « No SSO handler » : ce concentrateur exige le"
                " navigateur INTÉGRÉ (sso-v2), et l'openconnect des"
                " distributions est bâti sans. `--external-browser` ne"
                " s'applique que si le serveur annonce le mode navigateur"
                " externe. Installer openconnect-sso, ou renseigner"
                " oc_sso_helper : ce pilote délèguera l'étape web."
            )
            runner.info(
                "      → « username and password » demandé : alors le"
                " service ne fait PAS de SSO. Décocher « formulaire web »"
                " (oc_sso) et déposer le mot de passe."
            )
            runner.info(
                "      → Sinon : la redirection n'est jamais revenue sur le"
                " port 29786 (redirection ssh en place ?), ou le délai de"
                " 5 minutes a expiré avant la fin de l'authentification."
            )
            return False
        return True

    def _up_password(self, runner):
        """Mot de passe du coffre, par l'entrée standard."""
        if not self.secrets.get("password"):
            report = runner.warn if runner.dry_run else runner.fail
            report(
                "Aucun mot de passe dans le coffre, et le profil n'est pas"
                " en SSO : les déposer, ou cocher « formulaire web »."
            )
            if not runner.dry_run:
                return False
        secret = self.secrets.get("password", "")
        # Comparé, jamais tronqué : le coffre décide de ce qui part.
        # Comparer des LONGUEURS ne divulgue rien, et c'est le seul endroit
        # où le mot de passe déposé et la borne déclarée sont tous deux
        # connus.
        limite = self.password_len
        if limite and secret != PLACEHOLDER and len(secret) > limite:
            runner.warn(
                f"Le mot de passe du coffre fait {len(secret)} caractères"
                f" et ce concentrateur n'en compare que {limite} : n'en"
                f" déposer que {limite}."
            )
        code, _ = runner.cmd(
            f"ouvrir la session {self.profile['oc_protocol']} sur"
            f" {self.profile['server']}",
            self.command(),
            stdin=f"{secret}\n",
            secret_stdin=True,
            check=False,
            timeout=120,
        )
        if code != 0 and not runner.dry_run:
            runner.fail("openconnect a refusé.")
            runner.info(
                "      → Causes usuelles : identifiants, certificat serveur"
                " non épinglé (recopier la ligne « --servercert sha256:… »"
                " ci-dessus dans le champ oc_servercert), groupe"
                " d'authentification absent."
            )
            return False
        return True

    def _settle(self, runner):
        """Ce qui suit un montage réussi, quel que soit le chemin pris.

        On ATTEND l'interface au lieu de la constater. `--background` fait
        sortir openconnect dès que la session est ouverte, et c'est
        `vpnc-script` qui crée l'interface et lui pose son adresse, un
        instant plus tard. Regarder tout de suite déclare absent un tunnel
        qui monte — et accuse `vpnc-script` d'être absent alors qu'il est
        précisément en train de travailler.
        """
        addresses = wait_for_interface_address(self.iface, timeout=25)
        if not addresses and not interface_exists(self.iface):
            runner.fail(
                f"openconnect s'est lancé mais {self.iface} n'existe pas."
                " vpnc-script est-il installé ? (paquet vpnc-scripts)"
            )
            return False
        runner.ok(
            f"interface {self.iface} :"
            f" {', '.join(addresses) or 'sans adresse'}"
        )
        self.write_state(runner, "iface", self.iface)
        # Les routes du serveur sont déjà posées par vpnc-script. Celles du
        # profil s'AJOUTENT : un réseau que le concentrateur ne pousse pas
        # mais qu'on sait joignable.
        self.add_routes(runner, self.iface)
        return True

    def _explain_the_sso_round_trip(self, runner):
        """Dit à l'humain ce qu'il va devoir faire, AVANT de le bloquer.

        openconnect va afficher une URL puis attendre, silencieusement, sur
        son port 29786. Sans cette explication, l'attente ressemble à un
        blocage — et la redirection ne revient jamais si personne n'a monté
        le tunnel ssh."""
        runner.info(
            "      Authentification par formulaire web. openconnect va"
            " afficher une URL, puis attendre la redirection sur son port"
            " local 29786."
        )
        runner.info(
            "      Depuis VOTRE poste, avant d'ouvrir l'URL :"
            " ssh -L 29786:localhost:29786 <cette machine>"
        )
        if self.browser == "echo":
            runner.info(
                "      L'URL s'affichera ici : l'ouvrir dans votre propre"
                " navigateur. Le mot de passe ne quitte pas votre poste."
            )
        else:
            runner.info(f"      Navigateur lancé sur place : {self.browser}")

    def down(self, runner):
        # SIGTERM : openconnect rappelle vpnc-script, qui défait les routes
        # et le DNS qu'il avait posés. Un « kill -9 » les laisserait en
        # place, et la machine resterait à moitié dans le tunnel.
        self.kill_pidfile(runner, "arrêter openconnect (SIGTERM)")
        self.clear_state(runner, "iface", "pid")
        runner.ok(
            "Session fermée. Aucun secret à effacer : il n'a jamais"
            " touché le disque."
        )
        return True

    def check_sso_helper(self):
        """Verdict sur le greffon, quand le profil en a besoin.

        `None` en verdict quand le profil n'est pas en SSO : ce n'est pas
        « bon », ce n'est pas « en défaut », c'est hors sujet — et un ✓ sur
        une ligne hors sujet fait croire qu'elle a été vérifiée.
        """
        if not self.profile.get("oc_sso"):
            return (
                t("SSO helper"),
                None,
                "sans objet : ce profil authentifie par mot de passe",
            )
        helper = self.sso_helper
        if helper:
            return (
                t("SSO helper"),
                True,
                helper,
            )
        declared = self.profile.get("oc_sso_helper") or ""
        return (
            t("SSO helper"),
            False,
            (
                f"déclaré mais inexécutable : {declared}"
                if declared
                else "absent : openconnect-sso introuvable dans le PATH"
            ),
        )

    def status(self, runner):
        return self.standard_status(
            runner,
            extra=[
                self.check_daemon("processus openconnect"),
                self.check_sso_helper(),
            ],
        )

    def log_commands(self):
        return [
            (
                "journal openconnect",
                "journalctl -n 40 --no-pager -t openconnect",
            )
        ]
