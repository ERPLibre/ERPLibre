<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Set-OPS — the declared engine and the state of the integration

Five modules, one split: **the survey touches the system, the decision
does not.** Neither imports the engine's code: it is read through files and
subprocesses. Nothing here asks a question; the menu lives in
`script/todo/setops_menu.py`, and the user manual in
[../../doc/SETOPS.md](../../doc/SETOPS.md).

## `engine` — the manifest is the only authority

`manifest/git_manifest_setops.xml` carries the engine's path and its pinned
revision. The manifest merge, the fetch script and the state screen READ
them here instead of keeping a copy, which would drift at the first move.

These functions work on text only:

- `parse_manifest(texte)`: the engine's `Declaration` — path, revision,
  upstream, remote — or `None`. The engine is THE project of the `setops`
  group: none, or two, and nothing is declared. Its path stays under the
  workspace root, neither absolute nor climbing through `..`, and comes
  back normalised;
- `groups_of(texte)`: the groups of a `groups` attribute, split as Google
  Repo splits them, on commas AND whitespace;
- `mise_de_cote(chemin)`: the `mv` that sets the folder at `chemin` aside
  as `<chemin>.manuel`, quoted to be copied as is;
- `is_pinned(revision)`: true for a full 40-hex SHA only — a branch, a tag
  or a short SHA names something else tomorrow;
- `ignore_probe(chemin)`: the path `parent_is_ignored` asks git about — an
  invented name directly under the parent, since a `folder/` rule only
  applies to a folder and git cannot tell that a path missing from the disk
  is one: the probe answers on a fresh clone too.

The others read the disk or run `git`, and never raise: an unknown verdict
is `None` — or the `inconnue` relation — and the caller decides what to
say. Git never climbs above the folder it is given
(`GIT_CEILING_DIRECTORIES`): a folder without `.git` under ERPLibre's
checkout would otherwise answer with ERPLibre's own HEAD.

- `declaration(racine)`: `parse_manifest` applied to the manifest under
  `racine`;
- `managed_by_repo(racine, chemin)`: does `.repo/project.list` list
  `chemin`? `None` without `.repo/` or with an unreadable list, `False`
  when there is no list yet. The list says what the last sync AIMED at:
  Google Repo writes it even when the fetch fails;
- `repo_worktree(racine, chemin)`: did Google Repo LAY OUT the tree there?
  True when its `.git` — a link, or a `gitdir:` file — resolves under
  `.repo/`; False for a real `.git` folder, as a manual clone has, or for
  no `.git` at all; `None` when the `gitdir:` file cannot be read;
- `relation_to_pin(moteur, sha)`: where the clone's HEAD stands against the
  pin, and how many commits apart;
- `dirty_count(moteur)`: the entries of `git status --porcelain`, untracked
  files included;
- `parent_is_ignored(racine, chemin)`: are the engine's sibling folders
  ignored by the rules of the repository at `racine`, asked with
  `git check-ignore --no-index` about `ignore_probe(chemin)`?

Where the clone's HEAD stands against the pin, from local objects only and
without network, is a closed vocabulary: `egal`, `avance`, `retard`, `diverge`, `absente`, `inconnue`.
Only `absente` is a finding about the pin — git reads the clone and the
pinned commit is not in it, which a resynchronization settles; the last
term, `inconnue`, establishes nothing.

The entry point, `main`, serves the fetch script, run from ERPLibre's root.
`chemin` prints the declared path; `verifier-emplacement` returns `0` when
the path is free, or when Google Repo lists it AND laid out the tree there,
and `3` otherwise — a manual clone, even at a listed path, or a folder
without `.git` — printing the command that moves it aside. Both return `2`
without a readable declaration. Nothing is ever deleted nor moved here.

## `state` — ten lines, decided on a survey

`releve(racine)` touches the system once — files, `git`, and at most two
bounded subprocesses in an environment built from scratch — and never
raises. The ansible-core version is asked of the dedicated venv's Python
only when the venv has its `ansible-playbook`. `scripts/voutes.py etat`
runs only with an ecosystem mounted AND its `plan/serveurs.yml`, the
prerequisite of the only line that reads its code, and with `-B`: the
survey writes nothing in the engine, not even the bytecode of its modules.

