#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Installer Apertus : quelles étapes, dans quel ordre, sur quelle machine.

Le module est PUR. Il ne lit aucun fichier, n'ouvre aucune connexion et
n'exécute rien : il rend des listes d'`Etape` que l'appelant lance, et des
dictionnaires que l'appelant affiche. La persistance vit dans
`apertus_state`, l'exécution dans le mixin du menu. Cette séparation est ce
qui permet de tester l'ordre des étapes et le texte des commandes sans
machine ni réseau.

**L'ordre des étapes porte une garantie.** La version du moteur se vérifie
AVANT que le modèle ne se télécharge. Un moteur trop ancien ne connaît pas
l'activation xIELU d'Apertus : il accepte le fichier, puis produit du
charabia ou refuse de charger. Placer le contrôle après le téléchargement
coûte plusieurs gigaoctets pour apprendre une version.

**Le contexte par défaut est un piège mémoire.** Le cache clé-valeur d'un
Apertus 8B occupe 128 Kio par jeton — deux tenseurs, 32 couches, 8 têtes KV,
128 de dimension, 2 octets. Accepter les 65 536 jetons du modèle réserve donc
8 Gio par-dessus les poids. Les moteurs sont lancés avec un contexte plafonné.

**Aucun GGUF officiel n'existe.** L'éditeur publie ses poids et des
quantifications MLX et vLLM, pas de GGUF. Tout chemin passant par Ollama,
llama.cpp ou LocalAI dépend donc d'un quantificateur tiers, et le catalogue
ci-dessous ne retient que des dépôts qui déclarent leur licence.

**La famille 1.5 n'est pas visée.** Elle porte une autre architecture, exige
un fork épinglé de la bibliothèque de transformeurs et un compte pour être
téléchargée. Aucun des quatre moteurs ne la sert aujourd'hui.
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass

# Le modèle par défaut et le moteur par défaut, quand rien n'a été choisi.
MOTEUR_DEFAUT = "ollama"
MODELE_DEFAUT = "8b-q4"

# Plafond de contexte appliqué au lancement, en jetons. Le cache clé-valeur
# d'un 8B coûte 128 Kio par jeton : 8192 tient dans 1 Gio, 65536 en
# demanderait 8. Un modèle dont le contexte natif est plus court garde le
# sien.
CONTEXTE_PLAFOND = 8192

# Marge disque exigée en plus de la taille du modèle, en octets. Couvre les
# fichiers intermédiaires d'un téléchargement et le fichier de service.
MARGE_DISQUE = 2 * 1024**3


