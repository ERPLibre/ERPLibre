# ERPLibre call infrastructure, lot 3 (Odoo servers) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From `TODO › Deploy › Call infrastructure`, plug one or several
Odoo 18 databases into an installed coturn (and ntfy): with the new module
`erplibre_turn`, Odoo hands every caller temporary TURN credentials
(`turn:` and `turns:`); without it, a fixed coturn account in three
`mail.ice.server` rows. Remove an Odoo again, check through Odoo, and
prove it on a Debian VM with a harness Odoo 18.

**Architecture:** A new Odoo module in `ERPLibre_erplibre_addons` builds
the ICE list from a shared secret held in system parameters. On the
`todo.py` side, a stdlib `odoo_link.py` reaches an Odoo by its external
JSON-RPC API (admin login or API key) or by `odoo-bin shell` over the
lot 1 host runners; `call_infra.py` gains the coturn credential side
(secret or fixed user per Odoo, in coturn's SQLite database, never in the
config) and the per-Odoo registry in the host state; the submenu gains
« Ajouter un serveur Odoo » and « Retirer un serveur Odoo ».

**Tech Stack:** Odoo 18 (`mail.ice.server`, `res.config.settings`),
Python 3 stdlib (`hmac`, `hashlib`, `base64`, `urllib`, `json`), coturn
4.6 SQLite userdb (`turn_secret`, `turnusers_lt`), ntfy server.yml,
qemu VMs, the harness Odoo of `long_test/mobile_sync_odoo.py`.

**Spec:** `docs/superpowers/specs/2026-10-30-erplibre-call-infrastructure-design.md`
(lot 3 line of « Lots », « Decisions › Odoo servers », « Controller's calls »,
« Constraints »). User decisions: `tasks/chat/p3-decisions.md` (lot 3
answers at the end). Odoo recon: `tasks/chat/p3-recon-odoo.md` (file:line
in Odoo 18 `mail`, coturn REST facts, module conventions). coturn facts
measured: `tasks/chat/p3l1-sdd/spike/spike-report.md` (several DB secrets
work live; `use-auth-secret` refuses every long-term user, even with no
secret). Lot 1/2 code: `script/todo/call_infra.py`, `call_infra_menu.py`.

## Global Constraints

- Odoo 18 only; 12–17 refused (`call_infra_odoo_version` naming the version).
- « An Odoo server » = one URL + one database; the host state keys it
  `url|database`. One coturn serves several Odoo.
- coturn credential mode, per coturn (spike: no mixing on 4.6):
  `"secret"` (conf line `use-auth-secret`, secrets in `turn_secret`) or
  `"fixed"` (`lt-cred-mech`, users in `turnusers_lt`); set by the FIRST
  Odoo plugged (module installed → secret, else fixed); an Odoo of the
  other kind is refused (`call_infra_turn_mode_mismatch`) with the reason
  and, for a module-less Odoo whose addons path has the module, the offer
  to install it. Switching a coturn to secret mode rewrites its config and
  restarts it once, and replaces lot 1's long-term check account by a check
  SECRET of its own (`erplibre-check`), used by « Vérifier ».
- Secrets and fixed passwords: drawn on the machine running `todo.py`
  (`secrets.token_urlsafe(32)`), sent to the host only inside the root
  script body (0600 file runner) and to Odoo only over the chosen channel;
  never written on the laptop, never printed, never in argv. coturn rows
  are written with `sqlite3` reading SQL on stdin, as lot 1 does.
- Per Odoo: its own secret (module) or its own user (no module), so one is
  revoked alone. Rerunning « Ajouter » on the same Odoo rotates: the new
  secret is added, the old one stays one credential lifetime
  (`retired: [{"value_sha256", "expires_at"}]` in the state; the value
  itself is found in the DB by its digest), removed by the next `todo.py`
  run on that host after `expires_at`. A fixed user is rotated at once
  (new password written to Odoo first, then to coturn).
- With the module: Odoo parameters `erplibre_turn.secret`,
  `erplibre_turn.urls` (newline list, built by `todo.py`:
  `stun:<turn>:<port>`, `turn:<turn>:<port>?transport=udp`,
  `turn:<turn>:<port>?transport=tcp`, plus `turns:<turn>:<tls port>?transport=tcp`
  when coturn has TLS), `erplibre_turn.ttl_hours` (24 default, settings
  field « Durée des identifiants TURN (heures) » in Settings › Discuss);
  the tool writes no `mail.ice.server` row and removes any row it wrote
  earlier. Without the module: three rows (`stun`, `turn` udp, `turn` tcp)
  with the fixed account, and the screen warns that TURN over TLS is not
  available.