`lignes(vu)` is PURE: every verdict can be tested without a machine,
including those that cannot be provoked on the station. The prerequisites
are declared once, in `PREALABLES`; a line whose prerequisite is not held
names it and gives no other verdict, and an unknown verdict is never
carried. Each line names its source, its paths relative to ERPLibre's
root.

The lines are printed by `script/todo/state_screen.py`, the render shared
with the Devstack state screen: two renders would say, sooner or later, two
different things with the same marks.

## `ansible_env` — what the engine requires, and how to set it up

The engine sets up no controller: its `serveur_ops` role equips a TARGET, not
the station that drives it. This module sets up the controller's venv,
`.venv.todo.setops`, READING in the engine everything that can be read — the
ansible-core range, the pinned Python libraries, the pinned collections. None
of those values is copied here.

**The Python minor is a constraint, not a taste.** `serveur_ops` requires that
controller and target share their `major.minor`, and it builds the offline
wheel cache with the `python3` found on the PATH — not with Ansible's
interpreter. A controller on 3.14 therefore produces `cp314` wheels that a
3.13 target refuses. Hence two things this module holds together: the venv is
built with `MINEUR_CIBLE`, and `environnement(racine, moteur, base)` puts its `bin` FIRST on the
PATH.

The collections land under the engine, in a folder its own `.gitignore`
covers: its tree stays clean, and they do not mix with whatever the station
already carries. The engine's `ansible.cfg` declares no `collections_path`,
so the environment names it.

Two readings are distinguished on purpose: an empty tuple says "the engine
pins nothing", `None` says "we cannot tell". Confusing them would let the
state line be carried on an unreadable file, announcing zero drift — the
worst verdict, since it reassures.

What the engine declares, read as text:

- `plage_ansible(moteur)`: the `serveur_ops_ansible` requirement, exactly as
  the engine writes it — it reaches pip unrephrased, so a disagreement shows
  instead of silently correcting itself;
- `bibliotheques_epinglees(moteur)` and `collections_epinglees(moteur)`: the
  (name, version) the engine pins, `None` when the file does not read;
- `specifieur(texte)`, `version(texte)` and
  `dans_la_plage(version_texte, plage_texte)`: the readings the state screen
  and the check share, so both say the same thing about the same version.

What the station offers, and what setting up costs:

- `interprete(mineur)`: a usable Python and where it comes from — the PATH
  first, a version manager next, nothing at all last;
- `geste_mise(mineur)`: the command that would install it, NAMED so it can
  be shown; the menu installs no version manager behind your back;
- `chemin_venv(racine)`: the venv, as an ABSOLUTE path — the probes run
  with `cwd` inside it, and a relative argv would resolve under itself;
- `etapes(racine, moteur, python, plage, refaire)`: the gestures, in order.
  `refaire` opens with the removal, the only way to change the INTERPRETER
  of a venv already there;
- `montre(etape)`: the line to print, DERIVED from the argv — what is shown
  is what is run;
- `environnement(racine, moteur, base)`: the venv first on PATH, and the
  collections named;
- `version_posee(racine, paquet)`, `version_collection(moteur, nom)` and
  `mineur_du_path(racine, moteur)`: what is really there. The last one asks
  a BARE `python3`, which is what the engine's guard does;
- `poser(etape, racine, env)`: plays one step and returns its code; output
  is not captured, since a setup takes minutes. The launch itself goes
  through `runner`, below — one way to run a gesture, and only one.


## `runner` — one way to run a gesture, and only one

Three rules, each repairing a precise way of getting it wrong.

**The environment is built from scratch**, never inherited. Inherited, it
carries three things that decide in the operator's place: a `CONFIRMER=true`
left over from an earlier gesture, which the engine's appliers read as an
order to write instead of simulate; the parent make's overrides
(`MAKEFLAGS`, `MAKELEVEL`), since TODO launches itself through `make todo`;
and the `ANSIBLE_*` or `SETOPS_*` the engine lets win over its own defaults
— including the one naming the cluster a destructive gesture would hit.

