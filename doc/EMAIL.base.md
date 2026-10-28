<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Mail client

A mail client built into the TODO CLI: several accounts, IMAP + SMTP, and a
local cache — so you can read and answer email without leaving
`./script/todo/todo.py`.

Every `Mail > ...` path below is shorthand for
`TODO > [3] Assistant > [2] Mail - Read and send email > ...` — the full path
is spelled out once, in "Adding an account".

<!-- [fr] -->
# Client courriel

Un client courriel intégré au CLI TODO : plusieurs comptes, IMAP + SMTP, et
un cache local — pour lire et répondre à son courriel sans quitter
`./script/todo/todo.py`.

Chaque chemin `Courriel > ...` ci-dessous est un raccourci pour
`TODO > [3] Assistant > [2] Courriel - Lire et envoyer du courriel > ...` — le
chemin complet est écrit une fois, dans « Ajouter un compte ».

<!-- [en] -->
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

<!-- [fr] -->
## Prérequis

Quatre paquets Python, déjà listés dans
`requirement/erplibre_require-ments.txt` (l'environnement `.venv.erplibre`,
pas un venv Odoo) :

- `cryptography` — scelle le cache local en mode `encrypted` et `ephemeral`.
- `keyring` — le trousseau système, l'un des deux endroits où peut vivre un
  mot de passe.
- `pykeepass` — le coffre KDBX, l'autre endroit, celui que le client essaie
  en premier.
- `textual` — l'interface terminal elle-même. Sans lui, « Ouvrir le client
  courriel (TUI) » affiche un message et ne fait rien ; le reste du menu
  (comptes, synchronisation, cache) fonctionne quand même.

Installez-les avec :

<!-- [common] -->
```bash
.venv.erplibre/bin/pip install -r requirement/erplibre_require-ments.txt
```

<!-- [en] -->
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

<!-- [fr] -->
### Mots de passe d'application pour Gmail et iCloud, et le cas Microsoft

Le client ne parle qu'IMAP/SMTP en authentification simple — pas encore
OAuth, c'est la phase suivante. Gmail et iCloud ont fermé cette porte au
vrai mot de passe du compte : les deux préréglages exigent donc un **mot de
passe d'application** à la place :

