
# LLM ouverts — le relevé, et sa date de péremption

Ce guide décrit les modèles à poids ouverts qu'on peut faire tourner sur une
machine qui vous appartient, et les moteurs qui les servent. C'est la version
longue de ce que `TODO › Assistant › IA › Modèles ouverts` montre en un
écran.

Ses tableaux ne sont pas tapés ici : ils sont **générés** depuis
`script/todo/assistant/panorama.py`, qui fait autorité. Un tableau recopié à la
main dérive de la donnée qu'il prétend rendre, et c'est dans la documentation
que la dérive se voit le moins — personne ne relit un tableau de chiffres pour
vérifier qu'il dit encore vrai.

## 1. Ce que c'est, et quand ça périme

**Ce relevé a été fait le 13 septembre 2026** (`2026-09-13`)**.** Cette date est `DATE_RELEVE`
dans le module, et c'est la première chose à lire, avant tout chiffre placé en
dessous.

Un catalogue de modèles périme en semaines, pas en années. La preuve est dans
le relevé lui-même : `DeepSeek-V4.1-Flash`, qui prend le rang 1 du classement
de codage indépendant cité en section 6, a été publié **trois jours avant** le
relevé. Trois jours plus tôt, le haut de ce guide nommait un autre modèle.

C'est pourquoi le menu **affiche l'âge du relevé au lieu de le taire**.
L'entrée porte le nombre de jours, puis un verdict :

| Âge du relevé | Ce que dit le menu |
|---|---|
| 0 à 45 jours | ✅ relevé frais |
| 46 à 120 jours | ⚠️ relevé à relire |
| au-delà de 120 jours | ⛔ relevé périmé — vérifier avant de s'y fier |

Les deux seuils sont `AGE_TIEDE` et `AGE_FROID`, et ils sont courts exprès :
entre deux générations d'un même modèle il se passe parfois six semaines.

**Si vous lisez ceci au-delà de ces seuils, croyez les sources d'origine
plutôt que ces tableaux.** Le dépôt de l'éditeur — son `config.json`, la taille
de ses fichiers, son fichier de licence — est ce qui reste vrai. Une carte de
modèle dit ce qu'un modèle est aujourd'hui ; ce guide dit ce qu'il était le
jour du relevé. Quand les deux divergent, c'est le guide qui a tort.

Deux avertissements de plus tiennent ici plutôt que plus bas.

**Aucun chiffre officiel de RAM ni de VRAM n'est publié pour aucun de ces
modèles**, ni par les cartes de modèles, ni par les sites des projets. Toute
valeur matérielle de ce guide est *dérivée* : de tailles de fichiers vérifiées,
des dimensions que les modèles déclarent eux-mêmes, et d'une règle « taille de
la quantification plus une à deux marges de gigaoctet » énoncée par un
quantificateur communautaire. Ce sont des estimations, jamais des
spécifications d'éditeur, et ce guide le redit chaque fois que ça compte.

**La couche d'optimisation pour moteurs de recherche est activement trompeuse
sur ce sujet.** Un tour d'horizon très repris, consulté pendant le relevé,
donne à un modèle un contexte d'un million là où sa propre configuration dit
262 144, en qualifie un autre de « Modified MIT » là où l'étiquette de la
plateforme de publication dit `license:other`, invente un modèle qui n'existe
pas, et cite une taille en 4 bits fausse de cent gigaoctets. Traitez ce genre
de synthèse comme une piste à vérifier, jamais comme une donnée.

## 2. Comment lire les tableaux

Trois idées rendent utilisable tout le reste de ce guide. Chacune est de
l'arithmétique, et chacune contredit quelque chose qui se dit couramment sur
les modèles.

### 2.1 Le cache clé-valeur, et pourquoi c'est la colonne la plus utile

Servir un modèle coûte les poids **plus** un cache qui croît avec la
conversation. Personne ne l'annonce, et au-delà d'une certaine longueur de
contexte il est plus gros que le modèle lui-même.

Pour un modèle à attention groupée ordinaire, le cache coûte, par jeton :

```text
2 (K et V)
  × le nombre de couches à ATTENTION PLEINE
  × kv_heads
  × head_dim
  × 2 octets (fp16 ou bf16)
```

Deux pièges vivent dans cette formule.

**Seules les couches à attention pleine comptent.** Un modèle hybride dont les
autres couches sont à attention linéaire ou à espace d'états n'y cache rien.
Multiplier par le nombre total de couches est la façon la plus répandue de se
tromper ici — pour un modèle du tableau, cela gonflerait le chiffre d'un
facteur onze.

**Un modèle à attention latente (MLA) n'a pas le facteur deux.** Son cache est
un seul vecteur latent compressé par couche, plus les dimensions rotatives,
donc :

```text
couches × (kv_lora_rank + qk_rope_head_dim) × 2 octets
```

Appliquer la formule ordinaire à un modèle MLA se trompe deux fois : elle
double le latent et elle ignore les dimensions RoPE qu'il faut aussi cacher.

Ce que cela donne, concrètement : Apertus-8B coûte 2 × 32 × 8 × 128 × 2 =
131 072 octets, exactement **128 Kio par jeton**, donc sa fenêtre native de
65 536 jetons vaut **8 Gio de cache par-dessus les poids**. Un MoE du tableau
coûte 48,4 Kio par jeton dans sa forme latente ; un autre, à trente-deux têtes
clé-valeur, coûte **576 Kio par jeton** — vingt-quatre fois plus — et à un
million de jetons cela fait 549,3 Gio de cache, plus du double de ce que deux
grosses machines tiennent ensemble.

**À un million de jetons, le cache est généralement plus gros que les poids.**
Le cas le plus net du tableau est un modèle de quatre milliards de paramètres :
7,5 Gio de poids contre 30,5 Gio de cache. Le cache vaut quatre fois le modèle.

### 2.2 Ce sont les paramètres ACTIFS, pas le total, qui décident du débit

Décoder un jeton, c'est lire en mémoire les paramètres qu'il active. Le
plafond est donc arithmétique :

```text
jetons par seconde ≤ bande passante mémoire ÷ octets lus par jeton
```

Sur une machine à 273 Go/s de bande passante, un modèle **dense** de soixante-
dix milliards quantifié en 4 bits lit environ 40 Go par jeton, ce qui le
plafonne à 6,8 jetons par seconde, et 4 à 5 en pratique. Un **mélange
d'experts** de 229 G au total dont seulement 10 G actifs ne lit qu'une fraction
de lui-même, et son plafond avoisine 58 jetons par seconde — un ordre de
grandeur d'écart, et c'est le modèle creux qui est le *plus gros* sur disque.

Donc : **filtrer sur les paramètres actifs, jamais sur le total, et jamais sur
« ça rentre »**. La colonne `Paramètres` du tableau donne les deux dès qu'ils
diffèrent, et c'est le chiffre actif qui prédit la latence.

Les plafonds de ce guide sont théoriques. Une mesure les ancre : un MoE de cent
vingt milliards à 5,1 G actifs a été mesuré à **60,57 jetons par seconde** en
décodage et 1 956 jetons par seconde en préremplissage, soit **61 % de son
propre plafond théorique** de 99,4. Toute estimation de débit ici est le
plafond ramené dans cette bande, et elle est donc dérivée — pas un chiffre
publié.

### 2.3 La longueur de contexte n'est pas une fonction de la taille

C'est l'idée qui surprend, et le tableau la rend visible.

Un modèle **dense de 4 G** documente 1 010 000 jetons. Un modèle **dense de
70 G** s'arrête à 65 536. Le petit gagne parce que seules **8 de ses 32
couches** sont à attention pleine, donc son cache croît quatre fois moins
vite ; le gros paie ses 80 couches à chaque jeton. Un autre modèle du tableau
ne garde que **6 couches d'attention sur 52** et porte le cache le moins cher
relevé — 6 Kio par jeton, 5,7 Gio pour un million de jetons.

Ce qui fixe réellement une longueur de contexte, c'est (a) l'encodage
positionnel — la base RoPE, l'interpolation YaRN ou NTK, les couches sans
encodage positionnel du tout — et (b) la disposition de l'attention, qui décide
si le cache croît avec les jetons. Ni l'un ni l'autre ne lit le nombre de
paramètres.

### 2.4 La convention de la colonne « Contexte »

La colonne `Contexte` ne porte aucun mot, dans aucune des deux langues, parce
que le tableau est généré une fois pour les deux. Un contexte décrit comme
« natif » ou « conseillé » s'afficherait en français au lecteur anglophone. La
convention est donc faite de symboles :

| Ce qui est imprimé | Ce que ça veut dire |
|---|---|
| `65 536` | le natif, nu |
| `262 144 → 1,01 M YaRN` | natif, puis ce qu'une extrapolation atteint |
| `1 048 576 ⚑ 300 K` | le drapeau marque ce que l'éditeur conseille vraiment |
| `262 144 (config)` | seul le fichier de configuration l'affirme |

La distinction n'est pas cosmétique, et deux faits la justifient.

**Un contexte extrapolé se dégrade bien avant sa limite.** Un banc d'essai
indépendant de contexte long, qui évalue 26 modèles sur huit tranches de 8 K à
1 M, mesure une décroissance relative moyenne de **24,3 %** entre la portée
8K-128K et la portée 8K-1M. Le meilleur modèle perd 8,5 %, le pire 60,5 %, et
sept modèles sur 26 changent de rang quand la portée s'étend — avec des
intervalles de confiance de 1 à 2 points contre des écarts de 5 à 16, ce n'est
pas du bruit.