**The command carries its `CONFIRMER`**, in plain sight, on the line that is
shown. A variable passed to `make` on the command line reaches the called
script's environment AND beats the inherited one: the line shown is the line
that decides.

**The verdict is read**, code AND output. Several engine gestures return 0
having found a drift, so the code alone does not do.

This layer knows nothing of Ansible: the environment of an engine gesture is
composed by the caller, `environnement(racine, moteur, base)` over `base(source)`.
That way there is one process runner in the package, and the dependency goes
one way only.

- `base(source)`: the whitelist alone, PATH stripped of ERPLibre's venv;
- `sans_venv_erplibre(path)`: that stripping, judged on whole path
  SEGMENTS — judging on substrings would cut a neighbouring folder;
- `cible(moteur, nom, variables, confirmer)`: the argv of a `make` target,
  `CONFIRMER` always written, last;
- `cite(argv)`: the line to show, derived from the argv;
- `jouer(argv, env, cwd, capture, delai, fusionner)`: runs and returns a
  `Verdict`
  whose `code` is `None` when the process could not run at all — that is a
  verdict, not the absence of one.

## `ecosystems` — reading what the engine prints, never guessing

The engine offers no `--json`: `instances`, `instance-courante` and
`instance-modeles` print a table and sentences meant for a human. This layer
reads them, and **refuses rather than guesses**. An unexpected shape returns
`None`, never a partial list: the name read is used to SWITCH the active
ecosystem, and a name cut wrong switches to something else.

`()` and `None` are two different pieces of news — "nothing to mount, create
one" and "the engine answered something this version does not know how to
read". A caller given `None` says so and names the line to replay by hand.

- `lit_instances(sortie)`: the discovered ecosystems. The first column holds
  the mounted marker and is read by POSITION; the rest by its blanks, five
  fields exactly;
- `lit_courante(sortie)`: the mounted ecosystem's name, reduced to the last
  segment — what `instance-utiliser` expects back;
- `lit_modeles(sortie)`: the templates and the federated indexes already
  taken; the sentence carrying them is what says the output is the one we
  think we are reading;
- `index_libre(pris, mini, maxi)`: the smallest free index. A PROPOSAL only:
  the engine validates what it receives and refuses a federated collision;
- `monte(moteur)`: the mounted name, read on the link, launching nothing —
  it heads every screen that acts. A BROKEN link keeps its name, so a screen
  can say "mounted on X, which is gone" rather than "nothing".

<!-- [fr] -->
# Set-OPS — le moteur déclaré et l'état de l'intégration

Cinq modules, un partage : **le relevé touche le système, la décision ne le
touche pas.** Aucun n'importe le code du moteur : il se lit par fichiers et
sous-processus. Rien ici ne pose de question ; le menu vit dans
`script/todo/setops_menu.py`, et le mode d'emploi dans
[../../doc/SETOPS.fr.md](../../doc/SETOPS.fr.md).

## `engine` — le manifeste est la seule autorité

`manifest/git_manifest_setops.xml` porte le chemin du moteur et sa révision
épinglée. La fusion des manifestes, le script de rapatriement et l'écran
d'état les LISENT ici au lieu d'en garder une copie, qui divergerait au
premier déplacement.

Ces fonctions ne travaillent que sur du texte :

- `parse_manifest(texte)` : la `Declaration` du moteur — chemin, révision,
  upstream, remote — ou `None`. Le moteur est LE projet du groupe
  `setops` : aucun, ou deux, et rien n'est déclaré. Son chemin reste sous
  la racine de l'espace de travail, ni absolu ni remontant par `..`, et
  revient normalisé ;
- `groups_of(texte)` : les groupes d'un attribut `groups`, découpés comme
  Google Repo les découpe, sur les virgules ET les blancs ;
- `mise_de_cote(chemin)` : le `mv` qui met de côté le dossier posé en
  `chemin` sous `<chemin>.manuel`, cité pour être recopié tel quel ;