@dataclass(frozen=True)
class Moteur:
    """Un logiciel qui sert le modèle sur une API HTTP.

    `version_min` est la première version qui connaît l'activation xIELU ;
    au-dessous, le modèle se charge mal ou pas du tout. `version_cmd` rend
    cette version sur la sortie standard, et `version_regex` en extrait le
    numéro. `chemin` est la racine de l'API compatible OpenAI, ce que sonde
    déjà le registre des serveurs du CLI.
    """

    cle: str
    nom: str
    licence: str
    port: int
    chemin: str
    version_min: str
    version_cmd: str
    version_regex: str
    binaire: str
    # Les autres noms sous lesquels le MÊME moteur s'installe. llama.cpp a
    # remplacé ses binaires par un exécutable unifié, et les paquets de
    # distribution livrent encore les anciens : chercher un seul nom déclare
    # absent un moteur présent.
    alias: tuple[str, ...] = ()
    # Ce qui doit précéder toute commande du moteur. Un installateur sans
    # privilège écrit sous le compte, et un shell non interactif n'a pas ce
    # répertoire sur son chemin : sans ce préfixe, l'étape suivante ne trouve
    # pas ce que la précédente vient de poser.
    prefixe: str = ""

    @property
    def binaires(self) -> tuple[str, ...]:
        """Tous les noms qui valent « le moteur est là »."""
        return (self.binaire,) + self.alias

    @property
    def presence(self) -> str:
        """La commande qui répond 0 quand le moteur est installé."""
        tests = " || ".join(
            f"command -v {nom} >/dev/null 2>&1" for nom in self.binaires
        )
        return f"sh -c {shlex.quote(self.prefixe + tests)}"

    @property
    def version_test(self) -> str:
        """La commande qui LIT la version, l'affiche, et échoue si elle est
        trop ancienne.

        La comparaison vit dans le shell et non dans le lanceur, de sorte que
        le rendu texte et le rendu plein écran s'arrêtent exactement au même
        endroit sans qu'aucun des deux ne porte de cas particulier. La version
        trouvée est imprimée AVANT le test : c'est elle que le message
        d'erreur cite.
        """
        lecture = "{ " + self.prefixe + self.version_cmd + " ; } 2>&1"
        if self.cle == "llamacpp":
            seuil = self.version_min.lstrip("b")
            garde = f'[ "$v" -ge {seuil} ]'
            extrait = (
                r"grep -oE '(b|build )[0-9]+' | head -1"
                r" | grep -oE '[0-9]+'"
            )
            echo = 'echo "b$v"'
        else:
            garde = (
                "[ \"$(printf '%s\\n%s\\n' "
                f'"{self.version_min}" "$v" | sort -V | head -1)" '
                f'= "{self.version_min}" ]'
            )
            extrait = r'grep -oE "[0-9]+\.[0-9]+\.[0-9]+" | head -1'
            echo = 'echo "$v"'
        return "sh -c " + shlex.quote(
            f'v=$({lecture} | {extrait}); {echo}; test -n "$v" && {garde}'
        )


MOTEURS: dict[str, Moteur] = {
    "ollama": Moteur(
        cle="ollama",
        nom="Ollama",
        licence="MIT",
        port=11434,
        chemin="/v1",
        # xIELU arrive dans les sources embarquées à cette version. Aucune
        # note de version ne le mentionne : seul un diff des sources le dit.
        version_min="0.12.6",
        version_cmd="ollama --version",
        version_regex=r"(\d+\.\d+\.\d+)",
        binaire="ollama",
    ),
    "llamacpp": Moteur(
        cle="llamacpp",
        nom="llama.cpp",
        licence="MIT",
        port=8080,
        chemin="/v1",
        # Numéro de construction, pas un numéro sémantique : la comparaison
        # se fait sur l'entier qui suit le « b ».
        version_min="b6671",
        version_cmd="llama --version 2>&1 || llama-server --version 2>&1",
        # Deux formes pour le même numéro : l'installateur annonce « b10909 »
        # et le binaire « build 10909 ». N'en reconnaître qu'une rend une
        # version vide, donc un moteur déclaré trop ancien alors qu'il convient.
        version_regex=r"(?:b|build )(\d+)",
        binaire="llama",
        alias=("llama-server",),
        prefixe='PATH="$HOME/.local/bin:$PATH"; ',
    ),
    "localai": Moteur(
        cle="localai",
        nom="LocalAI",
        licence="MIT",
        port=8080,
        chemin="/v1",
        # Hérite du support par son moteur llama.cpp embarqué.
        version_min="4.0.0",
        version_cmd="local-ai --version",
        version_regex=r"(\d+\.\d+\.\d+)",
        binaire="local-ai",
    ),
    "vllm": Moteur(
        cle="vllm",
        nom="vLLM",
        licence="Apache-2.0",
        port=8000,
        chemin="/v1",
        # Apertus y est entré avant la sortie publique du modèle.
        version_min="0.10.2",
        version_cmd="python3 -c 'import vllm; print(vllm.__version__)'",
        version_regex=r"(\d+\.\d+\.\d+)",
        binaire="vllm",
    ),
}