**Un éditeur a déjà retiré par écrit une annonce d'un million que sa propre
configuration contredisait.** Sur une famille de modèles, un membre de son
personnel écrit mot pour mot : « sorry for the confusion on 1M context, we will
fix documentation ». La configuration dit 262 144, le README dit 128 K en
entrée plus 128 K en sortie, le rapport technique dit 1 M, et la limite
observée sur l'API hébergée du même éditeur est de 131 072 jetons, avec un
rappel complet jusqu'à 128 K puis dégradation. Quand un marqueur `(config)`
apparaît dans la colonne, c'est de cette classe de situation qu'il prévient.

Une dernière conséquence, à dire franchement : **un million de jetons est une
capacité, pas une fenêtre de travail**. Le même banc d'essai montre que
supprimer entièrement sa tranche de 1 M économise 54,5 % du budget de jetons
tout en conservant un rho de Spearman de 0,997 contre le classement complet.
Des sources secondaires situent la fenêtre utile en production entre 200 et
400 K, et la capacité effective est couramment citée à 60-70 % de la fenêtre
annoncée.

## 3. Les moteurs

Un moteur est le programme qui charge les poids et les sert sur une API HTTP.
Cinq sont décrits ici ; deux autres sont nommés en fin de section parce que le
relevé n'a **pas** su les décrire.

| Nom | Licence | Port | API | Formats | Plateformes | Minimum Apertus |
|---|---|---|---|---|---|---|
| Ollama | MIT | 11434 | /v1 + /api | GGUF | Linux, macOS, Windows | 0.12.6 |
| llama.cpp | MIT | 8080 | /v1 + /health | GGUF, NVFP4, MXFP4 | CPU, CUDA, Vulkan, Metal, SYCL, ROCm | b6671 |
| mlx-lm (MLX) | MIT | 8080 | /v1 + /health | safetensors MLX INT2-INT6 | Apple Silicon | 0.27.1 |
| LocalAI | MIT | 8080 | /v1 + /api + /readyz | GGUF + safetensors (via backends) | Linux x86_64, ARM64 | — |
| vLLM | Apache-2.0 | 8000 | /v1 + /health + /version | safetensors bf16, FP8, NVFP4, int4 | Linux + CUDA, CPU avx512 | 0.10.2 |

**La colonne `Formats` est la décisive.** Elle dit quels dépôts de poids sont
seulement utilisables, et c'est elle qui écarte un modèle bien plus souvent que
la mémoire disponible. Un moteur qui ne mange que du GGUF ne peut pas charger
les safetensors officiels ; un moteur qui ne mange que des safetensors ne peut
pas charger un GGUF communautaire.

### Pourquoi il y a une version minimale : l'activation xIELU

Apertus n'utilise pas la fonction d'activation que tout le reste utilise. Il
utilise **xIELU**, et ce seul fait date le support dans chaque moteur. Un
moteur publié avant l'arrivée de xIELU dans ses sources ne devient pas lent ou
approximatif sur Apertus — il **ne peut pas** le faire tourner. Soit il refuse
le fichier avec `unknown model architecture: apertus`, soit il le charge et
émet du bruit.

En dessous du minimum, **le téléchargement réussit et seule l'inférence
échoue**. Vérifiez la version avant de dépenser cinq gigaoctets de trafic, pas
après.

La colonne `Minimum Apertus` ne vaut que pour la famille Apertus. Pour tout
autre modèle de la section 4, le plancher est la version qui a ajouté cette
architecture-là, et le relevé ne la consigne pas.

### Ollama

S'installe par le paquet de la distribution là où il existe, et par le binaire
officiel sinon ; il n'y a aucun paquet source dans les deux plus grosses
distributions de la famille Debian, donc c'est une archive ou un dépôt tiers
là-bas. Il pose son propre service.

**GGUF uniquement** — ce qui inclut désormais le GGUF en MXFP4 et en NVFP4,
mais jamais les safetensors FP8 ni NVFP4. Les safetensors MLX ne passent que
par une compilation personnalisée, hors de la publique.

**Minimum 0.12.6**, du 15 octobre 2025, et ce numéro a été établi **par un diff
de sources, pas par des notes de version** : la balise 0.12.5 ne contient
aucune occurrence d'« apertus » ni de « xielu », 0.12.6 en contient deux et
trois, et c'est le rafraîchissement de la llama.cpp embarquée qui apporte
l'activation. Aucune note de version entre 0.12.3 et 0.34.0 ne mentionne
Apertus : chercher dans le journal des changements ne dit rien.

*Forces.* Le chemin le plus court : une commande, et le pont
`hf.co/<dépôt>:<quant>` ouvre tous les GGUF communautaires sans catalogue à
tenir. C'est aussi le seul moteur de cette liste à **annoncer ses capacités** —
`POST /api/show` rapporte les outils, la vision et la longueur de contexte — et
le seul à exposer le téléchargement en HTTP (`POST /api/pull`), donc à pouvoir
être piloté sans shell.

*Faiblesses et pièges.* **`ollama pull apertus` renvoie 404.** Apertus n'est pas
dans la bibliothèque officielle ; la demande de l'y ajouter est ouverte depuis
le 2 septembre 2025 et deux autres tickets sont ouverts à côté. Le guide
d'Apertus lui-même renvoie vers un dépôt communautaire en avertissant, en
toutes lettres, que l'équipe ne peut pas supporter directement les versions
communautaires — et le gabarit de discussion de ce dépôt est annoncé
« intentionally basic », donc pas à parité avec le Jinja officiel pour les
outils et le multilingue. Il n'y a **aucun partage d'un modèle entre
machines** : les deux tickets amont sont toujours ouverts, et les enrobages
tiers ne répliquent que des modèles entiers. Dernier piège : ses blobs GGUF de
modèles à mélange d'experts ne sont pas relisibles par la llama.cpp amont — les
experts sont empaquetés par groupes de quatre — ce qui est sans effet sur
Apertus, qui est dense, mais mord quand les deux moteurs partagent un magasin.

### llama.cpp

S'installe par son script amont — 225 lignes de shell POSIX — qui pose le
binaire sous votre propre compte et une copie dans `~/.local/bin`, **sans
droits d'administration**, à condition que ce répertoire soit dans votre
`PATH`. Des paquets existent dans une distribution à publication continue et
dans les versions de développement et récentes de la famille Debian.

**GGUF uniquement**, mais cela couvre désormais `NVFP4` et `MXFP4` à côté de
`Q2_K`…`Q8_0` et de `BF16`. Aucun safetensors FP8 ni NVFP4.

**Minimum construction `b6671`**, du 2 octobre 2025 : `b6670`, du même jour, ne
l'a pas, et l'équipe qui publie le modèle conseille `b6686` ou plus récent. En
dessous, le message est `error loading model architecture: unknown model
architecture: apertus`.

*Forces.* C'est le seul moteur d'ici qui s'installe sans droits
d'administration. Le binaire est unifié — `llama serve`, `llama cli`,
`llama bench` — et `--jinja` est maintenant actif par défaut, donc le gabarit
de discussion embarqué dans le GGUF s'applique tout seul, ce qui est exactement
le piège que pose Apertus. C'est aussi le chemin 4 bits le plus sûr pour un
modèle de 70 G : un seul fichier `Q4_K_M` de 43,7 Go, là où `Q6_K` à 57,9 Go
arrive en morceaux à réassembler.

*Faiblesses et pièges.* **Il n'existe aucun binaire préconstruit pour Linux sur
ARM avec CUDA.** Une publication actuelle offre une construction ARM64 pour
processeur, une ARM64 Vulkan et une Windows ARM64 CUDA, et rien d'autre : sur
une machine ARM à GPU NVIDIA, on compile. **Un paquet de distribution est
fréquemment antérieur au minimum** — une version d'une distribution très
répandue livre encore `b5882`, antérieur au support d'Apertus, et l'échec
arrive *après* cinq gigaoctets téléchargés ; la version stable d'une autre n'a
aucun paquet du tout. **xIELU n'est pas sur toutes les dorsales depuis la
construction minimale** : le processeur et CUDA l'ont eu le 2 octobre 2025,
mais WebGPU le 5 décembre 2025, Vulkan le 21 décembre 2025, Metal le 14 avril
2026 et la voie Intel le 15 juillet 2026 — une cible Intel exige donc bien plus
que `b6671` ; vérifiez la construction, pas le calendrier. Son **dos à dos
réseau est en TCP nu, sans RDMA, et ralentit quand on ajoute des machines** :
20,4, puis 17,2, puis 15,2 jetons par seconde à un, deux et quatre nœuds sur un
gros modèle. Et **le convertisseur a déménagé** : la classe de modèle Apertus
vit maintenant dans `conversion/llama.py`, plus dans `convert_hf_to_gguf.py`,
devenu une coquille de 312 lignes — un grep au mauvais endroit conclut à tort
que le modèle n'est pas pris en charge.

Sur le silicium NVIDIA récent, construire avec `-DGGML_NATIVE=ON` et une
architecture CUDA en `native` échoue, et le fichier de construction du projet
le dit lui-même ; passez l'architecture explicitement, avec un compilateur
CUDA 13.x. Enfin, deux séries de versions coexistent en amont — les
constructions `bNNNNN` et un versionnage sémantique parallèle — et le relevé
n'établit pas la correspondance entre les deux.

### mlx-lm (MLX)

S'installe par `pip install mlx-lm`, ou depuis un commit git épinglé.