- `is_pinned(revision)` : vrai pour un SHA complet de 40 hex seulement —
  une branche, un tag ou un SHA abrégé désignent demain autre chose ;
- `ignore_probe(chemin)` : le chemin sur lequel `parent_is_ignored`
  interroge git — un nom inventé directement sous le parent, parce qu'une
  règle `dossier/` ne vaut que pour un dossier et que git ne sait pas qu'un
  chemin absent du disque en est un : la sonde répond aussi sur un clone
  neuf.

Les autres lisent le disque ou lancent `git`, et ne lèvent jamais : un
verdict inconnu vaut `None` — ou la relation `inconnue` —, et l'appelant
décide quoi en dire. Git ne remonte jamais au-dessus du dossier qu'on lui
donne (`GIT_CEILING_DIRECTORIES`) : un dossier sans `.git` sous le checkout
d'ERPLibre répondrait sinon avec le HEAD d'ERPLibre lui-même.

- `declaration(racine)` : `parse_manifest` appliqué au manifeste sous
  `racine` ;
- `managed_by_repo(racine, chemin)` : `.repo/project.list` porte-t-il
  `chemin` ? `None` sans `.repo/` ou devant une liste illisible, `False`
  tant qu'il n'y a pas de liste. La liste dit ce que le dernier sync
  VISAIT : Google Repo l'écrit même quand le rapatriement échoue ;
- `repo_worktree(racine, chemin)` : Google Repo y a-t-il POSÉ l'arbre ?
  Vrai quand son `.git` — un lien, ou un fichier `gitdir:` — mène sous
  `.repo/` ; faux pour un vrai dossier `.git`, celui d'un clone manuel, ou
  sans `.git` du tout ; `None` quand le fichier `gitdir:` ne se lit pas ;
- `relation_to_pin(moteur, sha)` : où se tient le HEAD du clone face à
  l'épingle, et à combien de commits ;
- `dirty_count(moteur)` : les entrées de `git status --porcelain`, fichiers
  non suivis compris ;
- `parent_is_ignored(racine, chemin)` : les dossiers frères du moteur
  sont-ils ignorés par les règles du dépôt `racine`, question posée par
  `git check-ignore --no-index` sur `ignore_probe(chemin)` ?

Où se tient le HEAD du clone face à l'épingle, lu dans les seuls objets
locaux et sans réseau, est un vocabulaire clos : `egal`, `avance`, `retard`, `diverge`, `absente`, `inconnue`.
Seule `absente` est un constat sur l'épingle — git lit le clone et le
commit épinglé n'y est pas, ce qu'une resynchronisation règle ; le
dernier terme, `inconnue`, n'établit rien.

Le point d'entrée, `main`, sert le script de rapatriement, lancé depuis la
racine d'ERPLibre. `chemin` écrit le chemin déclaré ;
`verifier-emplacement` rend `0` quand le chemin est libre, ou quand Google
Repo le liste ET y a posé l'arbre, et `3` sinon — un clone manuel, même à
un chemin listé, ou un dossier sans `.git` —, en écrivant la commande qui
le met de côté. Les deux rendent `2` sans déclaration lisible. Rien n'est
jamais supprimé ni déplacé ici.

## `state` — dix lignes, décidées sur un relevé

`releve(racine)` touche le système une fois — fichiers, `git`, et au plus
deux sous-processus bornés dans un environnement construit à neuf — et ne
lève jamais. La version d'ansible-core n'est demandée au Python du venv
dédié que si le venv a son `ansible-playbook`. `scripts/voutes.py etat` ne
se lance qu'avec un écosystème monté ET son `plan/serveurs.yml`, le
préalable de la seule ligne qui lit son code, et avec `-B` : le relevé
n'écrit rien dans le moteur, pas même le bytecode de ses modules.

