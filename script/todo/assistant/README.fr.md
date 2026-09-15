
# L'assistant LLM — qui répond, et ce qu'on a le droit de lui dire

`script/todo/assistant/` est ce que lance `Assistant › LLM` : il reconnaît le
serveur de modèle qui écoute sur un port, lit ce que ce serveur annonce
savoir faire, garde ceux qu'on a choisis, et tient la conversation.

## Un port dit où frapper, jamais qui répond

C'est la seule chose à comprendre avant de lire une ligne du code. Le port
8080 héberge llama.cpp, LocalAI **et** Open WebUI ; le port 5000 héberge
text-generation-webui **et** TabbyAPI ; `/v1/models` est servi par onze des
douze familles. Un port ouvre donc la question — il n'y répond jamais.

L'identité se lit dans le **corps** d'une réponse, par une échelle de treize
étages sur onze ports, arrêt au premier accord. L'ordre de cette échelle
porte tout le raisonnement. LocalAI réémet l'API native d'Ollama **en
entier** — `/api/tags`, `/api/show`, `/api/ps`, `/api/version` — jusqu'à la
chaîne `Ollama is running` sur `/`. Les points de terminaison qui ressemblent
à ceux d'Ollama n'identifient donc pas Ollama. LocalAI s'écarte le
**premier**, par `GET /readyz`, qu'Ollama ne possède pas et où il rend 404 ;
l'étage Ollama n'est atteignable que parce que cet écart a déjà eu lieu.
Déplacer l'étage LocalAI plus bas nomme « ollama » toutes les machines
LocalAI.

`identify()` est pure — elle ne reçoit que des octets déjà lus — donc l'ordre
de l'échelle se vérifie sans ouvrir une socket. `collect()` ne fait que le
transport, et n'émet que des GET, sans corps et sans en-tête
`Authorization` : un balayage ne doit pouvoir ni charger un modèle, ni
dépenser un jeton.

## Une adresse ne devient jamais du texte de prompt

Un alias SSH, un nom d'hôte, une adresse IP, un nom de VM désignent des
machines qui ne s'annoncent nulle part ailleurs. Chaque serveur retenu porte
donc une **poignée** opaque — `server-1` — attribuée par son rang au
chargement, et c'est la seule forme qui a le droit de circuler : `redacted()`
rend `server-1 (ollama)`, et c'est cela qui peut atteindre une invite, un
argument de commande ou un fichier que le dépôt suit. L'hôte, le port et le
libellé servent à l'affichage du menu et à la configuration privée, et
s'arrêtent là.

La retenue est structurelle parce qu'elle ne **peut pas** être un filtre. Le
détecteur du dépôt reconnaît les adresses, les courriels et les chemins de
compte, et rend une liste vide devant un nom d'hôte, un alias SSH ou un nom
de base de données. Ce qu'aucun garde-fou ne voit passer ne doit pas être en
position de passer.

## Le menu

`Assistant › LLM` porte cinq entrées.

| Entrée | Ce qu'elle fait |
|--------|-----------------|
| Question libre | la conversation avec le serveur en usage, ou le repli distant quand aucun local n'a répondu |
| Outils gpt | le catalogue, les compatibles en tête, choisis par lettre |
| Serveurs connus | lister, choisir, ajouter à la main, supprimer |
| Chercher un serveur… | six sources, de la boucle locale à un réseau saisi |
| Fiche du serveur | ce que le serveur en usage annonce savoir faire |

Les entrées se choisissent par numéro, le catalogue par LETTRE. Une seconde
liste numérotée juste après un menu numéroté invite à retaper une entrée de
menu, et ce dépôt l'a déjà payé une fois. Un chiffre y reste accepté comme
rang, parce que le doigt vient d'en taper un.

Une destination tierce doit être **retapée** avant le premier envoi — une
fois par session, et pour cette destination seulement. Une frappe sur « o »
se donne par réflexe ; recopier l'adresse oblige à regarder où part le
texte.

L'historique de la conversation vit **en mémoire et nulle part ailleurs** —
rien dans `chat.py` n'ouvre un fichier. Il meurt avec le menu, et `/save` est
le seul moyen d'en garder une trace, ce que l'en-tête dit AVANT la
conversation qui méritait d'être gardée. Toute commande porte une barre
oblique initiale et aucun nombre nu n'en est une : une question collée sur
plusieurs lignes devient autant de tours, et une ligne collée valant `0`
déclencherait sinon une entrée de menu.