**safetensors quantifiés MLX uniquement** — INT2, INT3, INT4, INT6 — produits
par `mlx_lm.convert`. Cela compte pour Apertus plus que partout ailleurs :
l'éditeur publie officiellement du MLX INT3/INT4/INT6 pour toute la famille
Mini, à 2,2 / 2,6 / 3,4 Go pour le 4 B, 1,0 / 1,1 / 1,3 Go pour le 1,5 B et
0,3 / 0,3 / 0,4 Go pour le 0,5 B.

**Minimum mlx-lm 0.27.1**, du 4 septembre 2025 — Apertus y a tourné *un jour
après* sa sortie publique, parce que xIELU était déjà dans le fichier du
modèle.

*Forces.* C'est le cadre d'Apple lui-même, et le seul qui atteigne vraiment le
GPU sur cette plateforme. Onze analyseurs d'appels d'outils sont livrés avec et
choisis automatiquement, sans drapeau à passer. **Le parallélisme de tenseurs
est le mode de partage par défaut** — celui qui accélère vraiment le décodage,
contrairement au parallélisme de pipeline — sur un transport RDMA
Thunderbolt 5, à une latence annoncée sous 50 µs. Mesuré sur un portable de
16 Go de cette plateforme : Apertus 1.0 8B à 21,5 jetons par seconde pour un
pic de 4,7 Go, et Apertus v1.1 4B à 32,1 jetons par seconde pour 2,9 Go.

*Faiblesses et pièges.* **Sa propre documentation énonce que le serveur « is
not recommended for production as it only implements basic security checks »**,
et `--allowed-origins` vaut `*` par défaut : ne le liez jamais à une adresse
publique sans mandataire devant. **La dernière étiquette publiée est plus
ancienne que les fonctions que vous voulez** — les analyseurs d'outils et les
architectures récentes ne sont que sur la branche principale — donc on installe
depuis git et on épingle un commit. Le parallélisme de tenseurs est **par
modèle** : il exige une méthode `shard()` dans le fichier du modèle, et le
correctif pour un partage inégal n'est pas fusionné, donc un nombre de machines
qui ne divise pas les dimensions retombe silencieusement sur du pipeline, sans
gain de vitesse. Et il n'existe **aucune version MLX d'Apertus 70B** chez
l'organisation communautaire : la seule au monde est un affinage tiers de
39,7 Go, pas l'original de l'éditeur — sinon on convertit soi-même, ce qui est
direct puisque xIELU est en place.

MLX a désormais une dorsale CUDA sous Linux, mais toute la voie servie et
mesurée de ce relevé reste celle d'Apple.

### LocalAI

S'installe par un script qui pose le binaire dans un répertoire système avec
`sudo` ou sous votre propre compte, ou par une image de conteneur. À noter : le
script **n'écrit plus d'unité systemd**, elle est à produire soi-même.

**GGUF par sa dorsale llama.cpp**, et safetensors en bf16, FP8 et NVFP4 quand
il délègue à ses dorsales vLLM ou SGLang, revenues en 4.3.0 pour les machines
ARM64 sur des roues CUDA 13.

**Aucune version minimale n'est publiée pour Apertus**, et c'est pourquoi cette
case du tableau est un tiret. Le support est hérité de la llama.cpp qu'il
embarque, et le relevé n'épingle pas cette version embarquée — le `b6671` de
llama.cpp ne se transpose donc pas mécaniquement en un numéro LocalAI.

*Forces.* Un seul cœur qui parle les formes d'API OpenAI et Anthropic, et qui
peut mettre derrière lui soit llama.cpp, soit un vrai vLLM, selon ce que le
modèle demande. Il télécharge par URI — `huggingface://`, `hf://`, `hf.co/`,
`oci://`, `ollama://`, `github://`, `http(s)://`, `file` — donc n'importe quel
GGUF communautaire est joignable sans catalogue. Et `GET /healthz` et
`GET /readyz` séparent « démarré » de « prêt », ce qu'**aucun autre moteur de
cette liste ne distingue**.

*Faiblesses et pièges.* **Sa galerie ne contient aucune entrée Apertus** :
l'index fait 2,5 Mo et 1 566 entrées, et il ne donne aucun résultat pour
« apertus » ni pour « swiss ». `local-ai run apertus` échoue donc, et la forme
`huggingface://` est obligatoire, pas une préférence. Pire pour un installateur
par étapes : **ses dorsales se téléchargent elles-mêmes à la première
inférence**, c'est-à-dire une image de conteneur de plusieurs gigaoctets — une
étape lente et faillible, à compter à part et non à replier dans « démarrer le
serveur ». Un piège d'identification : il réémet en entier l'API native
d'Ollama et répond littéralement « Ollama is running » sur `/`, donc dans une
échelle de sondage il doit être testé **avant** Ollama ; ce qui les sépare est
`GET /readyz`, où Ollama renvoie 404.

### vLLM

S'installe par une roue Python ou une image de conteneur.

**safetensors** : bf16/fp16, FP8 W8A8, NVFP4 compressed-tensors, int4 w4a16,
MXFP4, et un cache clé-valeur en FP8. Pas de GGUF en pratique pour ces modèles.

**Minimum 0.10.2**, du 13 septembre 2025, par la demande de fusion qui a ajouté
« Apertus and XIELU » — un support au jour zéro, livré avant que le modèle ne
soit public. L'analyseur d'appels d'outils `apertus` est amont lui aussi, avec
son gabarit et ses tests.

*Forces.* C'est le **seul moteur de cette liste qui consomme directement les
poids officiels de l'éditeur**. Tout autre chemin dépend d'un quantificateur
communautaire, puisque l'organisation Apertus ne publie aucun GGUF. Et le lot
récupère tout ce qu'un flux unique perd : 20,5 jetons par seconde à un flux
contre 368 à trente-deux sur un 8 B en FP8, et 5,79 contre 695 jetons par
seconde agrégés de 1 à 256 flux sur un 49 B en NVFP4.

*Faiblesses et pièges.* **Il n'annonce absolument aucune capacité** : un client
ne peut lire ni les outils, ni le support de la vision, ni la longueur de
contexte — on suppose ou on essaie. En bf16 le 8 B pèse 16,1 Go et ne tient pas
sur une carte de 16 Go : 24 Go est le vrai plancher, sinon il faut une version
FP8 à 9,1 Go, qui n'est elle-même rapide qu'à partir de la capacité de calcul
8.9. **La voie processeur est inutilisable pour un débutant** : `avx512f` est
exigé pour l'ensemble des fonctions, un `LD_PRELOAD` est à trouver à la main,
et l'arbre torch pèse plusieurs gigaoctets — et une machine virtuelle au modèle
de processeur par défaut n'expose même pas `avx512` à l'invité, donc testez les
drapeaux du processeur avant d'offrir vLLM sur une cible sans GPU.

> ⚠️ **Le noyau CUDA xIELU fusionné optionnel n'est pas à installer.** Il vit
> dans un dépôt **sans aucune licence** — pas de fichier `LICENSE`, la
> plateforme d'hébergement annonce `license: None`, et rien sur l'index de
> paquets. Un projet libre ne peut pas le livrer. Le repli en PyTorch pur est
> automatique et correct ; il coûte de la vitesse, rien d'autre.

Deux faits de plus sur ce moteur. **Apertus v1.5 n'est pas amont** : le
registre de modèles ne connaît que la classe v1, la demande de fusion du modèle
est ouverte et non fusionnée, et l'affirmation contraire qui circule dans les
résumés de recherche est fausse — ce qui est amont, c'est l'*analyseur
d'outils*, pas le modèle. Et sur la roue ARM64, une extension de quantification
ne porte des cubins que pour une seule capacité de calcul ; les deux gardes du
chargement passent quand même, donc l'échec arrive tard, au lancement du noyau.
Un point de contrôle NVFP4 compressed-tensors sans schéma de transformation
échappe à ce trou, ses noyaux matriciels venant d'une bibliothèque qui porte
bien la bonne cible.

### Les deux moteurs que ce relevé n'a PAS su décrire

Ils sont **nommés plutôt que rangés dans la table avec des cases vides**. Une
ligne dont quatre colonnes sur onze disent « non relevé » encombre sans
renseigner, et un menu qui propose un moteur qu'il ne sait pas décrire promet
plus qu'il ne tient.

**llamafile.** Ce qui est établi : c'est la voie que la documentation
officielle d'Apertus présente pour une machine ordinaire, elle a sa page de
guide, il écoute sur le port 8080, il sert `/completions` décrit comme
« OpenAI-compatible format », et il ne demande ni Python ni CUDA — un
exécutable préconstruit est tout ce qu'il y a. **Ce qui manque : la licence,
tout numéro de version, le format de poids qu'il consomme, et une version
minimale pour Apertus.** Quatre champs sur onze. Aucun comportement précis ne
peut être promis, et la machine ne peut être sondée autrement qu'en appelant
`/completions`.

**SGLang.** Ce qui est établi : il a une page de guide officielle chez
Apertus — ce que llama.cpp n'a pas — le lot le porte de 20,5 à 368 jetons par
seconde sur un 8 B en FP8, le décodage spéculatif s'active par un drapeau, et
il a **refusé de servir une version NVFP4 dans deux versions différentes**, ce
qui compte puisque NVFP4 est précisément le format pour lequel le matériel
récent s'achète. **Ce qui manque : la licence, le port par défaut, la version
minimale pour Apertus, et sa propre voie d'installation.** Trois champs sur
onze sont vides, et le module consigne un port à `0` pour dire « non
renseigné » plutôt que d'inventer un nombre pour remplir la case.

