# ERPLibre call infrastructure, lot 4 (containers) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From `TODO › Deploy › Call infrastructure › Install on a host`,
install coturn and ntfy as containers (Docker, Podman as root, or Podman
rootless) launched by a compose file on the host, in both modes; migrate
an existing packages install to containers and back without re-plugging
any Odoo; keep check, « add/remove an Odoo », the deploy hook,
« Préparer ntfy pour ERPLibre mobile » and uninstall working; prove it on
a Debian VM.

**Architecture:** A new stdlib leaf module `call_infra_container.py`
holds what is container-specific and pure: pinned images, fixed names,
the remote engine probe section and its parser, the compose file, engine
and compose argv (rootful or through `runuser` for rootless), engine
package lists, registry-error classification. `call_infra.py` gains a
`method` on `Answers`/state and branches its plan, root install script,
migration, day-2 scripts, check and uninstall on it. Containers use host
networking and bind mounts at the packages method's own paths, so the
host keeps `sqlite3`, the firewall rules, the nginx site and every
host-side reader unchanged. `install_coturn.sh` gains a container target;
the deploy hook signals the container.

**Tech Stack:** Python 3 stdlib, POSIX `sh`/bash root scripts, Docker
(`docker compose` v2 or `docker-compose`), Podman 4.9–6 with
`podman-compose`, coturn 4.18.0 image, ntfy v2.36.0 image, qemu VMs.

**Spec:** `docs/superpowers/specs/2026-10-30-erplibre-call-infrastructure-design.md`
(lot 4 line of « Lots », « Decisions › Hosts and systems », « Controller's
calls », « Constraints »). User decisions: `tasks/chat/p3-decisions.md`
(« Lot 4 (containers) — answers 2026-11-01 »). Recon with file:line facts
and risks: `tasks/chat/p3-recon-lot4.md` (§5 package table is
authoritative, §6.17 lists what only the VM proves). Controller rulings
P4-1…P4-15: `tasks/chat/p3l4-plan-brief.md`. Lot 1–3 code is the base:
`script/todo/call_infra.py`, `call_infra_menu.py`,
`script/install/install_coturn.sh`, `erplibre_call_deploy_hook.sh`,
`long_test/call_infra.py`.

## Global Constraints

- Images, written once in `call_infra_container.IMAGES` (P4-4):
  `docker.io/coturn/coturn:4.18.0@sha256:bbefd3e1fdfdc0d58770fe01b581fd8b00d9f3a5580d00acb77cf719a6bc78e3`
  and `docker.io/binwiederhier/ntfy:v2.36.0@sha256:fb48c413eb11d50339962b5d62cddce0f800e7f77c626d638a7c20cb7e9c4465`;
  `IMAGE_VERSIONS = {"coturn": "4.18.0", "ntfy": "2.36.0"}`. The pin moves
  only after a green long test.
- Fixed names: project `erplibre-call`, containers `erplibre-call-coturn`
  and `erplibre-call-ntfy`, compose file `/etc/erplibre-call/compose.yml`,
  rootless account `erplibre-call` (home `/var/lib/erplibre-call-podman`),
  rootful coturn fallback account `erplibre-coturn`.
- Host networking for both services (P4-2): no published port; firewall
  rules, `listen-http 127.0.0.1:8080` in production and the nginx site are
  unchanged; the relay range is the mode's range, as in the packages method.
- Bind mounts at the packages paths (P4-1): coturn DB dir
  `/var/lib/erplibre-call`, `/etc/erplibre-call/tls` ro, the coturn config
  (`COTURN_CONFIGS[family]`) ro, `/etc/ntfy` ro, `/var/cache/ntfy`,
  `/var/lib/ntfy`. The host keeps `sqlite3`; every DB read/write of the
  tool stays host `sqlite3` under the state's account.
- Containers never run as root (P4-3): every compose service has
  `user: "<uid>:<gid>"` resolved on the host; rootless adds
  `userns_mode: keep-id`; no service sets `no-new-privileges` (coturn's
  file capability binds 443 under rootful). `restart: always` (P4-4).
- Install still needs root (firewall, /etc, packages, accounts): same sudo
  model as lots 1–3. Never add any user to the `docker` group (P4-5);
  `install_container.sh` is not called.
- Podman compose = `podman-compose` called directly; Docker = `docker
  compose`, else `docker-compose` (P4-4).
- State (P4-7): `version: 2` written only when `method == "container"`;
  packages hosts stay `version: 1`; new code reads 1 and 2. `settings`
  gain `method`/`engine`/`rootless` only in container mode, so a packages
  state written by lots 1–3 stays « nothing to change ».
- The method is per host: switching it migrates every recorded service.
- Docker Hub refusal (HTTP 429, `toomanyrequests`) is reported as
  « limite du registre, réessayer plus tard », distinct from a failure, by
  the product and by the long test (P4-14).
- Rulings are cited as P4-n in this plan only; code, tests, comments and
  commits carry no work-tracking label (no « P4-3 », « lot 4 », « Task 5 »).
- Everything else as lots 1–3: stdlib only under `script/todo/` (AST guard
  test per new module); secrets never in argv nor logs (env or script body,
  `-e NAME` without value for engine exec); comments follow
  `.claude/rules/04-code-conventions.md` and each file's language (French
  docstrings in Python, ASCII French comments in the shell scripts);
  invented test data; i18n fr and en; `.base.md` + mmg; bilingual commits,
  English first, ≤ 8 lines per language, `Assisted-by: Claude Opus 5.5`,
  no AI in `Co-authored-by`, files named at `git add`, never push.