`lignes(vu)` est PURE : chaque verdict s'éprouve sans machine, y compris
ceux qu'on ne sait pas provoquer sur le poste. Les préalables se déclarent
une fois, dans `PREALABLES` ; une ligne dont le préalable n'est pas tenu le
nomme sans autre verdict, et un verdict inconnu n'est jamais porté. Chaque
ligne nomme sa source, ses chemins relatifs à la racine d'ERPLibre.

Les lignes s'impriment par `script/todo/state_screen.py`, le rendu commun
avec l'écran d'état Devstack : deux rendus diraient tôt ou tard deux choses
différentes avec les mêmes marques.

## `ansible_env` — ce que le moteur exige, et comment le poser

Le moteur ne pose pas de contrôleur : son rôle `serveur_ops` équipe une CIBLE,
et non le poste qui la pilote. Ce module pose le venv du contrôleur,
`.venv.todo.setops`, en LISANT dans le moteur tout ce qui s'y lit — la plage
d'ansible-core, les bibliothèques Python épinglées, les collections
épinglées. Aucune de ces valeurs n'est recopiée ici.

**Le mineur de Python est une contrainte, pas un goût.** `serveur_ops` exige
que contrôleur et cible partagent leur `major.minor`, et il fabrique le cache
de roues hors ligne avec le `python3` du PATH — pas avec l'interpréteur
d'Ansible. Un contrôleur en 3.14 produit donc des roues `cp314` qu'une cible
en 3.13 refuse. D'où deux exigences que ce module tient ensemble : le venv est
posé dans `MINEUR_CIBLE`, et `environnement(racine, moteur, base)` met son `bin` en TÊTE du PATH.

Les collections vont sous le moteur, dans un dossier que son propre
`.gitignore` couvre : son arbre reste propre, et elles ne se mêlent pas à ce
que le poste porte déjà. L'`ansible.cfg` du moteur ne déclare aucun
`collections_path`, donc l'environnement le nomme.

Deux lectures sont distinguées exprès : un tuple vide dit « le moteur
n'épingle rien », `None` dit « on ne sait pas ». Les confondre ferait porter
la ligne d'état sur un fichier illisible, en annonçant zéro écart — le pire
des verdicts, puisqu'il rassure.

Ce que le moteur déclare, lu comme du texte :

- `plage_ansible(moteur)` : l'exigence `serveur_ops_ansible`, telle que le
  moteur l'écrit — elle part à pip sans être reformulée, pour qu'un désaccord
  se voie plutôt que de se corriger en silence ;
- `bibliotheques_epinglees(moteur)` et `collections_epinglees(moteur)` : les
  (nom, version) que le moteur épingle, `None` quand le fichier ne se lit pas ;
- `specifieur(texte)`, `version(texte)` et
  `dans_la_plage(version_texte, plage_texte)` : les lectures que l'écran
  d'état et la vérification partagent, pour que les deux disent la même
  chose de la même version.

Ce que le poste offre, et ce que la pose coûte :

- `interprete(mineur)` : un Python utilisable et d'où il vient — le PATH
  d'abord, un gestionnaire de versions ensuite, rien du tout en dernier ;
- `geste_mise(mineur)` : la commande qui le poserait, NOMMÉE pour être
  montrée ; le menu ne pose aucun gestionnaire de versions dans votre dos ;
- `chemin_venv(racine)` : le venv, en chemin ABSOLU — les sondes tournent
  avec `cwd` dedans, et un argv relatif s'y résoudrait sous lui-même ;
- `etapes(racine, moteur, python, plage, refaire)` : les gestes, dans
  l'ordre. `refaire` ouvre par la suppression, seule façon de changer
  l'INTERPRÉTEUR d'un venv déjà là ;
- `montre(etape)` : la ligne à imprimer, DÉRIVÉE de l'argv — ce qui est
  montré est ce qui est lancé ;
- `environnement(racine, moteur, base)` : le venv en tête du PATH, et les
  collections nommées ;
- `version_posee(racine, paquet)`, `version_collection(moteur, nom)` et
  `mineur_du_path(racine, moteur)` : ce qui est réellement là. La dernière
  interroge un `python3` NU, ce que fait la garde du moteur ;
