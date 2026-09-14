#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Panorama des modèles ouverts et des moteurs qui les servent.

CE FICHIER PÉRIME. C'est sa propriété la plus importante, et la seule que le
code doit traiter comme un fait plutôt que comme un défaut. Le paysage des
modèles ouverts bouge en semaines : un relevé de trois mois annonce des
modèles remplacés, des tailles fausses et des bancs d'essai qui ne servent
plus à comparer. `DATE_RELEVE` porte donc la date du relevé, et
`fraicheur()` la traduit en un verdict que le menu AFFICHE au lieu de le
taire. Un panorama qui ne dit pas son âge se fait croire.

Le module est PUR : aucune lecture de fichier, aucun réseau, aucune horloge.
`age_jours` reçoit le jour courant au lieu de l'appeler — sans quoi aucun test
ne pourrait vérifier ses seuils, et le comportement du menu dépendrait du
calendrier de qui le lance.

Les champs de PROSE — une force, une faiblesse — portent les deux langues et
tiennent en une phrase. Les champs de CHIFFRES n'en portent aucune : une taille
en gigaoctets et un nombre de couches se lisent pareil dans les deux, et les
dupliquer inviterait une moitié à dériver de l'autre. Le long format vit dans
la documentation, qui est déjà outillée pour le bilinguisme.

Ce que ce panorama n'est pas : un classement. Deux modèles à trois points
d'écart sur un banc d'essai sont à égalité, l'échafaudage qui les appelle
pesant autant que ce qui les sépare. Les colonnes servent à ÉCARTER ce qui ne
tient pas sur une machine, pas à couronner un gagnant.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# Le jour du relevé. Toute modification des tables ci-dessous doit l'avancer :
# c'est ce que le lecteur regarde pour décider s'il fait confiance au reste.
DATE_RELEVE = date(2026, 9, 13)

# Les deux seuils, en jours. Le premier marque un relevé encore utilisable, le
# second un relevé à ne plus croire sans vérifier. Ils sont courts exprès —
# entre ces deux versions d'un même modèle il se passe parfois six semaines.
AGE_TIEDE = 45
AGE_FROID = 120

# Les trois états, du plus sûr au moins sûr. Les valeurs sont des clés de
# traduction : le module ne traduit pas, il désigne.
FRAIS = "survey is fresh"
TIEDE = "survey should be re-read"
FROID = "survey is stale — check before trusting it"


def age_jours(aujourdhui: date | None = None) -> int:
    """L'âge du relevé en jours.

    Le jour courant est un ARGUMENT. Appeler l'horloge ici rendrait les seuils
    intestables et le menu dépendant de la date de qui le lance.
    """
    return ((aujourdhui or date.today()) - DATE_RELEVE).days


def fraicheur(aujourdhui: date | None = None) -> str:
    """La clé de traduction qui dit s'il faut encore croire ce panorama."""
    jours = age_jours(aujourdhui)
    if jours <= AGE_TIEDE:
        return FRAIS
    if jours <= AGE_FROID:
        return TIEDE
    return FROID


@dataclass(frozen=True)
class Moteur:
    """Un logiciel qui sert un modèle sur une API HTTP.

    `formats` est le champ décisif à la lecture : il dit quels dépôts de poids
    sont utilisables, et c'est lui qui écarte un modèle bien plus souvent que
    la mémoire disponible.

    `force` et `faiblesse` tiennent en UNE phrase chacune, dans les deux
    langues. Le long format — pourquoi une version minimale existe, quel piège
    guette, ce qu'une mesure a montré — vit dans la documentation, où il se lit
    sans lancer le CLI et où le bilinguisme est déjà outillé.
    """

    cle: str
    nom: str
    licence: str
    port: int
    api: str
    formats: str
    plateformes: str
    version_min: str
    force: dict[str, str]
    faiblesse: dict[str, str]


# Les moteurs que le relevé n'a pas su décrire. Ils sont NOMMÉS plutôt que
# rangés dans la table avec des cases vides : une ligne dont quatre colonnes
# sur onze disent « non relevé » encombre sans renseigner, et un menu qui
# propose un moteur qu'il ne sait pas décrire promet plus qu'il ne tient.
NON_RELEVES = ("llamafile", "SGLang")


@dataclass(frozen=True)
class Modele:
    """Un modèle à poids ouverts.

    `kv_par_jeton` est la colonne la plus utile du tableau, et la moins
    connue. Le coût d'un contexte croît avec elle, pas avec le nombre de
    paramètres : un modèle de quatre milliards atteint le million de jetons
    quand un modèle dense de soixante-dix n'atteint pas le dixième, parce que
    le premier ne paie que huit couches d'attention sur trente-deux.

    `contexte` distingue le NATIF de l'annoncé, par une convention SANS LANGUE
    plutôt que par des mots — « natifs », « sans YaRN » ou « conseillés »
    s'afficheraient en français au lecteur anglophone, et un test le refuse :

        65 536                 le natif, nu
        262 144 → 1,01 M YaRN  natif, puis ce qu'une extrapolation atteint
        1 048 576 ⚑ 300 K      ce que l'éditeur conseille vraiment
        262 144 (config)       seule la configuration l'affirme

    La distinction n'est pas cosmétique. Un contexte extrapolé se dégrade bien
    avant sa limite — un banc d'essai mesure près d'un quart de qualité perdue
    entre la tranche des 128 k et celle du million — et un éditeur a déjà
    retiré par écrit une annonce d'un million que sa propre configuration
    contredisait.
    """

    cle: str
    nom: str
    editeur: str
    parametres: str
    architecture: str
    contexte: str
    licence: str
    poids: str
    kv_par_jeton: str
    moteurs: str
    codage: str
    forces: dict[str, str]
    faiblesses: dict[str, str]
    note: dict[str, str]


# Les colonnes que la documentation reprend telles quelles, dans cet ordre.
# Elles n'ont pas de langue : un nombre de gigaoctets se lit pareil partout,
# et le dupliquer par langue inviterait une moitié à dériver de l'autre.
COLONNES_MOTEUR = (
    "nom",
    "licence",
    "port",
    "api",
    "formats",
    "plateformes",
    "version_min",
)
COLONNES_MODELE = (
    "nom",
    "editeur",
    "parametres",
    "contexte",
    "licence",
    "poids",
    "kv_par_jeton",
)


