
# long_test — tests that create real machines

These are not unit tests. They create virtual machines, install systems on
them, and take hours. They live here and **not** in `test/`, which the unit
runner sweeps: `./script/test/run_unit_test.sh` must stay runnable in seconds
on any machine, including one without virtualisation.

Run them from the menu — `TODO › Execute › Test › Long tests` — or directly.

## deep_proxmox.py — how deep does Proxmox-in-Proxmox go?

The practicable nesting depth cannot be deduced, only measured — and one
measurement is not a measurement.

A manual look at one fourth-level VM found a guest **36 times slower than real
time** (583 seconds of wall clock for 16 seconds of guest time, each ACPI line
taking a second) and then a frozen kernel: identical RIP across three samples
two minutes apart, and **not one byte written** to disk.

Running this script **refuted the conclusion drawn from it**. Its own
fourth-level VM — 2 vCPU where the manual one had 12 — booted, installed, and
wrote gigabytes. What looked like a nesting ceiling was a *parallelism*
ceiling under nesting. That is exactly what the algorithm caps, and this is
how it stopped being a guess.

Which is the point of the script: a number obtained once, on one machine, in
one chain, is an anecdote.

```
./long_test/deep_proxmox.py                        # three levels, ~30 minutes
./long_test/deep_proxmox.py --dry-run              # the plan, nothing created
./long_test/deep_proxmox.py --depth 5              # ask for more, knowingly
./long_test/deep_proxmox.py --detruire             # undo it
```

### How deep is worth asking for

The depth is the only setting, and **three** is the default because three
works. Measured on a 28-core machine, one full descent per row:

| level | boot (ssh) | install | total |
|------:|-----------:|--------:|------:|
| 1 | 0 s | 200 s | 280 s |
| 2 | 37 s | 344 s | 495 s |
| 3 | 93 s | 777 s | 1 064 s |
| 4 | **15 608 s** | **26 306 s** | did not finish |

Three levels cost half an hour. The **fourth** cost 4 h 20 of boot and 7 h 18
of install on the same machine — everything there is 15 to 30 times slower, not
just one step. And it lands exactly where the hardware vendors stop: level 4 is
the *third* nested hypervisor, and AMD documents two.

A wider guest makes it worse, sharply: at level 4, one extra vCPU multiplied
the boot by 9.4 (1 664 s at two vCPU, 15 608 s at three), and at eight vCPU the
guest read 32 MiB in 106 minutes with a static instruction pointer. At levels 2
and 3 that same vCPU costs nothing.

So: three by default, five if you want to know, ten only to watch the wall.

The descent is **uniform**. Every level, the first included, goes through the
same six steps: create, wait for ssh, install Proxmox, reboot and check the
kernel, bring pmxcfs back up, check the storage. Only creation differs —
libvirt locally, `qm` afterwards.

It sends **our** `install_proxmox.sh` over scp instead of letting the VM clone
the repository: it is our code we want to exercise, and the remote is often
behind the checkout — a fix absent from the remote made the same defect "come
back" on three VMs in a row.

### The resource algorithm — sized from the bottom up

The first version handed down whatever the parent could spare, and a real
descent showed what that costs. Level 4 ended up with 44 GB of memory and
2 vCPU **on a host that had 2** — a hundred percent overcommit, at every
level, with the hypervisor itself to serve on top. Its install ran past two
and a half hours against thirteen minutes for level 3, and extrapolating that
ratio gave five years for the tenth.

So the direction is reversed for **memory and disk**. The deepest level gets
what a test Proxmox actually asks for — 4 GB of memory, 25 GB of disk — and
every parent above it adds its own overhead and nothing else: 2 GiB and 10 GB.
A ten-level descent therefore asks its first level for 22 GB and 115 GB, where
handing resources down wanted 50 GB of memory for the same depth. The
processor follows a different rule; see below.

Three budgets can bound the depth, and `script/proxmox/nesting.py` names the
one that ran out:

* **memory** — every level must run its own daemons (`pve-cluster`,
  `pvestatd`, `pvedaemon`, `pveproxy`) *and* hold its child;
