<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Odoo instance tools

| File | What it does |
|------|--------------|
| `update_module.py` | updates installed modules of an instance run by systemd: stop, back up, update, restart, check |
| `log_check.py` | reads the journal of an instance: tracebacks, errors, refused SQL queries, mail sending failures, to review (read-only) |
| `mail_retry.py` | lists the failed outgoing mails of an instance (read-only), then requeues the chosen ones through the Odoo shell |
| `warmup_http.py` | wakes the registry up as soon as the server listens; launched by `run.sh` |
| `migration/` | migration tools, see [migration/README.md](migration/README.md) |

## update_module.py

```bash
./script/odoo/update_module.py --module my_module_a --dry-run
sudo ./script/odoo/update_module.py --module 'my_module_*' --db demo_db
```

It is also reachable from `make todo`: `Execute > Production`, which runs
the simulation first and asks before the real run.

What it does, in order:

1. **Detection, nothing stopped.** The unit is `--service`, else the
   `erplibre…`/`odoo…` unit whose `WorkingDirectory` is this checkout, else
   the only active one. Its account, directory, command line and
   environment come from `systemctl show`. The Odoo configuration, the
   database (`--db`, else `-d` of the unit, else `db_name`), the HTTP port
   and the modules (patterns expanded over `addons_path`, only folders with
   a `__manifest__.py`) are deduced from them. Anything missing refuses
   with code 2.
2. **Root and lock.** Root is required (except `--dry-run`); one lock per
   database, shared with the backup tool, code 75 when another update or
   backup holds it.
3. **Stop.** The state before is read from `ActiveState`; without an
   answer from systemctl nothing is stopped (code 2). After `systemctl
   stop`, the unit must be `inactive` or `failed` (not `deactivating`).
   If the port still answers, or an Odoo process runs on the same database
   outside the unit, the update is refused unless `--force`.
4. **Backup** (unless `--no-backup`), after the stop so that it is
   consistent: the verified backup of
   [script/database/odoo_backup.py](../database/README.md), called while
   the update already holds the database lock. It is written to
   `--backup-dest/<db>/` (default `/var/backups/erplibre`) and recorded in
   `--state-dir` (default `/var/lib/erplibre-backup`). Before anything is
   stopped, the detection checks that the unit's account can write there
   (missing folders are created for it), that the database can be read and
   that there is enough disk space; otherwise it refuses with code 2. It
   neither copies off-site nor applies retention: the scheduled backup
   does.
