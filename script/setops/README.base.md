<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Set-OPS — the declared engine and the state of the integration

Nine modules, one split: **the survey touches the system, the decision
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
  verdict, not the absence of one;
- `detacher(argv, env, cwd, journal)`: launches and hands back the PID of the
  group leader, or `None`. A NEW SESSION, and that is what makes it stoppable:
  one signal reaches both the `make` recipe and the server it starts. The
  terminal is not given to it — its input is closed, its output goes to the
  log. The PID does not prove the service came up; a detached launch fails in
  silence.

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
- `site_monte(moteur)`: the folder that carries the engine's
  `underlay.yml`. No FILE at the end of the link means nothing mounted:
  the engine reads that file, and a folder does not read;
- `monte(moteur)`: the mounted name, read on the link, launching nothing —
  it heads every screen that acts. A BROKEN link keeps its name, so a screen
  can say "mounted on X, which is gone" rather than "nothing".

## `coexistence` — one object, one master

Both tools work on the same Proxmox cluster and each keeps only ITS objects.
Without a guard, TODO's Proxmox menu offers a Set-OPS plan's VMs for
deletion, frees the disks of a VMID the plan claims, and picks a VMID the
fleet is about to materialise.

**Two markers, read on the cluster and in the plan.** The engine pours each
VM into a POOL named after its ecosystem repository, and DERIVES a
nine-digit VMID — VLAN on four, host on three, rank on two. The pool states
declared ownership; the VMID shape catches a VM taken out of its pool by
hand. The pool literally named `Set-OPS` on a reference cluster is NOT a
marker: it groups VMs from before the engine, which the engine never
touches.

**Closed by default.** When the cluster or the plan cannot be read, the state
is `INCONNU` and the caller refuses — the same stance as "only free what is
proven orphaned".

**The collision is the costly finding.** A fleet does not rename around a
taken VMID: the index changes and everything is regenerated — back up, raze,
change the index, deploy, restore. Hours. So the finding must land BEFORE a
deployment, not during one.

- `vmid_derive(vmid)`: does the VMID have the shape the engine derives?
- `lit_devis(sortie)`: the `Declaration` the pools plan carries, or `None`;
  the `make` recipe echoes its command, so reading starts at the first brace;
- `etat(invite, devis)`: (state, master) — may this guest be touched?
- `vmid_revendique(vmid, devis)`: the pool that DECLARES this VMID, `""` if
  none, `None` if the plan is unreadable — three answers, not two;
- `collisions(invites, devis)`: the declared VMIDs a foreign VM already
  holds. A VM does not collide with itself: the fleet's own carries either
  its pool or the name the plan gives it.

## `runbooks` — the engine's sequences, and nothing masked

The engine's Makefile carries more than a hundred and thirty documented
targets and says NOWHERE in which order to play them. The registry does: it
arranges them into seventeen sequences, each with its purpose, and gives every
step a "why" that only means something at its place in the suite.

**Nothing is masked.** A sequence stripped of the steps TODO will not launch
would lie by omission — eight of the seventeen have such steps, and one would
begin at its step 2. Every step is shown, and what will not run from here
carries the REASON why. That is the same stance as the state screen, which
shows its ten lines with three marks rather than the bare list of what is
ready.

**The scope rule is written once**, in `barriere(etape, ecosysteme, site)`. Two copies would sooner or
later say two different things about the same gesture.

- `lit_registre(sortie)`: the sequences, in order, or `None`. A step whose
  nature or target cannot be read refuses the WHOLE registry: a partial
  sequence is worse than none, since its order is what one came for;
- `barriere(etape, ecosysteme, site)`: what stops TODO from driving this step
  from here, or `""`. The refusals run from the general to the circumstantial:
  what destroys never runs from here, whereas a missing scope is settled by
  mounting an ecosystem;
- `conduisible(etape, ecosysteme, site)`: the same answer as a yes or no;
- `ecrit(etape)`: does it touch the system? A write the engine does not gate
  is where TODO asks its OWN confirmation — the line shown carries
  `CONFIRMER=false`, and for those targets the flag means nothing;
- `compte(runbook, ecosysteme, site)`: (drivable, total), shown at the head of
  a sequence. A list whose offer is unknown is walked in full to find out.

Eleven of those gestures also have a dedicated door in the menu, and all eleven
lead to ONE screen: the door names its target, and everything describing the
gesture is read back from the registry at each visit. Two places describing the
same gesture would sooner or later say two different things.

- `methode(cible)`: the name of the method that opens a target's door, DERIVED
  from the target so no table has to be kept in step;