* **disk** — the child's disk lives *inside* the parent's, which must also
  hold its own system;
* **processor** — it does *not* grow with depth. Every nested level keeps a
  fixed, narrow width; only the first level counts against the physical cores.
  Either the machine can carry that first level or it can carry nothing.

That third rule is measured, and it cost two descents to get right. A nested
guest at the **fourth** level freezes in early boot as soon as it is wide:
twelve vCPU the first time, eight the second — same instruction pointer at
three readings five minutes apart, 32 MiB read and not one byte more for 106
minutes. Two vCPU boots.

The first freeze was blamed on **overcommit**: that VM had twelve vCPU on a
host with two. The second measurement refuted it — eight vCPU on a parent with
**nine**, load 1.47, no overcommit at all, and the same freeze. It is the
nested guest's vCPU count, not its ratio to its host's.

At the third level, 9 vCPU boots in 117 s. The threshold sits between the
third and fourth level, so no nested level is ever made wide. An earlier
version of this algorithm gave each parent one vCPU more than its child, which
made level 4 eight wide — exactly the frozen case. The rule made wide what
must stay narrow.

Hence three fixed widths: `VCPU_METAL` for level 1 (on bare metal, no freeze
risk — eleven vCPU booted there in 42 s), `VCPU_IMBRIQUE` for the deepest, and
`VCPU_INTERMEDIAIRE` in between, wide enough to host its child without being
as narrow as it. That middle number is a **hypothesis**: two is proven to boot
at the fourth level and eight is proven to freeze, with nothing measured in
between. The descent decides.

Memory is not the lever. On that same manual VM, dropping it from 9 GB to 2 GB
moved nothing — it stopped after reading the same 32 MiB, which is simply the
size of the boot files.

The plan is printed **before** anything is created, and the script never
promises a depth it knows will not fit — better to announce six levels and
reach six than to promise ten and die at the seventh without knowing why.

## deep_qemu.py — how deep does QEMU-in-QEMU go?

The same descent, a different stack — and the pair is the point. The fourth
level's slowdown comes from the **processor**: what a VM exit costs under
nested paging. The per-level *cost*, though, comes from what you install. A
Proxmox node lays down a kernel, corosync, ceph and a web UI; a libvirt host
lays down `libvirtd` and `qemu-kvm`. Measured together, the two separate what
is due to the hardware from what is due to the stack — two things the Proxmox
measurement alone confounds.

### What this test must prove before it measures anything

`deploy_qemu.py` never passes `--cpu host-passthrough`, and when `/dev/kvm` is
missing it does **not** fail: it sets `--virt-type qemu`, warns on one line,
and creates a fully **emulated** VM. Seven and a half minutes to boot, and no
exit code says so.

Unguarded, this script would measure stacked TCG while believing it measured
nesting — and return a more flattering number that means nothing. So every
level must prove, not assume:

* `/dev/kvm` is readable;
* `/sys/module/kvm_amd|kvm_intel/parameters/nested` reads `Y`;
* the child's domain is `<domain type='kvm'>`, checked right after creation.

**What was not read counts as NO.** An absent `/sys/module` file means an
unloaded module, not a permissions problem. A level that fails these stops the
descent instead of prolonging it into the void.

## qemu_cache.py — does the download cache really serve the second VM?

Two sibling VMs, the same distribution, the same packages. The first fills the
cache, the second must be served by it.

**Zero upstream bytes is the headline, not the criterion.** Arch is a rolling
release: between the two deployments a mirror can publish a newer version,
which the second VM legitimately fetches — the cache never serves an index
while upstream answers, so the VM sees it. A criterion built on volume alone
would call the cache broken while it works.

The criterion is therefore: **no URL requested by BOTH VMs is fetched upstream
a second time.** What the second VM discovers on its own is counted, shown,
and does not fail.

`--hors-ligne` adds the counter-proof, which is what makes the test worth its
hours: it cuts the upstream of the cache SERVICE alone — by its system
account, not by a blanket rule that would take down the ssh session running
the test — and deploys a third VM, which must build from the stored index.