Les deux demandent une vérification propre avant d'apparaître comme choix de
menu.

## 4. Les modèles ouverts

Vingt-quatre entrées. L'ordre répond à la question que pose le lecteur, pas à
un classement : Apertus d'abord, parce que c'est le sujet de ce dépôt ; puis ce
qui **tourne** sur une machine modeste, du plus petit au plus lourd ; puis ce
qui **ne tient pas**, du moins gros au plus gros, pour que le mur se voie au
lieu de se deviner.

| Nom | Éditeur | Paramètres | Contexte | Licence | Poids | Cache KV/jeton |
|---|---|---|---|---|---|---|
| Apertus-8B-Instruct-2509 | Swiss AI Initiative (EPFL / ETH / CSCS) | 8,05 G dense | 65 536 | Apache-2.0 + USAGE_POLICY | bf16 16,1 Go · FP8 9,1 Go · NVFP4 6,1 Go | 128,0 Kio (2·32·8·128·2) |
| Apertus-70B-Instruct-2509 | Swiss AI Initiative (EPFL / ETH / CSCS) | 70,6 G dense | 65 536 | Apache-2.0 + USAGE_POLICY | 4 bits 39,9 Go · FP8 72,8 Go · bf16 141,2 Go | 320,0 Kio (2·80·8·128·2) |
| Apertus v1.1 Mini (0.5B, 1.5B, 4B) | Swiss AI Initiative (EPFL / ETH / CSCS) | 0,5 / 1,5 / 4 G dense | 4 096 (x3) | Apache-2.0 + USAGE_POLICY | 4B 7,7 Go · 1.5B 3,0 Go · 0.5B 1,1 Go | 96,0 / 32,0 / 20,0 Kio (4B / 1,5B / 0,5B) |
| Apertus-v1.5-8B | Swiss AI Initiative (EPFL / ETH / CSCS) | 8,90 G dense (multimodal) | 262 144 | Apache-2.0 (gated) | bf16 18,4 Go · FP8 11,4 Go · NVFP4 9,0 Go | 128,0 Kio (2·32·8·128·2) |
| Apertus-v1.5-70B | Swiss AI Initiative (EPFL / ETH / CSCS) | 72,0 G dense (multimodal) | 262 144 | Apache-2.0 (gated) | W4A16 43,0 Go · FP8 76,2 Go · bf16 144,6 Go | 320,0 Kio (2·80·8·128·2) |
| Qwen3.5-4B | Alibaba (Qwen) | 4 G dense | 262 144 → 1,01 M YaRN | Apache-2.0 | bf16 8,1 Go (7,5 Gio) | 32,0 Kio (2·8·4·128·2) |
| Qwen3.8-27B | Alibaba (Qwen) | 27,8 G dense | 262 144 | Apache-2.0 | Q4 17,6 Go · Q8 29,0 Go · bf16 55,6 Go | 256,0 Kio (2·64·4·256·2) calc. |
| Nemotron 3 Nano 30B-A3B | NVIDIA | 31,6 G · act. 3,6 G (MoE) | 262 144 (config) | NVIDIA Open Model License | FP8 31,6 Go · bf16 63,2 Go | 6,0 Kio (2·6·2·128·2) |
| Qwen3.6-35B-A3B | Alibaba (Qwen) | 35 G · act. 3 G (MoE) | 262 144 → 1,01 M YaRN | Apache-2.0 | FP8 35,0 Go · bf16 70,0 Go | 20,0 Kio (2·10·2·128·2) |
| Qwen3.5-35B-A3B | Alibaba (Qwen) | 35 G · act. 3 G (MoE) | 262 144 → 1,01 M YaRN | Apache-2.0 | FP8 35,0 Go · bf16 70,0 Go | 20,0 Kio (2·10·2·128·2) |
| gpt-oss-120b | OpenAI | 116,8 G · act. 5,1 G (MoE) | 131 072 | Apache-2.0 | 63,0 Go (MXFP4) | 72,0 Kio (2·36·8·128·2) |
| Mistral-Small-4-119B-2603 | Mistral AI | 119 G · act. 6,5 G (MoE) | 1 048 576 (config) ⚑ 200 K | Apache-2.0 | NVFP4 70,8 Go · IQ4_XS 58,1 Go | 576,0 Kio (2·36·32·128·2) |
| Devstral 2 123B Instruct 2512 | Mistral AI | 123 G dense (Small 2 : 24 G dense) | 262 144 | license:other (Mistral (custom)) | Q4_K_M 74,9 Go · Small 2 en Q4 ~14 Go | — |
| Nemotron 3 Super 120B-A12B | NVIDIA | 120,6 G · act. 12,7 G (MoE) | 262 144 (config) | NVIDIA Open Model License | NVFP4 80,3 Go · FP8 128,4 Go | 8,0 Kio (2·8·2·128·2) |
| Qwen3.8-Flash-Next | Alibaba (Qwen) | 125 G · act. 6 G (MoE) · 180 G | 262 144 → 1 M YaRN | qwen-community-1.0 | IQ4_XS 93,7 Go · NVFP4 132,7 Go | 24,0 Kio (2·12·2·128·2) |
| Kimi-Linear-48B-A3B-Instruct | Moonshot AI | 48 G · act. ~3 G (MoE) | — | MIT | bf16 98,3 Go | — |
| MiniMax-M2.7 | MiniMax | 228,7 G · act. 10 G (MoE) | 204 800 | Modified MIT | IQ4_XS 108,4 Go · NVFP4 139,9 Go | 248,0 Kio (2·62·8·128·2) |
| DeepSeek-V4-Flash-0731 | DeepSeek | 304,2 G · act. ~13 G (MoE) | 65 536 → 1 M YaRN | MIT | IQ3_XXS 104,2 Go · NVFP4 175,6 Go | 48,4 Kio (MLA 43·576·2) |
| GLM-5.3-Flash | Z.ai / Zhipu (zai-org) | 321,3 G · act. 18 G (MoE) | 1 048 576 ⚑ 300 K | MIT | IQ3_XXS 120,4 Go · NVFP4 204,4 Go | 50,6 Kio (MLA 45·576·2, inf.) |
| MiniMax-M3 | MiniMax | ~428 G · act. ~23 G (MoE) | 1 048 576 | minimax-community | IQ3_XXS 194,9 Go · IQ4_XS 207,6 Go | 120,0 Kio (2·60·4·128·2) |
| GLM-5.3 | Z.ai / Zhipu (zai-org) | ~744 G · act. — | 1 048 576 (config) | license:other « glm-5.3 » | IQ3_XXS 281,7 Go · IQ4_XS 365,3 Go · FP8 755 Go | — (cf. GLM-5.2 : 87,8 Kio) |
| DeepSeek-V4.1-Flash | DeepSeek | 763,2 G | 1 048 576 (config) | MIT | FP8 510,3 Go · ~380 Go en 4 bits | — |
| Kimi K2.7-Code | Moonshot AI | 1 000 G · act. 32 G (MoE) | 262 144 | Modified MIT | 595,2 Go (INT4) | 68,6 Kio (MLA 61·576·2) |
| Kimi K3 | Moonshot AI | 2 800 G · act. 104 G (MoE) | 1 048 576 | Kimi K3 License (Modified MIT +) | 1 560,9 Go en MXFP4 (119) | 27,0 Kio (MLA 24/93) |

### 4.1 La famille Apertus

Cinq entrées, un éditeur, et une séparation nette entre ce qui tourne
aujourd'hui et ce qui ne tourne pas.

**Apertus-8B-Instruct-2509 est celui à épingler pour ce dépôt.** C'est
8 053 338 176 paramètres, dense, 32 couches, 65 536 jetons de contexte,
Apache-2.0 et sans restriction de téléchargement. C'est le seul Apertus
vraiment confortable : 15,0 Gio en bf16, sa fenêtre entière sur une machine, et
**les quatre moteurs le servent sans correctif**. En bf16 il ne tient pas sur
une carte de 16 Go — 16,1 Go de poids seuls — donc le plancher réaliste est une
carte de 24 Go, ou la version FP8 à 9,1 Go, qui n'est rapide qu'à partir de la
capacité de calcul 8.9. Son gabarit de discussion est le piège : des jetons
spéciaux inhabituels plus un bloc développeur obligatoire, et quand il est mal
appliqué les jetons de contrôle bruts fuient dans les réponses visibles.

Sa licence mérite une phrase soignée. C'est de l'Apache-2.0, mais une politique
d'usage est livrée à côté du fichier de licence, et elle porte une obligation
d'indemnisation et une recommandation de re-télécharger un filtre d'empreintes
deux fois par an. « Apache-2.0, rien d'autre à lire » serait faux.

**Apertus-70B-Instruct-2509 est une autre sorte de machine.** Même famille,
80 couches, même fenêtre de 65 536 jetons, 320 Kio de cache clé-valeur par
jeton — donc sa fenêtre pleine coûte 20 Gio de cache par-dessus les poids. Une
quantification 4 bits tient largement sur une machine à 39,9 Go, mais comme il
est dense il relit tout à chaque jeton : 6,8 jetons par seconde de plafond, 4 à
5 en pratique. En bf16 il ne tient sur aucune machine unique de 128 Go —
131,5 Gio de poids contre un budget utilisable d'environ 115 Gio — et il échoue
même à contexte nul ; deux machines le portent confortablement, à environ
75,8 Gio par nœud.