La découverte d'hôtes au-delà de la boucle locale — domaines QEMU,
`~/.ssh/config`, balayage du `/24` local — repose sur quatre sources, dont
deux sont INJECTÉES : l'énumération des domaines libvirt et la résolution d'un
alias SSH existent déjà comme méthodes de la classe du CLI, que ce paquet n'a
pas le droit d'importer.

Un serveur vit souvent sur un réseau que cette machine ne PORTE pas, joignable
par la passerelle : quand le CLI tourne dans une machine virtuelle, le
« réseau local » qu'il voit est celui de l'hyperviseur. Deux sources y
répondent — un CIDR saisi, et les réseaux lus en SSH sur une autre machine
puis balayés d'ici. La table de voisinage, elle, ne peut pas : elle est
link-local, donc un hôte routé n'y figure jamais.

Plus large qu'un `/24` est refusé, et le refus précède l'énumération —
mesurer un `/8` en le matérialisant coûterait seize millions d'adresses. La
piscine se dimensionne par NOMBRE DE VAGUES et jamais par nombre de cœurs :
ces fils attendent le réseau. Et le délai de connexion est le seul réglage
d'ici qui fabrique des FAUX NÉGATIFS — un hôte joignable en une milliseconde
au repos se manque à cinq centièmes sous mille connexions simultanées, donc il
ne se déduit pas de la latence mesurée.

## Trouver un serveur qui n'est pas là

Quatre sources répondent à « où chercher » : la boucle locale, les domaines
QEMU de cette machine, les hôtes de `~/.ssh/config`, et un `/24` balayé. Deux
d'entre elles sont INJECTÉES — énumérer les domaines libvirt et résoudre un
alias SSH sont déjà des méthodes de la classe du CLI, que ce paquet n'a pas le
droit d'importer.

Un serveur vit souvent sur un réseau que cette machine ne PORTE pas, joignable
par la passerelle : quand le CLI tourne dans une machine virtuelle, le
« réseau local » qu'il voit est celui de l'hyperviseur. Deux sources y
répondent — un CIDR saisi, et les réseaux lus en SSH sur une autre machine
puis balayés d'ici. La table de voisinage, elle, ne le peut pas : elle est
link-local, donc un hôte routé n'y paraît jamais.

Plus large qu'un `/24` est refusé, et le refus a lieu AVANT l'énumération —
mesurer un `/8` en le matérialisant coûterait seize millions d'adresses. La
réserve de fils se dimensionne au NOMBRE DE VAGUES et jamais au nombre de
cœurs : ces fils attendent le réseau. Et le délai de connexion est le seul
réglage d'ici qui fabrique des FAUX NÉGATIFS — un hôte joignable en une
milliseconde au repos se manque à cinq centièmes sous mille connexions
simultanées, donc il ne se déduit pas d'une latence mesurée.

## Le catalogue d'outils gpt

Un gpt est un fichier Markdown : en-tête YAML, invite système, contexte
READ-ONLY déclaré. Rien n'y s'exécute au nom du modèle.

Ses exigences sont confrontées à ce que le serveur annonce, et une règle
gouverne l'affichage : L'INCONNU NE GRISE JAMAIS. Seule une exigence
contredite par un champ réellement lu sur le serveur grise — griser sur
l'inconnu viderait le catalogue devant un serveur qui n'annonce rien,
c'est-à-dire devant la plupart. Une valeur estimée ne grise pas non plus.

`yaml.safe_load` n'est pas un validateur, et cela façonne le chargeur. Un
en-tête qui est une liste rend une liste, un scalaire rend une chaîne, un
fichier vide ne rend rien, et une clé RÉPÉTÉE est résolue en silence sur la
dernière — deux blocs `requires` changeaient donc la classe de sûreté d'un gpt
sans un mot. D'où un contrôle de type et une relecture du texte brut.

Un gpt hors du dépôt est forcé en boucle locale et ne peut déclarer aucune
commande : un fichier que personne n'a relu est de la configuration, pas une
donnée.

