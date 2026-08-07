# Client courriel TUI dans le CLI TODO — conception

Date : 2026-08-02
Statut : approuvé, phase 1 prête à planifier

## Contexte

Le CLI TODO (`script/todo/todo.py`) sert déjà de poste de commande ERPLibre :
exécution d'instances, migrations, déploiement QEMU, télémétrie. Il embarque
Textual pour ses écrans (`todo_telemetry.py`, `qemu_deploy_form.py`,
`qemu_install_monitor.py`), pykeepass pour ses secrets (`kdbx_manager.py`) et
un dossier de préférences utilisateur (`~/.erplibre`, `todo_prefs.py`).

L'objectif est d'y ajouter un client courriel complet — un remplacement de
Thunderbird lancé depuis ERPLibre — qui réutilise ces briques plutôt que d'en
introduire de nouvelles.

## Objectif

Lire, chercher, écrire et envoyer du courriel depuis le CLI TODO, sur
plusieurs comptes, avec un cache local dont l'utilisateur choisit le niveau de
confidentialité.

## Non-objectifs (toutes phases confondues)

- Serveur de courriel. On est client, jamais MTA.
- Composition HTML riche. On envoie du texte brut ; on *lit* le HTML dépouillé.
- Intégration au modèle `mail.message` d'Odoo. Le cache est autonome ; le pont
  vers Odoo, s'il vient, sera une phase à part.