@dataclass(frozen=True)
class Modele:
    """Un jeu de poids, et la façon de le nommer selon le moteur.

    `reference` associe une clé de moteur à la chaîne que ce moteur attend :
    les quatre veulent quatre formes incompatibles pour les mêmes poids.
    `taille` sert à la vérification de place AVANT téléchargement ; elle est
    approchée pour les variantes dont la taille de fichier n'est pas publiée,
    et la marge disque couvre l'écart.
    """

    cle: str
    nom: str
    depot: str
    contexte: int
    taille: int
    distille: bool
    reference: dict[str, str]


_GGUF_8B = "unsloth/Apertus-8B-Instruct-2509-GGUF"
_GGUF_MINI_15 = "mradermacher/Apertus-v1.1-1.5B-Instruct-GGUF"
_GGUF_MINI_05 = "mradermacher/Apertus-v1.1-0.5B-Instruct-GGUF"

MODELES: dict[str, Modele] = {
    "8b-q4": Modele(
        cle="8b-q4",
        nom="Apertus 8B Instruct (Q4_K_M)",
        depot="swiss-ai/Apertus-8B-Instruct-2509",
        contexte=65536,
        taille=5_060_000_000,
        distille=False,
        reference={
            "ollama": f"hf.co/{_GGUF_8B}:Q4_K_M",
            "llamacpp": f"{_GGUF_8B}:Q4_K_M",
            "localai": (
                f"huggingface://{_GGUF_8B}/Apertus-8B-Instruct-2509-Q4_K_M.gguf"
            ),
            "vllm": "swiss-ai/Apertus-8B-Instruct-2509",
        },
    ),
    "8b-q8": Modele(
        cle="8b-q8",
        nom="Apertus 8B Instruct (Q8_0)",
        depot="swiss-ai/Apertus-8B-Instruct-2509",
        contexte=65536,
        taille=8_570_000_000,
        distille=False,
        reference={
            "ollama": f"hf.co/{_GGUF_8B}:Q8_0",
            "llamacpp": f"{_GGUF_8B}:Q8_0",
            "localai": (
                f"huggingface://{_GGUF_8B}/Apertus-8B-Instruct-2509-Q8_0.gguf"
            ),
            "vllm": "swiss-ai/Apertus-8B-Instruct-2509",
        },
    ),
    "mini-1.5b": Modele(
        cle="mini-1.5b",
        nom="Apertus Mini 1.5B Instruct (distillé)",
        depot="swiss-ai/Apertus-v1.1-1.5B-Instruct",
        # La distillation coûte le contexte : 4096 jetons au lieu de 65536.
        contexte=4096,
        taille=1_200_000_000,
        distille=True,
        reference={
            "ollama": f"hf.co/{_GGUF_MINI_15}:Q4_K_M",
            "llamacpp": f"{_GGUF_MINI_15}:Q4_K_M",
            "localai": (
                f"huggingface://{_GGUF_MINI_15}/"
                "Apertus-v1.1-1.5B-Instruct.Q4_K_M.gguf"
            ),
            "vllm": "swiss-ai/Apertus-v1.1-1.5B-Instruct",
        },
    ),
    "mini-0.5b": Modele(
        cle="mini-0.5b",
        nom="Apertus Mini 0.5B Instruct (distillé)",
        depot="swiss-ai/Apertus-v1.1-0.5B-Instruct",
        contexte=4096,
        taille=500_000_000,
        distille=True,
        reference={
            "ollama": f"hf.co/{_GGUF_MINI_05}:Q4_K_M",
            "llamacpp": f"{_GGUF_MINI_05}:Q4_K_M",
            "localai": (
                f"huggingface://{_GGUF_MINI_05}/"
                "Apertus-v1.1-0.5B-Instruct.Q4_K_M.gguf"
            ),
            "vllm": "swiss-ai/Apertus-v1.1-0.5B-Instruct",
        },
    ),
}