```
./long_test/qemu_cache.py                 # two VMs
./long_test/qemu_cache.py --dry-run       # the plan, nothing created
./long_test/qemu_cache.py --hors-ligne    # + the third VM, upstream cut
./long_test/qemu_cache.py --detruire      # undo it
```

It needs the cache installed and running — `TODO › Deployment › QEMU cache` —
and it refuses to create anything before saying which prerequisite is missing.
Among those prerequisites: the rules must target the subnet libvirt actually
serves, which is not always 192.168.122.0/24.

What governs the duration is the FIRST VM's download, everything else being
boot and install: minutes on a machine with nested KVM and a nearby mirror,
much longer on a slow link. The second VM does not download at all — that is
what is being measured.

One limit the counter-proof exposes: with upstream cut, the repository
database SIGNATURES are missing from the cache, the mirror answering 404 for
them, so the cache returns its named 504. pacman treats them as optional and
carries on. A distribution that required them would stop there.
## install_nixos.py — ERPLibre s'installe-t-il sur NixOS ?

Not a depth: one machine, one binary question. The other two measure how far
nesting goes; this one asks whether the path the menu takes reaches the end on
a **declarative** system, where nothing is installed one command at a time.

It sends the menu's own remote command, `_qemu_erplibre_remote_cmd`, taken as
it is. A test that installed by its own means would prove *its* path, not the
product's — and that is exactly where the failures hid: a bootstrap with no
nix branch, a Makefile assuming `/bin/bash`, compile paths read from a session
older than the module it had just applied.

The block goes in **one** ssh session, as the deployment does. That is the
condition that exposes the first-pass failure: the session opens before
`make install_os` applies the module, so before `pam_env` sets `CPATH`, and
the packages with no upstream wheel stopped there. Replaying the install in a
fresh session succeeds and proves the wrong thing.

The verdict is the **state of the machine**, not a return code:
`nixos-rebuild switch` returns 4 on a system that is nonetheless activated,
and every tool block of the menu returns 0 by construction. So it checks what
`envfs` makes (`/bin/bash`, `/usr/bin/env`, `/usr/bin/python3.x`), the venv,
the four modules that have no wheel and must compile — psycopg2, python-ldap,
pycups, mysqlclient — the absence of the HTML manuals, and Odoo answering.

```
./long_test/install_nixos.py                 # create the VM, install, judge
./long_test/install_nixos.py --dry-run       # the plan and the commands
./long_test/install_nixos.py --hote nixos-1  # on a machine you already have
./long_test/install_nixos.py --detruire      # undo it
```

`--hote` expects a machine that **already runs NixOS**: the script installs
ERPLibre there, it does not install the system.

It clones from the **published** repository, on the branch asked for
(`develop` by default). That is deliberate — the test measures what a user
receives, not what a local checkout holds. Say it before running: a fix still
on an unmerged branch is *not* in the VM, and the test will fail on whatever
that fix repairs.

## install_erplibre_home.py — does ERPLibre Home run on every distribution?

One VM per distribution version, one at a time: Ubuntu 24.04, 25.10 and
26.04, Debian 13, Fedora 41 to 44, AlmaLinux 10, Rocky Linux 10, openSUSE
Leap 16.0, and the two rolling ones, Arch Linux and openSUSE Tumbleweed. The
systems GNOME 45 to 51 does not reach — Debian 12, the EL9 rebuilds — and
those without a GNOME desktop path — NixOS, Proxmox — are listed
`UNSUPPORTED` and get no VM.

Each VM gets the GNOME desktop through the menu's own remote command, then
the code of **this checkout**, sent as a `git bundle` of `HEAD`: the VM never
reaches GitHub for it. A modified tracked file makes the run refuse to
start, since it would not be in the VM. Then `install_erplibre_home.sh` installs
the ERPLibre Home base, GDM logs the user in automatically, and the VM
reboots.