- `trouve(runbooks, cible)`: the step the registry declares for that target, or
  `None`. A target may appear in several sequences; while those declarations are
  identical the door opens one without ambiguity, and if they disagree it opens
  none — a door choosing at random would sometimes launch the other gesture.

`ECARTS` names what TODO knows and the registry does NOT say yet. A test reddens
the day the registry says it itself, so the entry must then go: a table of
exemptions that nobody retires ends up hiding the fix upstream.

- `ecart(cible)`: that divergence, or an empty one — never `None`, since the
  caller always reads fields;
- `interactif(etape)`: does it need the operator's terminal? Captured, a target
  that asks questions reads a closed input, answers "EOF" and has done nothing;
- `drapeau(etape)`: the name of a flag that is a SWITCH, not a value. The recipe
  reads it through `$(if $(NOM),…)` and GNU make holds any non-empty string
  true, so "0" turns it on as surely as "1". Its value is never asked for: the
  question is closed, and no is nothing at all.

## `vaults` — a missing key is not a fault

The engine writes it in capitals: on a tenant runner the SITE key must be
absent. That runner carries the fabric map and must never open it, so an
absence there is a separation that HOLDS. Only the mounted instance's key
stops the machine from working, and it alone decides the engine's exit code.
Presenting the others as defects would send someone to repair what works — by
handing that station keys it must not hold.

**The key is never displayed and never logged.** `poser_cle` writes the bytes
and returns a verdict that does not carry them.

- `lit_etat(sortie)`: the vaults the report names, `()` when it names none,
  `None` when the report is not the expected shape. Those are two different
  pieces of news: the first says "no instance mounted and no underlay". A role
  outside the three known ones refuses the WHOLE report, because `bloquante`
  decides on the word "instance": a rename upstream must not report calm on a
  machine that can configure nothing;
- `bloquante(voutes)`: the vault whose absence stops the machine, or `None` —
  the mounted instance's, and it alone;
- `separation(voutes)`: the vaults this machine does not open and must not.
  Posing a new key for one of them would open nothing: that vault's secret
  already exists elsewhere;
- `poser_cle(chemin)`: poses a new key file and returns a `Pose`. It NEVER
  overwrites an existing file — a replaced key makes its vault unreadable for
  good, where the shell redirection the engine documents truncates. The mode is
  set at creation, not after: in between, the key would be world readable. A
  new key only opens a vault that holds nothing yet; on one already encrypted
  it recovers nothing, and the caller settles that before calling.

## `console` — a door without a lock, so a door on the loopback

`inventaire-ui` serves an interface that reads the whole inventory — addresses,
VLANs, host names — and triggers its gestures: verify, deploy, push a flow. It
has **no authentication**; the token it carries guards its executions from one
another, not its door.

Hence the loopback and nothing else. The script accepts `--hote` and TODO never
passes it: binding to `0.0.0.0` would publish a lockless console that can
deploy to the fleet. To reach it from elsewhere a port is forwarded over SSH,
which hands authentication back to SSH instead of removing it.

A detached launch fails in silence, so the port is probed afterwards. And a PID
is reassigned: nothing is signalled without rereading that PID's command line.

- `dossier(env)`, `chemin_suivi(env)`, `chemin_journal(env)`: where the record
  and the log live — the user's runtime directory first, which belongs to them
  alone, the temporary directory otherwise;
- `lit_suivi(texte)`: the `Suivi` a record carries, or `None`. A PID below 1 is
  refused, because a signal sent to 0 hits the caller's WHOLE process group —
  TODO would kill itself — and one sent to -1 everything the user owns;
- `ecrit_suivi(chemin, pid, port)`, `oublie(chemin)`: note and forget it,
  without raising. A lost record does not break anything grave;
- `ligne_de_commande(pid, procfs)`: the command line, `ABSENT`, or `None` —
  three answers because there are three cases. `ABSENT` is what the system
  AFFIRMS when the PID's folder is gone from a mounted procfs; `None` says it
  is not known, and on a doubt nothing is killed nor declared stopped;
- `tenue(ligne, marque)`: is that our console? `None` passes the doubt on;
- `port_occupe(adresse, port, delai)`: is something listening? Probed by
  connecting and not by a trial bind, which would take the port and give it
  back exactly when the console tries to take it;
- `situation(suivi, portee, occupe)`: (state, pid) from those three measured
  facts. A missing fact gives `INCONNU` rather than a guess: on a doubt the
  screen offers neither to start — two consoles would fight over the port — nor
  to stop. Our own process alive while nothing answers is `MUETTE`, not
  running: a detached launch fails in silence, and the recipe can outlive the
  server it started;
