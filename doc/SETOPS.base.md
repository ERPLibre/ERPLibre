<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Set-OPS: driving the engine from TODO

`TODO › Execute › Deploy › Set-OPS` drives Set-OPS, an engine that builds a
sovereign ecosystem from a declarative plan, with Ansible and Proxmox.
**TODO launches the engine; it does not copy it.** The engine stays the only
source of truth for its gestures, and every command TODO names can be
replayed by hand, without TODO.

The menu shows only what exists: today, the state of the integration. The
engine's gestures are added as they are written.

## Getting the engine

The engine is **opt-in**. `manifest/git_manifest_setops.xml` declares it —
its path under `private/repo/` and its revision, a full commit SHA — and no
manifest merged by default names it: an ordinary ERPLibre installation never
contacts the engine's forge. The engine is fetched by:

<!-- [fr] -->
# Set-OPS : piloter le moteur depuis TODO

`TODO › Execute › Deploy › Set-OPS` pilote Set-OPS, un moteur qui construit
un écosystème souverain à partir d'un plan déclaratif, avec Ansible et
Proxmox. **TODO lance le moteur ; il ne le recopie pas.** Le moteur reste la
seule source de vérité de ses gestes, et toute commande que TODO nomme se
rejoue à la main, sans TODO.

Le menu n'affiche que ce qui existe : aujourd'hui, l'état de l'intégration.
Les gestes du moteur s'y ajoutent à mesure qu'ils sont écrits.

## Obtenir le moteur

Le moteur est **sur demande**. `manifest/git_manifest_setops.xml` le déclare
— son chemin sous `private/repo/` et sa révision, un SHA de commit complet —
et aucun manifeste fusionné par défaut ne le nomme : une installation
ERPLibre ordinaire ne contacte jamais la forge du moteur. Le moteur se
rapatrie par :

<!-- [common] -->

```bash
./script/manifest/update_manifest_local_setops.sh
```

<!-- [en] -->
The script fetches the engine alone, at the pinned revision, through Google
Repo. Its three guards run before any side effect — git daemon, manifest
merge, `.repo/` — and only read, so a refusal leaves nothing behind. They
all speak in the same run: one run names every refusal.

- `.venv.erplibre/bin/repo` missing or not executable: it names
  `./script/install/install_git_repo.sh`;
- a folder that Google Repo did not lay out occupies the engine's path: it
  names the command that moves it aside. That folder is a manual clone —
  a real `.git` folder — or a folder without `.git`, even at a path that
  `.repo/project.list` lists: Google Repo writes that list even when the
  fetch fails;
- ERPLibre's HEAD is detached and no local branch contains it: on a fresh
  workspace, `repo init` needs a branch name, never a bare SHA.

The path guard runs in `.venv.erplibre/bin/python`: when it is missing or
not executable, the script refuses (code `1`) saying the engine's location
could not be checked, and only the next run, once ERPLibre is installed,
names what occupies it.

Its exit code is `3` when a folder that Google Repo did not lay out occupies
the engine's path, `2` without a readable declaration of the engine, and
`1` for the other refusals. Past the guards, it is that of the manifest
merge, `repo init` or `repo sync`, whichever fails first.

The guards never delete nor move anything. Google Repo, however, aligns
`.repo/project.list` with the merged manifest on every sync, this one
included: a project that manifest no longer names loses its tree if the
tree is clean — its objects stay under `.repo/projects/` — and makes the
sync fail, naming it, if it carries changes. The script merges the same
manifests as `./script/manifest/update_manifest_local_dev.sh`, plus the
engine.

Moving the pin forward is a deliberate gesture: a new SHA in the manifest,
reviewed and committed.

### When a sync runs without the engine

Once fetched, the engine belongs to the workspace: the following manifest
merges keep it by themselves, since `.repo/project.list` lists its path,
and `repo forall` — hence `make repo_do_stash` — goes through it like any
other project. The only group list the repository gives `repo init`,
`make repo_configure_group_code_generator` (`-g base,code_generator,setops`),
names it.