Trois avertissements sur ses versions, et les trois portent sur des
quantifications communautaires. **Aucune quantification d'aucun Apertus n'est
officielle** — l'éditeur ne livre ni FP8 ni point de contrôle quantifié pour
l'une ou l'autre taille — donc tout ce qui est exploitable sur du matériel
récent est communautaire et non validé par les institutions qui publient. Une
version « 4 bits dynamique » très téléchargée **pèse 114,4 Go et non 40** : son
schéma dynamique a laissé 52,5 G de paramètres en bf16 contre seulement 18,6 Go
de charge utile en 4 bits, et le nom trompe. Et deux dépôts du même auteur,
l'un étiqueté NVFP4 et l'autre NVFP4A16, sont **le même modèle à l'octet près**
à 42,80 Go chacun : ne téléchargez pas les deux.

**La famille Apertus v1.1 Mini — 0,5 B, 1,5 B, 4 B — est la réponse petite
machine, et son contexte est le mur.** Les trois déclarent **4 096 jetons**, et
rien dans leur configuration ne l'étend : le 4 B et le 1,5 B utilisent un type
rotatif par défaut, sans aucun facteur d'échelle. Pour un assistant de code,
4 096 jetons est rédhibitoire. Ce que vous obtenez en échange, c'est que toute
la famille, six dépôts de poids pleins, tient ensemble résidente en 21,8 Gio,
que le cache est un non-sujet à 96 / 32 / 20 Kio par jeton, et que les plafonds
sont de 35,7, 90 puis au-delà de 150 jetons par seconde en descendant les
tailles.

Leurs quantifications portent un piège de plateforme : **neuf des dix
officielles sont des versions MLX**, donc Apple uniquement et mortes sur une
machine ARM à GPU NVIDIA ; la dixième, la seule NVFP4, ne couvre que le modèle
d'un milliard et demi. Et le plus gros Mini n'a **aucune version NVFP4**, ni
officielle ni communautaire.

Une curiosité qui ressemble à une erreur d'empaquetage et n'en est pas : le
dépôt de base du 0,5 B (0,9 Go) est *plus petit* que son jumeau affiné aux
instructions (1,1 Go). L'affiné déclare des embeddings liés dans sa
configuration mais livre une tête de sortie déliée, et la table 131 072 × 1024
fait les 0,3 Go d'écart. Pour toutes les autres paires de la famille, base et
affiné sont identiques à l'octet.

**Apertus v1.5, dans les deux tailles, est restreint et non servi.** Deux
choses l'arrêtent.

D'abord, **les dépôts sont restreints**. L'approbation est automatique au clic,
mais un compte est exigé, ainsi que l'acceptation des politiques d'usage et de
confidentialité et le remplissage d'un champ « société » et d'une adresse de
courriel institutionnelle. Une récupération anonyme de la configuration renvoie
« Access to model … is restricted » — soit un 401 que personne n'attend sur une
machine distante, au milieu d'une installation. Des miroirs sans restriction
existent, et ils contournent la politique que le dépôt officiel exige.

Ensuite, **aucun moteur en amont ne le charge**. Sa classe d'architecture n'est
enregistrée que dans un fork épinglé d'un moteur, à un commit donné, à côté
d'un fork épinglé de la bibliothèque de transformeurs ; la demande de fusion
amont est ouverte depuis le 31 juillet 2026 et sa devancière a été fermée sans
fusion ; llama.cpp n'a ni convertisseur pour lui ni projecteur multimodal, sur
les 92 fichiers de son paquet de conversion ; et le ticket Ollama
correspondant est ouvert. Les quantifications ne débloquent rien côté logiciel :
ce sont toujours la même architecture et elles passent toujours par le même
fork.

Et **tout GGUF v1.5 que vous trouverez est une amputation, pas une
conversion** : les tours image et audio sont *retirées* de la carte des poids —
pas converties, retirées — et le vocabulaire d'entrée est tronqué de 266 752 à
131 072. Un `-text-` dans le nom du fichier est le seul avertissement que vous
aurez.

Ce que v1.5 achèterait, s'il était servable : 262 144 jetons au lieu de 65 536,
un créneau plein à 49,1 Gio pour le 8 B, et la seule voie multimodale
d'Apertus. Pour le 70 B, une seule version communautaire atteint les 262 144
pleins sur une machine — 40 Gio de poids plus 40 Gio de cache fp8, avec environ
14 Gio de marge — et l'ironie à voir avant de s'engager est que cette
version-là est sur le chemin logiciel *le moins* supporté de tous. À noter
aussi qu'une de ses versions NVFP4 n'est pas uniforme : sa propre configuration
déclare un schéma de précision mixte, NVFP4 sur les projections de propagation
avant et FP8 sur l'attention, ce qui explique ses 51,5 Go au lieu d'environ 43.

Enfin, côté v1.5, **il n'existe aucun rapport technique**. Il était promis
« dans les semaines à venir » à la sortie du 24 juillet 2026 et il n'existe
pas. Il n'y a aucun chiffre de qualité pour v1.5, nulle part.

### 4.2 Ce qui tourne sur une machine modeste

« Modeste » veut dire ici trois paliers, et la façon honnête de les lire est
par la mémoire dont vous disposez vraiment, pas par le nombre de paramètres.

**Un portable ou un petit serveur — moins de 24 Go.** Les Mini d'Apertus,
l'Apertus 8B en GGUF 4 bits, et un modèle dense de 4 G qui est à ce catalogue
pour ce qu'il prouve plutôt que pour ce qu'il fait. Ce modèle documente
1 010 000 jetons à quatre milliards de paramètres sous Apache-2.0 — la même
fenêtre qu'un modèle quatre cents fois plus gros — parce que seules 8 de ses
32 couches sont à attention pleine. L'inversion à regarder, c'est que ses
7,5 Gio de poids portent 30,5 Gio de cache à un million de jetons, et que,
étant dense, il plafonne vers 34 jetons par seconde, sans aucun banc de code
publié. Gardez-le pour la démonstration.

Dans ce palier aussi, le petit frère d'une famille spécialisée code : environ
14 Go en 4 bits pour à peu près 12 à 14 jetons par seconde à 68,0 % sur un banc
de correctifs auto-déclaré, sous Apache-2.0. C'est un repli défendable quand on
veut un petit modèle de code dédié et une licence propre.

**Une seule grosse machine — environ 117 Gio utilisables.** C'est là que le
catalogue devient intéressant, et c'est là que la règle des paramètres actifs
fait tout le travail.

Le logement le plus confortable est un mélange d'experts de 119 G dont
seulement 6,5 G actifs : 65,9 Gio sur une machine, environ 45 Gio réellement
libres après surcoût, Apache-2.0, un plafond proche de 70 jetons par seconde.
C'est aussi l'avertissement canonique de ce guide : sa configuration déclare
1 048 576 jetons et sa carte recommande discrètement 200 K, et **son cache est
le plus cher de tout le catalogue** à 576 Kio par jeton — vingt-quatre fois
celui d'un autre modèle du même tableau. Ces 45 gigaoctets libres achètent
environ 82 K jetons en cache bf16, 164 K en fp8. Budgétez 64 K à 100 K de
contexte réel, et vérifiez `kv_heads × head_dim × couches` avant de croire une
longueur annoncée.

La chose la plus rapide réellement vérifiée sur cette classe de matériel est un
MoE de 116,8 G à 5,1 G actifs, livré nativement en MXFP4 à 63 Go : 1 956 jetons
par seconde en préremplissage, 60,57 en décodage, Apache-2.0, et **le seul
modèle du catalogue dont la fenêtre annoncée tient avec de la marge** — ses
131 072 jetons entiers coûtent 9,0 Gio, 68 Gio au total. Sa faiblesse est cette
même fenêtre : 131 072 jetons, c'est la moitié de ce que demande un agent qui
travaille à l'échelle d'un dépôt, et son éditeur n'a rien publié d'ouvert
depuis le 4 août 2025. Périmé comme agent principal, excellent comme complétion
locale rapide et comme appelant d'outils.

Deux modèles hybrides rendent le contexte long presque gratuit en mémoire.
L'un garde 6 couches d'attention sur 52 et coûte 6 Kio par jeton — 5,7 Gio pour
un million de jetons, 64,6 Gio au total en bf16 et 32,3 Gio en FP8, le cache le
moins cher relevé. L'autre garde 10 couches à attention pleine sur 40 et donne
le meilleur compromis vitesse-contexte sur une machine : 42,1 Gio en FP8 pour
un million de jetons, avec un plafond autour de 91 jetons par seconde. Les deux
ont leur réserve : le premier a une limite déployée observée à 131 072 jetons
avec dégradation au-delà de 128 K et **aucun score de codage nulle part**, et
le million du second est une extrapolation YaRN dont le grand frère perd
quatorze points sur un banc de contexte long entre une portée de 128 K et une
portée de 1 M.

Le seul modèle du catalogue qui tienne **un million de jetons sur une machine**
est un hybride de 125 G à 6 G actifs : 87,3 Gio de poids plus 11,4 Gio de cache
fp8. Un cache bf16 porte le total à 110,2 Gio, trop serré une fois les
activations et les graphes comptés : passez le cache en fp8. Ses deux coûts
sont une licence maison à lire avant tout déploiement commercial — elle n'est
explicitement *pas* de l'Apache-2.0, contrairement à ses frères denses — et le
fait qu'aucun chiffre indépendant n'existe pour lui : seul son frère dense de
27 G figure au classement indépendant.