- Rows owned by the tool are recognised by `username` =
  `erplibre-<8 hex of sha256(url|database)>` on a `uri` whose host is the
  coturn's TURN name; every other row is never written nor deleted; the
  tool shows existing rows and warns when the total passes 5 (Odoo sends
  `search(limit=5)`).
- Module absent from the Odoo's addons path: explain how to add it
  (`ERPLibre_erplibre_addons` on the addons path, restart, update the apps
  list), then offer the fixed-account fallback (only on a coturn in fixed
  mode or with no Odoo yet).
- « Retirer un serveur Odoo »: removes the tool's rows and
  `erplibre_turn.secret`/`erplibre_turn.urls`, keeps the module installed,
  revokes the Odoo's secret (no grace) or user, removes its ntfy exempt
  address when no other Odoo shares it, and drops it from the state. The
  last Odoo removed leaves the coturn's mode as is.
- ntfy exempt host (when ntfy is in the host state): the Odoo's outgoing
  address — over ssh, the Odoo host's public address as the lot 2
  `external_ip_for` logic finds it; over the web API, the resolved name of
  the Odoo URL — shown and confirmed or corrected; written to
  `visitor-request-limit-exempt-hosts` (comma list, kept apart from hand
  entries), then ntfy restarted.
- Web API: `/jsonrpc` `common.login` then `object.execute_kw`, password or
  API key (an admin with 2FA needs an API key, said on the prompt),
  credentials asked each time, never kept; the account must be in
  `base.group_system`. `odoo-bin shell`: script on stdin, ends with
  `env.cr.commit()`, run through `LocalHost`/`SshHost` in the ERPLibre
  directory asked (default the one `todo.py` runs from when local) with
  `./odoo_bin.sh shell -d <db>`.
- Never touch this machine's Odoo servers on 8016–8018 nor its ntfy;
  long tests use their own harness databases named `call_infra_odoo_*`
  (never `mobile_sync_*`) and their own coturn VM.
- Module commits happen inside `odoo18.0/addons/ERPLibre_erplibre_addons/`
  (its own git); the module follows that repo's conventions (French
  docstrings saying how the code works, `README.md` in French, version
  `18.0.1.0.0`, AGPL-3, `depends: ["mail"]`).
- Everything else as lots 1–2: stdlib only under `script/todo/`, i18n fr
  and en, invented test data, `.base.md` + mmg, bilingual commits with
  faithful FR translation, `Assisted-by: Claude Opus 5.5`, never push.

## Review Focus

1. **Odoo write fails after coturn was changed** (wrong admin password,
   AccessError, network drop): the coturn secret/user just added is
   removed again and the state is not changed, so no orphan credential
   stays valid. Test in Task 4: fake Odoo raising on `set_param` → the
   rollback script runs, state untouched, `call_infra_odoo_write_failed`.
2. **Hand-written `mail.ice.server` rows** (a Twilio-less admin's own
   STUN, another TURN): never written or deleted, even when their `uri`
   matches the coturn host but their username is not the tool's. Test in
   Task 4: rows `{uri: turn.exemple.test:3478, username: "alice"}` survive
   add and remove.