@dataclass(frozen=True)
class Etape:
    """Une étape d'installation, sa commande et son test de complétion.

    `cle` est stable et jamais traduite : elle sert de clé de reprise, donc
    la renommer invalide les progressions enregistrées. `label` est une clé
    de traduction. `deja_fait` est une commande dont le code de retour 0
    signifie « rien à faire ici », ce qui rend l'installation rejouable sans
    tout refaire. Une étape non `critique` qui échoue laisse la suite courir.
    """

    cle: str
    label: str
    commande: str
    deja_fait: str = ""
    critique: bool = True


def contexte_utile(modele: Modele) -> int:
    """Le contexte demandé au moteur : celui du modèle, plafonné."""
    return min(modele.contexte, CONTEXTE_PLAFOND)


def place_requise(modele: Modele) -> int:
    """Octets à avoir libres avant de lancer : le modèle, plus la marge."""
    return modele.taille + MARGE_DISQUE


def enrobe(cible: dict, commande: str) -> str:
    """La commande telle qu'elle se lance depuis ici, locale ou distante.

    Une cible distante reçoit `BatchMode=yes` : une invite de mot de passe
    sous un `ssh` non interactif attend sans rien afficher, et le menu paraît
    figé. Les options de confiance d'hôte ne sont jamais forcées — un hôte
    déclaré dans la configuration ssh de l'utilisateur garde la sienne.
    """
    if cible.get("kind") == "local":
        return commande
    destination = cible.get("destination", "")
    return (
        "ssh -o BatchMode=yes -o ConnectTimeout=10 "
        f"{shlex.quote(destination)} {shlex.quote(commande)}"
    )


# Détecte le gestionnaire de paquets plutôt que la distribution : c'est lui
# qui décide de la commande, et deux distributions parentes le partagent.
_GESTIONNAIRE = (
    "if command -v pacman >/dev/null 2>&1; then echo pacman; "
    "elif command -v apt-get >/dev/null 2>&1; then echo apt; "
    "elif command -v dnf >/dev/null 2>&1; then echo dnf; "
    "else echo none; fi"
)


def _installe_ollama() -> str:
    """Installe Ollama par le paquet de la distribution, et se rabat sur
    l'installateur amont dès que le paquet ne s'installe pas.

    Le repli n'est pas une précaution de style. Une base de paquets locale
    plus ancienne que la rotation des miroirs réclame une version qu'aucun
    miroir ne porte plus, et l'installation échoue avec un 404 sur CHAQUE
    miroir — un état que rien dans la commande ne laisse prévoir.

    Rafraîchir la base sans mettre le système à jour fabriquerait une mise à
    jour partielle, et mettre le système à jour est une décision qui
    appartient à l'utilisateur, pas à un installateur de modèle. L'amont pose
    un binaire autonome sous /usr/local et ne touche à aucune bibliothèque du
    système : c'est la sortie qui ne coûte rien à personne.
    """
    amont = "curl -fsSL https://ollama.com/install.sh | sh"
    return "sh -c " + shlex.quote(
        "if command -v pacman >/dev/null 2>&1; then "
        f"sudo pacman -S --needed --noconfirm ollama || {{ {amont} ; }}; "
        "elif command -v apt-get >/dev/null 2>&1; then "
        f"sudo apt-get install -y ollama 2>/dev/null || {{ {amont} ; }}; "
        f"else {amont}; fi"
    )


def _installe_llamacpp() -> str:
    """Installe llama.cpp par l'installateur amont, sans privilège.

    Les paquets de distribution sont fréquemment antérieurs à la
    construction qui connaît xIELU, et l'utilisateur ne l'apprendrait qu'au
    chargement du modèle. L'installateur amont pose un binaire récent sous
    le compte courant.
    """
    return "sh -c " + shlex.quote(
        "curl -fsSL https://llama.app/install.sh | sh"
    )


def _installe_localai() -> str:
    """Installe LocalAI par son script amont.

    Le script pose le binaire et rien d'autre : le service est écrit à
    l'étape suivante, et le premier appel télécharge encore l'image du
    moteur d'inférence, qui a sa propre étape.
    """
    return "sh -c 'curl -fsSL https://localai.io/install.sh | sh'"