| Fournisseur | Où le générer |
|---|---|
| Gmail | [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) — 16 caractères, les espaces sont acceptés. La validation en deux étapes doit être active, sinon la page est vide. |
| iCloud | [account.apple.com](https://account.apple.com) — section « Connexion et sécurité ». L'authentification à deux facteurs doit être active. |

**Un compte Microsoft exige OAuth, pas un mot de passe.** Microsoft a
retiré l'authentification simple d'IMAP — d'abord chez les locataires
Microsoft 365, puis sur Outlook.com — et un mot de passe d'application EST
de l'authentification simple : il est refusé lui aussi. Personne ne peut la
réactiver. Ajoutez plutôt un tel compte avec un jeton de rafraîchissement,
comme le décrit « S'authentifier par OAuth » plus bas ; le client le dit là
où il demande le secret, plutôt que de laisser un refus passer pour une
faute de frappe.

Utilisez ce mot de passe généré quand la configuration du compte en demande
un — jamais le mot de passe normal du compte. Le préréglage « Serveur
standard » (IMAP/SMTP générique) n'en a pas besoin. Le client affiche
lui-même ces mêmes notes — au moment de demander le mot de passe, et de
nouveau quand un refus le fait redemander. Elles vivent dans
`script/todo/todo_i18n.py` sous les clés `mail_preset_note_*`, et ce
tableau les suit.

<!-- [en] -->
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

<!-- [fr] -->
## Ajouter un compte

Chemin de menu : `TODO > [3] Assistant > [2] Courriel - Lire et envoyer du
courriel > [2] Comptes > [2] Ajouter un compte`.

La première fois seulement : si aucun coffre n'est encore configuré —
`kdbx.path` est vide dans la configuration livrée — le menu demande avant
tout le reste s'il faut créer un nouveau `.kdbx` ou en désigner un déjà
présent sur disque. La création demande son chemin (par défaut
`private/erplibre.kdbx`), puis le mot de passe du coffre, saisi deux fois ;
deux saisies différentes annulent l'ajout du compte, et répondre `[0]`
aussi. Désigner un coffre existant ne demande que son chemin. Une fois le
chemin enregistré, la question ne revient plus.

Ensuite, les questions, dans l'ordre :

1. **Nom court du compte** — devient à la fois le nom de dossier sous
   `~/.erplibre/mail/` et la référence dans le coffre : il ne peut donc pas
   contenir `/` ni commencer par un point.
2. **Adresse courriel**.
3. **Nom affiché** (facultatif) — apparaît dans l'en-tête `De :` comme
   `Nom affiché <email>`.
4. **Fournisseur** — un numéro dans la liste affichée : Gmail,
   Outlook.com (personnel), Microsoft 365 (organisation), iCloud, ou
   « Serveur standard » (IMAP/SMTP générique). Les deux entrées Microsoft
   partagent leur hôte IMAP et pas leur hôte d'envoi : se tromper d'entrée
   relève le courrier et échoue à l'envoi.
5. Si vous choisissez « Serveur standard », le **serveur IMAP** puis le
   **serveur SMTP** sont demandés ensuite ; les autres préréglages les
   remplissent déjà pour vous.
6. La note du préréglage s'affiche ici — ce que le fournisseur attend, et
   ce qu'il n'accepte plus.
7. **Authentification**, demandée seulement là où il y a un choix : Gmail
   prend un mot de passe d'application ou OAuth, les préréglages Microsoft
   seulement OAuth, iCloud seulement un mot de passe d'application.
8. **Le secret** — mot de passe d'application ou jeton de
   rafraîchissement, saisi masqué (`getpass`), puis rangé dans le coffre —
   jamais écrit dans `accounts.json`.

Où va le mot de passe : à l'étape du mot de passe, le client passe par le
**gestionnaire KDBX** partagé du CLI — le même que pour la clé OpenAI et
les identifiants Odoo. Il lit `kdbx.path` / `kdbx.password` dans la
configuration TODO (`script/todo/todo.json`, surchargeable dans
`private/todo/todo_override.json` / `private/todo/todo_override_private.json`).
Si `kdbx.path` n'est pas encore réglé, le menu le demande en texte, comme
décrit plus haut — aucun affichage graphique nécessaire, donc utilisable en
SSH et en conteneur. `[1]` crée un nouveau `.kdbx` au chemin donné
(`private/.gitignore` ignore déjà `*.kdbx`), `[2]` en adopte un déjà
présent sur disque, `[0]` annule sans rien écrire. Le chemin est inscrit
dans `private/todo/todo_override_private.json`, le seul de ces trois
fichiers que git ignore : la question n'est posée qu'une fois, et le TUI
pose la même avec `n`, avant son propre formulaire. Un coffre que le menu
vient de créer est rouvert pour y écrire ce premier secret : son mot de
passe maître est donc redemandé une fois. Régler `kdbx.path` (et
`kdbx.password`, pour éviter l'invite du mot de passe du coffre) d'avance
ne fait qu'éviter ces questions — c'est un raccourci, pas un préalable. Le
trousseau système ne sert que pour un compte dont la `secret_ref` le
désigne déjà — le menu écrit toujours les nouveaux comptes dans le coffre
KDBX.

`accounts.json` (dans `~/.erplibre/mail/accounts.json`) ne contient jamais
qu'une `secret_ref` du genre `kdbx:ERPLibre/Mail/perso` — une référence,
jamais le secret. Il est sans danger à lire, à éditer à la main, ou à
mettre dans une sauvegarde privée.

<!-- [en] -->
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

<!-- [fr] -->
## Les trois modes de cache

Chaque compte garde un cache local — une petite base SQLite plus un fichier
par message téléchargé — pour que la boîte de réception reste lisible hors
ligne. Trois modes contrôlent ce que ce cache laisse sur le disque :

| Mode | Ce qui reste sur le disque | Clé de chiffrement |
|---|---|---|
| `clear` (par défaut) | `~/.erplibre/mail/<compte>/cache.db` et les fichiers `.eml`, lisibles en clair | aucune |
| `encrypted` | même emplacement, mais l'expéditeur, les destinataires, le sujet, l'extrait, le Message-ID et le corps des messages sont scellés en AES-256-GCM à partir du changement de mode (voir plus bas) | générée une fois, rangée dans le coffre à côté du mot de passe (`.../cache-key`) |
| `ephemeral` | sous `/dev/shm/erplibre-mail-<pid>/<compte>/` (ou le dossier temporaire système si `/dev/shm` n'est pas inscriptible), scellé comme `encrypted` | tirée en RAM à chaque lancement, jamais écrite nulle part, et tout le dossier est effacé à la fermeture de la session |

Même en mode `encrypted` ou `ephemeral`, les champs techniques dont le SQL
a besoin pour trier et filtrer restent en clair : UID, nom de dossier,
date, drapeaux et taille, ainsi que les empreintes de Message-ID qui
reconstituent les fils — des empreintes salées par la clé du cache, qui
relient deux messages sans nommer ni l'un ni l'autre. Le scellement couvre
ce qui identifie des personnes : expéditeur, destinataires, sujet, extrait,
Message-ID, corps du message, et les messages en attente d'envoi jusqu'à la
raison de leur échec. Le client ne construit pas d'index plein texte pour
un cache scellé : la recherche y déchiffre ligne à ligne (voir Recherche).

**Changer de mode ne revient pas sur ce qui est déjà écrit.** Un mode ne
vaut que pour les écritures qui le suivent. Une fois le compte passé en
`encrypted`, les lignes écrites en `clear` gardent leur enveloppe en clair,
et les fichiers `.eml` déjà téléchargés restent sur le disque — plus relus,
pas effacés non plus. L'index plein texte fait exception : il est supprimé
quand le compte quitte le mode `clear`, parce qu'il tient à découvert les
sujets et les extraits que les lignes scellées protègent, et il se
reconstruit depuis le cache si le compte y revient. Pour repartir scellé,
effacez le dossier de cache du compte (`~/.erplibre/mail/<compte>/`), puis
resynchronisez — tout revient sous la clé.

Réglez le **défaut général** dans `Courriel > [4] Cache > [1] Mode de cache
par défaut` ; c'est la préférence `mail_cache_mode` (défaut `clear`).
**Surchargez-le par compte** dans `Courriel > [4] Cache > [2] Mode de cache
d'un compte` — ceci écrit le champ `cache_mode` du compte dans
`accounts.json` ; le laisser à `null` là-bas veut dire « hérite du défaut
général ».

`Courriel > [4] Cache > [3] Taille du cache et purge` liste le mode
effectif et l'espace disque de chaque compte, et vide les messages, les
dossiers et les fichiers téléchargés d'un compte (après confirmation) — la
prochaine synchronisation les reconstruit à partir de zéro. L'index plein
texte est vidé avec eux : rien ne continue de répondre pour des messages
qui ne sont plus là. Le fichier `cache.db` lui-même reste, et avec lui ce
qui attend dans la file d'envoi.

<!-- [en] -->
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

<!-- [fr] -->
## Le TUI

`Courriel > [1] Ouvrir le client courriel (TUI)` ouvre un écran en trois
volets : l'arbre comptes/dossiers à gauche, la liste des messages au
centre, et un aperçu à droite, avec une ligne de statut en bas.

| Touche | Action |
|---|---|
| `↑` `↓` `Tab` | se déplacer dans un volet / changer de volet (comportement par défaut de Textual) |
| `h` | ouvre la fenêtre d'aide : les raccourcis de l'écran principal et quelques repères — pas les touches propres aux fenêtres d'écriture, de dossiers et de statistiques ; fermée par `Échap` |
| `z` | plein écran sur l'aperçu (masque l'arbre et la liste) |
| `Échap` | quitter le plein écran |
| `v` | change de disposition : colonnes, partagée, empilée |
| `+` / `-` | agrandir / rétrécir le volet qui a le focus |
| `0` | revenir aux tailles de volets par défaut |
| `r` | synchronise le compte du dossier actuellement sélectionné (tous ses dossiers) |
| `Shift+R` | synchronise tous les comptes |
| `/` | ouvre le champ de recherche : cherche dans tout le cache du dossier ouvert — et non dans les seuls messages affichés — sur sujet/de/à/extrait (voir « Recherche ») |
| `Shift+S` | pose la même recherche au **serveur**, pour le dossier ouvert (voir « Recherche ») |
| `g` | change de vue de liste : à plat, par fil, non lus seulement (voir « Vues de la liste ») |
| `x` | cocher / décocher le message sous le curseur (voir « Agir sur plusieurs ») |
| `s` / `u` | marquer le message sélectionné lu / non lu |
| `*` | suivre / ne plus suivre le message — l'étoile des autres clients |
| `Shift+M` | marquer lu tout le dossier ouvert (demande confirmation) |
| `d` | déplacer le message sélectionné vers la corbeille du compte |
| `m` | ranger le message sélectionné dans un dossier qu'on choisit |
| `D` | vider la corbeille du compte, définitivement |
| `p` | élargir la recherche : dossier, compte, tous les comptes |
| `c` | écrire un nouveau message |
| `a` / `Shift+A` | répondre / répondre à tous |
| `f` | transférer |
| `w` | enregistrer la **première** pièce jointe du message dans `~/Téléchargements` (créé s'il n'existe pas) |
| `o` | ouvre la file d'envoi : ce qui attend de partir (voir « La file d'envoi ») |
| `e` | ouvre les règles du courrier entrant du compte courant (voir « Règles du courrier entrant ») |
| `Shift+F` | ouvre l'écran des dossiers : créer, renommer, supprimer (voir « Gérer les dossiers ») |
| `i` | ouvre l'écran de statistiques (voir « Statistiques ») |
| `Shift+I` | ouvre les paramètres du rapport de statistiques du compte courant (voir « Le rapport de statistiques ») |
| `n` | ajouter un compte sans quitter le client |
| `l` | affiche la fin de `~/.erplibre/mail.log` et les erreurs de synchronisation de la session |
| `q` | quitter |

Ce tableau est écrit à la main et peut prendre du retard sur le code ; la
fenêtre `h`, elle, ne le peut pas : elle construit sa liste depuis les
liaisons de l'application à chaque ouverture. En cas de désaccord entre les
deux, c'est elle qui a raison.

Les barres entre les volets se glissent aussi à la souris, et les tailles
sont retenues par disposition.

Les indices de touches du pied d'écran, comme la fenêtre d'aide, suivent la
langue choisie dans le CLI, tout comme l'arbre des comptes, la liste et le
texte d'aperçu.

<!-- [en] -->
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

<!-- [fr] -->
## Écrire un message

`c` ouvre le formulaire : `À`, `Cc`, `Objet`, un champ `Pièces jointes`
(chemins de fichiers séparés par un point-virgule — une virgule est légale
dans un nom de fichier, donc seul `;` sépare les entrées ; le bouton
« Parcourir… » posé à côté du champ ouvre le navigateur de fichiers du CLI,
qui repart du dossier du dernier chemin déjà saisi et ajoute le fichier
choisi), et un corps multi-lignes. `Ctrl+E` envoie le corps vers `$EDITOR`
(ou `nano` si non défini) et le relit ; si l'éditeur manque ou sort en
erreur, le texte de départ est conservé tel quel. `Ctrl+S` (ou le bouton
Envoyer) remet le message ; `Échap` abandonne le brouillon — il n'y a pas
d'enregistrement en brouillon.

`a` (répondre) et `Shift+A` (répondre à tous) préremplissent `À`/`Cc`/
`Objet`/`In-Reply-To`/`References` et citent le message d'origine dans le
corps. `f` (transférer) préremplit l'objet en `Fwd:` et **rattache le
message d'origine** automatiquement, en pièce jointe `message/rfc822` ; le
corps, lui, part vide — écrivez votre propre mot au-dessus du message
joint.

Répondre, répondre à tous et transférer ont tous besoin du corps du message
d'origine — depuis le cache, ou récupéré en direct si le compte est en
ligne ; sans l'un ou l'autre, vous obtenez « Aucun message sélectionné. » /
« Aucun message à transférer. ».

Un message écrit alors que le compte est hors ligne est mis en file au lieu
d'être envoyé : il part à la synchronisation suivante, et la ligne de
statut affiche « hors ligne : message mis en attente, il partira au
retour » (voir « La file d'envoi »). Une fois envoyé, une copie est classée
dans le dossier Envoyés du compte par IMAP ; si ce classement échoue, la
ligne de statut le dit, mais le message est déjà parti — il n'est pas
renvoyé.

L'envoi se fait en arrière-plan : le bouton Envoyer se grise et le
formulaire reste ouvert jusqu'à la réponse du serveur, sans figer le
client. Une réponse (`a` ou `Shift+A`) envoyée alors que le compte est en
ligne marque aussi l'original `\Answered`, dans le cache et sur le serveur,
comme le font les autres clients. Une réponse qui attend dans la file
d'envoi ne le fait pas, un transfert non plus.

<!-- [en] -->
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

<!-- [fr] -->
## Synchronisation

Une passe de synchronisation est incrémentale : seuls les UID supérieurs au
dernier connu sont demandés, le corps des messages n'est jamais téléchargé
pendant une passe (seulement les en-têtes), et les corps sont récupérés à
la demande à l'ouverture d'un message. Ce téléchargement part dans un fil
de travail : l'aperçu montre les en-têtes et *Téléchargement du corps…*
jusqu'à son arrivée, le client reste répondant, et déplacer le curseur
avant qu'il n'arrive le jette au lieu de le peindre par-dessus le message
où l'on est allé. Les drapeaux (lu/non lu, etc.) des messages déjà connus
sont revérifiés à chaque passe, donc un message lu ailleurs apparaît
correctement lu ici aussi.

La synchronisation a lieu :

- **Au lancement** — ouvrir le TUI déclenche une synchronisation de tous
  les comptes en arrière-plan.
- **À la demande** — `r` (compte courant) / `Shift+R` (tous les comptes)
  dans le TUI, ou `Courriel > [3] Synchroniser maintenant` depuis le menu
  CLI (affiche un résumé par compte dans le terminal).
- **Automatiquement, toutes les `mail_refresh_sec` secondes** (défaut 300 =
  5 minutes ; 0 la désactive) — **mais seulement tant que le TUI est
  ouvert**. Fermez-le et la minuterie part avec lui ; rien ne se
  synchronise en arrière-plan ensuite.

Un lien qui meurt est remplacé, pas traîné. Chaque lecture IMAP est bornée
par `mail_timeout_sec` secondes (défaut 30) ; passé ce délai, Python marque
la socket pour de bon et toute lecture suivante échoue aussitôt par
`cannot read from timed out object`, sans rien demander au serveur. Un seul
`LIST` lent — ce qu'une grande boîte chez un gros fournisseur produit —
condamnait le compte pour le reste de la session, chaque passe échouant en
quelques millisecondes sur un lien déjà mort, relancer le client étant le
seul remède et rien ne le disant. Tout échange rouvre désormais le lien
une fois et recommence — la passe comme le rangement, le vidage de la
corbeille, le marquage d'un dossier, une recherche serveur ou la copie
déposée dans *Envoyés*. Monter `mail_timeout_sec` évite la coupure plutôt
que de la réparer ; un serveur qui répond *non* n'est pas un lien mort et
n'est jamais réessayé.

Si le serveur annonce un `UIDVALIDITY` changé pour un dossier (ses UID ne
veulent plus dire ce qu'ils disaient — typiquement après une migration
côté serveur), le cache de ce dossier est purgé et resynchronisé à partir
de zéro automatiquement. La passe nomme les dossiers auxquels elle l'a
fait : le TUI dans sa ligne de statut à la fin de la passe, `Courriel >
[3] Synchroniser maintenant` sous le nom du compte.

### Les serveurs qui rangent par étiquettes

Certains fournisseurs ne détiennent un message qu'une fois et font de leurs
dossiers des *vues* sur lui : le même message répond dans la boîte de
réception et dans « tous les messages », sous un UID propre à chacun, et un
drapeau posé sous une étiquette se lit sous l'autre. Synchroniser tous les
dossiers rapporte donc le même message une fois par étiquette — trois vues
d'une boîte de 30 000 messages font 90 000 lignes de cache pour 30 000
courriels.

La passe écarte les vues qui ne redisent qu'un autre dossier, celles que le
serveur marque `\Flagged` (suivis) ou `\Important` : leurs messages sont
tous aussi dans le dossier `\All`, donc rien ne devient inaccessible.
`\All` lui-même est toujours synchronisé — archiver un message lui retire
l'étiquette de la boîte de réception, et il ne vit alors plus que là. Cet
écart n'a lieu **que** si le serveur annonce la capacité `X-GM-EXT-1` :
ailleurs `\All` désigne une archive ordinaire, aux messages distincts, et
un dossier peut porter `\Flagged` et contenir des messages qui ne sont
nulle part d'autre.

Un dossier non synchronisé n'est pas dans le cache, donc il n'apparaît pas
dans l'arbre des dossiers. Ce qui reste est le recoupement entre la boîte de
réception et « tous les messages », qu'aucune règle d'IMAP ne permet de
réduire : seul le `Message-ID` relie les deux.

<!-- [en] -->
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

<!-- [fr] -->
## Où sont les fichiers

| Chemin | Contenu |
|---|---|
| `~/.erplibre/mail/accounts.json` | la liste des comptes — serveurs, préréglages, mode de cache, et une référence `secret_ref` ; jamais un mot de passe (mode 0600) |
| `~/.erplibre/mail/<compte>/cache.db` | le cache SQLite de ce compte (mode 0600, dossier parent 0700) |
| `~/.erplibre/mail/<compte>/<dossier>/<uid>.eml` (ou `.eml.enc` s'il est scellé) | un fichier par corps de message téléchargé |
| `/dev/shm/erplibre-mail-<pid>/<compte>/` | le cache d'un compte `ephemeral` pendant que le processus vit ; effacé à sa sortie (un balayage au démarrage nettoie aussi ce qu'un processus tué aurait laissé) |
| `~/.erplibre/mail/.rules/<compte>/rules.json` | les règles du courrier entrant de ce compte et ses plafonds d'envoi, **en clair** même avec un cache chiffré (mode 0600 ; voir « Règles du courrier entrant ») |
| `~/.erplibre/mail/.rules/<compte>/state.json`, `lock` | l'endroit de la boîte de réception où le moteur des règles s'est arrêté, et le verrou qui empêche deux passes simultanées |
| `~/.erplibre/mail/.rules/<compte>/media/` | les copies des images que porte une réponse (dossier 0700, fichiers 0600) |

<!-- [en] -->
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

<!-- [fr] -->
## Dépannage

Les messages d'erreur qui viennent du paquet courriel lui-même
(`secrets.py`, `store.py`, `crypto.py`, `accounts.py`, `smtp_send.py`,
`imap_transport.py`, `imap_sync.py`) passent par la couche de traduction
du CLI, comme les invites de menu et les libellés du TUI : ils suivent la
langue dans laquelle le CLI tourne.

**« Connexion échouée : ... » en ajoutant ou en testant un compte.**
`Courriel > [2] Comptes > [5] Tester la connexion d'un compte` affiche
l'erreur exacte du serveur puis redemande le mot de passe — jusqu'à 3
tentatives. Le mot de passe dans le coffre n'est écrasé qu'*après* une
connexion réussie, donc une faute de frappe ne détruit jamais un mot de
passe qui fonctionnait. Si le compte est Gmail ou iCloud, vérifiez d'abord
que vous avez utilisé un mot de passe d'application (voir « Prérequis »
plus haut), pas le mot de passe normal du compte ; si c'est un compte
Microsoft, aucun mot de passe ne conviendra — voir la même section. Ouvrir le
TUI lui-même ne relance pas cette demande automatiquement : un compte au
mot de passe refusé porte un ⚠ ; s'il avait déjà synchronisé avec succès,
ses dossiers déjà en cache restent visibles et lisibles, ils cessent
seulement de se rafraîchir — seul un compte tout neuf (rien de
synchronisé encore) n'affiche aucun dossier du tout. Dans tous les cas,
passez par « Tester la connexion d'un compte » pour corriger.

**« le fichier kdbx n'a pas pu être ouvert » en ajoutant un compte.**
Un coffre est alors désigné — l'ajout de compte commence par s'en assurer —
mais il n'a pas pu s'ouvrir : mot de passe du coffre refusé (trois essais,
puis le client renonce ; une saisie vide renonce tout de suite),
`kdbx.password` faux dans la configuration, `pykeepass` absent, ou aucun
terminal pour saisir le mot de passe. Ressaisissez-le, ou réglez
`kdbx.password` pour un lancement sans surveillance. Deux autres refus
appartiennent à cette première question : « Ce fichier n'existe pas : »
(choix `[2]`, rien à ce chemin) et « Les mots de passe ne correspondent
pas. » (choix `[1]`, les deux saisies diffèrent) ; les deux annulent
l'ajout du compte sans rien écrire. Le même message hors de l'ajout de
compte — synchronisation, test de connexion, ouverture du client — veut
dire que `kdbx.path` est vide : ces entrées vont droit au gestionnaire KDBX
partagé, qui ouvre alors une fenêtre de sélection de fichier — l'annuler,
ou tourner sans affichage, laisse le coffre fermé.

**« le trousseau du système écrirait le mot de passe en clair (backend
...) ».**
Le backend actif de `keyring` n'est pas de ceux qu'on sait vraiment
chiffrer — ça arrive en SSH, dans un conteneur, ou sur une machine sans
session graphique, où `keyring` retombe silencieusement sur un fichier en
clair. Le client refuse plutôt que de faire semblant que c'est sûr.
Utilisez le coffre KDBX à la place (voir plus haut), ou lancez-le là où un
vrai trousseau est déverrouillé.

**« Installez textual pour le client courriel (pip). »**
`textual` n'est pas installé. `Courriel > [1] Ouvrir le client courriel
(TUI)` affiche seulement ce message et revient au menu ; tout le reste
(comptes, synchronisation, cache) fonctionne quand même sans lui.

**Le cache d'un dossier signale qu'il a changé (`UIDVALIDITY`).**
Rien à faire — le client purge et resynchronise ce dossier tout seul à la
prochaine synchronisation. La liste des messages se vide puis se remplit
brièvement.

**« cache illisible, purgez-le et resynchronisez : ... ».**
Le `cache.db` du compte est corrompu. `Courriel > [4] Cache > [3] Taille
du cache et purge` peut lui-même échouer à ouvrir ce même fichier cassé ;
le cas échéant, effacez à la main le dossier de cache du compte et
resynchronisez :

<!-- [en] -->
```bash
rm -rf ~/.erplibre/mail/<account>/
```

<!-- [fr] -->
```bash
rm -rf ~/.erplibre/mail/<compte>/
```

<!-- [en] -->
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

<!-- [fr] -->
## Tester contre un vrai serveur

Presque tous les tests courriel passent par un double en mémoire. Un double ne
produit que ce que son auteur avait imaginé — c'est par là que trois bugs de
protocole sont arrivés jusqu'aux utilisateurs. D'où un **bac à sable** : un
vrai serveur IMAP (Twisted) et un vrai serveur SMTP (aiosmtpd), qu'un test
démarre sur un port éphémère de la boucle locale, à qui il parle en vrai TCP,
et qu'il tue en terminant — qu'il réussisse ou qu'il échoue.

Le but n'est pas la conformité. Un serveur poli ne prouve pas grand-chose ;
celui-ci sait **se conduire mal exprès**. Un test déclare les octets exacts
d'un message — en-tête en 8 bits bruts, charset `unknown-8bit` — et peut
couper la connexion ou refuser une commande en pleine synchronisation.
Ajouter une nouvelle méchanceté est une petite sous-classe dans
`test/mail_sandbox.py`, pas un nouveau serveur.

Ces tests tournent avec le reste de la suite : `twisted` et `aiosmtpd`
figurent dans `requirement/erplibre_require-ments.txt`, le fichier même
qu'installent les « Prérequis ». Là où ces deux paquets manquent, tout le
fichier se saute visiblement. Pour ne lancer que ce fichier :

<!-- [common] -->
```bash
.venv.erplibre/bin/python -m unittest discover -s test \
    -p test_mail_live_server.py -v
```

<!-- [en] -->
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

<!-- [fr] -->
Ce qu'il ne couvre **pas**, et ne fera pas semblant de couvrir :

- **`SPECIAL-USE`** — Twisted n'annonce que `IMAP4REV1 NAMESPACE IDLE`. Le bug
  du message classé sous un nom de dossier deviné plutôt que sous celui
  annoncé par le serveur reste donc hors de portée. Implémenter l'extension
  dans le bac à sable ne testerait que notre propre supposition à son sujet —
  précisément l'erreur que ce bac à sable existe pour éviter.
- **Aucune particularité de fournisseur** — les dossiers-étiquettes de Gmail,
  OAuth chez Microsoft, les mots de passe d'application d'Apple : rien de tout
  cela n'est exercé. Le bac à sable est un serveur RFC 3501 ordinaire, pas la
  doublure d'un fournisseur précis.
- **Pas de TLS** — le bac à sable parle en clair sur `127.0.0.1`. Les chemins
  `starttls` et `ssl` ne sont pas exercés ici.
- **Rien ne quitte la machine** — aucun hôte externe, aucun trousseau système,
  aucun `~/.erplibre`, aucun identifiant réel, et jamais un port fixe.

<!-- [en] -->
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
closes the screen. Automatic messages queued by a rule — replies,
reports, forwards and redirects — are marked `[auto]` and carry an expiry;
the pane under the list previews the one whose button has focus, read in
the background so that a large forward never freezes the screen, and names
a forward or a redirect as such (see "Incoming mail rules").

A send that fails keeps the message in the queue and does not block those
behind it. A temporary refusal (a `4xx` code, a network error) is retried
at every pass, without limit. A permanent refusal (`5xx`) is retried up to
three times; after the third, a message written by hand is **held**, never
deleted, with its last error still shown under `o`. Holding a message
stops its attempts sooner — the screen deletes nothing. When the SMTP
server cannot be reached at all, the rest of the queue waits for the next
pass instead of each message waiting out the same connection timeout.

A message that leaves from the queue is filed into the account's Sent
folder, like one sent directly — except a rule's redirect, which is never
filed (see "Forwarding"). If that filing fails, the failure is logged; the
message has left and is not resent.

Queued messages are sealed with the same key as the rest of the cache: an
encrypted cache that left its outgoing mail in the open would protect
everything except what was just written. The reason a send failed is sealed
with them: a server that refuses a message names the recipient it refuses.

<!-- [fr] -->
## La file d'envoi

Un message écrit alors que le compte est hors ligne n'est pas refusé : il
est mis en file. Perdre ce que quelqu'un vient d'écrire parce que le réseau
manque est le pire des trois résultats possibles.

La file part au début de chaque passe de synchronisation, avant la
relecture du serveur : au lancement, par `r` / `Shift+R`, au minuteur
`mail_refresh_sec`, et par `Courriel > [3] Synchroniser maintenant` depuis
le menu CLI. Une passe qui envoie ou qui échoue le dit — le TUI dans sa
ligne de statut pendant la passe, le menu sous le nom du compte. L'ordre
est conservé : deux messages d'un même échange arriveraient sinon inversés.

Deux choses laissent un message en attente : un compte hors ligne ne vide
rien, et un message retenu est sauté. L'état réseau d'un compte est fixé à
l'ouverture du client et rien ne le rouvre ensuite — un compte hors ligne au
lancement, le cas même qui remplit la file, ne la vide qu'au lancement
suivant du client, ou par le menu CLI, qui se reconnecte à chaque appel.

`o` ouvre la file : une ligne d'en-tête compte ce qui attend, puis une
ligne par message, du plus ancien au plus récent — objet, destinataires et,
dès qu'un envoi a échoué, pourquoi il a échoué et combien de tentatives il a
coûtées. Chaque ligne porte à sa **gauche** un bouton qui retient le message
ou le relâche. Un message retenu ne part jamais seul ; seul ce bouton lève
la retenue. `Échap` ferme l'écran. Les messages automatiques mis en file
par une règle — réponses, rapports, transferts et redirections — sont
marqués `[auto]` et portent une échéance ; le volet sous la liste montre
l'aperçu de celui dont le bouton a le focus, lu en arrière-plan pour qu'un
gros transfert ne fige jamais l'écran, et nomme un transfert ou une
redirection comme tels (voir « Règles du courrier entrant »).

Un envoi qui échoue laisse le message en file et n'arrête pas ceux qui le
suivent. Un refus temporaire (code `4xx`, erreur réseau) est retenté à
chaque passe, sans limite. Un refus définitif (`5xx`) est retenté jusqu'à
trois fois ; après le troisième, un message écrit à la main est
**retenu**, jamais supprimé, et sa dernière erreur reste visible sous `o`.
Retenir un message arrête ses tentatives plus tôt — l'écran ne supprime
rien. Quand le serveur SMTP est injoignable, le reste de la file attend la
passe suivante au lieu que chaque message attende à son tour le même délai
de connexion.

Un message qui part de la file est classé dans le dossier Envoyés du
compte, comme un envoi direct — sauf la redirection d'une règle, qui n'y
est jamais classée (voir « La redirection »). Si ce classement échoue,
l'échec est journalisé ; le message est parti et n'est pas renvoyé.

Les messages en attente sont scellés par la même clé que le reste du cache :
un cache chiffré qui laisserait ses envois en clair protégerait tout sauf ce
qu'on vient d'écrire. La raison d'un échec est scellée avec eux : un serveur
qui refuse un message cite le destinataire qu'il refuse.

<!-- [en] -->
## Incoming mail rules

A rule answers incoming mail on its own: when a new message in the inbox
matches its filter, the client sends the rule's reply to the sender. Each
account has its own ordered list of rules. This version runs three kinds
of action: the **custom reply**, the **statistics report** — a custom
reply whose text carries figures computed on the mailbox (see "The
statistics report") — and **forwarding**, which relays the message to other
addresses instead of answering its sender (see "Forwarding"). Any rule can
be tried on a recent message before it acts on a real one (see "Testing a
rule").

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

The editor holds the action type (*Custom reply*, *Statistics report* or
*Forward*), the name, "Rule enabled", "Stop here", the throttle (see
"Safeguards"), the maximum age in hours (48 by default, 1 to 720), the
number of first sends held for approval (1 by default, 1 to 10), the
filter, and a button that opens the action's form — *Custom reply…*,
*Statistics report…* or *Forward…* depending on the type. Changing the type
brings the throttle to the new type's default when it still held the old
one's, and a body still equal to the old type's default text becomes the
new type's; a body written by hand is kept, and becomes a forward's
introduction. What a type does not use — a forward's destinations, a
reply's images — stays while the editor is open and is dropped when the
rule is saved. A rule of a type this version does not know shows its type
greyed out. `Ctrl+S`
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

### Forwarding

A rule of type *Forward* relays a matching message to one or more other
addresses instead of answering its sender. *Forward…* in the editor opens
its form: the mode, the destinations, an optional introduction text and the
*Skip lists and robots* box. `Ctrl+S` returns to the editor, which saves
the rule.

| Mode | What leaves |
|---|---|
| Forward inline (the default) | a new message from this account whose text opens on your introduction and a block of the original's headers — From, Date, To, Cc, Subject — followed by the original text; the original's structure (alternatives, inline images, attachments) is kept |
| Forward as attachment | a new message from this account carrying your introduction, the same block of headers, and the original attached whole as `message.eml` |
| True redirect (message unchanged) | the original message itself, byte for byte, under one `Resent-From` / `Resent-Date` / `Resent-Message-ID` block that names this account |

Forwarding is the recommended mode: the message leaves under this account's
own address, which its server vouches for. A signed or encrypted message
(S/MIME, PGP), or one whose text cannot be rewritten, goes as an attachment
even in inline mode, so that its signature stays verifiable. A true
redirect keeps the sender's From: the original DKIM signature can survive,
since nothing it covers changes, but the sender's SPF fails from our
server, and their DMARC policy passes only if that signature does. A
recipient may then reject the message, and some sending servers refuse a
From that is not the authenticated account. The form shows this warning
while the redirect mode is chosen, and greys out the introduction, which a
redirect does not carry.

**Destinations.** One to ten addresses, added one at a time by *Add* or
`Enter` and taken out by *Remove*. Each is checked as it is added: a plain
address (`carole.regle@example.org`; a quoted or non-ASCII local part is
refused), not this account, not another account configured in the client,
not already listed. A domain with accents is kept in its ASCII form:
`bruno.filtre@filtré.example.net` becomes
`bruno.filtre@xn--filtr-fsa.example.net`. An address typed but not added
keeps the form open. For each message, a destination equal to the original
sender — its From or its `Return-Path` — is dropped, since that person
already has the message; when none is left, the message is logged *no
destination left* and nothing leaves.

The destinations never see one another, and the original sender does not
learn them through "reply all". A forward is one message addressed to
`undisclosed-recipients:;`, the destinations in its envelope alone; a
redirect carries no `Resent-To`. The To, Cc and Bcc of the original never
enter the envelope.

**Headers.** A forward is a new message. Its From is this account, its
subject `Fwd: ` followed by the original subject (left as is when it
already starts so), and its `Reply-To` that of the original — or the
original sender when there is none: a destination who answers reaches the
person who wrote, and a `noreply@example.net` notification reaches the
requester its `Reply-To` names. It carries `Auto-Submitted:
auto-generated`, `X-Auto-Response-Suppress: All` and our `X-Loop` marker,
keeps the original's own `X-Loop` lines so that a third party's loop
detection still works, and has neither `In-Reply-To` nor `References`: it
is not a reply. A redirect removes from the original only `Bcc`,
`Resent-Bcc`, `Return-Path` and `X-ERPLibre-Bcc` — the client's internal
Bcc field, through which a sender would otherwise choose a recipient — and
changes nothing else but line endings, which leave as CRLF, the form SMTP
requires. A `Resent-*` block already present stays, under ours.

**Size.** A message larger than **25 MiB** is not relayed (*message too
large to forward*). The size the server announces is checked before any
download. The whole message is then fetched by `BODY.PEEK[]`, so it stays
unread, and only for a rule that is about to send it.

**Lists and robots.** Forwarding newsletters, alerts and list mail is the
usual purpose of a forward rule, so by default the safeguards that keep a
reply away from automatic, bulk, list and robot mail, and from mail not
addressed to the account, do not apply to it. Ticking *Skip lists and
robots* brings them back, as for a reply. The loop safeguards apply
whatever the box: our own automatic messages and replies to our forwards,
a redirect made by this account that came back, delivery reports,
automatic replies (out of office, acknowledgement), the `X-Loop` marker,
the null sender. So do *authentication failed* — a message probably forged
is not relayed — and *sent by this account*. A forward never requires an
authenticated sender.

**Throttle and residual loop.** "Do not send again" is unticked by default
for a forward: every matching message is relayed. Ticked, it counts from
the last forward of a message from the same sender. Two destinations that
each forward the message back to this account as a new message of their own
are served to each other through it: each return drops its own sender but
reaches the other. The caps bound that loop, and ticking the throttle cuts
it. A destination that redirects the message back is stopped (*already
redirected by this account*), and so is its automatic reply.

**Copies in Sent.** A forward is filed into Sent like an automatic reply.
The copy shows `To: undisclosed-recipients:;` — the destinations are read
in the rule — and stays out of the statistics. A redirect is not filed: its
copy would carry a third party's From and the original's `In-Reply-To`, and
the statistics would count it as an answer. The rules log keeps the trace
of both.

**What a forward rule is not.** It does not replace your mail server's
redirection of a whole mailbox. It runs only while the client or the menu
runs. Beyond 20 sends per pass or 60 per hour (the account's caps, a budget
**shared** with replies and reports), forwards enter the outbox **held**,
wait for a gesture under `o`, and expire after 24 h: mail can then never
leave, with no error visible outside the outbox and the rules log. Each
forward filed into Sent doubles the space the message takes (up to 25 MiB
per message), and an IMAP quota that fills up bounces incoming mail. A
server that accepts some destinations and refuses others reports a
success: the refused ones are lost, and the log says *sent*. To send
everything on, use your mail server's redirection.

### Safeguards

Before a reply leaves, the rule's checks run in this order, and the first
that applies stops it. A message that is not armed for the rule, already
handled by it, or not matched by its filter is passed over silently;
every other stop is written to the rules log (`l`) under the reason shown.

| Reason in the log | The message… |
|---|---|
| too old | was received by the server longer ago than the rule's maximum age — measured on the server's reception date (`INTERNALDATE`), never on the `Date` header the sender writes |
| receive date in the future | carries a reception date more than 10 minutes ahead |
| our own automatic message, or a reply to one | forward only: is a message one of this account's rules sent, or answers (`In-Reply-To`) a message a forward rule sent |
| already redirected by this account | carries a `Resent-From` with this account's address: a redirect made from this account that came back. Every type of rule — so a message redirected by hand from this account and returned is left alone too |
| delivery or non-delivery report | forward only: is a delivery report (`multipart/report`, `message/delivery-status`), or comes from `mailer-daemon` or `postmaster` |
| automatic reply (out of office, acknowledgement) | forward only, whatever *Skip lists and robots*: carries `Auto-Submitted: auto-replied` or `Precedence: auto_reply` |
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
| message too large to forward | forward only: is larger than 25 MiB (see "Forwarding") |
| no destination left | forward only: every destination of the rule was, for this message, the original sender, this account or another configured account |

A forward rule skips *automatic message*, *bulk mail*, *mailing list*,
*automatic replies refused by the sender*, *robot sender* and *not
addressed to this account* unless its *Skip lists and robots* box is
ticked, and never checks *sender not authenticated*. The other rows apply
to it as to a reply; the first four rows added for it apply whatever the
box.

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
messages per pass and **60** per sliding hour, all rules together —
replies, reports and forwards share that budget. Beyond that, they are held
in the outbox and the status line warns
*Automatic send cap reached; the rest is held (o) or skipped (log l).* A held forward keeps
a full copy of the original, so a forward rule that already has **20**
entries in the outbox holds no more: further messages are logged *pass cap
reached* or *hourly cap reached* without being downloaded, and are not
forwarded. Both caps are set under the rule list, or by the `caps` key of
`rules.json` (`{"per_pass": 20, "per_hour": 60}`, whole numbers of at
least 1). The hourly cap is what bounds a short timer: with `mail_refresh_sec` at 30 s,
the cap per pass alone would let 2 400 replies an hour through.

**Holding the first send.** Until a rule has really sent its first
replies — one by default, up to 10 — each new reply waits **held** in the
outbox. `o` previews it: recipient and subject, the first 20 lines of
text, the inline and attached images, and its expiry. *Release* lets it
leave at the next sync pass. Changing the rule's filter or its reply
(format, subject, body, images) — for a forward, its destinations, its mode
or its *Skip lists and robots* box — starts the count again, and a message
still waiting from before the change is dropped rather than sent; renaming,
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
| message to forward: account offline when it must be downloaded | left for the next online pass |
| message to forward: download refused by the server | logged as failed (*unreadable body*), not retried |
| message to forward: larger than 25 MiB once downloaded | skipped (*message too large to forward*) |

A forward or a redirect waits in the outbox like a reply, sealed with its
destinations: a queued redirect keeps its envelope and leaves to those
destinations only. The preview under `o` names the kind of entry — *forward
by a rule*, or *redirect by a rule, original message unchanged*.

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
whether the message matches; the **verdict** — *would reply* (*would
forward* for a forward rule), or the reason
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
this version does not know says so and sends nothing.

**A forward rule** needs the whole message: online it is fetched by
`BODY.PEEK[]` and stays unread; offline it is read from the cache when it is
there. In place of the recipient, the trial shows the mode; the
destinations kept, or *Destinations kept: none*; each destination removed
for this message, with its reason (*original sender*, *this account's
address*, *another configured account's address*); the message's size in
bytes; then *Message that would leave*: for a forward, its From, To,
Reply-To, Subject and Auto-Submitted, and the destinations as Bcc; for a
redirect, `Resent-From` and `Resent-Date`, then the original From, To and
Subject, and *The rest of the message leaves byte for byte.* The text,
attachments and images of the message follow. With no destination kept,
the preview is built addressed to yourself, and says so.

**Send a trial to myself** then sends that same forward — same
`Reply-To`, subject prefixed with `[Trial]` — or that same redirect,
subject unchanged, to the account's own address and to no destination.
When it comes back, every rule stops it: a forward is logged *our own
automatic message, or a reply to one* by a forward rule and *automatic
message* by a reply or a report; a redirect is stopped by every rule as
*already redirected by this account* — or passed over in silence by a rule
that already handled the original, whose `Message-ID` it carries.

### From the CLI menu

`Mail > [6] Incoming mail rules` asks for an account, then offers `[1]`
list the rules (with a summary of each filter, and under a forward rule a
line `→ mode : destinations`), `[2]` enable / disable one,
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
the file is rewritten; a file of a newer format version is refused and left
untouched.

A forward rule keeps its introduction in `body`, its format at `text`, its
subject empty and no image; the destinations — in their sending form,
an accented domain in ASCII — the mode (`inline`, `attachment` or
`redirect`) and the box sit under `options`:

```json
"action": {
  "kind": "forward",
  "format": "text",
  "subject": "",
  "body": "Message received on the rules mailbox.",
  "images": [],
  "options": {
    "targets": ["carole.regle@example.org", "denis.tri@example.org"],
    "mode": "inline",
    "skip_lists": false
  }
}
```

<!-- [fr] -->
## Règles du courrier entrant

Une règle répond seule au courrier entrant : quand un nouveau message de la
boîte de réception correspond à son filtre, le client envoie la réponse de
la règle à l'expéditeur. Chaque compte a sa liste ordonnée de règles. Cette
version exécute trois types d'action : la **réponse personnalisée**, le
**rapport de statistiques** — une réponse personnalisée dont le texte porte
des chiffres calculés sur la boîte (voir « Le rapport de statistiques ») —
et la **redirection**, qui relaie le message vers d'autres adresses au lieu
de répondre à son expéditeur (voir « La redirection »). Toute règle
s'essaie sur un message récent avant d'agir sur un vrai (voir « Tester une
règle »).

### Quand les règles tournent

Les règles tournent juste après la passe de synchronisation d'un compte en
ligne : au lancement, par `r` / `Shift+R`, au minuteur `mail_refresh_sec`
(300 s par défaut), et par `Courriel > [3] Synchroniser maintenant` depuis
le menu CLI. Rien ne tourne quand le client et le menu sont tous deux
fermés : le TUI ouvert, un message reçoit sa réponse en moins de
`mail_refresh_sec`. Seule la boîte de réception est lue : sur un serveur
qui range par étiquettes, le même message est aussi dans « Tous les
messages », et lire les deux y répondrait deux fois.

Une règle n'agit que sur ce qui arrive **après** son activation. L'activer
relève la position de la boîte de réception et l'heure — la règle est
*armée* — et tout ce qui est plus ancien est laissé tel quel : activer une
règle ne répond jamais à un arriéré. La désactiver puis la réactiver la
réarme. Un message déplacé vers la boîte de réception depuis un autre
dossier compte comme une arrivée, mais celui reçu avant l'armement de la
règle, ou depuis plus longtemps que son âge maximal, reste ignoré, et une
même règle ne répond jamais deux fois au même message ; l'essentiel du
reste — courrier de liste, copie reçue en Cci — est arrêté par un
garde-fou ci-dessous.

Un compte en cache `ephemeral` n'exécute aucune règle : le journal qui
garantit « au plus une fois » ne survivrait pas au processus. Quand le
serveur renumérote la boîte de réception (nouvelle `UIDVALIDITY`), toutes
les règles actives sont réarmées à la position courante et la ligne de
statut affiche *Boîte de réception renumérotée : règles réarmées.*

### La liste des règles

`e` ouvre la liste des règles du compte courant : ordre, active, nom, type,
« arrêter ici » et dernier résultat de la règle.

| Touche | Action |
|---|---|
| `n` | nouvelle règle |
| `Entrée` | modifier la règle sous le curseur |
| `Espace` | l'activer / la désactiver |
| `k` / `j` | la monter / la descendre |
| `t` | basculer « arrêter ici » |
| `x` | la supprimer (demande confirmation) |
| `s` | l'essayer sur un message récent de la boîte de réception (voir « Tester une règle ») |
| `l` | le journal des règles : les 200 dernières décisions — date, règle, résultat, raison, expéditeur, sujet |
| `Échap` | fermer |

Sous la table, *Plafond par passe* et *Plafond par heure* règlent les
plafonds d'envoi du compte (voir « Garde-fous »), enregistrés par leur
propre bouton.

Les règles s'appliquent dans l'ordre, et **toutes** s'appliquent : un
message qui correspond à deux règles reçoit deux réponses. Une règle
« arrêter ici » clôt la liste pour ce message dès que son filtre a
correspondu — même si un garde-fou a empêché sa réponse de partir.

L'éditeur porte le type d'action (*Réponse personnalisée*, *Rapport de
statistiques* ou *Redirection*), le nom, « Règle active », « Arrêter ici »,
la limite (voir « Garde-fous »), l'âge maximal en heures (48 par défaut, de
1 à 720), le nombre de premiers envois retenus pour approbation (1 par
défaut, de 1 à 10), le filtre, et un bouton qui ouvre le formulaire de
l'action — *Réponse personnalisée…*, *Rapport de statistiques…* ou
*Redirection…* selon le type. Changer de type ramène la limite au défaut
du nouveau type quand elle valait encore celui de l'ancien, et un corps
resté égal au texte par défaut de l'ancien type prend celui du nouveau ; un
corps écrit à la main est gardé, et devient l'introduction d'une
redirection. Ce qu'un type n'emploie pas — les destinations d'une
redirection, les images d'une réponse — reste tant que l'éditeur est
ouvert et part à l'enregistrement de la règle. Une règle d'un type que
cette version ne connaît pas montre son type grisé. `Ctrl+S` enregistre, `Échap` annule ; un champ qui ne se
valide pas garde la fenêtre ouverte, la raison sur sa ligne d'état.

### Filtres

Un filtre est un arbre. Un groupe est **ET — toutes**, **OU — au moins
une** ou **NON** (exactement un enfant) ; une condition teste un champ. La
racine est un groupe ET, et une racine vide retient tous les messages.
`+ Condition` et `+ Groupe` ajoutent dans le groupe sous le curseur (ou à
côté de la condition qui s'y trouve), `Modifier` ouvre la condition,
`Retirer` enlève le nœud.

| Champ | Testé sur |
|---|---|
| De | l'adresse de l'expéditeur |
| À/Cc | chaque adresse de À et de Cc |
| Sujet | le sujet |
| Corps | le texte du message, téléchargé seulement quand une règle atteint cette condition |

De et À/Cc se testent sur les seules adresses, jamais sur le nom affiché,
que n'importe qui peut écrire. Deux opérations :

- **correspond au motif** — De et À/Cc seulement : un motif à la manière du
  shell comparé à l'adresse entière, jamais sensible à la casse.
  `*@example.net` retient `bruno.filtre@example.net`.
- **contient**, selon l'un de cinq modes : *sans casse ni accents* (le
  défaut : `Désabonnement` contient `desabonnement`), *sensible à la
  casse*, *texte exact* (égal aux blancs près), *mot entier*, ou
  *expression régulière* (syntaxe Python, sensible à la casse sauf si le
  motif commence par `(?i)`, 200 caractères au plus, essayée sur les 10 000
  premiers caractères ; les répétitions imbriquées comme `(a+)+` sont
  refusées, car elles peuvent bloquer une passe). Chaque recherche dispose
  d'une seconde : un motif plus lent sur un message fait échouer la règle
  pour ce message (« expression régulière trop lente » au journal) et ne
  compte jamais comme une non-correspondance.

Un filtre compte au plus 8 niveaux et 64 nœuds, et une valeur au plus 500
caractères. Le corps est récupéré par `BODY.PEEK`, le message reste donc
non lu ; un compte hors ligne à ce moment laisse le message à sa prochaine
passe en ligne.

Sous l'arbre, un aperçu compte combien des 200 derniers messages en cache
de la boîte de réception le filtre retiendrait. Il ne télécharge jamais de
corps : les messages qu'il ne peut trancher sans lui sont comptés comme
inconnus. Le cache ne garde pas Cc, donc une condition À/Cc s'y prévisualise
sur À seulement.

Exemple — une règle qui répond aux partenaires d'un domaine, sauf à leur
liste de diffusion :

```
ET — toutes
├── De correspond au motif *@example.net
└── NON
    └── De contient (texte exact) liste-annonces@example.net
```

Un message de `bruno.filtre@example.net` reçoit la réponse ; un message de
`carole.regle@example.org` ne correspond pas. L'exclusion de la liste est
une ceinture avec les bretelles : un message de `liste-annonces@example.net`
porte `List-Id` et serait de toute façon arrêté par un garde-fou.

### La réponse

*Réponse personnalisée…* ouvre le formulaire de réponse : un format, un
sujet, un corps, des images, et un aperçu recalculé à la frappe.

| Format | Envoyé comme |
|---|---|
| Markdown (HTML et texte) | la source en partie texte, convertie en HTML pour la partie HTML ; le HTML brut de la source n'est pas transmis |
| HTML écrit à la main | votre HTML, plus une partie texte qui en est tirée |
| Texte, images en pièces jointes | du texte seul ; chaque image part en pièce jointe |

Les images (PNG, JPEG, GIF, WebP ; 2 Mio chacune, 5 Mio ensemble) sont
**copiées** dans le dossier des règles à l'ajout, par chemin ou par
*Parcourir…* puis *Ajouter les images* : déplacer ou modifier l'original
ensuite n'y change rien, et une copie altérée après coup est refusée au
lieu d'être envoyée. Dans les deux formats HTML, une image que le corps
nomme — `![Logo](logo.png)` ou `<img src="logo.png">` — part en ligne ;
une image listée que le corps ne nomme pas part en pièce jointe : aucune
ne se perd.

Une image SVG (`.svg`, `.svgz`) est **convertie en PNG** à l'ajout et rangée
sous le même nom terminé par `.png` : le SVG lui-même n'est ni gardé ni
envoyé, les clients courriel courants ne l'affichant pas en ligne et un SVG
pouvant porter du script. Le PNG garde la largeur propre du dessin, ramenée
à 1200 px au plus (600 px quand le dessin n'en donne pas), et demande un
convertisseur — `rsvg-convert`, le module Python `cairosvg`, `inkscape` ou
ImageMagick, essayés dans cet ordre ; sans aucun, le formulaire dit
d'installer `librsvg2-bin`. Un SVG qui renvoie à un fichier ou à une
ressource externe — un `href` ou un `url()` autre que `#…` ou `data:`, un
`@import`, une entité externe — est refusé.

Un sujet vide donne `Auto:` suivi du sujet reçu ; sinon le sujet est votre
texte, où `{subject}` est remplacé par le sujet reçu.

La réponse ne cite rien. Elle part vers l'expéditeur d'enveloppe
(`Return-Path`), ou vers l'adresse De à défaut — jamais vers `Reply-To`,
que le message de l'expéditeur fixe librement. Elle porte
`Auto-Submitted: auto-replied`, `X-Auto-Response-Suppress: All` et un
marqueur `X-Loop`, pour que les autres répondeurs se taisent, ainsi
qu'`In-Reply-To` et `References`, pour rejoindre la conversation. Une copie
est classée dans Envoyés ; l'original n'est pas marqué répondu.

### Le rapport de statistiques

Une règle de type *Rapport de statistiques* répond par une réponse
personnalisée dont le corps est un **gabarit** : le texte que vous écrivez,
dans les trois mêmes formats et avec les mêmes images, où `{{nom}}` est
remplacé par un chiffre calculé sur la boîte de réception du compte. Il dit
à un correspondant combien la boîte est chargée et en combien de temps une
réponse arrive d'ordinaire. *Rapport de statistiques…* ouvre le formulaire
de réponse avec, sous le corps, la liste des variables, une liste
déroulante et *Insérer la variable*, qui écrit `{{nom}}` au curseur.
L'aperçu se calcule sur les vrais chiffres de la boîte mais sans
demandeur : le délai propre au demandeur y vaut `—`, et l'essai (`s`) le
montre pour un vrai expéditeur. Une règle de statistiques neuve commence
par un court corps qui se termine par `{{rapport}}`.

| Variable | Remplacée par |
|---|---|
| `{{rapport}}` | le rapport entier : tableau par jour, tableau par semaine, délai de la boîte, délai du demandeur, date et fuseau |
| `{{rapport_jours}}` | le tableau par jour, avec son titre |
| `{{rapport_semaines}}` | le tableau par semaine ISO, avec son titre ; vide quand le rapport n'a pas de semaines |
| `{{recus_total}}` | les messages reçus sur la période du tableau par jour |
| `{{lus_total}}` | parmi eux, ceux qui sont lus |
| `{{repondus_total}}` | parmi eux, ceux qui sont répondus |
| `{{delai_moyen}}` | le délai moyen de réponse aux propres messages du demandeur |
| `{{delai_moyen_boite}}` | le délai moyen de réponse de la boîte, arrondi |
| `{{demandeur_recus}}` | les messages du demandeur reçus dans la fenêtre des délais |
| `{{demandeur_repondus}}` | parmi eux, ceux qui sont répondus |
| `{{jours}}`, `{{semaines}}`, `{{fenetre_jours}}` | le nombre de jours, de semaines, et de jours de la fenêtre des délais |
| `{{periode_debut}}`, `{{periode_fin}}` | le premier et le dernier jour de la période (`AAAA-MM-JJ` ; le dernier est hier) |
| `{{date_rapport}}` | la date, l'heure et le décalage UTC du rapport |

Les noms s'écrivent tels quels — sensibles à la casse, blancs admis entre
les accolades (`{{ rapport }}`). Les trois premiers sont des **blocs** —
paragraphes et tableaux — et vont sur une ligne à eux ; les autres sont des
valeurs courtes. Une valeur manquante s'affiche `—`. En HTML écrit à la
main, un bloc ne va pas dans une balise, et le sujet n'accepte que les
valeurs courtes ; pour le reste, le sujet se comporte comme celui d'une
réponse personnalisée (`{subject}`, `Auto:` quand il est vide). Un nom
inconnu est refusé à l'enregistrement de la règle, et un `rules.json`
modifié à la main qui en cite un échoue à l'envoi avec *message impossible
à construire*. Une réponse personnalisée, elle, refuse ces noms : les
chiffres ne sortent que par une règle de statistiques et ses garde-fous.

`{{rapport}}` en français (la langue du rapport se règle par `I`, plus
bas) :

```
Activité des 7 derniers jours

Jour        Reçus  Lus  Répondus
2026-10-21      3    3         2
2026-10-22      5    4         3
2026-10-23      2    2         1
2026-10-24      0    0         0
2026-10-25      1    1         0
2026-10-26      6    5         4
2026-10-27      4    3         2
Total          21   18        12

Par semaine ISO (4 dernières)

Semaine   Du          Reçus  Lus  Répondus
2026-W40  2026-09-28     18   17        11
2026-W41  2026-10-05     22   20        14
2026-W42  2026-10-12     15   15         9
2026-W43  2026-10-19     19   16        12
Total                    74   68        46

Délai moyen de réponse de la boîte (30 derniers jours) : 2 h 30 min

Votre délai moyen de réponse (30 derniers jours) : 12 h 35 min (sur 2 délais connus)

Rapport du 2026-10-28 09:12 +0000
Jours et semaines en heure locale (UTC+00:00).
```

Dans les formats HTML, les tableaux sont des tableaux HTML ; en Markdown,
la partie texte les porte comme ci-dessus.

**Ce qui est compté.**

- **Reçus** — les messages de la boîte de réception, datés par la date de
  réception du serveur (`INTERNALDATE`) ; un message mis en cache avant
  que cette date soit enregistrée se rabat sur son en-tête `Date`.
- **Lus** — parmi les messages reçus ce jour-là ou cette semaine-là, ceux
  qui portent `\Seen` *maintenant*. Les trois colonnes d'une ligne parlent
  des mêmes messages : lus et répondus ne dépassent jamais reçus. Les jours
  étant clos et les chiffres figés pour la journée (plus bas), « lus » n'est
  pas un accusé de lecture.
- **Répondus** — le message porte `\Answered`, ou une réponse à ce message
  se trouve dans un dossier Envoyés (celui que le serveur marque `\Sent`,
  ou le dossier Envoyés du compte par son nom). Sans dossier Envoyés, seul
  `\Answered` compte et aucun délai n'est connu.
- **Délai** — de la réception d'un message à sa première réponse datée
  après elle (en-tête `Date` de la réponse). La moyenne de la boîte porte
  sur les messages reçus pendant les *fenêtre* derniers jours clos ; sous
  **5** délais connus, le rapport dit qu'il y en a trop peu pour une
  moyenne, et au-delà la moyenne est arrondie — à 5 minutes sous une heure,
  à 15 minutes sous un jour, à l'heure au-delà. Le délai du demandeur porte
  sur ses propres messages des *fenêtre* derniers jours, exact et sans
  seuil.
- **Périodes** — le tableau par jour porte les *N* derniers jours **clos**,
  jusqu'à hier ; aujourd'hui n'y figure jamais. Le tableau par semaine
  porte les *M* dernières semaines ISO complètes, du lundi au dimanche,
  libellées `AAAA-Wss` avec la date de leur lundi ; la semaine courante en
  est exclue, et le 1er janvier 2027 appartient à `2026-W53`. Les totaux
  sont ceux du tableau par jour. Jours et semaines suivent le fuseau du
  processus (variable `TZ`), que le rapport indique.
- **Exclus partout** — les messages automatiques : la synchronisation
  reconnaît `Auto-Submitted` (toute valeur autre que `no`) et le marqueur
  `X-Loop` d'un client ERPLibre dans tous les dossiers, si bien que nos
  propres réponses automatiques restent dehors même après une recréation
  du cache, comme celles d'un tiers. Un message dont le `Message-ID` est
  déjà arrivé compte une fois : la première copie seulement, et une copie
  ultérieure n'hérite ni de la réponse ni du délai.

**Figé pour la journée.** La partie boîte — tableaux, totaux, délai de la
boîte — est calculée au plus une fois par jour local et par jeu de
réglages, puis relue de `report_snapshot.json` : toutes les demandes d'une
journée voient les mêmes chiffres, même si un message a été lu entre-temps.
La partie du demandeur est calculée à chaque réponse. Les aperçus (`I`, le
formulaire, `i`) calculent en direct.

**Limites connues.** La synchronisation ne relit `\Seen` et `\Answered` que
pour les 500 messages les plus récents de chaque dossier : au-delà, lus et
répondus par drapeau sont ceux du premier téléchargement, d'où le tableau
par semaine borné à 8 semaines. Un message reçu un jour montre, dans la
colonne « lus » de ce jour, son état à la première demande du lendemain :
un expéditeur apprend au mieux, une fois par jour, si son message avait été
lu à ce moment. De petits volumes donnent des comptes quotidiens de 0 ou
1 ; ils décrivent la boîte, comme voulu.

**Qui le reçoit, et quand.** Le rapport part vers l'adresse **De** — celle
que l'authentification garantit et celle que concerne le délai du
demandeur —, jamais vers `Return-Path` ni vers `Reply-To`. Une adresse de
`Return-Path` est tout de même contrôlée comme l'expéditeur : un automate,
ce compte ou un autre compte configuré à cet endroit arrête la réponse, et
`Return-Path: <>` est un expéditeur vide. Le rapport ne porte que des
agrégats et le délai propre au demandeur : ni adresse, ni nom, ni sujet
d'un autre message.

En plus des garde-fous de toute règle, un rapport de statistiques exige un
**expéditeur authentifié**. Le **premier** en-tête `Authentication-Results`
— celui que le serveur de réception ajoute au-dessus — doit porter
`dmarc=pass` avec `header.from` égal au domaine du De, ou `dkim=pass` avec
`header.d`, ou `spf=pass` avec `smtp.mailfrom`, égal à ce domaine ou à l'un
de ses sous-domaines. Sinon, le message est journalisé *expéditeur non
authentifié* et ne reçoit rien. Si votre serveur de réception n'ajoute pas
du tout cet en-tête, le premier vient de l'expéditeur, qui peut y écrire ce
qu'il veut : réglez l'**identifiant du serveur** (`I`, plus bas) sur le nom
que votre serveur écrit avant son premier `;` (par exemple
`mx.example.org`), et le premier en-tête devra alors le nommer. Cela ne
protège que si votre serveur **retire** les `Authentication-Results`
entrants qui portent son identifiant (RFC 8601, section 5) ; sinon un
faussaire écrit cet identifiant, qui est public. Certains serveurs ouvrent
l'en-tête sur un résultat (`spf=pass …`) plutôt que sur un identifiant :
avec eux, un identifiant réglé ne correspond jamais, et l'essai le dit.

La limite d'une règle de statistiques est cochée par défaut avec **1440
minutes** (un jour). Chaque règle de statistiques envoie en plus au plus
**20** rapports par 24 heures glissantes : au-delà, une demande est
journalisée *plafond quotidien du rapport atteint*, rien n'est mis en file,
et le plafond horaire du compte n'est pas entamé. Les plafonds du compte et
l'approbation du premier envoi valent comme pour toute règle : le premier
rapport réel attend **retenu** dans la file d'envoi (`o`), avec les
chiffres du moment où il a été construit.

**Paramètres du rapport — `I`.** Dans le client, `I` ouvre les paramètres
du rapport du compte courant : jours du tableau par jour (de 1 à 31, 7 par
défaut), semaines ISO (de 0 à 8, 4 par défaut ; 0 retire le tableau par
semaine), fenêtre des délais en jours (de 1 à 365, 30 par défaut), format
donné aux nouvelles règles de statistiques, langue du rapport (celle de
l'interface, français ou anglais — les libellés du rapport seulement, votre
texte reste tel quel) et identifiant du serveur. Le fuseau est affiché,
non réglable. Dessous, un aperçu de `{{rapport}}` sur la vraie boîte, pour
le demandeur écrit dans son champ — prérempli avec l'expéditeur du message
sélectionné, vide à défaut —, recalculé par *Recalculer l'aperçu* à partir
des champs tels que saisis, avant tout enregistrement. `Ctrl+S`
enregistre, `Échap` ferme. Tant que l'identifiant du serveur est vide, la
fenêtre avertit que tout premier `Authentication-Results` est cru. Les
réglages vivent sous la clé `report` de `rules.json` ; si cette clé est
illisible, les règles de statistiques sont écartées avec un avertissement
et les réponses personnalisées continuent.

### La redirection

Une règle de type *Redirection* relaie un message retenu vers une ou
plusieurs autres adresses au lieu de répondre à son expéditeur.
*Redirection…* dans l'éditeur ouvre son formulaire : le mode, les
destinations, un texte d'introduction facultatif et la case *Ignorer
listes et robots*. `Ctrl+S` revient à l'éditeur, qui enregistre la règle.

| Mode | Ce qui part |
|---|---|
| Transfert dans le corps du message (le défaut) | un nouveau message de ce compte dont le texte s'ouvre sur votre introduction et un bloc des en-têtes de l'original — De, Date, À, Cc, Sujet —, suivis du texte d'origine ; la structure de l'original (alternatives, images en ligne, pièces jointes) est gardée |
| Transfert en pièce jointe | un nouveau message de ce compte qui porte votre introduction, le même bloc d'en-têtes, et l'original joint en entier sous `message.eml` |
| Vraie redirection (message inchangé) | le message d'origine lui-même, octet pour octet, sous un bloc `Resent-From` / `Resent-Date` / `Resent-Message-ID` qui nomme ce compte |

Le transfert est le mode conseillé : le message part sous l'adresse même de
ce compte, que son serveur garantit. Un message signé ou chiffré (S/MIME,
PGP), ou dont le texte ne peut pas être réécrit, part en pièce jointe même
en mode « dans le corps », pour que sa signature reste vérifiable. Une
vraie redirection garde le De de l'expéditeur : la signature DKIM d'origine
peut survivre, rien de ce qu'elle couvre ne changeant, mais le SPF de
l'expéditeur échoue depuis notre serveur, et sa politique DMARC ne passe que
si cette signature passe. Le destinataire peut alors rejeter le message, et
certains serveurs d'envoi refusent un De qui n'est pas le compte
authentifié. Le formulaire affiche cet avertissement tant que le mode
redirection est choisi, et grise l'introduction, qu'une redirection ne
porte pas.

**Destinations.** De une à dix adresses, ajoutées une à une par *Ajouter*
ou `Entrée` et retirées par *Retirer*. Chacune est contrôlée à l'ajout :
une adresse simple (`carole.regle@example.org` ; une partie locale entre
guillemets ou non ASCII est refusée), pas ce compte, pas un autre compte
configuré dans le client, pas déjà dans la liste. Un domaine accentué est
gardé sous sa forme ASCII : `bruno.filtre@filtré.example.net` devient
`bruno.filtre@xn--filtr-fsa.example.net`. Une adresse saisie mais pas
ajoutée garde le formulaire ouvert. Pour chaque message, une destination
égale à l'expéditeur d'origine — son De ou son `Return-Path` — est retirée,
cette personne ayant déjà le message ; quand il n'en reste aucune, le
message est journalisé *aucune destination restante* et rien ne part.

Les destinations ne se voient jamais entre elles, et l'expéditeur d'origine
ne les apprend pas par « répondre à tous ». Un transfert est un seul
message adressé à `undisclosed-recipients:;`, les destinations dans son
enveloppe seulement ; une redirection ne porte pas de `Resent-To`. Les À,
Cc et Cci de l'original n'entrent jamais dans l'enveloppe.

**En-têtes.** Un transfert est un nouveau message. Son De est ce compte,
son sujet `Fwd: ` suivi du sujet d'origine (laissé tel quel s'il commence
déjà ainsi), et son `Reply-To` celui de l'original — ou l'expéditeur
d'origine à défaut : une destination qui répond joint la personne qui a
écrit, et une notification de `noreply@example.net` joint le demandeur que
nomme son `Reply-To`. Il porte `Auto-Submitted: auto-generated`,
`X-Auto-Response-Suppress: All` et notre marqueur `X-Loop`, garde les
lignes `X-Loop` propres à l'original pour que la détection de boucle d'un
tiers fonctionne encore, et n'a ni `In-Reply-To` ni `References` : ce n'est
pas une réponse. Une redirection ne retire de l'original que `Bcc`,
`Resent-Bcc`, `Return-Path` et `X-ERPLibre-Bcc` — le champ Cci interne du
client, par lequel un expéditeur choisirait sinon un destinataire — et ne
change rien d'autre que les fins de ligne, qui partent en CRLF, la forme
qu'exige SMTP. Un bloc `Resent-*` déjà présent reste, sous le nôtre.

