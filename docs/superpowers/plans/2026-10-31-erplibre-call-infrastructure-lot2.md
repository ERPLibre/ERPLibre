# ERPLibre call infrastructure, lot 2 (production) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From `TODO › Deploy › Call infrastructure`, install coturn and
ntfy in production mode: ntfy behind nginx (existing or installed, Debian
and Arch layouts), certificates from Let's Encrypt (HTTP-01 through nginx
or standalone, or DNS-01 through a certbot DNS plugin) or supplied by hand,
a deploy hook that hands renewed certificates to coturn, TURN over TLS on
5349 (and 443 on a coturn-only host when chosen), private ranges denied,
`external-ip` behind NAT; check and uninstall cover all of it; proven on
throwaway Debian 13 and Arch VMs.

**Architecture:** Same model as lot 1: stdlib builders in
`script/todo/call_infra.py` produce one root `sh` script per action, run
through the `LocalHost` / `SshHost` runners (script from a 0600 file, never
argv), parsed by `@@MARKER` lines. Two new root installers,
`install_nginx.sh` and `install_certbot.sh`, plus a deploy hook template,
are sent inside that script like lot 1's installers. Lot 1's development
mode is unchanged; production is a new `mode` in `Answers` and in the host
state.

**Tech Stack:** Python 3 stdlib, bash installers, nginx, certbot (webroot,
standalone, DNS plugins packaged by the distribution), coturn 4.6, ntfy 2.x,
qemu VMs through `script/qemu/deploy_qemu.py` (no sudo).

**Spec:** `docs/superpowers/specs/2026-10-30-erplibre-call-infrastructure-design.md`
(lot 2 line of « Lots », « Decisions », « Controller's calls », « Constraints »).
User decisions: `tasks/chat/p3-decisions.md` (lot 2 answers at the end).
Recon of lot 1 as built: `tasks/chat/p3-recon-lot2.md` (file:line; `ci` =
`script/todo/call_infra.py`, `cim` = `script/todo/call_infra_menu.py`).
Lot 1 ledger and parked items: `tasks/chat/p3l1-sdd/` (P4: `admin_added`
recorded in a later root run — fixed in Task 6 here).

## Global Constraints

- Everything lot 1 fixed stays true: systems Debian, Ubuntu (Debian path),
  Arch, systemd required; secrets never in argv nor printed (script body
  from a 0600 file, `redact_secrets` on diffs); state
  `/etc/erplibre-call/state.json` root 0600 written last; idempotent rerun
  says « rien à changer »; adopt with diff + backup, never clobber; firewall
  only added to an ACTIVE ufw/nftables after a yes, never port 22, never
  `ufw enable`; stdlib-only modules under `script/todo/` (AST guard); i18n fr
  and en through `t()`; invented test data (`*.exemple.test`, 192.0.2.x,
  198.51.100.x, 203.0.113.x).
- `STATE_VERSION` stays 1: production adds keys; a lot 1 state (no `mode`
  key means `"development"`) is read unchanged.
- Production mode:
  - names default to `ntfy.<domain>` and `turn.<domain>` (each editable);
    one certificate covers both names when both services share the host,
    certbot `--cert-name erplibre-call`;
  - TLS is `letsencrypt` or `supplied`; `none` is refused in production
    (`call_infra_prod_needs_tls`);
  - ntfy listens on `127.0.0.1:<http port>` only, with `behind-proxy: true`,
    `base-url: https://ntfy.<domain>` (no port), `web-root: disable` unless
    the web UI is chosen (`web-root: app`); nginx owns 80 and 443;
  - coturn: 3478 udp+tcp, TLS on 5349, plus 443 only on a host with no
    nginx when 443 is free and the user said yes; media range default
    49152–65535; private ranges denied (the installer's default — the
    production plan never exports `TURN_ALLOW_PRIVATE`); `external-ip` set
    when the TURN name resolves to an address absent from the host's
    interfaces;
  - Let's Encrypt: a staging run first (`certbot certonly --dry-run`, same
    arguments), then the real issuance; email asked (empty → `--register-unsafely-without-email`
    with a warning on screen); challenge HTTP-01 (webroot through nginx at
    `/var/lib/erplibre-call-acme`, outside `/var/lib/erplibre-call` which
    the coturn installer keeps 0750 so nginx could not traverse it; or
    `--standalone` on 80) or DNS-01
    (`--dns-<plugin> --dns-<plugin>-credentials <file>`); never the
    `--nginx` plugin (it edits configs);
  - DNS plugins offered: `cloudflare`, `digitalocean`, `dnsimple`,
    `google`, `linode`, `luadns`, `nsone`, `ovh`, `rfc2136` (each takes a
    credentials file; packages `python3-certbot-dns-<p>` on Debian,
    `certbot-dns-<p>` on Arch). The credentials file is read on the machine
    running `todo.py`, travels in the script body, lands in
    `/etc/erplibre-call/dns/<plugin>.ini` root 0600, and is removed by
    uninstall;
  - coturn-only production host: certificate by certbot standalone on 80
    (through nginx instead when nginx already listens there), nginx
    installed only for ACME, or supplied.