def _installe_vllm() -> str:
    """Installe vLLM dans un environnement virtuel dédié.

    L'installation tire une pile d'apprentissage profond de plusieurs
    gigaoctets ; la confiner évite qu'elle ne déplace les dépendances du
    système. Le noyau CUDA fusionné pour xIELU n'est PAS installé : son
    dépôt ne porte aucune licence, ce qu'un projet sous licence libre ne
    peut pas embarquer. Le repli en Python pur est automatique et correct,
    et ne coûte que de la vitesse.
    """
    return (
        'sh -c \'python3 -m venv "$HOME/.venv.vllm" && '
        '"$HOME/.venv.vllm/bin/pip" install --upgrade pip && '
        '"$HOME/.venv.vllm/bin/pip" install vllm\''
    )


_INSTALLE = {
    "ollama": _installe_ollama,
    "llamacpp": _installe_llamacpp,
    "localai": _installe_localai,
    "vllm": _installe_vllm,
}


def _service(moteur: Moteur, modele: Modele) -> tuple[str, str]:
    """La commande qui met le moteur à écouter, et son test de complétion.

    Ollama pose son propre service ; les trois autres se lancent détachés,
    parce qu'aucun ne livre d'unité systemd prête à l'emploi.
    """
    contexte = contexte_utile(modele)
    reference = modele.reference[moteur.cle]
    if moteur.cle == "ollama":
        return (
            "sh -c 'sudo systemctl enable --now ollama 2>/dev/null "
            "|| (nohup ollama serve >/dev/null 2>&1 & sleep 2)'",
            "pgrep -x ollama >/dev/null",
        )
    if moteur.cle == "llamacpp":
        # « llama serve » est la forme actuelle ; les paquets de distribution
        # livrent encore « llama-server », d'où le repli. Le dépôt et la
        # quantification tiennent en UNE référence : « -hf » attend
        # « <compte>/<dépôt>[:quant] » et refuse un nom de fichier accolé.
        lance = (
            f"llama serve -hf {shlex.quote(reference)}"
            f" --port {moteur.port} --ctx-size {contexte} --jinja"
        )
        repli = lance.replace("llama serve", "llama-server", 1)
        interne = shlex.quote(f"{lance} || {repli}")
        return (
            "sh -c "
            + shlex.quote(
                moteur.prefixe
                + f"nohup sh -c {interne}"
                + ' >"$HOME/.apertus-llamacpp.log" 2>&1 & sleep 3'
            ),
            f"curl -fsS http://127.0.0.1:{moteur.port}/health >/dev/null",
        )
    if moteur.cle == "localai":
        return (
            "sh -c 'nohup local-ai run "
            f"{shlex.quote(reference)} "
            '>"$HOME/.apertus-localai.log" 2>&1 & sleep 3\'',
            f"curl -fsS http://127.0.0.1:{moteur.port}/readyz >/dev/null",
        )
    return (
        'sh -c \'nohup "$HOME/.venv.vllm/bin/vllm" serve '
        f"{shlex.quote(reference)} --port {moteur.port} "
        f"--max-model-len {contexte} "
        '>"$HOME/.apertus-vllm.log" 2>&1 & sleep 5\'',
        f"curl -fsS http://127.0.0.1:{moteur.port}/health >/dev/null",
    )


# Nombre de sondes d'attente et délai entre deux, pour un moteur qui tire le
# modèle à son premier lancement. Le produit borne l'attente à dix minutes.
#
# Une attente FIXE ne peut pas marcher ici : un modèle déjà en cache se charge
# en quelques secondes, un premier téléchargement de plusieurs gigaoctets prend
# des minutes, et le moteur répond 503 tant qu'il n'a pas fini. Un modèle d'un
# demi-milliard de paramètres DÉJÀ téléchargé met une huitaine de secondes à
# charger : c'est déjà plus qu'une attente de cinq secondes, et le plus petit
# cas possible.
ATTENTE_SONDES = 120
ATTENTE_DELAI = 5