- Safety on this machine: no docker/podman/sudo/installers run locally;
  never touch its ntfy (8080), nginx, nor the Odoo servers on 8016–8018;
  `long_test` only with `--dry-run` during tasks. The real VM run is the
  controller's, after the final review.

## Review Focus

1. **A packages host from lots 1–3 rerun by the new code with the same
   answers**: still « nothing to change », state stays `version: 1`, no
   `method`/`engine` key in any `settings`, no container step in the
   script. Test in Task 3 (`test_packages_state_v1_still_nothing_to_do`).
2. **Registry refusal during install or migration** (429 or network):
   reported as the registry limit (or « pull failed »), nothing stopped,
   no installer run, no state written; images are pulled BEFORE any unit
   is stopped. Tests in Task 4 (`test_pull_rate_limit_stops_before_anything`)
   and Task 5 (`test_pull_precedes_first_stop`).
3. **A container that does not start after a migration**: the packages
   service comes back as it was (tool-installed reinstalled, adopted unit
   re-enabled per `was_active`/`was_enabled`), data chowned back, state
   unchanged, backups named on screen. Test in Task 5
   (`test_container_exited_rolls_back_to_packages`).
4. **Rootless with a port under the host's `ip_unprivileged_port_start`**
   (TURN over TLS on 443, a dev ntfy on 80): refused before any change,
   naming the port and offering 5349. Test in Task 3
   (`test_rootless_low_port_refused_early`).
5. **A tampered state reaching root commands** (container name, engine,
   account or uid outside the allow-list): the hook exits 2 without
   calling any engine; Odoo and uninstall scripts refuse with
   `call_infra_state_invalid`. Tests in Task 7
   (`test_container_state_tampered_refused`) and Task 8
   (`test_uninstall_refuses_tampered_container_block`).

---

### Task 1: Container leaf module and remote engine probe

**Files:**
- Create: `script/todo/call_infra_container.py`
- Modify: `script/todo/call_infra.py` (`HostFacts`, `probe_script`, `parse_probe`)
- Test: `test/test_call_infra_container.py`, `test/test_call_infra.py` (`TestParseProbe`, `TestProbeScript`)

**Interfaces:**
- Produces (module imported as `cc` by `call_infra`):
  - constants `IMAGES`, `IMAGE_VERSIONS`, `ENGINES` (= `container_runtime.MOTEURS`),
    `PROJECT`, `CONTAINERS = {"coturn": "erplibre-call-coturn", "ntfy": "erplibre-call-ntfy"}`,
    `COMPOSE_FILE`, `ROOTLESS_ACCOUNT`, `ROOTLESS_HOME`,
    `COTURN_ACCOUNTS = ("turnserver", "erplibre-coturn")`, `NTFY_ACCOUNT = "ntfy"`,
    `ACCOUNT_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")`.
  - `@dataclass(frozen=True) class EngineFacts`: `engines: dict[str, str]`
    (engine → version); `compose: dict[str, tuple[str, ...]]` (engine →
    first provider found: docker `("docker", "compose")` then
    `("docker-compose",)`, podman `("podman-compose",)`);
    `docker_service: tuple[str, str] | None` (active, enabled);
    `podman_restart: str | None` (root `is-enabled`); `unpriv_port_start: int`;
    `accounts: dict[str, tuple[int, int]]` (for the four fixed names);
    `rootless: dict | None` (`subuid`, `subgid`, `linger`, `newuidmap`:
    bool, `user_restart`: str | None — for `ROOTLESS_ACCOUNT` when it
    exists); `containers: tuple[tuple[str, str, bool, str, str], ...]`
    (name, engine, rootless, status, image); `images: tuple[tuple[str, bool, str], ...]`;
    `ntfy_host_version: str | None`; `sqlite3: bool`; `compose_text: str`.
  - `engine_probe_lines(root: str = "") -> list[str]` — root `sh` lines,
    every engine call under `timeout 20`, rootless calls through
    `rootless_prefix`; markers `@@ENGINE <e> <version>`, `@@COMPOSE <e> <words>`,
    `@@DOCKER_SERVICE <active> <enabled>`, `@@PODMAN_RESTART <enabled>`,
    `@@UNPRIV_PORT <n>`, `@@ACCOUNT <name> <uid> <gid>`,
    `@@ROOTLESS <subuid> <subgid> <linger> <newuidmap> <user-restart>`,
    `@@CONTAINER <name> <engine> <0|1> <status> <image>` (names
    `erplibre-call-*` or images `coturn/coturn`, `binwiederhier/ntfy`),
    `@@IMAGE <engine> <0|1> <ref>` (pinned refs present), `@@NTFY_HOST <version>`,
    `@@SQLITE3 <0|1>`, `@@COMPOSE_FILE <base64>`.
  - `parse_engine_lines(pairs: list[tuple[str, str]]) -> EngineFacts`.
  - `rootless_prefix(account: str, uid: int) -> list[str]` →
    `["runuser", "-u", account, "--", "env", f"XDG_RUNTIME_DIR=/run/user/{uid}", f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus"]`.
  - `engine_argv(block: dict) -> list[str]` and `compose_argv(block: dict) -> list[str]`
    (`block` = the state's `container` dict; compose argv ends with
    `-f COMPOSE_FILE -p PROJECT`; rootless prefixed by `rootless_prefix`).
  - `compose_text(services: tuple[str, ...], coturn_conf_path: str, rootless: bool) -> str`
    — first line `# erplibre-call: managed`; per service `image`,
    `container_name`, `network_mode: host`, `restart: always`,
    `user: "@USER_<SVC>@"`, rootless `userns_mode: keep-id`; coturn
    `command: ["-c", <config>]` and its three mounts; ntfy `command: ["serve"]`
    and its three mounts. `compose_resolved(template: str, users: dict[str, str]) -> str`.
  - `engine_packages(os_id: str, family: str, engine: str, rootless: bool, facts: EngineFacts) -> tuple[str, ...]`
    — only what is missing, recon §5: Debian `docker.io`, `docker-compose`;
    Ubuntu `docker.io`, `docker-compose-v2`; Arch `docker`, `docker-compose`;
    podman `podman`, `podman-compose`; rootless on Debian/Ubuntu `uidmap`.
  - `classify_pull(output: str) -> str` → `"rate-limit"` (`toomanyrequests`,
    ` 429 `) or `"failed"`; `version_older(found: str, pinned: str) -> bool`;
    `foreign_containers(facts: EngineFacts, state: dict | None) -> tuple[str, ...]`;
    `container_block_problem(state: dict) -> str | None` (name of the first
    invalid field: engine ∉ ENGINES, rootless not bool, account ∉ ACCOUNT_RE
    or `root`, uid not int in 1..2³¹−1, a service `container` ≠
    `CONTAINERS[svc]`, compose argv not one of the three providers).
  - `HostFacts.engines: EngineFacts | None = None`; `probe_script` appends
    `cc.engine_probe_lines(root)` before `@@END`; `parse_probe` fills it.