The verdict is what GNOME Shell answers, not a return code: `GetExtensionInfo`
must report state `1` and an empty `error`. Being listed in
`enabled-extensions` is not enough — an extension that throws in `enable()`
stays listed, in ERROR. The extension's own `ListPaths` and `ListDevices`
must answer too. ACTIVE does not prove the top bar either: the extension
catches an indicator constructor's exception and keeps running, so the
`extension-indicators` check reads the user journal: it requires the
`[ERPLibreHome] enabled` line that ends `enable()`, so an unread journal
fails too, and it fails on any `[ERPLibreHome] mount <id> failed` line.
Every read of the user journal (this check, `reinstall-indicators`,
`service-condition`, the failure diagnostic) falls back to
`sudo -n journalctl _UID=$(id -u)` when `journalctl --user` prints nothing:
with volatile journald storage (EL 10 cloud images) the user's entries live
in the system journal only, which a user outside `systemd-journal` or
`wheel` cannot read through `--user`. Two empty reads still fail.

That is the first of five stages, run in order on the same VM:

1. **base**: the checks above, then neither the udev rule nor
   `.venv.streamdeck` exists, and a second base install changes nothing;
2. **stream-deck**: `--stream-deck --deck-program=tiler --autostart`
   writes the udev rule, the venv imports what the deck programs import,
   the deck service unit runs this checkout's entry point and is enabled,
   `systemctl --user start` skips it since a VM has no deck (inactive,
   `Result=exec-condition`, or `success` on some systemd versions,
   `ExecMainStartTimestampMonotonic=0`, and the entry point's "no Stream
   Deck plugged in" line in the unit's journal written since that start,
   so an earlier skip at login does not count; the read is retried a few
   times while journald catches up), the extension stays ACTIVE, and a
   second run
   changes nothing, unit and settings included;
3. **partial-uninstall**: `--uninstall --stream-deck` removes the rule,
   the venv, the unit, its `graphical-session.target.wants` link and its
   settings, `systemctl --user is-enabled` says `not-found`, and the
   extension stays linked, enabled and ACTIVE;
4. **uninstall**: `--uninstall` leaves neither link, nor UUID in
   `enabled-extensions`, nor rule, nor venv, nor unit, nor settings. Stage
   3 already removed the deck service, so this stage only checks that a
   full uninstall leaves it gone; no stage runs `--uninstall` on a
   system that still has the unit;
5. **reinstall**: the base again, then a reboot: the extension comes back
   ACTIVE with every indicator mounted, without the rule or the venv.

A stage command that fails, or the first failed check, names the verdict
(`FAILED(install-stream-deck)`, `FAILED(reinstall-no-udev)`…): every name is
unique, so it tells which stage stopped.

```
./long_test/install_erplibre_home.py                 # the whole matrix
./long_test/install_erplibre_home.py --only ubuntu:24.04,fedora:43
./long_test/install_erplibre_home.py --extras        # --with-extras on 24.04
./long_test/install_erplibre_home.py --dry-run       # the plan, nothing created
./long_test/install_erplibre_home.py --garder        # keep the VMs
./long_test/install_erplibre_home.py --detruire      # undo the last run
```

A real run needs `sudo` for its whole duration: each VM is created by
`sudo deploy_qemu.py`, and destroyed through `sudo -n virsh`. Either allow
`virsh` and `deploy_qemu.py` without a password, or keep a sudo session
alive for the run. Only one VM lives at a time: when a VM survives its
destroy, even after `sudo -v`, the run stops, marks the remaining systems
`FAILED(previous-vm-still-up)` and exits 1; `--detruire` undoes it.
`--garder` keeps every VM running, 4 GiB each: pair it with `--only`.

The report lists one line per system, with the GNOME version expected and
the one measured: the matrix in the script is corrected from those lines. On
Arch and Tumbleweed, `UNSUPPORTED` means GNOME moved past 51, and it is the
expected signal to update `metadata.json`. Each system's log — installer
output, user journal, `gnome-extensions info` — is a `.log` in the run's
sub-directory. It proves every check: a `── contrôle <name> : réussi` or
`ÉCHEC` line per command and check, followed by each command it ran, and on
a failure by that command's raw reply.

