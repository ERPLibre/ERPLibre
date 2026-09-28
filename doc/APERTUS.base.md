<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Apertus — the open LLM, on your own machine

Apertus is a large language model that ERPLibre can install for you, here or
on a server you own, and then talk to from the TODO CLI. The whole path is one
menu entry: `TODO › Assistant › AI › Apertus`.

This guide says what the model is, which variant and which engine to pick,
what it costs in disk and memory, how the menu installs it, and — just as
important — what is **not** official about that path.

<!-- [fr] -->
# Apertus — le LLM ouvert, sur sa propre machine

Apertus est un grand modèle de langage qu'ERPLibre sait installer pour vous,
ici ou sur un serveur qui vous appartient, puis avec lequel le CLI TODO
discute. Tout le chemin tient dans une entrée de menu :
`TODO › Assistant › IA › Apertus`.

Ce guide dit ce qu'est le modèle, quelle variante et quel moteur choisir, ce
que ça coûte en disque et en mémoire, comment le menu l'installe et — tout
aussi important — ce qui n'est **pas** officiel dans ce chemin.

<!-- [en] -->
## 1. What Apertus is

Apertus comes from the **Swiss AI Initiative**, a joint effort of **EPFL**,
**ETH Zurich** and the **CSCS** (the Swiss National Supercomputing Centre, in
Lugano). It was trained on **Alps**, the CSCS supercomputer. Its licence is
**Apache-2.0**.

| | |
|---|---|
| Official site | `https://apertus-ai.org/` |
| Documentation | `https://apertus-ai.org/docs/` |
| Weights | `https://huggingface.co/swiss-ai` |

"Open" here is meant in its strong sense, and it is the reason this model is
in ERPLibre rather than another one. Three things are published, not one:

- the **weights**, downloadable without an account and redistributable;
- the **training data** — which corpora, in what proportion, with what
  filtering;
- the **full training recipe** — the hyper-parameters, the schedule, the
  intermediate checkpoints, the code.

Most models called "open" publish only the first. Publishing the three is what
makes a result reproducible instead of merely usable.

**One reservation, and the guide states it rather than hide it.** Beside its
`LICENSE.txt`, Apertus ships a `USAGE_POLICY.md`, which carries an
indemnification obligation towards ETH Zurich and EPFL. The model stays free
and redistributable under Apache-2.0 — but "Apache-2.0, nothing else to read"
would be wrong. Read the policy before deploying the model in front of third
parties.

<!-- [fr] -->
## 1. Ce qu'est Apertus

Apertus vient de la **Swiss AI Initiative**, un effort commun de l'**EPFL**,
de l'**ETH Zurich** et du **CSCS** (le centre suisse de calcul scientifique, à
Lugano). Il a été entraîné sur **Alps**, le supercalculateur du CSCS. Sa
licence est **Apache-2.0**.

| | |
|---|---|
| Site officiel | `https://apertus-ai.org/` |
| Documentation | `https://apertus-ai.org/docs/` |
| Poids | `https://huggingface.co/swiss-ai` |

« Ouvert » s'entend ici au sens fort, et c'est la raison pour laquelle ce
modèle-là est dans ERPLibre plutôt qu'un autre. Trois choses sont publiées,
pas une :

- les **poids**, téléchargeables sans compte et redistribuables ;
- les **données d'entraînement** — quels corpus, en quelle proportion, avec
  quel filtrage ;
- la **recette d'entraînement complète** — les hyperparamètres, le calendrier,
  les points de contrôle intermédiaires, le code.

La plupart des modèles dits « ouverts » ne publient que le premier. Publier les
trois est ce qui rend un résultat reproductible au lieu de seulement
utilisable.

**Une réserve, et le guide la dit plutôt que de la taire.** À côté de son
`LICENSE.txt`, Apertus livre un `USAGE_POLICY.md`, qui porte une obligation
d'indemnisation envers l'ETH Zurich et l'EPFL. Le modèle reste libre et
redistribuable sous Apache-2.0 — mais « Apache-2.0, rien d'autre à lire »
serait faux. Lisez cette politique avant de déployer le modèle devant des
tiers.

<!-- [en] -->
## 2. Why it fits ERPLibre

ERPLibre is AGPL-3.0+ and requires free software of everything it ships. A
model under a "community licence" with a user-count cap, a field-of-use
restriction or a revocation clause would not pass that bar; Apache-2.0 does.
The four engines the menu can install are free too — three MIT, one
Apache-2.0.

**No vendor lock-in.** The model is a file. Nothing expires, nothing phones
home, no key is rotated out from under you, and no price list changes. An
installation that works today works the same in five years, offline.

**It runs on your own machine.** Local, or a server you administer. That is
what makes the CLI's assistant usable on real work: an ERP question carries
the data it is about — a customer name, an amount, a database name. Sent to a
hosted model, that data leaves. Served by an engine listening on `127.0.0.1`,
it never leaves the machine that already holds it.

This is the same reasoning that runs through the rest of the assistant: the
repository's rule is that an address, a host name or a database name never
becomes prompt text. A local model removes the question instead of guarding
it.

<!-- [fr] -->
## 2. Pourquoi il va avec ERPLibre

ERPLibre est sous AGPL-3.0+ et exige du logiciel libre de tout ce qu'il livre.
Un modèle sous « licence communautaire » avec un plafond d'utilisateurs, une
restriction de domaine d'usage ou une clause de révocation ne passerait pas
cette barre ; Apache-2.0 la passe. Les quatre moteurs que le menu sait
installer sont libres aussi — trois MIT, un Apache-2.0.

**Aucune dépendance à un fournisseur.** Le modèle est un fichier. Rien
n'expire, rien ne téléphone, aucune clé ne vous est retirée, aucune grille
tarifaire ne change. Une installation qui marche aujourd'hui marche pareil
dans cinq ans, hors ligne.

**Il tourne sur votre propre machine.** En local, ou sur un serveur que vous
administrez. C'est ce qui rend l'assistant du CLI utilisable sur du vrai
travail : une question d'ERP transporte la donnée dont elle parle — un nom de
client, un montant, un nom de base. Envoyée à un modèle hébergé, cette donnée
part. Servie par un moteur qui écoute sur `127.0.0.1`, elle ne quitte jamais
la machine qui la détenait déjà.

C'est le même raisonnement que dans le reste de l'assistant : la règle du
dépôt veut qu'une adresse, un nom d'hôte ou un nom de base ne devienne jamais
du texte d'invite. Un modèle local supprime la question au lieu de la
surveiller.

<!-- [en] -->
## 3. Choosing a model

Two families are offered, and one number separates them.