Ce frère dense de 27 G mérite sa propre phrase, parce qu'il enseigne la règle.
Il frappe très au-dessus de sa taille — 0,730 sur un banc de terminal
indépendant, à un point d'un modèle sept fois plus gros — et toutes ses
quantifications tiennent sans effort. Et il est **disqualifié sur le débit
quand même** : son quasi-jumeau a été mesuré à 12,63 jetons par seconde sur un
nœud, sous la vitesse interactive confortable, parce que dense veut dire que
les 27,8 G sont lus à chaque jeton. Son meilleur emploi est celui de relecteur
de qualité en bf16 pendant qu'un modèle creux rapide fait le gros du travail.

Un modèle de recherche de 48 G sur l'attention linéaire tient confortablement à
98,3 Go, avec environ 3 G actifs et un plafond proche de 90 jetons par seconde.
Il n'a aucun banc de code et son contexte natif n'a pas été relevé. Gardez-le
pour ce qu'il démontre : l'attention linéaire se dégrade *gracieusement*, et
gagne des rangs quand la portée évaluée s'étend.

**Deux machines — environ 251 Go.** Deux modèles méritent ce palier. L'un est
un MoE de 304 G à 13 G actifs sous MIT, à cache latent compact, et c'est **la
mieux étayée de toutes les entrées du catalogue** : un score indépendant qui
concorde avec sa propre carte, plus une mesure de débit sur exactement cette
classe de matériel — 52,87 jetons par seconde en décodage sur deux machines
reliées en direct. Ses coûts sont honnêtes : il exige deux machines en NVFP4,
son délai jusqu'au premier jeton à 131 K a été mesuré à 89,36 s, et son million
de jetons est un étirement YaRN de facteur 16 depuis une base entraînée à
64 K — visez 128 à 256 K comme fenêtre de travail.

L'autre est un MoE multimodal de 321 G à 18 G actifs, MIT lui aussi, qui porte
le meilleur score de codage indépendant de tout ce qui tient. Dix-huit
milliards de paramètres actifs coûtent environ 30 % de débit contre le
précédent pour 1,6 point de plus — l'autre gagne à la vitesse par point. Sa
version 3 bits tiendrait sur une machine, mais lisez la section 6 avant de
prendre ce chemin.

Un troisième, à ~428 G dont ~23 G actifs, tient *tout juste* sur deux machines
et n'est **pas recommandé** : il décode environ deux fois plus lentement qu'un
frère plus petit sans rien gagner sur le banc de terminal, et son écart
frappant de 0,805 contre 0,660 entre deux bancs suggère un réglage pour
l'évaluation par correctifs plutôt que pour l'agence longue en terminal.

**Deux modèles d'ici sont périmés, et le tableau le dit.** Un MoE de 35 G n'est
gardé que parce que l'arithmétique de contexte publiée porte sur lui ; sa
génération plus récente a une géométrie identique et une qualité égale ou
meilleure, donc il n'y a aucune raison de déployer l'ancien neuf. Et un modèle
de code *dense* de 123 G est remplacé par le modèle creux de 119 G ci-dessus,
qui replie trois familles antérieures dans un seul point de contrôle. Ce modèle
dense est l'illustration parfaite de la règle : il tient sur une machine à
74,9 Go en 4 bits, et il est disqualifié quand même, à 3,6 jetons par seconde
de plafond et environ 2,5 en pratique. **« Ça rentre » n'est pas un critère.**

### 4.3 Ce qui ne tient pas du tout

Quatre entrées, et elles sont au tableau exprès : le mur doit se voir, pas se
deviner. Les quatre sont forts, les quatre sont ouverts, et aucun ne tournera
sur deux machines.

Le modèle de codage ouvert le plus fort qui existe demande **365,3 Go dans sa
version 4 bits** contre un plafond de 251 Go pour deux machines, et même sa
version 3 bits à 281,7 Go déborde encore. À noter aussi que sa licence **a
quitté le MIT** à cette génération pour une licence maison, là où les versions
précédentes et son propre petit frère sont restés MIT — si la pureté de licence
compte, épinglez la version antérieure ou prenez le frère.

Le modèle au rang 1 du classement de codage indépendant, publié trois jours
avant le relevé, est **sous licence MIT et vous ne pouvez toujours pas le faire
tourner** : environ 380 Go même en 4 bits. La branche exécutable de sa famille
est le modèle deux machines de la section 4.2.

Un modèle spécialisé code de mille milliards de paramètres à 595,2 Go dépasse
de 2,37 fois le plafond de deux machines, exige cinq machines pour les poids
seuls, et il est **déjà en INT4 natif** — descendre plus bas demanderait environ
deux bits par paramètre, bien sous le seuil d'utilisabilité, sans point de
contrôle officiel à ce niveau. Sa licence est un quasi-MIT avec une seule
obligation d'affichage au-delà de seuils d'usage très élevés et, fait notable,
aucune restriction d'usage interne. Et une variante à haute vitesse citée pour
sa rapidité **n'a aucun poids publié**, donc ces chiffres ne sont pas
reproductibles en auto-hébergement.

Enfin, un modèle de 2 800 G à 104 G actifs pèse 1 560,9 Go sur 119 fichiers —
6,21 fois deux machines, treize machines pour les poids seuls. Même en les
ayant, environ 57 Go seraient lus par jeton décodé, soit 4,8 jetons par seconde
à 273 Go/s ; son propre éditeur le sert à 37,4 jetons par seconde. Il n'en est
pas moins la meilleure démonstration du catalogue sur la règle du cache : seules
24 de ses 93 couches gardent un cache qui croît, donc un million de jetons coûte
environ 29 Go de cache pour 2 800 milliards de paramètres — le *cache*, lui,
tiendrait sur votre bureau.

Un piège d'intégration de ce modèle vaut la peine d'être connu même si vous ne
le lancez jamais, parce qu'il vaut pour tout modèle de ce genre : il renvoie
toujours un champ de raisonnement séparé, qu'il **faut repasser tel quel** dans
les tours suivants, appels d'outils inclus. Un agent qui ne repasse que le
contenu visible perd le fil silencieusement — sans erreur, et donc sans
diagnostic.

### Deux avertissements transversaux sur l'identité

**Épinglez l'identifiant de dépôt et la révision, pas le nom.** Un éditeur
livre cinq modèles distincts dont les noms ne diffèrent que par une date ou un
suffixe, et le mot « Flash » désigne un petit modèle distillé chez un
fournisseur et un mélange d'experts de plus de 300 G chez deux autres. Une
configuration épinglée par le nom résoudra un jour vers autre chose.

**Ne croyez pas la colonne « poids ouverts » d'un classement.** Celle qui a
servi à ce relevé est fausse en au moins deux endroits : elle marque comme
fermé un modèle publiquement téléchargeable à 755 Go, et elle en marque deux
autres comme fermés alors que leur éditeur publie les deux. Vérifiez ce statut
sur le dépôt de poids lui-même.

## 5. Ressources — ce qu'une classe de machine tient vraiment

### 5.1 La mémoire annoncée n'est pas la mémoire utilisable

Le nombre inscrit sur la boîte n'est pas celui qu'obtient un modèle.

**Sur une machine Linux à mémoire unifiée, une plaque de 128 Go rapporte
environ 117 Gio**, et le relevé budgète **115 Gio** une fois comptés les
activations, le contexte de l'accélérateur, la fragmentation et le tampon de
préremplissage. L'écart n'est pas théorique : la version FP8 d'un modèle mesure
**116,1 Gio contre 117 utilisables**, ce qui ne laisse pas un gigaoctet pour
aucun des quatre, et elle est à traiter comme **ne tenant pas**, même si
l'arithmétique dit le contraire d'un cheveu.

**Sur macOS, le système réserve environ un quart de la mémoire unifiée.** Une
machine de 256 Go n'en offre qu'environ 192 Go à un modèle jusqu'à ce que
`sudo sysctl iogpu.wired_limit_mb=237568` la porte à ~232 Go. Une contrainte de
plus sur cette plateforme : ses accélérateurs matriciels couvrent FP16 et INT8
mais **pas BF16** — convertissez en 4 ou 8 bits, jamais en bf16.

**Sur un GPU discret, la carte est le budget et on n'emprunte pas.** L'Apertus
8B en bf16 fait 16,1 Go de poids seuls, donc il ne tient pas sur une carte de
16 Go ; 24 Go est le vrai plancher, ou une version FP8 à 9,1 Go.

### 5.2 Ce que tient chaque classe

| Machine | Budget utilisable | Ce qu'elle tient |
|---|---|---|
| Portable, 16 Go unifiés | ~12 Go | les Mini d'Apertus, et l'Apertus 8B en 4 bits — mesuré à 21,5 jet/s pour un pic de 4,7 Go, et 32,1 jet/s pour 2,9 Go sur le 4 B |
| Carte GPU, 16 Go | 16 Go | un 8 B en FP8 (9,1 Go), pas en bf16 |
| Carte GPU, 24 Go | 24 Go | un 8 B en bf16, le vrai plancher pour servir en pleine précision |
| Une machine unifiée, 128 Go | ~115-117 Gio | un MoE MXFP4 de 63 Go avec 50 Gio libres ; un MoE NVFP4 de 70,8 Go avec ~45 Gio libres ; une version de 93,7 Go avec un million de jetons de cache fp8 ; un 70 B en 4 bits avec sa fenêtre pleine |
| Deux machines reliées | ~251 Go | un MoE NVFP4 de 175,6 Go ; une version 4 bits d'un modèle de 321 G ; et rien à 365 Go ou au-dessus |

Tout chiffre de ce tableau est dérivé de tailles de fichiers vérifiées plus les
surcoûts mesurés ci-dessus. **Rien de tout cela n'est une spécification
d'éditeur.**