## Ce qu'un contexte déclaré a le droit de lire

La liste de refus passe la première et se résout sur le chemin RÉEL : ni
« suivi par git » ni « ignoré par git » n'est une porte utilisable, puisque
`private/` est partiellement suivi et que `tasks/` n'est dans aucun fichier
d'exclusion. Un lien symbolique est donc résolu avant d'être comparé.

Une commande est un argv, jamais une chaîne d'interpréteur, et elle est
confrontée à une liste d'autorisation qui vit dans le dépôt. La substitution
d'une entrée saisie précède ce contrôle, jamais l'inverse : vérifier un
gabarit puis y injecter une valeur vérifierait ce qu'on n'exécute pas.

Chaque octet assemblé passe par le détecteur du dépôt — et sa limite est dite
plutôt que cachée. Il reconnaît les adresses, les courriels et les chemins de
compte. Il ne reconnaît PAS les noms, sauf si une liste les énumère, et cette
liste n'existe pas d'ordinaire. Une absence de trouvaille ne prouve donc rien
sur les noms, et un envoi vers un tiers est REFUSÉ dans ce cas, même sans
aucune trouvaille.

## Où s'écrit un serveur, et ce qui ne s'écrit pas

L'écriture passe par `config_file.set_config_value()`, et par lui seul. Des
trois fichiers que la lecture fusionne, c'est le seul qui soit gitignored :

| Chemin | État |
|--------|------|
| `script/todo/todo.json` | suivi, il suit le dépôt en amont |
| `private/todo/todo_override.json` | non ignoré — commitable, et public sur un fork rendu public |
| `private/todo/todo_override_private.json` | gitignored — là où s'écrit un serveur |

`set_config_value()` fusionne au lieu d'écraser, et écrit atomiquement : un
temporaire créé en 0600 dans le même dossier, puis `os.replace`. Une seule
section est écrite, sous le chemin de clés « assistant › servers », sept
champs par serveur, tous fournis par l'utilisateur ou lus sur le serveur
qu'il a désigné. La poignée n'est pas écrite : elle se rattribue par le rang
au chargement, et un rang figé sur le disque survivrait à la suppression d'un
voisin.

Rien d'autre n'est écrit — **ni rapport de balayage, ni table de qui est
vivant, ni résultat négatif, ni journal horodaté**. La liste de qui a répondu
parmi les 254 adresses d'un `/24` décrit des machines que personne n'a
désignées, là où un serveur retenu en désigne une seule, volontairement.

## Les sessions Claude Code de la machine

Une session ouverte ailleurs porte déjà le contexte d'un travail, et lui poser
une question sans le retaper vaut le détour. Elle vit sous « Assistant › IA »,
dans la section **Agents** et non parmi les serveurs : une session est un
processus adressé par identifiant, un serveur est un hôte adressé par port, et
les mettre dans une même section ferait partager les mêmes chiffres à deux
modèles mentaux.

Cet écran liste les harnais que ce dépôt connaît de nom, et il n'en cache
jamais un. Un harnais dont le binaire manque garde son numéro, grisé, avec ce
qui manque dit sur la même ligne — et la raison distingue deux choses qui
appellent des gestes opposés : un binaire à installer, ou un adaptateur que
personne n'a mesuré. Seul `claude` l'est ; déclarer une action pour les autres
offrirait ce qui échoue.

Deux dangers ont dû être mesurés avant de le proposer. Un pid ne prouve pas
qu'une session vit — les pids se recyclent, donc la vivacité exige le pid ET
le moment de démarrage du processus. Et l'outil ne REFUSE pas de reprendre une
session qu'un terminal tient, son garde-fou écartant les détenteurs
interactifs ; deux écritures scindent alors la transcription et une branche est
orpheline. Une copie est branchée par défaut, et écrire dans une session tenue
exige de retaper le pid du détenteur.

La frontière de vie privée est celle que le système a déjà tracée. Le registre
est lisible par tous, donc pid, répertoire, nom et identifiant n'y sont pas des
secrets. Les transcriptions ne le sont pas : il n'en sort que deux champs de
STRUCTURE — le répertoire de travail et la branche git — jamais un titre, une
invite ou un message. Le répertoire y est LU plutôt que dérivé du nom du
répertoire qui la contient, parce que cette transformation change les
séparateurs, les points et les tirets bas en tirets et ne s'inverse donc pas.