- nginx: never edit another site; our files are
  `erplibre-call-ntfy.conf` (Debian/Ubuntu: `sites-available/` + link in
  `sites-enabled/`; Arch: `/etc/nginx/erplibre-call.d/`, included from
  `nginx.conf` by one `include` line inside `http {}` added as an adoption
  with diff and backup when no existing include directory is used); every
  change is followed by `nginx -t`, and a failing test restores our files
  to their previous content before anything reloads; reload, never restart.
- Uninstall (spec): removes the nginx site and include line it added, the
  ACME directory `/var/lib/erplibre-call-acme`, the deploy hook, the
  renewal timer it added, the DNS credentials; keeps the certificates unless « yes » (kept: the lineage's renewal file is moved to
  `<file>.erplibre-hold` so the timer stops renewing it; a reinstall moves
  it back); purges nginx/certbot packages only if the tool installed them
  and no other nginx site is enabled.
- Never run anything against this machine's ntfy (8080, `/etc/ntfy`,
  `/var/lib/ntfy`), nginx, or the Odoo servers on 8016–8018. Real installs
  only in throwaway VMs. Docker allowed only in Task 1's spike (free ports,
  removed after).
- Docs `.base.md` + mmg. Commits: named files only, bilingual EN then
  `--- FR ---` (FR subject = faithful translation), ≤ 8 lines per language,
  subject ≤ 72, `Assisted-by: Claude Opus 5.5`, no Co-authored-by, identity
  `-c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca"`,
  hooks `-c core.hooksPath=script/git/hooks`. Never push.

## Review Focus

1. **`nginx -t` fails after our site is written** (an existing broken
   config, a duplicate `server_name`, a missing cert path): our files are
   put back, nginx is not reloaded, the run stops with nginx's message, the
   state is not written. Test in Task 4: stub `nginx -t` failing → previous
   site text restored, no `systemctl reload nginx` in the stub log,
   `@@NGINX failed` and exit ≠ 0.
2. **certbot fails** (name not pointing at the host, port 80 blocked, rate
   limit, wrong DNS credentials): the staging dry run fails first, no real
   issuance is attempted, the message carries certbot's last error line,
   nothing claims Let's Encrypt in the state. Test in Task 5: stub certbot
   failing on `--dry-run` → no second certbot call, `@@CERTBOT failed <line>`.
3. **Renewal leaves coturn on the old certificate:** the deploy hook copies
   the renewed lineage to `/etc/erplibre-call/tls/turn.{crt,key}`, updates
   `coturn.applied`, sends SIGUSR2 to coturn (no restart) and reloads nginx;
   a hook call for another lineage changes nothing. Test in Task 3.
4. **An existing nginx already serves `ntfy.<domain>`**, or holds 443 for
   another site: the name taken is refused before install
   (`call_infra_nginx_name_taken` with the file), other sites are never
   touched. Test in Task 6: probe `@@NGINX_NAME ntfy.exemple.test /etc/nginx/sites-enabled/x`
   → `Refusal`.
5. **Host behind NAT** (cloud VM, private interface address): the TURN name
   resolves to 203.0.113.7, absent from `facts.addresses` → `external-ip`
   proposed and confirmed; with it, coturn's config carries
   `external-ip=203.0.113.7`. A name resolving nowhere → the address is
   asked. Test in Task 2 (`plan_install`) and Task 8 (menu).

---

### Task 1: Spike — coturn TLS ports and reload, nginx and certbot layouts (no product commit)