- [ ] **Step 1: Failing tests:** parse a probe output with docker 26.1.5 +
  `docker compose`, podman 5.4.2 + `podman-compose`, `@@UNPRIV_PORT 1024`,
  accounts `turnserver 998 998` and `ntfy 997 997` → `EngineFacts` fields
  equal; `compose_text(("coturn", "ntfy"), "/etc/turnserver.conf", False)`
  has `network_mode: host`, `restart: always`, both pinned refs verbatim,
  `user: "@USER_COTURN@"`, no `keep-id`, no `no-new-privileges`, no
  `ports:`; rootless adds `userns_mode: keep-id` on both; `compose_argv`
  rootless starts with `runuser -u erplibre-call -- env XDG_RUNTIME_DIR=/run/user/990`;
  `engine_packages("ubuntu", "debian", "docker", False, none)` ==
  `("docker.io", "docker-compose-v2")`; `classify_pull("toomanyrequests: ...")`
  == `"rate-limit"`; `version_older("2.11.0", "2.36.0")` True; a probe
  section run in a sandbox with fake `docker`/`podman` binaries prints the
  markers and never calls `pull`, `run` or `rm`; stdlib-only AST guard.
- [ ] **Step 2:** `./script/test/run_unit_test.sh test/test_call_infra_container.py test/test_call_infra.py` — FAIL.
- [ ] **Step 3: Implement.** Reuse `container_runtime` constants and its
  rootless `info` rule as data only (P4-6): no local `subprocess` call.
- [ ] **Step 4:** run — PASS.
- [ ] **Step 5: Commit** `[ADD] call infra: container constants and remote engine probe`.

### Task 2: coturn container flavour

**Files:**
- Modify: `script/install/install_coturn.sh`, `script/todo/call_infra.py` (`coturn_config`)
- Test: `test/test_install_coturn.py`, `test/test_call_infra.py` (`TestCoturnConfig`)

**Interfaces:**
- Produces:
  - installer env `TURN_TARGET=packages|container` (default `packages`,
    unchanged path) and `TURN_SERVICE_USER` (required with `container`,
    must exist). Container target: installs only `sqlite3`/`sqlite` when
    absent; account from `TURN_SERVICE_USER`; config at the family
    default; no drop-in, no `systemctl`; `write_config` writes
    `log-file=stdout` where `syslog` was and omits `no-dtls` and
    `no-stun-backward-compatibility` (4.18 no longer knows them); DB,
    schema, check user, secret mode, TLS copy unchanged. Instead of
    restarting: when the APPLIED digest differs, writes
    `/etc/erplibre-call/coturn.applied.erplibre-pending` (root 0600) and
    prints `@@RECREATE 1`, else `@@RECREATE 0`; last line `@@CONFIGURED coturn`, exit 0.
  - `coturn_config(answers, turn_mode=None, flavour="packages") -> str`,
    `flavour="container"` mirroring the container `write_config` exactly.
- [ ] **Step 1: Failing tests:** sandbox run with `TURN_TARGET=container`,
  `TURN_SERVICE_USER=erplibre-coturn`, a fake `systemctl` that fails the
  test when called → config has `log-file=stdout`, no `syslog`, no
  `no-dtls`, no `no-stun-backward-compatibility`, root:<account group>
  0640; pending digest written and `coturn.applied` untouched,
  `@@RECREATE 1`; second identical run → `@@RECREATE 0`, no pending file;
  missing `TURN_SERVICE_USER` → refused before any write; packages target
  output byte-identical to today (existing tests unchanged);
  `coturn_config(a, "secret", "container")` equals the sandbox file for
  dev, dev+TLS and production answers.
- [ ] **Step 2–4:** `./script/test/run_unit_test.sh test/test_install_coturn.py test/test_call_infra.py` FAIL → implement → PASS.
- [ ] **Step 5: Commit** `[ADD] install_coturn: container target, coturn 4.18 config flavour`.

### Task 3: Plan for the container method