def _tirer(moteur: Moteur, modele: Modele) -> tuple[str, str]:
    """La commande qui rapatrie les poids, et son test de complétion.

    Seul Ollama sépare le téléchargement du service. Les trois autres tirent
    le modèle à leur premier lancement, et l'étape devient une ATTENTE : on
    sonde jusqu'à ce que le moteur annonce le modèle, parce qu'il répond 503
    pendant tout le chargement et qu'aucune durée fixe ne couvre à la fois un
    cache chaud et un téléchargement neuf.
    """
    reference = modele.reference[moteur.cle]
    if moteur.cle == "ollama":
        return (
            f"ollama pull {shlex.quote(reference)}",
            f"ollama list | grep -qF {shlex.quote(reference)}",
        )
    atteste = (
        f"curl -fsS http://127.0.0.1:{moteur.port}{moteur.chemin}/models"
        " 2>/dev/null | grep -qi apertus"
    )
    attente = (
        f"for _ in $(seq 1 {ATTENTE_SONDES}); do "
        f"{atteste} && exit 0; sleep {ATTENTE_DELAI}; done; exit 1"
    )
    return ("sh -c " + shlex.quote(attente), "sh -c " + shlex.quote(atteste))


def etapes(moteur_cle: str, modele_cle: str, cible: dict) -> list[Etape]:
    """Les étapes ordonnées d'une installation, prêtes à lancer.

    La vérification de version précède le téléchargement : c'est la seule
    contrainte d'ordre que le reste du code doit préserver.
    """
    moteur = MOTEURS[moteur_cle]
    modele = MODELES[modele_cle]
    reference = modele.reference[moteur.cle]
    requis = place_requise(modele)
    service_cmd, service_fait = _service(moteur, modele)
    tirer_cmd, tirer_fait = _tirer(moteur, modele)
    racine = f"http://127.0.0.1:{moteur.port}{moteur.chemin}"

    brutes = [
        Etape(
            cle="atteindre",
            label="Reach the target",
            commande="true",
        ),
        Etape(
            cle="sudo",
            label="Check sudo",
            # Un hôte qui réclame un mot de passe se signale ici plutôt que
            # de bloquer sans rien afficher au milieu d'une installation.
            commande="sudo -n true 2>/dev/null || test ! -x /usr/bin/sudo",
        ),
        Etape(
            cle="place",
            label="Check free space",
            commande=(
                'sh -c \'libre=$(df -B1 --output=avail "$HOME" | tail -1); '
                f'test "$libre" -ge {requis}\''
            ),
        ),
        Etape(
            cle="paquet",
            label="Install the engine",
            commande=_INSTALLE[moteur.cle](),
            deja_fait=moteur.presence,
        ),
        Etape(
            cle="version",
            label="Check the engine version",
            # Placée AVANT le téléchargement : un moteur trop ancien se
            # découvre pour quelques octets plutôt que pour plusieurs Go.
            commande=moteur.version_test,
        ),
        Etape(
            cle="service",
            label="Start the service",
            commande=service_cmd,
            deja_fait=service_fait,
            # Un hôte sans systemd sert quand même le modèle : c'est
            # l'étape d'écoute qui tranche, pas celle-ci.
            critique=False,
        ),
        Etape(
            cle="tirer",
            label="Pull the model",
            commande=tirer_cmd,
            deja_fait=tirer_fait,
        ),
        Etape(
            cle="ecouter",
            label="Check it listens",
            commande=f"curl -fsS {racine}/models >/dev/null",
        ),
        Etape(
            cle="repondre",
            label="Check it answers",
            commande=(
                f"curl -fsS {racine}/chat/completions "
                "-H 'Content-Type: application/json' -d "
                + shlex.quote(
                    '{"model": "%s", "max_tokens": 8, "messages": '
                    '[{"role": "user", "content": "ping"}]}' % reference
                )
                + " | grep -q content"
            ),
        ),
    ]
    return [
        Etape(
            cle=e.cle,
            label=e.label,
            commande=enrobe(cible, e.commande),
            deja_fait=enrobe(cible, e.deja_fait) if e.deja_fait else "",
            critique=e.critique,
        )
        for e in brutes
    ]