## mobile_sync.py — does the mobile app sync with Odoo 16, 17 and 18?

No VM here: throwaway Odoo databases and servers, and the phone when one is
plugged in. The app's own sync code (`mobile/erplibre_home_mobile`, through
its versioned test kit `src/testing/syncTestKit.ts`) runs under Vitest against
real servers: tasks, conflicts, opportunities, invoices, activities, messages,
proposed dates, two companies, files, a cut network or a lost answer, deleted
records, one note on three servers. Each scenario checks the result in Odoo,
and a proxy between the app and each server records what crossed the wire.

```
./long_test/mobile_sync.py                     # 16, 17 and 18
./long_test/mobile_sync.py --versions 18       # one version
./long_test/mobile_sync.py --filtre conflit    # tests whose name matches
./long_test/mobile_sync.py --dry-run           # the plan, nothing created
./long_test/mobile_sync.py --appareil          # also on the plugged phone
./long_test/mobile_sync.py --garder            # keep databases and servers
./long_test/mobile_sync.py --detruire          # drop templates and cache
```

It checks the mobile repository first — absent, without `node_modules`, Node
older than 22, or a test kit of another API — and says what to do. The first
run builds one template database per version (a few minutes); the next ones
copy it, and the whole suite takes about 30 seconds. A report with no test,
or no test for one version, fails: a path resolved wrong must not pass for a
green run.

Chat is tested on Odoo 18 only, where Discuss and the websocket bus exist.
The 18 template adds what those scenarios need: the `erplibre_mobile_chat`
module from the ERPLibre addons, a second user, `chat_user`, and a group
channel « ms chat » where he and the app's user talk, with no unread message
for chat_user at the start. `chat.test.ts` covers the load and its counters,
a post that reaches chat_user once, a lost answer with the module and with
the marker alone, the offline queue keeping its order, history paging, and
the read mark seen on the server. `chatRealtime.test.ts` covers the bus
delivering a message and the typing of chat_user, the counters of the first
connection, and a cut socket that delivers on reconnect. `chatManage.test.ts`
covers managing conversations against the real server, reading each result
back from it: a direct message made once and reused, a group created offline
then the app restarted with the create's answer lost (one group, its posts
once and in order, with the module's uuid dedupe and without it, by
fingerprint), the access groups of a new channel, a join, an invite, rename
and description, a leave with a post still queued, a hidden direct message
shown again when the other user writes, a mute and a global mute (one queued
past its end unmutes), and a removal by the administrator told on the removed
user's bus, which a non-administrator is refused. The scenario of a group that
chat_user creates and fills runs as `mc_user`, the two-company user, whom no
other file's conversation involves, so every `/mail/data` through its proxy
is its own and the later messages must arrive by the bus with no reload.
Every template, the 16, 17 and 18 ones alike, creates the settings of every
internal user ahead (two simultaneous first requests would otherwise both
create them and hit the uniqueness of `res.users.settings`), and the 18 one's
module is the 1.4, which dedupes creates and uploads, guards edits, searches the
member channels, sets a star instead of toggling it and dedupes the posts of
every record.
`--appareil` adds the « clavardage » screen and a group created from the
phone. To run only these:

```
./long_test/mobile_sync.py --versions 18 --filtre chat
./long_test/mobile_sync.py --versions 18 --filtre chat --appareil
```