**Files:**
- Create (not committed): `tasks/chat/p3l2-sdd/spike/` scripts and `spike-report.md`

**Interfaces:**
- Produces the facts Tasks 2–5 rely on: (a) can coturn 4.6 serve TURN over
  TLS on two ports at once (5349 and 443) — `alt-tls-listening-port` with
  `no-rfc5780`, or two `tls-listening-port` lines — and which exact lines;
  (b) does `systemctl kill -s USR2 <unit>` (or `kill -USR2 <pid>`) make
  coturn serve a NEW certificate without a restart, and does an allocation
  opened before survive; (c) Arch's packaged `/etc/nginx/nginx.conf`: does
  it include any directory; Debian 13's `sites-enabled` include; (d) the
  renewal timer each family ships with certbot (Debian `certbot.timer`?
  Arch none?) and the certbot version; (e) which of the nine DNS plugins
  exist as packages on Debian 13 and Arch.
- [ ] **Step 1:** (a)(b): official `coturn/coturn` image pinned to Debian
  13's 4.6.x, `--network host` on free ports only (never 3478/5349/443 if
  taken), invented certificates from `script/reverse_proxy/local_cert.py`,
  checked with `script/todo/turn_client.allocate(..., "tls", ...)`.
- [ ] **Step 2:** (c)(d)(e): `debian:trixie` and `archlinux` containers,
  `apt-get install --no-install-recommends nginx certbot` / `pacman -Sy
  nginx certbot`, read the files, `apt-cache policy` / `pacman -Ss` for the
  plugins. Remove every container and image pulled for the spike except the
  coturn pin.
- [ ] **Step 3:** Write `spike-report.md` (commands, answers, exact lines).
  If (a) fails, the controller rules: `turns_443` answer is refused when
  coturn cannot listen twice, and 443 then replaces 5349 only on explicit
  choice. If (b) fails: the hook restarts coturn and the screen says calls
  in progress drop at renewal.

### Task 2: Production answers, plan and configs

**Files:**
- Modify: `script/todo/call_infra.py`
- Test: `test/test_call_infra.py` (class `TestProduction`)

**Interfaces:**
- Consumes: Task 1 report (coturn lines for 443).
- Produces:
  - `MODES = ("development", "production")`; `TLS_MODES = ("none", "supplied", "letsencrypt")`;
    `ACME_METHODS = ("http-nginx", "http-standalone", "dns")`;
    `DNS_PLUGINS` = the nine names of Global Constraints;
    `PROD_MIN_PORT, PROD_MAX_PORT = 49152, 65535`.
  - `Answers` gains (all defaulted, so lot 1 callers keep working):
    `mode: str = "development"`, `ntfy_name: str | None = None`,
    `turn_name: str | None = None` (both None → `public_name`),
    `acme: str | None = None`, `dns_plugin: str | None = None`,
    `dns_credentials: str | None = None`, `email: str = ""`,
    `ntfy_web: bool = False`, `turns_443: bool = False`,
    `nginx: str | None = None` (`"existing"`, `"install"`, or None when no
    nginx is used).
  - `default_names(domain: str) -> tuple[str, str]` → `("ntfy.<domain>", "turn.<domain>")`.
  - `external_ip_for(turn_name: str, addresses, resolve=socket.getaddrinfo) -> tuple[str | None, str]`
    — `(ip, reason)` with reason `"local"` (resolved address is on the
    host: no external-ip), `"nat"` (resolved, not on the host: propose it),
    `"unresolved"` (ask).
  - `plan_install` production rules: refusals `call_infra_prod_needs_tls`,
    `call_infra_prod_needs_nginx` (ntfy in production with `nginx` None),
    `call_infra_acme_method` (method not allowed for the services:
    `http-standalone` with nginx answering 80; `http-nginx` with nginx None),
    `call_infra_dns_plugin` (unknown plugin or no credentials),
    `call_infra_turns_443` (443 busy, nginx used, or Task 1 says coturn
    cannot listen twice); supplied certificate checked for EVERY name used
    (ntfy name and/or turn name); `new_state["mode"]` from answers; media
    range default 49152–65535 in production when the answers keep lot 1's
    default.
  - `coturn_config(answers)` (the Python mirror of the installer) in
    production: the `denied-peer-ip` lines identical to
    `install_coturn.sh` `DENIED_PEER_RANGES`, the 443 line(s) from Task 1
    when `turns_443`, `external-ip` when set; `_coturn_block` exports no
    `TURN_ALLOW_PRIVATE` in production and exports `TURN_ALT_TLS_PORT=443`
    when `turns_443`.
  - `ntfy_config(answers)` in production: `listen-http: 127.0.0.1:<port>`,
    no `listen-https`/`cert-file`/`key-file`, `behind-proxy: true`,
    `web-root: disable|app`, `base-url: https://<ntfy_name>`;
    `ntfy_base_url` drops the port in production; `needed_ports` and
    `firewall_rules` count 80/443 for nginx (service label `"nginx"`),
    80 for standalone certbot (label `"certbot"`), 5349 and optional 443
    for coturn, never the loopback ntfy port.
  - `state_answers` reads every new key back (a lot 1 state → mode
    development).