## Ce qu'un agent coûte, et ce qu'il porte

Trois sources y répondent et elles ne se valent pas. L'écran dit de laquelle
vient chaque chiffre, parce qu'un tableau qui mélange une mesure et une
approximation fait accuser le mauvais composant.

**Le disque sait déjà presque tout.** Chaque transcription porte une ligne
`cost-state` — coût en dollars, durée d'horloge, durée d'API, durée d'outils,
lignes de code — et chaque message d'assistant porte son propre `usage` de
jetons. Rien à installer, rien à activer, aucune trace posée. Mais ces lignes
de coût ne sont PAS monotones : une compaction remet le compteur à zéro, et
une transcription porte plusieurs segments dont les champs ne se composent
pas. La dernière est retenue, et l'écran dit que c'en est une.

**Ce que le disque ne sait pas**, c'est QUEL outil, combien de fois et combien
de temps chacun. `totalToolDuration` est un agrégat : il annonce dix-neuf
minutes sans jamais dire que l'un d'eux en prend les trois quarts. Un jeu de
hooks le dit, une ligne par appel — et aucun événement de hook ne porte de
durée, donc deux sont écrits, avant et après, et leur identifiant d'appel les
recoud. Un appel dont l'après manque reste NON APPARIÉ plutôt que de se voir
attribuer une durée inventée.

**Un hook ne doit jamais faire échouer l'appel qu'il observe.** Un code non
nul sur `PreToolUse` BLOQUE l'appel d'outil, donc le script est enveloppé de
bout en bout et sort à zéro quoi qu'il arrive. Il n'importe rien du dépôt non
plus : il tourne des centaines de fois par session, dans un interpréteur neuf
chaque fois.

Ni la commande ni la réponse de l'outil ne sont écrites. Le journal compte des
appels, il ne garde pas ce qu'ils disent. Cela tient même là où la frontière
d'affichage a été levée : ce qui n'est pas écrit n'a pas à être protégé plus
tard.

## Ce qu'une session porte

Un delta n'est pas un état, et c'est le piège de tout ce domaine. Plusieurs
enregistrements sont réémis en cours de session et ne portent que ce qui a
changé : lire la dernière occurrence donne un fichier d'instructions là où
sept sont chargés, et une skill là où trente-neuf le sont. Chacun se corrige
selon sa forme — les instructions s'accumulent par chemin, une liste de skills
retient son entrée initiale — et celui dont la sémantique n'est pas
déterminable n'est jamais totalisé.

L'ancienne règle du paquet, « la structure oui, le contenu d'un message non »,
ne suffit plus : une transcription porte maintenant le texte intégral des
fichiers d'instructions, celui des skills, l'invite système et la sortie brute
d'un hook, dont aucun n'est un message. La forme opérante : **un chemin, un
nom, un compte, une taille ou une durée ; jamais un champ dont la valeur est
du texte libre de longueur non bornée.**

Un environnement se lit sans se recopier. Le noyau réserve déjà
`/proc/<pid>/environ` au propriétaire du processus, et un écran qui en imprime
une valeur en clair casse une frontière que personne n'a eu à écrire. Une
valeur ne s'affiche que si son nom est sur une liste fermée ET que sa valeur a
la forme attendue de ce nom ; le reste montre sa forme. Le caviardage par
motifs employé ailleurs dans le dépôt ne convient pas ici : il ne reconnaît
que `NOM=valeur` collé, et en deux colonnes alignées il laisse passer presque
tout.

## Un second harnais répond à une autre question

Open Code voisine avec Claude Code dans le menu, et les deux se ressemblent
assez pour tromper. Trois différences décident de la forme de son écran, et
chacune a été mesurée contre l'outil plutôt que supposée.

**Son listage est cadré sur le RÉPERTOIRE COURANT.** `claude agents` répond
« ce qui tourne sur cette machine » ; `opencode session list` répond « ce qui
s'est passé ICI », et aucun drapeau n'élargit la portée. L'écran dit donc sa
portée et imprime le répertoire avant de lister quoi que ce soit — sans quoi
il annoncerait « aucune séance » à qui en a vingt dans le dossier d'à côté.