A sync that runs WITHOUT it deletes its tree: after a `repo init -g` whose
list lacks `setops`, on an ERPLibre branch that has no
`manifest/git_manifest_setops.xml`, or after a merge run with
`--with_new_manifest` and without `--with_setops`. Google Repo deletes
every file of the tree, those the engine's `.gitignore` hides included;
only the targets of the `instance` and `underlay.yml` links survive, since
they live outside it.
The following merges then leave the engine out: the station is no longer
opted in, and `./script/manifest/update_manifest_local_setops.sh` opts it
back in.

A tree with changes, untracked files included, makes that sync fail
instead (`uncommitted changes are present`), and the tree stays. The sync
goes through once the changes are committed, or stashed with
`git stash --include-untracked`, in the engine itself: `make repo_do_stash`
does not reach it then, since `repo forall` only goes through the projects
the manifest and its groups name.

Nothing that cannot be rebuilt therefore belongs in
`private/repo/Set-OPS-Public`: ecosystems and sites live in its sibling
folders, and vault keys under `~/.config`.

### Migrating a manual clone

A clone made by hand is set aside, then the engine is fetched through the
manifest:

<!-- [fr] -->
Le script rapatrie le moteur seul, à la révision épinglée, par Google Repo.
Ses trois gardes passent avant tout effet de bord — démon git, fusion des
manifestes, `.repo/` — et ne font que lire : un refus ne laisse rien
derrière lui. Toutes parlent dans la même exécution : un seul lancement
nomme chaque refus.

- `.venv.erplibre/bin/repo` absent ou non exécutable : il nomme
  `./script/install/install_git_repo.sh` ;
- un dossier que Google Repo n'a pas posé occupe le chemin du moteur : il
  nomme la commande qui le met de côté. Ce dossier est un clone manuel —
  un vrai dossier `.git` — ou un dossier sans `.git`, même à un chemin que
  `.repo/project.list` porte : Google Repo écrit cette liste même quand le
  rapatriement échoue ;
- le HEAD d'ERPLibre est détaché et aucune branche locale ne le contient :
  sur un espace de travail neuf, `repo init` exige un nom de branche,
  jamais un SHA nu.

La garde du chemin tourne dans `.venv.erplibre/bin/python` : absent ou non
exécutable, le script refuse (code `1`) en disant que l'emplacement du
moteur n'a pas pu être vérifié ; c'est le lancement suivant, ERPLibre
installé, qui nomme ce qui l'occupe.

Son code de sortie est `3` quand un dossier que Google Repo n'a pas posé
occupe le chemin du moteur, `2` sans déclaration lisible du moteur, et `1`
pour les autres refus. Les gardes passées, c'est celui de la fusion des
manifestes, de `repo init` ou de `repo sync`, le premier qui échoue.

Les gardes ne suppriment ni ne déplacent jamais rien. Google Repo, lui,
aligne `.repo/project.list` sur le manifeste fusionné à chaque sync, celui-ci
compris : un projet que ce manifeste ne nomme plus perd son arbre si
l'arbre est propre — ses objets restent sous `.repo/projects/` — et fait
échouer le sync, en le nommant, s'il porte des modifications. Le script
fusionne les mêmes manifestes que
`./script/manifest/update_manifest_local_dev.sh`, plus le moteur.

Faire avancer l'épingle est un geste délibéré : un nouveau SHA dans le
manifeste, relu et commité.

### Quand un sync tourne sans le moteur

Une fois rapatrié, le moteur fait partie de l'espace de travail : les
fusions de manifestes suivantes le reprennent d'elles-mêmes, puisque
`.repo/project.list` porte son chemin, et `repo forall` — donc
`make repo_do_stash` — le parcourt comme les autres projets. La seule liste
de groupes que le dépôt passe à `repo init`,
`make repo_configure_group_code_generator` (`-g base,code_generator,setops`),
le nomme.

Un sync qui tourne SANS lui supprime son arbre : après un `repo init -g`
dont la liste n'a pas `setops`, sur une branche d'ERPLibre qui n'a pas
`manifest/git_manifest_setops.xml`, ou après une fusion lancée avec
`--with_new_manifest` et sans `--with_setops`. Google Repo supprime
chaque fichier de l'arbre, ceux que cache le `.gitignore` du moteur
compris ; seules les cibles des liens `instance` et `underlay.yml`
survivent, parce qu'elles vivent hors de lui.
Les fusions suivantes laissent alors le moteur de côté : le poste n'est
plus opté, et `./script/manifest/update_manifest_local_setops.sh` l'opte
de nouveau.