**Files:**
- Modify: `script/todo/call_infra.py`
- Test: `test/test_call_infra.py` (class `TestContainerPlan`)

**Interfaces:**
- Consumes: Task 1 (`EngineFacts`, `engine_packages`, `foreign_containers`,
  `version_older`, `compose_text`), Task 2 (`coturn_config(..., flavour)`).
- Produces:
  - `METHODS = ("packages", "container")`, `CONTAINER_STATE_VERSION = 2`,
    `STATE_VERSIONS_READ = (1, 2)`; `STATE_VERSION` stays 1.
  - `Answers` gains `method: str = "packages"`, `engine: str | None = None`,
    `rootless: bool = False`, `install_engine: bool = False` (consent to
    install what `engine_packages` lists). `_check_answers`: ValueError for
    an unknown method/engine, engine set with packages, rootless with docker.
  - `method_refusal(facts: HostFacts, answers: Answers) -> Refusal | None`,
    in this order: `call_infra_foreign_container` (values `names`),
    `call_infra_method_partial` (method switch while a recorded service is
    not chosen; values `service`), `call_infra_ntfy_downgrade` (container →
    packages with ntfy while a host `ntfy` older than `IMAGE_VERSIONS["ntfy"]`
    exists; values `host`, `image`; P4-9), `call_infra_engine_missing`
    (packages needed, no consent; values `engine`, `packages`),
    `call_infra_rootless_port` (rootless and a needed port, 443 included, <
    `unpriv_port_start`; values `port`, `start`, `alt` = 5349; P4-3).
    `plan_install` raises it after `_check_answers`.
  - `engine_offer(facts: HostFacts, engine: str, rootless: bool) -> tuple[str, ...]`
    (menu wrapper over `cc.engine_packages`).
  - `container_account(facts: HostFacts, svc: str, rootless: bool, purged: bool) -> str`
    — rootless `ROOTLESS_ACCOUNT`; coturn `turnserver` when it exists and
    its package is not purged by this plan, else `erplibre-coturn`; ntfy `ntfy`.
  - container record per service: `container`, `account`, `config`,
    `unit` (the adopted unit kept for restore, else None), plus `_origin`
    fields, `settings`, `tls_files`; top-level `method`, `version` 2,
    `container` block `{engine, rootless, account, uid, compose, compose_file,
    project, images, images_pulled, engine_packages_added, accounts_added,
    restart_unit_enabled, linger_added}` (runtime fields carried from the
    prior state, filled by Task 4). After a reverse migration: `version` 1,
    `method` packages, and the block's tool additions kept under
    `container_added` for uninstall.
  - `_settings` adds `method`, `engine`, `rootless` only in container mode.
  - `InstallPlan` gains `migration: str | None` (`"to_container"`,
    `"to_packages"`), `engine_packages: tuple[str, ...]`, `compose: str`
    (template, "" in packages mode).
  - `nothing_to_do` in container mode: same settings, each container
    `running` on its pinned image, `compose_resolved(template, users of
    the prior state) == facts.engines.compose_text`, config text equal to
    `coturn_config(..., flavour="container")`.
  - `state_answers(state)` fills `method`, `engine`, `rootless`.
- [ ] **Step 1: Failing tests:**
  `test_packages_state_v1_still_nothing_to_do` (a literal lot 3 state
  fixture, version 1, probe with active units → `nothing_to_do`,
  `new_state["version"] == 1`, settings keys equal to the fixture's;
  Review Focus 1); container rerun with running containers and identical
  compose → `nothing_to_do`, no `engine_packages`; first container plan on
  a packages state → `migration == "to_container"`, `odoo_readd == ()`,
  version 2; container → packages → `migration == "to_packages"`, version 1,
  `container_added` present; `test_rootless_low_port_refused_early`
  (rootless + `turns_443` → `call_infra_rootless_port` port 443 alt 5349;
  dev ntfy port 80 → port 80; Review Focus 4); method switch choosing only
  ntfy while coturn is recorded → `call_infra_method_partial`; container
  named `erplibre-call-coturn` with no state → `call_infra_foreign_container`;
  host ntfy `2.11.0` reverse → `call_infra_ntfy_downgrade`, absent host
  ntfy → allowed; missing podman without consent → `call_infra_engine_missing`
  listing `podman`, `podman-compose`; state version 3 → `call_infra_state_version`.
- [ ] **Step 2–4:** `./script/test/run_unit_test.sh test/test_call_infra.py` FAIL → implement → PASS.
- [ ] **Step 5: Commit** `[ADD] call infra: plan the container method, state version 2`.

### Task 4: Root install script, fresh container install

