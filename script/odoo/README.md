
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