- [ ] **Step 1: Failing tests:** production with `tls="none"` → `Refusal("call_infra_prod_needs_tls")`;
  ntfy prod without nginx → `call_infra_prod_needs_nginx`; supplied cert
  covering `turn.exemple.test` but not `ntfy.exemple.test` →
  `call_infra_cert_name_missing` naming `ntfy.exemple.test`;
  `coturn_config` production contains `denied-peer-ip=10.0.0.0-10.255.255.255`
  (same lines as the installer: a test parses both and compares) and no
  line when development; `external_ip_for("turn.exemple.test", ("10.0.0.5",), resolve=fake→203.0.113.7)`
  → `("203.0.113.7", "nat")`; same with addresses containing 203.0.113.7 →
  `(…, "local")`; resolver raising → `(None, "unresolved")`; ntfy prod
  config has `behind-proxy: true`, `web-root: disable`, base-url without
  port, `listen-http: 127.0.0.1:`; firewall rules production both services
  = 80/tcp nginx, 443/tcp nginx, 3478 udp+tcp, 5349/tcp, 49152:65535/udp,
  and no rule for the ntfy loopback port; lot 1 state (no `mode`) →
  `state_answers(...).mode == "development"`; rerun with the same
  production answers → `nothing_to_do`.
- [ ] **Step 2–4:** `./script/test/run_unit_test.sh test/test_call_infra.py` FAIL → implement → PASS.
- [ ] **Step 5: Commit** `[ADD] call infra: production answers, plan, coturn and ntfy configs`.

### Task 3: Deploy hook and coturn second TLS port

**Files:**
- Create: `script/install/erplibre_call_deploy_hook.sh`
- Modify: `script/install/install_coturn.sh`
- Test: `test/test_install_coturn.py`, new `test/test_deploy_hook.py`

**Interfaces:**
- Consumes: Task 1 (a)(b).
- Produces:
  - `install_coturn.sh` env `TURN_ALT_TLS_PORT` (empty or a port ≠ the
    other ports; only with a certificate) writing Task 1's line(s).
  - The hook, installed by Task 6 as `/etc/letsencrypt/renewal-hooks/deploy/erplibre-call`
    (root 0755): acts only when `basename "$RENEWED_LINEAGE"` is
    `erplibre-call`; when `/etc/erplibre-call/tls/` exists and coturn is
    in the state, copies `fullchain.pem` → `turn.crt` and `privkey.pem` →
    `turn.key` (root:<coturn group> 0640, via mktemp + mv, refusing
    symlinked targets), rewrites `/etc/erplibre-call/coturn.applied` with
    the digest `install_coturn.sh` computes (same function, extracted and
    shared by copy-check test), sends SIGUSR2 per Task 1 (or restarts per
    the Task 1 ruling); then `nginx -t && systemctl reload nginx` when
    nginx is active. Prints `@@HOOK <action>` lines; exit ≠ 0 on any
    failed copy.
- [ ] **Step 1: Failing tests** (stubs for `systemctl`, `kill`, `nginx`,
  `chown`, temp root via an env prefix as the lot 1 tests do): another
  lineage → no copy, no signal; our lineage → files copied with mode 0640,
  `coturn.applied` equals the digest `install_coturn.sh` computes for the
  same files (Review Focus 3), USR2 sent, no `restart`; symlinked
  `turn.key` target → refused, exit ≠ 0; nginx inactive → no reload;
  `install_coturn.sh` with `TURN_ALT_TLS_PORT=443` writes Task 1's line,
  without certificate it dies.
