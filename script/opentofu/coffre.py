# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Secrets d'un parc, environnement de `tofu` et configuration épinglée.

Les secrets vivent dans `private/opentofu/<parc>/secrets.json` (0600, dossier
0700) : le jeton d'API Proxmox et la phrase qui chiffre l'état et les plans.
`environnement` les passe à `tofu` par variables d'environnement, jamais par
la ligne de commande ni par un fichier de configuration. `masquer` retire ces
valeurs de toute ligne de journal avant affichage. `conf/opentofu.json` épingle
la version de tofu, sa clé de signature et la version du fournisseur.
"""

import json
import os
import secrets
import tempfile
from pathlib import Path

from script.opentofu.spec import RACINE_PARCS, dossier_parc
from script.todo.todo_i18n import t

CONF = Path(__file__).resolve().parent.parent.parent / "conf" / "opentofu.json"
CACHE_PLUGINS = Path.home() / ".cache" / "erplibre" / "opentofu" / "plugins"
_CLES_CONF = (
    "version",
    "required_version",
    "gpg_fingerprint",
    "cle_gpg_url",
    "providers",
)
_PHRASE_MIN = 16
_MASQUE = "***"


def charger_conf(chemin=None):
    """Configuration épinglée ; ValueError nomme la première clé absente."""
    chemin = Path(chemin) if chemin else CONF
    with open(chemin, encoding="utf-8") as f:
        conf = json.load(f)
    for cle in _CLES_CONF:
        if cle not in conf:
            raise ValueError(
                t("Missing key {cle} in {chemin}").format(cle=cle, chemin=chemin)
            )
    return conf


def _fichier(nom, racine):
    return dossier_parc(nom, racine) / "secrets.json"


def lire(nom, racine=RACINE_PARCS):
    """Secrets du parc, ou {} quand le fichier n'existe pas."""
    chemin = _fichier(nom, racine)
    if not chemin.is_file():
        return {}
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def ecrire(nom, donnees, racine=RACINE_PARCS):
    """Remplace tout le fichier de secrets, de façon atomique, en 0600.

    L'appelant lit, modifie, puis écrit : une clé absente de `donnees`
    disparaît du fichier.
    """
    dossier = dossier_parc(nom, racine)
    dossier.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(dossier, 0o700)
    cible = _fichier(nom, racine)
    fd, tmp = tempfile.mkstemp(dir=dossier, prefix=".secrets.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(donnees, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, cible)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def phrase_etat(nom, racine=RACINE_PARCS):
    """Phrase de chiffrement de l'état ; créée au premier appel, puis stable."""
    donnees = lire(nom, racine)
    phrase = donnees.get("phrase_etat")
    if not phrase:
        phrase = secrets.token_urlsafe(32)
        donnees["phrase_etat"] = phrase
        ecrire(nom, donnees, racine)
    return phrase


def _hcl(texte):
    """Texte échappé pour une chaîne HCL entre guillemets."""
    return texte.replace("\\", "\\\\").replace('"', '\\"')


def tf_encryption(phrase):
    """Corps HCL du bloc `encryption` : état et plans chiffrés, imposés.

    `enforced = true` refuse un état ou un plan en clair. La phrase d'au moins
    16 caractères dérive la clé par PBKDF2 ; ValueError si elle est plus
    courte.
    """
    if len(phrase) < _PHRASE_MIN:
        raise ValueError(
            t("State passphrase must have at least {n} characters.").format(
                n=_PHRASE_MIN
            )
        )
    return (
        'key_provider "pbkdf2" "main" {\n'
        f'  passphrase = "{_hcl(phrase)}"\n'
        "}\n"
        'method "aes_gcm" "main" {\n'
        "  keys = key_provider.pbkdf2.main\n"
        "}\n"
        "state {\n"
        "  method = method.aes_gcm.main\n"
        "  enforced = true\n"
        "}\n"
        "plan {\n"
        "  method = method.aes_gcm.main\n"
        "  enforced = true\n"
        "}\n"
    )


def environnement(nom, base=None, racine=RACINE_PARCS):
    """Copie de `base` (os.environ par défaut) prête pour un sous-processus tofu.

    Porte le jeton Proxmox quand il est stocké, le chiffrement de l'état, le
    cache partagé des fournisseurs et les réglages non interactifs. Ni `base`
    ni os.environ ne sont modifiés.
    """
    env = dict(os.environ if base is None else base)
    jeton = lire(nom, racine).get("jeton")
    if jeton:
        env["PROXMOX_VE_API_TOKEN"] = jeton
    env["TF_ENCRYPTION"] = tf_encryption(phrase_etat(nom, racine))
    CACHE_PLUGINS.mkdir(parents=True, exist_ok=True)
    env["TF_PLUGIN_CACHE_DIR"] = str(CACHE_PLUGINS)
    env["TF_IN_AUTOMATION"] = "1"
    env["TF_INPUT"] = "0"
    return env


def masquer(ligne, secrets_parc):
    """Remplace chaque valeur secrète de `secrets_parc` par `***`.

    Pour le jeton, la partie après `=` est masquée seule aussi : un journal
    qui la cite sans l'identifiant ne doit pas la laisser passer. Les valeurs
    les plus longues passent d'abord, pour qu'une valeur contenue dans une
    autre ne laisse pas de reste.
    """
    valeurs = set()
    for cle, valeur in secrets_parc.items():
        if not isinstance(valeur, str) or not valeur:
            continue
        valeurs.add(valeur)
        if cle == "jeton" and "=" in valeur:
            reste = valeur.split("=", 1)[1]
            if reste:
                valeurs.add(reste)
    for valeur in sorted(valeurs, key=len, reverse=True):
        ligne = ligne.replace(valeur, _MASQUE)
    return ligne
