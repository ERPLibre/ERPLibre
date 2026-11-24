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
| `health_check.py` | checks that an instance answers and exposes nothing it should not: login page, `/web/health`, TLS, HTTPS redirect, HSTS, database manager, bus, robots.txt, mail DNS (read-only) |
| `warmup_http.py` | wakes the registry up as soon as the server listens; launched by `run.sh`. `--deep` warms up public pages, asset bundles and, with an API key, views |
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
7. **After a verified restart**, lock released: with `--warmup-deep`, the
   deep warm-up of `warmup_http.py` (public pages and asset bundles, no
   key), then the health check of the local instance (`health_check.py`).
   Their findings are printed as ATTN at most and never change the exit
   code; Ctrl-C there only stops that step.

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

## health_check.py

```bash
./script/odoo/health_check.py --url https://odoo.example.org
./script/odoo/health_check.py --url odoo.example.org --mail-domain example.org --dkim-selector s1
./script/odoo/health_check.py --local --json
```

`--url` (repeatable; a bare host means `https://host`) probes through the
reverse proxy; `--local` (with `--service`, else the detected unit) probes
the address the unit's configuration gives, with `?db=` when the database is
known. A URL with credentials (`user:pw@`) or a scheme other than http(s) is
refused. Read-only: GET requests, plus one unauthenticated JSON-RPC call to
`/web/webclient/version_info` for the version. No cookie, no
`Authorization` header, no proxy from the environment, bodies read up to
1 MiB, `--timeout` (10 s) on every request, TLS connection and DNS lookup.

| Check | OK | ATTN | FAIL | SKIP |
|-------|----|------|------|------|
| `http_login` | 200 within 5 s | slow, redirect to the database selector, to plain HTTP or another host | no answer, 5xx, other status | |
| `web_health` | 200 `pass` | unexpected answer | no answer, 5xx, `fail` | 404 (route absent) |
| `tls_certificate` | 21 days or more | under 21 days | under 7 days, expired, refused (name, chain, self-signed) | http URL, `--local` |
| `http_redirect` | `http://host/` redirects to https on the same host | other host, port 80 closed, other status | served in clear text | http URL, `--local` |
| `hsts` | `max-age` ≥ 1 day | missing, shorter | | no 200 on `/web/login`, http URL, `--local` |
| `db_manager`, `db_selector` | blocked (401/403/404/3xx), disabled page (`list_db = False`) | undetermined (5xx); exposed on `--local`; selector listing databases | manager reachable, or master password not set, on `--url` | |
| `list_db` (`--local`) | `False` | absent or true | | |
| `websocket` (`--url`) | forwarded (400/426) | 404, no answer | 502/503/504 | `--local` |
| `robots` (`--url`) | served, or `Disallow: /` without a `Sitemap:` line (no public website) | `Disallow: /` with a `Sitemap:` line (the URL used is not the website domain) | | 404 |
| `mail_spf` | one record ending in `-all`/`~all` | other ending | none, several, `+all` | no dig/host, lookup failed |
| `mail_dmarc` | present (policy shown) | absent | | no dig/host, lookup failed |
| `mail_dkim` (`--dkim-selector`) | key found | | absent, empty key | no dig/host, lookup failed |

The certificate is judged by `tls_certificate` only: the other HTTPS
requests do not verify it, so that a refused certificate gives one FAIL and
the other checks still answer. A plain-HTTP `--url` adds an `https` ATTN.
DNS goes through `dig` or `host`, the domain and selector validated first
(no leading `-`); a failed lookup is a SKIP, never "record absent". dig
exits 0 on any answer, SERVFAIL and REFUSED included: the status of its
answer header decides, and only NOERROR and NXDOMAIN are definite. No
third-party web service is contacted.

A default deployment gets FAIL on `db_manager` through `--url`: Odoo keeps
`list_db = True` when the configuration does not set it, and the nginx
templates do not block `/web/database`. Set `list_db = False`, or deny
`/web/database` in nginx.

`--json` keys (English, stable): `tool`, `odoo_version`, `targets` (`kind`,
`url`, `odoo_version`), `checks` (`id`, `target`, `status`, `message`,
`hint`, `data`), `summary` (`ok`, `attn`, `fail`, `skip`), `exit_code`.

| Code | Meaning |
|------|---------|
| 0 | no FAIL (ATTN are listed) |
| 1 | at least one FAIL |
| 2 | could not check (usage, detection, unreadable configuration: run with sudo) |
| 130 | interrupted |

