# ERPLibre call infrastructure, lot 1 (host installer, packages and systemd) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From `TODO › Deploy › Call infrastructure`, install coturn, ntfy or
both on the local machine or a host reached over ssh (Debian, Ubuntu, Arch),
by system packages with systemd, in development mode (http, or https with a
supplied certificate), open an active firewall after confirmation, adopt a
coturn or ntfy already there, check the result from outside, and uninstall
it; proven on throwaway Debian 13 and Arch VMs.

**Architecture:** Pure stdlib modules build `sh` scripts and parse their
`@@MARKER` output (the `ntfy_mobile.py` model); scripts travel to the host
inside one `sh -c` argument through the existing `LocalHost` / `SshHost`
runners. Two root installers (`install_coturn.sh`, the reworked
`install_ntfy.sh`) do the system work and are sent base64 in that script.
What was installed lives in `/etc/erplibre-call/state.json` on the host.
A stdlib STUN/TURN client checks coturn from the machine running `todo.py`.

**Tech Stack:** Python 3 stdlib (`hashlib`, `hmac`, `socket`, `ssl`,
`json`, `base64`), POSIX `sh` and bash installers, coturn 4.6 (packages),
ntfy 2.x, ufw / nftables, qemu VMs through `script/qemu/deploy_qemu.py`.