def desinstaller(moteur_cle: str, modele_cle: str, cible: dict) -> list[Etape]:
    """Les étapes qui défont l'installation : le modèle, puis le service.

    Le moteur lui-même n'est pas retiré. Il sert peut-être d'autres modèles,
    et un menu qui désinstalle plus que ce qu'il a posé surprend.
    """
    moteur = MOTEURS[moteur_cle]
    modele = MODELES[modele_cle]
    reference = modele.reference[moteur.cle]
    if moteur.cle == "ollama":
        retrait = f"ollama rm {shlex.quote(reference)}"
        arret = "sudo systemctl stop ollama 2>/dev/null || pkill -x ollama"
    else:
        retrait = "true"
        arret = f"pkill -f {shlex.quote(moteur.binaire)} || true"
    return [
        Etape(
            cle="arret",
            label="Start the service",
            commande=enrobe(cible, arret),
            critique=False,
        ),
        Etape(
            cle="retrait",
            label="Pull the model",
            commande=enrobe(cible, retrait),
            critique=False,
        ),
    ]


def plan_lisible(liste: list[Etape]) -> str:
    """Le plan tel qu'il s'affiche avant la confirmation, une ligne par étape."""
    largeur = max((len(e.cle) for e in liste), default=0)
    return "\n".join(
        f"  {rang}. {e.cle.ljust(largeur)}  {e.commande}"
        for rang, e in enumerate(liste, 1)
    )


def contexte_reprise(etat: dict, liste: list[Etape]) -> dict:
    """L'état d'une installation interrompue, en données pures.

    Aucune entrée-sortie ici, volontairement : l'écran texte et l'écran
    plein rendent TOUS DEUX ce dictionnaire, et c'est la seule façon de
    garantir qu'ils ne décrivent jamais deux états différents.

    `etapes` porte une icône par étape — faite, échouée, pas encore
    atteinte — et `reprise_a` est le rang, à partir de 1, de la première
    étape qui reste à jouer.
    """
    faites = int(etat.get("etape_faite") or 0)
    echouee = etat.get("etape_echouee") or ""
    detail = []
    for rang, e in enumerate(liste, 1):
        if e.cle == echouee:
            icone = "⛔"
        elif rang <= faites:
            icone = "✅"
        else:
            icone = "⬜"
        detail.append(
            {"rang": rang, "cle": e.cle, "label": e.label, "icone": icone}
        )
    return {
        "cible": etat.get("cible", ""),
        "moteur": etat.get("moteur", ""),
        "modele": etat.get("modele", ""),
        "debut": etat.get("debut", ""),
        "etapes": detail,
        "faites": faites,
        "total": len(liste),
        "reprise_a": min(faites + 1, len(liste)) if liste else 1,
        "tentatives": int(etat.get("tentatives") or 0),
        "secondes": int(etat.get("secondes") or 0),
        "erreur": etat.get("erreur") or "",
        "code": etat.get("code"),
    }


def version_suffisante(moteur_cle: str, brut: str) -> bool:
    """Vrai si la version lue atteint celle qu'Apertus exige.

    llama.cpp se numérote par construction — « b6671 » — et les trois autres
    par composants. Les deux se comparent en listes d'entiers, ce qui suffit
    ici parce qu'aucun des minimums ne porte de suffixe de pré-version.
    """
    import re

    moteur = MOTEURS[moteur_cle]
    trouve = re.search(moteur.version_regex, brut or "")
    if not trouve:
        return False
    attendu = re.search(moteur.version_regex, moteur.version_min)
    if not attendu:
        return False

    def pieces(texte):
        return [int(x) for x in texte.split(".") if x.isdigit()]

    return pieces(trouve.group(1)) >= pieces(attendu.group(1))