`chatAttachments.test.ts` covers the files of a message against the real
server, each case read back from it. Where it says « on both routes », it
runs once on the module's route and once with the module ignored, on
Odoo's own. A lost upload answer leaves one attachment in one message (the
module's route returns the first one for the same `client_uuid`, Odoo's is
searched for and reused, a photo it stored resized to another size included); a lost post answer with two files posts one message
holding both; a voice file arrives as `audio/mpeg` with its voice metadata;
and an expired session answers 404 once, then the upload goes through. The
module's route keeps a photo's original (same checksum as the source file)
where Odoo's reduces it to 1920 px. A limit lowered before the app reads it
refuses the file at staging, and lowered after queueing refuses it with the
server's 413: the text is posted without it and the user is told once. On a
mobile network nothing leaves until Wi-Fi returns. A peer's image costs one
preview request of 512 px at most and downloads its original only when
opened, and a history of 20 attachments makes no file request at all. The
cases that lower the server's upload limit bound every request of the shared
server, so they live in `*.serial.test.ts` files, which run in a second pass,
one file at a time, after the parallel pass; the two reports merge into one
verdict. `--appareil` adds the « pièces jointes du clavardage » screen: a
file sent from the composer reaches the server once with its original
checksum, the attach and microphone buttons sit above the navigation bar, a
real tap records a voice message that arrives as MP3, a peer's photo shows its
preview and opens in the viewer, and a peer's voice message plays. The camera
and the system pickers are the vendor's screens and stay outside the run. The
device run also reads the `lastUpdateTime` of the user's own app before and
after, and fails if it changed or cannot be read. The kit's harness checks
(the API versions of the kit and of the device hook, the scenario list) run
with the unit tests of the platform; the standard library's `test` package
shadows `test/`, so the file is found by discovery:

```
.venv.erplibre/bin/python -m unittest discover -s test -p test_mobile_sync_harness.py
```

`chatActions.test.ts` covers the actions on a message against the real server,
each result read back from it. A reaction whose answer is lost leaves one row
after the retry; one added then removed offline sends no request; and
chat_user's reaction and edit reach the app by the bus with no reload. Where it
says « on both routes », the edit runs once on the module's guarded route and
once with the module ignored, on Odoo's: an edit of a message with two files
changes the text and keeps both files; an edit whose answer is lost, its body
opening on a mention that Odoo stores wrapped, counts as done on its replay,
and a correction made meanwhile follows it with no notice; a late edit, made
after chat_user edited or deleted the message in the browser, is refused with
the app's text kept for « Reprendre » and the server's body untouched; a delete
empties the body and removes the files, hidden in the app and for chat_user; a
reply keeps its parent on the server, a reply whose parent chat_user deletes
meanwhile is posted on it and quoted as deleted, and a reply to a message of
another conversation is posted as a plain message. `chatWriting.test.ts` covers
what the app writes: a mention of chat_user in a channel gives him a
notification (only a partner with an email address and inbox notifications is
notified of a channel mention, so the file gives him both for its run),
`@everyone` puts every member in `partner_ids`, `#channel` is stored as Odoo's
channel link, and a body that starts with a mention is stored in a `<span>`.
The round trip takes every case of the composer goldens, posts it, and has
chat_user's browser save it again: the body is stored as it was, the edited
span aside.

The goldens are produced by Odoo's own formatter, not written by hand.
`long_test/mobile_sync_composer.py` opens a session on an Odoo 18 in a
headless Chromium, loads Discuss, runs `prettifyMessageContent` of
`@mail/utils/common/format` on each case of `composer-cases.json` (with the
mentions `getMentionsFromText` keeps) and writes `composer-golden.json` next
to it, in the mobile repository's `src/__tests__/fixtures/`. It refuses a
server that is not an Odoo 18; the function runs in the page, so any Odoo 18
gives the same bodies.

```
./long_test/mobile_sync_composer.py http://127.0.0.1:8069 admin admin --base my_database
./long_test/mobile_sync.py --versions 18 --filtre chat
```

The « actions du clavardage » scenario of `--appareil` runs on Odoo 18 on the
phone: a long press of 700 ms opens the message menu and the click that ends
it chooses nothing, the native text selection of a bubble gives way to the
menu, a tap on a suggestion keeps the keyboard open with the text field
visible, a quote scrolls to its original, the « (modifié) » mark follows the
text, and the composer stays within 16 px above the navigation bar in every
chat scenario, the keyboard open or not.