**Apertus 8B Instruct** (`swiss-ai/Apertus-8B-Instruct-2509`) is the full
model: 8 billion parameters, **65536 tokens of context**, Apache-2.0, no
account needed to download.

**Apertus Mini** is **Apertus v1.1**, published by the same team
(arXiv **2605.29128**). It is obtained by *pre-training distillation* from the
8B teacher: a 90 % KL-divergence / 10 % cross-entropy mix over **1.7 T
permissively-licensed tokens**, about ten times shorter than a full
pre-training run — 2.4 × 10²² FLOPs for the whole family, roughly 12 % of what
the 8B cost. It is a real, official model, not a community shrink.

> ⚠️ **The price of distillation is the context: 4096 tokens, against 65536
> for the 8B.** This is the single most important line of this section. A Mini
> will not read a long file, a long diff or a long conversation — it will
> forget the beginning. If you hit that wall, it is not a bug and no setting
> raises it.

| Model | Parameters | Context | GGUF size | Repository |
|---|---|---|---|---|
| Apertus 8B Instruct, `Q4_K_M` | 8 B | **65536** | 5.06 GB | `swiss-ai/Apertus-8B-Instruct-2509` |
| Apertus 8B Instruct, `Q8_0` | 8 B | **65536** | 8.57 GB | `swiss-ai/Apertus-8B-Instruct-2509` |
| Apertus Mini 1.5B Instruct | 1.5 B | **4096** | ≈ 1.2 GB | `swiss-ai/Apertus-v1.1-1.5B-Instruct` |
| Apertus Mini 0.5B Instruct | 0.5 B | **4096** | ≈ 0.5 GB | `swiss-ai/Apertus-v1.1-0.5B-Instruct` |
| Apertus 70B Instruct, 4-bit | 70 B | **65536** | 43.7 GB | `swiss-ai/Apertus-70B-Instruct-2509` |

A **4 B** Mini also exists upstream (`swiss-ai/Apertus-v1.1-4B-Instruct`, same
4096 tokens), but no GGUF build of it was found, so the menu does not offer
it.

Official quantizations are published for **MLX** (INT3/INT4/INT6, Apple
Silicon) and for **vLLM** (NVFP4A16). There is **no official GGUF** — see
section 8.

**The 70B is a different kind of machine.** It pays its 80 layers on every
token: **320 KiB of KV cache per token**, against 128 KiB for the 8B, so its
full 65536-token window costs **20 GiB of cache** on top of the weights. And
being dense, it reads every one of its weights per token — on a machine with
273 GB/s of memory bandwidth that caps it near 6 tokens per second, against
17 for the 8B. Take it when quality matters more than latency, and expect to
wait. On a coding agent, do not take it at all: its only published numbers are
HumanEval Pass@10 73.0 and MBPP 47.0, against 97.0 and 73.6 for a 32B coding
model on the same table.

**Which one to take.** Take the **8B in `Q4_K_M`** unless you have a reason
not to: it is the default, and the context is what makes an assistant useful
on real files. Take a **Mini** when the machine cannot hold the 8B, when you
want an answer in a second on a CPU, or when the questions are short and
self-contained. Take the **8B in `Q8_0`** only if you have memory to spare and
want the last bit of quality.

> ⚠️ **The 0.5 B Mini does not answer factual questions correctly.**
> Measured on a working install: it writes correct French, follows an
> instruction and leaks no special token — so the engine and the chat template
> are fine — and it still answers `2` to *two plus two* and names Geneva as the
> capital of Switzerland. Knowledge is what half a billion parameters cannot
> hold. Use it to exercise an install or to check that a server answers; use
> the 8B to get an answer you rely on.

**Do not aim at Apertus v1.5.** `swiss-ai/Apertus-v1.5-8B` is a *different
architecture*, it is gated on its download page (an account and a token are
required, so a remote machine fails with a 401 nobody expected), it is absent
from the upstream transformers library, from the vLLM registry and from the
llama.cpp converter, and its card demands a pinned fork of transformers. None
of the four engines serves it. The menu targets v1 and v1.1 only.

<!-- [fr] -->
## 3. Choisir un modèle

Deux familles sont proposées, et un seul nombre les sépare.

**Apertus 8B Instruct** (`swiss-ai/Apertus-8B-Instruct-2509`) est le modèle
complet : 8 milliards de paramètres, **65536 jetons de contexte**,
Apache-2.0, aucun compte nécessaire pour le télécharger.

**Apertus Mini**, c'est **Apertus v1.1**, publié par la même équipe (article
arXiv **2605.29128**). Il s'obtient par *distillation de pré-entraînement*
depuis le professeur 8B : un mélange 90 % divergence KL / 10 % entropie
croisée sur **1,7 T jetons à licence permissive**, environ dix fois plus court
qu'un pré-entraînement complet — 2,4 × 10²² FLOPs pour toute la famille, à peu
près 12 % de ce qu'a coûté le 8B. C'est un vrai modèle officiel, pas une
réduction communautaire.

> ⚠️ **Le prix de la distillation est le contexte : 4096 jetons, contre 65536
> pour le 8B.** C'est la ligne la plus importante de cette section. Un Mini ne
> lira pas un long fichier, un long diff ni une longue conversation — il en
> oubliera le début. Si vous butez là-dessus, ce n'est pas un bogue et aucun
> réglage ne le relève.

| Modèle | Paramètres | Contexte | Taille GGUF | Dépôt |
|---|---|---|---|---|
| Apertus 8B Instruct, `Q4_K_M` | 8 B | **65536** | 5,06 Go | `swiss-ai/Apertus-8B-Instruct-2509` |
| Apertus 8B Instruct, `Q8_0` | 8 B | **65536** | 8,57 Go | `swiss-ai/Apertus-8B-Instruct-2509` |
| Apertus Mini 1.5B Instruct | 1,5 B | **4096** | ≈ 1,2 Go | `swiss-ai/Apertus-v1.1-1.5B-Instruct` |
| Apertus Mini 0.5B Instruct | 0,5 B | **4096** | ≈ 0,5 Go | `swiss-ai/Apertus-v1.1-0.5B-Instruct` |
| Apertus 70B Instruct, 4 bits | 70 B | **65536** | 43,7 Go | `swiss-ai/Apertus-70B-Instruct-2509` |

Un Mini **4 B** existe aussi en amont (`swiss-ai/Apertus-v1.1-4B-Instruct`,
mêmes 4096 jetons), mais aucune version GGUF n'en a été trouvée : le menu ne
le propose donc pas.

Des quantifications officielles sont publiées pour **MLX** (INT3/INT4/INT6,
Apple Silicon) et pour **vLLM** (NVFP4A16). Il n'existe **aucun GGUF
officiel** — voir la section 8.

