<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Set-OPS — the declared engine and the state of the integration

Two modules, one split: **the survey touches the system, the decision does
not.** Neither imports the engine's code: it is read through files and
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

<!-- [fr] -->
# Set-OPS — le moteur déclaré et l'état de l'intégration

Deux modules, un partage : **le relevé touche le système, la décision ne le
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
