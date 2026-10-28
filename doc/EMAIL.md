
# Mail client

A mail client built into the TODO CLI: several accounts, IMAP + SMTP, and a
local cache — so you can read and answer email without leaving
`./script/todo/todo.py`.

Every `Mail > ...` path below is shorthand for
`TODO > [3] Assistant > [2] Mail - Read and send email > ...` — the full path
is spelled out once, in "Adding an account".

## Prerequisites

Four Python packages, already listed in `requirement/erplibre_require-ments.txt`
(the `.venv.erplibre` environment, not an Odoo venv):

- `cryptography` — seals the local cache in `encrypted` and `ephemeral` mode.
- `keyring` — the system keyring, one of the two places a password can live.
- `pykeepass` — the KDBX vault, the other place, and the one the client tries
  first.
- `textual` — the terminal UI itself. Without it, "Open the mail client
  (TUI)" prints a message and does nothing; the rest of the menu (accounts,
  sync, cache) still works.

Install them with:

```bash
.venv.erplibre/bin/pip install -r requirement/erplibre_require-ments.txt
```

### App passwords for Gmail and iCloud, and why Microsoft is out

The client speaks plain IMAP/SMTP login only — no OAuth yet (that is the
next phase). Gmail and iCloud have closed that door to the account's real
password, so both presets require an **app password** instead:

| Provider | Where to generate it |
|---|---|
| Gmail | [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) — 16 characters, spaces are accepted. Two-step verification must be on, otherwise the page is empty. |
| iCloud | [account.apple.com](https://account.apple.com) — under "Sign-In and Security". Two-factor authentication must be on. |

**A Microsoft account needs OAuth, not a password.** Microsoft removed
basic authentication from IMAP — for Microsoft 365 tenants first, then for
Outlook.com — and an app password is basic authentication, so it is refused
too. Nobody can turn it back on. Add such an account with a refresh token
instead, as "Authenticating with OAuth" below describes; the client says so
where it asks for the secret, rather than letting a refusal look like a
typo.

Use the generated password when account setup asks for one — never the
account's normal password. The "Standard server" preset (generic IMAP/SMTP)
does not need one. The client prints these same notes itself — when it asks
for the password, and again when a refusal sends it back to asking. They
live in `script/todo/todo_i18n.py` under the `mail_preset_note_*` keys, and
this table follows them.

## Adding an account

Menu path: `TODO > [3] Assistant > [2] Mail - Read and send email > [2]
Accounts > [2] Add an account`.

The first time only: if no vault is configured yet — `kdbx.path` is empty
in the shipped config — the menu asks before anything else whether to
create a new `.kdbx` or to point at one already on disk. Creating one asks
for its path (default `private/erplibre.kdbx`), then the vault password,
typed twice; two different entries cancel the account creation, and so does
answering `[0]`. Pointing at an existing vault asks only for its path. Once
the path is recorded, the question never comes back.

Then the prompts, in order:

1. **Short account name** — becomes both the folder name under
   `~/.erplibre/mail/` and the vault reference, so it cannot contain `/` or
   start with a dot.
2. **Email address**.
3. **Display name** (optional) — shown in the `From:` header as
   `Display Name <email>`.
4. **Provider** — a number from the printed list: Gmail, Outlook.com
   (personal), Microsoft 365 (organisation), iCloud, or "Standard server"
   (generic IMAP/SMTP). The two Microsoft entries share an IMAP host and
   not an SMTP one, so picking the wrong one reads mail and fails to send.
5. If you picked "Standard server", the **IMAP host** and **SMTP host** are
   asked next; the other presets fill these in for you.
6. The preset's note is printed here — what the provider expects, and what
   it no longer accepts.
7. **Authentication**, asked only where there is a choice: Gmail takes an
   app password or OAuth, the Microsoft presets take OAuth only, iCloud an
   app password only.
8. **The secret** — an app password or a refresh token, typed hidden
   (`getpass`), then stored in the vault — never written to
   `accounts.json`.

Where the password goes: at the password step, the client hands off to the
CLI's shared **KDBX manager** — the same one already used for the OpenAI
key and Odoo credentials. It reads `kdbx.path` / `kdbx.password` from the
TODO config (`script/todo/todo.json`, overridable in
`private/todo/todo_override.json` / `private/todo/todo_override_private.json`).
If `kdbx.path` isn't set yet, the menu asks for it in text, as described
above — no display needed, so it works over SSH and in a container. `[1]`
creates a new `.kdbx` at the path you give (`private/.gitignore` already
ignores `*.kdbx`), `[2]` adopts one already on disk, `[0]` cancels and
writes nothing. The path is recorded in
`private/todo/todo_override_private.json`, the only one of those three
files git ignores, so the question is asked once; the TUI asks the same one
with `n`, before its own account form. A vault the menu has just created is
opened again to write that first secret, so its master password is asked
once more. Setting `kdbx.path` (and `kdbx.password`, to skip the vault
password prompt) beforehand only skips those questions — a shortcut, not a
prerequisite. The system keyring is only ever used for an account whose
`secret_ref` already points at one — the menu itself always writes new
accounts into the KDBX vault.

`accounts.json` (at `~/.erplibre/mail/accounts.json`) only ever holds a
`secret_ref` such as `kdbx:ERPLibre/Mail/perso` — a pointer, never the
secret. It is safe to read, edit by hand, or check into a private backup.

## The three cache modes

Every account keeps a local cache — a small SQLite database plus one file
per downloaded message — so the inbox stays readable offline. Three modes
control what that cache leaves on disk:

| Mode | What's on disk | Encryption key |
|---|---|---|
| `clear` (default) | `~/.erplibre/mail/<account>/cache.db` and `.eml` files, readable as plain text | none |
| `encrypted` | same location, but sender, recipients, subject, snippet, message-id and message bodies are sealed with AES-256-GCM from the mode change onward (see below) | generated once, stored in the vault next to the password (`.../cache-key`) |
| `ephemeral` | under `/dev/shm/erplibre-mail-<pid>/<account>/` (or the system temp dir if `/dev/shm` isn't writable), sealed the same way as `encrypted` | generated fresh in RAM at every run, never written anywhere, and the whole directory is removed when the session closes |

Even in `encrypted` and `ephemeral` mode, the technical fields the SQL
needs to sort and filter stay plain: UID, folder name, date, flags and
size, along with the Message-ID fingerprints that thread a conversation —
fingerprints salted with the cache key, so they link two messages without
naming either. Sealing covers what identifies people: sender, recipients,
subject, snippet, the Message-ID itself, the message body, and the queued
outgoing messages down to the reason a send failed. The client builds no
full-text index for a sealed cache, so the search there decrypts row by
row (see Search).

**Switching modes does not reach back over what is already written.** A
mode governs the writes that follow it. Once an account moves to
`encrypted`, the rows written in `clear` keep their plain envelopes, and
the `.eml` files already downloaded stay on disk — no longer read, not
removed either. The full-text index is the exception: it is dropped when
the account leaves `clear`, because it holds in the open the very subjects
and snippets the sealed rows protect, and it is rebuilt from the cache if
the account comes back. To start over sealed, delete the account's cache
directory (`~/.erplibre/mail/<account>/`), then sync again — everything
comes back under the key.

Set the **general default** at `Mail > [4] Cache > [1] Default cache mode`;
it is the `mail_cache_mode` preference (default `clear`). **Override it per
account** at `Mail > [4] Cache > [2] Cache mode of one account` — this
writes the account's `cache_mode` field in `accounts.json`; leaving it at
`null` there means "inherit the general default."

`Mail > [4] Cache > [3] Cache size and purge` lists every account's
effective mode and disk usage, and empties one account's messages, folders
and downloaded files (after confirmation) — the next sync rebuilds them
from scratch. The full-text index is emptied with them, so nothing keeps
answering for messages that are gone. The `cache.db` file itself stays, and
with it whatever waits in the outbox.

## The TUI

`Mail > [1] Open the mail client (TUI)` opens a three-pane screen: an
account/folder tree on the left, the message list in the middle, and a
preview pane on the right, with a status line at the bottom.

| Key | Action |
|---|---|
| `↑` `↓` `Tab` | move within a pane / move focus between panes (Textual defaults) |
| `h` | open the help window: the main screen's shortcuts plus a few notes — not the keys of the compose, folder and statistics windows, which each have their own; closed with `Escape` |
| `z` | toggle full-screen preview (hides the folder tree and the message list) |
| `Escape` | leave full-screen |
| `v` | cycle the layout: columns, split, stacked |
| `+` / `-` | grow / shrink the pane that has focus |
| `0` | back to the default pane sizes |
| `r` | sync the account of the currently selected folder (all its folders) |
| `Shift+R` | sync every account |
| `/` | open the search field: it searches the whole cache of the open folder — not just the messages on screen — over subject/from/to/snippet (see "Search") |
| `Shift+S` | ask the **server** the same search, for the open folder (see "Search") |
| `g` | cycle the message list: flat, by thread, unread only (see "List views") |
| `x` | select / unselect the message under the cursor (see "Acting on several") |
| `s` / `u` | mark the selected message seen / unseen |
| `*` | flag / unflag the selected message — the star other clients show |
| `Shift+M` | mark the whole open folder read (asks first) |
| `d` | move the selected message to the account's trash folder |
| `m` | file the selected message into a folder you pick |
| `D` | empty the account's trash folder, permanently |
| `p` | widen the search: folder, account, every account |
| `c` | compose a new message |
| `a` / `Shift+A` | reply / reply all |
| `f` | forward |
| `w` | save an attachment to `~/Téléchargements` (created if missing) |
| `o` | open the outbox: what is waiting to leave (see "The outbox") |
| `e` | open the incoming mail rules of the current account (see "Incoming mail rules") |
| `Shift+F` | open the folder screen: create, rename, delete (see "Managing folders") |
| `i` | open the statistics screen (see "Statistics") |
| `Shift+I` | open the statistics report settings of the current account (see "The statistics report") |
| `n` | add an account without leaving the client |
| `l` | show the tail of `~/.erplibre/mail.log` and this session's sync errors |
| `q` | quit |

This table is written by hand and can fall behind the code; the `h` window
cannot. It builds its list from the application's own key bindings every time
it opens, so it is the reference if the two ever disagree.

The bars between the panes can also be dragged with the mouse, and pane sizes
are remembered per layout.

The footer's key hints, like the help window, follow the CLI's chosen
language, as do the account tree, the message list and the preview text.

## Writing a message

`c` opens the compose form: `To`, `Cc`, `Subject`, an `Attachments` field
(semicolon-separated file paths — a comma is legal in a filename, so only
`;` splits entries; the `Browse…` button beside the field opens the CLI
file browser, which starts from the folder of the last path already typed
and appends the file you pick), and a multi-line body. `Ctrl+E` sends the
body out to `$EDITOR` (or `nano` if unset) and reads it back; if the
editor is missing or exits with an error, the body you had is kept
untouched. `Ctrl+S` (or the Send button) delivers the message; `Escape`
discards the draft — there is no save-as-draft.

`a` (reply) and `Shift+A` (reply all) prefill `To`/`Cc`/`Subject`/
`In-Reply-To`/`References` and quote the original message in the body. `f`
(forward) prefills the `Fwd:` subject and **attaches the original message**
automatically, as a `message/rfc822` attachment; the body itself starts
empty — write your own note above the attached original.

Reply, reply-all and forward all need the original message's body
available — from the cache, or fetched live if the account is online; with
neither, you get "No message selected." / "No message to forward."

A message written while the account is offline is queued instead of sent:
it leaves at the next sync, and the status line says "offline: message
queued, it will leave when the network is back" (see "The outbox"). Once
sent, a copy is filed into the account's Sent folder over IMAP; if that
filing step fails, the status line says so, but the message has already
left — it is not resent.

The send runs in the background: the Send button greys out and the form
stays open until the server has answered, while the rest of the client
stays responsive. A reply (`a` or `Shift+A`) sent while the account is online also
marks the original `\Answered`, in the cache and on the server, as other
clients do. A reply that waits in the outbox does not, nor does a forward.

## Synchronization

A sync pass is incremental: only UIDs above the last known one are
fetched, message bodies are never downloaded during a pass (only headers),
and bodies are fetched on demand when you open a message. That fetch runs
in a background thread: the preview shows the headers and *Downloading the
body…* until it lands, the client stays responsive, and moving the cursor
away before it arrives discards it rather than painting it over the message
you moved to. Flags (read/unread, etc.) of already-known messages are
re-checked on every pass, so a message read elsewhere shows up correctly
here too.

Sync happens:

- **At launch** — opening the TUI kicks off one background sync of every
  account.
- **On demand** — `r` (current account) / `Shift+R` (all accounts) inside
  the TUI, or `Mail > [3] Synchronise now` from the CLI menu (prints a
  per-account summary to the terminal).
- **Automatically, every `mail_refresh_sec` seconds** (default 300 = 5
  minutes; 0 disables it) — **but only while the TUI is open**. Close it
  and the timer goes with it; nothing syncs in the background afterward.

A link that dies is replaced rather than carried. Each IMAP read is
bounded by `mail_timeout_sec` seconds (default 30); when one is exceeded,
Python marks that socket for good and every later read fails instantly
with `cannot read from timed out object`, without asking the server
anything. One slow `LIST` — which a large mailbox at a big provider does
produce — used to condemn the account for the rest of the session, every
pass failing in milliseconds on a link already dead, with restarting the
client as the only cure and nothing saying so. Every exchange now reopens
the link once and runs again — the sync pass as much as filing, emptying
the trash, marking a folder read, a server-side search or the copy dropped
in *Sent*. Raising `mail_timeout_sec` avoids the cut rather than repairing
it; a server that answers *no* is not a dead link and is never retried.

If the server reports a changed `UIDVALIDITY` for a folder (its UIDs no
longer mean what they used to — typically after a server-side migration),
that folder's cache is purged and resynced from scratch automatically. The
pass says which folders it did that to: the TUI on its status line at the
end of the pass, `Mail > [3] Synchronise now` under the account name.

### Servers that file by label

Some providers hold a message only once and make their folders *views* of
it: the same message answers in the inbox and in the all-mail folder, under
a UID of each folder's own, and a flag set under one label is read under
the other. Syncing every folder therefore brings the same message back once
per label — three views of a 30 000-message mailbox make 90 000 cache rows
for 30 000 messages.

The pass skips the views that only restate another folder, those the server
marks `\Flagged` (starred) or `\Important`: their messages are all in the
`\All` folder too, so nothing becomes unreachable. `\All` itself is always
synced — archiving a message removes its inbox label, and it then lives
only there. Skipping happens **only** when the server announces the
`X-GM-EXT-1` capability; elsewhere `\All` is an ordinary archive holding
distinct messages, and a folder may carry `\Flagged` and hold messages
that are nowhere else.

A folder that is not synced is not in the cache, so it does not appear in
the folder tree. What remains is the inbox/all-mail overlap, which no IMAP
rule lets a client collapse: only the `Message-ID` ties the two together.

## Where the files live

| Path | Contents |
|---|---|
| `~/.erplibre/mail/accounts.json` | account list — servers, presets, cache mode, and a `secret_ref` pointer; never a password (mode 0600) |
| `~/.erplibre/mail/<account>/cache.db` | that account's SQLite cache (mode 0600, parent directory 0700) |
| `~/.erplibre/mail/<account>/<folder>/<uid>.eml` (or `.eml.enc` when sealed) | one file per downloaded message body |
| `/dev/shm/erplibre-mail-<pid>/<account>/` | an `ephemeral` account's cache while the process is alive; removed when it exits (a sweep at every startup also clears directories left behind by a killed process) |
| `~/.erplibre/mail/.rules/<account>/rules.json` | that account's incoming mail rules and send caps, **in clear text** even with an encrypted cache (mode 0600; see "Incoming mail rules") |
| `~/.erplibre/mail/.rules/<account>/state.json`, `lock` | where the rules engine stopped in the inbox, and the lock that keeps two passes from running at once |
| `~/.erplibre/mail/.rules/<account>/media/` | the copies of the images a reply carries (directory 0700, files 0600) |

## Troubleshooting

Error messages raised by the mail package itself (`secrets.py`,
`store.py`, `crypto.py`, `accounts.py`, `smtp_send.py`,
`imap_transport.py`, `imap_sync.py`) go through the CLI's translation
layer, the same as the menu prompts and TUI labels: they follow the
language the CLI runs in.

**"Connection failed: ..." when adding or testing an account.**
`Mail > [2] Accounts > [5] Test an account connection` prints the server's
exact error and then asks for the password again — up to 3 attempts. The
password in the vault is only overwritten *after* a successful connection,
so a typo never destroys a working password. If the account is Gmail or
iCloud, check first that you used an app password (see "Prerequisites"
above), not the account's normal one; if it is a Microsoft account, no
password will do — see the same section. Opening the TUI
itself does not retry automatically: an account with a rejected password
gets a ⚠ marker; if it had synced successfully before, its already-cached
folders stay visible and readable, they just stop refreshing — only a
brand-new account (nothing synced yet) shows no folders at all. Either
way, go run "Test an account connection" to fix it.

**"the kdbx file could not be opened" when adding an account.**
A vault is designated by then — adding an account begins by making sure of
it — but it would not open: the vault password was refused (three tries,
then the client gives up; an empty entry gives up at once), the
`kdbx.password` in the config is wrong, `pykeepass` isn't installed, or
there is no terminal to type the password on. Type it again, or set
`kdbx.password` for an unattended run. Two other refusals belong to that
first question: "This file does not exist:" (choice `[2]`, nothing at that
path) and "Passwords do not match." (choice `[1]`, the two entries differ);
both cancel the account creation without writing anything. The same message
outside account creation — sync, connection test, opening the client —
means `kdbx.path` is empty: those entries go straight to the shared KDBX
manager, which then opens a graphical file picker, and cancelling it, or
running with no display, leaves the vault closed.

**"the system keyring would store the password in plaintext (backend
...)".**
`keyring`'s active backend isn't one of the ones known to actually
encrypt — this happens over SSH, in a container, or on a machine with no
desktop session, where `keyring` silently falls back to a plaintext file
store. The client refuses rather than pretend that's safe. Use the KDBX
vault instead (see above), or run somewhere a real keyring is unlocked.

**"Install textual for the mail client (pip)."**
`textual` isn't installed. `Mail > [1] Open the mail client (TUI)` just
prints this and returns; every other menu entry (accounts, sync, cache)
still works without it.

**The folder cache says it changed (`UIDVALIDITY`).**
Nothing to do — the client purges and resyncs that folder by itself the
next time it syncs. Expect the message list to empty briefly and refill.

**"unreadable cache, purge it and resynchronise: ...".**
The account's `cache.db` is corrupt. `Mail > [4] Cache > [3] Cache size and
purge` may itself fail to open the same broken file; if so, delete the
account's cache directory by hand and resync:

```bash
rm -rf ~/.erplibre/mail/<account>/
```

## Testing against a real server

Almost every mail test uses an in-memory double. A double only produces what
its author imagined, which is how three protocol bugs reached users. So there
is also a **sandbox**: a real IMAP server (Twisted) and a real SMTP server
(aiosmtpd) that a test starts on an ephemeral loopback port, talks to over
real TCP, and kills when it finishes — pass or fail.

The point is not conformance. A well-behaved server proves little; this one
can **misbehave on purpose**. A test declares the exact bytes a message is
made of — raw 8-bit header bytes, an `unknown-8bit` charset — and can drop the
connection or refuse a command mid-sync. Adding a new hostile behaviour is a
small subclass in `test/mail_sandbox.py`, not a new server.

These tests run with the rest of the suite: `twisted` and `aiosmtpd` sit in
`requirement/erplibre_require-ments.txt`, the file "Prerequisites" installs.
Where those two packages are missing, the whole file skips visibly. To run
this file alone:

```bash
.venv.erplibre/bin/python -m unittest discover -s test \
    -p test_mail_live_server.py -v
```

What it does **not** cover, and will not pretend to:

- **`SPECIAL-USE`** — Twisted announces only `IMAP4REV1 NAMESPACE IDLE`. The
  bug where a sent message was filed under a guessed folder name instead of
  the one the server announced is therefore out of reach. Implementing the
  extension in the sandbox would only test our own assumption about it, which
  is the exact failure this sandbox exists to escape.
- **No provider quirk** — Gmail's label-as-folder model, Microsoft's OAuth,
  Apple app passwords: none of it is exercised. The sandbox is a plain
  RFC 3501 server, not a stand-in for a specific provider.
- **No TLS** — the sandbox talks in the clear on `127.0.0.1`. `starttls` and
  `ssl` code paths are not exercised here.
- **Nothing leaves the machine** — no external host, no OS keyring, no
  `~/.erplibre`, no real credentials, and never a fixed port.

## The outbox

A message written while the account is offline is not refused: it is
queued. Losing what someone has just written because the network is down is
the worst of the three possible outcomes.

The queue empties at the start of every sync pass, before the server is
read again: at launch, on `r` / `Shift+R`, on the `mail_refresh_sec` timer,
and on `Mail > [3] Synchronise now` from the CLI menu. A pass that sends or
fails something says so — the TUI in its status line while the pass runs,
the menu under the account name. Order is preserved: two messages of one
exchange would otherwise arrive reversed.

Two things keep a message waiting: an offline account flushes nothing, and
a held message is skipped. An account's network state is settled when the
client opens it, and nothing reopens it afterwards — so an account that was
offline at launch, the very case that fills the queue, empties it at the
next launch of the client, or through the CLI menu, which connects afresh
each time it runs.

`o` opens the queue: a header line counts what is waiting, then one line
per message, oldest first — subject, recipients, and, once a send has
failed, why it failed and how many attempts it has taken. Each line carries
a button on its **left** that holds the message or releases it. A held
message never leaves on its own; only that button lifts the hold. `Escape`
closes the screen. Automatic replies queued by a rule are marked `[auto]`
and carry an expiry; the pane under the list previews the one whose button
has focus (see "Incoming mail rules").

A send that fails keeps the message in the queue and does not block those
behind it. A temporary refusal (a `4xx` code, a network error) is retried
at every pass, without limit. A permanent refusal (`5xx`) is retried up to
three times; after the third, a message written by hand is **held**, never
deleted, with its last error still shown under `o`. Holding a message
stops its attempts sooner — the screen deletes nothing. When the SMTP
server cannot be reached at all, the rest of the queue waits for the next
pass instead of each message waiting out the same connection timeout.

A message that leaves from the queue is filed into the account's Sent
folder, like one sent directly. If that filing fails, the failure is
logged; the message has left and is not resent.

Queued messages are sealed with the same key as the rest of the cache: an
encrypted cache that left its outgoing mail in the open would protect
everything except what was just written. The reason a send failed is sealed
with them: a server that refuses a message names the recipient it refuses.

## Incoming mail rules

A rule answers incoming mail on its own: when a new message in the inbox
matches its filter, the client sends the rule's reply to the sender. Each
account has its own ordered list of rules. This version runs two kinds of
action: the **custom reply**, and the **statistics report** — a custom
reply whose text carries figures computed on the mailbox (see "The
statistics report"). Forwarding comes later (see "What the client does not
do yet"). Any rule can be tried on a recent message before it answers a
real one (see "Testing a rule").

### When rules run

Rules run right after the sync pass of an online account: at launch, on
`r` / `Shift+R`, on the `mail_refresh_sec` timer (300 s by default), and on
`Mail > [3] Synchronise now` from the CLI menu. Nothing runs while both the
client and the menu are closed, so with the TUI open a message gets its
answer within `mail_refresh_sec`. Only the inbox is read: on a server that
files by label, the same message also sits in "All mail", and reading both
would answer it twice.

A rule acts only on what arrives **after** it is enabled. Enabling it
records the inbox position and the time — the rule is *armed* — and
everything older is left alone, so turning on a rule never answers a
backlog. Disabling then enabling it again arms it afresh. A message moved
into the inbox from another folder counts as an arrival, but one received
before the rule was armed, or longer ago than the rule's maximum age, is
still left alone, and no message is ever answered twice by the same rule;
most of the rest — list mail, a copy received in Bcc — is stopped by a
safeguard below.

An account with an `ephemeral` cache runs no rules: the log that
guarantees "at most once" would not outlive the process. When the server
renumbers the inbox (a new `UIDVALIDITY`), every enabled rule is armed again
at the current position and the status line says *Inbox renumbered: rules
re-armed.*

### The rule list

`e` opens the rule list of the current account: order, on/off, name, type,
"stop here", and the rule's last result.

| Key | Action |
|---|---|
| `n` | new rule |
| `Enter` | edit the rule under the cursor |
| `Space` | enable / disable it |
| `k` / `j` | move it up / down |
| `t` | toggle "stop here" |
| `x` | delete it (asks first) |
| `s` | try it on a recent inbox message (see "Testing a rule") |
| `l` | the rules log: the latest 200 decisions — date, rule, result, reason, sender, subject |
| `Escape` | close |

Under the table, *Cap per pass* and *Cap per hour* set the account's send
caps (see "Safeguards"), saved by their own button.

Rules apply in order, and **all** of them apply: a message that matches two
rules gets two replies. A rule with "stop here" ends the list for that
message as soon as its filter matched — even when a safeguard kept its
reply from leaving.

The editor holds the action type (*Custom reply* or *Statistics report*),
the name, "Rule enabled", "Stop here", the throttle (see "Safeguards"), the
maximum age in hours (48 by default, 1 to 720), the number of first sends
held for approval (1 by default, 1 to 10), the filter, and a button that
opens the reply form — *Custom reply…* or *Statistics report…* depending on
the type. Changing the type brings the throttle to the new type's default
when it still held the old one's, and a body still equal to the old type's
default text becomes the new type's; a body written by hand is kept. A rule
of a type this version does not run shows its type greyed out. `Ctrl+S`
saves, `Escape` cancels; a field that does not validate keeps the window
open with the reason on its status line.

### Filters

A filter is a tree. A group is **AND — all**, **OR — at least one** or
**NOT** (exactly one child); a condition tests one field. The root is an
AND group, and an empty root matches every message. `+ Condition` and
`+ Group` add inside the group under the cursor (or beside the condition
under it), `Edit` opens the condition, `Remove` takes the node out.

| Field | Tested on |
|---|---|
| From | the sender's address |
| To/Cc | every address in To and Cc |
| Subject | the subject |
| Body | the message text, downloaded only when a rule reaches this condition |

From and To/Cc are tested on the addresses alone, never on the display
name, which anyone can write. Two operations:

- **matches the pattern** — From and To/Cc only: a shell-style pattern
  compared with the whole address, never case sensitive. `*@example.net`
  matches `bruno.filtre@example.net`.
- **contains**, in one of five modes: *ignoring case and accents* (the
  default: `Désabonnement` contains `desabonnement`), *case sensitive*,
  *exact text* (equal apart from spacing), *whole word*, or *regular
  expression* (Python syntax, case sensitive unless the pattern starts with
  `(?i)`, at most 200 characters, tried on the first 10 000 characters;
  nested repetitions such as `(a+)+` are refused, as they can stall a pass).
  Each search gets one second: a pattern that takes longer on a message
  marks the rule as failed for that message ("regular expression too
  slow" in the log) and never counts as a non-match.

A filter holds at most 8 levels and 64 nodes, and a value at most 500
characters. The body is fetched with `BODY.PEEK`, so the message stays
unread; an account that is offline at that moment leaves the message for
its next online pass.

Under the tree, a preview counts how many of the last 200 cached inbox
messages the filter would retain. It never downloads a body: the messages
it cannot decide without one are counted as unknown. The cache keeps no Cc,
so a To/Cc condition is previewed on To alone.

Example — a rule that answers the partners of one domain, except their
mailing list:

```
AND — all
├── From matches the pattern *@example.net
└── NOT
    └── From contains (exact text) liste-annonces@example.net
```

A message from `bruno.filtre@example.net` gets the reply; one from
`carole.regle@example.org` does not match. The list exclusion is belt and
braces: a message from `liste-annonces@example.net` carries `List-Id` and
would be stopped by a safeguard anyway.

### The reply

*Custom reply…* opens the reply form: a format, a subject, a body, images,
and a preview recomputed as you type.

| Format | Sent as |
|---|---|
| Markdown (HTML and text) | the source as the text part, converted to HTML for the HTML part; raw HTML in the source is not passed through |
| Hand-written HTML | your HTML, plus a text part drawn from it |
| Text, images attached | text only; every image goes as an attachment |

Images (PNG, JPEG, GIF, WebP; 2 MiB each, 5 MiB together) are **copied**
into the rules folder when added, by path or with *Browse…* then *Add the
images*: moving or editing the original later changes nothing, and a
stored copy altered afterwards is refused instead of sent. In both HTML
formats, an image the body names — `![Logo](logo.png)` or
`<img src="logo.png">` — goes inline; a listed image the body does not name
goes as an attachment, so none is lost.

An SVG image (`.svg`, `.svgz`) is **converted to PNG** when added and stored
under the same name ending in `.png`: the SVG itself is never kept nor sent,
since common mail clients do not show it inline and it may carry script. The
PNG keeps the drawing's own width, reduced to 1200 px at most (600 px when
the drawing gives none), and needs a converter — `rsvg-convert`, the Python
module `cairosvg`, `inkscape` or ImageMagick, tried in that order; without
one, the form says to install `librsvg2-bin`. An SVG that points to an
outside file or resource — an `href` or `url()` other than `#…` or
`data:`, an `@import`, an external entity — is refused.

An empty subject gives `Auto:` followed by the received subject; otherwise
the subject is your text, with `{subject}` replaced by the received
subject.

The reply quotes nothing. It goes to the envelope sender (`Return-Path`),
or to the From address when there is none — never to `Reply-To`, which the
sender's message sets freely. It carries `Auto-Submitted: auto-replied`,
`X-Auto-Response-Suppress: All` and an `X-Loop` marker, so that other
responders stay silent, plus `In-Reply-To` and `References`, so that it
joins the conversation. A copy is filed into Sent; the original is not
marked answered.

### The statistics report

A rule of type *Statistics report* answers with a custom reply whose body
is a **template**: the text you write, in the same three formats and with
the same images, where `{{name}}` is replaced by a figure computed on this
account's inbox. It tells a correspondent how busy the mailbox is and how
long a reply usually takes. *Statistics report…* opens the reply form
with, under the body, the list of variables, a drop-down and *Insert the
variable*, which writes `{{name}}` at the cursor. The preview is computed
on the mailbox's real figures but without a requester: the requester's own
delay shows `—` there, and the trial (`s`) shows it for a real sender. A
new statistics rule starts with a short body ending on `{{rapport}}`.

| Variable | Replaced by |
|---|---|
| `{{rapport}}` | the whole report: daily table, weekly table, mailbox delay, the requester's delay, date and time zone |
| `{{rapport_jours}}` | the daily table, with its title |
| `{{rapport_semaines}}` | the ISO weekly table, with its title; empty when the report has no weeks |
| `{{recus_total}}` | messages received over the period of the daily table |
| `{{lus_total}}` | among them, those read |
| `{{repondus_total}}` | among them, those answered |
| `{{delai_moyen}}` | the average reply delay to the requester's own messages |
| `{{delai_moyen_boite}}` | the mailbox's average reply delay, rounded |
| `{{demandeur_recus}}` | the requester's messages received in the delay window |
| `{{demandeur_repondus}}` | among them, those answered |
| `{{jours}}`, `{{semaines}}`, `{{fenetre_jours}}` | the number of days, of weeks, and of days of the delay window |
| `{{periode_debut}}`, `{{periode_fin}}` | the first and last day of the period (`YYYY-MM-DD`; the last is yesterday) |
| `{{date_rapport}}` | the report's date, time and UTC offset |

The names are written as shown — in French, case sensitive, spaces inside
the braces allowed (`{{ rapport }}`). The first three are **blocks** —
paragraphs and tables — and go on a line of their own; the others are
short values. A missing value shows `—`. In hand-written HTML a block
cannot sit inside a tag, and the subject takes short values only; otherwise
the subject works as for a custom reply (`{subject}`, `Auto:` when empty).
An unknown name is refused when the rule is saved, and a `rules.json`
edited by hand that names one fails at send time with *message could not
be built*. A custom reply, in turn, refuses these names: the figures go out
only through a statistics rule and its safeguards.

`{{rapport}}` in English (the report's language is set by `I`, see below):

```
Activity over the last 7 days

Day         Received  Read  Answered
2026-10-21         3     3         2
2026-10-22         5     4         3
2026-10-23         2     2         1
2026-10-24         0     0         0
2026-10-25         1     1         0
2026-10-26         6     5         4
2026-10-27         4     3         2
Total             21    18        12

By ISO week (last 4)

Week      From        Received  Read  Answered
2026-W40  2026-09-28        18    17        11
2026-W41  2026-10-05        22    20        14
2026-W42  2026-10-12        15    15         9
2026-W43  2026-10-19        19    16        12
Total                       74    68        46

Mailbox average reply delay (last 30 days): 2 h 30 min

Your average reply delay (last 30 days): 12 h 35 min (over 2 known delays)

Report of 2026-10-28 09:12 +0000
Days and weeks in local time (UTC+00:00).
```

In the HTML formats the tables are HTML tables; in Markdown the text part
carries them as above.

**What is counted.**

- **Received** — inbox messages, dated by the server's reception date
  (`INTERNALDATE`); a message cached before that date was recorded falls
  back on its `Date` header.
- **Read** — among the messages received that day or week, those that
  carry `\Seen` *now*. The three columns of a row speak of the same
  messages: read and answered never exceed received. Since days are closed
  and the figures frozen for the day (below), "read" is no read receipt.
- **Answered** — the message carries `\Answered`, or a reply to it sits in
  a Sent folder (the one the server marks `\Sent`, or the account's Sent
  folder by name). Without a Sent folder, only `\Answered` counts and no
  delay is known.
- **Delay** — from the reception of a message to its first reply dated
  after it (the reply's `Date` header). The mailbox's average covers the
  messages received over the last *window* closed days; below **5** known
  delays the report says there are too few for an average, and above it
  the average is rounded — to 5 minutes under an hour, to 15 minutes under
  a day, to the hour beyond. The requester's delay covers their own
  messages over the last *window* days, exact and with no threshold.
- **Periods** — the daily table holds the last *N* **closed** days, up to
  yesterday; today never shows. The weekly table holds the last *M*
  complete ISO weeks, Monday to Sunday, labelled `YYYY-Www` with the date
  of their Monday; the current week is left out, and 1 January 2027
  belongs to `2026-W53`. The totals are those of the daily table. Days and
  weeks follow the time zone of the process (the `TZ` variable), which the
  report states.
- **Excluded everywhere** — automatic messages: the sync recognises
  `Auto-Submitted` (any value but `no`) and the `X-Loop` marker of an
  ERPLibre client in every folder, so our own automatic replies stay out
  even after the cache is rebuilt, and so do a third party's. A message
  whose `Message-ID` already arrived counts once: the first copy only, and
  a later copy inherits neither the answer nor the delay.

**Frozen for the day.** The mailbox part — tables, totals, mailbox delay —
is computed at most once per local day and per set of settings, then read
back from `report_snapshot.json`: every request of a day sees the same
figures, even if a message was read in between. The requester's part is
computed at each reply. The previews (`I`, the form, `i`) compute live.

**Known limits.** The sync re-reads `\Seen` and `\Answered` only for the 500
most recent messages of each folder: beyond them, read and answered by flag
are those of the first download, which is why the weekly table stops at 8
weeks. A message received one day shows, in that day's "read" column, its
state at the first request of the next day: a sender learns at best, once a
day, whether their message had been read by then. Small volumes give daily
counts of 0 or 1; they describe the mailbox, as intended.

**Who receives it, and when.** The report goes to the **From** address —
the one authentication vouches for and the one the requester's delay
concerns — never to `Return-Path` nor to `Reply-To`. A `Return-Path`
address is still checked like the sender: a robot, this account or another
configured account there stops the reply, and `Return-Path: <>` is a null
sender. The report carries aggregates and the requester's own delay only:
no address, name nor subject of another message.

On top of the safeguards of every rule, a statistics report requires an
**authenticated sender**. The **first** `Authentication-Results` header —
the one the receiving server adds on top — must carry `dmarc=pass` with
`header.from` equal to the From domain, or `dkim=pass` with `header.d`, or
`spf=pass` with `smtp.mailfrom`, equal to that domain or one of its
subdomains. Otherwise the message is logged *sender not authenticated* and
gets nothing. If your receiving server does not add that header at all,
the first one comes from the sender, who can write anything: set the
**server identifier** (`I`, below) to the name your server writes before
its first `;` (for example `mx.example.org`), and the first header must
then name it. This only protects when your server **removes** incoming
`Authentication-Results` that carry its identifier (RFC 8601, section 5);
otherwise a forger writes that identifier, which is public. Some servers
open the header on a result (`spf=pass …`) instead of an identifier: with
them a set identifier never matches, and the trial says so.

The throttle of a statistics rule is ticked with **1440 minutes** (one day)
by default. Each statistics rule also sends at most **20** reports per
sliding 24 hours: beyond, a request is logged *daily report cap reached*,
nothing is queued, and the account's hourly cap is left untouched. The
account caps and the first-send approval apply as to any rule: the first
real report waits **held** in the outbox (`o`), with the figures of the
moment it was built.

**Report settings — `I`.** In the client, `I` opens the report settings of
the current account: days in the daily table (1 to 31, 7 by default), ISO
weeks (0 to 8, 4 by default; 0 drops the weekly table), the delay window in
days (1 to 365, 30 by default), the format given to new statistics rules,
the report's language (the interface's, French or English — the labels of
the report only, your text stays as written), and the server identifier.
The time zone is shown, not set. Below, a preview of `{{rapport}}` on the
real mailbox, for the requester written in its field — prefilled with the
sender of the selected message, empty for none — recomputed by *Refresh
the preview* from the fields as typed, before any save. `Ctrl+S` saves,
`Escape` closes. While the server identifier is empty, the window warns
that any first `Authentication-Results` is trusted. The settings live under
the `report` key of `rules.json`; if that key cannot be read, the
statistics rules are skipped with a warning and the custom replies go on.

### Safeguards

Before a reply leaves, the rule's checks run in this order, and the first
that applies stops it. A message that is not armed for the rule, already
handled by it, or not matched by its filter is passed over silently;
every other stop is written to the rules log (`l`) under the reason shown.

| Reason in the log | The message… |
|---|---|
| too old | was received by the server longer ago than the rule's maximum age — measured on the server's reception date (`INTERNALDATE`), never on the `Date` header the sender writes |
| receive date in the future | carries a reception date more than 10 minutes ahead |
| automatic message | carries `Auto-Submitted` with any value but `no` |
| bulk mail | carries `Precedence: bulk`, `list`, `junk` or `auto_reply` |
| mailing list | carries `List-Id` or `List-Unsubscribe` |
| automatic replies refused by the sender | carries `X-Auto-Response-Suppress` with `All`, `OOF` or `AutoReply` |
| loop detected | carries the `X-Loop` marker of an ERPLibre client — another of your accounts included |
| spam | carries `X-Spam-Flag: yes` |
| null sender | has an empty envelope sender (`Return-Path: <>`), as a bounce does |
| no reply address | has no address to answer, or a From that names more than one |
| robot sender | comes from `mailer-daemon`, `postmaster`, `no-reply`, a bounce address… |
| sent by this account | comes from this account's own address |
| another configured account | comes from another account configured in the client |
| not addressed to this account | names this account in neither To nor Cc — a Bcc copy, a list, an alias |
| authentication failed | is marked `dmarc=fail`, or `spf=fail` without `dkim=pass`, by the receiving server's `Authentication-Results`: answering would send our reply to whoever was impersonated |
| sender not authenticated | statistics report only: carries no first `Authentication-Results` that vouches for the From domain (see "The statistics report") |
| throttled | comes from a sender this rule answered recently (below) |

**Do not send again if a message arrives within N minutes.** When the box
is ticked, a message is not answered if this rule's last send to the same
sender — the same From address, or the same reply address — is less than
N minutes old. It is measured from the last **send**, not from the last
message received, and a reply waiting in the outbox counts as a send. The
box is ticked by default with 10080 minutes (7 days); unticked, every
message gets its reply, the other safeguards aside. With 60 minutes:
`carole.regle@example.org` writes at 9:00 and is answered at 9:00; she
writes again at 9:40 — *throttled*, 40 minutes after the last send; she
writes at 10:05 — answered, 65 minutes after the last send. The 9:40
message did not restart the clock.

**Caps.** Whatever the rules say, an account sends at most **20** automatic
replies per pass and **60** per sliding hour, all rules together. Beyond
that, replies are held in the outbox and the status line warns
*Automatic send cap reached; the rest is held (o).* Both caps are set
under the rule list, or by the `caps` key of `rules.json`
(`{"per_pass": 20, "per_hour": 60}`, whole numbers of at least 1). The
hourly cap is what bounds a short timer: with `mail_refresh_sec` at 30 s,
the cap per pass alone would let 2 400 replies an hour through.

**Holding the first send.** Until a rule has really sent its first
replies — one by default, up to 10 — each new reply waits **held** in the
outbox. `o` previews it: recipient and subject, the first 20 lines of
text, the inline and attached images, and its expiry. *Release* lets it
leave at the next sync pass. Changing the rule's filter or its reply
(format, subject, body, images) starts the count again, and a reply still
waiting from before the change is dropped rather than sent; renaming,
reordering or changing its limits does not.

**When the cache is rebuilt**, the log that throttles and counts goes with
it. Replies are then held for approval until the longest throttle of the
enabled rules has run out, and the status line says *Cache rebuilt:
automatic replies await your approval (o).*

### When a reply cannot leave

| Situation | What happens |
|---|---|
| account offline | the reply is queued and leaves at the next online pass |
| temporary server refusal | queued; the rest of the pass's replies are queued too, without trying the server again |
| permanent server refusal | logged as failed, not retried |
| queued for 24 h | dropped from the queue (*expired*), held or not |
| rule deleted or disabled meanwhile | dropped (*rule disabled*) |
| rule's filter or reply changed meanwhile | dropped (*rule changed since*) |
| three permanent refusals from the queue | dropped (*attempts exhausted*) |
| image unreadable, message impossible to build | logged as failed, not retried |

The log `l` of the main screen lists, per rule, what failed; the rules log
gives each message's result and reason. `~/.erplibre/mail.log` never
carries an address or a subject.

After a pass that did something, one line is appended to the status line,
per account with enabled rules — for instance `perso : automatic replies
sent: 2, awaiting approval (o): 1`. A pass that found nothing to do adds
nothing.

One pass at a time handles an account, whatever the process — TUI or menu.
Another one waits up to 30 s, then gives up with *Rules: another pass is
running.*; the next pass picks up where it stopped. A pass catches up at
most 200 messages; older ones are skipped with a warning.

### Testing a rule

`s` in the rule list tries the rule under the cursor without waiting for a
real message. It lists the 50 most recent inbox messages of the cache;
`Enter` on one shows what the rule would do with it, and writes nothing.
Online, the message's full headers (`Authentication-Results`,
`Return-Path`, `List-Id`…) are fetched from the server, and its body with
`BODY.PEEK`, so it stays unread. Offline, the trial works on the cached
row — without Cc nor those headers — says the verdict is partial, and
reads the body from the cache when it is there; without it, a Body
condition stays unknown. It does the same online when the server has
renumbered the inbox since the last sync: a cached number could then name
another message.

The result shows, in order: a warning when the rule is disabled; the filter
tree with each node's outcome (✓, ✗, `?` when the body is missing) and
whether the message matches; the **verdict** — *would reply*, or the reason
a real pass would give (too old, already handled, sent by this account…);
and, when it differs, the verdict **for a new message**, as if this one had
just arrived after the rule was armed — arming, age and "already handled"
aside, the other safeguards, the throttle included, still apply. When a
reply would be decided, the trial also says whether the engine would
**hold** it, and why: until a rule has really sent its first replies, each
new one is held for review — the first real report always is — and is
released from the outbox (`o`). A statistics report past its daily cap
is not held but skipped: the verdict then reads *daily report cap
reached*, and nothing would reach the outbox. For a statistics report, it
shows the server identifier read in the first `Authentication-Results` (or
that the server writes none), whether the sender is authenticated, and a
warning while no identifier is set. Then the recipient, the subject, the text of
the reply, its images and their role, or the error that stops the reply
from being built.

**Send a trial to myself** sends that reply to the account's own address,
its subject prefixed with `[Trial]`, as soon as the reply could be built —
whatever the verdict, since one usually tests with a message of one's own,
which a real pass stops as *sent by this account*. It carries the same
automatic-reply headers but no `In-Reply-To` nor `References`, so it never
joins a third party's conversation. It writes nothing to the rules log,
counts towards no throttle nor cap, does not go through the outbox — offline
it is refused and nothing is queued — and marks nothing answered. It is
recorded as an automatic message, so its copy in Sent and its arrival in
the inbox stay out of the statistics. When it arrives, the next pass logs
it *automatic message* for every rule whose filter matches it: that line in
the rules log comes from the trial, not from a stranger. A rule of a type
this version does not run says so and sends nothing.

### From the CLI menu

`Mail > [6] Incoming mail rules` asks for an account, then offers `[1]`
list the rules (with a summary of each filter), `[2]` enable / disable one,
`[3]` move one up or down, `[4]` delete one (asks first), `[5]` the latest
50 lines of the rules log, `[6]` the statistics report settings, `[7]` try
a rule on a message, `[0]` back. `[6]` prints the time zone, asks each
setting with its current value as default — `-` empties the language or
the server identifier — saves them, then prints `{{rapport}}` computed on
the cache, without a requester. `[7]` asks for a rule, opens the account
like `[3] Synchronise now` — online when it can, for the full headers —,
lists the 20 most recent inbox messages, prints for the chosen one what the
`s` screen shows, then offers to send the trial to yourself. Creating and
editing a rule go through `e` in the TUI: a filter tree is not typed line
by line. A rule enabled from the menu is armed at its next pass.

### Where rules live

`~/.erplibre/mail/.rules/<account>/rules.json` holds the rules, the caps
and the report settings (`report` key), mode 0600, **in clear text even
when the cache is encrypted** — the same exposure as `accounts.json`. It
carries the filter values (the addresses and words you filter on) and the
body of the reply. The images are copied beside it under `media/`;
`state.json` records where the engine stopped in the inbox, and
`report_snapshot.json` (0600) the mailbox part of the day's report — counts
and a delay, no address. The rules log itself lives in the account's
`cache.db`, sealed with it. Keys this version does not know are kept when
the file is rewritten, and a rule of a kind it does not run yet — forward —
is shown and left alone; a file of a newer format version is refused and
left untouched.

## Managing folders

`F` opens the folder screen: `n` creates, `r` renames, `d` deletes,
`Escape` closes.

Deletion destroys the folder **and its contents on the server**. IMAP has no
trash for folders, so what leaves this way comes back only from a server
backup. It therefore asks you to type a word rather than to confirm: a
closed question gets answered by reflex. The word carries no accent, so it
can be typed on any keyboard layout.

Every operation reaches the server first and the cache second. If the server
refuses, the cache must not describe a state that exists nowhere — a folder
missing from the remote tree but present in ours would never resynchronise.
Renaming carries the messages and their bodies across, so the next pass does
not download again what is already there.

## Filing and throwing away

`d` moves the selected message to the account's trash folder. Nothing is
destroyed: a trash folder is emptied elsewhere, which is what makes the
gesture repairable — and why it asks for no confirmation.

IMAP has no verb every server knows, so the client copies the message,
flags the original deleted, and clears it with `UID EXPUNGE`, which names
what it removes. A bare `EXPUNGE` would sweep every message flagged deleted
in the folder, including ones another client flagged: destroying what this
client did not move is not its place. A server that does not offer
`UID EXPUNGE` leaves the original in place, struck through, and the status
line says so rather than letting another client's view look like a bug.

Three refusals, each said on the status line: the account is offline, the
account announces no trash folder — inventing a name would create one
nobody asked for — or the message is already there. The local cache is
updated only after the server agrees; getting ahead of it would make a
message vanish from the screen and come back at the next pass.

`m` files the message into a folder you pick instead: it opens the
account's folders, arrows and `Enter` choose, `Escape` cancels. The folder
the message is already in is not offered — moving it there would do
nothing, and offering it suggests otherwise. It is a screen of its own,
apart from the folder screen on `F`, which creates and destroys: mixing an
everyday gesture with destructive ones puts deleting a folder one key away
from filing a message.

The list also offers the folders of the **other open accounts**, each row
carrying its account name; the message's own account comes first and is
not named, since that is where most filing goes. An account that is
offline is not offered at all — proposing an unreachable target would
fail the gesture after the message had already been read back.

Nothing links two servers, so a move across accounts is a different
sequence: the message is read in full, deposited at the other end with
`APPEND`, and only then removed here. Its flags and its original date
travel with it — without the date the receiving server stamps it as
arriving now, and it would climb to the top of the mailbox as if it were
new mail.

An accepted deposit is not proof on its own. The client asks the target
server whether that folder now holds this `Message-ID`, and only a yes
lets it remove the source. Anything else leaves the message here and says
so: a duplicate can be cleaned up, a message that vanished cannot. The
check is `HEADER Message-ID`, not a text search, because a reply quoting
the identifier in its `In-Reply-To` would otherwise pass for the deposit.
A message carrying no `Message-ID` is therefore never removed from its
source — nothing would identify it at the other end.

`D` empties that trash folder. This is the one gesture the client cannot
repair: IMAP has no trash for what leaves a trash folder, and no
synchronization pass brings it back. It therefore asks you to TYPE
`supprimer`, not to press a key — an irreversible gesture must not be
obtainable by one keystroke too many. `Escape`, an empty field or any
other word all leave everything in place.

The whole folder goes at once, which is what makes a bare `EXPUNGE`
acceptable here where `move` refuses it: everything flagged deleted in
that folder is either what the client just flagged or what another client
flagged in the same folder, and the gesture destroys both anyway. A
message delivered after the UID listing is not flagged, so it survives.

The count the confirmation shows comes from the cache and says so. The
cache always lags behind the trash folder — `d` fills it on the server
without adding anything locally — so the number that matters is the one
reported afterwards: what the server actually removed.

## Reading a long folder

A folder arrives in pages of 500 messages, newest first. The next page
loads by itself as the cursor comes within twenty rows of the bottom, so
scrolling never stops at a wall — and the cursor stays where it was when
it arrives. A sync pass keeps the depth already loaded rather than
shrinking the list back to one page under a cursor that had gone further
down.

Pages exist because the alternative is worse: a mailbox of thirty thousand
messages would build thirty thousand rows on every open and every
keystroke of a search, in a screen that answers instantly today. Searching
is unaffected — a search looks at the whole cache, not at what the list
has loaded.

## Acting on several messages

`x` selects the message under the cursor and moves down a line, so a run
of them is a run of keystrokes. `d`, `m`, `s`, `u` and `*` then act on
what is selected — and on the message under the cursor when nothing is,
so a single-message gesture never costs a keystroke more than it used to.
Selected rows carry a `✓` next to the unread dot and the flag star.

Messages of one folder leave together — one `COPY`, one named removal —
rather than one round trip each. A widened search mixes folders and even
accounts in one list, so the batch is grouped by where each message
actually lives, never assumed. A batch heading for another account is
deposited and confirmed one message at a time, since nothing links two
servers.

`*` on a batch takes the group's meaning: it only unflags when every
selected message is already flagged. Toggling each on its own would make
the result unpredictable — a half-flagged batch would invert with nothing
saying which state it ends in.

What has been handled stops being selected. Keeping it would aim the next
key at messages already gone, whose UIDs no longer mean anything in the
folder they left.

## Following a message

`*` flags the selected message, and `*` again unflags it — a toggle rather
than two keys, because a flag is put on and taken off the same message,
unlike read/unread where one often forces the state of a message already
in the other. `\Flagged` is an IMAP system flag, so the phone and the
desktop client show what is flagged here, and the reverse.

The list carries two marks in one column: `●` for unread, `★` for flagged.
Two characters and not one, because a message can be both, and showing a
single mark would lose one of them.

## Signature

Each account can carry a signature, set from `Mail > Accounts > Signature
of an account` — line by line, an empty line ending the entry, and writing
nothing clearing it. It lives in `accounts.json`: a signature is read in
every message it goes out with, so hiding it in the vault would protect
nothing.

It appears in the compose form, below what you write and after the `-- `
delimiter — two dashes, a space, a newline, the form clients use to fold
or grey out what follows. Being in the form rather than added on sending
means it can be read and edited before it leaves; added at the last
moment, a wrong signature would go out without its author ever seeing it.

A reply carries it under the quoted text. A forward does not: the
forwarded message travels with its own.

## Reading a whole folder at once

`Shift+M` marks every unread message of the open folder as read — the
gesture a mailing-list mailbox calls for, where three hundred unread
messages ask nothing of anyone. It asks first, and names how many: the
gesture destroys nothing, but nothing undoes it conveniently either, since
"make unread the ones that were" does not exist once the starting list is
gone. A closed question, not a word to type: demanding a word here would
wear out the vigilance kept for what destroys.

It refuses while the account is offline, and that is not a shortcut: a sync
pass reads flags back from the server, so a mark set without it would be
undone at the next pass, silently. The server is told first and the cache
follows, so a refusal leaves both saying the same thing.

## Saving an attachment

`w` saves an attachment of the selected message into `~/Téléchargements`,
creating the folder if needed. With more than one attachment it opens the
list — name, type, size — and `Enter` saves the one you point at; with a
single one it saves without asking, since the question would have a known
answer. It knew only the first one before, and a message carrying three
showed three in the preview while handing over one.

The file name comes from the message, so from anyone: only its base name
is kept and nothing may be written outside the target folder.


## List views

`g` cycles the message list through three views:

- **flat, by date** — the default;
- **by thread** — replies sit under the message they answer, indented, and
  ordered by date within their thread. Roots keep the order the flat view
  gave them, so switching does not reshuffle everything;
- **unread only**.

A reply whose original is not in the selection stays visible as a root
rather than disappearing, and a cache filled before threading was added
behaves exactly like the flat view. The list keeps its scrollbar gutter
reserved at all times, so its width does not shift under the cursor.

## Syncing several accounts

Accounts sync side by side, four at a time. Each holds its own socket and
its own locked cache, so a pass that mostly waits on the network becomes one
wait instead of several. Measured with four accounts of 0.25 s each: 0.26 s
against 1.00 s in sequence.

The cap is deliberate — providers refuse a burst of simultaneous
connections, and past a handful the gain disappears. Two passes never
overlap on the same account: one shared imaplib socket is not safe across
threads. An account that fails is reported and does not stop the others.

Inside one account, its folders now advance together too, over up to three
links to the same server. One `imaplib` connection has a single selected
folder at a time, so on one link a mailbox of thirty folders walks them
one by one and the wait is the sum of the thirty.

Three links, no more: providers cap how many connections one account may
hold, and that cap is shared with the person's other clients — phone,
desktop client — which keep theirs open all day. Folders are dealt out in
round robin rather than in contiguous slices, because a LIST returns them
grouped by hierarchy and the large ones follow each other.

A provider that refuses one more link costs no folder: that link's share
goes back to the one already open, so the account syncs more slowly, never
less completely. Extra links are closed at the end of every pass, whatever
happened — an account leaving one behind each time would reach the
provider's limit in minutes.

## Search

`/` searches the **whole cache of the open folder**, not just the messages
currently loaded. Subject, sender, recipient and snippet are matched. At
most 500 matches are returned, the most recent first. `Shift+S` reaches
past the cache — see below.

`p` widens that scope, one press at a time: the open folder, then every
folder of the account, then every folder of every account, then back to
the open folder. The status bar names the new scope each time — a list
that silently grew would read as a defect. Widening stays an explicit
gesture: in `encrypted` mode, doing it automatically would decrypt folders
nobody asked about, at every keystroke.

A result from elsewhere carries where it comes from, shown before its
subject as `[Archives]`, or `[account/Archives]` when it comes from
another account. This is not decoration. A UID names nothing on its own —
the same number names a different message in every folder — so a result
that lost its origin would show the body of its namesake here, and `d`,
`m`, `s`, `u` and `w` would act on that one. Each of those keys follows
the result's own folder and account instead.

In `clear` cache mode an FTS5 index answers in milliseconds and the list
follows every keystroke. In `encrypted` mode no index exists — one would
store in the open exactly what the cache seals — so the search decrypts row
by row. Measured on 200,000 messages: 0.00 s indexed against 4.4 s scanned
for a term that matches nothing. The list therefore stops following each
keystroke there and waits for **Enter**, saying so in the status bar. Until
that key is pressed, the list filters only the messages already loaded.

The result is the same either way; only the cost differs.

`Shift+S` asks the server the same question, over the same scope as `p`
has set — the open folder, the account's folders, or every account's. It
is a separate gesture on purpose: extending at every keystroke would charge a
round trip to a search that already answers. What the server finds is
downloaded and stored, so the local search shows it immediately and finds
it again offline. The server looks at whole messages, headers and body, so
it can return what the local search would not — which is the point of
looking further. An account that is offline says so rather than waiting,
and a server that refuses says why. Over a wider scope one folder that
refuses — unselectable, gone since the last pass — does not stop the
others: the count of folders that gave no answer is reported alongside
what was brought back.

## Statistics

`i` in the client opens the statistics screen; `[5]` in the Mail menu prints
a text summary per account, without opening the client — total, unread and
their share, the last fourteen daily slices of volume, the five most frequent
senders, and the median reply delay. That is all of it: the per-folder table,
the recipients and the count of undated messages are computed and dropped,
the cut to fourteen slices is not announced, and step, period and scope
belong to the `i` screen alone. Everything is computed from the local cache,
so both answer offline, with no network request; `[5]` opens the vault once
for all accounts, and only where a cache is sealed with a key kept there — an
account in `clear` is never asked for a password.

- **Volume** per day, week, month or year. The bars are normalised on the
  series maximum, so the shape of the distribution survives whether a month
  holds twelve messages or twelve thousand.
- **Per folder** — count, unread share, cumulative size.
- **Correspondents** — the most frequent senders and recipients, counted by
  lowercased address rather than by display name, so one person writing under
  several labels stays one row.
- **Reply delay** — the median time between a message and the reply that
  answers it, joined through hashed `Message-ID`s.

Three drop-downs sit above the figures. **Step** (day, week, month, year)
sets how wide one histogram bar is: `d`, `w` and `m` choose the first three,
the year only from the list. **Period** (all time, last 12 months, last 5
years, last 30 days) bounds the histogram and, with it, the totals, the
per-folder table, the correspondents and the reply delays; a folder that the
period empties stays listed, with a zero. **Scope** is all folders or the
open one, and `f` toggles it. Keys and lists lead to the same state: a key
moves its own list along with it.

The screen opens on an **overview computed in SQL alone** — counts, per-folder
figures and the histogram — so it appears at once even on a mailbox holding
hundreds of thousands of messages. Correspondents and reply delays open every
sealed column and are therefore computed only on **Enter**, in a background
thread with a progress count. The histogram step is chosen from the span the
what is counted actually covers — the chosen period, and the chosen
scope — so that no more than 180 bars are drawn: ten years of archives are
read by month, twenty by year rather than as seven thousand daily bars. Only the most recent slices are listed — the totals above them
count every slice of the period, and the screen says how many it left out.

At the top of the screen, an **activity** section gives the inbox's daily
table of the statistics report: received, read and answered for each of the
last *N* closed days, *N* being the days of the report settings (`I`, 7 by
default), with their total. It counts exactly as the report does (see "The
statistics report") and ignores the step, the period and the scope chosen
below, which its title says. It is computed once when the screen opens, in
SQL alone, without opening a sealed column.

Two figures are honest about what they cannot know:

- **Messages with no readable date** are excluded from the histogram and
  counted on their own line. Filing them under 1 January 1970 would draw a
  spike that never happened.
- **Reply delays need the thread columns**, added with the v2 cache. Messages
  synchronised before that carry nothing to join, and the screen says so
  instead of showing a null delay. A full resynchronisation fills them in.

## Authenticating with OAuth

Gmail and Microsoft both accept OAuth on IMAP and SMTP; Microsoft accepts
nothing else. An account says how it authenticates — `login` or `oauth` —
and the client hands the server whichever secret that means, a password or
an access token.

**What this repository does not ship: an identity.** The endpoints and
scopes travel with each preset, but `client_id` is empty. A client
identifier registered in the project's name would make every installation
share one quota, one consent screen and one revocation; whoever deploys
registers their own, once, in the provider's console. Set it either in the
TODO configuration under `mail.oauth.<preset>.client_id` — written to
`private/todo/todo_override_private.json`, the file git ignores — or in
`ERPLIBRE_MAIL_OAUTH_CLIENT_ID` (append `_GMAIL` or `_OUTLOOK` to set one
per provider). The configuration wins over the environment. Add
`client_secret` the same way when the provider requires one; an installed
application usually does not.

**Adding the account.** `Mail > [2] Accounts > [2] Add an account` asks
which authentication to use wherever there is a choice — Gmail takes
either, the Microsoft presets only OAuth, iCloud only an app password.
Choosing OAuth then offers two ways to obtain the token, or goes straight
to the second when no `client_id` is configured:

1. **Authorise in the browser.** The client listens on an ephemeral port of
   127.0.0.1 — never on every interface, which would expose the
   authorisation code to the local network for the length of the flow —
   opens the provider's consent page, and waits for one redirection. PKCE
   ties the exchange to the request: the verifier stays on the machine, so
   an intercepted code is not enough to obtain a token. A redirection whose
   state does not match the request is refused without exchanging anything.
2. **Paste a refresh token** obtained elsewhere — a provider console, or a
   tool made for it.

Either way the token is stored in the vault under its own reference, beside
the password entry rather than over it, so an account that goes back to a
password still has one.

The TUI's own form (`n`) offers the same choice: picking a preset settles
what the account can use — the list of authentications is only live where
there is something to choose — and the secret field then says whether it
wants a password or a token. An **Authorise in the browser** button appears
there too, but only where a `client_id` is configured: without one it would
open a page answering "invalid_client", so it stays hidden rather than
greyed out. The flow runs in a worker thread, otherwise waiting for the
redirection would freeze the window, `Escape` included.

**Afterwards, nothing.** An access token lasts about an hour; the client
exchanges the refresh token for a new one before opening a session, writes
the new set back to the vault, and syncs. The exchange happens in the main
thread, before any pass: writing the vault rewrites the whole file, and two
sync threads writing at once would corrupt it.

A session outlives its token, so the exchange is not only a start-up step.
Anything that opens a connection later asks for the secret again and gets a
refreshed one — a queued message leaving hours after it was written, for
instance. And when the server refuses a pass on a dead token, the client
reopens the IMAP link once with a fresh one rather than going quiet until
someone restarts it. Once only, and only where the secret can change:
presenting the same password to the same server would earn the same
refusal, and retrying forever on a server that refuses for another reason
would spin.

**When it fails.** Three outcomes, told apart because the remedy differs. A
new token arrives and nothing is said. The grant is revoked — the owner
withdrew it, or the provider expired it — and no retry will bring it back:
`Mail > [2] Accounts > [6] Replace an account's OAuth token` offers the
same two ways as adding one does, and an abandoned flow or an empty entry
writes nothing rather than erasing what is there.
Or the provider failed to answer, in which case the token in place still
stands and the next pass tries again.

## What the client does not do yet

- **No client identifier** — the browser authorisation flow needs a
  `client_id` you register yourself; without one, an OAuth account is added
  from a token obtained elsewhere (see "Authenticating with OAuth").
- **Rules do not forward** — a rule cannot yet forward a message; a
  forward rule is kept and shown, never run.
- **No headless service** — rules run only while the TUI is open or when
  `Mail > [3] Synchronise now` runs; with both closed, nothing is answered.
- **No `\Answered` from the outbox** — a manual reply marks the original
  answered only when it leaves at once; one that waited in the outbox does
  not.
- **No aliases** — an account knows its own address and login only, so a
  message received through an alias is logged *not addressed to this
  account* and gets no automatic reply.

The design spec is not tracked in this tree; recover it from history with
`git log --all -- "docs/superpowers/specs/*"` if you need what the remaining
phases add.