**Spec:** `docs/superpowers/specs/2026-10-30-erplibre-call-infrastructure-design.md`
(lot 1 line of « Lots », « Decisions », « Controller's calls », « Constraints »).
User decisions log: `tasks/chat/p3-decisions.md`. Recon maps:
`tasks/chat/p3-recon-{ntfy,todo,tests,odoo}.md` (file:line references).

## Global Constraints

- Systems: Debian, Ubuntu (same path as Debian), Arch; anything else is
  refused with a message naming what is supported. systemd required.
- Lot 1 offers ONLY the package + systemd method and ONLY development mode;
  production (nginx, Let's Encrypt, TLS on 5349 in prod, private ranges
  denied) is lot 2, containers lot 4, « add an Odoo server » lot 3. The menu
  shows no entry for what is not built.
- Development: TLS « none » (http, TURN without TLS, the screen says « réseau
  local seulement ») or « supplied » (certificate and key files given to
  `todo.py`, handed straight to ntfy and coturn). Private address ranges stay
  allowed in development (no `denied-peer-ip`), said on screen.
- Ports (defaults, asked): TURN 3478 (udp+tcp), TURNS 5349 (tcp, only with a
  supplied certificate), media range 49152–49252 udp in development, ntfy
  8080 in http, 8443 in https.
- coturn credentials live in coturn's own SQLite user database
  (`userdb=/var/lib/erplibre-call/turndb`, owned by coturn's service user),
  never in `turnserver.conf`. Lot 1 creates one fixed check account
  `erplibre-check` with long-term credentials.
- Host state: `/etc/erplibre-call/state.json`, root:root 0600, the only
  record of what the tool did. No secret is kept on the machine running
  `todo.py`. Secrets never travel in argv or printed commands (inside the
  script body as base64 only; printed commands go through
  `execute.redact_secrets`).
- Firewall: never enable a firewall, never touch ssh's rule; only ADD allow
  rules to an ACTIVE ufw or nftables, after showing them and a yes; record
  each rule in the state; remind of the cloud provider's firewall.
- Idempotent: a second install with the same answers changes nothing and
  says « rien à changer ».
- Adopt, never clobber: an existing coturn or ntfy config not written by the
  tool is shown as a unified diff, backed up (`<file>.bak-<stamp>`), and
  recorded as adopted with its backup path; ntfy users and tokens stay.
  Uninstall of an adopted service restores the backup and leaves the package.
- Never run anything against this development machine's own ntfy (port
  8080, `/etc/ntfy`, `/var/lib/ntfy`) nor the Odoo servers on 8016–8018: unit
  tests use fake hosts or `LocalHost(sudo=())` in temp dirs; real installs
  happen only in the throwaway VMs.
- Modules under `script/todo/` added by this lot are stdlib only (an AST
  guard test, as `test_ntfy_mobile.py` TestStdlibOnly).
- i18n: every screen string through `t()` with fr and en in
  `script/todo/todo_i18n.py`, French first in the user's eyes; test data
  invented (`*.exemple.test`, 192.0.2.x / 198.51.100.x).
- Docs: edit `.base.md`, regenerate with mmg. Commits: named files only,
  bilingual EN then `--- FR ---`, ≤ 8 lines per language, subject ≤ 72,
  `Assisted-by: Claude Opus 5.5`, no Co-authored-by, identity
  `-c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca"`,
  hooks `-c core.hooksPath=script/git/hooks`. Never push.

## Review Focus

1. **ssh drops mid-install** (laptop sleeps, network cut): the host must not
   be left with a state file claiming success; the state is written last,
   and a rerun converges. Test in Task 5: `install_script` writes the state
   only after every service reported `@@ACTIVE <svc> active`.
2. **sudo asks a password over ssh**: the prompt must reach the user
   (`ssh -t`), and a wrong password must end as a clear refusal, not a
   traceback. Test in Task 8: a fake host returning code 1 with
   « sudo: 3 incorrect password attempts » gives the « sudo refusé » line.
3. **Supplied certificate not matching its key, expired, or missing the
   host's name**: refused before anything is installed, with the reason.
   Test in Task 5: `plan_install` raises `Refusal("call_infra_cert_key_mismatch")`
   / `"call_infra_cert_expired"` / `"call_infra_cert_name_missing"`.
4. **A port already taken on the host** (another service on 3478 or 8080):
   refused with the process name before installing. Test in Task 5:
   probe output `@@PORT tcp 8080 nginx` makes `plan_install` raise
   `Refusal("call_infra_port_busy")` carrying port and process.
5. **Uninstall twice, or uninstall with no state**: the second run says
   « rien à désinstaller » and changes nothing. Test in Task 7.

---

### Task 1: Stdlib STUN/TURN client

**Files:**
- Create: `script/todo/turn_client.py`
- Test: `test/test_turn_client.py`

**Interfaces:**
- Produces:
  - `long_term_key(username: str, realm: str, password: str) -> bytes` — MD5 of `username:realm:password` (RFC 5389 §15.4).
  - `rest_credentials(secret: str, user: str, expiry: int) -> tuple[str, str]` — `("<expiry>:<user>", base64(HMAC-SHA1(secret, username)))`.
  - `@dataclass(frozen=True) class Allocation: ok: bool; relayed: tuple[str, int] | None; error: str | None` (error = TURN error code and reason, or `"timeout"`, `"refused"`, `"tls"`).
  - `binding(host: str, port: int, transport: str = "udp", timeout: float = 5.0) -> tuple[str, int] | None` — STUN Binding, the mapped address.
  - `allocate(host, port, transport, username, key: bytes, timeout=5.0, cafile=None, server_name=None) -> Allocation` — transport `"udp"|"tcp"|"tls"`; does the 401 → nonce/realm → authenticated Allocate (REQUESTED-TRANSPORT UDP, MESSAGE-INTEGRITY, FINGERPRINT), then a Refresh with lifetime 0 to free it.

- [ ] **Step 1: Write failing tests**: RFC 5769 test vectors (§2.1 sample request: MESSAGE-INTEGRITY and FINGERPRINT bytes match for the vector's password "VOkJxbRl1RmTxUk/WvJxBt"); `long_term_key("user","realm","pass")` equals `hashlib.md5(b"user:realm:pass").digest()`; `rest_credentials("s3cret","odoo",1893456000)` username `"1893456000:odoo"` and password = base64 HMAC-SHA1 computed in the test; `allocate` against an in-process fake UDP server (thread on 127.0.0.1, port 0) that answers 401 with REALM+NONCE then a success with XOR-RELAYED-ADDRESS 192.0.2.10:50000 → `Allocation(True, ("192.0.2.10", 50000), None)`; a fake answering 401 twice → `ok False`, error starts with `"401"`; no answer → error `"timeout"` within timeout+1 s; TCP framing (fake TCP server) same success; stdlib-only AST guard.
- [ ] **Step 2: Run** `./script/test/run_unit_test.sh test/test_turn_client.py` — expected FAIL (module missing).
- [ ] **Step 3: Implement** `script/todo/turn_client.py` with the signatures above (header comment says how it works; no story).
- [ ] **Step 4: Run** the same command — expected PASS.
- [ ] **Step 5: Commit** `script/todo/turn_client.py test/test_turn_client.py` — `[ADD] call infra: stdlib STUN/TURN client for check`.

### Task 2: Spike — coturn database credentials (no product commit)

**Files:**
- Create (not committed): `tasks/chat/p3l1-sdd/spike/` scripts and `spike-report.md`

**Interfaces:**
- Consumes: `turn_client.allocate`, `long_term_key`, `rest_credentials` (Task 1).
- Produces: a ledger finding consumed by lot 3 and by Task 4: (a) does coturn
  accept SEVERAL shared secrets in its SQLite database (`turnadmin -s
  <secret> -r <realm> -b <db>` twice; both secrets' REST credentials
  allocate)? (b) with at least one secret present, does a long-term user of
  the same database (`turnadmin -a -u erplibre-check -r <realm> -p <pw> -b
  <db>`) still allocate? (c) does adding/removing a secret or a user take
  effect WITHOUT restarting coturn (allocate before and after, same
  process)? (d) the exact `turnserver.conf` lines that made it work.

- [ ] **Step 1:** Run the official `coturn/coturn` image (pin the 4.6.x tag
  matching Debian 13's package) with `--network host` on free ports chosen by
  the script (never 3478 if taken; never touch ntfy or Odoo), a config with
  `lt-cred-mech`, `use-auth-secret`, `realm=spike.exemple.test`,
  `userdb=/var/lib/turn/turndb` on a temp volume, `listening-ip=127.0.0.1`,
  `min-port/max-port` small range.
- [ ] **Step 2:** Answer (a)–(d) with `turn_client`; if (b) fails, also try
  without `use-auth-secret` to confirm users alone work. Remove the container
  and volume.
- [ ] **Step 3:** Write `spike-report.md` (commands, answers, conf lines).
  Controller records `Ruling` lines from it. If (b) fails: lot 1 is unchanged
  (no secret exists in lot 1; the check account is a long-term user), the
  spec's « Left to the builder » refusal applies in lot 3.

### Task 3: ntfy installer reworked for remote, adoption and https on a chosen port

**Files:**
- Modify: `script/install/install_ntfy.sh`
- Modify: `test/test_install_ntfy.py`, `test/test_ntfy_mobile.py` (heredoc contract)

**Interfaces:**
- Produces (env inputs of `install_ntfy.sh`, kept: `NTFY_PORT`, `NTFY_BASE_URL`, `NTFY_PUBLIC`, `NTFY_ADMIN_USER`, `NTFY_GARDER_CONFIG`; new or changed):
  - `NTFY_HTTPS_PORT` (default empty; with `NTFY_CERT_FILE`/`NTFY_KEY_FILE` set, `listen-https: ":$NTFY_HTTPS_PORT"`, default 8443 instead of the hard-coded 443);
  - `NTFY_NON_INTERACTIVE=1`: never calls an AUR helper (Arch: `pacman -S --noconfirm ntfy` when the package exists in the sync repos, else the binary path), never prompts;
  - exit code non-zero when the service is not `active` after `enable_service`; last line `@@ACTIVE ntfy <state>`;
  - the admin password line `@@ADMIN_PASSWORD <pw>` only when created (the menu shows it once and drops it).
- Fixes the three defects: binary unit `ReadWritePaths` includes `/var/lib/ntfy`; `user.db` is `chown ntfy:ntfy` after `ensure_admin_user`; `ensure_admin_user` passes `--config` and runs with `NTFY_*` stripped (`env -u` each var).

- [ ] **Step 1: Failing tests** (pattern `extraire_fonction`): `configure_ntfy` with `NTFY_HTTPS_PORT=8443` + cert/key writes `listen-https: ":8443"`; unit text from `create_systemd_service` contains `/var/lib/ntfy` in `ReadWritePaths`; `ensure_admin_user` stubbed `ntfy` sees `--config` and no `NTFY_BASE_URL` in its env; `install_arch` with `NTFY_NON_INTERACTIVE=1` and a stub `pacman -Si ntfy` success calls `pacman -S --noconfirm ntfy`, never `yay`; `main` returns non-zero when stub `systemctl is-active` prints `failed`.
- [ ] **Step 2: Run** `./script/test/run_unit_test.sh test/test_install_ntfy.py test/test_ntfy_mobile.py` — FAIL.
- [ ] **Step 3: Implement** in `install_ntfy.sh` (keep the existing refusal of a permissive config, keep « config with auth-default-access kept untouched »: adoption edits are made by Task 5's script, not by the installer).
- [ ] **Step 4: Run** — PASS. **Step 5: Commit** `[FIX] install_ntfy: remote-ready, https port, unit and user.db ownership`.

### Task 4: coturn installer

**Files:**
- Create: `script/install/install_coturn.sh`
- Test: `test/test_install_coturn.py`

**Interfaces:**
- Consumes: Task 2 finding (conf lines for the user database).
- Produces: `sudo env TURN_*=… bash install_coturn.sh` (bash, `set -euo pipefail`, `log`/`die`, French comments without accents as `install_asterisk.sh`), env inputs:
  `TURN_REALM` (required), `TURN_PORT`=3478, `TURN_TLS_PORT`=5349,
  `TURN_MIN_PORT`=49152, `TURN_MAX_PORT`=49252, `TURN_CERT_FILE`/`TURN_KEY_FILE`
  (both or none; copied to `/etc/erplibre-call/tls/turn.{crt,key}`,
  root:<coturn user> 0640), `TURN_EXTERNAL_IP` (optional),
  `TURN_CHECK_PASSWORD` (required; read from the environment the calling
  script exports, never argv), `TURN_GARDER_CONFIG=1` (adoption: the caller
  has already backed up and agreed).
  Functions: `detect_os`, `family` (debian|arch; anything else → `die`),
  `install_packages` (apt-get `coturn` + `sqlite3`; pacman `coturn` + `sqlite`),
  `service_user` (Debian `turnserver`; Arch read from the package's unit
  `User=`), `unit_name` (Debian `coturn`, Arch `turnserver`), `write_config`
  (`/etc/turnserver.conf` root:<user> 0640, first line
  `# erplibre-call: managed`, lines: `listening-port`, `tls-listening-port`
  and `cert`/`pkey` only with a certificate, `min-port`, `max-port`,
  `fingerprint`, `lt-cred-mech`, `realm`, `userdb=/var/lib/erplibre-call/turndb`,
  `no-cli`, `no-multicast-peers`, `external-ip` when given, plus Task 2's
  lines; no `denied-peer-ip` in this lot), `enable_default` (Debian
  `/etc/default/coturn` `TURNSERVER_ENABLED=1` when the file exists),
  `ensure_check_user` (`turnadmin -a -b <db> -u erplibre-check -r $TURN_REALM
  -p "$TURN_CHECK_PASSWORD"`, idempotent: delete then add), `enable_service`.
  Output markers: `@@UNIT <name>`, `@@USER <user>`, `@@ACTIVE coturn <state>`;
  exit non-zero when not active.

- [ ] **Step 1: Failing tests** (`extraire_fonction`, stubs for `apt-get`, `pacman`, `turnadmin`, `systemctl`, `chown`, `id`): `write_config` without certificate has no `tls-listening-port`/`cert`, with certificate has `tls-listening-port=5349`, `cert=/etc/erplibre-call/tls/turn.crt`; never contains `user=` nor `static-auth-secret`; first line is the managed marker; `family` dies on `ID=fedora`; `ensure_check_user` never shows the password in argv of anything except `turnadmin` and the test asserts the script source never echoes `TURN_CHECK_PASSWORD`; `main` exits non-zero when `systemctl is-active` prints `failed`.
- [ ] **Step 2–4:** run `./script/test/run_unit_test.sh test/test_install_coturn.py` FAIL → implement → PASS.
- [ ] **Step 5: Commit** `[ADD] install_coturn: coturn by packages, user database, check account`.

### Task 5: Probe, plan, install script, host state, adoption

**Files:**
- Create: `script/todo/call_infra.py`
- Test: `test/test_call_infra.py`

**Interfaces:**
- Consumes: `ntfy_mobile.parse_markers`, `unified_diff`, `read_yml_keys`, `_set_key`; installers of Tasks 3–4 (read from disk, sent base64).
- Produces:
  - `STATE_PATH = "/etc/erplibre-call/state.json"`, `STATE_VERSION = 1`.
  - `@dataclass(frozen=True) class HostFacts: family: str | None; os_id: str; os_version: str; systemd: bool; hostname: str; addresses: tuple[str, ...]; busy_ports: tuple[tuple[str, int, str], ...]; coturn: dict | None; ntfy: dict | None; firewall: str; state: dict | None` — `coturn`/`ntfy` = `{"unit", "config", "config_text", "managed": bool}`; `firewall` ∈ `"ufw"|"nftables"|"none"|"unknown"`.
  - `probe_script() -> str`; `parse_probe(output: str) -> HostFacts` (markers `@@OS`, `@@SYSTEMD`, `@@HOSTNAME`, `@@ADDR`, `@@PORT <proto> <port> <process>`, `@@COTURN`, `@@NTFY`, `@@FILE <path> <base64>`, `@@FIREWALL`, `@@STATE <base64>`).
  - `@dataclass(frozen=True) class Answers: services: frozenset[str]; tls: str; cert_pem: str | None; key_pem: str | None; public_name: str; turn_port: int = 3478; turns_port: int = 5349; min_port: int = 49152; max_port: int = 49252; ntfy_port: int | None = None; external_ip: str | None = None` (`ntfy_port` None → 8080 for `tls="none"`, 8443 for `"supplied"`).
  - `class Refusal(Exception)` with `.key` (i18n key) and `.values` (dict for formatting).
  - `@dataclass(frozen=True) class InstallPlan: answers: Answers; adopt: tuple[str, ...]; diffs: tuple[tuple[str, str], ...]; nothing_to_do: bool; new_state: dict`.
  - `plan_install(facts: HostFacts, answers: Answers, now: datetime) -> InstallPlan` — refusals: `call_infra_unsupported_os`, `call_infra_no_systemd`, `call_infra_port_busy` (a needed port held by a process that is not the service being reinstalled), `call_infra_cert_key_mismatch`, `call_infra_cert_expired`, `call_infra_cert_name_missing` (certificate checks run on the machine running `todo.py`: dates and names by `openssl x509 -noout -enddate -ext subjectAltName -subject` through `subprocess`, as `local_cert.py` already uses openssl; key match by `ssl.SSLContext.load_cert_chain`); `nothing_to_do` when the state already records the same answers and both units are active.
  - `install_script(plan: InstallPlan, stamp: str, check_password: str) -> str` — one `sh` script: backups of adopted files (`cp -p <f> <f>.bak-<stamp>`), installers decoded from base64 and run with their env, `@@ACTIVE` lines, and ONLY THEN the state written atomically (`.new` + `mv`, 0600).
  - `state_answers(state: dict) -> Answers | None` (to prefill a rerun).

- [ ] **Step 1: Failing tests:** probe parse of a canned Debian 13 output and an Arch output; `plan_install` refusals for each key above (fedora, no systemd, `@@PORT tcp 8080 nginx`, mismatched key, expired cert, cert for `other.exemple.test` when `public_name` is `turn.exemple.test` or an IP SAN missing); adoption: facts with an unmanaged `/etc/turnserver.conf` → `adopt == ("coturn",)` and a diff listed; second plan on the produced state → `nothing_to_do True`; `install_script` text: state write appears after the last `@@ACTIVE` check and is guarded by both services active (Review Focus 1); the check password appears only inside the base64 payload, not in clear (`check_password not in script`); invented data only.
- [ ] **Step 2–4:** `./script/test/run_unit_test.sh test/test_call_infra.py` FAIL → implement → PASS.
- [ ] **Step 5: Commit** `[ADD] call infra: host probe, install plan, adoption, host state`.

### Task 6: Firewall detection and confirmed rules

**Files:**
- Modify: `script/todo/call_infra.py`
- Test: `test/test_call_infra.py` (class `TestFirewall`)

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Rule: proto: str; port: str; service: str` (`port` "3478" or "49152:49252").
  - `firewall_rules(answers: Answers) -> tuple[Rule, ...]` — coturn: 3478/udp, 3478/tcp, 5349/tcp when TLS, media range/udp; ntfy: its port/tcp.
  - `firewall_preview(kind: str, rules) -> list[str]` (the exact commands shown before the yes).
  - `firewall_script(kind: str, rules, action: str) -> str` — `ufw`: `ufw allow <port>/<proto> comment 'erplibre-call <service>'` / `ufw delete allow …`; `nftables`: rules inserted in the base chain hooked on input whose policy is drop (exactly one such chain, else the script prints `@@FIREWALL_MANUAL` and changes nothing), each with `comment "erplibre-call <service>"`, removal by handle looked up by comment; persistence only when `/etc/nftables.conf` includes `/etc/nftables.d/*` (writes `/etc/nftables.d/erplibre-call.nft`), else `@@FIREWALL_RUNTIME_ONLY`. Never `ufw enable`, never a rule on 22.
  - state gains `"firewall": {"kind", "rules": [[proto, port, service], …], "persisted": bool}`.

- [ ] **Step 1: Failing tests:** rules for dev http (no 5349) and dev supplied (5349 present); ufw preview strings exact; nftables script contains no `flush`, no `policy accept`, no `22`; `@@FIREWALL_MANUAL` path when the canned ruleset has two drop input chains; `kind "none"` → empty script and the state records no rule; the provider-firewall reminder key `call_infra_cloud_firewall` is returned by `firewall_notes(kind)` for every kind.
- [ ] **Step 2–4:** run FAIL → implement → PASS. **Step 5: Commit** `[ADD] call infra: firewall detection and confirmed allow rules`.

### Task 7: Check and uninstall

**Files:**
- Modify: `script/todo/call_infra.py`
- Test: `test/test_call_infra.py` (classes `TestCheck`, `TestUninstall`)

**Interfaces:**
- Consumes: `turn_client` (Task 1), state (Task 5), firewall (Task 6).
- Produces:
  - `check_remote_script() -> str` — read-only: `@@STATE <base64>`, `@@ACTIVE <svc> <state>`, `@@CHECK_KEY <hex>` (the check account's long-term key read from the user database: `sqlite3 <db> "select hmackey from turnusers_lt where name='erplibre-check'"`), `@@FIREWALL_RULE …` for each recorded rule still present.
  - `@dataclass(frozen=True) class CheckLine: name: str; ok: bool | None; detail: str` (`None` = not checked, with the reason).
  - `check_local(facts_remote: dict, address: str, cafile: str | None, allocate=turn_client.allocate, https_get=…) -> list[CheckLine]` — lines `turn-udp`, `turn-tcp`, `turn-tls` (only with TLS), `ntfy-health` (`/v1/health` over http/https, `cafile` for a supplied certificate's CA, else system store; an unverifiable certificate gives `ok None` with « certificat non vérifié »), `cert-expiry` (days left; < 14 → `ok False`), `firewall` (recorded rules present), `service-<svc>` (active).
  - `uninstall_script(state: dict, remove_data: bool, stamp: str) -> str` — stops/disables units, purges packages the tool installed (not adopted ones), restores adopted configs from their backups, removes recorded firewall rules, removes `/etc/erplibre-call` (keeps `tls/` and ntfy's `user.db` unless `remove_data`), prints `@@REMOVED <item>`; with no state: prints `@@NOTHING` and changes nothing.

- [ ] **Step 1: Failing tests:** `check_local` with fake `allocate` returning ok/401/timeout gives the right `CheckLine`s; https probe fake raising `ssl.SSLCertVerificationError` → `ntfy-health ok None`; cert with 10 days left → `cert-expiry ok False`; uninstall script for an adopted ntfy contains the restore of `server.yml.bak-<stamp>` and no package purge for ntfy; `remove_data False` keeps `/var/lib/ntfy/user.db`; no-state → `@@NOTHING` (Review Focus 5); `check_remote_script` contains no write command (`rm`, `mv`, `>`, `turnadmin -a`).
- [ ] **Step 2–4:** FAIL → implement → PASS. **Step 5: Commit** `[ADD] call infra: check from outside and uninstall`.

### Task 8: The todo.py submenu « Infrastructure d'appel »

**Files:**
- Create: `script/todo/call_infra_menu.py` (`CallInfraMenuMixin`)
- Modify: `script/todo/todo.py` (import, class bases, `_MENU_LABELS`, Deploy menu entries 8–9 replaced by one entry, `_deploy_ntfy_server` removed), `script/todo/ntfy_mobile_menu.py` (the « Fix this with » message names the new path), `script/todo/todo_i18n.py` (new section `# Call infrastructure`; stale `# NTFY section` comment fixed)
- Test: `test/test_todo_call_infra.py`; Modify `test/test_todo_ntfy_mobile.py`, `test/test_proxmox_deploy.py`, `test/test_todo_menu.py` (a `MenuCoherence` subclass for the new menu)

**Interfaces:**
- Consumes: Tasks 1, 3–7; `_ask_ssh_target`, `ntfy_mobile.LocalHost/SshHost`, `prompt_execute_ntfy_mobile`.
- Produces:
  - Deploy menu: entry « Deploy - Call infrastructure » (fr « 📞 Déployer - Infrastructure d'appel ») at position 8 → `prompt_execute_call_infra`; later entries renumbered (`10 → 9` qemu cache, …).
  - `prompt_execute_call_infra()` entries: `[1]` « Installer sur un hôte (coturn, ntfy) » → `_call_infra_install`; `[2]` « Préparer ntfy pour ERPLibre mobile » → `prompt_execute_ntfy_mobile`; `[3]` « Vérifier » → `_call_infra_check`; `[4]` « Désinstaller » → `_call_infra_uninstall`. `_MENU_LABELS["prompt_execute_call_infra"] = "Call infrastructure"`.
  - `_call_infra_host() -> host | None` — the same [1] this machine / [2] over ssh choice as `_ntfy_mobile_host` (reuse it; this machine warns when it already runs a ntfy on 8080 that it will be ADOPTED, not replaced).
  - Install flow: host → probe → services → TLS none/supplied (paths, read locally) → public name (default ssh hostname or first address) → ports → summary + diffs of adopted files → yes → `install_script` run as root → admin password shown once if `@@ADMIN_PASSWORD` → firewall preview → yes → `firewall_script` → state firewall update → `check_local` table. A refusal prints `t(refusal.key).format(**values)` and returns.
  - Sudo failure (code ≠ 0 and output contains `incorrect password` or `a password is required`) → `call_infra_sudo_refused` line (Review Focus 2).
- [ ] **Step 1: Failing tests** with a `FakeHost` (own class, classifying by `@@` markers the scripts print, not by substrings that collide — see `test_todo_ntfy_mobile.py:76-89` pitfall) and `MenuCase.drive`-style scripted answers: full install on a fake Debian answering active; refusal shown for fedora; adoption diff shown and « n » aborts with nothing run; firewall « n » leaves no rule and the state's firewall rules empty; sudo refused line; check prints one line per `CheckLine`; uninstall twice → second prints « rien à désinstaller »; Deploy numbering pins updated; every `t("…")` literal in the new file exists in fr and en; `TestMenuLabels` passes.
- [ ] **Step 2–4:** `./script/test/run_unit_test.sh test/test_todo_call_infra.py test/test_todo_ntfy_mobile.py test/test_proxmox_deploy.py test/test_todo_menu.py test/test_todo_i18n.py test/test_i18n_duplicates.py` FAIL → implement → PASS.
- [ ] **Step 5: Commit** `[ADD] todo: call infrastructure submenu, ntfy entries moved into it`.

### Task 9: Long test on throwaway VMs

**Files:**
- Create: `long_test/call_infra.py`
- Modify: `long_test/descente.py` (`SCRIPTS`), `script/todo/longtest_menu.py` (`SCRIPTS_DESCENTE`, `SCRIPTS_DEFAISABLES`, menu entries, `_longtest_question` branch, i18n keys), `long_test/README.base.md` (section in both halves, mmg)
- Test: `test/test_longtest_call_infra.py`

**Interfaces:**
- Consumes: `call_infra` builders and `turn_client` (the SAME functions the menu uses, driven with `Answers` instead of prompts), `descente` (`Famille`, `detruire`, `drapeaux_cache`, `capacite_hote`, `cle_publique`, `dire`), `install_nixos.py` patterns (`creer_vm`, `adresse_de`, `attendre_ssh`), `qemu_install._qemu_cloud_init_wait`, `_qemu_pacman_prepare_cmd`, `local_cert.issue`.
- Produces: `./long_test/call_infra.py [--distro debian|arch|tous] [--garder] [--detruire] [--dry-run]`, report `~/.erplibre/longtest/long-call-infra-<ts>.json` in the shape `descente.detruire` reads, VM names `long-call-infra-<distro>`, Debian `--version 13`, Arch `--version latest`, both with `drapeaux_cache()`.
  Debian scenario, one ssh session per product step, verdict from machine state:
  1. create VM, wait for ssh and cloud-init; enable ufw after `ufw allow 22/tcp` (so « active firewall » is exercised);
  2. adoption seed: install ntfy with the old-style local call (`install_ntfy.sh` unmanaged config, add one phone user via `access_script`);
  3. install both services, dev, supplied certificate from `local_cert.issue(run/"tls", [vm_ip])`, firewall yes;
  4. check from the host: `turn-udp`, `turn-tcp`, `turn-tls`, `ntfy-health` (with the CA), `firewall`, both services — all `ok True`; the seeded phone user still listed (`list_script`);
  5. second install with the same answers → `nothing_to_do`;
  6. Task 2 finding replayed on the real package: add a secret with `turnadmin -s`, REST allocation ok and the check account still ok (reported as `melange-ok` / `melange-refuse`, not a failure);
  7. uninstall with `remove_data True` → no unit, no `/etc/erplibre-call`, no ufw `erplibre-call` rule, adopted `server.yml` restored from backup, ports closed from the host; uninstall again → `@@NOTHING`;
  8. destroy the VM unless `--garder`.
  Arch scenario: pacman preamble, both services dev http, check (`turn-udp`, `turn-tcp`, `ntfy-health`), uninstall, destroy.
- [ ] **Step 1: Failing unit tests** (no VM): `--dry-run` lists `deploy_qemu.py --distro debian --version 13` with the cache flags and creates nothing; `--detruire --dry-run` with a temp `HOME` report lists the VM; `call_infra.py` is in `descente.SCRIPTS` and `longtest_menu.SCRIPTS_DESCENTE`/`SCRIPTS_DEFAISABLES`; every `subprocess.run(timeout=…)` inside a `try` (AST); README has the section in both halves.
- [ ] **Step 2–4:** `./script/test/run_unit_test.sh test/test_longtest_call_infra.py test/test_todo_longtest.py` FAIL → implement → PASS.
- [ ] **Step 5: Commit** `[ADD] long_test call_infra: throwaway VMs install, check, uninstall`.
- [ ] **Step 6 (part B, controller, needs the user's sudo):** run `./long_test/call_infra.py --distro tous`; both scenarios green; then `--detruire` leaves no `long-call-infra-*` VM. Logs in `tasks/chat/p3l1-sdd/partB/`.

### Task 10: Documentation and changelog

**Files:**
- Modify: `CHANGELOG.base.md`, `long_test/README.base.md` (old path `TODO › Deploy › Prepare ntfy…` → new), any `.base.md` naming the moved entries (grep), then mmg.
- Test: the doc tests that pin the README sections (`test/test_todo_longtest.py`), `make doc_markdown` clean.

- [ ] **Step 1:** grep for `Prepare ntfy for ERPLibre mobile`, `Install NTFY notification server` in `*.base.md`; update to `TODO › Deploy › Call infrastructure`.
- [ ] **Step 2:** CHANGELOG entry (coturn, dev mode, firewall, adoption, check, uninstall, ntfy defects fixed, entries moved).
- [ ] **Step 3:** regenerate with mmg; run the doc tests — PASS.
- [ ] **Step 4: Commit** `[UPD] doc: call infrastructure menu, changelog`.