`chatFinding.test.ts` covers finding things against the real server, as the
app's user. Where it says « the module and the module ignored », the search
runs on the module's route and on the `search_read` fallback. A server search
sees only the channels the user is a member of, never a public channel not
joined and never chat_user's private chat with someone else, and marks nothing
read; a term holding `&` or `%` finds the same messages on the module, on the
fallback and on the phone's own search; opening a hit older than the loaded
history pages older messages with `around` only and marks nothing read; a pin
whose answer is lost leaves `pinned_at` set and one pin notice; chat_user's pin
reaches the pinned list; a star whose answer is lost is starred once after the
retry, on the module and with it ignored; and a star made in the user's browser
since the load, then starred on the phone, stays starred.

`chatInbox.test.ts` covers the inbox against the real server, as `inbox_user`,
a user the template seeds for it: internal, a project user, with
`notification_type` written explicitly to `inbox` (the group alone leaves a new
user on email), a member of « ms chat », and with an email address, because a
channel mention notifies only a partner that has one. His tests run in order.
A mention, a comment on a followed task and an assignment fill the three kinds
of item; a server search for the mentioned word leaves the mention unread; one
item marked read is `is_read` on the server; mark all tapped offline while
chat_user mentions again leaves the newer mention unread; a reply as a note
with a photo is one note holding the photo and sends no email, a reply as a
message is one comment and one email to the follower notified by email (counted
as `mail.mail`), and a reply whose upload answer, then post answer, are lost
posts one message with one attachment, on the module and with it ignored; two
comments and a mention reach the open inbox by the bus, with no
conversation page read; and a user notified by email is told why the inbox is
empty, switches to the inbox, and the server reads `inbox`. The follower
notified by email is a user the file creates, because another file switches
chat_user's preference for the whole run.

The test servers' SMTP points at a closed local port of the machine. Odoo
sends notification emails right after the commit, and the host may run a mail
server of its own: without this, a test mail would leave the machine, and a
sent mail is deleted, so there would be no `mail.mail` to count. With it, the
mail stays in `mail.mail` in the `exception` state, counted and never
delivered.

The « recherche et boîte du clavardage » scenario of `--appareil` runs on
Odoo 18 on the phone: a message is sent, edited and deleted, then the search
index passes SQLite's integrity check once (or the phone uses the LIKE
fallback); a search from the list opens the conversation at the hit,
highlighted; a long press then Pin, confirmed in the native dialog, sets
`pinned_at` on the server; the star action stars it; the inbox of an email-notified
user shows the explanation, the switch writes `inbox`, a mention of chat_user
appears and « Marquer comme lu » reads it; a reply on a task with a photo
posts it; in a group, the second bubble of a run of one author's messages
shows neither name nor avatar, while the first shows the author's name and
avatar (an author check on the rendered bubbles); and an old hit, followed by
more unread messages than the thread first renders, opens the conversation at
it while the user's seen message on the server stays where it was.

