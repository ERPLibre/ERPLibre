
# Client courriel

Un client courriel intégré au CLI TODO : plusieurs comptes, IMAP + SMTP, et
un cache local — pour lire et répondre à son courriel sans quitter
`./script/todo/todo.py`.

Chaque chemin `Courriel > ...` ci-dessous est un raccourci pour
`TODO > [3] Assistant > [2] Courriel - Lire et envoyer du courriel > ...` — le
chemin complet est écrit une fois, dans « Ajouter un compte ».

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

```bash
.venv.erplibre/bin/pip install -r requirement/erplibre_require-ments.txt
```

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
| `/` | ouvre le champ de recherche : cherche dans tout le cache du dossier ouvert — et non dans les seuls messages affichés — sur sujet/de/à/extrait ; ne cherche pas sur le serveur (voir « Recherche ») |
| `g` | change de vue de liste : à plat, par fil, non lus seulement (voir « Vues de la liste ») |
| `s` / `u` | marquer le message sélectionné lu / non lu |
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
de zéro automatiquement. La passe nomme les dossiers auxquels elle l'a
fait : le TUI dans sa ligne de statut à la fin de la passe, `Courriel >
[3] Synchroniser maintenant` sous le nom du compte.

## Où sont les fichiers

| Chemin | Contenu |
|---|---|
| `~/.erplibre/mail/accounts.json` | la liste des comptes — serveurs, préréglages, mode de cache, et une référence `secret_ref` ; jamais un mot de passe (mode 0600) |
| `~/.erplibre/mail/<compte>/cache.db` | le cache SQLite de ce compte (mode 0600, dossier parent 0700) |
| `~/.erplibre/mail/<compte>/<dossier>/<uid>.eml` (ou `.eml.enc` s'il est scellé) | un fichier par corps de message téléchargé |
| `/dev/shm/erplibre-mail-<pid>/<compte>/` | le cache d'un compte `ephemeral` pendant que le processus vit ; effacé à sa sortie (un balayage au démarrage nettoie aussi ce qu'un processus tué aurait laissé) |

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

```bash
rm -rf ~/.erplibre/mail/<compte>/
```

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

```bash
.venv.erplibre/bin/python -m unittest discover -s test \
    -p test_mail_live_server.py -v
```

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

## Recherche

`/` cherche dans **tout le cache du dossier ouvert**, et non dans les seuls
messages chargés. Sujet, expéditeur, destinataire et extrait sont comparés.
La portée s'arrête là : les autres dossiers du compte, les autres comptes et
le serveur ne sont pas parcourus, et 500 correspondances au plus sont
rendues, les plus récentes d'abord.

En mode de cache `clear`, un index FTS5 répond en millisecondes et la liste
suit chaque frappe. En mode `encrypted` aucun index n'existe — il stockerait
en clair ce que le cache scelle — et la recherche déchiffre ligne à ligne.
Mesuré sur 200 000 messages : 0,00 s avec index contre 4,4 s en balayage
pour un terme qui ne correspond à rien. La liste cesse donc d'y suivre la
frappe et attend **Entrée**, ce que la barre d'état annonce. Jusqu'à cette
validation, la liste ne filtre que les messages déjà chargés.

Le résultat est le même des deux côtés ; seul le coût change.

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

Deux chiffres disent honnêtement ce qu'ils ignorent :

- **Les messages sans date lisible** sont exclus de l'histogramme et comptés
  sur leur propre ligne. Les ranger au 1er janvier 1970 dessinerait un pic qui
  n'a jamais eu lieu.
- **Les délais de réponse exigent les colonnes de fil**, apparues avec le
  cache v2. Les messages synchronisés avant ne portent rien à relier, et
  l'écran le dit plutôt que d'afficher un délai nul. Une resynchronisation
  complète les remplit.

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

**Ensuite, plus rien à faire.** Un jeton d'accès vit environ une heure ; le
client échange le jeton de rafraîchissement contre un neuf avant d'ouvrir
une session, range le jeu neuf au coffre, et synchronise. L'échange a lieu
dans le fil principal, avant toute passe : écrire au coffre y réécrit le
fichier entier, et deux fils de synchronisation qui écriraient ensemble le
corrompraient.

**Quand ça échoue.** Trois issues, distinguées parce que le remède diffère.
Le jeton neuf arrive, et rien n'est dit. L'autorisation est révoquée — le
propriétaire l'a retirée, ou le fournisseur l'a expirée — et aucun nouvel
essai ne la rendra : `Courriel > [2] Comptes > [6] Remplacer le jeton OAuth
d'un compte` offre les deux mêmes voies que l'ajout, et un parcours
abandonné comme une saisie vide n'écrivent rien plutôt que d'effacer ce qui
est là. Ou le fournisseur n'a pas répondu, auquel cas le
jeton en place vaut toujours et la passe suivante réessaie.

## Ce que le client ne fait pas encore

- **Pas d'identifiant client livré** — le parcours d'autorisation dans le
  navigateur exige un `client_id` que vous enregistrez vous-même ; sans lui,
  un compte OAuth s'ajoute à partir d'un jeton obtenu ailleurs (voir
  « S'authentifier par OAuth »).
- **Pas de recherche côté serveur** — `/` ne filtre que ce qui est déjà
  synchronisé dans le cache local.
- **Ni suppression ni déplacement d'un message** — `s` et `u` changent
  l'état lu / non lu, et `F` crée, renomme et supprime des dossiers, mais
  un message lui-même ne peut être ni supprimé ni déplacé vers un autre
  dossier.

Le devis de conception n'est pas suivi dans cet arbre ; retrouvez-le dans
l'historique par `git log --all -- "docs/superpowers/specs/*"` si vous avez
besoin de ce qu'apportent les phases restantes.