- `poser(etape, racine, env)` : joue une étape et rend son code ; la sortie
  n'est pas capturée, une pose durant des minutes. Le lancement lui-même
  passe par `runner`, en dessous — une seule façon de lancer un geste.

## `runner` — une seule façon de lancer un geste

Trois règles, et chacune répare une façon précise de se tromper.

**L'environnement est construit à neuf**, jamais hérité. Hérité, il porte
trois choses qui décident à la place de l'opérateur : un `CONFIRMER=true`
resté d'un geste précédent, que les applicateurs du moteur lisent comme un
ordre d'écrire au lieu de simuler ; les surcharges du make parent
(`MAKEFLAGS`, `MAKELEVEL`), puisque TODO se lance lui-même par `make todo` ;
et les `ANSIBLE_*` ou `SETOPS_*` que le moteur laisse gagner sur ses propres
défauts — dont celui qui désigne la grappe qu'un geste destructeur viserait.

**La commande porte son `CONFIRMER`**, en clair, sur la ligne qu'on affiche.
Une variable passée à `make` sur la ligne de commande arrive dans
l'environnement du script appelé ET l'emporte sur celle qui serait héritée :
la ligne montrée est la ligne qui décide.

**Le verdict se lit**, code ET sortie. Plusieurs gestes du moteur rendent 0
en ayant trouvé un écart : le code seul ne suffit pas.

Cette couche ignore Ansible : l'environnement d'un geste du moteur se compose
chez l'appelant, `environnement(racine, moteur, base)` par-dessus `base(source)`.
Il n'y a ainsi qu'un lanceur dans le paquet, et la dépendance ne va que dans
un sens.

- `base(source)` : la liste blanche seule, PATH débarrassé du venv
  d'ERPLibre ;
- `sans_venv_erplibre(path)` : ce retrait, jugé sur des SEGMENTS de chemin
  entiers — juger par sous-chaîne couperait un dossier voisin ;
- `cible(moteur, nom, variables, confirmer)` : l'argv d'une cible `make`,
  `CONFIRMER` toujours écrit, en dernier ;
- `cite(argv)` : la ligne à montrer, dérivée de l'argv ;
- `jouer(argv, env, cwd, capture, delai, fusionner)` : joue et rend un
  `Verdict` dont
  le `code` vaut `None` quand le processus n'a pas pu tourner — c'est un
  verdict, pas l'absence de verdict.

## `ecosystems` — lire ce que le moteur imprime, sans jamais deviner

Le moteur n'offre pas de `--json` : `instances`, `instance-courante` et
`instance-modeles` impriment un tableau et des phrases, faits pour un humain.
Cette couche les lit, et **refuse plutôt que de deviner**. Une forme
inattendue rend `None`, jamais une liste partielle : le nom lu sert à
BASCULER l'écosystème actif, et un nom mal découpé bascule vers autre chose.

`()` et `None` sont deux nouvelles différentes — « rien à monter, en créer
un » et « le moteur a répondu autre chose que ce que cette version sait
lire ». Un appelant qui reçoit `None` le dit et nomme la ligne à rejouer à la
main.

- `lit_instances(sortie)` : les écosystèmes découverts. La première colonne
  porte le marqueur du monté et se lit par sa POSITION ; le reste par ses
  blancs, cinq champs exactement ;
- `lit_courante(sortie)` : le nom de l'écosystème monté, réduit à son dernier
  segment — ce que `instance-utiliser` attend en retour ;
- `lit_modeles(sortie)` : les modèles et les index fédérés déjà pris ; la
  phrase qui les porte est ce qui dit que la sortie est bien celle-là ;
- `index_libre(pris, mini, maxi)` : le plus petit index libre. Une PROPOSITION
  seulement : le moteur valide ce qu'il reçoit et refuse une collision
  fédérée ;
- `monte(moteur)` : le nom monté, lu sur le lien, sans rien lancer — il ouvre
  chaque écran qui agit. Un lien BRISÉ garde son nom, pour qu'un écran puisse
  dire « monté sur X, qui n'existe plus » plutôt que « rien ».