- [ ] **Step 2–4:** `./script/test/run_unit_test.sh test/test_install_coturn.py test/test_deploy_hook.py` FAIL → implement → PASS.
- [ ] **Step 5: Commit** `[ADD] call infra: certbot deploy hook hands renewals to coturn`.

### Task 4: nginx installer and ntfy site

**Files:**
- Create: `script/install/install_nginx.sh`
- Test: `test/test_install_nginx.py`

**Interfaces:**
- Consumes: Task 1 (c); the Odoo 18 SSL template `script/nginx/template_nginx_ssl_odoo_18.0.txt` as a model only.
- Produces: `bash install_nginx.sh` with env:
  `NGINX_STAGE` (`acme` = port 80 only: ACME location + redirect to https;
  `full` = 80 as acme + 443 ntfy proxy), `NGINX_NAMES` (space-separated
  names answered on 80), `NGINX_NTFY_NAME` (empty on a coturn-only host),
  `NGINX_UPSTREAM_PORT`, `NGINX_CERT_FILE`/`NGINX_KEY_FILE` (paths on the
  host: the lineage `live/erplibre-call/` or `/etc/erplibre-call/tls/site.{crt,key}`
  root 0600 for a supplied certificate), `NGINX_ACME_ROOT`
  (`/var/lib/erplibre-call-acme`), `NGINX_INSTALL=1` (install the package
  when absent), `NGINX_ADOPT_INCLUDE=1` (Arch: the caller agreed to the
  include line). Functions: `family`, `layout` (`debian` when
  `sites-enabled` is included, `confd` when `conf.d/*.conf` is included,
  else `arch-include`), `site_path`, `write_site`, `ensure_include`,
  `test_and_reload` (backup of our previous file text, `nginx -t`, restore
  on failure, `systemctl reload nginx` or `enable --now` when it was not
  running). Site content: `map $http_upgrade $erplibre_call_upgrade`,
  `proxy_http_version 1.1`, `Upgrade`/`Connection` headers,
  `proxy_buffering off`, `proxy_read_timeout 3h`, `client_max_body_size 20m`,
  `X-Forwarded-For`/`X-Forwarded-Proto`/`Host`, `server_name` exact (never
  `default_server`), TLS protocols 1.2 and 1.3. Markers `@@NGINX_LAYOUT`,
  `@@NGINX_SITE <path>`, `@@NGINX_INCLUDE <path>` (when added),
  `@@NGINX active|failed <line>`; `@@NGINX_INSTALLED 1` when it installed
  the package.
- [ ] **Step 1: Failing tests** (`extraire_fonction`, stubs for `apt-get`,
  `pacman`, `nginx`, `systemctl`, temp root): Debian layout writes
  `sites-available/erplibre-call-ntfy.conf` and the link; Arch default
  `nginx.conf` (canned from Task 1) without `NGINX_ADOPT_INCLUDE` → exit ≠ 0
  and nginx.conf unchanged, with it → one `include /etc/nginx/erplibre-call.d/*.conf;`
  line inside `http {` and a `.bak-` copy; `acme` stage has no `listen 443`;
  `full` stage has the websocket headers and `proxy_pass http://127.0.0.1:<port>`;
  no `default_server` anywhere; failing `nginx -t` (Review Focus 1) →
  previous site text restored, no reload; second run with the same env →
  no reload (`@@NGINX active`, file unchanged).
- [ ] **Step 2–4:** `./script/test/run_unit_test.sh test/test_install_nginx.py` FAIL → implement → PASS.
- [ ] **Step 5: Commit** `[ADD] install_nginx: ntfy site behind nginx, Debian and Arch layouts`.

### Task 5: certbot installer

**Files:**
- Create: `script/install/install_certbot.sh`
- Test: `test/test_install_certbot.py`