5. **Update**: the unit's command line followed by `-c CONFIG -d DB -u
   MODULES --stop-after-init --no-http --workers=0 --max-cron-threads=0`,
   as the unit's account — the repeated `-c` keeps the update on the file
   the detection and the backup read (`--odoo-conf` included). It fails
   on a non-zero code, on `--timeout`, or on an
   `ERROR`/`CRITICAL` record in its output or in what was appended to the
   configured `logfile`. A record is the header line and its continuation
   lines (a traceback); the report groups tracebacks by their final
   exception, like `log_check.py`. `--ignore-error REGEX`, searched in the
   header line and in the final exception, excludes known records.
6. **Restart**, if the unit was running: wait for `active` and the port
   (`--start-wait`), one HTTP request, then the unit's journal and the
   `logfile` are read since the start.

The unit is never modified: the tool only reads it and runs `systemctl
stop` / `start`. Whatever happens after the stop — failure, exception,
Ctrl-C, SIGTERM — a unit that was running is restarted. Nothing is
restored: the tool does not replace the code; the backup is there for a
restore decided by a person.

| Code | Meaning |
|------|---------|
| 0 | success (or simulation) |
| 1 | update failed, service restarted |
| 2 | refused before anything was stopped |
| 75 | another update or backup of this database is running |
| 130 | interrupted, service restarted |

The update log goes to `--log-dir` (default `/var/log/erplibre`, falling
back to the temporary directory).

## log_check.py

```bash
./script/odoo/log_check.py --since-last
./script/odoo/log_check.py --last 6
./script/odoo/log_check.py --since "2026-03-01 08:00" --until "2026-03-01 12:00"
./script/odoo/log_check.py --by-hour --days 7
./script/odoo/log_check.py --file /var/log/odoo/odoo.log --json
```

**Source.** The unit is `--service`, else detected like `update_module.py`.
When its configuration sets a `logfile`, Odoo writes there and that file is
read; otherwise `journalctl -u UNIT -o short-iso`, streamed with an overall
`--timeout`. `--file` reads a given file without a unit. When the account
cannot read the configuration, a `--logfile` on ExecStart is read if there
is one, otherwise the journal; a journal read that yields no Odoo record then
refuses (code 2, advising sudo) instead of reporting nothing to review.

**Window.** `--since-last` resumes after the last read: the journal cursor
(`--after-cursor`), or the byte offset of a file that kept its inode and did
not shrink (otherwise it is read from the start, and the report says so);
the first run reads the last 24 h. `--last HOURS`, `--since`/`--until`
(local time) and `--by-hour --days N` (default 7, adds the hour × day
matrix) never touch the state. Without a window option: the last 24 h.

**State.** `--state-dir/<unit>.json` (default `/var/lib/erplibre-logcheck`),
written only after a complete and successful read, through a temporary file
and a rename; a state that is a symbolic link is neither read nor replaced.
When the folder is not writable the report is still printed and says
"position not saved".

**Report.** (1) Python tracebacks grouped by their final exception line,
with count, first and last time and one sample (`--full-trace` shows all of
it); (2) other `ERROR`/`CRITICAL` records grouped by logger and normalised
message; (3) refused SQL queries (`odoo.sql_db: bad query`) by table and
PostgreSQL reason; (4) mail sending failures classified as transient or
PERMANENT with the Odoo setting to check; (5) known noise counted apart:
outdated asset source maps, serialization conflicts that Odoo retries,
outdated VAPID push subscriptions, plus `--ignore REGEX` (searched in the
header line and the final exception, never in traceback frames). Only
`ERROR` and `CRITICAL` are "to review". Times are local. `--json` prints a
summary with stable English keys; `update_module.py` uses the same parser.

It never writes anything but its state file and reads no database. Root is
not required when the account belongs to `systemd-journal` (or `adm`);
otherwise journalctl only shows the account's own messages, which is
detected and reported with code 2 and the advice to use sudo.

| Code | Meaning |
|------|---------|
| 0 | nothing to review |
| 1 | something to review |
| 2 | could not read (rights, unit, file, options) |
| 130 | interrupted |

## mail_retry.py

```bash
./script/odoo/mail_retry.py --dry-run
sudo ./script/odoo/mail_retry.py
sudo ./script/odoo/mail_retry.py --resend oldest 10 --yes
sudo ./script/odoo/mail_retry.py --resend ids 7404,7405 --yes --json
```

**List, read-only.** One `psql` query as the unit's account, with the
connection settings of its Odoo configuration passed through the
environment and a read-only transaction forced by `PGOPTIONS`: the
`mail.mail` in state `exception` created in the last `--days` (30), oldest
first, with date, subject, recipients masked by default (`j***@example.org`,
a display name reduced to its initial; `--details` shows everything) and the
failure cause, transient or PERMANENT, whose addresses are masked the same
way, in the text as in `--json`. Then totals by subject, cause and
day, and two warnings: a PERMANENT cause fails again until the named setting
is fixed; more than 10 mails with `mail.session.batch.size` unset or above
20 may hit the server's limit of messages per connection.

**Resend, through the ORM.** `--resend all | oldest N | ids LIST` with
`--yes` (without a terminal, nothing is resent without it); on a terminal
without `--resend`, a menu: `[a]ll`, `[o]ldest batch`, `[i]ds`, `[n]one`
(default). `--list` only lists. The unit's `odoo_bin.sh shell` runs as its
account in its working directory with a short script on its standard input:
it re-reads the mails still in `exception`, calls `action_retry()` when the
method exists, else `write({'state': 'outgoing'})`, commits, and prints its
result as JSON. The scheduled action "Mail: Email Queue Manager" then sends
the queue. No SQL write is ever made. `--dry-run` shows the selection and
the exact command and script. Beyond `--timeout`, the shell's whole process
group is stopped; a commit may have happened just before, so the tool says
the outcome is unknown and the list must be read again.

Root is only needed to become the unit's account.

| Code | Meaning |
|------|---------|
| 0 | no failed mail, or every chosen mail requeued |
| 1 | failed mails listed and not resent, or part of the selection skipped |
| 2 | refused or impossible (detection, rights, psql, no answer from the shell) |
| 130 | interrupted |

### Odoo 12 to 18

| Point | Variation |
|-------|-----------|
| Log line | `date time,ms pid LEVEL db logger: message`, with a trailing `perf_info` from 13; db `?` outside a request; header time in UTC |
| `mail.mail.failure_type` | present in 18; not checked in 12 to 17; read without branching (`to_jsonb(m)->>'failure_type'`), the text decides when it is missing |
| `mail.mail.action_retry()` | checked in 18 only; fallback `write({'state': 'outgoing'})` |
| From filter (`from_filter`) | 15+; named in the sender advice from 15 |
| Alias domains (default from, catchall) | 17+; `mail.default.from` and `mail.catchall.domain` system parameters up to 16 |
| `mail.session.batch.size` | present in 18; not checked in 12 to 14 |

<!-- [fr] -->
# Outils d'instance Odoo

| Fichier | Ce qu'il fait |
|---------|---------------|
| `update_module.py` | met à jour des modules installés d'une instance servie par systemd : arrêter, sauvegarder, mettre à jour, relancer, vérifier |
| `log_check.py` | lit le journal d'une instance : traces, erreurs, requêtes SQL refusées, échecs d'envoi de courriel, à revoir (lecture seule) |
| `mail_retry.py` | liste les courriels sortants en échec d'une instance (lecture seule), puis remet en file ceux qu'on choisit par le shell d'Odoo |
| `warmup_http.py` | réveille le registre dès que le serveur écoute ; lancé par `run.sh` |
| `migration/` | outils de migration, voir [migration/README.fr.md](migration/README.fr.md) |

## update_module.py

```bash
./script/odoo/update_module.py --module my_module_a --dry-run
sudo ./script/odoo/update_module.py --module 'my_module_*' --db demo_db
```

Aussi accessible depuis `make todo` : `Exécuter > Production`, qui lance
d'abord la simulation et demande avant l'exécution réelle.

Ce qu'il fait, dans l'ordre :

1. **Détection, rien d'arrêté.** L'unité est `--service`, sinon l'unité
   `erplibre…`/`odoo…` dont `WorkingDirectory` est ce checkout, sinon la
   seule active. Son compte, son dossier, sa ligne de commande et son
   environnement viennent de `systemctl show`. La configuration Odoo, la
   base (`--db`, sinon le `-d` de l'unité, sinon `db_name`), le port HTTP et
   les modules (motifs développés sur l'`addons_path`, seuls les dossiers
   portant un `__manifest__.py`) en sont déduits. Tout manque refuse avec
   le code 2.
2. **Root et verrou.** Root est exigé (sauf `--dry-run`) ; un verrou par
   base, partagé avec l'outil de sauvegarde, code 75 quand une autre mise à
   jour ou une sauvegarde le détient.
3. **Arrêt.** L'état d'avant se lit dans `ActiveState` ; sans réponse de
   systemctl, rien n'est arrêté (code 2). Après `systemctl stop`, l'unité
   doit être `inactive` ou `failed` (pas `deactivating`). Si le port répond
   encore, ou qu'un processus Odoo tourne sur la même base hors de
   l'unité, la mise à jour est refusée, sauf `--force`.
4. **Sauvegarde** (sauf `--no-backup`), après l'arrêt pour être cohérente :
   la sauvegarde vérifiée de
   [script/database/odoo_backup.py](../database/README.fr.md), appelée
   alors que la mise à jour tient déjà le verrou de la base. Elle s'écrit
   dans `--backup-dest/<base>/` (par défaut `/var/backups/erplibre`) et se
   note dans `--state-dir` (par défaut `/var/lib/erplibre-backup`). Avant
   tout arrêt, la détection vérifie que le compte de l'unité peut y écrire
   (les dossiers manquants sont créés pour lui), que la base se lit et que
   l'espace disque suffit ; sinon elle refuse avec le code 2. Elle ne copie
   pas hors site et n'applique pas de rétention : la sauvegarde planifiée
   s'en charge.
5. **Mise à jour** : la ligne de commande de l'unité suivie de `-c CONFIG
   -d BASE -u MODULES --stop-after-init --no-http --workers=0
   --max-cron-threads=0`, sous le compte de l'unité — le `-c` répété garde
   la mise à jour sur le fichier lu par la détection et la sauvegarde
   (`--odoo-conf` compris). Échec sur un code non nul, sur `--timeout`, ou
   sur un enregistrement `ERROR`/`CRITICAL` dans sa sortie ou dans ce qui
   s'est ajouté au `logfile` configuré. Un enregistrement est la ligne
   d'en-tête et ses lignes de continuation (une trace) ; le rapport groupe
   les traces par leur exception finale, comme `log_check.py`.
   `--ignore-error REGEX`, cherché dans la ligne d'en-tête et dans
   l'exception finale, écarte des enregistrements connus.
6. **Relance**, si l'unité tournait : attente de `active` et du port
   (`--start-wait`), une requête HTTP, puis lecture du journal de l'unité et
   du `logfile` depuis le démarrage.

L'unité n'est jamais modifiée : l'outil la lit et lance seulement
`systemctl stop` / `start`. Quoi qu'il arrive après l'arrêt — échec,
exception, Ctrl-C, SIGTERM —, une unité qui tournait est relancée. Rien
n'est restauré : l'outil ne remplace pas le code ; la sauvegarde sert à une
restauration décidée par une personne.

| Code | Sens |
|------|------|
| 0 | réussi (ou simulation) |
| 1 | mise à jour en échec, service relancé |
| 2 | refusé avant tout arrêt |
| 75 | une autre mise à jour ou sauvegarde de cette base est en cours |
| 130 | interrompu, service relancé |

Le journal de la mise à jour va dans `--log-dir` (par défaut
`/var/log/erplibre`, avec repli sur le dossier temporaire).

## log_check.py

```bash
./script/odoo/log_check.py --since-last
./script/odoo/log_check.py --last 6
./script/odoo/log_check.py --since "2026-03-01 08:00" --until "2026-03-01 12:00"
./script/odoo/log_check.py --by-hour --days 7
./script/odoo/log_check.py --file /var/log/odoo/odoo.log --json
```

**Source.** L'unité est `--service`, sinon détectée comme pour
`update_module.py`. Quand sa configuration pose un `logfile`, Odoo y écrit
et c'est ce fichier qui est lu ; sinon `journalctl -u UNITÉ -o short-iso`,
lu au fil de l'eau avec un délai total `--timeout`. `--file` lit un fichier
donné, sans unité. Quand le compte ne peut pas lire la configuration, un
`--logfile` d'ExecStart est lu s'il y en a un, sinon le journal ; une lecture
du journal qui ne rend aucun enregistrement d'Odoo refuse alors (code 2,
conseil sudo) au lieu de dire qu'il n'y a rien à revoir.

**Fenêtre.** `--since-last` reprend après la dernière lecture : le curseur
du journal (`--after-cursor`), ou l'octet d'un fichier qui garde son inode et
n'a pas raccourci (sinon il est relu depuis le début, et le rapport le dit) ;
la première fois, les dernières 24 h. `--last HEURES`, `--since`/`--until`
(heure locale) et `--by-hour --days N` (7 par défaut, ajoute la matrice
heure × jour) ne touchent jamais l'état. Sans option de fenêtre : les
dernières 24 h.

**État.** `--state-dir/<unité>.json` (par défaut
`/var/lib/erplibre-logcheck`), écrit seulement après une lecture complète et
réussie, par un fichier temporaire puis un renommage ; un état qui est un
lien symbolique n'est ni lu ni remplacé. Quand le dossier n'est pas
inscriptible, le rapport s'affiche quand même et dit « position non
retenue ».

**Rapport.** (1) Traces Python groupées par leur ligne d'exception finale,
avec nombre, première et dernière heure et un exemple (`--full-trace` le
montre en entier) ; (2) autres enregistrements `ERROR`/`CRITICAL` groupés
par logger et message normalisé ; (3) requêtes SQL refusées
(`odoo.sql_db: bad query`) par table et raison PostgreSQL ; (4) échecs
d'envoi de courriel classés passagers ou PERMANENTS, avec le réglage d'Odoo
à vérifier ; (5) bruit connu compté à part : cartes source d'assets
périmés, conflits de sérialisation qu'Odoo rejoue, abonnements push à clé
VAPID périmée, plus `--ignore REGEX` (cherché dans la ligne d'en-tête et
l'exception finale, jamais dans les cadres de la trace). Seuls `ERROR` et
`CRITICAL` sont « à revoir ». Les heures sont locales. `--json` donne un
résumé aux clés anglaises stables ; `update_module.py` emploie le même
analyseur.

Il n'écrit rien d'autre que son fichier d'état et ne lit aucune base. Root
n'est pas exigé quand le compte est membre de `systemd-journal` (ou `adm`) ;
sinon journalctl ne montre que les messages du compte, ce qui est détecté et
signalé en code 2 avec le conseil de passer par sudo.

| Code | Sens |
|------|------|
| 0 | rien à revoir |
| 1 | quelque chose à revoir |
| 2 | lecture impossible (droits, unité, fichier, options) |
| 130 | interrompu |

## mail_retry.py

```bash
./script/odoo/mail_retry.py --dry-run
sudo ./script/odoo/mail_retry.py
sudo ./script/odoo/mail_retry.py --resend oldest 10 --yes
sudo ./script/odoo/mail_retry.py --resend ids 7404,7405 --yes --json
```

**Liste, en lecture seule.** Une requête `psql` sous le compte de l'unité,
les paramètres de connexion de sa configuration Odoo passés par
l'environnement et une transaction en lecture seule forcée par
`PGOPTIONS` : les `mail.mail` à l'état `exception` créés dans les `--days`
derniers jours (30), du plus ancien au plus récent, avec date, sujet,
destinataires masqués par défaut (`j***@example.org`, un nom affiché réduit
à son initiale ; `--details` montre tout) et la cause de l'échec, passagère
ou PERMANENTE, dont les adresses sont masquées de même, au texte comme en
`--json`. Puis les totaux par sujet, cause et jour, et deux
avertissements : une cause PERMANENTE échoue de nouveau tant que le réglage
nommé n'est pas corrigé ; plus de 10 courriels avec
`mail.session.batch.size` absent ou au-dessus de 20 risquent la limite de
messages par connexion du serveur.

**Renvoi, par l'ORM.** `--resend all | oldest N | ids LISTE` avec `--yes`
(sans terminal, rien n'est renvoyé sans lui) ; sur un terminal sans
`--resend`, un menu : `[a]` tous, `[o]` les plus anciens, `[i]` des ids,
`[n]` aucun (par défaut). `--list` ne fait que lister. Le
`odoo_bin.sh shell` de l'unité tourne sous son compte dans son dossier de
travail, avec un court script sur son entrée standard : il relit les
courriels encore en `exception`, appelle `action_retry()` quand la méthode
existe, sinon `write({'state': 'outgoing'})`, valide, et rend son bilan en
JSON. L'action planifiée « Mail: Email Queue Manager » envoie ensuite la
file. Aucune écriture SQL n'est jamais faite. `--dry-run` montre la
sélection, la commande et le script exacts. Au-delà de `--timeout`, tout le
groupe de processus du shell est arrêté ; une validation a pu précéder
l'arrêt, l'outil dit donc que l'issue est inconnue et qu'il faut relister.

Root n'est nécessaire que pour devenir le compte de l'unité.

| Code | Sens |
|------|------|
| 0 | aucun courriel en échec, ou tous les courriels choisis remis en file |
| 1 | des échecs listés et non renvoyés, ou une partie de la sélection ignorée |
| 2 | refusé ou impossible (détection, droits, psql, shell sans réponse) |
| 130 | interrompu |

### Odoo 12 à 18

| Point | Variation |
|-------|-----------|
| Ligne de journal | `date heure,ms pid NIVEAU base logger: message`, suivie de `perf_info` depuis 13 ; base `?` hors requête ; heure de l'en-tête en UTC |
| `mail.mail.failure_type` | présent en 18 ; non vérifié de 12 à 17 ; lu sans branchement (`to_jsonb(m)->>'failure_type'`), le texte décide quand il manque |
| `mail.mail.action_retry()` | vérifié en 18 seulement ; repli `write({'state': 'outgoing'})` |
| Filtre « De » (`from_filter`) | 15+ ; nommé dans le conseil sur l'expéditeur à partir de 15 |
| Domaines d'alias (expéditeur par défaut, catchall) | 17+ ; paramètres système `mail.default.from` et `mail.catchall.domain` jusqu'à 16 |
| `mail.session.batch.size` | présent en 18 ; non vérifié de 12 à 14 |
