
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

### App passwords for Gmail, Outlook and iCloud

Phase 1 speaks plain IMAP/SMTP login only — no OAuth yet (that is phase 2).
Gmail, Outlook and iCloud have all closed that door to the account's real
password, so each of these three presets requires an **app password**
instead:

| Provider | Where to generate it |
|---|---|
| Gmail | [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) — 16 characters, spaces are accepted. Two-step verification must be on, otherwise the page is empty. |
| Outlook / Microsoft 365 | [account.microsoft.com/security](https://account.microsoft.com/security) — Microsoft is closing basic authentication on consumer accounts: without an app password this needs OAuth (phase 2, not implemented). |
| iCloud | [account.apple.com](https://account.apple.com) — under "Sign-In and Security". Two-factor authentication must be on. |

Use that generated password when account setup asks for one — never the
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
4. **Provider** — a number from the printed list: Gmail, Outlook, iCloud, or
   "Standard server" (generic IMAP/SMTP).
5. If you picked "Standard server", the **IMAP host** and **SMTP host** are
   asked next; the other presets fill these in for you.
6. If the preset requires an app password, its note is printed here as a
   reminder.
7. **Password** — typed hidden (`getpass`), then stored — never written to
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
| `/` | open the search field: it searches the whole cache of the open folder — not just the messages on screen — over subject/from/to/snippet; it does not search the server (see "Search") |
| `g` | cycle the message list: flat, by thread, unread only (see "List views") |
| `s` / `u` | mark the selected message seen / unseen |
| `c` | compose a new message |
| `a` / `Shift+A` | reply / reply all |
| `f` | forward |
| `w` | save the message's **first** attachment to `~/Téléchargements` (created if missing) |
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
so a typo never destroys a working password. If the account is Gmail,
Outlook or iCloud, check first that you used an app password (see
"Prerequisites" above), not the account's normal one. Opening the TUI
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

## Search

`/` searches the **whole cache of the open folder**, not just the messages
currently loaded. Subject, sender, recipient and snippet are matched. The
scope stops there: the other folders of the account, the other accounts and
the server are not searched, and at most 500 matches are returned, the most
recent first.

In `clear` cache mode an FTS5 index answers in milliseconds and the list
follows every keystroke. In `encrypted` mode no index exists — one would
store in the open exactly what the cache seals — so the search decrypts row
by row. Measured on 200,000 messages: 0.00 s indexed against 4.4 s scanned
for a term that matches nothing. The list therefore stops following each
keystroke there and waits for **Enter**, saying so in the status bar. Until
that key is pressed, the list filters only the messages already loaded.

The result is the same either way; only the cost differs.

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

## What the client does not do yet

- **No OAuth** — Gmail, Outlook and iCloud need an app password (see above).
- **No server-side search** — `/` filters only what's already synced to the
  local cache.
- **No deleting or moving a message** — `s` and `u` change the seen flag,
  and `F` creates, renames and deletes folders, but a message itself can be
  neither deleted nor moved to another folder.

The design spec is not tracked in this tree; recover it from history with
`git log --all -- "docs/superpowers/specs/*"` if you need what the remaining
phases add.