- `url(adresse, port)`, `redirection(hote, utilisateur, port)`: the address to
  show, and the forward that keeps both ends on the loopback;
- `arreter(suivi, portee, signal_au_groupe)`: stops it, and NOTHING is killed
  without proof. The signal goes to the GROUP: the `make` recipe and the server
  it started are both there, and signalling `make` alone would leave the server
  holding the port;
- `attendre(sonde, attendu, essais, pause)`: probes until the answer comes. The
  port neither opens nor frees at the instant of the gesture; without this wait
  the screen would conclude on the state from before.

<!-- [fr] -->
# Set-OPS — le moteur déclaré et l'état de l'intégration

Neuf modules, un partage : **le relevé touche le système, la décision ne le
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
  verdict, pas l'absence de verdict ;
- `detacher(argv, env, cwd, journal)` : lance et rend le PID du chef de
  groupe, ou `None`. NOUVELLE SESSION, et c'est ce qui permet de l'arrêter :
  un seul signal atteint la recette `make` ET le serveur qu'elle lance. Le
  terminal ne lui est pas rendu — son entrée est fermée, sa sortie va au
  journal. Le PID ne prouve pas que le service a démarré ; un détaché échoue
  en silence.

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
- `site_monte(moteur)` : le dossier qui porte l'`underlay.yml` du moteur.
  Aucun FICHIER au bout du lien vaut « rien de monté » : le moteur lit ce
  fichier, et un dossier ne se lit pas ;
- `monte(moteur)` : le nom monté, lu sur le lien, sans rien lancer — il ouvre
  chaque écran qui agit. Un lien BRISÉ garde son nom, pour qu'un écran puisse
  dire « monté sur X, qui n'existe plus » plutôt que « rien ».

## `coexistence` — un objet, un maître

Les deux outils travaillent sur la même grappe Proxmox et chacun ne garde que
SES objets. Sans garde, le menu Proxmox de todo propose à l'effacement les VM
d'un plan Set-OPS, libère les disques d'un VMID que le plan réclame, et
choisit un VMID que la flotte s'apprête à matérialiser.

**Deux marqueurs, lus sur la grappe et dans le plan.** Le moteur verse chaque
VM dans un POOL qui porte le nom de son dépôt d'écosystème, et DÉRIVE un VMID
de neuf chiffres — VLAN sur quatre, hôte sur trois, rang sur deux. Le pool dit
l'appartenance déclarée ; la forme du VMID rattrape une VM sortie de son pool
à la main. Le pool littéralement nommé `Set-OPS` d'une grappe de référence
n'est PAS un marqueur : il regroupe des VM antérieures au moteur, auxquelles
le moteur ne touche pas.

**Fermé par défaut.** Quand la grappe ou le plan ne se lisent pas, l'état est
`INCONNU` et l'appelant refuse — le même parti que « ne libérer que ce qui se
prouve orphelin ».

**La collision est le constat qui coûte.** Une flotte ne se renomme pas pour
contourner un VMID pris : on change l'index et on régénère — sauvegarder,
raser, changer l'index, déployer, restaurer. Des heures. Le constat doit donc
tomber AVANT un déploiement, pas pendant.

- `vmid_derive(vmid)` : le VMID a-t-il la forme que le moteur dérive ?
- `lit_devis(sortie)` : la `Declaration` que porte le devis des pools, ou
  `None` ; la recette `make` écho sa commande, donc la lecture commence à la
  première accolade ;
- `etat(invite, devis)` : (état, maître) — todo peut-il toucher cet invité ?
- `vmid_revendique(vmid, devis)` : le pool qui DÉCLARE ce VMID, `""` si
  aucun, `None` si le plan est illisible — trois réponses, pas deux ;
- `collisions(invites, devis)` : les VMID déclarés qu'une VM étrangère occupe
  déjà. Une VM n'entre pas en collision avec elle-même : celle de la flotte
  porte soit son pool, soit le nom que le plan lui donne.

## `runbooks` — les séquences du moteur, et rien de masqué

Le Makefile du moteur porte plus de cent trente cibles documentées et ne dit
NULLE PART dans quel ordre les jouer. Le registre le dit : il les range en
dix-sept séquences, chacune avec son but, et donne à chaque étape un
« pourquoi » qui n'a de sens qu'à sa place dans la suite.