**Le 70B est une autre sorte de machine.** Il paie ses 80 couches à chaque
jeton : **320 Kio de cache clé-valeur par jeton**, contre 128 Kio pour le 8B,
donc sa fenêtre pleine de 65536 jetons coûte **20 Gio de cache** par-dessus les
poids. Et comme il est dense, il lit tous ses poids à chaque jeton — sur une
machine à 273 Go/s cela le plafonne vers 6 jetons par seconde, contre 17 pour
le 8B. Prenez-le quand la qualité compte plus que la latence, et attendez-vous
à attendre. Pour un agent de code, ne le prenez pas : ses seuls chiffres
publiés sont HumanEval Pass@10 73,0 et MBPP 47,0, contre 97,0 et 73,6 pour un
modèle de code de 32 B sur la même table.

**Lequel prendre.** Prenez le **8B en `Q4_K_M`** sauf raison contraire : c'est
le défaut, et le contexte est ce qui rend un assistant utile sur de vrais
fichiers. Prenez un **Mini** quand la machine ne peut pas tenir le 8B, quand
vous voulez une réponse en une seconde sur un processeur, ou quand les
questions sont courtes et se suffisent à elles-mêmes. Prenez le **8B en
`Q8_0`** seulement si vous avez de la mémoire de reste et voulez le dernier
cran de qualité.

> ⚠️ **Le Mini 0,5 B répond faux aux questions factuelles.**
> Mesuré sur une installation qui marche : il écrit un français correct, suit
> une consigne et ne laisse fuir aucun jeton spécial — le moteur et le gabarit
> de chat sont donc en place — et il répond pourtant `2` à *deux plus deux* et
> nomme Genève comme capitale de la Suisse. La connaissance est ce qu'un demi-
> milliard de paramètres ne peut pas contenir. Servez-vous-en pour éprouver une
> installation ou vérifier qu'un serveur répond ; prenez le 8B pour une réponse
> sur laquelle vous comptez.

