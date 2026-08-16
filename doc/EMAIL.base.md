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
### App passwords for Gmail, Outlook and iCloud

Phase 1 speaks plain IMAP/SMTP login only — no OAuth yet (that is phase 2).
Gmail, Outlook and iCloud have all closed that door to the account's real
password, so each of these three presets requires an **app password**
instead:

| Provider | Where to generate it |
|---|---|
| Gmail | Enable 2-step verification, then [myaccount.google.com](https://myaccount.google.com/security) > Security > App passwords |
| Outlook / Microsoft 365 | [account.microsoft.com](https://account.microsoft.com/security) > Security > Advanced security options > App passwords |
| iCloud | [account.apple.com](https://account.apple.com/) > Sign-In and Security > App-Specific Passwords |

Use that generated password when account setup asks for one — never the
account's normal password. The "Standard server" preset (generic IMAP/SMTP)
does not need one.

<!-- [fr] -->
### Mots de passe d'application pour Gmail, Outlook et iCloud

La phase 1 ne parle qu'IMAP/SMTP en authentification simple — pas encore
OAuth (ça, c'est la phase 2). Gmail, Outlook et iCloud ont tous les trois
fermé cette porte au vrai mot de passe du compte : chacun de ces trois
préréglages exige donc un **mot de passe d'application** à la place :

| Fournisseur | Où le générer |
|---|---|
| Gmail | Activez la validation en deux étapes, puis [myaccount.google.com](https://myaccount.google.com/security) > Sécurité > Mots de passe des applications |
| Outlook / Microsoft 365 | [account.microsoft.com](https://account.microsoft.com/security) > Sécurité > Options de sécurité avancées > Mots de passe d'application |
| iCloud | [account.apple.com](https://account.apple.com/) > Connexion et sécurité > Mots de passe spécifiques aux applications |

Utilisez ce mot de passe généré quand la configuration du compte en demande
un — jamais le mot de passe normal du compte. Le préréglage « Serveur
standard » (IMAP/SMTP générique) n'en a pas besoin.

<!-- [en] -->
## Adding an account

Menu path: `TODO > [3] Assistant > [2] Mail - Read and send email > [2]
Accounts > [2] Add an account`.

The prompts, in order:

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
If `kdbx.path` isn't set yet, a graphical file picker pops up asking you to
choose an existing `.kdbx` file — it needs a display, and cancelling it (or
running headless) fails account creation with "le fichier kdbx n'a pas pu
être ouvert" (French — see Troubleshooting). **Set `kdbx.path` (and
`kdbx.password`, to skip the prompt) before adding your first account**,
pointing at a `.kdbx` vault you already have (create one with KeePassXC or
similar). The system keyring is only ever used for an account whose
`secret_ref` already points at one — the menu itself always writes new
accounts into the KDBX vault.

`accounts.json` (at `~/.erplibre/mail/accounts.json`) only ever holds a
`secret_ref` such as `kdbx:ERPLibre/Mail/perso` — a pointer, never the
secret. It is safe to read, edit by hand, or check into a private backup.

<!-- [fr] -->
## Ajouter un compte

Chemin de menu : `TODO > [3] Assistant > [2] Courriel - Lire et envoyer du
courriel > [2] Comptes > [2] Ajouter un compte`.

Les questions, dans l'ordre :

1. **Nom court du compte** — devient à la fois le nom de dossier sous
   `~/.erplibre/mail/` et la référence dans le coffre : il ne peut donc pas
   contenir `/` ni commencer par un point.
2. **Adresse courriel**.
3. **Nom affiché** (facultatif) — apparaît dans l'en-tête `De :` comme
   `Nom affiché <email>`.
4. **Fournisseur** — un numéro dans la liste affichée : Gmail, Outlook,
   iCloud, ou « Serveur standard » (IMAP/SMTP générique).
5. Si vous choisissez « Serveur standard », le **serveur IMAP** puis le
   **serveur SMTP** sont demandés ensuite ; les autres préréglages les
   remplissent déjà pour vous.
6. Si le préréglage exige un mot de passe d'application, sa note s'affiche
   ici en rappel.
7. **Mot de passe** — saisi masqué (`getpass`), puis rangé dans le coffre —
   jamais écrit dans `accounts.json`.

Où va le mot de passe : à l'étape du mot de passe, le client passe par le
**gestionnaire KDBX** partagé du CLI — le même que pour la clé OpenAI et
les identifiants Odoo. Il lit `kdbx.path` / `kdbx.password` dans la
configuration TODO (`script/todo/todo.json`, surchargeable dans
`private/todo/todo_override.json` / `private/todo/todo_override_private.json`).
Si `kdbx.path` n'est pas encore réglé, une fenêtre de sélection de fichier
s'ouvre pour choisir un `.kdbx` existant — il faut un affichage graphique,
et l'annuler (ou lancer le CLI sans affichage) fait échouer la création du
compte avec « le fichier kdbx n'a pas pu être ouvert » (voir Dépannage).
**Réglez `kdbx.path` (et `kdbx.password`, pour éviter l'invite) avant
d'ajouter votre premier compte**, en pointant vers un coffre `.kdbx` que
vous avez déjà (créez-en un avec KeePassXC ou équivalent). Le trousseau
système ne sert que pour un compte dont la `secret_ref` le désigne déjà —
le menu écrit toujours les nouveaux comptes dans le coffre KDBX.

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
| `encrypted` | same location, but sender, recipients, subject, snippet, message-id and message bodies are sealed with AES-256-GCM | generated once, stored in the vault next to the password (`.../cache-key`) |
| `ephemeral` | under `/dev/shm/erplibre-mail-<pid>/<account>/` (or the system temp dir if `/dev/shm` isn't writable), sealed the same way as `encrypted` | generated fresh in RAM at every run, never written anywhere, and the whole directory is removed when the session closes |

Even in `clear` mode, the technical fields the SQL needs to sort and
filter — UID, folder, date, flags, size — are always plain; only the
person-identifying fields (and the message body) are ever sealed, and only
in `encrypted`/`ephemeral`.

Set the **general default** at `Mail > [4] Cache > [1] Default cache mode`;
it is the `mail_cache_mode` preference (default `clear`). **Override it per
account** at `Mail > [4] Cache > [2] Cache mode of one account` — this
writes the account's `cache_mode` field in `accounts.json`; leaving it at
`null` there means "inherit the general default."

`Mail > [4] Cache > [3] Cache size and purge` lists every account's
effective mode and disk usage, and can erase one account's cache entirely
(after confirmation) — the next sync rebuilds it from scratch.

<!-- [fr] -->
## Les trois modes de cache

Chaque compte garde un cache local — une petite base SQLite plus un fichier
par message téléchargé — pour que la boîte de réception reste lisible hors
ligne. Trois modes contrôlent ce que ce cache laisse sur le disque :

| Mode | Ce qui reste sur le disque | Clé de chiffrement |
|---|---|---|
| `clear` (par défaut) | `~/.erplibre/mail/<compte>/cache.db` et les fichiers `.eml`, lisibles en clair | aucune |
| `encrypted` | même emplacement, mais l'expéditeur, les destinataires, le sujet, l'extrait, le Message-ID et le corps des messages sont scellés en AES-256-GCM | générée une fois, rangée dans le coffre à côté du mot de passe (`.../cache-key`) |
| `ephemeral` | sous `/dev/shm/erplibre-mail-<pid>/<compte>/` (ou le dossier temporaire système si `/dev/shm` n'est pas inscriptible), scellé comme `encrypted` | tirée en RAM à chaque lancement, jamais écrite nulle part, et tout le dossier est effacé à la fermeture de la session |

Même en mode `clear`, les champs techniques dont le SQL a besoin pour trier
et filtrer — UID, dossier, date, drapeaux, taille — restent toujours en
clair ; seuls les champs qui identifient des personnes (et le corps du
message) sont scellés, et seulement en `encrypted`/`ephemeral`.

Réglez le **défaut général** dans `Courriel > [4] Cache > [1] Mode de cache
par défaut` ; c'est la préférence `mail_cache_mode` (défaut `clear`).
**Surchargez-le par compte** dans `Courriel > [4] Cache > [2] Mode de cache
d'un compte` — ceci écrit le champ `cache_mode` du compte dans
`accounts.json` ; le laisser à `null` là-bas veut dire « hérite du défaut
général ».

`Courriel > [4] Cache > [3] Taille du cache et purge` liste le mode
effectif et l'espace disque de chaque compte, et peut effacer entièrement le
cache d'un compte (après confirmation) — la prochaine synchronisation le
reconstruit à partir de zéro.

<!-- [en] -->
## The TUI

`Mail > [1] Open the mail client (TUI)` opens a three-pane screen: an
account/folder tree on the left, the message list in the middle, and a
preview pane on the right, with a status line at the bottom.

| Key | Action |
|---|---|
| `↑` `↓` `Tab` | move within a pane / move focus between panes (Textual defaults) |
| `h` | open the help window: every shortcut plus a few notes, closed with `Escape` |
| `z` | toggle full-screen preview (hides the folder tree and the message list) |
| `Escape` | leave full-screen |
| `v` | cycle the layout: columns, split, stacked |
| `+` / `-` | grow / shrink the pane that has focus |
| `0` | back to the default pane sizes |
| `r` | sync the account of the currently selected folder (all its folders) |
| `Shift+R` | sync every account |
| `/` | open the search field (filters the currently visible list only — locally, over subject/from/to/snippet; it does not search the server) |
| `s` / `u` | mark the selected message seen / unseen |
| `c` | compose a new message |
| `a` / `Shift+A` | reply / reply all |
| `f` | forward |
| `w` | save the message's **first** attachment to `~/Téléchargements` (created if missing) |
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
| `h` | ouvre la fenêtre d'aide : tous les raccourcis et quelques repères, fermée par `Échap` |
| `z` | plein écran sur l'aperçu (masque l'arbre et la liste) |
| `Échap` | quitter le plein écran |
| `v` | change de disposition : colonnes, partagée, empilée |
| `+` / `-` | agrandir / rétrécir le volet qui a le focus |
| `0` | revenir aux tailles de volets par défaut |
| `r` | synchronise le compte du dossier actuellement sélectionné (tous ses dossiers) |
| `Shift+R` | synchronise tous les comptes |
| `/` | ouvre le champ de recherche (filtre seulement la liste déjà affichée — localement, sur sujet/de/à/extrait ; ne cherche pas sur le serveur) |
| `s` / `u` | marquer le message sélectionné lu / non lu |
| `c` | écrire un nouveau message |
| `a` / `Shift+A` | répondre / répondre à tous |
| `f` | transférer |
| `w` | enregistrer la **première** pièce jointe du message dans `~/Téléchargements` (créé s'il n'existe pas) |
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
`;` splits entries; there is no file picker, type the paths), and a
multi-line body. `e` sends the body out to `$EDITOR` (or
`nano` if unset) and reads it back; if the editor is missing or exits with
an error, the body you had is kept untouched. `Ctrl+S` (or the Send button)
delivers the message; `Escape` discards the draft — there is no
save-as-draft.

`a` (reply) and `Shift+A` (reply all) prefill `To`/`Cc`/`Subject`/
`In-Reply-To`/`References` and quote the original message in the body. `f`
(forward) prefills the `Fwd:` subject and **attaches the original message**
automatically, as a `message/rfc822` attachment; the body itself starts
empty — write your own note above the attached original.

Reply, reply-all and forward all need the original message's body
available — from the cache, or fetched live if the account is online; with
neither, you get "No message selected." / "No message to forward."

Sending requires the account to be online (composing offline fails with
"Account offline: cannot send." — there is no offline outbox). Once sent, a
copy is filed into the account's Sent folder over IMAP; if that filing step
fails, the status line says so, but the message has already left — it is
not resent.

<!-- [fr] -->
## Écrire un message

`c` ouvre le formulaire : `À`, `Cc`, `Objet`, un champ `Pièces jointes`
(chemins de fichiers séparés par un point-virgule — une virgule est légale
dans un nom de fichier, donc seul `;` sépare les entrées ; il n'y a pas de
sélecteur de fichier, tapez les chemins), et un corps multi-lignes.
`e` envoie le corps vers `$EDITOR` (ou `nano` si non défini) et le relit ;
si l'éditeur manque ou sort en erreur, le texte de départ est conservé tel
quel. `Ctrl+S` (ou le bouton Envoyer) remet le message ; `Échap` abandonne
le brouillon — il n'y a pas d'enregistrement en brouillon.

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

Envoyer exige que le compte soit en ligne (écrire hors ligne échoue avec
« Compte hors ligne : envoi impossible. » — il n'y a pas de file d'attente
hors ligne). Une fois envoyé, une copie est classée dans le dossier
Envoyés du compte par IMAP ; si ce classement échoue, la ligne de statut le
dit, mais le message est déjà parti — il n'est pas renvoyé.

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

If the server reports a changed `UIDVALIDITY` for a folder (its UIDs no
longer mean what they used to — typically after a server-side migration),
that folder's cache is purged and resynced from scratch automatically;
there is currently no on-screen notice when this happens beyond the folder
briefly emptying and refilling.

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

Si le serveur annonce un `UIDVALIDITY` changé pour un dossier (ses UID ne
veulent plus dire ce qu'ils disaient — typiquement après une migration
côté serveur), le cache de ce dossier est purgé et resynchronisé à partir
de zéro automatiquement ; il n'y a actuellement aucun avis à l'écran
au-delà du dossier qui se vide puis se remplit à nouveau brièvement.

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
`imap_transport.py`, `imap_sync.py`) now go through the CLI's translation
layer, the same as the menu prompts and TUI labels: running the CLI in
English shows them in English. The wording below is quoted in French, this
document's reference language; expect the matching English wording when
`EL_LANG=en`.

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

**"le fichier kdbx n'a pas pu être ouvert" when adding an account.**
The shared KDBX vault isn't configured yet, its file picker was cancelled,
or the CLI is running without a display to show that picker. Set
`kdbx.path` (and `kdbx.password`) as described in "Adding an account"
above, then try again.

**"le trousseau du système écrirait le mot de passe en clair (backend
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

**"cache illisible, purgez-le et resynchronisez : ...".**
The account's `cache.db` is corrupt. `Mail > [4] Cache > [3] Cache size and
purge` may itself fail to open the same broken file; if so, delete the
account's cache directory by hand and resync:

<!-- [fr] -->
## Dépannage

Les messages d'erreur qui viennent du paquet courriel lui-même
(`secrets.py`, `store.py`, `crypto.py`, `accounts.py`, `smtp_send.py`,
`imap_transport.py`, `imap_sync.py`) passent maintenant par la couche de
traduction du CLI, comme les invites de menu et les libellés du TUI :
lancer le CLI en anglais les affiche en anglais. Le libellé ci-dessous est
cité en français, la langue de référence de ce document ; attendez-vous au
libellé anglais correspondant avec `EL_LANG=en`.

**« Connexion échouée : ... » en ajoutant ou en testant un compte.**
`Courriel > [2] Comptes > [5] Tester la connexion d'un compte` affiche
l'erreur exacte du serveur puis redemande le mot de passe — jusqu'à 3
tentatives. Le mot de passe dans le coffre n'est écrasé qu'*après* une
connexion réussie, donc une faute de frappe ne détruit jamais un mot de
passe qui fonctionnait. Si le compte est Gmail, Outlook ou iCloud,
vérifiez d'abord que vous avez utilisé un mot de passe d'application (voir
« Prérequis » plus haut), pas le mot de passe normal du compte. Ouvrir le
TUI lui-même ne relance pas cette demande automatiquement : un compte au
mot de passe refusé porte un ⚠ ; s'il avait déjà synchronisé avec succès,
ses dossiers déjà en cache restent visibles et lisibles, ils cessent
seulement de se rafraîchir — seul un compte tout neuf (rien de
synchronisé encore) n'affiche aucun dossier du tout. Dans tous les cas,
passez par « Tester la connexion d'un compte » pour corriger.

**« le fichier kdbx n'a pas pu être ouvert » en ajoutant un compte.**
Le coffre KDBX partagé n'est pas encore configuré, sa fenêtre de sélection
de fichier a été annulée, ou le CLI tourne sans affichage pour la montrer.
Réglez `kdbx.path` (et `kdbx.password`) comme décrit dans « Ajouter un
compte » plus haut, puis réessayez.

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

<!-- [common] -->
```bash
rm -rf ~/.erplibre/mail/<account>/
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

These tests do **not** run in the fast loop. Without `twisted` and `aiosmtpd`
the whole file skips visibly. Run them deliberately:

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

Ces tests ne tournent **pas** dans la boucle rapide. Sans `twisted` ni
`aiosmtpd`, tout le fichier se saute visiblement. Pour les lancer
volontairement :

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
## Phase 1 limits

- **No OAuth** — Gmail, Outlook and iCloud need an app password (see
  above); OAuth is phase 2.
- **No statistics** — no read/unread counters or activity dashboards beyond
  the per-folder unseen count shown in the folder tree.
- **No server-side search** — `/` filters only what's already synced to the
  local cache.
- **No offline outbox** — sending requires the account to be online; there
  is no queue that flushes once you're back online.

See the [design spec](../docs/superpowers/specs/2026-08-02-email-tui-design.md)
for what the following phases add.

<!-- [fr] -->
## Limites de la phase 1

- **Pas d'OAuth** — Gmail, Outlook et iCloud demandent un mot de passe
  d'application (voir plus haut) ; OAuth arrive en phase 2.
- **Pas de statistiques** — aucun compteur lu/non lu global ni tableau de
  bord d'activité, au-delà du compte de non-lus par dossier affiché dans
  l'arbre.
- **Pas de recherche côté serveur** — `/` ne filtre que ce qui est déjà
  synchronisé dans le cache local.
- **Pas de file d'attente hors ligne** — l'envoi exige que le compte soit
  en ligne ; rien ne se met en attente pour partir au retour du réseau.

Voir le [spec de conception](../docs/superpowers/specs/2026-08-02-email-tui-design.md)
pour ce qu'apportent les phases suivantes.