Un arbre qui porte des modifications, fichiers non suivis compris, fait
plutôt échouer ce sync (`uncommitted changes are present`), et l'arbre
reste. Le sync passe une fois les modifications commitées, ou remisées par
`git stash --include-untracked`, dans le moteur lui-même :
`make repo_do_stash` ne l'atteint pas alors, puisque `repo forall` ne
parcourt que les projets que nomment le manifeste et ses groupes.

Rien d'irremplaçable n'a donc sa place dans `private/repo/Set-OPS-Public` :
les écosystèmes et les sites vivent dans ses dossiers frères, et les clés
de voûte sous `~/.config`.

### Migrer un clone manuel

Un clone fait à la main se met de côté, puis le moteur se rapatrie par le
manifeste :

<!-- [common] -->

```bash
mv private/repo/Set-OPS-Public private/repo/Set-OPS-Public.manuel
./script/manifest/update_manifest_local_setops.sh
```

<!-- [en] -->
The set-aside clone keeps what lives INSIDE the engine's folder: the
`instance` link and `underlay.yml`. The state screen then names the gestures
that mount an ecosystem and a site again.

## Where the data lives

The engine finds its ecosystems and its sites among its **sibling**
folders. That is why it sits under `private/repo/`, which ERPLibre's
`.gitignore` ignores: an ecosystem placed next to the engine carries a
customer's data and never enters an ERPLibre commit.

- the **active ecosystem** is the engine's `instance` link, to a sibling
  folder; TODO reads it and keeps no registry of its own;
- the **mounted site** is the engine's `underlay.yml` link, to the
  `underlay.yml` of a sibling folder;
- the **vault keys** stay outside every repository, under the user's
  configuration directory (`~/.config`, or `$XDG_CONFIG_HOME`).

## The state screen

`Set-OPS - State of the integration, line by line` is READ-ONLY: no `make`,
no network, no write. `git` reads without its optional locks, so it does not
rewrite the engine's index. Beyond `git`, the screen runs at most two
bounded subprocesses, in an environment built from scratch:

- the ansible-core version, asked of the dedicated venv's Python, when the
  venv has its `ansible-playbook`;
- `scripts/voutes.py etat`, only with an ecosystem mounted AND its
  `plan/serveurs.yml`, the prerequisite of the vault key line. It runs with
  `-B`: nothing is written in the engine, not even the bytecode of its
  modules. Its return code alone is read — its output names the ecosystem
  and is not even captured.

Ten lines, in the order the station is set up: platform, engine manifest,
private location, Google Repo, engine, Ansible environment, mounted
ecosystem, mounted site, ecosystem vault key, station tools. Each line gives
its state, the gesture that settles it, and the source it reads (`↳`),
its paths relative to ERPLibre's root. When a line finds several things to
settle, it names them all on one line, so settling the first does not
uncover the next on the following run.

Three states, because "the repository knows how" and "this station has set
it up" are two distinct questions:

| mark | in the count | meaning |
|---|---|---|
| ✓ | carried | settled here, as its source shows |
| ◐ | to set up here | the repository knows how; the line names the gesture |
| ○ | not in the repository | what the repository does not carry: for instance no declaration, a revision that is not pinned, a location git does not ignore, or the Ansible venv `.venv.todo.setops` it does not set up yet |

A line whose prerequisite is not held says only `first: <segment>`: the
engine line waits for the manifest line to be carried; Ansible, the
ecosystem and the site wait for the engine's folder to be present; the
vault key waits for the ecosystem line to be carried. An unknown verdict is
never ✓: a probe that fails turns its line to ◐ or ○ with "unreadable
verdict" or "cannot tell", never to a traceback.

Line by line:

- **Platform**: carried on Linux; ○ elsewhere, since the engine assumes
  bash and the GNU tools.
- **Engine manifest**: carried when `manifest/git_manifest_setops.xml`
  declares exactly one project of the `setops` group, at a full commit SHA;
  ○ without a readable declaration, or on a revision that is not pinned.