**Le titre d'une séance est ENGENDRÉ par le modèle** à partir de la
conversation. Il a la forme d'un champ structurel et n'en est pas un, donc il
ne sort pas de l'adaptateur — la même règle qui garde hors de l'écran le titre
d'une session de Claude Code. Ce qui situe une séance sans la citer est son
identifiant et sa date ; la colonne du répertoire disparaît, puisqu'elle
répète celui que l'en-tête vient d'imprimer.

**Deux sources répondent, et elles ne pèsent pas pareil.** La base SQLite que
l'outil tient porte tout — coût, jetons, cache, lignes touchées, modèle,
agent, dates — en une lecture de moins d'une milliseconde, sur TOUTES les
séances. Les deux commandes du CLI demandent près de deux secondes pour moins,
et l'une des deux se tronque. La base est donc lue d'abord et le CLI sert de
repli, son schéma étant celui d'un tiers que personne ne promet stable.
L'écran nomme celle qui a répondu, car seule la base sait sortir du répertoire
courant.

**Ce même fichier porte des secrets, et c'est ce qui borne la lecture.** Il
tient les jetons d'accès et de rafraîchissement du compte, son adresse, et les
invites tapées par l'utilisateur. Une seule table est donc nommée, ses
colonnes énumérées une à une, l'ouverture en lecture seule, et un test refuse
toute autre table comme toute colonne d'authentification. `immutable=1` est
refusé aussi : il ignore le journal d'écriture anticipée, qui pèse ici
plusieurs mégaoctets, et rend ZÉRO ligne sur une base pleine — une réponse
fausse plutôt qu'une erreur, ce qui est pire.

**Seule la lecture est déclarée.** `opencode run` écrit dans l'arbre de
travail sans demander — une consigne de trois mots suffit à faire créer un
fichier — donc une entrée « question libre » y serait un piège. Elle reste au
CLI, où l'on va exprès, comme `delete`, `uninstall` et `upgrade`.

Deux formes de sortie piègent le décodage, et l'écran nomme le coupable au
lieu de s'accuser. Un listage VIDE n'est pas `[]`, donc le décoder lève ; et
`export` tronque sa propre sortie au-delà d'une soixantaine de kilooctets, en
sortant avant d'avoir vidé son tampon — trois exécutions du même export
rendent trois tailles, toutes coupées au milieu d'une chaîne. L'écran dit
qu'Open Code a coupé, ce qu'il faut savoir pour cesser de chercher un défaut
ici.

L'écran vivant de télémétrie montre les deux harnais dans un seul tableau,
chaque ligne marquée de l'icône du sien. Ce qu'Open Code ne mesure pas — les
tours, le contexte et sa pente, les durées d'API et d'outils — affiche un
TIRET et jamais un zéro : une colonne à zéro se lit « mesuré, et nul », ce qui
est faux et décourage de chercher ailleurs ce que l'autre harnais donne. La
ligne de résumé garde les deux séparés plutôt que de les fondre en un total,
le coût de Claude Code étant lu dans un `cost-state` qu'une compaction remet à
zéro là où celui d'Open Code est un champ de base stable.

**Le temps passé n'est pas le temps écoulé, et le tableau montre le premier.**
L'horloge d'une session compte tout ce qui s'est écoulé, y compris les heures
où personne ne regardait — elle annonce des centaines d'heures dès qu'une
session reste ouverte plusieurs jours. La colonne d'attention somme plutôt les
écarts entre événements de hook, chaque écart borné par un seuil d'inactivité
que ce paquet choisit et nomme. Rien n'est collecté pour elle : le journal des
hooks porte déjà l'instant de chaque événement. Sans hooks posés, la colonne
affiche un tiret et jamais un zéro, un zéro disant « cette session n'a pas
travaillé » là où la vérité est « rien n'est mesuré ».

**La série temporelle était sur le disque depuis le début.** Chaque message
d'assistant porte son instant et son modèle — présents sur les dix mille
échantillonnés. Les jetons par jour et par modèle viennent donc d'une somme de
messages et non de la lecture d'un `cost-state` : aucune compaction ne les
remet à zéro, aucun segment ne s'y perd, et ils s'additionnent d'une session à
l'autre sans la réserve qui pèse sur le coût. Le jour se lit en UTC comme la
transcription l'écrit ; le convertir en heure locale déplacerait des messages
d'un jour à l'autre selon qui regarde.

