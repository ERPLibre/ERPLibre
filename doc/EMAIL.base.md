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
| `Shift+F` | ouvre l'écran des dossiers : créer, renommer, supprimer (voir « Gérer les dossiers ») |
| `i` | ouvre l'écran de statistiques (voir « Statistiques ») |
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

<!-- [en] -->
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

<!-- [fr] -->
## Synchronisation

Une passe de synchronisation est incrémentale : seuls les UID supérieurs au
dernier connu sont demandés, le corps des messages n'est jamais téléchargé
pendant une passe (seulement les en-têtes), et les corps sont récupérés à
la demande à l'ouverture d'un message. Les drapeaux (lu/non lu, etc.) des
messages déjà connus sont revérifiés à chaque passe, donc un message lu
ailleurs apparaît correctement lu ici aussi.

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
seul remède et rien ne le disant. La passe rouvre désormais le lien une
fois et recommence. Monter `mail_timeout_sec` évite la coupure plutôt que
de la réparer ; un serveur qui répond *non* n'est pas un lien mort et n'est
jamais réessayé.

Si le serveur annonce un `UIDVALIDITY` changé pour un dossier (ses UID ne
veulent plus dire ce qu'ils disaient — typiquement après une migration
côté serveur), le cache de ce dossier est purgé et resynchronisé à partir
de zéro automatiquement. La passe nomme les dossiers auxquels elle l'a
fait : le TUI dans sa ligne de statut à la fin de la passe, `Courriel >
[3] Synchroniser maintenant` sous le nom du compte.

<!-- [en] -->
## Where the files live

| Path | Contents |
|---|---|
| `~/.erplibre/mail/accounts.json` | account list — servers, presets, cache mode, and a `secret_ref` pointer; never a password (mode 0600) |
| `~/.erplibre/mail/<account>/cache.db` | that account's SQLite cache (mode 0600, parent directory 0700) |
| `~/.erplibre/mail/<account>/<folder>/<uid>.eml` (or `.eml.enc` when sealed) | one file per downloaded message body |
| `/dev/shm/erplibre-mail-<pid>/<account>/` | an `ephemeral` account's cache while the process is alive; removed when it exits (a sweep at every startup also clears directories left behind by a killed process) |

<!-- [fr] -->
## Où sont les fichiers

| Chemin | Contenu |
|---|---|
| `~/.erplibre/mail/accounts.json` | la liste des comptes — serveurs, préréglages, mode de cache, et une référence `secret_ref` ; jamais un mot de passe (mode 0600) |
| `~/.erplibre/mail/<compte>/cache.db` | le cache SQLite de ce compte (mode 0600, dossier parent 0700) |
| `~/.erplibre/mail/<compte>/<dossier>/<uid>.eml` (ou `.eml.enc` s'il est scellé) | un fichier par corps de message téléchargé |
| `/dev/shm/erplibre-mail-<pid>/<compte>/` | le cache d'un compte `ephemeral` pendant que le processus vit ; effacé à sa sortie (un balayage au démarrage nettoie aussi ce qu'un processus tué aurait laissé) |

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
la retenue, jamais un délai qui expire. `Échap` ferme l'écran.

Un envoi qui échoue laisse le message en file et n'arrête pas ceux qui le
suivent. Rien n'abandonne : la passe suivante retente et le compteur monte,
si définitif que soit le refus. Retenir le message est le seul moyen
d'arrêter ces tentatives — l'écran ne supprime rien.

Les messages en attente sont scellés par la même clé que le reste du cache :
un cache chiffré qui laisserait ses envois en clair protégerait tout sauf ce
qu'on vient d'écrire. La raison d'un échec est scellée avec eux : un serveur
qui refuse un message cite le destinataire qu'il refuse.

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

The design spec is not tracked in this tree; recover it from history with
`git log --all -- "docs/superpowers/specs/*"` if you need what the remaining
phases add.

<!-- [fr] -->
## Ce que le client ne fait pas encore

- **Pas d'identifiant client livré** — le parcours d'autorisation dans le
  navigateur exige un `client_id` que vous enregistrez vous-même ; sans lui,
  un compte OAuth s'ajoute à partir d'un jeton obtenu ailleurs (voir
  « S'authentifier par OAuth »).

Le devis de conception n'est pas suivi dans cet arbre ; retrouvez-le dans
l'historique par `git log --all -- "docs/superpowers/specs/*"` si vous avez
besoin de ce qu'apportent les phases restantes.
