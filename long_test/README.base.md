<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
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

<!-- [fr] -->
# long_test — des tests qui créent de vraies machines

Ce ne sont pas des tests unitaires. Ils créent des machines virtuelles, y
installent des systèmes, et durent des heures. Ils vivent ici et **non** dans
`test/`, que le lanceur unitaire balaie : `./script/test/run_unit_test.sh`
doit rester lançable en quelques secondes, sur n'importe quelle machine, y
compris sans virtualisation.

Ils se lancent depuis le menu — `TODO › Execute › Test › Tests longs` — ou
directement.

## deep_proxmox.py — jusqu'à quel étage un Proxmox dans un Proxmox tient-il ?

La profondeur d'imbrication praticable ne se déduit pas, elle se mesure — et
une mesure n'est pas une mesure.

Un examen à la main d'UNE VM du quatrième étage a trouvé un invité **36 fois
plus lent que le temps réel** (583 secondes d'horloge pour 16 secondes de
temps invité, chaque ligne d'ACPI prenant une seconde), puis un noyau gelé :
même RIP à trois relevés deux minutes d'écart, et **pas un octet écrit** sur
le disque.

Lancer ce script a **réfuté la conclusion qu'on en avait tirée**. Sa propre VM
du quatrième étage — 2 vCPU là où celle de la main en avait 12 — a démarré,
s'est installée, et a écrit des gigaoctets. Ce qui ressemblait à un plafond
d'imbrication était un plafond de *parallélisme* sous imbrication. C'est
précisément ce que l'algorithme borne, et c'est ainsi qu'il a cessé d'être une
supposition.

D'où le script : un chiffre obtenu une fois, sur une machine, dans une chaîne,
est une anecdote.

```
./long_test/deep_proxmox.py                        # trois étages, ~30 minutes
./long_test/deep_proxmox.py --dry-run              # le plan, rien de créé
./long_test/deep_proxmox.py --depth 5              # en demander plus, sciemment
./long_test/deep_proxmox.py --detruire             # défaire
```

### Quelle profondeur vaut la peine d'être demandée

La profondeur est le seul réglage, et **trois** est le défaut parce que trois
marche. Mesuré sur une machine à 28 cœurs, une descente complète par ligne :

| étage | amorçage (ssh) | installation | total |
|------:|---------------:|-------------:|------:|
| 1 | 0 s | 200 s | 280 s |
| 2 | 37 s | 344 s | 495 s |
| 3 | 93 s | 777 s | 1 064 s |
| 4 | **15 608 s** | **26 306 s** | n'a pas abouti |

Trois étages coûtent une demi-heure. Le **quatrième** a coûté 4 h 20
d'amorçage et 7 h 18 d'installation sur la même machine — tout y est 15 à 30
fois plus lent, pas une seule étape. Et cela tombe précisément là où les
fabricants s'arrêtent : le quatrième étage est le *troisième* hyperviseur
imbriqué, et AMD en documente deux.

Un invité plus large aggrave brutalement : au quatrième étage, un vCPU de plus
a multiplié l'amorçage par 9,4 (1 664 s à deux vCPU, 15 608 s à trois), et à
huit vCPU l'invité a lu 32 Mio en 106 minutes, pointeur d'instruction
immobile. Aux étages 2 et 3, ce même vCPU ne coûte rien.

Donc : trois par défaut, cinq pour savoir, dix seulement pour voir le mur.

La descente est **uniforme**. Chaque étage, le premier compris, passe par les
mêmes six étapes : créer, attendre le ssh, installer Proxmox, redémarrer et
vérifier le noyau, remettre pmxcfs debout, contrôler le stockage. Seule la
création diffère — libvirt en local, `qm` ensuite.

Il envoie **notre** `install_proxmox.sh` par scp au lieu de laisser la VM
cloner le dépôt : c'est notre code qu'on veut éprouver, et le dépôt distant
est souvent en retard sur le checkout — un correctif absent du distant a fait
« revenir » le même défaut sur trois VM de suite.

### L'algorithme de ressources — dimensionné depuis le bas

La première version cédait à l'enfant ce que le parent pouvait céder, et une
descente réelle a montré ce que cela coûte. L'étage 4 se retrouvait avec 44 Go
de mémoire et 2 vCPU **sur un hôte qui en avait 2** — cent pour cent de
surengagement, à chaque étage, avec l'hyperviseur lui-même à servir par-dessus.
Son installation dépassait deux heures et demie contre treize minutes pour
l'étage 3, et l'extrapolation de ce rapport donnait cinq ANS pour le dixième.

Le sens est donc inversé pour la **mémoire et le disque**. Le plus profond
reçoit ce qu'un Proxmox de test demande vraiment — 4 Go de mémoire, 25 Go de
disque — et chaque parent au-dessus ajoute son propre surcoût, rien d'autre :
2 Gio et 10 Go. Une descente à dix étages demande ainsi 22 Go et 115 Go à son
premier étage, là où la cession de haut en bas voulait 50 Go de mémoire pour la
même profondeur. Le processeur, lui, suit une autre règle — voir plus bas.

Trois budgets peuvent borner la profondeur, et `script/proxmox/nesting.py`
nomme celui qui a manqué :

* **la mémoire** — chaque étage doit faire tourner ses propres démons
  (`pve-cluster`, `pvestatd`, `pvedaemon`, `pveproxy`) *et* héberger son
  enfant ;
* **le disque** — le disque de l'enfant vit *dans* celui du parent, qui doit
  aussi contenir son propre système ;
* **le processeur** — il ne croît *pas* avec la profondeur. Tout étage
  imbriqué garde une largeur fixe et étroite ; seul le premier compte sur les
  cœurs physiques. Ou la machine peut porter ce premier étage, ou elle ne peut
  rien.

Cette troisième règle est mesurée, et il a fallu deux descentes pour la poser
juste. Un invité imbriqué au **quatrième** étage gèle en tout début de
démarrage dès qu'il est large : douze vCPU la première fois, huit la seconde —
même pointeur d'instruction à trois relevés espacés de cinq minutes, 32 Mio lus
et plus un octet pendant 106 minutes. Deux vCPU démarrent.

Le premier gel avait été imputé au **surengagement** : cette VM à douze vCPU
tournait sur un hôte qui en avait deux. La seconde mesure l'a réfuté — huit
vCPU sur un parent qui en avait **neuf**, charge 1,47, aucun surengagement, et
le même gel. C'est le nombre de vCPU de l'invité imbriqué, et non son rapport à
celui de son hôte.

Au troisième étage, 9 vCPU démarrent en 117 s. Le seuil est entre le troisième
et le quatrième étage : aucun étage imbriqué n'est donc rendu large. Une version
précédente de cet algorithme donnait un vCPU de plus à chaque parent, ce qui
rendait l'étage 4 large de huit — exactement le cas gelé. La règle rendait large
ce qui doit rester étroit.

D'où trois largeurs fixes : `VCPU_METAL` pour l'étage 1 (sur le métal, aucun
risque de gel — onze vCPU y ont démarré en 42 s), `VCPU_IMBRIQUE` pour le plus
profond, et `VCPU_INTERMEDIAIRE` entre les deux, juste assez large pour héberger
son enfant sans être aussi étroit que lui. Ce nombre du milieu est une
**hypothèse** : deux démarre au quatrième étage, huit gèle, et rien n'est mesuré
entre les deux. C'est la descente qui tranche.

La mémoire n'est pas le levier. Sur cette même VM examinée à la main, la faire
passer de 9 Go à 2 Go n'a rien déplacé : elle s'arrêtait après avoir lu les
mêmes 32 Mio, c'est-à-dire simplement la taille des fichiers d'amorçage.

Le plan est affiché **avant** que quoi que ce soit ne soit créé, et le script
ne promet jamais une profondeur qu'il sait irréalisable — mieux vaut annoncer
six étages et en réussir six que d'en promettre dix et mourir au septième sans
savoir pourquoi.

## deep_qemu.py — jusqu'à quel étage une QEMU dans une QEMU tient-elle ?

La même descente, une autre pile — et c'est le couple qui compte. Le
ralentissement du quatrième étage vient du **processeur** : de ce que coûte une
sortie de VM sous pagination imbriquée. Le *coût* par étage, lui, vient de ce
qu'on installe. Un nœud Proxmox pose un noyau, corosync, ceph et une interface
web ; un hôte libvirt pose `libvirtd` et `qemu-kvm`. Mesurées ensemble, les
deux séparent ce qui tient au matériel de ce qui tient à la pile — deux choses
que la seule mesure Proxmox confond.

### Ce que ce test doit prouver avant de mesurer quoi que ce soit

`deploy_qemu.py` ne passe jamais `--cpu host-passthrough`, et quand
`/dev/kvm` manque il n'échoue **pas** : il pose `--virt-type qemu`, avertit sur
une ligne, et crée une VM entièrement **émulée**. Sept minutes et demie de
démarrage, et aucun code de retour ne le dit.

Sans garde, ce script mesurerait de la TCG empilée en croyant mesurer de
l'imbrication — et rendrait un chiffre plus flatteur qui ne veut rien dire.
Chaque étage doit donc prouver, et non supposer :

* `/dev/kvm` est lisible ;
* `/sys/module/kvm_amd|kvm_intel/parameters/nested` vaut `Y` ;
* le domaine de l'enfant est `<domain type='kvm'>`, vérifié juste après sa
  création.

**Ce qui n'a pas été lu vaut NON.** Un fichier `/sys/module` absent, c'est un
module non chargé, pas un problème de permission. Un étage qui échoue à cela
arrête la descente au lieu de la prolonger dans le vide.

## qemu_cache.py — le cache de téléchargement sert-il vraiment la seconde VM ?

Deux machines sœurs, la même distribution, les mêmes paquets. La première
remplit le cache, la seconde doit être servie par lui.

**« Zéro octet d'amont » est la manchette, pas le critère.** Arch est une
publication continue : entre les deux déploiements, un miroir peut publier une
version neuve, que la seconde VM tire légitimement — le cache ne sert jamais
un index tant que l'amont répond, donc elle la voit. Un critère fondé sur le
seul volume déclarerait le cache en panne alors qu'il fonctionne.

Le critère est donc : **aucune URL demandée par les DEUX VM n'est retirée de
l'amont une seconde fois.** Ce que la seconde découvre seule est compté,
montré, et n'échoue pas.

« --hors-ligne » ajoute la contre-épreuve, qui fait la valeur de ces heures :
elle coupe l'amont du SEUL service du cache — par son compte système, non par
une règle générale qui emporterait la session ssh depuis laquelle le test se
lance — et déploie une troisième VM, qui doit se bâtir sur l'index stocké.

```
./long_test/qemu_cache.py                 # deux VM
./long_test/qemu_cache.py --dry-run       # le plan, rien de créé
./long_test/qemu_cache.py --hors-ligne    # + la troisième VM, amont coupé
./long_test/qemu_cache.py --detruire      # défaire
```

Il exige le cache installé et actif — « TODO › Déploiement › Cache QEMU » — et
refuse de rien créer avant d'avoir dit lequel des préalables manque. Parmi
eux : les règles doivent viser le sous-réseau que libvirt sert vraiment, qui
n'est pas toujours 192.168.122.0/24.

Ce qui gouverne la durée est le téléchargement de la PREMIÈRE VM, le reste
n'étant que démarrage et installation : quelques minutes sur une machine à
KVM imbriqué et miroir proche, bien davantage sur une liaison lente. La
seconde VM ne télécharge rien — c'est précisément ce qu'on mesure.

Une limite que la contre-épreuve met au jour : amont coupé, les SIGNATURES
des bases de dépôt manquent au cache, le miroir y répondant 404, et le cache
rend donc son 504 nommé. pacman les traite comme optionnelles et poursuit.
Une distribution qui les exigerait s'arrêterait là.
## install_nixos.py — ERPLibre s'installe-t-il sur NixOS ?

Pas une profondeur : une machine, une question binaire. Les deux autres
mesurent jusqu'où l'imbrication tient ; celui-ci demande si le chemin que le
menu emprunte aboutit sur un système **déclaratif**, où rien ne s'installe
commande par commande.

Il envoie la commande distante du menu, `_qemu_erplibre_remote_cmd`, prise
telle quelle. Un test qui installerait par ses propres soins prouverait *son*
chemin, pas celui du produit — et c'est justement là que se cachaient les
pannes : un amorçage sans branche nix, un Makefile qui présumait `/bin/bash`,
des chemins de compilation lus d'une session plus vieille que le module
qu'elle venait d'appliquer.

Le bloc part en **une** session ssh, comme le déploiement le fait. C'est la
condition qui expose la panne du premier passage : la session est ouverte
avant que `make install_os` n'applique le module, donc avant que `pam_env` ne
pose `CPATH`, et les paquets sans roue amont s'y arrêtaient. Rejouer
l'installation dans une session neuve réussit et donne raison à tort.

Le verdict est l'**état de la machine**, pas un code de retour :
`nixos-rebuild switch` rend 4 sur un système pourtant activé, et chaque bloc
d'outil du menu rend 0 par construction. On contrôle donc ce que fabrique
`envfs` (`/bin/bash`, `/usr/bin/env`, `/usr/bin/python3.x`), le venv, les
quatre modules sans roue qui doivent se compiler — psycopg2, python-ldap,
pycups, mysqlclient —, l'absence des manuels HTML, et Odoo qui répond.

```
./long_test/install_nixos.py                 # crée la VM, installe, juge
./long_test/install_nixos.py --dry-run       # le plan et les commandes
./long_test/install_nixos.py --hote nixos-1  # sur une machine qu'on a déjà
./long_test/install_nixos.py --detruire      # défaire ce qui a été posé
```

`--hote` attend une machine qui porte **déjà** NixOS : le script y installe
ERPLibre, il n'y installe pas le système.

Le clone vient du dépôt **publié**, sur la branche demandée (`develop` par
défaut). C'est voulu : le test mesure ce qu'un utilisateur reçoit, pas ce
qu'un checkout local contient. À dire avant de lancer : un correctif encore
sur une branche non fusionnée n'est *pas* dans la VM, et le test échouera sur
ce que ce correctif répare.

## install_erplibre_home.py — ERPLibre Home tourne-t-il sur chaque distribution ?

Une VM par version de distribution, l'une après l'autre : Ubuntu 24.04, 25.10
et 26.04, Debian 13, Fedora 41 à 44, AlmaLinux 10, Rocky Linux 10, openSUSE
Leap 16.0, et les deux roulantes, Arch Linux et openSUSE Tumbleweed. Les
systèmes que GNOME 45 à 51 n'atteint pas — Debian 12, les reconstructions
EL9 — et ceux sans chemin de bureau GNOME — NixOS, Proxmox — sont listés
`UNSUPPORTED` et n'ont pas de VM.

Chaque VM reçoit le bureau GNOME par la commande distante du menu, puis le
code de **ce checkout**, envoyé en `git bundle` de `HEAD` : la VM ne joint
jamais GitHub pour lui. Un fichier suivi et modifié fait refuser la course,
puisqu'il ne serait pas dans la VM. Puis `install_erplibre_home.sh` installe
la base d'ERPLibre Home, GDM ouvre la session de l'utilisateur tout seul, et
la VM redémarre.

Le verdict est ce que GNOME Shell répond, pas un code de retour :
`GetExtensionInfo` doit rendre l'état `1` et une `error` vide. Figurer dans
`enabled-extensions` ne suffit pas — une extension qui lève dans `enable()` y
reste listée, en ERREUR. Les `ListPaths` et `ListDevices` de l'extension
doivent répondre aussi. ACTIVE ne prouve pas non plus la barre du haut :
l'extension attrape l'exception du constructeur d'un indicateur et continue,
alors le contrôle `extension-indicators` lit le journal utilisateur : il
exige la ligne `[ERPLibreHome] enabled` qui clôt `enable()`, si bien qu'un
journal non lu échoue aussi, et il échoue sur toute ligne
`[ERPLibreHome] mount <id> failed`.
Toute lecture du journal utilisateur (ce contrôle, `reinstall-indicators`,
`service-condition`, le diagnostic d'échec) retombe sur
`sudo -n journalctl _UID=$(id -u)` quand `journalctl --user` n'imprime rien :
avec un stockage journald volatil (images cloud EL 10), les entrées de
l'utilisateur ne vivent que dans le journal système, que `--user` ne lit pas
hors des groupes `systemd-journal` ou `wheel`. Deux lectures vides échouent
toujours.

C'est la première de cinq étapes, menées dans l'ordre sur la même VM :

1. **base** : les contrôles ci-dessus, puis ni la règle udev ni
   `.venv.streamdeck` n'existent, et une seconde installation de la base ne
   change rien ;
2. **stream-deck** : `--stream-deck --deck-program=tiler --autostart`
   écrit la règle udev, le venv importe ce qu'importent les programmes du
   deck, l'unité du service du deck lance le point d'entrée de ce checkout
   et est activée, `systemctl --user start` la saute faute de deck dans
   une VM (inactive, `Result=exec-condition`, ou `success` selon la version
   de systemd, `ExecMainStartTimestampMonotonic=0`, et la ligne « no Stream
   Deck plugged in » du point d'entrée dans le journal de l'unité écrit
   depuis ce démarrage, si bien qu'un saut antérieur à l'ouverture de
   session ne compte pas ; la lecture est reprise quelques fois, le temps
   que journald écrive), l'extension reste ACTIVE, et une seconde exécution
   ne change rien, unité et réglages compris ;
3. **partial-uninstall** : `--uninstall --stream-deck` retire la règle,
   le venv, l'unité, son lien `graphical-session.target.wants` et ses
   réglages, `systemctl --user is-enabled` répond `not-found`, et
   l'extension reste liée, activée et ACTIVE ;
4. **uninstall** : `--uninstall` ne laisse ni lien, ni UUID dans
   `enabled-extensions`, ni règle, ni venv, ni unité, ni réglages.
   L'étape 3 a déjà retiré le service du deck : celle-ci vérifie seulement
   qu'une désinstallation complète le laisse parti ; aucune étape ne lance
   `--uninstall` sur un système qui porte encore l'unité ;
5. **reinstall** : la base de nouveau, puis un redémarrage : l'extension
   revient ACTIVE avec chaque indicateur monté, sans la règle ni le venv.

Une commande d'étape qui échoue, ou le premier contrôle tombé, nomme le
verdict (`FAILED(install-stream-deck)`, `FAILED(reinstall-no-udev)`…) :
chaque nom est unique, il dit donc quelle étape s'est arrêtée.

```
./long_test/install_erplibre_home.py                 # toute la matrice
./long_test/install_erplibre_home.py --only ubuntu:24.04,fedora:43
./long_test/install_erplibre_home.py --extras        # --with-extras sur 24.04
./long_test/install_erplibre_home.py --dry-run       # le plan, rien de créé
./long_test/install_erplibre_home.py --garder        # garder les VM
./long_test/install_erplibre_home.py --detruire      # défaire la dernière course
```

Une course réelle a besoin de `sudo` du début à la fin : chaque VM est
créée par `sudo deploy_qemu.py`, et détruite par `sudo -n virsh`. Soit
`virsh` et `deploy_qemu.py` sont permis sans mot de passe, soit une session
sudo reste ouverte toute la course. Une seule VM vit à la fois : quand une
VM survit à son défaire, même après `sudo -v`, la course s'arrête, marque
les systèmes restants `FAILED(previous-vm-still-up)` et rend 1 ;
`--detruire` la défait. `--garder` laisse chaque VM tourner, 4 Gio chacune :
l'associer à `--only`.

Le rapport porte une ligne par système, avec la version de GNOME attendue et
celle mesurée : c'est d'après ces lignes que la matrice du script se
corrige. Sur Arch et Tumbleweed, `UNSUPPORTED` veut dire que GNOME a dépassé
51, et c'est le signal attendu pour mettre `metadata.json` à jour. Le
journal de chaque système — sortie de l'installateur, journal utilisateur,
`gnome-extensions info` — est un `.log` dans le sous-dossier de la course.
Il prouve chaque contrôle : une ligne `── contrôle <nom> : réussi` ou
`ÉCHEC` par commande et par contrôle, suivie de chaque commande lancée, et,
sur un échec, de la réponse brute de cette commande.

## mobile_sync.py — l'app mobile se synchronise-t-elle avec Odoo 16, 17 et 18 ?

Pas de VM ici : des bases et des serveurs Odoo jetables, et le téléphone
quand il est branché. Le code de synchro de l'app (`mobile/erplibre_home_mobile`,
par son kit de test versionné `src/testing/syncTestKit.ts`) tourne sous Vitest
contre de vrais serveurs : tâches, conflits, opportunités, factures, activités,
messages, dates proposées, deux sociétés, fichiers, réseau coupé ou réponse
perdue, enregistrements supprimés, une note sur trois serveurs. Chaque scénario
vérifie le résultat dans Odoo, et un proxy entre l'app et chaque serveur trace
ce qui passe sur le fil.

```
./long_test/mobile_sync.py                     # 16, 17 et 18
./long_test/mobile_sync.py --versions 18       # une seule version
./long_test/mobile_sync.py --filtre conflit    # les tests dont le nom correspond
./long_test/mobile_sync.py --dry-run           # le plan, rien de créé
./long_test/mobile_sync.py --appareil          # aussi sur le téléphone branché
./long_test/mobile_sync.py --garder            # garder bases et serveurs
./long_test/mobile_sync.py --detruire          # supprimer gabarits et cache
```

Elle vérifie d'abord le dépôt mobile — absent, sans `node_modules`, Node
antérieur à 22, ou kit de test d'une autre API — et dit quoi faire. Le premier
passage construit un gabarit par version (quelques minutes) ; les suivants le
copient, et la suite entière prend une trentaine de secondes. Un rapport sans
test, ou sans test pour une version, échoue : un chemin mal résolu ne doit pas
passer pour une course verte.

Le clavardage n'est testé que sur la 18, où Discuss et le bus websocket
existent. Le gabarit de la 18 ajoute ce dont ces scénarios ont besoin : le
module `erplibre_mobile_chat` des addons d'ERPLibre, un second utilisateur,
`chat_user`, et un canal de groupe « ms chat » où lui et l'utilisateur de
l'app se parlent, sans message non lu pour chat_user au départ. `chat.test.ts`
couvre le chargement et ses compteurs, un envoi qui arrive une fois chez
chat_user, une réponse perdue avec le module et avec le seul marqueur, la file
hors ligne qui garde son ordre, la pagination de l'historique et la marque de
lecture vue sur le serveur. `chatRealtime.test.ts` couvre le bus qui livre un
message et la frappe de chat_user, les compteurs de la première connexion, et
un socket coupé qui livre à la reconnexion. `chatManage.test.ts` couvre la
gestion des conversations contre le vrai serveur, chaque résultat relu sur
lui : un message direct créé une fois et réutilisé, un groupe créé hors ligne
puis l'app relancée, la réponse de la création perdue (un seul groupe, ses
messages une fois et dans l'ordre, avec le dédoublonnage par uuid du module
et sans lui, par empreinte), les groupes d'accès d'un nouveau canal, une
adhésion, une invitation, le renommage et la description, un départ avec un
message encore en file, un message direct masqué qui réapparaît quand l'autre
utilisateur écrit, une sourdine et la sourdine globale (celle mise en file
au-delà de sa fin la lève), et un retrait par l'administrateur annoncé sur le
bus du retiré, qu'un non-administrateur se voit refuser. Le scénario d'un
groupe que chat_user crée et remplit tourne sous `mc_user`, l'utilisateur à
deux sociétés, qu'aucune conversation d'un autre fichier n'implique : tout
`/mail/data` de son proxy est le sien et les messages suivants doivent
arriver par le bus sans rechargement. Chaque gabarit, ceux de la 16, de la
17 et de la 18 pareillement, crée d'avance les réglages de chaque
utilisateur interne (deux premières requêtes simultanées les créeraient
toutes deux et buteraient sur l'unicité de `res.users.settings`), et le
module de celui de la 18 est le 1.4, qui dédoublonne les créations et les
téléversements, garde les modifications, cherche dans les canaux dont on est
membre, pose un favori au lieu de le basculer et dédoublonne les envois sur
tout enregistrement. `--appareil` ajoute l'écran
« clavardage » et un groupe créé depuis le téléphone. Pour ne lancer que
ceux-là :

```
./long_test/mobile_sync.py --versions 18 --filtre chat
./long_test/mobile_sync.py --versions 18 --filtre chat --appareil
```

`chatAttachments.test.ts` couvre les fichiers d'un message contre le vrai
serveur, chaque cas relu sur lui. Là où il dit « sur les deux routes », il
tourne une fois sur la route du module et une fois en l'ignorant, sur celle
d'Odoo. Une réponse de téléversement perdue laisse une seule pièce jointe
dans un seul message (la route du module rend la première pour le même
`client_uuid`, celle d'Odoo est cherchée et réutilisée, y compris une photo
qu'elle a stockée redimensionnée à une autre taille) ; une réponse d'envoi
perdue avec deux fichiers poste un message qui les porte tous deux ; un
fichier vocal arrive en `audio/mpeg` avec ses métadonnées vocales ; et une
session expirée répond 404 une fois, puis le téléversement passe. La route du
module garde l'original d'une photo (même somme de contrôle que le fichier
source) là où celle d'Odoo le réduit à 1920 px. Une limite abaissée avant que
l'app la lise refuse le fichier à la mise en place, et abaissée après la mise
en file le refuse par le 413 du serveur : le texte est posté sans lui et
l'utilisateur en est averti une fois. Sur un réseau mobile rien ne part avant
le retour du Wi-Fi. L'image d'un interlocuteur coûte une requête d'aperçu de
512 px au plus et télécharge son original seulement à l'ouverture, et un
historique de 20 pièces jointes ne fait aucune requête de fichier. Les cas qui
abaissent la limite de téléversement du serveur bornent chaque requête du
serveur partagé : ils vivent dans des fichiers `*.serial.test.ts`, lancés dans
une seconde passe, un fichier à la fois, après la passe parallèle ; les deux
rapports donnent un seul bilan. `--appareil` ajoute l'écran « pièces jointes
du clavardage » : un fichier envoyé depuis la zone de saisie arrive une fois
sur le serveur avec sa somme de contrôle d'origine, les boutons de pièce
jointe et de micro sont au-dessus de la barre de navigation, un vrai appui
enregistre un message vocal qui arrive en MP3, la photo d'un interlocuteur
montre son aperçu et s'ouvre dans la visionneuse, et son message vocal se lit.
La caméra et les sélecteurs du système sont des écrans du fabricant et restent
hors de l'exécution. L'exécution sur appareil relève aussi la `lastUpdateTime` de
l'app de l'utilisateur avant et après, et échoue si elle a changé ou ne se lit
pas. Les contrôles du banc (les versions d'API du kit et du crochet d'appareil,
la liste des scénarios) se lancent avec les tests unitaires de la plateforme ;
le paquet `test` de la bibliothèque standard masque `test/`, d'où la
découverte :

```
.venv.erplibre/bin/python -m unittest discover -s test -p test_mobile_sync_harness.py
```

`chatActions.test.ts` couvre les actions sur un message contre le vrai serveur,
chaque résultat relu sur lui. Une réaction dont la réponse est perdue laisse
une ligne après la reprise ; une réaction ajoutée puis retirée hors ligne
n'envoie aucune requête ; et la réaction et la modification de chat_user
arrivent à l'app par le bus sans rechargement. Là où il dit « sur les deux
routes », la modification tourne une fois sur la route gardée du module et une
fois en l'ignorant, sur celle d'Odoo : la modification d'un message à deux
fichiers change le texte et garde les deux fichiers ; une modification dont la
réponse est perdue, son corps ouvert par une mention qu'Odoo stocke enveloppée,
compte comme faite à sa reprise, et une correction faite entre-temps la suit
sans avis ; une modification tardive, faite après que chat_user a modifié ou
supprimé le message dans le navigateur, est refusée, le texte de l'app gardé
pour « Reprendre » et le corps du serveur intact ; une suppression vide le
corps et retire les fichiers, masquée dans l'app et pour chat_user ; une
réponse garde son parent sur le serveur, une réponse dont chat_user supprime le
parent entre-temps est postée dessus et citée comme supprimée, et une réponse à
un message d'une autre conversation est postée comme un message simple.
`chatWriting.test.ts` couvre ce que l'app écrit : la mention de chat_user dans
un canal lui donne une notification (seul un partenaire qui a un courriel et
des notifications par boîte de réception est averti d'une mention de canal, le
fichier lui donne donc les deux le temps de sa course), `@everyone` met chaque
membre dans `partner_ids`, `#canal` est stocké comme le lien de canal d'Odoo,
et un corps qui commence par une mention est stocké dans un `<span>`.
L'aller-retour prend chaque cas des références du composeur, l'envoie, et fait
réenregistrer par le navigateur de chat_user : le corps reste stocké tel qu'il
était, au span « modifié » près.

Les références sont produites par le formateur d'Odoo lui-même, non écrites à
la main. `long_test/mobile_sync_composer.py` ouvre une session sur un Odoo 18
dans un Chromium sans écran, charge Discuss, fait tourner
`prettifyMessageContent` de `@mail/utils/common/format` sur chaque cas de
`composer-cases.json` (avec les mentions que retient `getMentionsFromText`) et
écrit `composer-golden.json` à côté, dans `src/__tests__/fixtures/` du dépôt
mobile. Il refuse un serveur qui n'est pas un Odoo 18 ; la fonction tourne dans
la page, tout Odoo 18 donne donc les mêmes corps.

```
./long_test/mobile_sync_composer.py http://127.0.0.1:8069 admin admin --base ma_base
./long_test/mobile_sync.py --versions 18 --filtre chat
```

Le scénario « actions du clavardage » de `--appareil` tourne sur la 18, sur le
téléphone : un appui long de 700 ms ouvre le menu du message et le clic qui le
termine ne choisit rien, la sélection native du texte d'une bulle cède la place
au menu, un appui sur une suggestion garde le clavier ouvert avec le champ de
saisie visible, une citation défile jusqu'à son original, la marque
« (modifié) » suit le texte, et la zone de saisie reste à 16 px au plus
au-dessus de la barre de navigation dans chaque scénario du clavardage, clavier
ouvert ou non.

`chatFinding.test.ts` couvre la recherche contre le vrai serveur, sous
l'utilisateur de l'app. Là où il est dit « le module et le module ignoré »,
la recherche passe par la route du module et par le repli `search_read`. Une
recherche serveur ne voit que les canaux dont l'utilisateur est membre, jamais
un canal public non rejoint ni la conversation privée de chat_user avec un
tiers, et ne marque rien lu ; un terme qui contient `&` ou `%` trouve les mêmes
messages par le module, par le repli et par la recherche du téléphone ; ouvrir
un résultat plus ancien que l'historique chargé ne charge les pages plus
anciennes que par `around` et ne marque rien lu ; une épingle à réponse
perdue laisse `pinned_at` posé et une seule notice d'épingle ; l'épingle de
chat_user arrive dans la liste des épinglés ; un favori à réponse perdue n'est
posé qu'une fois après la reprise, avec le module et sans lui ; et un favori
posé dans le navigateur de l'utilisateur depuis le chargement, puis posé sur le
téléphone, reste posé.

`chatInbox.test.ts` couvre la boîte de réception contre le vrai serveur, sous
`inbox_user`, un utilisateur que le gabarit crée pour cela : interne,
utilisateur de projet, avec `notification_type` écrit explicitement à `inbox`
(le groupe seul laisse un nouvel utilisateur sur le courriel), membre de
« ms chat », et avec une adresse courriel, car une mention de canal ne notifie
qu'un partenaire qui en a une. Ses tests s'exécutent dans l'ordre. Une mention,
un commentaire sur une tâche suivie et une assignation remplissent les trois
genres d'élément ; une recherche serveur du mot mentionné laisse la mention non
lue ; un élément marqué lu est `is_read` sur le serveur ; « tout marquer lu »
touché hors ligne pendant que chat_user mentionne de nouveau laisse la mention
plus récente non lue ; une réponse en note avec une photo est une seule note
qui porte la photo et n'envoie aucun courriel, une réponse en message est un
seul commentaire et un courriel à l'abonné notifié par courriel (compté en
`mail.mail`), et une réponse dont la réponse du téléversement, puis celle de
l'envoi, sont perdues poste un seul message avec une seule pièce jointe, avec
le module et sans lui ; deux commentaires et une mention arrivent dans la boîte
ouverte par le bus, sans lire de page de conversation ; et un utilisateur
notifié par courriel apprend pourquoi sa boîte est vide, passe à la boîte, et le
serveur lit `inbox`. L'abonné notifié par courriel est un utilisateur que le
fichier crée, car un autre fichier change la préférence de chat_user pour toute
sa course.

Le SMTP des serveurs d'essai pointe sur un port local fermé de la machine.
Odoo envoie les courriels de notification juste après la validation, et l'hôte
peut faire tourner un serveur de courrier : sans cela, un courriel d'essai
quitterait la machine, et un courriel envoyé est supprimé, donc aucun
`mail.mail` à compter. Avec cela, le courriel reste dans `mail.mail` à l'état
`exception`, compté et jamais livré.

Le scénario « recherche et boîte du clavardage » de `--appareil` tourne sur la
18, sur le téléphone : un message est envoyé, modifié et supprimé, puis l'index
de recherche passe une fois le contrôle d'intégrité de SQLite (ou le téléphone
utilise le repli LIKE) ; une recherche depuis la liste ouvre la conversation au
résultat, en surbrillance ; un appui long puis Épingler, confirmé dans la
boîte de dialogue native, pose `pinned_at` sur le serveur ; Favori le met en
favori ; la boîte d'un utilisateur notifié par courriel montre l'explication, le
bouton écrit `inbox`, une mention de chat_user apparaît et « Marquer comme lu »
la lit ; une réponse sur une tâche avec une photo l'envoie ; dans un groupe, la
seconde bulle d'une suite de messages d'un même auteur ne montre ni nom ni
avatar, alors que la première montre le nom et l'avatar de l'auteur (un contrôle
de l'auteur sur les bulles affichées) ; et un vieux résultat, suivi de plus de
messages non lus que le fil n'en rend d'abord, ouvre la conversation sur lui
sans que le dernier message vu de l'utilisateur ne bouge sur le serveur.

`--appareil` joue ses écrans sur le téléphone, contre les mêmes serveurs :
le sélecteur de cibles, le bandeau d'une date changée sur le serveur, la saisie
pendant un pull, la note datée créée depuis le calendrier et, sur la 18
seulement, le clavardage (la tuile ouvre la liste en 2 s au plus, et la zone
de saisie de « ms chat » en 2 s aussi, trois messages qui y sont tapés de
suite arrivent chacun une fois sur le serveur, le clavier restant ouvert d'un
envoi à l'autre, la réponse de chat_user
s'affiche par le websocket natif) et un groupe créé depuis le téléphone avec
chat_user, qui existe une fois sur le serveur sous son nom, dont la fiche
nomme chat_user parmi les membres et où les messages passent dans les deux
sens. Ils tournent
dans une app à part, `ca.erplibre.home.synctest`, construite par `-PsyncTest`
depuis un paquet de développement et effacée à chaque version ; l'app de
l'utilisateur n'est jamais touchée. Le téléphone doit être déverrouillé, le
débogage USB autorisé. Un échec garde une capture d'écran dans le répertoire
de la course, `cache/mobile_sync/runs/`.

Une course gardée par `--garder` est arrêtée et balayée par la course
suivante, ou par `--detruire`. Codes de sortie : 0 tout vert, 1 des tests
échouent, 2 un prérequis manque, 3 l'infrastructure a échoué.

### Les tests du push du clavardage — notifications app fermée

La course démarre son propre `ntfy serve`, sur `127.0.0.1` et un port libre,
avec un `server.yml`, un fichier d'accès et un cache temporaires sous le
répertoire de la course ; elle ne touche jamais au ntfy de la machine (chaque
appel `ntfy` porte `--config`, placé avant la sous-commande pour `user` et
`token`). L'accès du téléphone se crée comme le menu `TODO › Déployer ›
Préparer ntfy pour ERPLibre mobile` le crée : anonyme en écriture seule sur
`up*`, un utilisateur en lecture seule sur son préfixe, un jeton. Le ntfy
s'arrête avec la course (gardé avec les serveurs par `--garder`).

`--filtre push` joue les tests dont le nom correspond : les quatre formes de
push déchiffrées depuis le cache de ntfy, une conversation en sourdine qui n'est
pas poussée, un jeton qui ne lit que son préfixe, le désenregistrement quand un
compte est retiré, le passage à un nouveau sujet quand un nouveau lien arrive
et, seul dans un fichier en série, les clés VAPID retirées au sort, que le
chargement suivant guérit.

Avec `--appareil`, le scénario des notifications tourne sur le téléphone, sur
Odoo 18, contre ce ntfy renvoyé au téléphone par `adb reverse` : au niveau 1
l'app est connectée et montre une notification permanente ; un message d'un
autre utilisateur sonne en quelques secondes sous l'étiquette de sa
conversation, son texte en clair et, pour l'écran verrouillé, seulement
« Nouveau message — <serveur> » ou aucune version d'écran verrouillé, selon le
réglage d'Android ; le processus tué (`am crash`, car SELinux refuse
`run-as kill` sur Android 11), le service revient et le message suivant
s'empile dans la même notification ; la toucher ouvre la conversation ; au
premier plan rien ne s'affiche ; avec « Jamais affiché » le texte n'est pas dans
la notification ; le ntfy retiré, le sommaire direct d'Odoo dit « 2 nouveaux
messages » et rien n'est marqué lu sur le serveur. Le scénario ne verrouille
jamais le téléphone : la forme de l'écran verrouillé se lit dans
`dumpsys notification --noredact`. Il remet en état ce qu'il change : le
réglage `stay_on_while_plugged_in`, l'entrée d'optimisation de la batterie de
l'app de test et les ports `adb reverse`.

## Partir d'un hôte qu'on possède déjà

Les trois scripts acceptent `--hote`. Créer une VM de tête pour héberger un
hyperviseur qu'on a sous la main coûte cinq minutes *et* un étage
d'imbrication — donc de la lenteur, puisque c'est justement elle qu'on mesure.

```
./long_test/deep_proxmox.py --hote root@10.0.0.5      # un Proxmox existant
./long_test/deep_qemu.py --hote erplibre@10.0.0.7     # un hôte libvirt existant
```

Trois choses en découlent, et elles ne sont pas décoratives :

* le plan se dimensionne sur la **racine**, lue par ssh — le dimensionner sur
  la machine locale quand les étages vivent ailleurs annoncerait des étages qui
  ne tiennent pas ;
* les délais comptent la profondeur **absolue** : un enfant de niveau 1 posé
  dans une racine déjà au troisième étage est en réalité au quatrième ;
* la racine n'est **jamais** un étage atteint, et **jamais** détruite. Un hôte
  emprunté n'a pas d'UUID libvirt local, donc `--detruire` refuse de se rabattre
  sur son nom — `virsh undefine --remove-all-storage` efface un disque pour de
  bon.

Le menu propose l'hôte déjà retenu sans le rechercher, et défait chaque pile
séparément : elles partagent le dossier des rapports, mais chacune ne connaît
que les siens.