**Taille.** Un message de plus de **25 Mio** n'est pas relayé (*message
trop gros pour être transféré*). La taille qu'annonce le serveur est
contrôlée avant tout téléchargement. Le message entier est ensuite lu par
`BODY.PEEK[]`, il reste donc non lu, et seulement pour une règle sur le
point de l'envoyer.

**Listes et robots.** Transférer infolettres, alertes et courrier de liste
est l'usage ordinaire d'une règle de redirection : par défaut, les
garde-fous qui tiennent une réponse à l'écart du courrier automatique, de
masse, de liste et d'automate, et du courrier non adressé au compte, ne s'y
appliquent pas. Cocher *Ignorer listes et robots* les rétablit, comme pour
une réponse. Les garde-fous anti-boucle s'appliquent quelle que soit la
case : nos propres envois automatiques et les réponses à nos transferts,
une redirection faite par ce compte et revenue, les rapports de remise, les
réponses automatiques (absence, accusé de réception), le marqueur `X-Loop`,
l'expéditeur vide. De même *authentification en échec* — un message
probablement usurpé n'est pas relayé — et *envoyé par ce compte*. Une
redirection n'exige jamais d'expéditeur authentifié.

**Limite et boucle résiduelle.** « Ne pas renvoyer » est décochée par
défaut pour une redirection : chaque message retenu est relayé. Cochée,
elle compte depuis le dernier transfert d'un message du même expéditeur.
Deux destinations qui renvoient chacune le message à ce compte sous la
forme d'un message neuf à elles se le servent l'une à l'autre par son
intermédiaire : chaque retour retire son propre expéditeur mais atteint
l'autre. Les plafonds bornent cette boucle, et cocher la limite la coupe.
Une destination qui redirige le message en retour est arrêtée (*déjà
redirigé par ce compte*), de même que sa réponse automatique.