## warmup_http.py --deep

```bash
./script/odoo/warmup_http.py --deep --local
./script/odoo/warmup_http.py --deep --url https://odoo.example.org -d DATABASE --max-pages 50
./script/odoo/warmup_http.py --deep --local --login admin --api-key-file ~/.odoo_key --models res.partner,sale.order
```

Without `--deep`, nothing changes: one line, silent with `--quiet`, always
exit 0, unknown options passed to Odoo; `--deep` after `--` belongs to Odoo.
With `--deep`: wait for the first answer (`--timeout`, 120 s), open a
session on `/web/login?db=BASE`, fetch `/web/login`, `/` and up to
`--max-pages` (20) HTML pages of `/sitemap.xml` (an index is followed one
level; only the path of each `<loc>` is kept, the request goes to the
target), each `--repeat` (4, at most 16) times at once. Then each asset
bundle those pages reference (`/web/assets/…`, and `/web/content/…assets_…`
in older versions) once alone — that request builds it — then `--repeat` − 1
times at once. With `--login` and `--api-key-file`: `common.login` through
`/jsonrpc` with the API key (Odoo accepts a key only outside an interactive
login), then `execute_kw` of a closed list of read-only methods:
`res.users.context_get`, `ir.ui.menu.load_menus` and, for each model of
`--models` (`res.partner`), `get_views` (16+) or `load_views` (15 and
before). The key file is read without following a link; a file readable by
other accounts gets a warning. The key leaves only over https, or over
http to the loopback (`--local`, the default-mode address): `--login` with
an `http://` URL on another host is refused (code 2). The target is
`--url`, `--local` (detected unit) or the default-mode address. A sitemap
`<loc>` that is neither an absolute URL nor a path starting with `/` is
ignored: only its path is sent, to the target.

A request fails on no answer or a code ≥ 500, and on a JSON-RPC error; a
4xx is counted apart as "not public".

| Code | Meaning |
|------|---------|
| 0 | done, failures included |
| 1 | with `--strict`, at least one failure |
| 2 | invalid option, unreadable key file, no database with `--login` |
| 130 | interrupted |

### Odoo 12 to 18 (health check, warm-up)

| Point | Variation |
|-------|-----------|
| `/web/health` | 18: present, `db_server_status=1` checks PostgreSQL; 16 and 17: present (not checked); 12 to 15: absent, SKIP |
| Bus path behind the proxy | `/websocket` from 16 (checked in 18); `/longpolling/poll` up to 15; an unknown version tries both |
| Web client URL | `/odoo` in 18, `/web` redirects to it; `/web` up to 17 |
| View loading by RPC | `get_views` from 16, `load_views` up to 15; list view type `list` in 18, `tree` before |
| API key with `common.login` | 14+ (non-interactive only); none in 12 and 13 |
| `/robots.txt` | without website, 18: `Disallow: /` plus `Allow:` lines, 404 up to 17 (not checked); with website: a `Sitemap:` line, and `Disallow: /` when the URL is not the website domain (checked in 18) |
| Database manager with `list_db = False` | 18: 200 with the "disabled" page (read, not just the status); not checked in 12 to 17, a 403 is handled too |
| ERPLibre nginx templates | no HSTS for 12 to 15; HSTS in `location /` from 16; none blocks `/web/database` |

<!-- [fr] -->
# Outils d'instance Odoo

