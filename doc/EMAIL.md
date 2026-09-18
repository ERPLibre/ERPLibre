
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
| `Shift+F` | open the folder screen: create, rename, delete (see "Managing folders") |
| `i` | open the statistics screen (see "Statistics") |
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

## Synchronization

A sync pass is incremental: only UIDs above the last known one are
fetched, message bodies are never downloaded during a pass (only headers),
and bodies are fetched on demand when you open a message. Flags
(read/unread, etc.) of already-known messages are re-checked on every
pass, so a message read elsewhere shows up correctly here too.

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
client as the only cure and nothing saying so. The pass now reopens the
link once and runs again. Raising `mail_timeout_sec` avoids the cut rather
than repairing it; a server that answers *no* is not a dead link and is
never retried.

If the server reports a changed `UIDVALIDITY` for a folder (its UIDs no
longer mean what they used to — typically after a server-side migration),
that folder's cache is purged and resynced from scratch automatically. The
pass says which folders it did that to: the TUI on its status line at the
end of the pass, `Mail > [3] Synchronise now` under the account name.

## Where the files live

| Path | Contents |
|---|---|
| `~/.erplibre/mail/accounts.json` | account list — servers, presets, cache mode, and a `secret_ref` pointer; never a password (mode 0600) |
| `~/.erplibre/mail/<account>/cache.db` | that account's SQLite cache (mode 0600, parent directory 0700) |
| `~/.erplibre/mail/<account>/<folder>/<uid>.eml` (or `.eml.enc` when sealed) | one file per downloaded message body |
| `/dev/shm/erplibre-mail-<pid>/<account>/` | an `ephemeral` account's cache while the process is alive; removed when it exits (a sweep at every startup also clears directories left behind by a killed process) |

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
message never leaves on its own; only that button lifts the hold, never a
delay that expires. `Escape` closes the screen.

A send that fails keeps the message in the queue and does not block those
behind it. Nothing gives up: the next pass tries again and the counter
climbs, however final the refusal. Holding the message is the only way to
stop those attempts — the screen deletes nothing.

Queued messages are sealed with the same key as the rest of the cache: an
encrypted cache that left its outgoing mail in the open would protect
everything except what was just written. The reason a send failed is sealed
with them: a server that refuses a message names the recipient it refuses.

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

## Lire un long dossier

Un dossier arrive par pages de 500 messages, le plus récent d'abord. La
page suivante se charge d'elle-même quand le curseur arrive à vingt lignes
du bas, de sorte que le défilement ne bute sur aucun mur — et le curseur
reste où il était quand elle arrive. Une passe de synchronisation garde la
profondeur déjà chargée plutôt que de ramener la liste à une page sous un
curseur descendu bien plus bas.

Ces pages existent parce que l'inverse est pire : une boîte de trente mille
messages construirait trente mille lignes à chaque ouverture et à chaque
frappe de recherche, dans un écran qui répond aujourd'hui tout de suite. La
recherche n'est pas concernée — elle regarde tout le cache, pas ce que la
liste a chargé.

## Following a message

`*` flags the selected message, and `*` again unflags it — a toggle rather
than two keys, because a flag is put on and taken off the same message,
unlike read/unread where one often forces the state of a message already
in the other. `\Flagged` is an IMAP system flag, so the phone and the
desktop client show what is flagged here, and the reverse.

The list carries two marks in one column: `●` for unread, `★` for flagged.
Two characters and not one, because a message can be both, and showing a
single mark would lose one of them.

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

The design spec is not tracked in this tree; recover it from history with
`git log --all -- "docs/superpowers/specs/*"` if you need what the remaining
phases add.