**Rien n'est masqué.** Une séquence dont on retirerait les étapes que todo ne
lance pas mentirait par omission — huit des dix-sept en ont, et l'une
commencerait à son étape 2. Chaque étape est affichée, et ce qui ne part pas
d'ici porte la RAISON pour laquelle il ne part pas. C'est le parti de l'écran
d'état, qui montre ses dix lignes avec trois marques plutôt que la seule liste
de ce qui est prêt.

**La règle de périmètre est écrite une fois**, dans `barriere(etape, ecosysteme, site)`. Deux copies
diraient tôt ou tard deux choses différentes du même geste.

- `lit_registre(sortie)` : les séquences, dans l'ordre, ou `None`. Une étape
  dont la nature ou la cible ne se lisent pas fait refuser TOUT le registre :
  une séquence partielle est pire qu'une absence, puisque son ordre est ce
  qu'on vient y chercher ;
- `barriere(etape, ecosysteme, site)` : ce qui empêche todo de conduire cette
  étape d'ici, ou `""`. Les refus vont du général au circonstanciel : ce qui
  détruit ne part jamais d'ici, alors qu'une portée manquante se règle en
  montant un écosystème ;
- `conduisible(etape, ecosysteme, site)` : la même réponse, en oui ou non ;
- `ecrit(etape)` : touche-t-elle au système ? Une écriture que le moteur ne
  garde pas est celle où todo pose sa PROPRE confirmation — la ligne affichée
  porte `CONFIRMER=false`, et pour ces cibles-là le drapeau ne veut rien dire ;
- `compte(runbook, ecosysteme, site)` : (conduisibles, total), affiché en tête
  d'une séquence. Une liste dont on ignore ce qu'elle offre se parcourt en
  entier pour le découvrir.

Onze de ces gestes ont aussi une porte dédiée au menu, et les onze mènent à UN
seul écran : la porte nomme sa cible, et tout ce qui décrit le geste est relu au
registre à chaque visite. Deux endroits qui décriraient le même geste diraient
tôt ou tard deux choses différentes.

- `methode(cible)` : le nom de la méthode qui ouvre la porte d'une cible,
  DÉRIVÉ de la cible pour qu'aucune table n'ait à suivre ;
- `trouve(runbooks, cible)` : l'étape que le registre déclare pour cette cible,
  ou `None`. Une cible peut figurer dans plusieurs séquences ; tant que ces
  déclarations sont identiques la porte en ouvre une sans ambiguïté, et si elles
  divergent elle n'en ouvre aucune — une porte qui trancherait au hasard
  lancerait parfois l'autre geste.

`ECARTS` nomme ce que todo sait et que le registre ne dit PAS encore. Une
épreuve rougit le jour où le registre le dit lui-même, et l'entrée doit alors
partir : une table de dérogations que personne ne retire finit par masquer la
correction en amont.

- `ecart(cible)` : cet écart, ou un écart vide — jamais `None`, puisque
  l'appelant lit toujours des champs ;
- `interactif(etape)` : a-t-elle besoin du terminal de l'opérateur ? Capturée,
  une cible qui pose des questions lit une entrée fermée, rend « EOF » et n'a
  rien fait ;
- `drapeau(etape)` : le nom d'un drapeau qui est un INTERRUPTEUR et non une
  valeur. La recette le lit par `$(if $(NOM),…)` et GNU make tient toute chaîne
  non vide pour vraie : « 0 » l'active aussi sûrement que « 1 ». Sa valeur ne se
  demande jamais : la question est fermée, et « non » ne passe rien du tout.

## `vaults` — une clé absente n'est pas une faute

Le moteur l'écrit en capitales : sur le runner d'un locataire, la clé du SITE
doit manquer. Ce runner porte la carte de la fabric et ne doit jamais
l'ouvrir ; une absence y est donc une séparation qui TIENT. Seule celle de
l'instance montée empêche la machine de travailler, et elle seule décide du
code de sortie du moteur. Présenter les autres comme des défauts enverrait
réparer ce qui fonctionne — en donnant à ce poste des clés qu'il ne doit pas
détenir.

**La clé ne s'affiche jamais et ne se journalise jamais.** `poser_cle` écrit
les octets et rend un verdict qui ne les porte pas.

- `lit_etat(sortie)` : les voûtes que le rapport nomme, `()` s'il n'en nomme
  aucune, `None` si le rapport n'a pas la forme attendue. Ce sont deux
  nouvelles différentes : la première dit « ni instance montée ni underlay ».
  Un rôle hors des trois connus fait refuser TOUT le rapport, parce que
  `bloquante` se décide sur le mot « instance » : un renommage en amont ne doit
  pas rendre un calme trompeur sur une machine qui ne peut rien configurer ;