**Ne visez pas Apertus v1.5.** `swiss-ai/Apertus-v1.5-8B` est une
*architecture différente*, son téléchargement est restreint (compte et jeton
exigés, donc un échec 401 que personne n'attend sur une machine distante), il
est absent de la bibliothèque de transformeurs amont, du registre vLLM et du
convertisseur llama.cpp, et sa carte impose un fork épinglé de transformers.
Aucun des quatre moteurs ne le sert. Le menu ne vise que v1 et v1.1.

<!-- [en] -->
## 4. Choosing an engine

An engine is the program that loads the weights and serves them over an
OpenAI-compatible HTTP API. Five are offered, all free software:

| Engine | Licence | Default port | Minimum version | Who it suits |
|---|---|---|---|---|
| **Ollama** | MIT | 11434 | **0.12.6** | anyone starting out — one install command, a systemd service, and the only engine that reports real download progress |
| **llama.cpp** | MIT | 8080 | build **b6671** | a machine where you have no root, or where you want to pick the quantization yourself |
| **LocalAI** | MIT | 8080 | **4.0.0** | a host that already serves several models through one gateway |
| **MLX** | MIT | 8080 | **0.27.1** | an Apple Silicon machine — and the only engine for one, since nothing else uses the GPU there |
| **vLLM** | Apache-2.0 | 8000 | **0.10.2** | a GPU machine serving several users at once |

The default is **Ollama**, and it is the right answer for a first install.

**On a Mac, take MLX and nothing else.** The menu can install Ollama or
llama.cpp there, and both will work — but they reach the GPU through a generic
path, where MLX is Apple's own framework. Two things follow. The official
`swiss-ai` quantizations of the Mini family are **MLX builds**: nine of the ten
quantizations the publisher ships are useless anywhere else and native here.
And the 70B has **no published MLX build at all**, so the menu converts it
locally with `mlx_lm.convert` — which downloads the full-precision weights
before writing the quantized ones, so it asks for about 175 GB of free space
to produce 41 GB. The menu says so before it starts.

One number to know before converting on a Mac: macOS reserves about a quarter
of the unified memory for the system, so a 256 GB machine offers roughly
192 GB to a model until `sudo sysctl iogpu.wired_limit_mb=237568` raises it to
about 232 GB. And Apple's matrix accelerators cover FP16 and INT8 but **not
BF16** — convert to 4-bit or 8-bit, never to bf16.

### Why a minimum version: the xIELU activation

Apertus does not use the activation function everything else uses. It uses
**xIELU**, and that single fact dates support for it everywhere. An engine
released before xIELU landed in its sources does not become slow or
approximate on Apertus — it **cannot** run it. It either refuses the file with
`unknown model architecture: apertus`, or loads it and produces gibberish.

That is why the menu **checks the engine version before downloading anything**
— step 5 of 9, ahead of the multi-gigabyte step 7. Learning about a version
number should not cost 5 GB of traffic.

Where xIELU landed:

- **llama.cpp** — build `b6671` (CPU and CUDA in the same change).
- **Ollama** — `0.12.6`. **No release note mentions it**; searching the
  changelog for "xielu" finds nothing, and only a diff of the vendored sources
  shows it. If the version check fails on an Ollama that looks recent, that is
  why.
- **vLLM** — `0.10.2`, which shipped before the model was public.
- **LocalAI** — inherits support from the llama.cpp it embeds; `4.0.0` is the
  floor the menu uses.

Other ggml back ends got xIELU later than CPU and CUDA: Vulkan, then Metal,
then SYCL/Intel. An Intel Arc target therefore needs much more than `b6671` —
check the build, not the calendar.

### What each engine costs you in practice

- **Ollama** installs itself from the distribution package where one exists,
  and from its upstream script otherwise; it registers its own service. It is
  the only one of the four whose pull emits a machine-readable progress
  stream, which is why the install screen can show a real percentage for it
  and only a step counter for the others.
- **llama.cpp** is installed from its upstream installer under your own
  account, without root. Distribution packages are frequently older than
  `b6671` — one current distribution still ships `b5882` — and you would only
  find out after downloading the weights.
- **LocalAI** needs the `huggingface://` URI form, because its gallery has no
  Apertus entry at all. Its **first** call also downloads a multi-gigabyte OCI
  back end image; that is a step of its own, not a fold of "start the server".
- **vLLM** is a GPU engine in practice. Its CPU wheel requires the `avx512f`
  instruction set and an `LD_PRELOAD`, and a virtual machine with a default
  CPU model often does not expose `avx512`. In bf16 the weights are 16.11 GB,
  which makes 24 GB of VRAM the real floor; a 16 GB card wants the
  `RedHatAI/Apertus-8B-Instruct-2509-FP8-dynamic` build instead (9.13 GB,
  Apache-2.0).

> ⚠️ **The fused xIELU CUDA kernel is deliberately not installed.** vLLM
> suggests installing it from a source repository that carries **no LICENSE
> file at all**, which an AGPL-3.0+ project cannot ship. The pure-PyTorch
> fallback is automatic and correct; it costs speed, nothing else.

<!-- [fr] -->
## 4. Choisir un moteur

Un moteur est le programme qui charge les poids et les sert sur une API HTTP
compatible OpenAI. Cinq sont proposés, tous libres :

| Moteur | Licence | Port par défaut | Version minimale | À qui il convient |
|---|---|---|---|---|
| **Ollama** | MIT | 11434 | **0.12.6** | à qui débute — une commande d'installation, un service systemd, et le seul moteur qui rapporte une vraie progression de téléchargement |
| **llama.cpp** | MIT | 8080 | construction **b6671** | une machine sans droits d'administration, ou quand on veut choisir soi-même la quantification |
| **LocalAI** | MIT | 8080 | **4.0.0** | un hôte qui sert déjà plusieurs modèles derrière une seule porte |
| **MLX** | MIT | 8080 | **0.27.1** | une machine Apple Silicon — et le seul moteur pour elle, rien d'autre n'y utilisant le GPU |
| **vLLM** | Apache-2.0 | 8000 | **0.10.2** | une machine à GPU servant plusieurs utilisateurs à la fois |

Le défaut est **Ollama**, et c'est la bonne réponse pour une première
installation.

**Sur un Mac, prenez MLX et rien d'autre.** Le menu sait y installer Ollama ou
llama.cpp, et les deux marcheront — mais ils atteignent le GPU par un chemin
générique, là où MLX est le cadre d'Apple lui-même. Deux conséquences. Les
quantifications officielles `swiss-ai` de la famille Mini sont des **builds
MLX** : neuf des dix que publie l'éditeur ne servent nulle part ailleurs et
sont natives ici. Et le 70B n'a **aucun build MLX publié**, donc le menu le
convertit sur place par `mlx_lm.convert` — ce qui télécharge les poids pleins
avant d'écrire les quantifiés, et demande donc environ 175 Go de place libre
pour en produire 41. Le menu le dit avant de commencer.

Un chiffre à connaître avant de convertir sur un Mac : macOS réserve environ un
quart de la mémoire unifiée au système, donc une machine de 256 Go n'en offre
que ~192 Go à un modèle jusqu'à ce que `sudo sysctl iogpu.wired_limit_mb=237568`
la porte à ~232 Go. Et les accélérateurs matriciels d'Apple couvrent FP16 et
INT8 mais **pas BF16** — convertissez en 4 ou 8 bits, jamais en bf16.

### Pourquoi une version minimale : l'activation xIELU

Apertus n'utilise pas la fonction d'activation que tout le reste utilise. Il
utilise **xIELU**, et ce seul fait date le support partout. Un moteur publié
avant l'arrivée de xIELU dans ses sources ne devient pas lent ou approximatif
sur Apertus — il **ne peut pas** le faire tourner. Soit il refuse le fichier
avec `unknown model architecture: apertus`, soit il le charge et produit du
charabia.

C'est pourquoi le menu **vérifie la version du moteur avant de télécharger
quoi que ce soit** — l'étape 5 sur 9, devant l'étape 7 qui pèse plusieurs
gigaoctets. Apprendre un numéro de version ne devrait pas coûter 5 Go de
trafic.

Où xIELU est arrivé :

- **llama.cpp** — construction `b6671` (processeur et CUDA dans le même
  changement).
- **Ollama** — `0.12.6`. **Aucune note de version ne le mentionne** ;
  chercher « xielu » dans le journal des versions ne donne rien, et seul un
  diff des sources embarquées le montre. Si le contrôle de version échoue sur
  un Ollama qui semble récent, c'est la raison.
- **vLLM** — `0.10.2`, parue avant que le modèle ne soit public.
- **LocalAI** — hérite du support de la llama.cpp qu'il embarque ; `4.0.0` est
  le plancher retenu par le menu.

Les autres dorsales ggml ont reçu xIELU après le processeur et CUDA : Vulkan,
puis Metal, puis SYCL/Intel. Une cible Intel Arc exige donc bien plus que
`b6671` — vérifiez la construction, pas le calendrier.

### Ce que chaque moteur coûte en pratique

- **Ollama** s'installe par le paquet de la distribution là où il existe, et
  par son script amont sinon ; il pose son propre service. C'est le seul des
  quatre dont le téléchargement émet un flux de progression lisible par
  machine, et c'est pourquoi l'écran d'installation peut afficher un vrai
  pourcentage pour lui, et seulement un compteur d'étapes pour les autres.
- **llama.cpp** s'installe par son installateur amont sous votre propre
  compte, sans droits d'administration. Les paquets de distribution sont
  fréquemment antérieurs à `b6671` — une distribution actuelle en livre encore
  `b5882` — et vous ne le découvririez qu'après avoir téléchargé les poids.
- **LocalAI** exige la forme d'URI `huggingface://`, parce que sa galerie ne
  contient aucune entrée Apertus. Son **premier** appel télécharge en plus une
  image OCI de dorsale de plusieurs gigaoctets ; c'est une étape à part
  entière, pas un pli de « démarrer le serveur ».
- **vLLM** est un moteur à GPU en pratique. Sa roue processeur exige le jeu
  d'instructions `avx512f` et un `LD_PRELOAD`, et une machine virtuelle au
  modèle de processeur par défaut n'expose souvent pas `avx512`. En bf16 les
  poids font 16,11 Go, ce qui fait de 24 Go de VRAM le vrai plancher ; une
  carte de 16 Go veut plutôt la version
  `RedHatAI/Apertus-8B-Instruct-2509-FP8-dynamic` (9,13 Go, Apache-2.0).

> ⚠️ **Le noyau CUDA xIELU fusionné n'est délibérément pas installé.** vLLM
> suggère de l'installer depuis un dépôt de sources qui ne porte **aucun
> fichier de licence**, ce qu'un projet AGPL-3.0+ ne peut pas livrer. Le repli
> en PyTorch pur est automatique et correct ; il coûte de la vitesse, rien
> d'autre.

<!-- [en] -->
## 5. Hardware — what it really takes

**No official VRAM or RAM figure is published for Apertus.** Everything below
is *derived*: from the sizes of the published files, and from the model's own
declared dimensions. Treat them as floors, not as certified requirements.

### Disk

The GGUF file sizes are the ones in section 3: **5.06 GB** for the 8B in
`Q4_K_M`, **8.57 GB** in `Q8_0`, about **1.2 GB** and **0.5 GB** for the two
Minis. The installer checks free space before downloading, and asks for the
model's size **plus a 2 GiB margin** — a download writes intermediate files,
and an engine writes a service file.

### Memory: the weights, plus the KV cache

The weights are the easy half: roughly the file size, once loaded.

The other half is the **KV cache**, which grows with the context and which no
one advertises. For the **8B**, it is exactly **128 KiB per token**:

```text
2 tensors (K and V)
  × 32 layers
  × 8 key/value heads
  × 128 head dimension
  × 2 bytes (fp16)
  = 131072 bytes = 128 KiB per token
```

Multiply that by the model's native context and the number stops being
academic:

| Context | KV cache for the 8B |
|---|---|
| 4096 tokens | 512 MiB |
| **8192 tokens** (the cap the menu applies) | **1 GiB** |
| **65536 tokens** (the model's native maximum) | **8 GiB** |

Accepting the native context therefore reserves **8 GiB on top of the
weights** — about 13 GB in total for a 5.06 GB `Q4_K_M`. That is how a machine
with plenty of room for the file still gets its engine killed the moment the
first question arrives.

**This is why the menu starts every engine with a capped context — 8192
tokens.** A model whose native context is already shorter keeps its own: a
Mini at 4096 tokens is served at 4096. If you need the full 65536, raise the
cap knowingly and budget the 8 GiB.

Reasonable derived floors, for the 8B in `Q4_K_M` at the 8192-token cap:
about **7 GB** of RAM (or VRAM) to serve it, and about **7.2 GB** of free disk
to install it. The Minis are an order of magnitude cheaper on both counts, and
that — not speed — is the reason to pick one on a small machine.

<!-- [fr] -->
## 5. Matériel — ce qu'il faut vraiment

**Aucun chiffre officiel de VRAM ni de RAM n'est publié pour Apertus.** Tout
ce qui suit est *dérivé* : de la taille des fichiers publiés, et des
dimensions déclarées du modèle. À traiter comme des planchers, pas comme des
exigences certifiées.

### Disque

Les tailles de fichiers GGUF sont celles de la section 3 : **5,06 Go** pour le
8B en `Q4_K_M`, **8,57 Go** en `Q8_0`, environ **1,2 Go** et **0,5 Go** pour
les deux Mini. L'installateur vérifie la place libre avant de télécharger, et
demande la taille du modèle **plus une marge de 2 Gio** — un téléchargement
écrit des fichiers intermédiaires, et un moteur écrit un fichier de service.

### Mémoire : les poids, plus le cache clé-valeur

Les poids sont la moitié facile : à peu près la taille du fichier, une fois
chargés.

L'autre moitié est le **cache clé-valeur**, qui croît avec le contexte et que
personne n'annonce. Pour le **8B**, il vaut exactement **128 Kio par
jeton** :

```text
2 tenseurs (K et V)
  × 32 couches
  × 8 têtes clé/valeur
  × 128 de dimension de tête
  × 2 octets (fp16)
  = 131072 octets = 128 Kio par jeton
```

Multipliez par le contexte natif du modèle et le nombre cesse d'être
théorique :

| Contexte | Cache clé-valeur du 8B |
|---|---|
| 4096 jetons | 512 Mio |
| **8192 jetons** (le plafond appliqué par le menu) | **1 Gio** |
| **65536 jetons** (le maximum natif du modèle) | **8 Gio** |

Accepter le contexte natif réserve donc **8 Gio par-dessus les poids** —
environ 13 Go au total pour un `Q4_K_M` de 5,06 Go. C'est ainsi qu'une machine
largement assez grande pour le fichier voit quand même son moteur tué dès que
la première question arrive.

**C'est pourquoi le menu lance chaque moteur avec un contexte plafonné —
8192 jetons.** Un modèle dont le contexte natif est déjà plus court garde le
sien : un Mini à 4096 jetons est servi à 4096. S'il vous faut les 65536
complets, relevez le plafond en connaissance de cause et prévoyez les 8 Gio.

Planchers dérivés raisonnables, pour le 8B en `Q4_K_M` au plafond de 8192
jetons : environ **7 Go** de RAM (ou de VRAM) pour le servir, et environ
**7,2 Go** de disque libre pour l'installer. Les Mini coûtent un ordre de
grandeur de moins sur les deux plans, et c'est cela — pas la vitesse — qui
justifie d'en prendre un sur une petite machine.

<!-- [en] -->
## 6. Installing through the menu

The whole installation is `TODO › Assistant › AI › Apertus`. The screen:

```text
🇨🇭 Apertus — the open LLM of the Swiss Confederation.
📍 TODO › Assistant › AI › Apertus
Command:

── 📖 Understand ──
[1] 📖 Guide — what Apertus is, and how to use it

── 🎯 Prepare ──
[2] 🎯 Target — the machine to install on  (here)
[3] ⚙️ Engine — how to serve the model  (Ollama)
[4] 🧠 Model — full 8B, or distilled Mini  (8B-Instruct-2509, Q4_K_M)

── 📦 Install ──
[5] 📦 Install  (never run)
[6] 🩺 Check and keep the server

── 💬 Use ──
[7] 💬 Chat with the model
[8] 🧹 Uninstall
[0] 🔙 Back
```

**[2] Target.** Three ways to designate a machine: here, a QEMU virtual
machine of this host, or a host from your `~/.ssh/config`. A remote target is
reached with `BatchMode` — the connection must already work without typing a
password, or the menu would appear frozen while `ssh` waits for one.

**[3] Engine** and **[4] Model** are the two choices of sections 3 and 4. Both
suffixes show the current value in parentheses, so the screen always says what
would be installed.

**[5] Install** prints a **full plan first**, then asks **once**:

```text
Target  : SSH server "<alias>"
Engine  : Ollama (MIT)
Model   : Apertus-8B-Instruct-2509, Q4_K_M — 5.06 GB
Space   : 7.2 GB needed, 41 GB free
Context : 8192 tokens (native 65536 capped — 8 GiB of KV cache otherwise)

Will execute:
  1. atteindre  ...
  ...
  9. repondre   ...

Run these 9 steps? (y/N)
```

The nine steps, in this order:

| # | Step | What it does |
|---|---|---|
| 1 | `atteindre` | is the target reachable at all |
| 2 | `sudo` | does `sudo` work without an interactive password |
| 3 | `place` | is there room for the model plus the 2 GiB margin |
| 4 | `paquet` | install the engine (skipped if its binary is already there) |
| 5 | `version` | **is the engine new enough for xIELU** |
| 6 | `service` | put the engine to listen |
| 7 | `tirer` | download the weights — the long one |
| 8 | `ecouter` | does the API answer on `/v1/models` |
| 9 | `repondre` | a real completion comes back |

The order is deliberate: **step 5 comes before step 7**. An engine that is too
old is caught before the gigabytes, not after.

Each step carries a completion test, so a second run skips what is already
done. An engine already installed does not get reinstalled; weights already
pulled do not get pulled again.

**If a step fails**, the run stops there, prints the step, its exit code and
the tail of its output, and records the progress. Coming back into **[5]**
then opens the resume screen instead of starting over:

```text
📍 TODO › Assistant › AI › Apertus › Resume

  ✅ 1 atteindre      ✅ 2 sudo        ✅ 3 place
  ✅ 4 paquet         ⛔ 5 version     ⬜ 6 service
  ⬜ 7 tirer          ⬜ 8 ecouter     ⬜ 9 repondre

  4/9 steps, 3 min 12 s elapsed, 2 attempts.

[1] ▶️ Resume at step 5
[2] 🔄 Start over
[3] 📜 See the full last output
[0] 🔙 Back
```

That progress lives in `~/.erplibre/apertus_install.json`, **outside the
repository** — one entry per target machine. It is written there and not in
the tree on purpose: a progress record names its machine, and everything in
the tree follows the repository upstream. Starting over resets that target's
progress while keeping the failure history, so the screen can still show what
went wrong last time.

**[6] Check and keep the server** probes the engine and, if it answers, offers
to keep it as the assistant's server — after which `Assistant › LLM` talks to
it like any other.

**[8] Uninstall** removes the weights and stops the service; it does **not**
remove the engine, which may well be serving other models. Because it is
irreversible, it asks you to **retype the target's name in full** — a "yes" is
given by reflex, retyping makes you look at which machine you are emptying.

You can pick how progress is displayed with the `apertus_progress` preference:
`ask`, `tui` or `cli`. Both renderings describe the same state; the TUI simply
draws it.

<!-- [fr] -->
## 6. Installer par le menu

Toute l'installation est dans `TODO › Assistant › IA › Apertus`. L'écran :

```text
🇨🇭 Apertus — le LLM ouvert de la Confédération suisse.
📍 TODO › Assistant › IA › Apertus
Commande :

── 📖 Comprendre ──
[1] 📖 Guide — ce qu'est Apertus, et comment s'en servir

── 🎯 Préparer ──
[2] 🎯 Cible — la machine où installer  (ici)
[3] ⚙️ Moteur — comment servir le modèle  (Ollama)
[4] 🧠 Modèle — 8B complet, ou Mini distillé  (8B-Instruct-2509, Q4_K_M)

── 📦 Installer ──
[5] 📦 Installer  (jamais lancé)
[6] 🩺 Vérifier et retenir le serveur

── 💬 Utiliser ──
[7] 💬 Discuter avec le modèle
[8] 🧹 Désinstaller
[0] 🔙 Retour
```

**[2] Cible.** Trois façons de désigner une machine : ici, une machine
virtuelle QEMU de cet hôte, ou un hôte de votre `~/.ssh/config`. Une cible
distante est jointe en `BatchMode` — la connexion doit déjà fonctionner sans
mot de passe à taper, sinon le menu paraîtrait figé pendant que `ssh` en
attend un.

**[3] Moteur** et **[4] Modèle** sont les deux choix des sections 3 et 4. Les
deux suffixes montrent la valeur courante entre parenthèses : l'écran dit
toujours ce qui serait installé.

**[5] Installer** imprime **d'abord le plan complet**, puis demande **une
seule** confirmation :

```text
Cible    : serveur SSH « <alias> »
Moteur   : Ollama (MIT)
Modèle   : Apertus-8B-Instruct-2509, Q4_K_M — 5,06 Go
Place    : 7,2 Go requis, 41 Go libres
Contexte : 8192 jetons (natif 65536 plafonné — 8 Gio de cache KV sinon)

Will execute:
  1. atteindre  ...
  ...
  9. repondre   ...

Lancer ces 9 étapes ? (o/N)
```

Les neuf étapes, dans cet ordre :

| # | Étape | Ce qu'elle fait |
|---|---|---|
| 1 | `atteindre` | la cible est-elle seulement joignable |
| 2 | `sudo` | `sudo` marche-t-il sans mot de passe interactif |
| 3 | `place` | y a-t-il la place du modèle plus la marge de 2 Gio |
| 4 | `paquet` | installe le moteur (sautée si son binaire est déjà là) |
| 5 | `version` | **le moteur est-il assez récent pour xIELU** |
| 6 | `service` | met le moteur à écouter |
| 7 | `tirer` | télécharge les poids — la longue |
| 8 | `ecouter` | l'API répond-elle sur `/v1/models` |
| 9 | `repondre` | une vraie complétion revient |

L'ordre est délibéré : **l'étape 5 précède l'étape 7**. Un moteur trop ancien
est attrapé avant les gigaoctets, pas après.

Chaque étape porte un test de complétion : un deuxième passage saute ce qui
est déjà fait. Un moteur déjà installé n'est pas réinstallé, des poids déjà
tirés ne sont pas retirés.

**Si une étape échoue**, la séquence s'arrête là, imprime l'étape, son code de
retour et la fin de sa sortie, puis enregistre la progression. Revenir dans
**[5]** ouvre alors l'écran de reprise au lieu de tout recommencer :

```text
📍 TODO › Assistant › IA › Apertus › Reprise

  ✅ 1 atteindre      ✅ 2 sudo        ✅ 3 place
  ✅ 4 paquet         ⛔ 5 version     ⬜ 6 service
  ⬜ 7 tirer          ⬜ 8 ecouter     ⬜ 9 repondre

  4/9 étapes, 3 min 12 s écoulées, 2 tentatives.

[1] ▶️ Reprendre à l'étape 5
[2] 🔄 Tout recommencer
[3] 📜 Voir la dernière sortie complète
[0] 🔙 Retour
```

Cette progression vit dans `~/.erplibre/apertus_install.json`, **hors du
dépôt** — une entrée par machine cible. Elle est écrite là et non dans
l'arborescence exprès : une progression nomme sa machine, et tout ce qui est
dans l'arborescence suit le dépôt en amont. Tout recommencer remet à zéro la
progression de cette cible en gardant l'historique des échecs, pour que
l'écran puisse encore montrer ce qui a cassé la dernière fois.

**[6] Vérifier et retenir le serveur** sonde le moteur et, s'il répond,
propose de le retenir comme serveur de l'assistant — après quoi
`Assistant › LLM` lui parle comme à n'importe quel autre.

**[8] Désinstaller** retire les poids et arrête le service ; il ne retire
**pas** le moteur, qui sert peut-être d'autres modèles. Parce que c'est
irréversible, il demande de **retaper le nom de la cible en entier** — un
« oui » se donne par réflexe, le retaper oblige à regarder quelle machine on
vide.

L'affichage de la progression se choisit par la préférence
`apertus_progress` : `ask`, `tui` ou `cli`. Les deux rendus décrivent le même
état ; la TUI ne fait que le dessiner.

<!-- [en] -->
## 7. Using it

### From the menu

`[7] Chat with the model` opens the conversation, and the answer arrives token
by token rather than in one block at the end. The usual commands of the CLI's
conversation apply — `/save` to keep a transcript, `/ctx` to see where the
context stands, `/new` to start a fresh thread.

The history lives in memory and nowhere else. It dies with the menu, and
`/save` is the only way to keep a trace.

### From your own code

Every engine serves the same OpenAI-compatible API, so anything that speaks to
a hosted model speaks to this one by changing the base URL. With Ollama on the
default port:

```bash
curl -fsS http://127.0.0.1:11434/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "hf.co/unsloth/Apertus-8B-Instruct-2509-GGUF:Q4_K_M",
    "messages": [{"role": "user", "content": "Explain an Odoo manifest."}]
  }'
```

Two things change from one engine to another, and only two: the **port** (see
the table in section 4) and the string to put in `"model"`. Ollama wants the
`hf.co/<repository>:<quantization>` bridge form, LocalAI wants a
`huggingface://` URI, llama.cpp wants the GGUF file, and vLLM wants the
upstream repository name. `GET /v1/models` on the running engine always tells
you which string it accepts.

No API key is required on a local engine. If a client library demands one, any
non-empty string does.

<!-- [fr] -->
## 7. S'en servir

### Depuis le menu

`[7] Discuter avec le modèle` ouvre la conversation, et la réponse arrive
jeton par jeton plutôt qu'en un bloc à la fin. Les commandes habituelles de la
conversation du CLI s'appliquent — `/save` pour garder une trace, `/ctx` pour
voir où en est le contexte, `/new` pour repartir d'un fil neuf.

L'historique vit en mémoire et nulle part ailleurs. Il meurt avec le menu, et
`/save` est le seul moyen d'en garder une trace.

### Depuis votre propre code

Tous les moteurs servent la même API compatible OpenAI : ce qui parle à un
modèle hébergé parle à celui-ci en changeant l'URL de base. Avec Ollama sur le
port par défaut :

```bash
curl -fsS http://127.0.0.1:11434/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "hf.co/unsloth/Apertus-8B-Instruct-2509-GGUF:Q4_K_M",
    "messages": [{"role": "user", "content": "Explique un manifeste Odoo."}]
  }'
```

Deux choses changent d'un moteur à l'autre, et deux seulement : le **port**
(voir le tableau de la section 4) et la chaîne à mettre dans `"model"`. Ollama
veut la forme de pont `hf.co/<dépôt>:<quantification>`, LocalAI veut une URI
`huggingface://`, llama.cpp veut le fichier GGUF, et vLLM veut le nom du dépôt
amont. `GET /v1/models` sur le moteur en marche dit toujours quelle chaîne il
accepte.

Aucune clé d'API n'est nécessaire sur un moteur local. Si une bibliothèque
cliente en exige une, n'importe quelle chaîne non vide fait l'affaire.

<!-- [en] -->
## 8. What is NOT official

This is the honest core of the guide. The model is official; **the path this
menu takes to run it is partly not**, and you should know exactly where the
seam is.

**There is no official GGUF. At all.** The `swiss-ai` organisation publishes
two dozen repositories and not one `.gguf` file. Official quantizations exist
only for MLX and for vLLM. Every path through Ollama, llama.cpp or LocalAI
therefore depends on a **community quantizer**. The menu only offers
repositories that declare their licence — an `apache-2.0` field that is filled
in, rather than left empty — because licence hygiene is not optional in an
AGPL-3.0+ project. Apertus's own documentation points at community builds and
says, in as many words, that the team cannot support them directly.

**`ollama pull apertus` does not work.** Apertus is not in Ollama's official
library; the request to add it has been open for a long time. The bare name
404s. The menu uses the HuggingFace bridge form
`hf.co/<repository>:<quantization>` instead, which is why the model string
looks longer than the ones in Ollama's documentation.

**The LocalAI gallery contains zero Apertus entries.** Its `index.yaml` holds
more than fifteen hundred models and not one of them matches. `local-ai run
apertus` fails; the `huggingface://` URI is mandatory, not a preference.

**`apertus.click` is not the Apertus project.** It is an unaffiliated
marketing landing page. It serves no model, no API and no download, and it is
not operated by EPFL, ETH Zurich or the CSCS. This guide deliberately does not
link it. The real site is **`apertus-ai.org`**, and the weights are under
`huggingface.co/swiss-ai`. If a search engine sends you to the other one, you
are in the wrong place.

What this adds up to: the **weights** and the **licence** are official and
verifiable; the **GGUF conversion**, the **Ollama reference** and the
**LocalAI URI** are community plumbing that the menu picks for you and that
you are free to replace.

<!-- [fr] -->
## 8. Ce qui n'est PAS officiel

C'est le cœur honnête de ce guide. Le modèle est officiel ; **le chemin que ce
menu prend pour le faire tourner ne l'est qu'en partie**, et il faut savoir
exactement où est la couture.

**Il n'existe aucun GGUF officiel. Aucun.** L'organisation `swiss-ai` publie
deux douzaines de dépôts et pas un fichier `.gguf`. Les quantifications
officielles n'existent que pour MLX et pour vLLM. Tout chemin passant par
Ollama, llama.cpp ou LocalAI dépend donc d'un **quantificateur
communautaire**. Le menu ne propose que des dépôts qui déclarent leur licence
— un champ `apache-2.0` rempli, plutôt que laissé vide — parce que l'hygiène
de licence n'est pas facultative dans un projet AGPL-3.0+. La documentation
d'Apertus pointe elle-même vers des versions communautaires et dit, en toutes
lettres, que l'équipe ne peut pas les supporter directement.

**`ollama pull apertus` ne marche pas.** Apertus n'est pas dans la
bibliothèque officielle d'Ollama ; la demande de l'y ajouter est ouverte
depuis longtemps. Le nom nu répond 404. Le menu utilise à la place la forme de
pont HuggingFace `hf.co/<dépôt>:<quantification>`, et c'est pourquoi la chaîne
de modèle est plus longue que celles de la documentation d'Ollama.

**La galerie LocalAI ne contient aucune entrée Apertus.** Son `index.yaml`
porte plus de quinze cents modèles et pas un seul ne correspond. `local-ai run
apertus` échoue ; l'URI `huggingface://` est obligatoire, pas une préférence.

**`apertus.click` n'est pas le projet Apertus.** C'est une page
d'atterrissage marketing non affiliée. Elle ne sert ni modèle, ni API, ni
téléchargement, et elle n'est opérée ni par l'EPFL, ni par l'ETH Zurich, ni
par le CSCS. Ce guide ne la lie délibérément pas. Le vrai site est
**`apertus-ai.org`**, et les poids sont sous `huggingface.co/swiss-ai`. Si un
moteur de recherche vous envoie vers l'autre, vous êtes au mauvais endroit.

Ce que cela donne au total : les **poids** et la **licence** sont officiels et
vérifiables ; la **conversion GGUF**, la **référence Ollama** et l'**URI
LocalAI** sont de la plomberie communautaire, que le menu choisit pour vous et
que vous êtes libre de remplacer.

<!-- [en] -->
## 9. Troubleshooting

### `unknown model architecture: apertus`

The engine is **too old**. It does not know the xIELU activation, and no
option, no flag and no re-download will change that. Check the version against
the table in section 4 and upgrade the engine:

```bash
ollama --version          # needs 0.12.6 or newer
llama-server --version    # needs build b6671 or newer
local-ai --version        # needs 4.0.0 or newer
```

On llama.cpp in particular, a distribution package is often the culprit: some
current distributions still ship a build older than `b6671`. Install from the
upstream installer instead, which puts a recent binary under your own account.

The menu catches this at step 5, before any download. Seeing the message means
the engine was installed or upgraded outside the menu.

### Special tokens leak into the replies

Answers that contain `<|assistant_start|>`, `<|user_start|>`,
`<|system_start|>` or similar markers mean the **chat template is not being
applied**. Apertus uses an unusual template, with a mandatory developer block;
when the engine falls back to a generic template, the model's own control
tokens end up in the visible text.

The fix is on the engine side, not the model's: make sure it applies the
template shipped with the weights — for llama.cpp, that is the `--jinja`
switch, which the menu passes. A raw completion endpoint bypasses the template
by design; use the chat endpoint (`/v1/chat/completions`).

### The engine is killed (out of memory)

Almost always the **context**. The 8B declares 65536 tokens, and the KV cache
for that is 8 GiB on top of the weights (section 5). A machine with room for
the file gets killed at the first question.

Cap the context. The menu serves at 8192 tokens for exactly this reason; if
you are launching an engine by hand, pass the equivalent option —
`--ctx-size` for llama.cpp, `--max-model-len` for vLLM, `num_ctx` for Ollama —
and keep it at 8192 unless you have measured that you can afford more.

A second suspect, if the context is already capped: a quantization that is too
large for the machine. `Q8_0` is 8.57 GB against 5.06 GB for `Q4_K_M`, for a
difference in quality most uses will not notice.

### The install seems frozen on a remote target

A remote step runs under `BatchMode`, where a password prompt waits invisibly.
If a host needs an interactive `sudo` password, step 2 says so and stops
there. If the freeze happens earlier, the SSH connection itself is asking for
something: make `ssh <target> true` work without typing anything, then come
back.

### A download that says nothing for minutes

Normal. Pulling several gigabytes can stay silent for a long while; only
Ollama exposes a real progress stream, and the other three can only be shown
as a step counter and an elapsed time. The screen marks a long silence rather
than inventing a progress bar.

<!-- [fr] -->
## 9. Dépannage

### `unknown model architecture: apertus`

Le moteur est **trop ancien**. Il ne connaît pas l'activation xIELU, et aucune
option, aucun drapeau et aucun re-téléchargement n'y changera rien. Comparez
la version au tableau de la section 4 et mettez le moteur à jour :

```bash
ollama --version          # exige 0.12.6 ou plus récent
llama-server --version    # exige la construction b6671 ou plus récente
local-ai --version        # exige 4.0.0 ou plus récent
```

Sur llama.cpp en particulier, un paquet de distribution est souvent le
coupable : certaines distributions actuelles livrent encore une construction
antérieure à `b6671`. Installez plutôt par l'installateur amont, qui pose un
binaire récent sous votre propre compte.

Le menu attrape ce cas à l'étape 5, avant tout téléchargement. Voir le message
signifie que le moteur a été installé ou mis à jour hors du menu.

### Des jetons spéciaux fuient dans les réponses

Des réponses qui contiennent `<|assistant_start|>`, `<|user_start|>`,
`<|system_start|>` ou des marqueurs semblables signifient que le **gabarit de
conversation n'est pas appliqué**. Apertus utilise un gabarit inhabituel, avec
un bloc développeur obligatoire ; quand le moteur se rabat sur un gabarit
générique, les jetons de contrôle du modèle finissent dans le texte visible.

Le correctif est du côté du moteur, pas du modèle : assurez-vous qu'il
applique le gabarit livré avec les poids — pour llama.cpp, c'est l'option
`--jinja`, que le menu passe. Un point d'entrée de complétion brute contourne
le gabarit par construction ; utilisez celui de conversation
(`/v1/chat/completions`).

### Le moteur est tué (mémoire épuisée)

Presque toujours le **contexte**. Le 8B déclare 65536 jetons, et le cache
clé-valeur correspondant fait 8 Gio par-dessus les poids (section 5). Une
machine qui a la place du fichier se fait tuer à la première question.

Plafonnez le contexte. Le menu sert à 8192 jetons exactement pour cette
raison ; si vous lancez un moteur à la main, passez l'option équivalente —
`--ctx-size` pour llama.cpp, `--max-model-len` pour vLLM, `num_ctx` pour
Ollama — et gardez 8192 tant que vous n'avez pas mesuré que vous pouvez vous
offrir davantage.

Deuxième suspect, si le contexte est déjà plafonné : une quantification trop
grosse pour la machine. `Q8_0` fait 8,57 Go contre 5,06 Go pour `Q4_K_M`, pour
un écart de qualité que la plupart des usages ne remarqueront pas.

### L'installation semble figée sur une cible distante

Une étape distante tourne en `BatchMode`, où une demande de mot de passe
attend sans rien afficher. Si un hôte exige un mot de passe `sudo` interactif,
l'étape 2 le dit et s'arrête là. Si le blocage survient plus tôt, c'est la
connexion SSH elle-même qui demande quelque chose : faites marcher
`ssh <cible> true` sans rien taper, puis revenez.

### Un téléchargement muet pendant plusieurs minutes

Normal. Tirer plusieurs gigaoctets peut rester silencieux un bon moment ; seul
Ollama expose un vrai flux de progression, et les trois autres ne peuvent être
montrés que par un compteur d'étapes et un temps écoulé. L'écran signale un
long silence plutôt que d'inventer une barre de progression.