3. **Expired credentials and clock**: the module's username expiry is
   `now + ttl`, the password is `base64(HMAC-SHA1(secret, username))`
   with stdlib `hmac`; empty config returns exactly what `super()`
   returns (mail's `TestChannelRTC` expects `iceServers` False). Test in
   Task 1.
4. **Two Odoo on one coturn, one removed**: the other keeps allocating
   (its own secret still in `turn_secret`). Test in Task 3 (script content)
   and Task 7 (real VM).
5. **An Odoo 17 or a database name typo**: refused before anything on the
   host changes, with the version found or the login error. Test in Task 2.

---

### Task 1: Module `erplibre_turn`

**Files (repo `odoo18.0/addons/ERPLibre_erplibre_addons/`):**
- Create: `erplibre_turn/__manifest__.py`, `__init__.py`, `models/__init__.py`,
  `models/mail_ice_server.py`, `models/res_config_settings.py`,
  `views/res_config_settings_views.xml`, `tests/__init__.py`,
  `tests/test_erplibre_turn.py`, `README.md`

**Interfaces:**
- Produces (contract `todo.py` writes to):
  - parameters `erplibre_turn.secret` (str), `erplibre_turn.urls`
    (newline-separated URLs), `erplibre_turn.ttl_hours` (int, default 24,
    settings field `erplibre_turn_ttl_hours` with `config_parameter=`,
    shown next to mail's ICE block, `mail.res_config_settings_view_form`).
  - `mail.ice.server._get_ice_servers()` override: Twilio enabled
    (`mail.use_twilio_rtc_servers`) → `super()`; secret or urls missing →
    `super()`; else one dict per URL `{"urls": url, "username":
    "<expiry>:<userid>", "credential": <b64 hmac>}` (`stun:` URLs get no
    username/credential), userid `odoo-u<uid>` for a user, `odoo-guest`
    for the public user, never a login; then the local rows from
    `_get_local_ice_servers()` appended while the total stays ≤ 5; a
    `_logger.warning` when rows are dropped or the module's own list
    already passes 5.
- [ ] **Step 1: Failing tests** (`TransactionCase`, `@tagged("post_install", "-at_install")`):
  fixed secret `"s3cret"`, urls of 4 entries, `ttl_hours` 24, time
  patched to 1893456000 → username `"1893542400:odoo-u<uid>"`, credential
  equals `base64(hmac.new(b"s3cret", username, sha1))` computed in the
  test; `stun:` entry has no credential; empty secret → result equals
  `super()` (`[]` with no row); Twilio flag on → `super()` called; two
  hand rows + 4 module URLs → 5 entries and a warning logged; public user
  → `odoo-guest`; settings field writes the parameter. Also run mail's
  `/mail:TestChannelRTC` to show the empty case stays False.
- [ ] **Step 2:** run `./odoo_bin.sh` tests as the recon names
  (`--test-tags /erplibre_turn,/mail:TestChannelRTC --stop-after-init`
  on a throwaway database `call_infra_odoo_unit`, created and dropped by
  the implementer) — FAIL.
- [ ] **Step 3: Implement** (stdlib `hmac`, `hashlib`, `base64`; never
  `odoo.tools.misc.hmac`).
- [ ] **Step 4:** run — PASS; drop the throwaway database.
- [ ] **Step 5: Commit** in the addons repo: `[ADD] erplibre_turn: temporary TURN credentials for Odoo calls`.

### Task 2: `odoo_link.py` — reach an Odoo by web API or odoo-bin shell

**Files:**
- Create: `script/todo/odoo_link.py`
- Test: `test/test_odoo_link.py`

**Interfaces:**
- Produces:
  - `class OdooError(Exception)` with `.key` (i18n) and `.values`.
  - `@dataclass(frozen=True) class OdooFacts: version: str; major: int; module_state: str` (`"installed"`, `"uninstalled"` (on the addons path), `"absent"`, or another `ir.module.module` state as is); `params: dict[str, str]` (the three `erplibre_turn.*` keys present); `rows: tuple[dict, ...]` (`id`, `server_type`, `uri`, `username`; never `credential`); `host_name: str` (from the URL).
  - `class WebApi(url, database, login, secret, timeout=20, opener=urllib)`
    and `class OdooShell(host, erplibre_dir, database)` (host = a lot 1
    runner), both with: `facts() -> OdooFacts`, `install_module() -> None`
    (`button_immediate_install` / `env["ir.module.module"]...` +
    commit), `set_params(values: dict[str, str | None])` (None removes),
    `replace_rows(owned_username: str, rows: list[dict])` (deletes the
    rows with that username, creates the given ones, never touches others),
    `whoami() -> str`.
  - Refusals: `call_infra_odoo_version` (major ≠ 18, values `version`),
    `call_infra_odoo_login` (login refused, or database unknown),
    `call_infra_odoo_not_admin` (not `base.group_system`),
    `call_infra_odoo_unreachable`, `call_infra_odoo_shell_failed`
    (shell exit ≠ 0, last line).
  - `owned_username(url: str, database: str) -> str` → `erplibre-<8 hex>`.
- [ ] **Step 1: Failing tests:** an in-process fake JSON-RPC server
  (thread, port 0) answering `version`, `login`, `execute_kw`; Odoo
  `"17.0"` → `OdooError("call_infra_odoo_version")` before any write;
  wrong password → `call_infra_odoo_login`; `replace_rows` sends unlink
  only for ids whose username is the owned one (Review Focus 2) and the
  credential never appears in any log line; `OdooShell` with a fake host
  receives one script ending in `env.cr.commit()`, the secret only inside
  the script body, never in the command; `facts()` parses the shell's
  `@@ODOO` marker lines; stdlib-only AST guard.
- [ ] **Step 2–4:** `./script/test/run_unit_test.sh test/test_odoo_link.py` FAIL → implement → PASS.
- [ ] **Step 5: Commit** `[ADD] call infra: reach an Odoo by web API or odoo-bin shell`.

### Task 3: coturn credentials per Odoo on the host

**Files:**
- Modify: `script/todo/call_infra.py`, `script/install/install_coturn.sh`
- Test: `test/test_call_infra.py` (class `TestOdooCredentials`), `test/test_install_coturn.py`

**Interfaces:**
- Produces:
  - `install_coturn.sh` env `TURN_AUTH=fixed|secret` (default `fixed`):
    `secret` writes `use-auth-secret` and no `lt-cred-mech`, and the Python
    mirror `coturn_config` follows the state's `turn_mode`.
  - state: `"turn_mode": None|"fixed"|"secret"`, `"check_secret_sha256"`,
    `"odoos": {"<url>|<db>": {"method", "module", "credential":
    {"kind": "secret"|"user", "value_sha256"|"user"}, "retired": [...],
    "rows": bool, "exempt": "<ip>"|None, "added_at"}}`.
  - `odoo_add_script(state: dict, key: str, kind: str, value: str, user: str | None, exempt: str | None, now: datetime) -> str`
    — root script: switches the coturn to secret mode when needed
    (config, restart, check secret added, lot 1 check user removed),
    inserts the secret (`turn_secret(realm, value)`) or the user
    (`turnusers_lt` hmackey), moves a previous secret of this key to
    `retired`, purges retired entries past `expires_at` (all keys), adds
    the exempt address to ntfy, then the state; markers `@@ODOO_ADDED`,
    `@@TURN_MODE <mode>`.
  - `odoo_remove_script(state, key) -> str` and `odoo_rollback_script(state, key, value_sha256 | user) -> str`.
  - `turn_mode_for(state, module_installed: bool) -> str` raising
    `Refusal("call_infra_turn_mode_mismatch", values={"mode", "odoos"})`.
  - `ice_urls(state) -> list[str]` (the module's URLs from the coturn
    settings: turn name, ports, `turns:` when TLS).
- [ ] **Step 1: Failing tests:** first module Odoo on a lot 1 state →
  script switches to `use-auth-secret`, adds a check secret, removes the
  `erplibre-check` user; second module Odoo → no restart; module-less Odoo
  on a secret coturn → refusal; rotation keeps the old digest in `retired`
  with `expires_at = now + ttl`; a retired entry past expiry is deleted
  by any later script; remove of one Odoo deletes only its own secret
  (Review Focus 4); secret values appear only inside the script body as
  base64, never in clear, never in argv; `ice_urls` with TLS gives 4 URLs
  with `turns:` on the TLS port, without TLS 3.
- [ ] **Step 2–4:** `./script/test/run_unit_test.sh test/test_call_infra.py test/test_install_coturn.py` FAIL → implement → PASS.
- [ ] **Step 5: Commit** `[ADD] call infra: coturn secret or fixed user per Odoo server`.

### Task 4: « Ajouter » and « Retirer » plans

**Files:**
- Modify: `script/todo/call_infra.py`
- Test: `test/test_call_infra.py` (class `TestOdooPlan`)

**Interfaces:**
- Consumes: Tasks 2–3.
- Produces:
  - `@dataclass(frozen=True) class OdooPlan: key: str; kind: str; install_module: bool; params: dict; rows: tuple[dict, ...]; rows_total: int; warnings: tuple[str, ...]; exempt: str | None`.
  - `plan_odoo_add(state: dict, facts: OdooFacts, url: str, database: str, want_module_install: bool, exempt: str | None) -> OdooPlan`
    — warnings `call_infra_no_turns` (fixed mode), `call_infra_ice_over_5`
    (values `count`), `call_infra_module_absent` (explanation key).
  - `apply_odoo_add(host, link, plan, now) -> None` — order: host script
    (coturn credential first), then Odoo (module install when asked,
    params or rows), and on any Odoo failure `odoo_rollback_script`
    (Review Focus 1), raising `Refusal("call_infra_odoo_write_failed")`.
  - `apply_odoo_remove(host, link, state, key) -> None` — Odoo first
    (params None, `replace_rows(owned, [])`), then host; when the Odoo
    cannot be reached, asks the caller (a flag) whether to revoke on the
    host anyway.
- [ ] **Step 1: Failing tests** (fake host + fake link): module installed
  → params with `ice_urls` and no rows, `replace_rows(owned, [])` called;
  module absent, fixed coturn → 3 rows, `call_infra_no_turns` and
  `call_infra_module_absent`; 3 hand rows + 3 tool rows →
  `call_infra_ice_over_5` count 6; fake link raising on `set_params` →
  rollback script run and state unchanged; hand row `{username: "alice"}`
  on the coturn host never in a delete (Review Focus 2).
- [ ] **Step 2–4:** run FAIL → implement → PASS.
- [ ] **Step 5: Commit** `[ADD] call infra: add and remove an Odoo server, rollback on failure`.

### Task 5: Check per Odoo and through Odoo

**Files:**
- Modify: `script/todo/call_infra.py`, `script/todo/odoo_link.py`
- Test: `test/test_call_infra.py` (`TestOdooCheck`), `test/test_odoo_link.py`

**Interfaces:**
- Produces:
  - `check_remote_script` also prints `@@ODOO_SECRET <key> <base64>` /
    `@@ODOO_USER <key> <hmackey>` (read from the DB as root, masked on
    screen like `@@CHECK_KEY`) and the check secret.
  - check lines `odoo-<n>` per plugged Odoo: REST credential computed from
    its secret (or its user's key) → real allocation udp; ok/False.
  - `WebApi.join_call_ice(user_login, user_secret) -> list[dict]` —
    `/web/session/authenticate`, a private chat channel of that user
    (`discuss.channel` `channel_get` with itself), `/mail/rtc/channel/join_call`,
    read `Rtc.iceServers`, then `/mail/rtc/channel/leave_call`.
  - `check_through_odoo(ice: list[dict], allocate=turn_client.allocate)`
    → lines `odoo-ice-<url>`: each `turn:`/`turns:` URL allocated with
    the handed username and credential (key = MD5(user:realm:credential),
    realm from the 401).
- [ ] **Step 1: Failing tests:** two Odoo in a fake check output → two
  `odoo-*` lines, one failing when its secret is missing; fake join_call
  JSON with 4 URLs → 3 allocation attempts (no stun), credentials never
  printed; expired username (fake allocate 401) → line False with the
  reason.
- [ ] **Step 2–4:** run FAIL → implement → PASS.
- [ ] **Step 5: Commit** `[ADD] call infra: check each Odoo and through Odoo's own ICE list`.

### Task 6: Menu entries « Ajouter » and « Retirer un serveur Odoo »

**Files:**
- Modify: `script/todo/call_infra_menu.py`, `script/todo/todo_i18n.py`
- Test: `test/test_todo_call_infra.py`

**Interfaces:**
- Submenu becomes: `[1]` Installer sur un hôte, `[2]` Ajouter un serveur
  Odoo, `[3]` Retirer un serveur Odoo, `[4]` Préparer ntfy pour ERPLibre
  mobile, `[5]` Vérifier, `[6]` Désinstaller (pins updated).
- Add flow: coturn host (probe, refuse when no coturn in the state) →
  method `[1] API web (compte admin)` / `[2] ssh et odoo-bin shell` →
  URL/database/login/password-or-API-key (hidden input) or ssh target /
  ERPLibre directory / database → `facts()` (version refusal shown) →
  module state: installed → secret mode; uninstalled → « Installer
  erplibre_turn ? (O/n) »; absent → explanation, then « Continuer avec un
  compte fixe, sans TLS ? (o/N) » → mode refusal shown with its reason →
  existing rows listed (username shown, credential never) → ntfy exempt
  address proposed and confirmed when ntfy is in the state → summary
  (mode, rows or params, warnings) → yes → `apply_odoo_add` → `odoo-<n>`
  check line.
- Remove flow: host → list of plugged Odoo (`url|database`, method) →
  choice → link (same method questions) → `apply_odoo_remove`; Odoo
  unreachable → « Révoquer quand même sur coturn ? (o/N) ».
- Check: « Vérifier aussi par Odoo ? (o/N) » asks one plugged Odoo and a
  user login/password, then shows `check_through_odoo` lines.
- Uninstall: when Odoo are plugged, offers to remove each one first;
  otherwise lists the Odoo that keep the tool's rows.
- [ ] **Step 1: Failing tests** (FakeHost + fake link factory + scripted
  answers): add with module installed → host script then `set_params`
  called, summary shows « identifiants temporaires »; module absent → the
  explanation and the fallback question; mixing refusal printed; password
  never in captured output; remove → `replace_rows(owned, [])` and the
  remove script; numbering pins and `TestMenuLabels` pass; every `t()`
  literal fr+en.
- [ ] **Step 2–4:** `./script/test/run_unit_test.sh test/test_todo_call_infra.py test/test_todo_menu.py test/test_todo_i18n.py test/test_i18n_duplicates.py` FAIL → implement → PASS.
- [ ] **Step 5: Commit** `[ADD] todo call infra: add and remove an Odoo server`.

### Task 7: Long test, Odoo servers on one coturn

**Files:**
- Modify: `long_test/call_infra.py` (scenario `odoo`), `long_test/README.base.md` (+ mmg)
- Test: `test/test_longtest_call_infra.py`

**Interfaces:**
- Consumes: `long_test/mobile_sync_odoo.py` (template, run database,
  server start with free ports) with databases `call_infra_odoo_<run>_a`,
  `_b`, `_c` and an addons path that adds `ERPLibre_erplibre_addons`;
  the menu's builders (`plan_odoo_add`, `apply_odoo_add`, …) through
  `WebApi`.
- Produces `--scenario odoo` (in `tous`): Debian VM, coturn + ntfy dev with
  a supplied certificate, then:
  1. Odoo A without the module → fixed mode, 3 rows; `check_through_odoo`
     as a test user allocates `turn:` udp and tcp;
  2. remove A → rows gone, user revoked (allocation with the old
     credentials → 401);
  3. Odoo B with the module installed by the tool → coturn switches to
     secret mode once; join_call as a user and as a guest (invitation
     link) both allocate `turn:` and `turns:`;
  4. Odoo C with the module on the same coturn → no restart (coturn
     MainPID unchanged), both allocate;
  5. rotate B → B allocates with fresh credentials, credentials handed
     before rotation still allocate (grace);
  6. remove C → B still allocates (Review Focus 4), C's secret gone;
  7. module-less Odoo A again → refused for mode;
  8. uninstall everything (removing B first), drop the harness databases,
     destroy the VM unless `--garder`.
- [ ] **Step 1: Failing unit tests:** `--dry-run --scenario odoo` lists the
  steps and the database names (never `mobile_sync_*`); `--detruire`
  drops `call_infra_odoo_*` databases from the report and destroys the
  VM; AST guards as before.
- [ ] **Step 2–4:** `./script/test/run_unit_test.sh test/test_longtest_call_infra.py test/test_todo_longtest.py` FAIL → implement → PASS.
- [ ] **Step 5: Commit** `[ADD] long_test call_infra: Odoo servers on one coturn`.
- [ ] **Step 6 (part B, controller):** `./long_test/call_infra.py --distro debian --scenario odoo`, then `--detruire`; logs in `tasks/chat/p3l3-sdd/partB/`.

### Task 8: Documentation and changelog

**Files:**
- Modify: `CHANGELOG.base.md`, the call infrastructure doc section
  (`*.base.md` grep `Call infrastructure`), then mmg;
  `contracts/compatibility.json` gains an `erplibre_turn` entry
  (`source`, `version` 18.0.1.0.0, `depends` ["mail"], `optional` true,
  no routes).
- [ ] **Step 1:** document add/remove, the two modes and why they cannot
  mix, rotation grace, the 5-row cap, check through Odoo.
- [ ] **Step 2:** CHANGELOG lines (English quotes English screen strings).
- [ ] **Step 3:** mmg; doc and contract tests PASS
  (`test/test_contracts_compatibility.py`).
- [ ] **Step 4: Commit** `[UPD] doc: call infrastructure Odoo servers`.