### 5.3 Relier deux machines agrège la capacité, pas la bande passante

C'est la partie qui déçoit.

Deux machines tiennent deux fois les poids. Elles ne décodent **pas** deux fois
plus vite, et sous certains moteurs elles décodent *moins* vite.

Ce qui est mesuré : un MoE décode à **52,87 jetons par seconde sur deux
machines reliées en direct**, soit environ 73 % de ce que prédirait le report
de l'estimation « une machine ». Le lien entre elles déplace environ 10,2 Go/s,
et la façon dont un gros mélange d'experts à parallélisme d'experts s'y met à
l'échelle n'est **pas mesurée** du tout.

Ce qui est mesuré de l'autre côté : le transport dos à dos de llama.cpp est du
TCP nu, sans RDMA, et il **ralentit quand on ajoute des nœuds** — 20,4, puis
17,2, puis 15,2 jetons par seconde à un, deux et quatre nœuds. L'inverse a
aussi été observé, 1,8 montant à 12,5 jetons par seconde en passant d'un
boîtier ARM à deux — mais là le nœud unique débordait de mémoire, donc la
seconde machine achetait de la capacité, pas de la vitesse.

**Rien dans le relevé ne tranche le cas qui décide vraiment** : le modèle tient
sur une machine, et on en ajoute une seconde. Tant que personne ne l'a mesuré,
traitez une deuxième machine comme de la capacité.

Sur le matériel Apple, le partage est meilleur par nature : le parallélisme de
tenseurs — le mode qui accélère vraiment le décodage, contrairement au
pipeline — est le défaut, sur un transport RDMA Thunderbolt 5 à une latence
annoncée sous 50 µs. Il reste par modèle, et il retombe silencieusement sur du
pipeline quand le nombre de machines ne divise pas les dimensions du modèle.

### 5.4 Le disque, et la marge

Le disque est la moitié facile, et la règle est celle qu'énonce un
quantificateur communautaire : **la taille de la quantification, plus une à
deux marges de gigaoctet.** Un téléchargement écrit des fichiers
intermédiaires, et un moteur écrit un fichier de service.

Un cas de conversion est bien pire que cette règle, et le menu prévient avant
de commencer : convertir un 70 B vers une version 4 bits d'Apple télécharge
d'abord les poids en pleine précision, et demande donc environ 175 Go de place
libre pour en produire 41.

### 5.5 Avant de conclure qu'un modèle est lent

La seule mesure qui ancre toutes les estimations de débit de ce guide — 61 % du
plafond théorique — a été prise avec un noyau, un pilote et une version de CUDA
précis. Sans la bonne option de noyau, le **temps de chargement du même modèle
passe de 22 s à 104 s**. Avant de conclure qu'un modèle est lent sur votre
machine, vérifiez que le noyau, le pilote et la trousse à outils correspondent
à ceux des mesures publiées.

## 6. Forces et faiblesses, honnêtement

### 6.1 Un score de banc d'essai est indissociable de son échafaudage

C'est la réserve la plus importante sur tous les chiffres de codage de ce
guide, et ce n'est pas une précaution de langage.

**Un éditeur a mesuré 3,6 points d'écart pour un même modèle inchangé entre
deux échafaudages** — 79,7 contre 76,1 — et a publié les deux. Cet écart est
aussi grand que celui qui sépare entre eux les meilleurs modèles ouverts. Rien
du modèle n'a changé ; ce qui l'entourait, si.

Les échafaudages en jeu ne sont pas comparables non plus. Un éditeur mesure
dans un agent de code précis, à effort de raisonnement maximal, avec des délais
de six heures, en moyennant sur trois passages. Un autre mesure dans un
échafaudage « mode minimal » de son cru, non publié. Un troisième rapporte le
meilleur de deux échafaudages. Un quatrième a fait tourner son propre
échafaudage maison en citant des concurrents mesurés dans celui d'autrui — et
une source secondaire rapporte ce modèle trois points plus bas dans un
échafaudage indépendant que ce qu'annonce sa carte.

**Aucun chiffre de carte ne sera reproduit avec un échafaudage différent.**
Quand ce guide écrit « indépendant », cela veut dire qu'un tiers a fait tourner
le modèle ; quand il écrit « auto-déclaré », cela veut dire que c'est
l'éditeur. Le champ `codage` du module porte ce mot pour chaque modèle qui en a
un.

### 6.2 SWE-bench Verified ne discrimine plus

Il est saturé à 0,950, et les grands laboratoires ont cessé de le rapporter.
Les modèles ouverts s'y agglutinent entre **0,772 et 0,806** — cinq d'entre eux
dans un mouchoir de poche. Un banc d'essai sur lequel tout le monde obtient la
même chose a cessé de porter de l'information.

Le banc d'agence en terminal étale ces mêmes modèles de **0,25 à 0,91**. S'il
faut choisir sur un chiffre, choisissez sur celui-là — puis relisez la section
6.1, parce que ce chiffre a un échafaudage lui aussi.

### 6.3 La perte de qualité sous 4 bits n'est pas mesurée, exactement là où ça compte

Deux des modèles les plus forts d'ici tiennent sur **une seule** machine si on
les prend sous quatre bits : une version 2 bits à 90,9 Go, et une version
3 bits à 120,4 Go. Les deux sont tentantes, et **aucun banc publié ne rejoue
l'un ou l'autre à ce niveau**.

La raison d'être prudent est la *forme* de la dégradation plus que sa taille.
La dégradation agentique est vicieuse et invisible : le JSON des appels
d'outils se déforme, les plans longs perdent leur cohérence — pendant que la
perplexité bouge à peine. Le contrôle rapide habituel ne vous dira rien.

Préférez une version 4 bits sur deux machines à une version 2 ou 3 bits sur
une, sauf à être prêt à mesurer l'écart vous-même.

### 6.4 Apertus est un modèle multilingue souverain, pas un modèle de code

Il faut le dire franchement, avec ses chiffres.

La seule table de code qui existe pour Apertus, toutes versions confondues, est
la table 18 de son rapport technique (arXiv:2509.14233), et elle est
**auto-déclarée** :

| Modèle | HumanEval Pass@10 | MBPP Pass@1 |
|---|---|---|
| **Apertus-8B** | **67,0** | **36,2** |
| **Apertus-70B** | **73,0** | **47,0** |
| Qwen3-32B | 97,0 | 73,6 |
| Llama-3.3-70B-Instruct | 95,8 | 75,6 |
| Qwen2.5-72B-Instruct | 95,4 | 74,6 |
| gemma-3-27b-it | 89,3 | 72,8 |
| SmolLM3-3B | 89,7 | 52,8 |

Lisez la dernière ligne. **Un modèle de trois milliards de paramètres bat
l'Apertus de soixante-dix sur HumanEval.** L'écart avec un modèle de code de
32 B est de 24 points. Et la métrique flatte Apertus deux fois : le Pass@10 est
environ dix fois plus indulgent que le Pass@1 que rapportent ailleurs les
modèles auxquels il est comparé.

Il n'existe **ni SWE-bench, ni Terminal-Bench, ni LiveCodeBench, ni aucun
résultat agentique ou d'outillage pour aucune version d'Apertus**, nulle part.

Ce qu'Apertus a à la place, c'est ce qui l'a mis dans ce dépôt : des poids
Apache-2.0 qui se téléchargent sans compte, des **données d'entraînement
ouvertes**, une recette d'entraînement publiée avec ses points de contrôle
intermédiaires, une couverture de **1 811 langues**, 17 T de jetons de
préentraînement pour la famille, et un travail de conformité du genre que
demande la réglementation européenne. C'est un modèle souverain, auditable et
multilingue. Prenez-le pour cela. Pour un agent de code, prenez autre chose et
dites-le tout haut.

### 6.5 Ceci n'est pas un classement

Deux modèles à trois points d'écart sur un banc d'essai sont **à égalité**,
l'échafaudage qui les appelle pesant autant que ce qui les sépare. Les colonnes
de ces tableaux servent à **écarter** ce qui ne tiendra pas sur une machine,
pas à couronner un gagnant.

## 7. Ce que ce relevé ne sait pas

Cette section est l'honnêteté de ce guide, et elle n'est pas à adoucir. Tout ce
qui suit est un trou qui a été trouvé et laissé ouvert, plutôt que rempli par
une supposition.

### 7.1 Sur les moteurs

- **SGLang est le trou le plus large.** Le relevé n'en donne ni la licence, ni
  le port par défaut, ni la version minimale pour Apertus, ni sa propre voie
  d'installation. Il n'en établit que trois choses : une page de guide
  officielle existe, le lot le porte de 20,5 à 368 jetons par seconde sur un
  8 B en FP8, et deux versions ont échoué à servir une version NVFP4.
- **llamafile n'est documenté que par une seule ligne**, celle du guide
  officiel : port 8080, `/completions` décrit comme « OpenAI-compatible », ni
  Python ni CUDA requis. Licence, numéro de version, format de poids consommé
  et minimum pour Apertus sont tous absents.
- **Aucune version minimale de LocalAI pour Apertus n'est publiée.** Elle
  dépend de la llama.cpp qu'il embarque, et le relevé n'épingle pas ce moteur —
  le `b6671` de llama.cpp ne se transpose donc pas mécaniquement en un numéro
  LocalAI.
- **La licence propre de mlx-lm n'est pas relevée.** MIT est établi pour MLX,
  le cadre de calcul ; le projet de service est un autre dépôt.