- **Private location**: carried when git ignores what sits next to the
  engine. Its source is the very question the line asks git, to be
  replayed from ERPLibre's root:
  `git check-ignore -v --no-index -- private/repo/.sonde-setops-ignore`
  — return code `0`, ignored; `1`, not ignored (○); anything else, "cannot
  tell" (○). The question bears on an invented name under `private/repo/`:
  asked about the folder itself, without `--no-index`, git answers "not
  ignored", since the folder holds the tracked `private/repo/.gitkeep`.
- **Google Repo**: carried when `.venv.erplibre/bin/repo` is executable,
  the rule the fetch script applies, and `.repo/manifest.xml` exists —
  `repo init` writes it, whereas the manifest merge alone creates the
  `.repo/` folder. Otherwise ◐: without `repo`, the line names
  `./script/install/install_git_repo.sh`; without `.repo/manifest.xml`, the
  fetch script, which initializes `.repo/` — and first, when something
  Google Repo did not lay out occupies the engine's path, the `mv` that
  sets it aside.
- **Engine**: carried only when Google Repo manages it, at the pin, with a
  clean tree. Managed follows the fetch script's rule: `.repo/project.list`
  lists the path AND Google Repo laid out the tree there, its `.git` leading
  under `.repo/`. ◐ when nothing is at the path, naming the fetch script;
  ◐ for a manual clone — anything else at the path, even a listed one:
  another folder, a file, a broken link — naming its `mv`, or when it
  cannot tell whether Google Repo manages the path; ◐ ahead
  of or behind the pin, on a HEAD that does not descend from the pin, on a
  pin the clone does not hold ("resynchronize"), when it
  "cannot tell where HEAD stands against the pin", and on modified files.
  A pin the clone does not hold is a finding: git reads the clone and the
  pinned object is not in it, which resynchronizing settles. "Cannot tell"
  is the lack of a finding — git stops answering, or the pin names an
  object that is not a commit — so the line names no gesture: nothing
  shows that anything is missing. When git cannot read the clone, the line
  says so, and says nothing about the pin or modified files.
- **Ansible environment**: ○ while `.venv.todo.setops` has no
  `ansible-playbook` — the repository does not set it up yet — and when
  the engine's range (`serveur_ops_ansible`) is not a bounded ansible-core
  requirement: another package, a URL, extras, a marker, or no bound.
  Carried when the version the venv imports is within the range; ◐ outside
  it or unreadable. A pre-release is within the range only if the range
  itself names a pre-release, whatever version of `packaging` is
  installed.
- **Mounted ecosystem**: carried when `instance` is a link to a folder that
  holds its `plan/serveurs.yml`. ◐ otherwise: without a link, the line
  names `make -C private/repo/Set-OPS-Public instance-utiliser NOM=…`; a
  real `instance` folder is one the engine refuses to switch.
- **Mounted site**: carried when `underlay.yml` leads to a file, and the
  line names the folder that holds it. Otherwise ◐, a link that leads to
  no file — broken, or to a folder — being named as such, with the same
  gesture, typed from ERPLibre's root:
  `ln -sfn ../<site>/underlay.yml private/repo/Set-OPS-Public/underlay.yml`
  — `<site>` is the sibling folder, under `private/repo/`, that holds the
  site's `underlay.yml`, and the target is relative to the link's folder.
  The source points to the engine's
  `docs/implanter-un-tenant-sur-un-site.md`.
- **Ecosystem vault key**: return code `0` of `scripts/voutes.py etat`,
  carried. ◐ on `1`, the key is missing: the line names the command that
  shows why, since a script that raises exits with `1` too. ◐ "unreadable
  verdict" on any other code, or none.
- **Station tools**: carried as soon as `make`, `git` and `ssh` are found,
  ◐ without one of them. A missing optional tool is listed as a note, with
  the engine targets it blocks.

<!-- [fr] -->
Le clone mis de côté garde ce qui vit DANS le dossier du moteur : le lien
`instance` et `underlay.yml`. L'écran d'état nomme alors les gestes qui
montent de nouveau un écosystème et un site.

## Où vivent les données