**Copies dans Envoyés.** Un transfert est classé dans Envoyés comme une
réponse automatique. La copie montre `To: undisclosed-recipients:;` — les
destinations se lisent dans la règle — et reste hors des statistiques. Une
redirection n'est pas classée : sa copie porterait le De d'un tiers et
l'`In-Reply-To` de l'original, et les statistiques la compteraient comme
une réponse. Le journal des règles garde la trace des deux.

**Ce qu'une règle de redirection n'est pas.** Elle ne remplace pas la
redirection de toute une boîte par votre serveur de courrier. Elle ne
tourne que pendant que le client ou le menu tourne. Au-delà de 20 envois
par passe ou de 60 par heure (les plafonds du compte, un budget **partagé**
avec les réponses et les rapports), les transferts entrent **retenus** dans
la file d'envoi, attendent un geste sous `o`, et expirent après 24 h : du
courrier peut alors ne jamais partir, sans erreur visible hors la file et
le journal. Chaque transfert classé dans Envoyés double l'espace qu'occupe
le message (jusqu'à 25 Mio par message), et un quota IMAP plein fait
rebondir le courrier entrant. Un serveur qui accepte certaines destinations
et en refuse d'autres annonce un succès : les refusées sont perdues, et le
journal dit *envoyé*. Pour tout faire suivre, la redirection de votre
serveur de courrier est conseillée.

### Garde-fous

Avant qu'une réponse parte, les contrôles de la règle s'exécutent dans cet
ordre, et le premier qui s'applique l'arrête. Un message que la règle n'a
pas armé, qu'elle a déjà traité, ou que son filtre ne retient pas est
passé en silence ; tout autre arrêt est inscrit au journal des règles (`l`)
sous la raison indiquée.

| Raison au journal | Le message… |
|---|---|
| trop vieux | a été reçu par le serveur depuis plus longtemps que l'âge maximal de la règle — mesuré sur la date de réception du serveur (`INTERNALDATE`), jamais sur l'en-tête `Date` qu'écrit l'expéditeur |
| date de réception dans le futur | porte une date de réception de plus de 10 minutes en avance |
| notre propre envoi automatique, ou une réponse à l'un d'eux | redirection seulement : est un message qu'une règle de ce compte a envoyé, ou répond (`In-Reply-To`) à un message qu'une règle de redirection a envoyé |
| déjà redirigé par ce compte | porte un `Resent-From` à l'adresse de ce compte : une redirection faite depuis ce compte et revenue. Tout type de règle — un message redirigé à la main depuis ce compte et revenu est donc lui aussi laissé tel quel |
| rapport de remise ou de non-remise | redirection seulement : est un rapport de remise (`multipart/report`, `message/delivery-status`), ou vient de `mailer-daemon` ou de `postmaster` |
| réponse automatique (absence, accusé de réception) | redirection seulement, quelle que soit *Ignorer listes et robots* : porte `Auto-Submitted: auto-replied` ou `Precedence: auto_reply` |
| message automatique | porte `Auto-Submitted` avec toute valeur autre que `no` |
| envoi de masse | porte `Precedence: bulk`, `list`, `junk` ou `auto_reply` |
| liste de diffusion | porte `List-Id` ou `List-Unsubscribe` |
| réponses automatiques refusées par l'expéditeur | porte `X-Auto-Response-Suppress` avec `All`, `OOF` ou `AutoReply` |
| boucle détectée | porte le marqueur `X-Loop` d'un client ERPLibre — un autre de vos comptes compris |
| pourriel | porte `X-Spam-Flag: yes` |
| expéditeur vide | a un expéditeur d'enveloppe vide (`Return-Path: <>`), comme un rebond |
| aucune adresse de réponse | n'a aucune adresse à qui répondre, ou un De qui en nomme plusieurs |
| expéditeur automate | vient de `mailer-daemon`, `postmaster`, `no-reply`, d'une adresse de rebond… |
| envoyé par ce compte | vient de l'adresse même de ce compte |
| autre compte configuré | vient d'un autre compte configuré dans le client |
| non adressé à ce compte | ne nomme ce compte ni dans À ni dans Cc — une copie en Cci, une liste, un alias |
| authentification en échec | est marqué `dmarc=fail`, ou `spf=fail` sans `dkim=pass`, par l'`Authentication-Results` du serveur de réception : répondre enverrait notre réponse à la personne dont l'adresse a été usurpée |
| expéditeur non authentifié | rapport de statistiques seulement : ne porte aucun premier `Authentication-Results` qui authentifie le domaine du De (voir « Le rapport de statistiques ») |
| limité | vient d'un expéditeur auquel cette règle a répondu récemment (ci-dessous) |
| message trop gros pour être transféré | redirection seulement : dépasse 25 Mio (voir « La redirection ») |
| aucune destination restante | redirection seulement : chaque destination de la règle était, pour ce message, l'expéditeur d'origine, ce compte ou un autre compte configuré |

Une règle de redirection saute *message automatique*, *envoi de masse*,
*liste de diffusion*, *réponses automatiques refusées par l'expéditeur*,
*expéditeur automate* et *non adressé à ce compte* tant que sa case
*Ignorer listes et robots* n'est pas cochée, et ne contrôle jamais
*expéditeur non authentifié*. Les autres lignes s'y appliquent comme à une
réponse ; les quatre premières lignes ajoutées pour elle s'appliquent
quelle que soit la case.

**Ne pas renvoyer si message reçu à l'intérieur de N minutes.** Case
cochée, un message ne reçoit pas de réponse si le dernier envoi de cette
règle au même expéditeur — même adresse De, ou même adresse de réponse — a
moins de N minutes. La mesure part du dernier **envoi**, pas du dernier
message reçu, et une réponse qui attend dans la file d'envoi compte comme
un envoi. La case est cochée par défaut avec 10080 minutes (7 jours) ;
décochée, chaque message reçoit sa réponse, les autres garde-fous mis à
part. Avec 60 minutes : `carole.regle@example.org` écrit à 9 h 00 et reçoit
la réponse à 9 h 00 ; elle réécrit à 9 h 40 — *limité*, 40 minutes après le
dernier envoi ; elle écrit à 10 h 05 — réponse, 65 minutes après le dernier
envoi. Le message de 9 h 40 n'a pas relancé le décompte.

**Plafonds.** Quoi que disent les règles, un compte envoie au plus **20**
messages automatiques par passe et **60** par heure glissante, toutes
règles confondues — réponses, rapports et transferts se partagent ce
budget. Au-delà, ils sont retenus dans la file d'envoi et la ligne de statut avertit *Plafond d'envois automatiques
atteint ; le reste est retenu (o) ou ignoré (journal l).* Un transfert retenu garde une copie
entière de l'original : une règle de redirection qui a déjà **20** entrées
dans la file n'en retient plus, et les messages suivants sont journalisés
*plafond de la passe atteint* ou *plafond horaire atteint* sans être
téléchargés, ni transférés. Les deux plafonds se règlent sous la liste
des règles, ou par la clé `caps` de `rules.json`
(`{"per_pass": 20, "per_hour": 60}`, entiers d'au moins 1). C'est le
plafond horaire qui borne un minuteur court : avec `mail_refresh_sec` à
30 s, le seul plafond par passe laisserait passer 2 400 réponses par heure.

**Retenue du premier envoi.** Tant qu'une règle n'a pas réellement envoyé
ses premières réponses — une par défaut, jusqu'à 10 —, chaque nouvelle
réponse attend **retenue** dans la file d'envoi. `o` en montre l'aperçu :
destinataire et sujet, les 20 premières lignes du texte, les images en
ligne et jointes, et son échéance. *Relâcher* la laisse partir à la passe
de synchronisation suivante. Modifier le filtre de la règle ou sa réponse
(format, sujet, corps, images) — pour une redirection, ses destinations, son
mode ou sa case *Ignorer listes et robots* — relance le décompte, et un
message qui attendait depuis avant la modification est retiré au lieu
d'être envoyé ;
renommer la règle, la déplacer ou changer ses limites ne le relance pas.

**Quand le cache est recréé**, le journal qui limite et qui compte part
avec lui. Les réponses sont alors retenues pour approbation jusqu'à ce que
la plus longue limite des règles actives soit écoulée, et la ligne de
statut affiche *Cache recréé : les réponses automatiques attendent votre
approbation (o).*

### Quand une réponse ne peut pas partir

| Situation | Ce qui se passe |
|---|---|
| compte hors ligne | la réponse est mise en file et part à la prochaine passe en ligne |
| refus temporaire du serveur | mise en file ; les autres réponses de la passe aussi, sans réessayer le serveur |
| refus définitif du serveur | journalisée en échec, pas retentée |
| 24 h en file | retirée de la file (*expiré*), retenue ou non |
| règle supprimée ou désactivée entre-temps | retirée (*règle désactivée*) |
| filtre ou réponse de la règle modifiés entre-temps | retirée (*règle modifiée depuis*) |
| trois refus définitifs depuis la file | retirée (*essais épuisés*) |
| image illisible, message impossible à construire | journalisée en échec, pas retentée |
| message à transférer : compte hors ligne quand il faut le télécharger | laissé à la prochaine passe en ligne |
| message à transférer : téléchargement refusé par le serveur | journalisé en échec (*corps illisible*), pas retenté |
| message à transférer : plus de 25 Mio une fois téléchargé | écarté (*message trop gros pour être transféré*) |

Un transfert ou une redirection attend dans la file d'envoi comme une
réponse, scellé avec ses destinations : une redirection en file garde son
enveloppe et ne part que vers ces destinations. L'aperçu sous `o` nomme le
type d'entrée — *transfert d'une règle*, ou *redirection d'une règle,
message d'origine inchangé*.

Le journal `l` de l'écran principal dit, par règle, ce qui a échoué ; le
journal des règles donne le résultat et la raison de chaque message.
`~/.erplibre/mail.log` ne porte jamais ni adresse ni sujet.

Après une passe qui a fait quelque chose, une ligne s'ajoute à la ligne de
statut, par compte ayant des règles actives — par exemple `perso :
réponses automatiques envoyées : 2, en attente d'approbation (o) : 1`. Une
passe qui n'a rien trouvé à faire n'ajoute rien.

Une seule passe à la fois traite un compte, quel que soit le processus —
TUI ou menu. Une autre attend jusqu'à 30 s, puis renonce avec *Règles :
une autre passe est en cours.* ; la passe suivante reprend où elle s'était
arrêtée. Une passe rattrape au plus 200 messages ; les plus anciens sont
ignorés, avec un avertissement.

### Tester une règle

`s` dans la liste des règles essaie la règle sous le curseur sans attendre
un vrai message. Il liste les 50 messages les plus récents de la boîte de
réception en cache ; `Entrée` sur l'un d'eux montre ce que la règle en
ferait, sans rien écrire. En ligne, les en-têtes complets du message
(`Authentication-Results`, `Return-Path`, `List-Id`…) sont lus sur le
serveur, et son corps par `BODY.PEEK` : il reste non lu. Hors ligne,
l'essai travaille sur la ligne du cache — sans Cc ni ces en-têtes —, dit
que le verdict est partiel, et lit le corps dans le cache quand il s'y
trouve ; sans lui, une condition sur le Corps reste inconnue. Il fait de
même en ligne quand le serveur a renuméroté la boîte de réception depuis la
dernière synchronisation : un numéro du cache pourrait alors désigner un
autre message.

Le résultat montre, dans l'ordre : un avertissement quand la règle est
désactivée ; l'arbre du filtre avec l'issue de chaque nœud (✓, ✗, `?` quand
le corps manque) et si le message correspond ; le **verdict** —
*répondrait* (*transférerait* pour une règle de redirection), ou la
raison que donnerait une vraie passe (trop vieux, déjà
traité, envoyé par ce compte…) ; et, s'il diffère, le verdict **pour un
message neuf**, comme si celui-ci venait d'arriver après l'armement de la
règle — armement, âge et « déjà traité » mis à part, les autres garde-fous,
limite comprise, s'appliquent toujours. Quand une réponse serait décidée,
l'essai dit aussi si le moteur la **retiendrait**, et pourquoi : tant
qu'une règle n'a pas réellement envoyé ses premières réponses, chaque
nouvelle est retenue pour relecture — le premier rapport réel l'est
toujours — et se libère dans la file d'envoi (`o`). Un rapport de
statistiques qui a atteint son plafond quotidien n'est pas retenu mais
écarté : le verdict dit alors *plafond quotidien du rapport atteint*, et
rien n'arriverait dans la file d'envoi. Pour un rapport de
statistiques, il montre l'identifiant de serveur lu dans le premier
`Authentication-Results` (ou que le serveur n'en écrit pas), si
l'expéditeur est authentifié, et un avertissement tant qu'aucun
identifiant n'est réglé. Puis le destinataire, le sujet, le texte de la
réponse, ses images et leur rôle, ou l'erreur qui empêche de la construire.

**Envoyer un essai à moi-même** envoie cette réponse à l'adresse même du
compte, sujet préfixé de `[Essai]`, dès que la réponse a pu être construite
— quel que soit le verdict, car on essaie d'ordinaire avec un message à
soi, qu'une vraie passe arrête en *envoyé par ce compte*. Il porte les
mêmes en-têtes de réponse automatique mais ni `In-Reply-To` ni
`References` : il n'entre jamais dans la conversation d'un tiers. Il
n'écrit rien au journal des règles, ne compte dans aucune limite ni aucun
plafond, ne passe pas par la file d'envoi — hors ligne il est refusé et
rien n'est mis en file — et ne marque rien répondu. Il est inscrit comme
message automatique : sa copie dans Envoyés et son arrivée dans la boîte
de réception restent hors des statistiques. À son arrivée, la passe
suivante le journalise *message automatique* pour chaque règle dont le
filtre le retient : cette ligne du journal vient de l'essai, pas d'un
inconnu. Une règle d'un type que cette version ne connaît pas le dit et
n'envoie rien.

**Une règle de redirection** a besoin du message entier : en ligne, il est
lu par `BODY.PEEK[]` et reste non lu ; hors ligne, il est lu dans le cache
quand il s'y trouve. À la place du destinataire, l'essai montre le mode ;
les destinations retenues, ou *Destinations retenues : aucune* ; chaque
destination retirée pour ce message, avec sa raison (*expéditeur
d'origine*, *adresse de ce compte*, *adresse d'un autre compte configuré*) ;
la taille du message en octets ; puis *Message qui partirait* : pour un
transfert, ses De, À, Reply-To, Sujet et Auto-Submitted, et les
destinations en Cci ; pour une redirection, `Resent-From` et
`Resent-Date`, puis les De, À et Sujet d'origine, et *Le reste du message
part octet pour octet.* Suivent le texte, les pièces jointes et les images
du message. Sans destination retenue, l'aperçu est construit adressé à
vous-même, et le dit.

**Envoyer un essai à moi-même** envoie alors ce même transfert — même
`Reply-To`, sujet préfixé de `[Essai]` — ou cette même redirection, sujet
inchangé, à l'adresse même du compte et à aucune destination. À son
retour, toute règle l'arrête : un transfert est journalisé *notre propre
envoi automatique, ou une réponse à l'un d'eux* par une règle de
redirection et *message automatique* par une réponse ou un rapport ; une
redirection est arrêtée par toute règle en *déjà redirigé par ce compte* —
ou passée en silence par une règle qui a déjà traité l'original, dont elle
porte le `Message-ID`.

### Depuis le menu CLI

`Courriel > [6] Règles du courrier entrant` demande un compte, puis propose
`[1]` lister les règles (avec un résumé de chaque filtre, et sous une règle
de redirection une ligne `→ mode : destinations`), `[2]` en
activer / désactiver une, `[3]` en monter ou descendre une, `[4]` en
supprimer une (demande confirmation), `[5]` les 50 dernières lignes du
journal des règles, `[6]` les paramètres du rapport de statistiques, `[7]`
essayer une règle sur un message, `[0]` retour. `[6]` imprime le fuseau,
demande chaque réglage avec sa valeur actuelle pour défaut — `-` vide la
langue ou l'identifiant du serveur —, les enregistre, puis imprime
`{{rapport}}` calculé sur le cache, sans demandeur. `[7]` demande une
règle, ouvre le compte comme `[3] Synchroniser maintenant` — en ligne
quand il le peut, pour les en-têtes complets —, liste les 20 messages les
plus récents de la boîte de réception, imprime pour celui qu'on choisit ce
que montre l'écran `s`, puis propose d'envoyer l'essai à vous-même. Créer
et modifier une règle passent par `e` dans le TUI : un arbre de filtre ne
se saisit pas ligne à ligne. Une règle activée depuis le menu est armée à
sa passe suivante.

### Où vivent les règles

`~/.erplibre/mail/.rules/<compte>/rules.json` porte les règles, les
plafonds et les paramètres du rapport (clé `report`), en mode 0600, **en
clair même quand le cache est chiffré** — la même exposition
qu'`accounts.json`. Il contient les valeurs des filtres (les adresses et
les mots sur lesquels on filtre) et le corps de la réponse. Les images sont
copiées à côté, sous `media/` ; `state.json` retient où le moteur s'est
arrêté dans la boîte de réception, et `report_snapshot.json` (0600) la
partie boîte du rapport du jour — des comptes et un délai, aucune adresse.
Le journal des règles, lui, vit dans le `cache.db` du compte, scellé avec
lui. Les clés que cette version ne connaît pas sont gardées quand le
fichier est réécrit ; un fichier d'une version de format plus récente est
refusé et laissé intact.

Une règle de redirection garde son introduction dans `body`, son format à
`text`, son sujet vide et aucune image ; les destinations — sous leur forme
d'envoi, un domaine accentué en ASCII —, le mode (`inline`, `attachment` ou
`redirect`) et la case vont sous `options` :

```json
"action": {
  "kind": "forward",
  "format": "text",
  "subject": "",
  "body": "Message reçu sur la boîte des règles.",
  "images": [],
  "options": {
    "targets": ["carole.regle@example.org", "denis.tri@example.org"],
    "mode": "inline",
    "skip_lists": false
  }
}
```

<!-- [en] -->
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

<!-- [fr] -->
## Gérer les dossiers

`F` ouvre l'écran des dossiers : `n` crée, `r` renomme, `d` supprime,
`Échap` ferme.

La suppression détruit le dossier **et son contenu sur le serveur**. IMAP
n'a pas de corbeille pour les dossiers : ce qui part ainsi ne revient que
d'une sauvegarde du serveur. Elle demande donc de taper un mot plutôt que
de confirmer — une question fermée se valide par réflexe. Le mot est sans
accent, pour se taper sur n'importe quelle disposition de clavier.

Chaque opération atteint le serveur d'abord, le cache ensuite. S'il refuse,
le cache ne doit pas décrire un état qui n'existe nulle part : un dossier
absent de l'arbre distant et présent dans le nôtre ne se resynchroniserait
jamais. Le renommage emporte les messages et leurs corps, pour que la passe
suivante ne retélécharge pas ce qui est déjà là.

<!-- [en] -->
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

<!-- [fr] -->
## Ranger et jeter un message

`d` déplace le message sélectionné vers la corbeille du compte. Rien n'est
détruit : une corbeille se vide ailleurs, ce qui rend le geste réparable —
et c'est pourquoi il ne demande aucune confirmation.

IMAP n'a pas de verbe que tous les serveurs connaissent : le client copie
le message, marque l'original supprimé, et le retire par `UID EXPUNGE`, qui
NOMME ce qu'il enlève. Un `EXPUNGE` nu emporterait tous les messages marqués
supprimés du dossier, y compris ceux qu'un autre client a marqués :
détruire ce que ce client n'a pas déplacé ne lui appartient pas. Un serveur
qui n'offre pas `UID EXPUNGE` laisse l'original sur place, barré, et la
ligne de statut le dit plutôt que de laisser la vue d'un autre client
passer pour un bogue.

Trois refus, chacun dit sur la ligne de statut : le compte est hors ligne,
le compte n'annonce pas de corbeille — en inventer une créerait un dossier
que personne n'a demandé — ou le message y est déjà. Le cache local n'est
mis à jour qu'après l'accord du serveur : le devancer ferait disparaître de
l'écran un message qui reviendrait à la passe suivante.

`m` range plutôt le message dans un dossier qu'on choisit : il ouvre les
dossiers du compte, les flèches et `Entrée` choisissent, `Échap` renonce.
Le dossier où le message se trouve déjà n'est pas proposé — s'y déplacer ne
ferait rien, et le proposer laisse croire le contraire. C'est un écran à
part, distinct de celui des dossiers sur `F`, qui crée et détruit : mêler
un geste quotidien à des gestes destructeurs met la suppression d'un
dossier à une touche du rangement d'un message.

La liste propose aussi les dossiers des **autres comptes ouverts**, chaque
ligne portant le nom de son compte ; celui du message vient en premier et
n'est pas nommé, puisque c'est là que va la plupart des rangements. Un
compte hors ligne n'est pas proposé du tout — offrir une cible injoignable
ferait échouer le geste après coup, le message déjà relu.

Rien ne relie deux serveurs : un déplacement entre comptes est donc une
autre suite. Le message est relu en entier, déposé chez l'autre par
`APPEND`, et retiré d'ici seulement ensuite. Ses drapeaux et sa date
d'origine voyagent avec lui — sans la date, le serveur d'arrivée
l'horodate à maintenant et il remonte en tête de la boîte comme s'il
venait d'arriver.

Un dépôt accepté ne prouve rien à lui seul. Le client redemande au serveur
d'arrivée si ce dossier contient bien ce `Message-ID`, et seul un oui lui
permet de retirer la source. Tout le reste laisse le message ici et le
dit : un doublon se corrige, un message disparu ne se rattrape pas. La
vérification est `HEADER Message-ID` et non une recherche en texte, sinon
une réponse qui cite l'identifiant dans son `In-Reply-To` passerait pour
le dépôt. Un message sans `Message-ID` n'est donc jamais retiré de sa
source : rien ne permettrait de le reconnaître là-bas.

`D` vide cette corbeille. C'est le seul geste que le client ne sait pas
réparer : IMAP n'a pas de corbeille pour ce qui sort d'une corbeille, et
aucune passe de synchronisation ne le ramène. Il demande donc de TAPER
`supprimer`, pas d'appuyer sur une touche — un geste irréversible ne doit
pas pouvoir s'obtenir par la frappe de trop. `Échap`, un champ vide ou
tout autre mot laissent tout en place.

Le dossier part en entier, et c'est ce qui rend l'`EXPUNGE` nu acceptable
ici là où `move` le refuse : tout ce qui y est marqué supprimé est soit ce
que le client vient de marquer, soit ce qu'un autre client a marqué dans
ce même dossier, que le geste détruit de toute façon. Un message livré
après le relevé des UID n'est pas marqué, et survit.

Le nombre affiché par la confirmation vient du cache, et le dit. Le cache
retarde toujours sur la corbeille — `d` la remplit côté serveur sans rien
y ajouter localement — donc le nombre qui compte est celui annoncé
ensuite : ce que le serveur a réellement retiré.

<!-- [en] -->
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

<!-- [fr] -->
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

<!-- [en] -->
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

<!-- [fr] -->
## Agir sur plusieurs messages

`x` coche le message sous le curseur et descend d'une ligne, de sorte
qu'une rafale de coches est une rafale de frappes. `d`, `m`, `s`, `u` et
`*` agissent alors sur ce qui est coché — et sur le message sous le
curseur quand rien ne l'est, si bien qu'un geste à un seul message ne
coûte jamais une frappe de plus qu'avant. Les lignes cochées portent un
`✓` à côté du point de non-lu et de l'étoile de suivi.

Les messages d'un même dossier partent ensemble — un `COPY`, un retrait
nommé — plutôt qu'un aller-retour chacun. Une recherche élargie mêle des
dossiers et même des comptes dans une seule liste : le lot est donc
regroupé d'après l'endroit où chaque message vit vraiment, jamais supposé.
Un lot qui part vers un autre compte est déposé et confirmé message par
message, rien ne reliant deux serveurs.

`*` sur un lot prend le sens du groupe : il ne retire le suivi que si tout
ce qui est coché l'a déjà. Basculer chacun de son côté rendrait le
résultat imprévisible — un lot mi-suivi s'inverserait sans que rien ne
dise dans quel état il finit.

Ce qui a été traité cesse d'être coché. Le garder viserait la touche
suivante sur des messages déjà partis, dont les UID ne veulent plus rien
dire dans le dossier qu'ils ont quitté.

<!-- [en] -->
## Following a message

`*` flags the selected message, and `*` again unflags it — a toggle rather
than two keys, because a flag is put on and taken off the same message,
unlike read/unread where one often forces the state of a message already
in the other. `\Flagged` is an IMAP system flag, so the phone and the
desktop client show what is flagged here, and the reverse.

The list carries two marks in one column: `●` for unread, `★` for flagged.
Two characters and not one, because a message can be both, and showing a
single mark would lose one of them.

<!-- [fr] -->
## Suivre un message

`*` pose le drapeau « suivi » sur le message sélectionné, et `*` le
retire — une bascule plutôt que deux touches, parce qu'un drapeau se met et
s'ôte sur le même message, contrairement à lu/non lu où l'on veut souvent
forcer l'état d'un message déjà dans l'autre. `\Flagged` est un drapeau
système d'IMAP : le téléphone et le client de bureau montrent ce qui est
suivi ici, et réciproquement.

La liste porte deux marques dans une colonne : `●` pour non lu, `★` pour
suivi. Deux caractères et non un, parce qu'un message peut être les deux et
qu'une marque unique en perdrait une.

<!-- [en] -->
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

<!-- [fr] -->
## Signature

Chaque compte peut porter une signature, réglée depuis `Courriel > Comptes
> Signature d'un compte` — ligne par ligne, une ligne vide terminant la
saisie, et ne rien écrire l'efface. Elle vit dans `accounts.json` : une
signature se lit dans chaque message qui l'emporte, la cacher au coffre ne
protégerait rien.

Elle apparaît dans le formulaire d'écriture, sous ce qu'on écrit et après
le délimiteur `-- ` — deux tirets, une espace, un saut de ligne, la forme
dont les clients se servent pour replier ou griser ce qui suit. Être dans
le formulaire plutôt qu'ajoutée à l'envoi permet de la relire et de la
corriger avant qu'elle parte ; ajoutée au dernier moment, une signature
fausse partirait sans que son auteur l'ait vue.

Une réponse la porte sous le texte cité. Un transfert, non : le message
transféré voyage avec la sienne.

<!-- [en] -->
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

<!-- [fr] -->
## Lire un dossier entier d'un coup

`Shift+M` marque lus tous les messages non lus du dossier ouvert — le geste
qu'appelle une boîte de listes de diffusion, où trois cents non-lus
n'attendent rien de personne. Il demande d'abord, et dit combien : le geste
ne détruit rien, mais rien ne le défait commodément non plus, « rendre non
lus ceux qui l'étaient » n'existant pas une fois la liste de départ perdue.
Une question fermée, pas un mot à taper : exiger un mot ici userait la
vigilance qu'on garde pour ce qui détruit.

Il refuse tant que le compte est hors ligne, et ce n'est pas une facilité :
une passe de synchronisation relit les drapeaux depuis le serveur, donc un
marquage posé sans lui serait défait à la passe suivante, en silence. Le
serveur est prévenu d'abord et le cache suit, de sorte qu'un refus les
laisse dire la même chose.

<!-- [en] -->
## Saving an attachment

`w` saves an attachment of the selected message into `~/Téléchargements`,
creating the folder if needed. With more than one attachment it opens the
list — name, type, size — and `Enter` saves the one you point at; with a
single one it saves without asking, since the question would have a known
answer. It knew only the first one before, and a message carrying three
showed three in the preview while handing over one.

The file name comes from the message, so from anyone: only its base name
is kept and nothing may be written outside the target folder.


<!-- [fr] -->
## Enregistrer une pièce jointe

`w` enregistre une pièce jointe du message sélectionné dans
`~/Téléchargements`, créé au besoin. À partir de deux pièces, il ouvre la
liste — nom, type, taille — et `Entrée` enregistre celle qu'on désigne ;
à une seule, il enregistre sans rien demander, la question ayant une
réponse connue d'avance. Il ne connaissait que la première auparavant, et
un message qui en portait trois en montrait trois dans l'aperçu pour n'en
donner qu'une.

Le nom du fichier vient du message, donc de n'importe qui : on n'en garde
que le nom de base, et rien ne peut s'écrire hors du dossier visé.


<!-- [en] -->
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

<!-- [fr] -->
## Vues de la liste

`g` fait défiler trois vues de la liste des messages :

- **à plat, par date** — celle par défaut ;
- **par fil** — les réponses se placent sous le message auquel elles
  répondent, en retrait, dans l'ordre des dates à l'intérieur du fil. Les
  racines gardent l'ordre de la vue à plat : changer de vue ne rebat donc
  pas toute la liste ;
- **non lus seulement**.

Une réponse dont l'original n'est pas dans la sélection reste visible comme
racine plutôt que de disparaître, et un cache rempli avant l'arrivée des
fils se comporte comme la vue à plat. La liste réserve en permanence la
gouttière de sa barre de défilement, pour que sa largeur ne bouge pas sous
le curseur.

<!-- [en] -->
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

<!-- [fr] -->
## Synchroniser plusieurs comptes

Les comptes se synchronisent de front, quatre à la fois. Chacun a son socket
et son cache verrouillé : une passe qui attend surtout le réseau devient une
seule attente au lieu de plusieurs. Mesuré avec quatre comptes de 0,25 s :
0,26 s contre 1,00 s en série.

Le plafond est volontaire — les fournisseurs refusent une rafale de
connexions simultanées, et au-delà d'une poignée le gain disparaît. Deux
passes ne se chevauchent jamais sur un même compte : un socket imaplib
partagé n'est pas sûr à plusieurs fils. Un compte qui échoue est signalé et
n'arrête pas les autres.

À l'intérieur d'un compte, ses dossiers avancent désormais ensemble eux
aussi, sur trois liens au plus vers le même serveur. Une connexion
`imaplib` n'a qu'un dossier sélectionné à la fois : sur un seul lien, une
boîte de trente dossiers les parcourt un par un, et l'attente est la somme
des trente.

Trois liens, pas plus : les fournisseurs plafonnent le nombre de
connexions qu'un compte peut tenir, et ce plafond est partagé avec les
autres clients de la personne — téléphone, client de bureau — qui gardent
le leur ouvert toute la journée. Les dossiers sont distribués en
tourniquet plutôt qu'en tranches contiguës, parce qu'un LIST les rend
groupés par hiérarchie et que les gros se suivent.

Un fournisseur qui refuse un lien de plus ne coûte aucun dossier : la part
de ce lien revient à celui déjà ouvert, donc le compte se synchronise plus
lentement, jamais moins complètement. Les liens supplémentaires sont
refermés à la fin de chaque passe, quoi qu'il arrive — un compte qui en
laisserait un derrière lui à chaque fois atteindrait la limite du
fournisseur en quelques minutes.

<!-- [en] -->
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

<!-- [fr] -->
## Recherche

`/` cherche dans **tout le cache du dossier ouvert**, et non dans les seuls
messages chargés. Sujet, expéditeur, destinataire et extrait sont comparés.
500 correspondances au plus sont rendues, les plus récentes d'abord.
`Shift+S` va au-delà du cache — voir plus bas.

`p` élargit cette portée, d'une pression à l'autre : le dossier ouvert,
puis tous les dossiers du compte, puis tous les dossiers de tous les
comptes, puis retour au dossier ouvert. La barre d'état nomme la nouvelle
portée à chaque fois — une liste qui s'allongerait en silence se lirait
comme un défaut. L'élargissement reste un geste explicite : en mode
`encrypted`, le faire d'office déchiffrerait à chaque frappe des dossiers
que personne n'a demandés.

Un résultat venu d'ailleurs porte sa provenance, affichée devant son sujet
sous la forme `[Archives]`, ou `[compte/Archives]` s'il vient d'un autre
compte. Ce n'est pas un ornement. Un UID ne désigne rien tout seul — le
même nombre nomme un autre message dans chaque dossier — donc un résultat
qui perdrait la sienne afficherait le corps de son homonyme ici, et `d`,
`m`, `s`, `u` et `w` agiraient sur celui-là. Chacune de ces touches suit
le dossier et le compte du résultat lui-même.

En mode de cache `clear`, un index FTS5 répond en millisecondes et la liste
suit chaque frappe. En mode `encrypted` aucun index n'existe — il stockerait
en clair ce que le cache scelle — et la recherche déchiffre ligne à ligne.
Mesuré sur 200 000 messages : 0,00 s avec index contre 4,4 s en balayage
pour un terme qui ne correspond à rien. La liste cesse donc d'y suivre la
frappe et attend **Entrée**, ce que la barre d'état annonce. Jusqu'à cette
validation, la liste ne filtre que les messages déjà chargés.

Le résultat est le même des deux côtés ; seul le coût change.

`Shift+S` pose la même question au serveur, sur la portée que `p` a
réglée — le dossier ouvert, les dossiers du compte, ou ceux de tous les
comptes. C'est un geste à part, et c'est voulu : étendre à chaque frappe ferait payer un
aller-retour à une recherche qui répond déjà. Ce que le serveur trouve est
téléchargé puis rangé dans le cache : la recherche locale l'affiche aussitôt
et le retrouvera hors ligne. Le serveur regarde les messages entiers,
en-têtes et corps, donc il peut rendre ce que la recherche locale n'aurait
pas rendu — c'est le sens même de chercher plus loin. Un compte hors ligne
le dit plutôt que d'attendre, et un serveur qui refuse dit pourquoi. Sur
une portée élargie, un dossier qui refuse — non sélectionnable, disparu
depuis la dernière passe — n'arrête pas les autres : le nombre de dossiers
restés sans réponse est annoncé à côté de ce qui a été ramené.

<!-- [en] -->
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

<!-- [fr] -->
## Statistiques

`i` dans le client ouvre l'écran de statistiques ; `[5]` dans le menu Courriel
en imprime un résumé texte par compte, sans lancer le client — total, non-lus
et leur part, les quatorze dernières tranches quotidiennes de volume, les cinq
premiers expéditeurs et la médiane des délais de réponse. C'est tout : le
tableau par dossier, les destinataires et le nombre de messages sans date sont
calculés puis jetés, la coupe à quatorze tranches n'est pas annoncée, et le
choix du pas, de la période et de la portée n'appartient qu'à l'écran `i`.
Tout est calculé depuis le cache local : les deux répondent hors ligne, sans
requête réseau ; `[5]` n'ouvre le coffre qu'une fois pour tous les comptes, et
seulement là où un cache est scellé par une clé qui y est rangée — un compte
en `clear` ne se voit jamais demander de mot de passe.

- **Volume** par jour, semaine, mois ou année. Les barres sont normalisées
  sur le maximum de la série, pour que la forme de la distribution reste
  lisible qu'un mois porte douze messages ou douze mille.
- **Par dossier** — nombre, part de non-lus, taille cumulée.
- **Correspondants** — les expéditeurs et destinataires les plus fréquents,
  comptés par adresse en minuscules plutôt que par libellé : une personne qui
  signe de plusieurs façons reste une seule ligne.
- **Délai de réponse** — la médiane entre un message et la réponse qui lui
  répond, reliés par des empreintes de `Message-ID`.

Trois listes déroulantes surmontent les chiffres. Le **pas** (jour, semaine,
mois, année) fixe la largeur d'une barre de l'histogramme : `d`, `w` et `m`
posent les trois premiers, l'année ne s'obtient que par la liste. La
**période** (depuis toujours, 12 derniers mois, 5 dernières années, 30
derniers jours) borne l'histogramme et, avec lui, les totaux, le tableau par
dossier, les correspondants et les délais de réponse ; un dossier que la
période vide reste listé, avec un zéro. La **portée** est tous les dossiers
ou celui qui est ouvert, et `f` la bascule. Touches et listes mènent au même
état : une touche déplace sa liste avec elle.

L'écran s'ouvre sur une **vue d'ensemble calculée en SQL seul** — nombres,
chiffres par dossier et histogramme — donc il apparaît immédiatement même sur
une boîte de plusieurs centaines de milliers de messages. Les correspondants
et les délais de réponse ouvrent chaque colonne scellée : ils ne se calculent
donc que sur **Entrée**, dans un fil de fond, avec une progression. Le pas de
l'histogramme se choisit d'après l'étendue réelle de ce qui est compté — la
période et la portée choisies —, pour ne jamais dépasser 180 barres : dix ans
d'archives se lisent par mois, vingt ans par année plutôt qu'en sept mille
barres quotidiennes. Seules les tranches les
plus récentes sont listées — les totaux au-dessus, eux, comptent toutes les
tranches de la période, et l'écran annonce combien il en a laissées.

En tête de l'écran, une section d'**activité** donne le tableau par jour de
la boîte de réception du rapport de statistiques : reçus, lus et répondus
pour chacun des *N* derniers jours clos, *N* étant les jours des paramètres
du rapport (`I`, 7 par défaut), avec leur total. Elle compte exactement
comme le rapport (voir « Le rapport de statistiques ») et ignore le pas, la
période et la portée choisis plus bas, ce que dit son titre. Elle est
calculée une fois à l'ouverture de l'écran, en SQL seul, sans ouvrir de
colonne scellée.

<!-- [en] -->
Two figures are honest about what they cannot know:

- **Messages with no readable date** are excluded from the histogram and
  counted on their own line. Filing them under 1 January 1970 would draw a
  spike that never happened.
- **Reply delays need the thread columns**, added with the v2 cache. Messages
  synchronised before that carry nothing to join, and the screen says so
  instead of showing a null delay. A full resynchronisation fills them in.

<!-- [fr] -->
Deux chiffres disent honnêtement ce qu'ils ignorent :

- **Les messages sans date lisible** sont exclus de l'histogramme et comptés
  sur leur propre ligne. Les ranger au 1er janvier 1970 dessinerait un pic qui
  n'a jamais eu lieu.
- **Les délais de réponse exigent les colonnes de fil**, apparues avec le
  cache v2. Les messages synchronisés avant ne portent rien à relier, et
  l'écran le dit plutôt que d'afficher un délai nul. Une resynchronisation
  complète les remplit.

<!-- [en] -->
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

<!-- [fr] -->
## S'authentifier par OAuth

Gmail et Microsoft acceptent tous deux OAuth sur IMAP et SMTP ; Microsoft
n'accepte plus rien d'autre. Un compte dit comment il s'authentifie —
`login` ou `oauth` — et le client présente au serveur le secret que cela
désigne, mot de passe ou jeton d'accès.

**Ce que ce dépôt ne livre pas : une identité.** Les points de service et
les portées voyagent avec chaque préréglage, mais le `client_id` est vide.
Un identifiant client enregistré au nom du projet ferait partager à toutes
les installations un seul quota, un seul écran de consentement et une seule
révocation ; celui qui déploie enregistre le sien, une fois, dans la console
du fournisseur. Réglez-le dans la configuration TODO sous
`mail.oauth.<préréglage>.client_id` — écrit dans
`private/todo/todo_override_private.json`, le fichier que git ignore — ou
dans `ERPLIBRE_MAIL_OAUTH_CLIENT_ID` (suffixez `_GMAIL` ou `_OUTLOOK` pour
en poser un par fournisseur). La configuration l'emporte sur
l'environnement. Ajoutez `client_secret` de la même façon si le fournisseur
en exige un ; une application installée n'en a généralement pas besoin.

**Ajouter le compte.** `Courriel > [2] Comptes > [2] Ajouter un compte`
demande quelle authentification employer là où il y a un choix — Gmail
prend les deux, les préréglages Microsoft seulement OAuth, iCloud seulement
un mot de passe d'application. Choisir OAuth propose ensuite deux façons
d'obtenir le jeton, et va droit à la seconde quand aucun `client_id` n'est
configuré :

1. **Autoriser dans le navigateur.** Le client écoute sur un port éphémère
   de 127.0.0.1 — jamais sur toutes les interfaces, ce qui exposerait le
   code d'autorisation au réseau local le temps du parcours — ouvre la page
   de consentement du fournisseur, et attend une redirection. PKCE lie
   l'échange à la demande : le vérificateur ne quitte pas la machine, donc
   un code intercepté ne suffit pas à obtenir un jeton. Une redirection dont
   l'état ne correspond pas à la demande est refusée sans rien échanger.
2. **Coller un jeton de rafraîchissement** obtenu ailleurs — console du
   fournisseur, ou un outil prévu pour cela.

Dans les deux cas le jeton se range au coffre sous sa propre référence, à
côté de l'entrée du mot de passe et non dessus : un compte qui repasse au
mot de passe en a toujours un.

Le formulaire du TUI (`n`) offre le même choix : choisir un préréglage fixe
ce que le compte peut employer — la liste des authentifications n'est
active que là où il y a quelque chose à choisir — et le champ du secret dit
ensuite s'il attend un mot de passe ou un jeton. Un bouton **Autoriser dans
le navigateur** y figure aussi, mais seulement là où un `client_id` est
configuré : sans lui, il ouvrirait une page répondant « invalid_client »,
donc il reste caché plutôt que grisé. Le parcours tourne dans un fil de
travail, sans quoi l'attente de la redirection gèlerait la fenêtre, Échap
compris.

**Ensuite, plus rien à faire.** Un jeton d'accès vit environ une heure ; le
client échange le jeton de rafraîchissement contre un neuf avant d'ouvrir
une session, range le jeu neuf au coffre, et synchronise. L'échange a lieu
dans le fil principal, avant toute passe : écrire au coffre y réécrit le
fichier entier, et deux fils de synchronisation qui écriraient ensemble le
corrompraient.

Une session dure plus longtemps que son jeton : l'échange n'est donc pas
qu'une étape de démarrage. Tout ce qui ouvre une connexion plus tard
redemande le secret et en obtient un rafraîchi — un message en file qui
part des heures après avoir été écrit, par exemple. Et quand le serveur
refuse une passe sur un jeton mort, le client rouvre le lien IMAP une fois
avec un jeton neuf, au lieu de se taire jusqu'à ce qu'on le relance. Une
seule fois, et seulement là où le secret peut changer : représenter le même
mot de passe au même serveur donnerait le même refus, et réessayer sans fin
sur un serveur qui refuse pour une autre raison ferait tourner le client
indéfiniment.

**Quand ça échoue.** Trois issues, distinguées parce que le remède diffère.
Le jeton neuf arrive, et rien n'est dit. L'autorisation est révoquée — le
propriétaire l'a retirée, ou le fournisseur l'a expirée — et aucun nouvel
essai ne la rendra : `Courriel > [2] Comptes > [6] Remplacer le jeton OAuth
d'un compte` offre les deux mêmes voies que l'ajout, et un parcours
abandonné comme une saisie vide n'écrivent rien plutôt que d'effacer ce qui
est là. Ou le fournisseur n'a pas répondu, auquel cas le
jeton en place vaut toujours et la passe suivante réessaie.

<!-- [en] -->
## What the client does not do yet

- **No client identifier** — the browser authorisation flow needs a
  `client_id` you register yourself; without one, an OAuth account is added
  from a token obtained elsewhere (see "Authenticating with OAuth").
- **No headless service** — rules run only while the TUI is open or when
  `Mail > [3] Synchronise now` runs; with both closed, nothing is answered.
- **No `\Answered` from the outbox** — a manual reply marks the original
  answered only when it leaves at once; one that waited in the outbox does
  not.
- **No aliases** — an account knows its own address and login only, so a
  message received through an alias is logged *not addressed to this
  account* and gets no automatic reply.
- **No SMTPUTF8** — a forward destination must have an ASCII local part
  (the domain may carry accents), and a redirected original whose headers
  carry raw UTF-8 leaves as is: a strict server may refuse it.

The design spec is not tracked in this tree; recover it from history with
`git log --all -- "docs/superpowers/specs/*"` if you need what the remaining
phases add.

<!-- [fr] -->
## Ce que le client ne fait pas encore

- **Pas d'identifiant client livré** — le parcours d'autorisation dans le
  navigateur exige un `client_id` que vous enregistrez vous-même ; sans lui,
  un compte OAuth s'ajoute à partir d'un jeton obtenu ailleurs (voir
  « S'authentifier par OAuth »).
- **Pas de service sans interface** — les règles ne tournent que TUI
  ouvert ou pendant `Courriel > [3] Synchroniser maintenant` ; les deux
  fermés, rien ne reçoit de réponse.
- **Pas de `\Answered` depuis la file d'envoi** — une réponse manuelle ne
  marque l'original répondu que si elle part aussitôt ; celle qui a attendu
  dans la file d'envoi ne le fait pas.
- **Pas d'alias** — un compte ne connaît que sa propre adresse et son
  identifiant, donc un message reçu par un alias est journalisé *non
  adressé à ce compte* et ne reçoit pas de réponse automatique.
- **Pas de SMTPUTF8** — une destination de redirection doit avoir une
  partie locale ASCII (le domaine peut porter des accents), et un original
  redirigé dont les en-têtes portent de l'UTF-8 brut part tel quel : un
  serveur strict peut le refuser.

Le devis de conception n'est pas suivi dans cet arbre ; retrouvez-le dans
l'historique par `git log --all -- "docs/superpowers/specs/*"` si vous avez
besoin de ce qu'apportent les phases restantes.