**Files:**
- Modify: `script/todo/call_infra.py` (`install_script`, `installed_state`, new block helpers)
- Test: `test/test_call_infra.py` (class `TestContainerInstallRun`, sandbox with fake binaries like `TestInstallScriptRun`)

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: `install_script(plan, stamp, root="")` branches on
  `plan.answers.method`; helpers `_engine_lines(plan)`,
  `_container_accounts_lines(plan)`, `_rootless_lines(plan)`,
  `_pull_lines(plan)`, `_coturn_container_block(plan)`,
  `_ntfy_container_block(plan)`, `_compose_lines(plan)`,
  `_container_gate_lines(plan)`. Order and markers:
  1. pending fiches as today (fiche gains `method`);
  2. engine/compose packages from `plan.engine_packages`, each
     `@@ENGINE_PACKAGE <name>`; Docker: `systemctl enable --now
     docker.service` only when not active/enabled → `@@RESTART_UNIT_ENABLED docker.service`;
     rootful Podman: same for `podman-restart.service`;
  3. accounts: missing fixed accounts created `useradd --system`
     (`@@ACCOUNT_ADDED <name>`), then `@@ACCOUNT <svc> <name> <uid> <gid>`;
  4. rootless: account with home `ROOTLESS_HOME`, subuid/subgid range
     like `install_container.sh` `prochaine_plage` (65 536 ids from the
     first free multiple of 100 000), `loginctl enable-linger` →
     `@@LINGER_ADDED`, wait ≤ 30 s for `/run/user/<uid>`, user
     `podman-restart.service` enabled → `@@RESTART_UNIT_ENABLED user`;
  5. each pinned image absent → `<engine> pull <ref>` → `@@IMAGE_PULLED <ref>`;
     a failure → `@@PULL_FAILED <svc> <rate-limit|failed>` (via the shell
     mirror of `classify_pull`), `OK=0`, and the script stops before any
     service step;
  6. coturn: `install_coturn.sh` with `TURN_TARGET=container`,
     `TURN_SERVICE_USER=<account>` (it installs host `sqlite3`); ntfy:
     dirs `/var/lib/ntfy`, `/var/cache/ntfy` owned by its account,
     `server.yml` written as `_ntfy_block` does, TLS key group = the
     account's group;
  7. compose file from `plan.compose`, `@USER_<SVC>@` replaced by the
     resolved `uid:gid`, 0640 root:root (rootless: root:<account group>);
  8. `compose up -d`, plus `up -d --force-recreate coturn` when
     `@@RECREATE 1` and the container already existed;
  9. gate: `inspect` status, transient states re-read ≤ 10 s → `@@ACTIVE
     <svc> active` when running, else the status; coturn running → the
     pending digest moved to `coturn.applied`, else removed;
  10. ntfy admin as `install_ntfy.sh` `ensure_admin_user` does, through
      `ntfy_cli` with `-e NTFY_PASSWORD`, line `@@ADMIN_PASSWORD` through
      `cap` as today;
  11. state written only when OK.
  `installed_state(plan, stamp, out)` reads the new markers into the
  `container` block and each record's `uid`/`gid`.
- Also produces (used by Tasks 6 and 8):
  `@dataclass(frozen=True) class NtfyCli: prefix: str; sudo_user: str | None; restart: str; active: str`
  and `ntfy_cli(state: dict | None, owner: str) -> NtfyCli` — packages:
  prefix `ntfy`, sudo `owner`, restart/active the systemctl lines of
  today; rootful container: `<engine> exec -e NTFY_PASSWORD -u <uid>:<gid> erplibre-call-ntfy ntfy`,
  sudo root, restart `<compose> restart ntfy`, active the inspect line;
  rootless: `env XDG_RUNTIME_DIR=/run/user/<uid> podman exec …`, sudo the
  rootless account (P4-11).
- [ ] **Step 1: Failing tests:** Docker fresh dev install → fake argv log
  shows apt `docker.io docker-compose`, pulls of both refs, installer env
  `TURN_TARGET=container`, `docker compose -f /etc/erplibre-call/compose.yml -p erplibre-call up -d`,
  state with `version` 2 and `images_pulled` both refs;
  `test_pull_rate_limit_stops_before_anything` (fake pull prints
  `toomanyrequests` → `@@PULL_FAILED coturn rate-limit`, no installer, no
  compose, no state; Review Focus 2); rootless → every podman call starts
  with the `runuser … env XDG_RUNTIME_DIR=/run/user/<uid>` prefix,
  compose file `user: "<uid>:<gid>"` and `keep-id`; no script text
  contains `usermod -aG docker`, `gpasswd` or `no-new-privileges`; fake
  inspect `exited` → `@@ACTIVE coturn exited`, no state, pending digest
  removed; second run with images present → no pull, no `--force-recreate`;
  `NTFY_PASSWORD` value never in any recorded argv.
- [ ] **Step 2–4:** run FAIL → implement → PASS.
- [ ] **Step 5: Commit** `[ADD] call infra: install coturn and ntfy as containers`.

### Task 5: Migration packages ↔ container

**Files:**
- Modify: `script/todo/call_infra.py` (`install_script` migration branch, `_migration_lines`)
- Test: `test/test_call_infra.py` (class `TestMigrationRun`)

**Interfaces:**
- Consumes: Task 4 helpers, `_service_uninstall_lines`, `_restore_lines`,
  `_coturn_block`, `_ntfy_block`, `state_answers`.
- Produces `_migration_lines(plan, stamp) -> list[str]` (P4-9):
  - **to_container:** pulls first (Task 4 step 5); per service: stop the
    unit; backup by the old account (`runuser -u <acct> -- cp -p`) of
    `turndb` and `user.db` to `<file>.bak-<stamp>`, `@@BACKUP <path>`;
    tool-installed → `_service_uninstall_lines(..., remove_data=False)`
    (purge, ntfy data held); adopted → `systemctl disable --now <unit>`,
    package kept, record keeps `unit`/`was_active`/`was_enabled`; then the
    container steps of Task 4 (config rewritten after the purge); data
    chowned (`chown -R --no-dereference`) to the container accounts;
    compose up; gate. Gate failure → `compose down`, data chowned back,
    tool-installed services reinstalled by the packages blocks with
    `state_answers(prior)`, adopted units restored per
    `was_active`/`was_enabled`, `@@MIGRATION rolled-back`, no state write.
    Success → `@@MIGRATION done`.
  - **to_packages:** `compose down`; packages blocks (installers chown
    the coturn DB; ntfy data chowned to `ntfy`); gate on the units; only
    then `rmi` of `images_pulled` (`@@IMAGE_KEPT <ref>` when in use, never
    forced) and the compose file removed. Gate failure → units stopped,
    data chowned back, `compose up -d`, `@@MIGRATION rolled-back`.
  - No Odoo write (`plan.odoo_readd` stays empty with unchanged answers).