def _m(
    cle,
    nom,
    licence,
    port,
    api,
    formats,
    plateformes,
    vmin,
    ffr,
    fen,
    wfr,
    wen,
) -> Moteur:
    """Un moteur, écrit court. Les deux dernières paires sont force puis
    faiblesse, français d'abord."""
    return Moteur(
        cle=cle,
        nom=nom,
        licence=licence,
        port=port,
        api=api,
        formats=formats,
        plateformes=plateformes,
        version_min=vmin,
        force={"fr": ffr, "en": fen},
        faiblesse={"fr": wfr, "en": wen},
    )


# L'ordre va du plus abordable au plus spécialisé : c'est celui dans lequel on
# les essaie, et non celui de leurs performances.
MOTEURS: dict[str, Moteur] = {
    m.cle: m
    for m in (
        _m(
            "ollama",
            "Ollama",
            "MIT",
            11434,
            "/v1 + /api",
            "GGUF",
            "Linux, macOS, Windows",
            "0.12.6",
            "Une commande pour installer, et le pont hf.co ouvre tous les"
            " GGUF communautaires sans catalogue à tenir.",
            "One command to install, and the hf.co bridge opens every"
            " community GGUF with no catalogue to maintain.",
            "Apertus n'est pas dans sa bibliothèque officielle : la référence"
            " nue échoue, il faut passer par un dépôt tiers.",
            "Apertus is not in its official library: the bare reference"
            " fails, a third-party repository is required.",
        ),
        _m(
            "llamacpp",
            "llama.cpp",
            "MIT",
            8080,
            "/v1 + /health",
            "GGUF, NVFP4, MXFP4",
            "CPU, CUDA, Vulkan, Metal, SYCL, ROCm",
            "b6671",
            "Le seul qui s'installe sans droits d'administration, et son"
            " gabarit de discussion s'applique tout seul.",
            "The only one that installs without root, and its chat template"
            " applies by itself.",
            "Aucun binaire préconstruit pour ARM avec CUDA : sur cette"
            " machine-là, il faut le compiler.",
            "No prebuilt binary for ARM with CUDA: on such a machine it must"
            " be compiled.",
        ),
        _m(
            "mlx",
            "mlx-lm (MLX)",
            "MIT",
            8080,
            "/v1 + /health",
            "safetensors MLX INT2-INT6",
            "Apple Silicon",
            "0.27.1",
            "Le cadre d'Apple : le seul qui atteigne vraiment son GPU, et il"
            " sert les quantifications officielles de la famille Mini.",
            "Apple's own framework: the only one that truly reaches its GPU,"
            " and it serves the Mini family's official quantizations.",
            "Son serveur n'implémente que des contrôles de sécurité"
            " élémentaires, de son propre aveu : jamais exposé sans"
            " mandataire devant.",
            "Its server implements only basic security checks, by its own"
            " admission: never exposed without a proxy in front.",
        ),
        _m(
            "localai",
            "LocalAI",
            "MIT",
            8080,
            "/v1 + /api + /readyz",
            "GGUF + safetensors (via backends)",
            "Linux x86_64, ARM64",
            "—",
            "Un seul cœur devant plusieurs moteurs, et il distingue"
            " « démarré » de « prêt », ce qu'aucun autre ne fait.",
            "One core in front of several engines, and it separates"
            ' "started" from "ready", which no other does.',
            "Sa galerie ne contient aucune entrée Apertus, et ses moteurs se"
            " téléchargent à la première inférence, pas à l'installation.",
            "Its gallery holds no Apertus entry, and its backends download"
            " themselves on first inference, not at install time.",
        ),
        _m(
            "vllm",
            "vLLM",
            "Apache-2.0",
            8000,
            "/v1 + /health + /version",
            "safetensors bf16, FP8, NVFP4, int4",
            "Linux + CUDA, CPU avx512",
            "0.10.2",
            "Le seul qui consomme les poids officiels de l'éditeur, et le lot"
            " récupère tout : un flux contre trente-deux change l'échelle.",
            "The only one that consumes the publisher's official weights, and"
            " batching recovers everything: one stream against thirty-two"
            " changes the scale.",
            "Il n'annonce aucune de ses capacités, et sa voie processeur exige"
            " avx512, souvent absent d'une machine virtuelle.",
            "It announces none of its capabilities, and its CPU path needs"
            " avx512, often absent from a virtual machine.",
        ),
    )
}


def _mod(
    cle,
    nom,
    editeur,
    parametres,
    architecture,
    contexte,
    licence,
    poids,
    kv,
    moteurs,
    codage,
    ffr,
    fen,
    wfr,
    wen,
    nfr,
    nen,
) -> Modele:
    """Un modèle, écrit court. Les trois dernières paires sont forces,
    faiblesses puis note, français d'abord."""
    return Modele(
        cle=cle,
        nom=nom,
        editeur=editeur,
        parametres=parametres,
        architecture=architecture,
        contexte=contexte,
        licence=licence,
        poids=poids,
        kv_par_jeton=kv,
        moteurs=moteurs,
        codage=codage,
        forces={"fr": ffr, "en": fen},
        faiblesses={"fr": wfr, "en": wen},
        note={"fr": nfr, "en": nen},
    )


