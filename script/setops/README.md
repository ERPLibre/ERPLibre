
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