Le moteur trouve ses écosystèmes et ses sites parmi ses dossiers **frères**.
C'est pourquoi il se pose sous `private/repo/`, que le `.gitignore`
d'ERPLibre ignore : un écosystème posé à côté du moteur porte les données
d'un client et n'entre jamais dans un commit d'ERPLibre.

- l'**écosystème actif** est le lien `instance` du moteur, vers un dossier
  frère ; TODO le lit et ne tient aucun registre à lui ;
- le **site monté** est le lien `underlay.yml` du moteur, vers le
  `underlay.yml` d'un dossier frère ;
- les **clés de voûte** restent hors de tout dépôt, sous le dossier de
  configuration de l'utilisateur (`~/.config`, ou `$XDG_CONFIG_HOME`).

## L'écran d'état

`Set-OPS - État de l'intégration, ligne par ligne` est en LECTURE SEULE : ni
`make`, ni réseau, ni écriture. `git` lit sans ses verrous facultatifs, si
bien qu'il ne réécrit pas l'index du moteur. Au-delà de `git`, l'écran lance
au plus deux sous-processus bornés, dans un environnement construit à neuf :

- la version d'ansible-core, demandée au Python du venv dédié, quand le
  venv a son `ansible-playbook` ;
- `scripts/voutes.py etat`, seulement avec un écosystème monté ET son
  `plan/serveurs.yml`, le préalable de la ligne de la clé de voûte. Il est
  lancé avec `-B` : rien ne s'écrit dans le moteur, pas même le bytecode de
  ses modules. Seul son code de retour est lu — sa sortie nomme
  l'écosystème et n'est pas même capturée.

Dix lignes, dans l'ordre où l'on règle le poste : plateforme, manifeste du
moteur, emplacement privé, Google Repo, moteur, environnement Ansible,
écosystème monté, site monté, clé de voûte de l'écosystème, outils du poste.
Chaque ligne dit son état, le geste qui la règle, et la source qu'elle lit
(`↳`), ses chemins relatifs à la racine d'ERPLibre. Quand une ligne trouve
plusieurs choses à régler, elle les nomme toutes sur une ligne, pour que
régler la première ne fasse pas découvrir la suivante au lancement d'après.

Trois états, parce que « le dépôt sait le faire » et « ce poste l'a réglé »
sont deux questions distinctes :

| marque | au compte | sens |
|---|---|---|
| ✓ | portés | réglé ici, comme sa source le montre |
| ◐ | à régler ici | le dépôt sait le faire ; la ligne nomme le geste |
| ○ | absent du dépôt | ce que le dépôt ne porte pas : par exemple aucune déclaration, une révision non épinglée, un emplacement que git n'ignore pas, ou le venv Ansible `.venv.todo.setops` qu'il ne sait pas encore poser |

Une ligne dont le préalable n'est pas tenu dit seulement
`d'abord : <segment>` : la ligne du moteur attend la ligne du manifeste
portée ; Ansible, l'écosystème et le site attendent le dossier du moteur
présent ; la clé de voûte attend la ligne de l'écosystème portée. Un
verdict inconnu n'est jamais ✓ : une sonde qui échoue fait passer sa ligne
à ◐ ou ○ avec « verdict illisible » ou « impossible de savoir », jamais à
une trace Python.

Ligne par ligne :

- **Plateforme** : portée sous Linux ; ○ ailleurs, le moteur supposant bash
  et l'outillage GNU.
- **Manifeste du moteur** : porté quand
  `manifest/git_manifest_setops.xml` déclare exactement un projet du groupe
  `setops`, à un SHA de commit complet ; ○ sans déclaration lisible, ou sur
  une révision non épinglée.
- **Emplacement privé** : porté quand git ignore ce qui se pose à côté du
  moteur. Sa source est la question même que la ligne pose à git, à
  rejouer depuis la racine d'ERPLibre :
  `git check-ignore -v --no-index -- private/repo/.sonde-setops-ignore`
  — code de retour `0`, ignoré ; `1`, non ignoré (○) ; tout autre,
  « impossible de savoir » (○). La question porte sur un nom inventé sous
  `private/repo/` : posée sur le dossier lui-même, sans `--no-index`, git
  répond « non ignoré », puisque le dossier porte le fichier suivi
  `private/repo/.gitkeep`.