# L'ordre répond à la question que le lecteur pose, pas à un classement.
# Apertus d'abord, parce que c'est le sujet de ce dépôt. Puis ce qui TOURNE
# sur une machine modeste, du plus petit au plus lourd : c'est la liste dans
# laquelle on choisit. Les modèles qui NE TIENNENT PAS ferment la marche, du
# moins gros au plus gros, pour que le mur se voie au lieu de se deviner.
MODELES: dict[str, Modele] = {
    m.cle: m
    for m in (
        _mod(
            "apertus-8b-instruct-2509",
            "Apertus-8B-Instruct-2509",
            "Swiss AI Initiative (EPFL / ETH / CSCS)",
            "8,05 G dense",
            "dense, GQA, 32 couches, xIELU",
            "65 536",
            "Apache-2.0 + USAGE_POLICY",
            "bf16 16,1 Go · FP8 9,1 Go · NVFP4 6,1 Go",
            "128,0 Kio (2·32·8·128·2)",
            "vLLM, llama.cpp, Ollama, LocalAI",
            "HumanEval@10 67,0 · MBPP 36,2 (auto-déclaré)",
            "Le seul Apertus confortable : 15,0 Gio en bf16, sa fenêtre de"
            " 65 K entière sur une machine, et les quatre moteurs le servent"
            " sans correctif.",
            "The only comfortable Apertus: 15.0 GiB in bf16, its full 65 K"
            " window on one machine, and all four engines serve it"
            " unpatched.",
            "Gabarit de discussion non standard dont les jetons spéciaux"
            " fuient s'il est mal appliqué, et 67,0 en HumanEval contre 97,0"
            " pour Qwen3-32B.",
            "A non-standard chat template whose special tokens leak when it"
            " is misapplied, and 67.0 on HumanEval against 97.0 for"
            " Qwen3-32B.",
            "Le modèle à épingler pour ce dépôt, pas v1.5. Le noyau CUDA"
            " xIELU fusionné n'a aucune licence : pour un projet AGPL, s'en"
            " tenir au repli PyTorch.",
            "The model to pin for this repository, not v1.5. The fused xIELU"
            " CUDA kernel carries no licence: on an AGPL project, stay on the"
            " PyTorch fallback.",
        ),
        _mod(
            "apertus-70b-instruct-2509",
            "Apertus-70B-Instruct-2509",
            "Swiss AI Initiative (EPFL / ETH / CSCS)",
            "70,6 G dense",
            "dense, GQA, 80 couches, xIELU",
            "65 536",
            "Apache-2.0 + USAGE_POLICY",
            "4 bits 39,9 Go · FP8 72,8 Go · bf16 141,2 Go",
            "320,0 Kio (2·80·8·128·2)",
            "vLLM, llama.cpp, Ollama, LocalAI",
            "HumanEval@10 73,0 · MBPP 47,0 (auto-déclaré)",
            "Ouvert par ses données autant que par ses poids, 1811 langues,"
            " et une quantification 4 bits tient largement sur une machine à"
            " 39,9 Go.",
            "Open by its data as much as by its weights, 1811 languages, and"
            " a 4-bit quantization fits one machine with room to spare at"
            " 39.9 GB.",
            "Dense : les 40 Go de poids 4 bits sont relus à chaque jeton,"
            " 6,8 jet/s de plafond et 4 à 5 en pratique ; en bf16 il ne tient"
            " nulle part.",
            "Dense: its 40 GB of 4-bit weights are reread for every token, a"
            " 6.8 tok/s ceiling and 4 to 5 in practice; in bf16 it fits"
            " nowhere.",
            "Aucune quantification n'est officielle, et unsloth-bnb-4bit pèse"
            " 114,4 Go et non 40 : sa quantification « dynamique » laisse"
            " 52,5 G en bf16.",
            "No quantization is official, and unsloth-bnb-4bit weighs"
            " 114.4 GB rather than 40: its dynamic quantization leaves"
            " 52.5 G in bf16.",
        ),
        _mod(
            "apertus-v1.1-mini",
            "Apertus v1.1 Mini (0.5B, 1.5B, 4B)",
            "Swiss AI Initiative (EPFL / ETH / CSCS)",
            "0,5 / 1,5 / 4 G dense",
            "dense, GQA, 20 / 16 / 24 couches",
            "4 096 (x3)",
            "Apache-2.0 + USAGE_POLICY",
            "4B 7,7 Go · 1.5B 3,0 Go · 0.5B 1,1 Go",
            "96,0 / 32,0 / 20,0 Kio (4B / 1,5B / 0,5B)",
            "vLLM, llama.cpp (officielles en MLX)",
            "aucun publié",
            "Les six dépôts tiennent ensemble en 21,8 Gio, et le 1.5B"
            " plafonne à 90 jet/s : de quoi tout garder résident sur une"
            " petite machine.",
            "All six repositories fit together in 21.8 GiB, and the 1.5B tops"
            " out at 90 tok/s: enough to keep the whole family resident on a"
            " small machine.",
            "4 096 jetons de contexte, rédhibitoire pour un assistant de"
            " code, et le 4B-Instruct n'a aucun build NVFP4, ni officiel ni"
            " communautaire.",
            "A 4 096-token context, fatal for a coding assistant, and the"
            " 4B-Instruct has no NVFP4 build at all, official or community.",
            "Neuf des dix quantifications officielles sont en MLX, donc Apple"
            " uniquement ; la seule NVFP4 ne couvre que le 1,5 milliard.",
            "Nine of the ten official quantizations are MLX, hence"
            " Apple-only; the only NVFP4 one covers just the 1.5-billion"
            " model.",
        ),
        _mod(
            "apertus-v1.5-8b",
            "Apertus-v1.5-8B",
            "Swiss AI Initiative (EPFL / ETH / CSCS)",
            "8,90 G dense (multimodal)",
            "dense, GQA, 32 couches, tours image et audio",
            "262 144",
            "Apache-2.0 (gated)",
            "bf16 18,4 Go · FP8 11,4 Go · NVFP4 9,0 Go",
            "128,0 Kio (2·32·8·128·2)",
            "fork swiss-ai/vllm uniquement",
            "aucun publié",
            "262 144 jetons sur une machine sans effort, 49,1 Gio pour un"
            " créneau plein, et la seule voie multimodale d'Apertus.",
            "262 144 tokens on one machine without strain, 49.1 GiB for a"
            " full slot, and Apertus's only multimodal path.",
            "Aucun moteur en amont ne le charge : la PR vLLM #50496 reste"
            " ouverte, et les quantifications restent des apertus1p5 passant"
            " par le même fork.",
            "No upstream engine loads it: vLLM PR #50496 is still open, and"
            " the quantizations are still apertus1p5 going through the same"
            " fork.",
            "Tout GGUF v1.5 est une amputation : les deux tours sont retirées"
            " de la weight map et le vocabulaire tronqué de 266 752 à"
            " 131 072.",
            "Every v1.5 GGUF is an amputation: both towers are stripped from"
            " the weight map and the vocabulary truncated from 266 752 to"
            " 131 072.",
        ),
        _mod(
            "apertus-v1.5-70b",
            "Apertus-v1.5-70B",
            "Swiss AI Initiative (EPFL / ETH / CSCS)",
            "72,0 G dense (multimodal)",
            "dense, GQA, 80 couches, tours image et audio",
            "262 144",
            "Apache-2.0 (gated)",
            "W4A16 43,0 Go · FP8 76,2 Go · bf16 144,6 Go",
            "320,0 Kio (2·80·8·128·2)",
            "fork swiss-ai/vllm ; llama.cpp (texte)",
            "aucun publié",
            "Un seul build atteint 262 144 sur une machine, le W4A16-KV8 :"
            " 40,0 Gio de poids et 40,0 Gio de cache fp8, avec 14 Gio de"
            " marge.",
            "One build alone reaches 262 144 on a single machine, W4A16-KV8:"
            " 40.0 GiB of weights and 40.0 GiB of fp8 cache, with 14 GiB to"
            " spare.",
            "Ce sont les 80 Gio de cache qui ferment la porte, pas les poids,"
            " et le débit plafonne entre 2,5 et 5,1 jet/s selon la"
            " quantification.",
            "It is the 80 GiB of cache that shuts the door, not the weights,"
            " and throughput tops out between 2.5 and 5.1 tok/s depending on"
            " quantization.",
            "Le seul build qui tienne le contexte plein est le moins"
            " supporté, et le NVFP4 d'onprem-ai est mixte : NVFP4 sur les"
            " MLP, FP8 sur l'attention.",
            "The only build that holds the full context is the least"
            " supported, and onprem-ai's NVFP4 is mixed: NVFP4 on the MLPs,"
            " FP8 on attention.",
        ),
        _mod(
            "qwen3.5-4b",
            "Qwen3.5-4B",
            "Alibaba (Qwen)",
            "4 G dense",
            "dense hybride, 8 couches d'attention sur 32",
            "262 144 → 1,01 M YaRN",
            "Apache-2.0",
            "bf16 8,1 Go (7,5 Gio)",
            "32,0 Kio (2·8·4·128·2)",
            "vLLM, llama.cpp, Ollama, LocalAI",
            "aucun publié",
            "La preuve que le contexte ne suit pas la taille : quatre"
            " milliards de paramètres documentent 1,01 M de jetons, pour"
            " 38,0 Gio au total.",
            "Proof that context does not follow size: four billion parameters"
            " document 1.01 M tokens, for 38.0 GiB all told.",
            "À 1 M, le cache vaut quatre fois le modèle, 30,5 Gio contre 7,5,"
            " et, étant dense, il plafonne à 34,1 jet/s sans aucun banc de"
            " code.",
            "At 1 M the cache is worth four times the model, 30.5 GiB against"
            " 7.5, and being dense it tops out at 34.1 tok/s, with no coding"
            " benchmark.",
            "À garder au menu pour ce qu'il démontre, pas pour ce qu'il"
            " code : la longueur de contexte tient à l'encodage positionnel"
            " et à l'attention.",
            "Keep it on the menu for what it demonstrates, not for what it"
            " codes: context length comes from positional encoding and"
            " attention layout.",
        ),
        _mod(
            "qwen3.8-27b",
            "Qwen3.8-27B",
            "Alibaba (Qwen)",
            "27,8 G dense",
            "dense, GQA, 64 couches",
            "262 144",
            "Apache-2.0",
            "Q4 17,6 Go · Q8 29,0 Go · bf16 55,6 Go",
            "256,0 Kio (2·64·4·256·2) calc.",
            "vLLM, llama.cpp, Ollama, LocalAI",
            "Terminal-Bench 2.1 0,730 (indépendant)",
            "Il frappe au-dessus de sa taille, 0,730 de Terminal-Bench pour"
            " 27,8 G, et toutes ses quantifications tiennent sur une"
            " machine.",
            "It punches above its size, 0.730 on Terminal-Bench for 27.8 G,"
            " and every one of its quantizations fits on a single machine.",
            "Dense, donc disqualifié sur le débit : son quasi-jumeau"
            " Qwen3.6-27B a été mesuré à 12,63 jet/s sur un nœud, sous la"
            " vitesse interactive.",
            "Dense, hence disqualified on throughput: its near-twin"
            " Qwen3.6-27B was measured at 12.63 tok/s on one node, below"
            " interactive speed.",
            "Filtrer sur les paramètres ACTIFS, jamais sur le total : un MoE"
            " de 229 G à 10 G tourne trois fois plus vite que ce dense"
            " de 27 G.",
            "Filter on ACTIVE parameters, never on the total: a 229 G MoE"
            " with 10 G active runs three times faster than this 27 G dense"
            " model.",
        ),
        _mod(
            "nemotron-3-nano-30b-a3b",
            "Nemotron 3 Nano 30B-A3B",
            "NVIDIA",
            "31,6 G · act. 3,6 G (MoE)",
            "Mamba-2 + MoE, 6 couches d'attention sur 52",
            "262 144 (config)",
            "NVIDIA Open Model License",
            "FP8 31,6 Go · bf16 63,2 Go",
            "6,0 Kio (2·6·2·128·2)",
            "vLLM",
            "aucun publié",
            "Le cache le moins cher relevé : 5,7 Gio pour un million de"
            " jetons, soit 64,6 Gio au total en bf16 et 32,3 Gio en FP8 sur"
            " une machine.",
            "The cheapest cache on record: 5.7 GiB for a million tokens, so"
            " 64.6 GiB all told in bf16 and 32.3 GiB in FP8 on one machine.",
            "Une limite déployée de 131 072 jetons a été mesurée via l'API"
            " NIM, avec dégradation au-delà de 128 K, et aucun score de"
            " codage n'existe.",
            "A deployed limit of 131 072 tokens was measured through the NIM"
            " API, with degradation past 128 K, and no coding score exists"
            " anywhere.",
            "NVIDIA a reconnu par écrit que le 1 M annoncé est une erreur de"
            " documentation : le config dit 262 144 et le README 128 K plus"
            " 128 K.",
            "NVIDIA acknowledged in writing that the announced 1 M is a"
            " documentation error: the config says 262 144 and the README"
            " 128 K plus 128 K.",
        ),
        _mod(
            "qwen3.6-35b-a3b",
            "Qwen3.6-35B-A3B",
            "Alibaba (Qwen)",
            "35 G · act. 3 G (MoE)",
            "MoE hybride, 10 couches d'attention sur 40",
            "262 144 → 1,01 M YaRN",
            "Apache-2.0",
            "FP8 35,0 Go · bf16 70,0 Go",
            "20,0 Kio (2·10·2·128·2)",
            "vLLM, llama.cpp",
            "SWE-bench Verified 0,734 (indépendant)",
            "Le meilleur compromis vitesse-contexte sur une machine :"
            " 42,1 Gio en FP8 pour un million de jetons, avec 91 jet/s de"
            " plafond.",
            "The best speed-to-context trade-off on one machine: 42.1 GiB in"
            " FP8 for a million tokens, with a 91 tok/s ceiling.",
            "Le million est une extrapolation YaRN, et son grand frère"
            " Qwen3.6-Plus tombe de 68,34 à 54,98 sur ATLAS entre 128 K et"
            " 1 M de portée.",
            "The million is a YaRN extrapolation, and its bigger sibling"
            " Qwen3.6-Plus falls from 68.34 to 54.98 on ATLAS between a"
            " 128 K and a 1 M span.",
            "Génération plus récente de la recette de Qwen3.5-35B-A3B, à lui"
            " préférer : géométrie identique, qualité égale ou meilleure.",
            "A newer generation of the Qwen3.5-35B-A3B recipe, to be"
            " preferred over it: identical geometry, equal or better"
            " quality.",
        ),
        _mod(
            "qwen3.5-35b-a3b",
            "Qwen3.5-35B-A3B",
            "Alibaba (Qwen)",
            "35 G · act. 3 G (MoE)",
            "MoE hybride, 10 couches d'attention sur 40",
            "262 144 → 1,01 M YaRN",
            "Apache-2.0",
            "FP8 35,0 Go · bf16 70,0 Go",
            "20,0 Kio (2·10·2·128·2)",
            "vLLM, llama.cpp",
            "aucun publié",
            "Même arithmétique que le 3.6 : 42,1 Gio au total pour un million"
            " de jetons en FP8, avec 91 jet/s de plafond.",
            "Same arithmetic as the 3.6: 42.1 GiB all told for a million"
            " tokens in FP8, with a 91 tok/s ceiling.",
            "Remplacé par Qwen3.6-35B-A3B, de géométrie identique : il n'y a"
            " aucune raison de le déployer neuf.",
            "Superseded by Qwen3.6-35B-A3B, of identical geometry: there is"
            " no reason to deploy it fresh.",
            "PÉRIMÉ au profit du 3.6, et conservé parce que c'est sur lui que"
            " porte l'arithmétique de contexte publiée.",
            "Superseded by the 3.6, kept here because the published context"
            " arithmetic was done on it.",
        ),
        _mod(
            "gpt-oss-120b",
            "gpt-oss-120b",
            "OpenAI",
            "116,8 G · act. 5,1 G (MoE)",
            "MoE, GQA, 36 couches, MXFP4 natif",
            "131 072",
            "Apache-2.0",
            "63,0 Go (MXFP4)",
            "72,0 Kio (2·36·8·128·2)",
            "llama.cpp, Ollama, LocalAI, vLLM",
            "aucun publié pour 2026",
            "La chose la plus rapide vérifiée sur ce silicium : 1 956 jet/s"
            " en préremplissage, 60,57 en décodage, et sa fenêtre entière"
            " tient.",
            "The fastest thing verified on this silicon: 1 956 tok/s in"
            " prefill, 60.57 decoding, and its entire window fits.",
            "131 072 jetons, la moitié de ce qu'un agent de dépôt demande, et"
            " OpenAI n'a rien publié d'ouvert depuis le 4 août 2025.",
            "131 072 tokens, half of what a repository agent asks for, and"
            " OpenAI has published nothing open since 4 August 2025.",
            "Périmé comme agent principal, excellent en complétion locale."
            " Sans le noyau NVIDIA 6.17.1, son chargement passe de 22 s à"
            " 104 s.",
            "Superseded as a main agent, excellent as local completion."
            " Without the NVIDIA 6.17.1 kernel its load time goes from 22 s"
            " to 104 s.",
        ),
        _mod(
            "mistral-small-4-119b-2603",
            "Mistral-Small-4-119B-2603",
            "Mistral AI",
            "119 G · act. 6,5 G (MoE)",
            "MoE multimodal, 36 couches, 128 experts",
            "1 048 576 (config) ⚑ 200 K",
            "Apache-2.0",
            "NVFP4 70,8 Go · IQ4_XS 58,1 Go",
            "576,0 Kio (2·36·32·128·2)",
            "vLLM, llama.cpp",
            "aucun publié exploitable (cartes en images)",
            "Le logement le plus confortable du catalogue : 65,9 Gio sur une"
            " machine, 45 Gio réellement libres, Apache-2.0 et 6,5 G"
            " seulement.",
            "The most comfortable fit in the catalogue: 65.9 GiB on one"
            " machine, 45 GiB genuinely free, Apache-2.0, and only 6.5 G"
            " active.",
            "Son cache est le plus cher du catalogue, vingt-quatre fois celui"
            " du Flash-Next : les 45 Gio libres n'achètent que 82 K jetons en"
            " bf16.",
            "Its cache is the priciest in the catalogue, twenty-four times"
            " the Flash-Next's: the 45 GiB free buy only 82 K tokens in"
            " bf16.",
            "L'exemple canonique : vérifier kv_heads x head_dim x couches"
            " avant de croire une longueur de contexte. Budgéter 64 K à"
            " 100 K de contexte réel.",
            "The canonical example: check kv_heads x head_dim x layers before"
            " believing a context length. Budget 64 K to 100 K of real"
            " context.",
        ),
        _mod(
            "devstral-2-123b",
            "Devstral 2 123B Instruct 2512",
            "Mistral AI",
            "123 G dense (Small 2 : 24 G dense)",
            "dense, GQA, 88 couches",
            "262 144",
            "license:other (Mistral (custom))",
            "Q4_K_M 74,9 Go · Small 2 en Q4 ~14 Go",
            "—",
            "vLLM, llama.cpp",
            "SWE-bench Verified 72,2 (auto-déclaré)",
            "Le petit frère Devstral Small 2 en Q4 tient en 14 Go et donne 12"
            " à 14 jet/s pour 68,0 % de SWE-bench Verified, sous"
            " Apache-2.0.",
            "The little Devstral Small 2 in Q4 fits in 14 GB and gives 12 to"
            " 14 tok/s for 68.0 % on SWE-bench Verified, under Apache-2.0.",
            "Le 123B est dense : 74,9 Go relus à chaque jeton, 3,6 jet/s de"
            " plafond — du travail par lots, pas un assistant interactif.",
            "The 123B is dense: 74.9 GB reread for every token, a 3.6 tok/s"
            " ceiling — batch work, not an interactive assistant.",
            "PÉRIMÉ au profit de Mistral-Small-4-119B-2603, et il tient"
            " pourtant sur une machine : « ça rentre » n'est pas un critère.",
            "Superseded by Mistral-Small-4-119B-2603, and yet it fits on one"
            ' machine: "it fits" is not a criterion.',
        ),
        _mod(
            "nemotron-3-super-120b-a12b",
            "Nemotron 3 Super 120B-A12B",
            "NVIDIA",
            "120,6 G · act. 12,7 G (MoE)",
            "Mamba-2 + MoE, 8 couches d'attention sur 88",
            "262 144 (config)",
            "NVIDIA Open Model License",
            "NVFP4 80,3 Go · FP8 128,4 Go",
            "8,0 Kio (2·8·2·128·2)",
            "vLLM (NVFP4 natif)",
            "aucun publié confirmable",
            "Réglé par NVIDIA pour du silicium NVIDIA et nativement NVFP4 :"
            " 60 Gio au total sur une machine pour un million de jetons de"
            " contexte.",
            "Tuned by NVIDIA for NVIDIA silicon and natively NVFP4: 60 GiB"
            " all told on one machine for a million tokens of context.",
            "Le FP8 à 116,1 Gio contre 117 utilisables ne tient pas en"
            " pratique, et vLLM mesure 22,7 à 23,7 jet/s, nettement sous"
            " l'estimation théorique.",
            "Its FP8 at 116.1 GiB against 117 usable does not fit in"
            " practice, and vLLM measures 22.7 to 23.7 tok/s, well under the"
            " theoretical estimate.",
            "NVIDIA a reconnu par écrit que l'annonce de 1 M est une erreur"
            " de documentation : la configuration « une machine » est le"
            " NVFP4, pas le FP8.",
            "NVIDIA acknowledged in writing that the 1 M claim is a"
            " documentation error: the single-machine configuration is NVFP4,"
            " not FP8.",
        ),
        _mod(
            "qwen3.8-flash-next",
            "Qwen3.8-Flash-Next",
            "Alibaba (Qwen)",
            "125 G · act. 6 G (MoE) · 180 G",
            "MoE hybride, 12 couches d'attention sur 48",
            "262 144 → 1 M YaRN",
            "qwen-community-1.0",
            "IQ4_XS 93,7 Go · NVFP4 132,7 Go",
            "24,0 Kio (2·12·2·128·2)",
            "llama.cpp, Ollama, LocalAI, vLLM",
            "SWE-bench Pro 62,5 (auto-déclaré)",
            "Le seul à tenir un million de jetons sur une machine : 87,3 Gio"
            " de poids plus 11,4 Gio de cache fp8, et six milliards de"
            " paramètres actifs.",
            "The only one holding a million tokens on one machine: 87.3 GiB"
            " of weights plus 11.4 GiB of fp8 cache, and six billion active"
            " parameters.",
            "Aucun chiffre indépendant, une licence maison à lire avant tout"
            " déploiement commercial, et un million de jetons extrapolé"
            " depuis 262 144.",
            "No independent figure, a house licence to read before any"
            " commercial deployment, and a million tokens extrapolated from"
            " 262 144.",
            "Le cache bf16 porte le total à 110,2 Gio, trop serré une fois"
            " les activations et les graphes comptés : passer"
            " --kv-cache-dtype fp8.",
            "A bf16 cache brings the total to 110.2 GiB, too tight once"
            " activations and graphs are counted: switch to --kv-cache-dtype"
            " fp8.",
        ),
        _mod(
            "kimi-linear-48b-a3b",
            "Kimi-Linear-48B-A3B-Instruct",
            "Moonshot AI",
            "48 G · act. ~3 G (MoE)",
            "MoE à attention linéaire, 27 couches",
            "—",
            "MIT",
            "bf16 98,3 Go",
            "—",
            "vLLM, SGLang",
            "aucun publié",
            "Le seul Moonshot qui tienne confortablement sur une machine,"
            " 98,3 Go pour 117 Gio utilisables, avec un plafond de 90 jet/s à"
            " 3 G.",
            "The only Moonshot model that fits comfortably on one machine,"
            " 98.3 GB against 117 GiB usable, with a 90 tok/s ceiling at 3 G"
            " active.",
            "C'est un modèle de recherche sur l'attention linéaire, sans"
            " aucun banc de code, et son contexte natif n'a pas été relevé.",
            "It is a research model on linear attention, with no coding"
            " benchmark at all, and its native context was not recorded.",
            "",
            "",
        ),
        _mod(
            "minimax-m2.7",
            "MiniMax-M2.7",
            "MiniMax",
            "228,7 G · act. 10 G (MoE)",
            "MoE, GQA, 62 couches, FP8 natif",
            "204 800",
            "Modified MIT",
            "IQ4_XS 108,4 Go · NVFP4 139,9 Go",
            "248,0 Kio (2·62·8·128·2)",
            "vLLM, llama.cpp",
            "SWE-bench Verified 0,802 (indépendant)",
            "Le plus haut SWE-bench Verified corroboré par un tiers parmi ce"
            " qui tient, 0,802, pour dix milliards de paramètres actifs"
            " seulement.",
            "The highest third-party-corroborated SWE-bench Verified among"
            " models that fit, 0.802, for only ten billion active"
            " parameters.",
            "Une machine pour ses poids seulement : les 10 Gio qui restent"
            " n'achètent que 42 K jetons, un cinquième de sa propre fenêtre"
            " de 204 800.",
            "One machine for its weights only: the 10 GiB left buy just 42 K"
            " tokens, a fifth of its own 204 800-token window.",
            "Personne n'avait calculé son cache avant de l'appeler « modèle"
            " une machine » : sa fenêtre pleine coûte 48,4 Gio en bf16,"
            " 24,2 en fp8.",
            "Nobody costed its cache before calling it a single-machine"
            " model: its full window costs 48.4 GiB in bf16, 24.2 in fp8.",
        ),
        _mod(
            "deepseek-v4-flash-0731",
            "DeepSeek-V4-Flash-0731",
            "DeepSeek",
            "304,2 G · act. ~13 G (MoE)",
            "MoE, MLA, 43 couches, DSpark fusionné",
            "65 536 → 1 M YaRN",
            "MIT",
            "IQ3_XXS 104,2 Go · NVFP4 175,6 Go",
            "48,4 Kio (MLA 43·576·2)",
            "vLLM, SGLang, llama.cpp",
            "Terminal-Bench 2.1 0,827 (indépendant)",
            "Le seul mesuré sur ce matériel exact : 52,87 jet/s en décodage"
            " sur deux machines reliées en direct, sous MIT, avec un cache"
            " MLA compact.",
            "The only one measured on this exact hardware: 52.87 tok/s"
            " decoding across two directly linked machines, under MIT, with a"
            " compact MLA cache.",
            "Deux machines en NVFP4, un TTFT de 89,36 s mesuré à 131 K, et un"
            " million de jetons étiré par YaRN depuis une base entraînée à"
            " 64 K.",
            "Two machines in NVFP4, a TTFT of 89.36 s measured at 131 K, and"
            " a million tokens YaRN-stretched from a base trained at 64 K.",
            "DeepSeek publie cinq V4-Flash distincts, 0423, 0731, Max, DSpark"
            " et V4.1 : épingler l'identifiant de dépôt et la révision, pas"
            " le nom.",
            "DeepSeek publishes five distinct V4-Flash models, 0423, 0731,"
            " Max, DSpark and V4.1: pin the repository ID and the revision,"
            " not the name.",
        ),
        _mod(
            "glm-5.3-flash",
            "GLM-5.3-Flash",
            "Z.ai / Zhipu (zai-org)",
            "321,3 G · act. 18 G (MoE)",
            "MoE multimodal, 45 couches, attention hybride",
            "1 048 576 ⚑ 300 K",
            "MIT",
            "IQ3_XXS 120,4 Go · NVFP4 204,4 Go",
            "50,6 Kio (MLA 45·576·2, inf.)",
            "vLLM, llama.cpp",
            "Terminal-Bench 2.1 0,843 (indépendant)",
            "Le meilleur score de codage indépendant de tout ce qui tient,"
            " 0,843 de Terminal-Bench, sous MIT et nativement multimodal.",
            "The best independent coding score among everything that fits,"
            " 0.843 on Terminal-Bench, under MIT and natively multimodal.",
            "Dix-huit milliards de paramètres actifs coûtent 30 % de débit"
            " contre DeepSeek-V4-Flash pour 1,6 point de Terminal-Bench de"
            " plus.",
            "Eighteen billion active parameters cost 30 % of throughput"
            " against DeepSeek-V4-Flash for 1.6 more points of"
            " Terminal-Bench.",
            "Son cache est le seul inféré du catalogue, et l'UD-IQ3_XXS"
            " tiendrait sur une machine sans qu'aucun banc rejoue ce niveau"
            " de quantification.",
            "Its cache is the only inferred one in the catalogue, and the"
            " UD-IQ3_XXS would fit one machine with no benchmark replaying"
            " that level.",
        ),
        _mod(
            "minimax-m3",
            "MiniMax-M3",
            "MiniMax",
            "~428 G · act. ~23 G (MoE)",
            "MoE, GQA + attention creuse, 60 couches",
            "1 048 576",
            "minimax-community",
            "IQ3_XXS 194,9 Go · IQ4_XS 207,6 Go",
            "120,0 Kio (2·60·4·128·2)",
            "vLLM, llama.cpp",
            "SWE-bench Verified 0,805 (indépendant)",
            "Un million de jetons nativement, sans extrapolation, et l'un des"
            " meilleurs SWE-bench Verified ouverts à 0,805.",
            "A million tokens natively, with no extrapolation, and one of the"
            " best open SWE-bench Verified scores at 0.805.",
            "L'attention creuse réduit le calcul, pas le cache : les 60"
            " couches stockent K et V en entier, 114,4 Gio à 1 M, plus qu'une"
            " machine.",
            "Sparse attention cuts compute, not cache: all 60 layers store K"
            " and V in full, 114.4 GiB at 1 M, more than a whole machine.",
            "Il tient tout juste sur deux machines sans être recommandé : à"
            " 23 G, il décode deux fois plus lentement que M2.7 sans"
            " rien gagner.",
            "It barely fits two machines and is not recommended: at 23 G"
            " active it decodes twice as slowly as M2.7 for no gain.",
        ),
        _mod(
            "glm-5.3",
            "GLM-5.3",
            "Z.ai / Zhipu (zai-org)",
            "~744 G · act. —",
            "MoE, 78 couches, 256 experts routés",
            "1 048 576 (config)",
            "license:other « glm-5.3 »",
            "IQ3_XXS 281,7 Go · IQ4_XS 365,3 Go · FP8 755 Go",
            "— (cf. GLM-5.2 : 87,8 Kio)",
            "vLLM, SGLang (classe datacentre)",
            "Terminal-Bench 2.1 0,882 (indépendant)",
            "Le modèle de codage ouvert le plus fort qui existe : 0,882 de"
            " Terminal-Bench, et un CyberGym à 84,5 devant tout modèle"
            " propriétaire.",
            "The strongest open coding model there is: 0.882 on"
            " Terminal-Bench, and a CyberGym of 84.5 ahead of every"
            " proprietary model.",
            "Ne tient pas : 365,3 Go en 4 bits contre 251 Go pour deux"
            " machines, et même le 3 bits à 281,7 Go déborde encore.",
            "It does not fit: 365.3 GB in 4 bits against 251 GB for two"
            " machines, and even the 3-bit at 281.7 GB still overflows.",
            "Sa licence a quitté le MIT de GLM-5 à 5.2 : si la pureté de"
            " licence compte, épingler GLM-5.2 ou prendre le Flash, resté"
            " MIT.",
            "Its licence left the MIT of GLM-5 through 5.2: if licence purity"
            " matters, pin GLM-5.2 or take the Flash, which stayed MIT.",
        ),
        _mod(
            "deepseek-v4.1-flash",
            "DeepSeek-V4.1-Flash",
            "DeepSeek",
            "763,2 G",
            "MoE, MLA, DSpark fusionné",
            "1 048 576 (config)",
            "MIT",
            "FP8 510,3 Go · ~380 Go en 4 bits",
            "—",
            "vLLM, SGLang (classe datacentre)",
            "Terminal-Bench 2.1 0,906, rang 1 (indépendant)",
            "La démonstration que la frontière ouverte égale ou dépasse la"
            " frontière propriétaire, rang 1 à 0,906, et qu'elle est sous"
            " MIT.",
            "The demonstration that the open frontier matches or beats the"
            " proprietary one, rank 1 at 0.906, and that it is MIT-licensed.",
            "Ne tient pas : environ 380 Go en 4 bits contre 251 Go pour"
            " deux machines.",
            "It does not fit: roughly 380 GB even in 4 bits against 251 GB"
            " for two machines.",
            "Publié trois jours avant ce relevé, il redéfinit le haut du"
            " classement ; le 0731 Flash est la branche exécutable de la même"
            " famille.",
            "Published three days before this survey, it redefines the top of"
            " the leaderboard; the 0731 Flash is the runnable branch of the"
            " same family.",
        ),
        _mod(
            "kimi-k2.7-code",
            "Kimi K2.7-Code",
            "Moonshot AI",
            "1 000 G · act. 32 G (MoE)",
            "MoE, MLA, 61 couches, INT4 natif",
            "262 144",
            "Modified MIT",
            "595,2 Go (INT4)",
            "68,6 Kio (MLA 61·576·2)",
            "vLLM, SGLang (classe datacentre)",
            "Kimi Code Bench v2 62,0 (auto-déclaré)",
            "Spécialisé code, sous une licence quasi MIT sans contrainte"
            " d'usage interne, et son cache reste minuscule : 18,4 Go pour"
            " 256 K.",
            "Code-specialized, under a near-MIT licence with no internal-use"
            " constraint, and its cache stays tiny: 18.4 GB for 256 K of"
            " context.",
            "Ne tient pas : 595,2 Go contre 251 Go pour deux machines, et il"
            " est INT4 — descendre plus bas demanderait environ deux"
            " bits.",
            "It does not fit: 595.2 GB against 251 GB for two machines, and"
            " it is already INT4 — going lower would need about two bits.",
            "La variante highspeed n'a aucun poids publié : les vitesses qui"
            " en viennent ne sont pas reproductibles en auto-hébergement.",
            "The highspeed variant has no published weights: the speeds"
            " quoted from it are not reproducible when self-hosting.",
        ),
        _mod(
            "kimi-k3",
            "Kimi K3",
            "Moonshot AI",
            "2 800 G · act. 104 G (MoE)",
            "MoE, 24 couches MLA sur 93, le reste linéaire",
            "1 048 576",
            "Kimi K3 License (Modified MIT +)",
            "1 560,9 Go en MXFP4 (119)",
            "27,0 Kio (MLA 24/93)",
            "vLLM (au moins 8 GB300)",
            "Terminal-Bench 2.1 0,883, rang 5 (indépendant)",
            "Vingt-quatre couches seulement gardent un cache qui croît, d'où"
            " 29 Go de KV à un million de jetons pour 2 800 milliards de"
            " paramètres.",
            "Only twenty-four layers keep a growing cache, hence 29 GB of KV"
            " at a million tokens for 2 800 billion parameters.",
            "Ne tient pas : 1 560,9 Go, treize machines pour les poids seuls,"
            " et 57 Go relus par jeton décodé donneraient 4,8 jet/s.",
            "It does not fit: 1 560.9 GB, thirteen machines for the weights"
            " alone, and 57 GB reread per decoded token would give"
            " 4.8 tok/s.",
            "Il renvoie toujours reasoning_content, qu'il faut repasser tel"
            " quel : un agent qui ne repasse que content perd le fil sans"
            " erreur ni diagnostic.",
            "It always returns reasoning_content, which must be passed back"
            " verbatim: an agent returning only content loses the thread"
            " silently, with no diagnosis.",
        ),
    )
}