| Fichier | Ce qu'il fait |
|---------|---------------|
| `update_module.py` | met à jour des modules installés d'une instance servie par systemd : arrêter, sauvegarder, mettre à jour, relancer, vérifier |
| `log_check.py` | lit le journal d'une instance : traces, erreurs, requêtes SQL refusées, échecs d'envoi de courriel, à revoir (lecture seule) |
| `mail_retry.py` | liste les courriels sortants en échec d'une instance (lecture seule), puis remet en file ceux qu'on choisit par le shell d'Odoo |
| `health_check.py` | vérifie qu'une instance répond et n'expose rien de trop : page de connexion, `/web/health`, TLS, redirection HTTPS, HSTS, gestionnaire de bases, bus, robots.txt, DNS du courriel (lecture seule) |
| `warmup_http.py` | réveille le registre dès que le serveur écoute ; lancé par `run.sh`. `--deep` préchauffe les pages publiques, les paquets d'assets et, avec une clé d'API, les vues |
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
7. **Après une relance vérifiée**, verrou relâché : avec `--warmup-deep`,
   le préchauffage profond de `warmup_http.py` (pages publiques et paquets
   d'assets, sans clé), puis la vérification de santé de l'instance locale
   (`health_check.py`). Leurs constats s'affichent en ATTN au plus et ne
   changent jamais le code de sortie ; un Ctrl-C n'y arrête que l'étape.

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

## health_check.py

```bash
./script/odoo/health_check.py --url https://odoo.example.org
./script/odoo/health_check.py --url odoo.example.org --mail-domain example.org --dkim-selector s1
./script/odoo/health_check.py --local --json
```

`--url` (répétable ; un hôte nu veut dire `https://hote`) sonde à travers
le proxy inverse ; `--local` (avec `--service`, sinon l'unité détectée)
sonde l'adresse que donne la configuration de l'unité, avec `?db=` quand la
base est connue. Une URL qui porte un identifiant (`compte:mdp@`) ou un
autre schéma que http(s) est refusée. Lecture seule : des GET, et un appel
JSON-RPC sans authentification à `/web/webclient/version_info` pour la
version. Aucun cookie, aucun en-tête `Authorization`, aucun proxy de
l'environnement, corps lus jusqu'à 1 Mio, `--timeout` (10 s) sur chaque
requête, connexion TLS et recherche DNS.

| Vérification | OK | ATTN | FAIL | SKIP |
|--------------|----|------|------|------|
| `http_login` | 200 en moins de 5 s | lente, redirection vers le sélecteur de bases, vers HTTP clair ou un autre hôte | aucune réponse, 5xx, autre statut | |
| `web_health` | 200 `pass` | réponse inattendue | aucune réponse, 5xx, `fail` | 404 (route absente) |
| `tls_certificate` | 21 jours ou plus | moins de 21 jours | moins de 7 jours, expiré, refusé (nom, chaîne, autosigné) | URL http, `--local` |
| `http_redirect` | `http://hote/` redirige vers https sur le même hôte | autre hôte, port 80 fermé, autre statut | servi en clair | URL http, `--local` |
| `hsts` | `max-age` ≥ 1 jour | absent, plus court | | pas de 200 sur `/web/login`, URL http, `--local` |
| `db_manager`, `db_selector` | bloqué (401/403/404/3xx), page « disabled » (`list_db = False`) | indéterminé (5xx) ; exposé en `--local` ; sélecteur qui liste les bases | gestionnaire joignable, ou mot de passe maître absent, en `--url` | |
| `list_db` (`--local`) | `False` | absent ou vrai | | |
| `websocket` (`--url`) | relayé (400/426) | 404, aucune réponse | 502/503/504 | `--local` |
| `robots` (`--url`) | servi, ou `Disallow: /` sans ligne `Sitemap:` (pas de site public) | `Disallow: /` avec une ligne `Sitemap:` (l'URL employée n'est pas le domaine du site) | | 404 |
| `mail_spf` | un enregistrement fini par `-all`/`~all` | autre fin | aucun, plusieurs, `+all` | ni dig ni host, recherche en échec |
| `mail_dmarc` | présent (politique affichée) | absent | | ni dig ni host, recherche en échec |
| `mail_dkim` (`--dkim-selector`) | clé trouvée | | absente, clé vide | ni dig ni host, recherche en échec |

Le certificat n'est jugé que par `tls_certificate` : les autres requêtes
HTTPS ne le vérifient pas, pour qu'un certificat refusé donne un seul FAIL
et que les autres vérifications répondent encore. Une `--url` en HTTP clair
ajoute un ATTN `https`. Le DNS passe par `dig` ou `host`, domaine et
sélecteur validés d'abord (pas de `-` en tête) ; une recherche en échec est
un SKIP, jamais « enregistrement absent ». dig rend 0 pour toute réponse,
SERVFAIL et REFUSED compris : le statut de l'en-tête de sa réponse
tranche, et seuls NOERROR et NXDOMAIN sont définitifs. Aucun service web
tiers n'est contacté.

Un déploiement par défaut obtient un FAIL sur `db_manager` par `--url` :
Odoo garde `list_db = True` quand la configuration ne le pose pas, et les
gabarits nginx ne bloquent pas `/web/database`. Poser `list_db = False`, ou
refuser `/web/database` dans nginx.

Clés de `--json` (anglais, stables) : `tool`, `odoo_version`, `targets`
(`kind`, `url`, `odoo_version`), `checks` (`id`, `target`, `status`,
`message`, `hint`, `data`), `summary` (`ok`, `attn`, `fail`, `skip`),
`exit_code`.

| Code | Sens |
|------|------|
| 0 | aucun FAIL (les ATTN sont listés) |
| 1 | au moins un FAIL |
| 2 | vérification impossible (usage, détection, configuration illisible : lancer avec sudo) |
| 130 | interrompu |

## warmup_http.py --deep

```bash
./script/odoo/warmup_http.py --deep --local
./script/odoo/warmup_http.py --deep --url https://odoo.example.org -d BASE --max-pages 50
./script/odoo/warmup_http.py --deep --local --login admin --api-key-file ~/.odoo_key --models res.partner,sale.order
```

Sans `--deep`, rien ne change : une ligne, muet avec `--quiet`, toujours le
code 0, options inconnues transmises à Odoo ; un `--deep` placé après `--`
appartient à Odoo. Avec `--deep` : attente de la première réponse
(`--timeout`, 120 s), session ouverte sur `/web/login?db=BASE`, puis
`/web/login`, `/` et au plus `--max-pages` (20) pages HTML de
`/sitemap.xml` (un index est suivi d'un cran ; seul le chemin de chaque
`<loc>` est gardé, la requête part vers la cible), chacune `--repeat` (4,
16 au plus) fois à la fois. Puis chaque paquet d'assets que ces pages citent
(`/web/assets/…`, et `/web/content/…assets_…` des versions anciennes), une
fois seul — cette requête le construit —, puis `--repeat` − 1 fois à la
fois. Avec `--login` et `--api-key-file` : `common.login` par `/jsonrpc`
avec la clé d'API (Odoo n'accepte une clé que hors d'une connexion
interactive), puis `execute_kw` d'une liste fermée de méthodes de lecture :
`res.users.context_get`, `ir.ui.menu.load_menus` et, pour chaque modèle de
`--models` (`res.partner`), `get_views` (16+) ou `load_views` (15 et avant).
Le fichier de la clé est lu sans suivre de lien ; un fichier lisible par
d'autres comptes reçoit un avertissement. La clé ne part qu'en https, ou
en http vers la boucle locale (`--local`, l'adresse du mode par défaut) :
`--login` avec une URL `http://` sur un autre hôte est refusé (code 2). La
cible est `--url`, `--local` (unité détectée) ou l'adresse du mode par
défaut. Un `<loc>` du sitemap qui n'est ni une URL absolue ni un chemin
commençant par `/` est ignoré : seul son chemin part, vers la cible.

Une requête échoue sur une absence de réponse ou un code ≥ 500, et sur une
erreur JSON-RPC ; un 4xx est compté à part (« non public »).

| Code | Sens |
|------|------|
| 0 | fait, échecs compris |
| 1 | avec `--strict`, au moins un échec |
| 2 | option invalide, fichier de clé illisible, pas de base avec `--login` |
| 130 | interrompu |

### Odoo 12 à 18 (santé, préchauffage)

| Point | Variation |
|-------|-----------|
| `/web/health` | 18 : présent, `db_server_status=1` vérifie PostgreSQL ; 16 et 17 : présent (non vérifié) ; 12 à 15 : absent, SKIP |
| Chemin du bus derrière le proxy | `/websocket` dès 16 (vérifié en 18) ; `/longpolling/poll` jusqu'à 15 ; une version inconnue essaie les deux |
| URL du client web | `/odoo` en 18, `/web` y redirige ; `/web` jusqu'à 17 |
| Chargement des vues par RPC | `get_views` dès 16, `load_views` jusqu'à 15 ; type de vue liste `list` en 18, `tree` avant |
| Clé d'API avec `common.login` | 14+ (hors connexion interactive seulement) ; aucune en 12 et 13 |
| `/robots.txt` | sans website, 18 : `Disallow: /` et des lignes `Allow:`, 404 jusqu'à 17 (non vérifié) ; avec website : une ligne `Sitemap:`, et `Disallow: /` quand l'URL n'est pas le domaine du site (vérifié en 18) |
| Gestionnaire de bases avec `list_db = False` | 18 : 200 avec la page « disabled » (le corps est lu, pas seulement le statut) ; non vérifié de 12 à 17, un 403 est traité aussi |
| Gabarits nginx d'ERPLibre | pas de HSTS de 12 à 15 ; HSTS dans `location /` dès 16 ; aucun ne bloque `/web/database` |