- **La version courante de llama.cpp apparaît sous deux chiffres différents**
  à deux jours consécutifs du relevé. Deux séries de versions coexistent en
  amont — les constructions `bNNNNN` et un versionnage sémantique parallèle — et
  le relevé n'en donne pas la correspondance.
- **Ce que fait llama.cpp quand on ajoute une machine n'est pas tranché**, et
  les deux mesures ne se contredisent pas : sur quatre machines Apple en
  Thunderbolt le débit *descend* (20,4, 17,2, 15,2 jetons par seconde de un à
  quatre nœuds) parce que le transport est du TCP nu, mais sur deux boîtiers
  ARM il *monte*, de 1,8 à 12,5 — et là le nœud unique débordait de mémoire.
  Rien n'établit le cas qui décide : le modèle tient sur une machine, et on en
  ajoute une seconde.
- **Aucun moteur ne prend en charge Apertus v1.5 aujourd'hui.** La demande de
  fusion du modèle chez vLLM est ouverte, llama.cpp n'a pas de convertisseur,
  le ticket Ollama est ouvert, et la voie officielle passe par un fork épinglé
  de la bibliothèque de transformeurs. Les seuls GGUF v1.5 qui circulent sont
  des amputations, et un `-text-` dans le nom du fichier est le seul
  avertissement.
- **Aucun rapport d'Apertus sur le silicium NVIDIA récent n'existe.** Tous les
  débits de cette classe de matériel viennent d'autres modèles servis par ces
  moteurs, et servent de proxy : le comportement de l'activation xIELU sur
  cette capacité de calcul n'est mesuré nulle part.
- **Aucun chiffre officiel de RAM ni de VRAM n'est publié**, par aucune carte
  de modèle ni aucun site de projet. Toute valeur matérielle est dérivée de
  tailles de fichiers vérifiées plus la règle « taille de la quantification
  plus une à deux marges de gigaoctet » d'un quantificateur communautaire.
- **Le trou d'une extension ARM64 de vLLM a été mesuré statiquement**, par
  couverture de cubins ; l'échec à l'exécution n'a pas été reproduit. Et
  l'outil d'inspection ne permet pas de trancher : un cubin de famille et un
  cubin spécifique affichent le même nom de cible, donc auditer une roue et
  conclure « pas de support, donc cassé » est un faux négatif.
- **Quel moteur rend compte de l'avancement d'un téléchargement n'est pas
  documenté.** Le relevé établit seulement qu'Ollama expose un téléchargement
  en HTTP et que les dorsales de LocalAI se téléchargent d'elles-mêmes à la
  première inférence ; il ne décrit la sortie d'aucun d'eux. À vérifier avant
  de promettre une barre de progression dans un menu.
- **Un exécuteur distribué reste hors catalogue faute de champs.** Il est
  établi sous Apache-2.0, adossé à MLX, avec parallélisme de tenseurs et de
  pipeline — mais aussi à l'arrêt, son dernier commit de fond datant du 22 juin
  2026 avec des semaines entières sans aucun, et ne tournant que sur processeur
  sous Linux, donc incapable d'utiliser un GPU NVIDIA. Ni son port par défaut
  ni le support d'Apertus ne sont relevés.

### 7.2 Sur les modèles et leurs chiffres

- **Le cache clé-valeur d'un modèle est inféré**, et c'est le seul chiffre du
  catalogue qui ne remonte pas à un décompte de couches publié : ses 45 couches
  ont été lues comme de l'attention latente. Son mélange documenté d'attention
  creuse et linéaire n'a pas pu être vérifié couche par couche.
- **Le cache par jeton d'un modèle a été calculé ici**, à partir de la
  géométrie vérifiée de sa configuration, parce que la source ne chiffrait pas
  ce modèle.
- **Le nombre total de paramètres d'un modèle existe en deux versions**,
  304,2 G selon l'index des poids et 284 G selon la table comparative d'un
  concurrent. Les deux circulent ; le chiffre de l'index a été retenu.
- **Les poids d'un modèle existent en deux chiffrages**, et la conclusion
  pratique change entre les deux : sa version FP8 passe de « juste à la
  limite » à « ne tient pas ». Les sommes d'octets ont été retenues contre les
  estimations antérieures faites à partir des paramètres.
- **Les poids d'un modèle ont été largement mal rapportés.** Le chiffre de
  1 560,9 Go est une somme d'octets sur 119 fichiers ; deux estimations
  antérieures ont circulé, et un nombre repris sur plusieurs blogs est en
  réalité la taille d'un *autre* modèle. Un dimensionnement matériel fait sur
  ce nombre se tromperait d'un facteur 2,6.
- **Les tailles décimales de quatre modèles sont des conversions
  arithmétiques** depuis des unités binaires : la source ne donnait que les
  binaires pour ceux-là.
- **Aucun score de codage n'est publié du tout** pour sept des vingt-quatre
  entrées, y compris toute la famille Apertus au-delà de sa table 18. Pour
  l'une d'elles, les chiffres de la carte existent mais sont rendus en
  **images** et n'ont pas pu être extraits.
- **Les seuls chiffres de code d'Apertus sont auto-déclarés**, et la métrique
  est environ dix fois plus indulgente que celle que rapportent les modèles
  auxquels il est comparé.
- **Apertus v1.5 n'a aucun rapport technique.** Il était promis « dans les
  semaines à venir » à la sortie du 24 juillet 2026 et il n'existe pas. Il n'y
  a aucun chiffre de qualité pour v1.5, nulle part.
- **On ignore si les forks épinglés qu'exige Apertus v1.5 se construisent en
  ARM64 avec CUDA 13.** C'est la seule question qui décide de sa faisabilité,
  et elle n'est pas tranchée.
- **Le comportement de xIELU sur la capacité de calcul NVIDIA récente n'est pas
  vérifié**, et il conditionne toute la colonne Apertus.
- **Le contexte natif d'un modèle n'a pas été relevé** sur sa fiche, et les
  paramètres actifs d'un autre ne sont pas énoncés sur sa carte.
- **La qualification « Modified MIT » d'un modèle, très reprise, n'a pas pu
  être confirmée** : l'étiquette de la plateforme de publication dit
  `license:other`.
- **Les modèles propriétaires ont été volontairement exclus** de ce relevé, qui
  ne porte que sur les poids ouverts.

### 7.3 Sur la longueur de contexte et les bancs d'essai

- **Une longueur de contexte annoncée est souvent une extrapolation, pas une
  propriété entraînée.** Trois modèles du tableau sont natifs à 262 144 et
  n'atteignent le million que par YaRN ; un autre est un étirement de facteur
  16 depuis une base entraînée à 65 536. L'extension est appliquée par le
  moteur à l'inférence, n'est pas gratuite en qualité, et doit être activée
  explicitement — le modèle ne le fera pas de lui-même.
- **Parmi les modèles ouverts examinés, seuls quatre déclarent un contexte d'un
  million ou plus sans aucune entrée YaRN.**
- **Une annonce d'un million a été rétractée par écrit** par un éditeur, sur
  une famille dont la configuration dit 262 144, dont le README dit 128 K en
  entrée plus 128 K en sortie, dont le rapport technique dit 1 M, et dont l'API
  hébergée s'est arrêtée à 131 072 avec dégradation au-delà de 128 K.
- **La qualité s'effondre avant le chiffre annoncé.** Un banc d'essai
  indépendant de contexte long, sur 26 modèles et huit tranches, mesure une
  décroissance relative moyenne de 24,3 % entre la portée 8K-128K et la portée
  8K-1M ; 8,5 % au mieux, 60,5 % au pire. Sept modèles sur 26 changent de rang,
  avec des intervalles de confiance de 1 à 2 points contre des écarts de 5 à
  16.
- **Ce même banc tronque par le milieu** quand la fenêtre d'un modèle est plus
  courte que la tranche évaluée, donc un mauvais score en portée 1 M peut
  refléter une fenêtre courte plutôt qu'une vraie dégradation. Lisez ces scores
  avec le contexte déclaré de chaque modèle.
- **Un million de jetons est une capacité, pas une fenêtre de travail.**
  Supprimer entièrement la tranche de 1 M économise 54,5 % du budget de jetons
  tout en conservant un rho de Spearman de 0,997 contre le classement complet,
  avec un déplacement de rang maximal de 1. Des sources secondaires situent la
  fenêtre utile en production entre 200 et 400 K, et la capacité effective est
  couramment citée à 60-70 % de la fenêtre annoncée.
- **Les scores de cartes sont indissociables de leur échafaudage**, et l'écart
  entre deux échafaudages peut dépasser l'écart entre deux modèles — les 3,6
  points d'écart qu'un éditeur publie lui-même pour un modèle inchangé en sont
  la preuve.
- **La perte de qualité sous 4 bits n'est mesurée pour aucun de ces modèles**,
  y compris pour les deux versions qui changeraient la réponse en tenant sur
  une seule machine.
- **Ne choisissez pas sur SWE-bench Verified en 2026** : il est saturé à 0,950,
  les grands laboratoires ont cessé de le rapporter, et les modèles ouverts s'y
  agglutinent entre 0,772 et 0,806.
- **La colonne « poids ouverts » d'un classement est fausse en au moins deux
  endroits.** Vérifiez ce statut sur le dépôt de poids, jamais sur la case d'un
  classement.
- **La couche d'optimisation pour moteurs de recherche est activement trompeuse
  sur ce sujet**, comme le décrit la section 1. Traitez un article de synthèse
  comme une piste à vérifier, jamais comme une donnée.