- [ ] **Step 1: Failing tests:** `test_pull_precedes_first_stop` (the first
  `pull` index < the first `systemctl stop` index in the argv log; a 429
  leaves the unit running; Review Focus 2);
  `test_container_exited_rolls_back_to_packages` (fake inspect `exited` →
  `compose down`, chown back, coturn installer replayed with
  `TURN_TARGET` unset, adopted ntfy `systemctl enable --now ntfy`,
  `@@MIGRATION rolled-back`, state file unchanged; Review Focus 3);
  backups by `runuser -u turnserver`; adopted record keeps
  `unit: "ntfy"`; reverse: `rmi` only after `@@ACTIVE coturn active`, a
  failing reverse gate restarts the containers; `turn_secret` rows of a
  fake DB identical before and after (no SQL write in the script).
- [ ] **Step 2–4:** run FAIL → implement → PASS.
- [ ] **Step 5: Commit** `[ADD] call infra: migrate between packages and containers`.

### Task 6: Day-2 operations and check in container mode

**Files:**
- Modify: `script/todo/call_infra.py`, `script/todo/ntfy_mobile.py`, `script/todo/ntfy_mobile_menu.py`
- Test: `test/test_call_infra.py` (`TestContainerOdoo`, `TestContainerCheck`), `test/test_ntfy_mobile.py`, `test/test_todo_ntfy_mobile.py`

**Interfaces:**
- Consumes: `NtfyCli`, `ntfy_cli` (Task 4), `compose_argv`/`engine_argv` (Task 1).
- Produces:
  - `_coturn_target(state) -> tuple[str | None, str, str | None]` (unit,
    realm, account); `_userdb_lines(unit, realm, account=None)`: with an
    account, `U=<account>` literal (checked by `cc.ACCOUNT_RE`, else
    `call_infra_state_invalid`), no `systemctl show`.
  - `_switch_lines(state, mode)` container: installer `TURN_TARGET=container`,
    then `compose up -d --force-recreate coturn` + gate + pending digest
    only on `@@RECREATE 1` (P4-10). Add, remove, rotate: no compose, no
    kill, no restart.
  - `_ntfy_put_lines` container: `ntfy_cli(state, …).restart` then the inspect gate.
  - `nm.access_script(config, user, prefix, label=..., cli="ntfy")`,
    `nm.revoke_script(config, user, cli="ntfy")`, `nm.list_script(config, cli="ntfy")`,
    `nm.inspect_script(config, state_path=None)` (prints `@@STATE <base64>`
    when given and present); `ntfy_mobile_menu` reads the state from
    `inspect_script(config, ci.STATE_PATH)` and runs every ntfy command
    and restart through `ci.ntfy_cli`.
  - `check_remote_script(root="")` adds `@@CONTAINER_ACTIVE <svc> <engine>
    <0|1> <status> <uid:gid>` for the fixed names (rootful docker, rootful
    podman, rootless podman under `ROOTLESS_ACCOUNT`); a found container's
    status gives `@@ACTIVE <svc>` (`running` → `active`); the DB is read
    as the account owning the coturn container's uid (`getent passwd`).
    `check_local`: `service-coturn` false with
    `call_infra_container_account_mismatch` when that uid differs from the
    state's coturn uid; turn/ntfy/TLS/firewall lines and
    `check_through_odoo` unchanged.
- [ ] **Step 1: Failing tests:** `odoo_add_script` on a rootful container
  state → `U=turnserver`, no `systemctl show`; rootless → `U=erplibre-call`;
  first module Odoo on a container fixed-mode coturn → one
  `--force-recreate coturn` guarded by `RECREATE`; a second module Odoo →
  no `compose`, `kill` nor `restart` in the script; exempt edit →
  `compose … restart ntfy`; account `root;id` in state → refusal; check
  output with `@@CONTAINER_ACTIVE coturn docker 0 running 998:998` and a
  state uid 998 → `service-coturn` ok, uid 999 → false with the mismatch
  key; nmm « Préparer » on a container state → recorded command
  `NTFY_PASSWORD=… docker exec -e NTFY_PASSWORD -u 997:997 erplibre-call-ntfy ntfy user …`
  run as root, the password never in argv; packages state → commands
  byte-identical to today.
- [ ] **Step 2–4:** `./script/test/run_unit_test.sh test/test_call_infra.py test/test_ntfy_mobile.py test/test_todo_ntfy_mobile.py` FAIL → implement → PASS.
- [ ] **Step 5: Commit** `[ADD] call infra: Odoo, ntfy and check against containers`.

### Task 7: Deploy hook signals the coturn container

**Files:**
- Modify: `script/install/erplibre_call_deploy_hook.sh`
- Test: `test/test_deploy_hook.py` (class `TestConteneur`)

**Interfaces:**
- Produces (P4-8): `coturn_record` prints, for a container state,
  `container <engine> <name> <0|1> <account> <uid> <config>` after the
  same checks as `cc.container_block_problem` (written again in the
  snippet, stdlib only), else exit 2. Rootful: `<engine> inspect -f
  '{{.State.Running}}' <name>` → `true` → `<engine> kill --signal SIGUSR2 <name>`;
  rootless: the same through `runuser -u <account> -- env
  XDG_RUNTIME_DIR=/run/user/<uid> podman`. Markers as lot 2 with the
  container name: `coturn-inactive <name>`, `signal <name>`,
  `failed signal <name>`, `applied`/`applied-stale`. The packages path and
  `applied_digest` stay byte-identical.