# Les en-têtes de colonne, par langue. Ce sont les SEULS mots de la table
# générée qui se traduisent : le reste est du chiffre et du nom propre.
ENTETES = {
    "fr": {
        "nom": "Nom",
        "licence": "Licence",
        "port": "Port",
        "api": "API",
        "formats": "Formats",
        "plateformes": "Plateformes",
        "version_min": "Minimum Apertus",
        "editeur": "Éditeur",
        "parametres": "Paramètres",
        "contexte": "Contexte",
        "poids": "Poids",
        "kv_par_jeton": "Cache KV/jeton",
    },
    "en": {
        "nom": "Name",
        "licence": "Licence",
        "port": "Port",
        "api": "API",
        "formats": "Formats",
        "plateformes": "Platforms",
        "version_min": "Apertus minimum",
        "editeur": "Publisher",
        "parametres": "Parameters",
        "contexte": "Context",
        "poids": "Weights",
        "kv_par_jeton": "KV cache/token",
    },
}


def markdown(lignes, colonnes, langue: str) -> str:
    """Les mêmes données, en tableau Markdown.

    La documentation reprend CE rendu et ne le recopie pas : un tableau
    recopié à la main dérive de la table qui fait autorité, et c'est dans la
    documentation que la dérive se voit le moins — personne ne relit un
    tableau de chiffres pour vérifier qu'il dit encore vrai.
    """
    entetes = ENTETES[langue]
    lignes_texte = [
        "| " + " | ".join(entetes[c] for c in colonnes) + " |",
        "|" + "|".join(["---"] * len(colonnes)) + "|",
    ]
    for ligne in tableau(lignes, colonnes):
        lignes_texte.append("| " + " | ".join(ligne) + " |")
    return "\n".join(lignes_texte)


def tableau(lignes, colonnes) -> list[list[str]]:
    """Les lignes demandées réduites aux colonnes demandées, en texte.

    Rend une liste de listes plutôt qu'un tableau formaté : le menu et la
    documentation n'alignent pas de la même façon, et un seul d'eux impose son
    format à l'autre si la mise en forme se décide ici.
    """
    return [
        [str(getattr(ligne, colonne)) for colonne in colonnes]
        for ligne in lignes
    ]