**Interfaces:**
- Consumes: Task 1 (d)(e).
- Produces: `bash install_certbot.sh` with env `CERTBOT_NAMES`,
  `CERTBOT_METHOD` (`webroot`|`standalone`|`dns`), `CERTBOT_WEBROOT`,
  `CERTBOT_DNS_PLUGIN`, `CERTBOT_DNS_CREDENTIALS` (path on the host, root
  0600), `CERTBOT_EMAIL` (empty → `--register-unsafely-without-email`),
  `CERTBOT_SKIP_STAGING=1` (only when the lineage already holds exactly
  these names: a rerun does not re-issue). Steps: install `certbot` and the
  plugin package (Debian `python3-certbot-dns-<p>`, Arch `certbot-dns-<p>`);
  move back a held renewal file (`.erplibre-hold`); staging run
  `certbot certonly --dry-run --non-interactive --agree-tos --cert-name erplibre-call <method args> -d …`;
  on success the real run without `--dry-run` and with `--keep-until-expiring`
  and `--expand`; ensure a renewal timer (the packaged one when Task 1
  found it, else `erplibre-call-certbot.{service,timer}` twice a day with
  `certbot renew --quiet`, marker `@@CERTBOT_TIMER <unit> added`). Markers
  `@@CERTBOT staging-ok`, `@@CERTBOT issued <lineage>` or
  `@@CERTBOT unchanged <lineage>`, `@@CERTBOT failed <last error line>`
  (exit ≠ 0), `@@CERTBOT_INSTALLED 1` when it installed the package.
  Never `--nginx`, never prints the credentials file.
- [ ] **Step 1: Failing tests** (stubs; certbot stub logs its argv to a
  file): webroot args `--webroot -w /var/lib/erplibre-call-acme`; dns args
  `--dns-ovh --dns-ovh-credentials /etc/erplibre-call/dns/ovh.ini`; first
  call carries `--dry-run`, second does not; dry run failing → only one
  certbot call and `@@CERTBOT failed` with the stub's last stderr line
  (Review Focus 2); empty email → `--register-unsafely-without-email`;
  Arch without packaged timer → the two unit files written; never
  `--nginx` in any argv; held renewal file moved back before certbot runs.
- [ ] **Step 2–4:** `./script/test/run_unit_test.sh test/test_install_certbot.py` FAIL → implement → PASS.
- [ ] **Step 5: Commit** `[ADD] install_certbot: staging then issuance, HTTP-01 and DNS-01`.

### Task 6: Production install script and probe

**Files:**
- Modify: `script/todo/call_infra.py`
- Test: `test/test_call_infra.py` (classes `TestProductionProbe`, `TestProductionInstall`)