**Un appel d'outil finit de quatre façons, et l'écran les distingue.** Il est
fini, il a échoué, il a été interrompu, ou rien ne l'a jamais clos. Un seul
compte pour les quatre donnait un chiffre auquel aucun geste ne répond : un
échec se corrige, une interruption se relance, et un appel sans clôture ne dit
rien du tout. L'événement `PostToolUseFailure` porte la différence dans son
`is_interrupt`.

**La durée est celle que l'outil a mesurée, et non l'écart entre deux
instants.** Cet écart INCLUT le temps passé devant une demande d'autorisation,
donc un appel approuvé au bout de quatre minutes se lisait comme un appel de
quatre minutes et majorait la médiane par outil. L'événement de clôture porte
`duration_ms` ; l'écart ne reste qu'en repli, pour un binaire qui ne la porte
pas. Les deux champs sont numériques, et un filtre à chaînes les écartait en
silence — le défaut que le module voisin avait déjà payé sur le code de sortie
d'un hook.

**Le panneau du bas PERMUTE au lieu de s'empiler.** Un terminal n'a pas la
hauteur pour trois tableaux, et les empiler les réduirait à quatre lignes
chacun. La touche `v` fait le tour : par outil, qui répond à « lequel est
lent », et le flux des derniers appels, qui répond à « pourquoi ça bloque
depuis deux minutes ». Ni l'un ni l'autre ne montre de contenu — un nom
d'outil, une durée, une fin. La colonne de fin reste vide pour un appel
réussi, cas ordinaire qui n'a rien à signaler, et les trois mauvaises fins se
nomment au singulier : une ligne décrit un appel, là où le tableau par outil
en compte plusieurs.

**L'écran agit, et dit ce qu'il ne peut pas faire.** Un troisième panneau
liste les agents détachés qui tournent — vivants ET détachés, car la flotte
réunit deux sources : le registre annonce ce qui TOURNE, un balayage des
transcriptions annonce ce qui se REPREND, et une session dormante en sort sans
genre ni processus. L'offrir proposerait `stop` sur un fichier, et l'outil
répond « No job matching » avec un code de sortie NUL — rien ne paraîtrait
avoir échoué.

`n` lance un agent, son invite lue sur l'entrée standard et jamais dans l'argv,
où `/proc/<pid>/cmdline` l'expose à tout compte. `s` arrête celui qui est
surligné — sa conversation est gardée, donc rien à confirmer. `a` attache et
FERME donc l'écran : `claude attach` prend le terminal et ne peut pas le
partager. Une touche pressée dans un autre panneau ne fait rien, plutôt que
d'agir sur une ligne surlignée que personne ne voit.

**Le flux montre la commande, et rien n'a été collecté pour ça.** « Bash ·
1,2 s · échec » dit qu'une chose a raté sans dire laquelle. Le journal des
hooks garde `tool_use_id` et rien d'autre de l'appel — ni la commande, ni la
réponse — parce qu'y écrire `tool_input` mettrait chaque commande shell sur le
disque pour quatorze jours, ce qui est garder et non montrer. La commande est
relue dans la TRANSCRIPTION, où Claude Code l'avait déjà mise, au moment où
quelqu'un la demande. Trois centièmes de seconde par recherche dans trente
mégaoctets : le pré-filtre par sous-chaîne fait tout le travail.

Un piège s'ajoute, et il cache un appel sur trois : un outil lancé par un
SOUS-AGENT s'écrit dans le fichier de celui-ci, sous le répertoire de la
session, alors que le hook l'annonce sous l'identifiant de la session PARENTE.
Les deux endroits sont donc balayés, la transcription principale d'abord.

Un volet de détail s'ouvre sur l'appel surligné et montre la commande avec sa
sortie. C'est le seul volet du paquet qui affiche du contenu, alors il le dit,
en première ligne plutôt qu'en dernière — une longue sortie pousserait
l'avertissement hors de l'écran.

