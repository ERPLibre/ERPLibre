
# Apertus — le LLM ouvert, sur sa propre machine

Apertus est un grand modèle de langage qu'ERPLibre sait installer pour vous,
ici ou sur un serveur qui vous appartient, puis avec lequel le CLI TODO
discute. Tout le chemin tient dans une entrée de menu :
`TODO › Assistant › IA › Apertus`.

Ce guide dit ce qu'est le modèle, quelle variante et quel moteur choisir, ce
que ça coûte en disque et en mémoire, comment le menu l'installe et — tout
aussi important — ce qui n'est **pas** officiel dans ce chemin.

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

Un Mini **4 B** existe aussi en amont (`swiss-ai/Apertus-v1.1-4B-Instruct`,
mêmes 4096 jetons), mais aucune version GGUF n'en a été trouvée : le menu ne
le propose donc pas.

Des quantifications officielles sont publiées pour **MLX** (INT3/INT4/INT6,
Apple Silicon) et pour **vLLM** (NVFP4A16). Il n'existe **aucun GGUF
officiel** — voir la section 8.

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

## 4. Choisir un moteur

Un moteur est le programme qui charge les poids et les sert sur une API HTTP
compatible OpenAI. Quatre sont proposés, tous libres :

| Moteur | Licence | Port par défaut | Version minimale | À qui il convient |
|---|---|---|---|---|
| **Ollama** | MIT | 11434 | **0.12.6** | à qui débute — une commande d'installation, un service systemd, et le seul moteur qui rapporte une vraie progression de téléchargement |
| **llama.cpp** | MIT | 8080 | construction **b6671** | une machine sans droits d'administration, ou quand on veut choisir soi-même la quantification |
| **LocalAI** | MIT | 8080 | **4.0.0** | un hôte qui sert déjà plusieurs modèles derrière une seule porte |
| **vLLM** | Apache-2.0 | 8000 | **0.10.2** | une machine à GPU servant plusieurs utilisateurs à la fois |

Le défaut est **Ollama**, et c'est la bonne réponse pour une première
installation.

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