- [ ] **Step 1: Failing tests:** rootful docker state → fake `docker` argv
  `kill --signal SIGUSR2 erplibre-call-coturn`, copies done, `@@HOOK applied`,
  no `systemctl kill`, no `restart`; rootless → `runuser -u erplibre-call
  -- env XDG_RUNTIME_DIR=/run/user/990 podman kill --signal SIGUSR2 erplibre-call-coturn`;
  inspect `false` → `coturn-inactive erplibre-call-coturn`, copy without
  signal; `test_container_state_tampered_refused` (name
  `erplibre-call-coturn;id`, engine `sh`, account `root`, uid `0`, uid
  `"990 x"` → each exits 2 with `@@HOOK failed state` and no fake binary
  called; Review Focus 5).
- [ ] **Step 2–4:** `./script/test/run_unit_test.sh test/test_deploy_hook.py` FAIL → implement → PASS.
- [ ] **Step 5: Commit** `[ADD] deploy hook: signal the coturn container after renewal`.

### Task 8: Uninstall in container mode

**Files:**
- Modify: `script/todo/call_infra.py` (`uninstall_script`, `_uninstall_records`, new `_container_uninstall_lines`)
- Test: `test/test_call_infra.py` (class `TestContainerUninstall`, `UninstallSandbox`)

**Interfaces:**
- Produces (P4-12): `uninstall_script(state, remove_data, stamp, root="", remove_engine=False)`.
  `_uninstall_records` accepts container records (`unit` None or in
  `_UNITS[svc]`, `container` == `CONTAINERS[svc]`, account by
  `ACCOUNT_RE`) and refuses an invalid block through
  `cc.container_block_problem` (`call_infra_state_invalid`, values
  `service` = the field). Order: ntfy admin removed through `ntfy_cli`
  while the container runs (when the tool added it, as today); `compose
  down`; compose file removed; `rmi` of `images_pulled` (in use →
  `@@IMAGE_KEPT <ref>`, never forced); data and TLS rules unchanged;
  adopted units restored by `_restore_lines`; with `remove_engine`:
  restart unit disabled when the tool enabled it, `loginctl
  disable-linger`, tool-added accounts removed only when the data they
  own goes too (else `@@KEPT account <name>`), the rootless account with
  `userdel -r`, `engine_packages_added` purged by `pkg_purge`
  (`@@REMOVED package <name>`); without it `@@KEPT engine <names>`. The
  same tail runs for `container_added` on a packages host.
- [ ] **Step 1: Failing tests:** container state, `remove_data=False`,
  `remove_engine=False` → `compose down`, compose file gone, both refs
  removed, DB and `user.db` kept, `@@KEPT engine docker.io docker-compose`;
  `remove_engine=True, remove_data=True` rootless → linger disabled,
  `userdel -r erplibre-call`, packages purged; `rmi` failing → `@@IMAGE_KEPT`
  and the uninstall goes on; `test_uninstall_refuses_tampered_container_block`
  (engine `sh`, container `x;rm`, uid `0` → `call_infra_state_invalid`;
  Review Focus 5); packages state → script byte-identical to today.
- [ ] **Step 2–4:** run FAIL → implement → PASS.
- [ ] **Step 5: Commit** `[ADD] call infra: uninstall containers and what the tool added`.

### Task 9: Menu — method, engine, migration, i18n

**Files:**
- Modify: `script/todo/call_infra_menu.py`, `script/todo/todo_i18n.py`
- Test: `test/test_todo_call_infra.py`

**Interfaces:**
- Consumes: `ci.method_refusal`, `ci.engine_offer`, `ci.state_answers`,
  `ci.plan_install`, `ci.install_script`, `ci.uninstall_script(..., remove_engine)`.
- Produces `_call_infra_ask_install_method(facts) -> tuple[str, str | None, bool, bool] | None`
  (method, engine, rootless, install_engine), called after the services
  question (P4-13): `[1] Paquets du système (systemd)` / `[2] Conteneurs
  (Docker ou Podman)`, prefilled from the state; no engine → `[1] Docker
  [2] Podman` and the packages offer `(o/N)`; one engine → used, said;
  both → asked; Podman → `[1] en root [2] sans root (compte erplibre-call)`;
  compose missing → its package offered; then `ci.method_refusal` shown
  at once. Rootless never asks the 443 question and says why
  (`call_infra_rootless_no_443`). A method switch shows
  `call_infra_migration_notice` (what stops, backups, Odoo untouched) and
  asks `call_infra_ask_migrate (o/N)` before the summary. The summary
  names method, engine, rootless, images, packages to install, and with
  Docker `call_infra_docker_forward_note`. `_call_infra_installed`:
  `@@PULL_FAILED <svc> rate-limit` → `call_infra_registry_limit`
  (« Limite du registre atteinte (Docker Hub) : réessayer plus tard. »),
  `failed` → `call_infra_pull_failed`; `@@MIGRATION rolled-back` →
  `call_infra_migration_rolled_back` with the `@@BACKUP` paths.
  Uninstall: `call_infra_ask_remove_engine` asked only when the state
  records tool additions. Every new key fr+en. New `ci.` bricks are
  called only from `_call_infra_ask_install_method`, which Task 10 adds
  to `ETAPES_DU_MENU` together with the long test calls, so the
  menu-path guard stays green between the two tasks.