**Les tableaux tiennent dans le terminal, parce qu'ils y ont été mesurés.**
Les colonnes s'étaient accumulées une par fonctionnalité sans que personne
regarde la largeur : douze en réclamaient cent vingt-quatre, et le flux
quatre-vingt-quinze dont cinquante-cinq pour la seule commande. Un terminal de
quatre-vingts colonnes — le défaut le plus répandu — n'en montrait ni l'un ni
l'autre. Rien n'était cassé, Textual fait défiler ; mais un tableau de bord
qu'il faut faire défiler ne se lit plus d'un coup.

Deux correctifs, mesurés tous les deux. La colonne de commande prend CE QUI
RESTE plutôt qu'un soixante fixe, donc elle ne déborde plus d'un terminal
étroit et ne gaspille plus celui d'un large. Et le tableau des sessions ne
montre que les colonnes qui tiennent, par ordre d'importance — quelle session,
quel projet, combien ça coûte, où en est son contexte —, refaites seulement
quand leur nombre change, les recréer à chaque tour remettant le curseur en
haut sous les doigts de qui lit. Un nom de projet se coupe par la GAUCHE : une
famille de dépôts partage son préfixe et se distingue par ce qui suit.

## Les modules

| Fichier | Ce qu'il porte |
|---------|----------------|
| `__init__.py` | les deux règles qui gouvernent tout ce qui suit |
| `fingerprint.py` | qui répond sur un port : l'échelle, et son transport |
| `capabilities.py` | ce qu'un serveur annonce savoir faire, en trois paliers d'honnêteté, et l'appariement d'une exigence |
| `servers.py` | les serveurs retenus : poignées opaques, lecture et écriture |
| `backends.py` | parler à une destination : un serveur HTTP, ou le CLI `claude` |
| `chat.py` | les tours d'une conversation, et les commandes qui la pilotent |
| `discover.py` | quels couples (hôte, port) méritent une reconnaissance, et la frappe |
| `gpt.py` | le catalogue : charger, refuser, et ne jamais casser le menu |
| `context.py` | ce qu'un contexte déclaré peut lire, et ce que la porte autorise |
| `claude_sessions.py` | les sessions Claude Code de la machine : lesquelles vivent |
| `harness/registre.py` | quels harnais d'agent cette machine porte, et ce qui manque aux autres |
| `harness/claude.py` | l'argv des cinq sous-commandes d'un agent détaché, et ce que chacune coûte |
| `harness/opencode.py` | les séances d'Open Code et leur coût, en lecture seule, et les trois formes que prend sa sortie |
| `agents/detail.py` | la commande et la réponse d'un appel, relues dans la transcription et jamais collectées |
| `agents/statistiques.py` | ce qu'une transcription dit d'une session : jetons, coût, durées, contexte |
| `agents/tui.py` | l'écran vivant, rafraîchi sans relire ce qu'il a déjà replié |
| `agents/journal.py` | le journal des appels d'outils : une ligne par événement, et leur appariement |
| `agents/hooks/evenement.py` | le hook qui écrit un événement, et ne doit jamais faire échouer l'appel |
| `agents/pose.py` | poser et retirer les hooks, à l'un ou l'autre des deux endroits |
| `agents/disque.py` | ce que Claude Code occupe, par répertoire et par session |
| `agents/mcp.py` | les serveurs MCP : ce qui est déclaré ici, et ce qu'il faut demander |
| `agents/contexte.py` | ce qu'une session a chargé : modèle, machine, instructions, skills |
| `agents/environnement.py` | l'environnement d'un processus, lu sans le recopier |
| `../assistant_menu.py` | le mixin : demander et afficher, hors du paquet |

Aucun de ces modules n'importe `todo.py`, qui coûte près d'une seconde et
imprime en arrivant. C'est le mixin du menu qui les branche sur le CLI, et un
test par sous-processus dans `test_assistant_menu.py` tombe en rouge le jour
où l'un d'eux y touche.

## Tests

```bash
make test_unit_file F=test/test_assistant_fingerprint.py
PYTHONPATH=. ./.venv.erplibre/bin/python test/test_assistant_servers.py
for f in test/test_assistant_*.py; do
  PYTHONPATH=. ./.venv.erplibre/bin/python "$f"
done
```