- **Google Repo** : porté quand `.venv.erplibre/bin/repo` est exécutable,
  la règle qu'applique le script de rapatriement, et que
  `.repo/manifest.xml` existe — `repo init` l'écrit, alors que la seule
  fusion des manifestes crée le dossier `.repo/`. Sinon ◐ : sans `repo`, la
  ligne nomme `./script/install/install_git_repo.sh` ; sans
  `.repo/manifest.xml`, le script de rapatriement, qui initialise `.repo/`
  — et d'abord, quand ce que Google Repo n'a pas posé occupe le chemin du
  moteur, le `mv` qui le met de côté.
- **Moteur** : porté seulement quand Google Repo le gère, à l'épingle,
  arbre propre. Géré suit la règle du script de rapatriement :
  `.repo/project.list` porte le chemin ET Google Repo y a posé l'arbre, son
  `.git` menant sous `.repo/`. ◐ quand rien n'occupe le chemin, en nommant
  le script de rapatriement ; ◐ pour un clone manuel — tout autre occupant
  du chemin, même listé : un autre dossier, un fichier, un lien brisé — en
  nommant son `mv`, ou quand il est impossible de savoir si
  Google Repo gère le chemin ; ◐ en avance ou en retard sur l'épingle,
  sur un HEAD qui ne descend pas de l'épingle, sur une épingle que le clone
  ne porte pas (« resynchroniser »), quand il est « impossible de savoir
  où HEAD se tient face à l'épingle », et sur des fichiers modifiés. Une
  épingle que le clone ne porte pas est un constat : git lit le clone et
  l'objet épinglé n'y est pas, ce que la resynchronisation règle.
  « Impossible de savoir » est l'absence de constat — git cesse de
  répondre, ou l'épingle désigne un objet qui n'est pas un commit — et la
  ligne ne nomme donc aucun geste : rien n'établit qu'il manque quelque
  chose. Quand git ne sait pas lire le clone, la ligne le dit, et ne dit
  rien ni de l'épingle ni des fichiers modifiés.
- **Environnement Ansible** : ○ tant que `.venv.todo.setops` n'a pas
  d'`ansible-playbook` — le dépôt ne sait pas encore le poser — et quand la
  plage du moteur (`serveur_ops_ansible`) n'est pas une exigence
  d'ansible-core bornée : un autre paquet, une URL, des extras, un
  marqueur, ou aucune borne. Porté quand la version que le venv importe est
  dans la plage ; ◐ hors de la plage ou illisible. Une pré-version n'est
  dans la plage que si la plage en nomme elle-même une, quelle que soit la
  version de `packaging` installée.
- **Écosystème monté** : porté quand `instance` est un lien vers un dossier
  qui porte son `plan/serveurs.yml`. ◐ sinon : sans lien, la ligne nomme
  `make -C private/repo/Set-OPS-Public instance-utiliser NOM=…` ; un vrai
  dossier `instance` est un dossier que le moteur refuse de basculer.
- **Site monté** : porté quand `underlay.yml` mène à un fichier, et la
  ligne nomme le dossier qui le porte. Sinon ◐, un lien qui ne mène à
  aucun fichier — brisé, ou vers un dossier — étant nommé comme tel, avec
  le même geste, tapé depuis la racine d'ERPLibre :
  `ln -sfn ../<site>/underlay.yml private/repo/Set-OPS-Public/underlay.yml`
  — `<site>` est le dossier frère, sous `private/repo/`, qui porte le
  `underlay.yml` du site, et la cible est relative au dossier du lien. La
  source renvoie au `docs/implanter-un-tenant-sur-un-site.md` du moteur.
- **Clé de voûte de l'écosystème** : code de retour `0` de
  `scripts/voutes.py etat`, portée. ◐ sur `1`, la clé manque : la ligne
  nomme la commande qui montre pourquoi, puisqu'un script qui lève sort
  aussi en `1`. ◐ « verdict illisible » sur tout autre code, ou aucun.
- **Outils du poste** : portés dès que `make`, `git` et `ssh` se trouvent,
  ◐ sans l'un d'eux. Un outil facultatif absent est listé en note, avec les
  cibles du moteur qu'il bloque.