`--appareil` plays its screens on the phone, against the same servers: the
target picker, the banner of a date changed on the server, typing during a
pull, the dated note made from the calendar, and, on Odoo 18 only, the chat
(the tile opens the list within 2 s, and the composer of « ms chat » within
2 s too, three messages typed there in a row reach the server once each,
the keyboard staying open from one send to the next, chat_user's reply shows through the native websocket) and a
group created from the phone with chat_user, which exists once on the server
under its name, whose info screen lists chat_user among the members and in
which messages go both ways. They
run in a separate app,
`ca.erplibre.home.synctest`, built by `-PsyncTest` from a development bundle
and cleared for each version; the user's own app is never touched. The phone
must be unlocked, with USB debugging allowed. A failure keeps a screenshot in
the run's directory, `cache/mobile_sync/runs/`.

A run kept by `--garder` is stopped and swept by the next run, or by
`--detruire`. Exit codes: 0 all green, 1 tests failed, 2 a prerequisite is
missing, 3 the infrastructure failed.

### The chat push tests — notifications while the app is closed

The run starts its own `ntfy serve`, on `127.0.0.1` and a free port, with a
temporary `server.yml`, access file and cache under the run directory; it never
touches the ntfy of the machine (every `ntfy` call carries `--config`, placed
before the subcommand for `user` and `token`). The phone's access is created
the way the `TODO › Deploy › Prepare ntfy for ERPLibre mobile` menu creates it:
anonymous write-only on `up*`, a read-only user on its prefix, a token. The
ntfy stops with the run (kept with the servers by `--garder`).

`--filtre push` plays the tests whose name matches: the four push shapes
decrypted from the ntfy cache, a muted conversation that is not pushed, a token
that reads only its own prefix, the unregistration when an account is removed,
the move to a new topic when a new link comes, and, alone in a serial file, the
VAPID keys drawn again, which the next load heals.

Two more files play the second lot of the notifications. `chatPushModule.test.ts`
plays module 1.5: a device marked through `/erplibre_mobile_chat/push/device`
gets the message id and the channel type, an unmarked one gets Odoo's own
payload, a read in the browser or the author's own post sends a « read » push
to the app's devices only, an inbox read sends `inbox_done` with the record,
and a device marked quiet hears nothing while a browser is online.
`chatPushActions.test.ts` plays what the app does with an action the phone
handed over: a reply is posted once, or not at all when Odoo already holds it,
a read marks the conversation read with read receipts off, a mute lasts the
hour that is left, and a reply's answer shows the message in the cache.

With `--appareil`, the notifications scenario runs on the phone, on Odoo 18,
against that ntfy sent to the phone by `adb reverse`: at level 1 the app is
connected and shows one permanent notification; a message from another user
rings within a few seconds under its conversation's tag, with its text in clear
and, in the lock-screen version, only « Nouveau message — <server> » or no
lock-screen version at all, whichever Android's setting calls for; the
process killed (`am crash`, since SELinux refuses `run-as kill` on Android 11),
the service comes back and the next message stacks in the same notification;
tapping it opens the conversation; in the foreground nothing shows; with
« Never shown » the text is not in the notification; with the ntfy removed, the
Odoo-direct summary reads « 2 nouveaux messages » and nothing is marked read on
the server. The scenario never locks the phone: the lock-screen form is read
from `dumpsys notification --noredact`. It restores what it changes: the
`stay_on_while_plugged_in` setting, the battery-optimisation entry of the test
app and the `adb reverse` ports.

A second device scenario, « chat actions, app killed », runs with the module
on the run's Odoo: the app killed, a message shows with three buttons;
« Reply », typed in the shade, posts once and the author's read push clears the
notification; « Mark read » reads the conversation up to the message; « 👍 »
reacts and the notification stays, « Mute 1 h » taking its place and muting for
an hour; a read in the browser clears the notification; with « Never shown »
the notification says « Nouveau message » only, with the same buttons; with the
phone's session copy broken the reply is handed to the app, which posts it once
when the handoff notification is tapped; a device the module does not know gets
Odoo's payload without a message id and « Mute 1 h » as the third button. Every
tap is bound to the test app's own notification row, so another app's
notification on the shade is never touched or typed into.

## Starting from a host you already have

The three scripts take `--hote`. Creating a head VM to host a hypervisor you
already own costs five minutes *and* one level of nesting — that is, slowness,
which is the very thing being measured.

```
./long_test/deep_proxmox.py --hote root@10.0.0.5      # an existing Proxmox
./long_test/deep_qemu.py --hote erplibre@10.0.0.7     # an existing libvirt host
```

Three things follow, and they are not decorative:

* the plan is sized on the **root**, read over ssh — sizing it on the local
  machine while the levels live elsewhere would announce levels that do not
  fit;
* the delays count **absolute** depth: a level-1 child placed in a root that
  is already at the third level is really at the fourth;
* the root is **never** a level reached, and **never** destroyed. A borrowed
  host has no local libvirt UUID, so `--detruire` refuses to fall back on its
  name — `virsh undefine --remove-all-storage` erases a disk for good.

The menu offers the host already chosen without searching for it, and undoes
each stack separately: they share the report directory, but each knows only
its own reports.