**Interfaces:**
- Consumes: Tasks 2–5 (installers read from disk, sent compressed as lot 1 does).
- Produces:
  - probe additions: `@@NGINX <active|inactive|absent> <layout>`,
    `@@NGINX_NAME <name> <file>` for every `server_name` in enabled sites
    not written by the tool, `@@CERTBOT <version|absent>`,
    `@@LINEAGE erplibre-call <names…>` (from `certbot certificates`, read
    only), `@@HELD erplibre-call` for a held renewal file; `HostFacts`
    gains `nginx: dict | None`, `certbot: dict | None` (defaulted).
  - `plan_install` refusal `call_infra_nginx_name_taken` (Review Focus 4);
    nginx and certbot `PROCESSES` entries so their ports are not « busy »
    when the plan uses them.
  - `install_script` production order, each step stopping the script on
    failure before the state: coturn and ntfy installers (ntfy on loopback;
    coturn without certificate on a Let's Encrypt first run, `no-tls`);
    `install_nginx.sh` stage `acme` (when nginx is used;
    `NGINX_ACME_ROOT=/var/lib/erplibre-call-acme`, certbot's `-w`); DNS
    credentials placed; `install_certbot.sh`; hook installed and run once with
    `RENEWED_LINEAGE=/etc/letsencrypt/live/erplibre-call` (which gives
    coturn its certificate and the TLS port); `install_nginx.sh` stage
    `full`; then the `@@ACTIVE` checks and the state (with `nginx`,
    `certbot`, `hook` records: paths, `installed_by_tool`, method, plugin,
    names, timer added). A supplied certificate in production skips
    certbot and the hook, places `site.{crt,key}` for nginx and
    `turn.{crt,key}` for coturn.
  - `admin_added` and firewall records are written by the same root run
    that creates them (lot 1 parked P4).
- [ ] **Step 1: Failing tests:** canned Debian probe with an enabled
  foreign site `server_name ntfy.exemple.test` → refusal naming the file;
  production install script order: index of `install_nginx` stage acme <
  `install_certbot` < hook run < stage full < state write; certbot failure
  marker stops before the state (text guarded by `||` exit, as lot 1's
  active checks); DNS credentials appear only base64 in the script, never
  in clear; supplied production → no certbot, `site.crt` placed 0600;
  `admin_added` written in the install run; a rerun with an unchanged
  lineage passes `CERTBOT_SKIP_STAGING=1` and `nothing_to_do` holds.
- [ ] **Step 2–4:** `./script/test/run_unit_test.sh test/test_call_infra.py` FAIL → implement → PASS.
- [ ] **Step 5: Commit** `[ADD] call infra: production install, nginx, certbot and hook order`.

### Task 7: Check and uninstall in production

**Files:**
- Modify: `script/todo/call_infra.py`, `script/todo/turn_client.py`
- Test: `test/test_call_infra.py` (`TestProductionCheck`, `TestProductionUninstall`), `test/test_turn_client.py`

**Interfaces:**
- Produces:
  - `turn_client.permission(host, port, transport, username, key, peer: str, timeout=5.0, cafile=None, server_name=None) -> Allocation`
    — Allocate then CreatePermission for `peer`; `ok False` with error
    starting `"403"` when coturn refuses the peer.
  - check lines: `letsencrypt` counts as TLS everywhere `supplied` does;
    `cert-issuer` (issuer CN; a staging issuer « (STAGING) » → `ok False`);
    `renewal` (hook file present and executable, timer active) for
    `letsencrypt`; `ntfy-health` through `https://<ntfy_name>/v1/health`
    on 443 in production; `private-denied` in production (permission to
    10.0.0.1 refused → `ok True`; granted → `ok False`, « relais ouvert vers
    le réseau privé »). New keys in `CHECK_KEYS`.
  - uninstall per Global Constraints: nginx site and link or include line
    (restored from backup), ACME directory `/var/lib/erplibre-call-acme`,
    hook, added timer, DNS credentials, lineage
    held (or `certbot delete --cert-name erplibre-call` with
    `remove_data`), packages purged only when installed by the tool and no
    other site is enabled; nginx reloaded after `nginx -t`.
- [ ] **Step 1: Failing tests:** `permission` against the lot 1 fake TURN
  server answering 403 to CreatePermission → `ok False`, error `"403 …"`;
  `check_local` production with fake permission granted → `private-denied ok False`;
  staging issuer → `cert-issuer ok False`; uninstall script for a
  production state removes `/etc/letsencrypt/renewal-hooks/deploy/erplibre-call`,
  moves `renewal/erplibre-call.conf` to `.erplibre-hold` without
  `remove_data`, runs `certbot delete` with it, never purges nginx when the
  state says `installed_by_tool: false`; uninstall twice → `@@NOTHING`.
- [ ] **Step 2–4:** `./script/test/run_unit_test.sh test/test_call_infra.py test/test_turn_client.py` FAIL → implement → PASS.
- [ ] **Step 5: Commit** `[ADD] call infra: production check and uninstall`.

### Task 8: Menu questions for production

**Files:**
- Modify: `script/todo/call_infra_menu.py`, `script/todo/todo_i18n.py`
- Test: `test/test_todo_call_infra.py`

**Interfaces:**
- Consumes: Tasks 2, 6, 7.
- Produces, in `_call_infra_ask_answers`, after the services:
  - mode: `[1] Développement` / `[2] Production`;
  - production: domain → names proposed `ntfy.<d>`, `turn.<d>` (editable);
    certificate `[1] Let's Encrypt` / `[2] Fourni`; Let's Encrypt
    challenge `[1] HTTP (port 80)` / `[2] DNS (clé d'API)`; HTTP on a
    coturn-only host: `[1] certbot seul sur le port 80` / `[2] nginx
    installé pour le défi` (nginx already on 80 → nginx used, said);
    DNS: plugin from `DNS_PLUGINS`, credentials file path (read locally,
    never echoed); email (empty allowed, warning); ntfy web UI (default
    no); nginx existing or installed (detected, said); coturn on 443 asked
    only on a host without nginx and with 443 free; `external_ip_for` →
    `local`: nothing asked; `nat`: « IP publique 203.0.113.7 ? » confirm or
    type; `unresolved`: typed (empty refused in production);
  - summary shows mode, names, certificate source, challenge, private
    ranges denied, the 80/443 rules; a resolved name that matches neither
    the host's addresses nor the confirmed external IP prints the DNS
    warning before the yes (Let's Encrypt would fail).
  - every new screen string fr + en.
- [ ] **Step 1: Failing tests** (FakeHost + scripted answers as lot 1):
  production both services Let's Encrypt HTTP through installed nginx →
  the install script run contains the nginx and certbot payloads and the
  state shows `mode production`; DNS plugin path with a credentials file →
  its content never printed (captured output); NAT case shows the proposed
  IP and the plan carries it; development flow unchanged (lot 1 tests
  still green); every `t()` literal exists in fr and en.
- [ ] **Step 2–4:** `./script/test/run_unit_test.sh test/test_todo_call_infra.py test/test_todo_i18n.py test/test_i18n_duplicates.py test/test_todo_menu.py` FAIL → implement → PASS.
- [ ] **Step 5: Commit** `[ADD] todo call infra: production questions, names, certificate source`.

### Task 9: Long test, production scenarios

**Files:**
- Modify: `long_test/call_infra.py`, `long_test/README.base.md` (+ mmg)
- Test: `test/test_longtest_call_infra.py`

**Interfaces:**
- Consumes: the same builders as the menu (the AST drift guard of lot 1
  extended to the production path).
- Produces: `--scenario dev|prod|tous` (default `tous`) next to
  `--distro`. Production scenario on each distro (VM names
  `long-call-infra-<distro>`, run one after the other):
  1. VM, ssh, cloud-init (Arch pacman preamble); Debian enables ufw after
     `ufw allow 22/tcp`;
  2. invented CA and a certificate for `ntfy.call.exemple.test`,
     `turn.call.exemple.test` and the VM IP (`local_cert.issue`);
  3. install production, both services, supplied certificate, nginx
     installed (Arch: include line adopted), firewall yes;
  4. check from the host with the CA: `turn-udp`, `turn-tcp`, `turn-tls`
     (server name `turn.call.exemple.test`), `ntfy-health` through nginx
     on 443 (Host `ntfy.call.exemple.test`), `private-denied`, firewall,
     services — all `ok True`;
  5. deploy hook by hand: a NEW certificate (other serial) placed as a
     fake lineage `/etc/letsencrypt/live/erplibre-call/`, the hook text from
     the product run with `RENEWED_LINEAGE`; coturn `MainPID` unchanged,
     `turn-tls` now sees the new serial, nginx serves it too;
  6. rerun → `nothing_to_do`;
  7. uninstall with `remove_data` → no nginx site/include/link, no hook,
     no `/etc/erplibre-call`, nginx purged (installed by the tool), ports
     closed; uninstall again → `@@NOTHING`;
  8. destroy unless `--garder`.
- [ ] **Step 1: Failing unit tests:** `--dry-run --scenario prod` lists
  the steps above for both distros and creates nothing; the hook step's
  serial comparison is computed from the two certificates, not a constant;
  every `subprocess.run(timeout=…)` inside a `try` (AST); README section
  updated in both halves.
- [ ] **Step 2–4:** `./script/test/run_unit_test.sh test/test_longtest_call_infra.py test/test_todo_longtest.py` FAIL → implement → PASS.
- [ ] **Step 5: Commit** `[ADD] long_test call_infra: production with nginx, hook by hand`.
- [ ] **Step 6 (part B, controller):** `./long_test/call_infra.py --distro tous --scenario tous`,
  then `--detruire`; logs in `tasks/chat/p3l2-sdd/partB/`.

### Task 10: Documentation and changelog

**Files:**
- Modify: `CHANGELOG.base.md`, the call infrastructure section of the docs
  that describe the menu (grep `Call infrastructure` in `*.base.md`), then mmg.
- [ ] **Step 1:** document production mode (names, certificate sources,
  DNS plugins and credentials file, staging first, renewal hook, nginx
  layouts, private ranges denied, external-ip, uninstall keeps
  certificates unless yes).
- [ ] **Step 2:** CHANGELOG Added/Security lines; English bullets quote the
  English screen strings.
- [ ] **Step 3:** mmg; doc tests PASS.
- [ ] **Step 4: Commit** `[UPD] doc: call infrastructure production mode`.