- Notifications système (l'utilisateur les a explicitement écartées).
- Chiffrement de bout en bout des messages (PGP/S-MIME). On chiffre le cache
  au repos, pas le courrier en transit.

## Découpage en phases

Chaque phase a son spec, son plan et son cycle d'implémentation. Une phase ne
commence qu'une fois la précédente livrée et testée.

| Phase | Contenu | État |
|-------|---------|------|
| 1 | Socle vertical : comptes IMAP/SMTP manuels, secrets, cache chiffrable, sync incrémentale, TUI 3 volets, envoi, renommage Assistant, tests, doc | spec ci-dessous, détaillé |
| 2 | OAuth 2.0 Google et Microsoft, mots de passe d'application Apple, rafraîchissement de jeton | esquissé |
| 3 | Vue statistique, recherche plein texte, sync multi-comptes parallèle, fils de discussion | esquissé |
| 4 | Suivi des réseaux sociaux dans la même coquille | esquissé |

---

# Phase 1 — socle

## Décisions arrêtées

| Sujet | Décision | Raison |
|-------|----------|--------|
| Secrets | kdbx primaire (créer un nouveau fichier ou en choisir un), repli trousseau OS via `keyring` | réutilise `KdbxManager` ; le repli couvre l'utilisateur sans kdbx |
| Backend keyring en clair | refus explicite | `keyrings.alt` écrit le mot de passe en clair ; l'accepter en silence serait un piège |
| Config non secrète | `accounts.json` lisible et éditable | diffable, réparable à la main, jamais de mot de passe dedans |
| Format de cache | SQLite (index) + `.eml` sur disque | base petite, pièces jointes hors base, `.eml` relisible par tout outil |
| Chiffrement | trois modes — `clear`, `encrypted`, `ephemeral` | l'utilisateur arbitre confidentialité contre commodité |
| Portée du mode | par compte, avec un défaut général | courrier professionnel chiffré, liste de diffusion en clair |
| Racine de cache | une par compte | un compte éphémère ne peut pas partager une base avec un compte persistant |
| Bibliothèques réseau | `imaplib`, `smtplib`, `email` de la stdlib | zéro nouvelle dépendance réseau |
| Sync | à l'ouverture du TUI, touche `r`/`R`, plus un rafraîchissement automatique **actif par défaut, uniquement pendant que le TUI est ouvert** | pas de démon, pas de processus orphelin |
| Disposition TUI | 3 volets, avec bascule plein écran sur le message | modèle mental Thunderbird, lecture confortable au besoin |
| Composition | formulaire Textual, touche `e` vers `$EDITOR` | utilisable sans éditeur configuré, puissant si on en a un |
| Menu | `[3] Question` devient `[3] Assistant`, sous-menu contenant Question IA et Courriel | regroupe ce qui s'adresse à l'humain, garde le menu principal court |

## Arborescence des modules

```
script/todo/mail/
  __init__.py      API publique du paquet
  accounts.py      modèle de compte, accounts.json, préréglages, générateur de modèle
  secrets.py       SecretStore : kdbx (créer ou choisir) → repli keyring, refus du backend en clair
  crypto.py        MailCrypto.seal/open — NullCrypto | AesGcmCrypto
  store.py         cache par compte : schéma SQLite, fichiers .eml, résolution du mode, racine éphémère
  imap_sync.py     ImapTransport (protocole) + ImaplibTransport + Syncer incrémental
  smtp_send.py     construction MIME, envoi, pièces jointes, réponse/transfert, APPEND dans Envoyés
  tui.py           application Textual : 3 volets, plein écran, formulaire de composition
  menu.py          prompt_execute_mail() — appelé depuis todo.py
```

Chaque module a une responsabilité unique et une interface étroite :
`accounts` ne connaît pas le réseau, `imap_sync` ne connaît pas le
chiffrement (il parle au `Store`), `tui` ne connaît ni IMAP ni SQLite (il
parle au `Store` et au `Syncer`). Aucun n'importe `todo.py` ; c'est `todo.py`
qui importe `menu.py`.

### Pourquoi un paquet et non un fichier de plus

`todo.py` fait 7 156 lignes. Y verser un client courriel le rendrait
impossible à relire. Le paquet `mail/` garde chaque fichier sous ~400 lignes,
testable seul, et `todo.py` ne gagne qu'un import et un branchement de menu.

## Modèle de données

Une base par compte, `<racine>/<compte>/cache.db`.

```sql
CREATE TABLE meta (
  key   TEXT PRIMARY KEY,
  value TEXT
);
-- clés : schema_version, cache_mode, account_name, created_at

CREATE TABLE folders (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,  -- nom IMAP brut (UTF-7 modifié)
  display     TEXT,                  -- nom décodé, affichable
  role        TEXT,                  -- inbox|sent|drafts|trash|archive|junk|NULL
  uidvalidity INTEGER,
  uidnext     INTEGER,
  last_uid    INTEGER NOT NULL DEFAULT 0,
  total       INTEGER NOT NULL DEFAULT 0,
  unseen      INTEGER NOT NULL DEFAULT 0,
  synced_at   INTEGER
);

CREATE TABLE messages (
  id             INTEGER PRIMARY KEY,
  folder_id      INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
  uid            INTEGER NOT NULL,
  date           INTEGER,   -- epoch UTC — en clair, sert au tri
  size           INTEGER,   -- en clair
  flags          TEXT,      -- en clair, CSV : \Seen,\Answered,\Flagged
  has_body       INTEGER NOT NULL DEFAULT 0,
  msgid_hash     TEXT,      -- sha256(clé || Message-ID), en clair, pour les jointures
  sealed_msgid   BLOB,
  sealed_from    BLOB,
  sealed_to      BLOB,
  sealed_subject BLOB,
  sealed_snippet BLOB,
  UNIQUE(folder_id, uid)
);
CREATE INDEX idx_msg_date ON messages(folder_id, date DESC);
```

Le `Message-ID` en clair trahirait le domaine du correspondant : il est scellé
comme le reste, et un hachage salé par la clé du compte permet quand même de
retrouver un message par identifiant (base des fils de discussion en phase 3).

Déchiffrer 10 000 sujets pour peupler la liste coûte quelques millisecondes ;
aucune optimisation n'est prévue tant que ce n'est pas mesuré comme un
problème.

## `accounts.json`

`~/.erplibre/mail/accounts.json`, permissions `0600`.

```json
{
  "version": 1,
  "default_account": "perso",
  "accounts": [
    {
      "name": "perso",
      "email": "moi@exemple.ca",
      "display_name": "Mathieu Benoit",
      "preset": "gmail",
      "imap": {"host": "imap.gmail.com", "port": 993, "security": "ssl", "user": "moi@exemple.ca"},
      "smtp": {"host": "smtp.gmail.com", "port": 587, "security": "starttls", "user": "moi@exemple.ca"},
      "secret_ref": "kdbx:ERPLibre/Mail/perso",
      "cache_mode": null,
      "sent_folder": "[Gmail]/Messages envoyés",
      "enabled": true
    }
  ]
}
```

`cache_mode: null` hérite de la préférence générale. `secret_ref` porte le
schéma du coffre (`kdbx:` ou `keyring:`) ; jamais de mot de passe.

### Préréglages

| Clé | IMAP | SMTP | Note |
|-----|------|------|------|
| `gmail` | imap.gmail.com:993 SSL | smtp.gmail.com:587 STARTTLS | exige un mot de passe d'application (2FA obligatoire) |
| `outlook` | outlook.office365.com:993 SSL | smtp.office365.com:587 STARTTLS | l'authentification simple est en fin de vie côté Microsoft ; OAuth en phase 2 |
| `icloud` | imap.mail.me.com:993 SSL | smtp.mail.me.com:587 STARTTLS | exige un mot de passe d'application |
| `generic` | saisie manuelle | saisie manuelle | — |

Cette limite est assumée : la phase 1 fonctionne partout où un mot de passe
d'application est possible, la phase 2 lève la contrainte pour Google et
Microsoft.

### Générateur de modèle

Entrée de menu « Générer un modèle » : écrit un `accounts.json` commenté
(commentaires portés par des clés `_comment`, JSON strict oblige) avec un
exemple par préréglage, et crée les entrées kdbx correspondantes, vides, à
remplir. Ne remplace jamais un fichier existant sans confirmation explicite.

## Secrets

```
SecretStore.get(ref) -> str | None
SecretStore.set(ref, secret) -> None
SecretStore.delete(ref) -> None
SecretStore.available_backends() -> list[str]
```

Résolution à la création d'un compte :

1. **kdbx** — si `kdbx.path` est déjà configuré dans le fichier de config du
   CLI, on le propose. Sinon deux choix : créer un nouveau `.kdbx`
   (`PyKeePass.create_database`, mot de passe demandé deux fois) ou en choisir
   un existant (chemin saisi, ou `tkinter.filedialog` si disponible).
   Les entrées vont dans le groupe `ERPLibre/Mail`, titre = nom du compte.
2. **keyring** — proposé si `pykeepass` est absent ou si l'utilisateur refuse
   le kdbx. Avant tout usage, `keyring.get_keyring()` est inspecté : les
   backends `SecretService.Keyring`, `macOS.Keyring` et
   `Windows.WinVaultKeyring` sont acceptés ; tout backend du paquet
   `keyrings.alt` ou un `fail.Keyring` est **refusé** avec un message qui
   explique que le mot de passe finirait en clair.
3. Aucun des deux → la création de compte échoue avec un message actionnable.

La clé de chiffrement du cache est un secret distinct du mot de passe :
32 octets aléatoires, référence `<ref>/cache-key`, encodés base64.

## Chiffrement du cache

```
MailCrypto.seal(data: bytes) -> bytes
MailCrypto.open(blob: bytes) -> bytes
```

Enveloppe auto-descriptive, pour qu'une base écrite dans un mode reste
lisible si le mode change :

```
clair    b"P0" + data
chiffré  b"E1" + nonce(12) + AES-256-GCM(ct || tag)
```

`AesGcmCrypto` s'appuie sur `cryptography.hazmat.primitives.ciphers.aead.AESGCM`.
Un nonce aléatoire par scellement ; aucune réutilisation de nonce possible
puisqu'on ne rescelle jamais en place sans en tirer un neuf.

### Les trois modes

| Mode | Racine | Clé | Cycle de vie |
|------|--------|-----|--------------|
| `clear` | `~/.erplibre/mail/<compte>/` | aucune | persistant, `0600` sur fichiers, `0700` sur dossiers |
| `encrypted` | `~/.erplibre/mail/<compte>/` | 32 o dans kdbx/keyring | persistant |
| `ephemeral` | `/dev/shm/erplibre-mail-<pid>/<compte>/` | tirée au démarrage, jamais écrite | effacée à la sortie, resync complète au lancement suivant |

Éphémère : si `/dev/shm` est absent ou non inscriptible (macOS), repli sur
`tempfile.mkdtemp()` en `0700`. Le nettoyage est branché **à la fois** sur
`atexit` et sur des gestionnaires `SIGINT`/`SIGTERM`, parce qu'`atexit` ne
s'exécute pas sur signal. Un `SIGKILL` laissera un résidu dans `/dev/shm` ;
au démarrage, le module balaie les `erplibre-mail-*` dont le PID n'existe plus
et les efface.

## Sync IMAP

`imap_sync.py` définit un protocole pour que le moteur soit testable sans
serveur :

```python
class ImapTransport(Protocol):
    def login(self, user: str, password: str) -> None: ...
    def list_folders(self) -> list[FolderInfo]: ...
    def select(self, folder: str) -> SelectInfo: ...   # uidvalidity, uidnext, exists
    def search_uids(self, since_uid: int) -> list[int]: ...
    def fetch_headers(self, uids: list[int]) -> list[HeaderInfo]: ...
    def fetch_body(self, uid: int) -> bytes: ...
    def store_flags(self, uid: int, add: list[str], remove: list[str]) -> None: ...
    def append(self, folder: str, raw: bytes, flags: list[str]) -> None: ...
    def logout(self) -> None: ...
```

`ImaplibTransport` l'implémente sur `imaplib.IMAP4_SSL`. Les tests utilisent
`FakeImapTransport`, qui sert des messages en mémoire.

Algorithme d'une passe, par dossier :

1. `SELECT` → comparer `UIDVALIDITY` au stocké. Différent → purger le dossier
   (lignes et `.eml`) et repartir de `last_uid = 0`.
2. `UID SEARCH UID <last_uid+1>:*` → nouveaux UID.
3. `UID FETCH <lot> (UID FLAGS ENVELOPE RFC822.SIZE)` par lots de 200 →
   upsert des métadonnées scellées, `last_uid` avancé.
4. Rafraîchir les drapeaux des N derniers messages déjà connus
   (`UID FETCH <plage> (FLAGS)`), N = 500, pour capter les lus/supprimés.
5. Écrire `total`, `unseen`, `synced_at`.

Le corps n'est jamais téléchargé pendant la sync : au premier affichage d'un
message, `fetch_body` écrit le `.eml` (scellé si besoin) et passe
`has_body = 1`.

Rafraîchissement automatique : minuterie Textual, `mail_refresh_sec` (défaut
300), armée à l'ouverture du TUI et désarmée à sa fermeture. Aucun travail
réseau quand le TUI n'est pas à l'écran.

## Envoi SMTP

`smtp_send.py` construit un `email.message.EmailMessage` :

- `From` depuis le compte (`display_name <email>`), `To`, `Cc`, `Subject`,
  `Date`, `Message-ID` généré.
- Réponse : `In-Reply-To` = `Message-ID` du parent, `References` = celles du
  parent plus le parent. Objet préfixé `Re: ` si absent.
- Transfert : objet préfixé `Fwd: `, message d'origine attaché en
  `message/rfc822`.
- Pièces jointes : détection de type par `mimetypes`, repli
  `application/octet-stream`.

Envoi via `smtplib.SMTP_SSL` ou `smtplib.SMTP` + `starttls()` selon
`security`. En cas de succès : `APPEND` du message brut dans le dossier
`sent_folder` avec `\Seen`, plus écriture locale immédiate pour qu'il
apparaisse sans attendre la sync.

En cas d'échec, le formulaire de composition reste ouvert avec son contenu et
l'erreur exacte du serveur en barre d'état. Pas de file d'attente hors ligne
en phase 1 — c'est une fonction à part entière, elle sera arbitrée plus tard.

## TUI

Application Textual, trois volets :

```
+-- Comptes ----+-- INBOX (142) --------+-- Aperçu -----+
| v perso       | * Alice   Re: devis   | De: Alice     |
|   INBOX  12   |   Bob     CR réunion  | Obj: Re:devis |
|   Envoyés     |   github  [PR] #421   | 2026-08-01    |
|   Archives    |   Carl    Facture     |               |
| > travail   3 |                       | Bonjour, ci-  |
+---------------+-----------------------+ joint le ...  |
 r sync  c écrire  R répondre  / rech.  q quitter
```

| Touche | Action |
|--------|--------|
| `↑` `↓` `Tab` | navigation, changement de volet |
| `Entrée` | bascule plein écran sur le message courant, `Échap` revient |
| `r` / `Shift+R` | resync du compte courant / de tous les comptes |
| `c` | composer |
| `a` | répondre · `A` répondre à tous · `f` transférer |
| `u` | marquer non lu · `s` marquer lu |
| `/` | filtre incrémental sur les métadonnées en cache (la recherche serveur arrive en phase 3) |
| `q` | quitter |

Le corps est rendu en texte : partie `text/plain` si elle existe, sinon HTML
dépouillé (balises retirées, entités décodées, sans dépendance externe). Les
pièces jointes sont listées avec nom et taille ; leur enregistrement sur
disque passe par une invite de chemin.

Seules les fonctions pures du TUI sont testées (tri, troncature, formatage
d'en-têtes, extraction du corps). Les écrans ne le sont pas : ça coûterait
plus cher que la valeur produite.

## Menus et i18n

Menu principal :

```
[1] Exécution
[2] Installation
[3] Assistant        <- ex-« ❓ Question »
[4] Fork
[5] Télémétrie
[6] Configuration
[0] Quitter
```

`execute_prompt_ia` devient `prompt_assistant()` ; son corps actuel part dans
`_assistant_question()` sans changement de comportement.

```
Assistant
  [1] Question IA
  [2] Courriel
  [0] Retour

Courriel
  [1] Ouvrir le client (TUI)
  [2] Comptes
      [1] Lister  [2] Ajouter  [3] Modifier  [4] Supprimer
      [5] Générer un modèle  [6] Tester la connexion
  [3] Synchroniser maintenant
  [4] Cache
      [1] Mode par défaut  [2] Mode d'un compte  [3] Taille / purger
  [0] Retour
```

Toutes les chaînes passent par `t()`, clés préfixées `mail_`, groupées sous un
commentaire `# Courriel` dans `TRANSLATIONS`, avec `fr` et `en`.

Nouvelles préférences dans `todo_prefs.DEFAULTS` :

```python
"mail_cache_mode": "clear",   # défaut général : clear | encrypted | ephemeral
"mail_refresh_sec": 300,      # rafraîchissement auto pendant que le TUI est ouvert
```

## Gestion des erreurs

| Situation | Comportement |
|-----------|--------------|
| Réseau injoignable, IMAP refuse | non fatal : compte marqué hors ligne en barre d'état, cache navigable |
| `textual` absent | message dans le style existant (« Installez textual… ») ; le menu Courriel reste utilisable pour la config et la sync |
| Ni `pykeepass` ni `keyring` | création de compte refusée, message expliquant quoi installer |
| Backend keyring en clair | refusé, message expliquant pourquoi |
| `cryptography` absent | modes `encrypted` et `ephemeral` indisponibles, `clear` fonctionne |
| `UIDVALIDITY` changé | purge du dossier puis resync complète, notifiée à l'utilisateur |
| `cache.db` corrompue | détection à l'ouverture, proposition de purge + resync |
| Envoi SMTP en échec | formulaire conservé, erreur serveur affichée telle quelle |
| Mot de passe rejeté | invite de ressaisie, mise à jour du coffre après succès |

Aucune de ces situations n'interrompt le CLI TODO : le module courriel dégrade
mais ne fait jamais tomber le menu.

## Tests

Dans `test/`, `unittest` comme le reste du dépôt.

| Fichier | Couvre |
|---------|--------|
| `test_mail_accounts.py` | préréglages, lecture/écriture d'`accounts.json`, permissions `0600`, générateur de modèle, refus d'écraser |
| `test_mail_crypto.py` | aller-retour scellement, enveloppe auto-descriptive, mauvaise clé → erreur, nonce distinct à chaque appel |
| `test_mail_store.py` | création du schéma, upsert, résolution du mode (compte → défaut général), purge sur `UIDVALIDITY`, chemins `.eml`, nettoyage éphémère |
| `test_mail_sync.py` | `FakeImapTransport` : première sync, sync incrémentale, changement d'`UIDVALIDITY`, rafraîchissement des drapeaux, lots |
| `test_mail_send.py` | MIME multipart, pièces jointes, `In-Reply-To`/`References` sur réponse, `Fwd:` sur transfert, `FakeSmtp` |
| `test_mail_secrets.py` | kdbx créé dans un dossier temporaire, entrées lues/écrites, repli keyring simulé, refus du backend en clair |
| `test_mail_tui.py` | fonctions pures : tri, troncature, extraction du corps, HTML dépouillé |

`test/test_todo_i18n.py` couvre déjà la complétude des traductions ; les
nouvelles clés doivent y passer sans modification du test.

Aucun test ne touche le réseau ni le trousseau réel de la machine.

## Documentation

- `doc/EMAIL.base.md` — configuration d'un compte, choix du mode de cache,
  raccourcis du TUI, dépannage. `make doc_markdown` génère `EMAIL.md` et
  `EMAIL.fr.md`.
- Lien depuis `doc/TODO.base.md`.
- Mention dans `script/todo/README.base.md`.

Les `.md` et `.fr.md` générés ne sont jamais édités à la main.

## Dépendances

Ajouts à `requirement/erplibre_require-ments.txt` :

```
cryptography
keyring
```

`pykeepass`, `click` et `textual` y sont déjà. `imaplib`, `smtplib`, `email`,
`sqlite3` et `mimetypes` viennent de la bibliothèque standard.

## Critères de succès de la phase 1

1. Configurer un compte Gmail avec mot de passe d'application, sans éditer un
   fichier à la main.
2. Ouvrir le TUI, voir la boîte de réception, lire un message, l'aperçu et le
   plein écran.
3. Répondre, l'envoi part et la copie apparaît dans Envoyés.
4. Basculer un compte en `encrypted` : les fichiers du cache ne contiennent
   plus le sujet en clair (vérifiable par `grep`).
5. Un compte en `ephemeral` ne laisse rien sur le disque après fermeture.
6. Réseau coupé : le TUI s'ouvre et laisse relire le cache.
7. Tous les tests passent, la doc bilingue est générée.

---

# Phase 2 — OAuth 2.0

Lever la contrainte du mot de passe d'application, obligatoire dès que
l'authentification simple est désactivée côté fournisseur — ce qui est déjà le
cas des comptes Microsoft grand public et devient la règle chez Google.

Contenu attendu :

- Flux `authorization_code` avec PKCE, redirection sur un serveur HTTP
  éphémère en local (`localhost` sur port libre), ouverture du navigateur.
- Authentification IMAP et SMTP en `XOAUTH2` (`AUTHENTICATE XOAUTH2` /
  `AUTH XOAUTH2`).
- Jeton de rafraîchissement stocké dans le même coffre que les mots de passe,
  jeton d'accès en mémoire seulement, renouvellement transparent sur `401`.
- Préréglages `gmail-oauth` et `outlook-oauth`, en plus des préréglages mot de
  passe conservés.
- Apple : pas d'OAuth IMAP public — la documentation explique le mot de passe
  d'application ; le préréglage `icloud` de la phase 1 reste la voie.
- Identifiants client : configurables, avec un défaut ERPLibre documenté et la
  possibilité d'utiliser les siens.

Points à trancher au moment du spec : où loger l'écran de consentement quand
le CLI tourne en SSH sans navigateur (flux `device_code` en repli ?), et
comment tester un flux OAuth sans compte réel (serveur d'autorisation factice).

# Phase 3 — statistiques, recherche, parallélisme

## Vue statistique

Écran Textual dédié, alimenté par le cache — donc instantané et hors ligne :

- volume par jour, semaine, mois (histogramme en caractères) ;
- top correspondants en émission et en réception ;
- répartition par dossier, part de non-lus, taille cumulée ;
- délai de réponse médian ;
- filtres par compte, par période, par dossier.

Les agrégats sont calculés en SQL sur les colonnes en clair (`date`, `size`,
`flags`, `folder_id`) ; ceux qui portent sur l'expéditeur passent par le
déchiffrement des colonnes scellées, en mémoire, sans les réécrire.

## Recherche plein texte

Table FTS5 optionnelle sur sujet et corps. En mode `clear`, elle indexe
directement. En mode `encrypted`, l'index en clair annulerait le chiffrement :
la recherche s'y fera par balayage déchiffré, plus lente et assumée comme
telle, ou par index chiffré à clé déterministe si la mesure montre que le
balayage ne tient pas. Ce compromis sera tranché avec des chiffres.

## Reste de la phase

- Sync des comptes en parallèle (un fil par compte, plafonné).
- Fils de discussion via `msgid_hash`, `In-Reply-To` et `References`.
- Gestion des dossiers depuis le TUI : déplacer, supprimer, créer.
- File d'attente d'envoi hors ligne.

# Phase 4 — suivi des réseaux sociaux

Étendre la coquille du client courriel au suivi des réseaux sociaux : mêmes
volets, même cache chiffrable, mêmes statistiques, une source de plus.

Direction pressentie, à spécifier le moment venu :

- Une abstraction `Feed` au-dessus du `Store`, dont le courriel devient une
  implémentation parmi d'autres — les messages sociaux réutilisent la table
  `messages` (auteur, date, corps, drapeaux) plutôt qu'un schéma parallèle.
- Sources candidates par ordre de faisabilité : flux RSS/Atom et ActivityPub
  (Mastodon) d'abord, parce qu'ils sont ouverts et sans négociation d'API ;
  puis les plateformes à API fermée, dont l'accès est devenu payant ou
  restreint et doit être évalué avant d'être promis.
- Le volet gauche liste les sources à côté des comptes courriel ; la vue
  statistique de la phase 3 les agrège sans code spécifique.

Questions ouvertes : jusqu'où va « suivi » — lecture seule, ou publication et
réponse ? Et quelles plateformes justifient l'effort au regard de leurs
conditions d'accès actuelles ?

---

## Risques

| Risque | Portée | Réponse |
|--------|--------|---------|
| Les fournisseurs ferment l'authentification simple pendant la phase 1 | phase 1 inutilisable sur Outlook grand public | phase 2 déjà cadrée ; la doc annonce la limite dès la phase 1 |
| `keyring` retombe silencieusement sur un backend en clair | fuite de mot de passe | détection et refus explicites, testés |
| Résidu de cache éphémère après `SIGKILL` | fuite de contenu en RAM disque | balayage des dossiers orphelins au démarrage |
| `todo.py` grossit encore | maintenabilité | tout le code vit dans `script/todo/mail/`, `todo.py` ne gagne qu'un import et un branchement |
| L'index FTS annule le chiffrement | phase 3 | tranché à la phase 3, avec mesure, pas par principe |