- [ ] **Step 1: Failing tests** (FakeHost + scripted answers): no engine →
  offer lists `docker.io docker-compose`, accepted → `install_engine`
  True; both engines → engine asked; Podman rootless → no 443 question;
  rootless + ntfy port 80 → `call_infra_rootless_port` printed before the
  summary, no host script run; packages state + container chosen → the
  migration notice, « non » → nothing run; captured `rate-limit` output →
  the registry sentence, not the failure one; `LeMemeCheminQueLeMenu`
  still passes; numbering pins, `TestMenuLabels`, i18n parity.
- [ ] **Step 2–4:** `./script/test/run_unit_test.sh test/test_todo_call_infra.py test/test_todo_menu.py test/test_todo_i18n.py test/test_i18n_duplicates.py` FAIL → implement → PASS.
- [ ] **Step 5: Commit** `[ADD] todo call infra: choose packages or containers, migrate`.

### Task 10: Long test containers and migration, documentation

**Files:**
- Modify: `long_test/call_infra.py`, `script/todo/longtest_menu.py`,
  `long_test/README.base.md`, `CHANGELOG.base.md` (+ mmg)
- Test: `test/test_longtest_call_infra.py`, `test/test_todo_longtest.py`

**Interfaces:**
- Consumes: the menu bricks (`ci.method_refusal`, `ci.engine_offer`,
  `ci.plan_install`, `ci.install_script`, `ci.installed_state`,
  `ci.check_remote_script`, `ci.check_local`, `ci.check_through_odoo`,
  `ci.odoo_add_script`, `ci.uninstall_script`), the lot 2 `crochet` passes,
  the lot 1 `_melange`, the lot 3 `Harnais`.
- Produces (P4-14), Debian only, `SCENARIOS_NOMS` + `"conteneur"`,
  `"migration"`, option `--moteur docker|podman|podman-rootless` (default:
  the three in sequence, each its own course and fresh VM):
  - `conteneur`: engine absent → offer accepted (`@@ENGINE_PACKAGE`
    recorded); install; containers running with the account's uid;
    check green (TURN udp/tcp/tls allocations, ntfy health); DB owner =
    the state account (rootless: not a subordinate uid); a host-side
    secret via `odoo_add_script` with an invented key → recreate once,
    allocation with its REST credential, a second key → container
    `StartedAt` unchanged; hook by hand on a staged lineage → `signal
    erplibre-call-coturn`, turnserver PID unchanged; VM reboot →
    containers running again (`podman-restart` enabled, linger for
    rootless); rerun → nothing to change; uninstall with engine removal →
    no container, image, compose file, account or package left, ports
    closed. `docker` and `podman-rootless` run development with both
    services; `podman` runs coturn alone in production with a supplied
    certificate and `turns_443` (443 bound by a non-root uid); the
    `docker` course also runs `_melange` on 4.18 (information, result recorded).
  - `migration` (Podman as root): packages dev install; harness Odoo
    `call_infra_odoo_<run>_m` with `erplibre_turn` plugged; a phone seeded;
    migrate to containers → `odoo_readd == ()`, `turn_secret` rows
    identical, Odoo's own ICE list relays (`check_through_odoo`), the
    phone still listed through the container CLI; back to packages →
    allowed and done when the host has no older ntfy, else
    `call_infra_ntfy_downgrade` asserted; Odoo still relays; uninstall
    (Odoo removed first); database dropped.
  - `@@PULL_FAILED … rate-limit` → course verdict `limite-registre`,
    printed « limite du registre, réessayer plus tard », distinct from red.
  - `--dry-run` mutates nothing; `--detruire` as lots 1–3 (VM name per
    distro, `call_infra_odoo_*` databases).
- [ ] **Step 1: Failing unit tests:** `--dry-run --scenario conteneur`
  lists three courses and their steps; `--moteur podman-rootless` lists
  one; `--dry-run --scenario migration` names the database (never
  `mobile_sync_*`); a fake install output with the rate-limit marker →
  verdict `limite-registre`, not `echec`; `_call_infra_ask_install_method`
  added to `ETAPES_DU_MENU` and `LeMemeCheminQueLeMenu` passes (the long
  test calls `ci.method_refusal` and `ci.engine_offer`); longtest menu
  text counts the new VMs.
- [ ] **Step 2–4:** `./script/test/run_unit_test.sh test/test_longtest_call_infra.py test/test_todo_longtest.py` FAIL → implement → PASS; `./long_test/call_infra.py --distro debian --scenario conteneur --dry-run` and `--scenario migration --dry-run` print their plans and write only the dry-run report.
- [ ] **Step 5: Docs:** `long_test/README.base.md` (the two scenarios,
  `--moteur`, Docker Hub limit) and `CHANGELOG.base.md` (method choice,
  engines, rootless limits, migration and the one-way ntfy rule, pinned
  images); regenerate with mmg; doc tests PASS.
- [ ] **Step 6: Commit** `[ADD] long_test call_infra: containers and migration scenarios`.
- [ ] **Step 7 (controller, after the final review):** `./long_test/call_infra.py --distro debian --scenario conteneur`, then `--scenario migration`, then `--detruire`; logs in `tasks/chat/p3l4-sdd/partB/`. Proves recon §6.17 (keep-id + host network + `user:`, `podman-restart` enablement, 443 non-root under rootful, rootless kill from root) and « secret and fixed cannot mix » on 4.18.