- `bloquante(voutes)` : la voûte dont l'absence empêche la machine de
  travailler, ou `None` — celle de l'instance montée, et elle seule ;
- `separation(voutes)` : les voûtes que cette machine n'ouvre pas et ne doit
  pas ouvrir. Y poser une clé neuve n'en ouvrirait aucune : le secret de cette
  voûte existe déjà ailleurs ;
- `poser_cle(chemin)` : pose un fichier-clé neuf et rend une `Pose`. Il
  n'écrase JAMAIS un fichier existant — une clé remplacée rend sa voûte
  définitivement illisible, là où la redirection que documente le moteur
  tronque. Le mode est posé à la création, pas après : entre les deux, la clé
  est lisible par tout le monde. Une clé neuve n'ouvre qu'une voûte qui ne
  porte encore rien ; sur une voûte déjà chiffrée elle ne récupère rien, et
  l'appelant tranche avant d'appeler.

## `console` — une porte sans serrure, donc une porte sur la boucle

`inventaire-ui` sert une interface qui lit tout l'inventaire — adresses, VLAN,
noms d'hôtes — et déclenche ses gestes : vérifier, déployer, pousser un flux.
Elle n'a **aucune authentification** ; le jeton qu'elle porte garde ses
exécutions les unes des autres, pas sa porte.

D'où la boucle locale, et rien d'autre. Le script accepte `--hote` et todo ne
le passe jamais : le lier à `0.0.0.0` publierait une console sans serrure qui
peut déployer sur la flotte. Pour l'atteindre d'ailleurs, on redirige un port
par SSH, ce qui remet l'authentification à SSH au lieu de la supprimer.

Un détaché échoue en silence, donc le port se sonde après coup. Et un PID se
réattribue : rien n'est signalé sans avoir relu la ligne de commande de ce PID.

- `dossier(env)`, `chemin_suivi(env)`, `chemin_journal(env)` : où vivent le
  suivi et le journal — le dossier d'exécution de l'utilisateur d'abord, qui
  n'appartient qu'à lui, le dossier temporaire sinon ;
- `lit_suivi(texte)` : le `Suivi` que porte un enregistrement, ou `None`. Un
  PID sous 1 est refusé, parce qu'un signal envoyé à 0 porte sur TOUT le groupe
  de processus de l'appelant — todo se tuerait lui-même — et un signal envoyé à
  -1 sur tout ce que l'utilisateur possède ;
- `ecrit_suivi(chemin, pid, port)`, `oublie(chemin)` : le noter et l'oublier,
  sans lever. Un suivi perdu ne casse rien de grave ;
- `ligne_de_commande(pid, procfs)` : la ligne de commande, `ABSENT`, ou
  `None` — trois réponses parce qu'il y a trois cas. `ABSENT` est ce que le
  système AFFIRME quand le dossier du PID a disparu d'un procfs monté ; `None`
  dit qu'on ne sait pas, et sur un doute rien n'est tué ni déclaré arrêté ;
- `tenue(ligne, marque)` : est-ce notre console ? `None` transmet le doute ;
- `port_occupe(adresse, port, delai)` : quelque chose écoute-t-il ? Sondé par
  une connexion et non par une liaison d'essai, qui prendrait le port et le
  rendrait au moment précis où la console cherche à le prendre ;
- `situation(suivi, portee, occupe)` : (état, pid) depuis ces trois faits
  mesurés. Un fait manquant rend `INCONNU` plutôt qu'une supposition : sur un
  doute, l'écran n'offre ni de lancer — deux consoles se disputeraient le
  port — ni d'arrêter. Notre propre processus vivant sans que rien ne réponde
  est `MUETTE`, et non debout : un détaché échoue en silence, et la recette
  peut survivre au serveur qu'elle a lancé ;
- `url(adresse, port)`, `redirection(hote, utilisateur, port)` : l'adresse à
  montrer, et la redirection qui garde les deux bouts sur la boucle locale ;
- `arreter(suivi, portee, signal_au_groupe)` : l'arrête, et RIEN n'est tué sans
  preuve. Le signal va au GROUPE : la recette `make` et le serveur qu'elle a
  lancé y sont tous les deux, et signaler le seul `make` laisserait le serveur
  tenir le port ;
- `attendre(sonde, attendu, essais, pause)` : sonde jusqu'à ce que la réponse
  vienne. Le port ne s'ouvre ni ne se libère à l'instant du geste ; sans cette
  attente, l'écran conclurait sur l'état d'avant.
