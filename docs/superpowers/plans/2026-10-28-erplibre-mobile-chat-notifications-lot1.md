# ERPLibre mobile chat notifications, lot 1 (transport and display) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** With the app closed, a message posted in Odoo 18 rings the phone:
Odoo encrypts a Web Push for the phone, the user's own ntfy carries it
without reading it, native code decrypts it and shows one notification per
conversation (or per inbox record) in the server's own Android channel,
private on the lock screen by default; a tap opens the conversation or the
inbox item. The user picks a level from 1 (realtime) to 5 (off); an account
without ntfy, or a phone silent longer than the ntfy cache, gets one summary
per server from Odoo's unread counters, never marking anything read. The
phone always says when it is not listening. `todo.py` prepares the ntfy:
rights, a read-only user per phone, a token that never expires, a QR code,
revocation.

**Architecture:** ERPLibre gains `script/todo/ntfy_mobile.py` (pure
functions: checks, ACL/user/token script, `server.yml` edit and diff, link,
QR) and a todo menu mixin that runs them locally or over ssh in one `sudo`
per step. The app gains a Capacitor-free Java package
`ca.erplibre.home.chatpush` (RFC 8291 decryption, ntfy client, notification
model, level policy, Keystore-wrapped stores, an Odoo client limited to two
read-only routes, an engine holding one connection per distinct ntfy), thin
Android glue (notifier, tap intent, plugin, a 15-minute job, a boot
receiver) and the permanent service in a source set a build property leaves
out. The JS side keeps one `chat_push` row per account (ntfy, topic,
endpoint, lock screen), registers the endpoint with Odoo's
`mail.push.device`, and mirrors to native storage what native code needs
(level, « Autoriser http », strings, account labels, conversation names, the
Odoo session) — the `NoteSyncPlugin` pattern.

**Tech Stack:** Python 3 stdlib + `segno` (ERPLibre tooling venv); Java 11
JCA, OkHttp 4.12, AndroidX NotificationCompat, JobScheduler, ML Kit
barcode-scanning; TypeScript, Owl 2, Capacitor 8, SQLite over SQLCipher,
Vitest; ntfy 2.34 and Odoo 18 in the long tests.

**Spec:** `docs/superpowers/specs/2026-10-28-erplibre-mobile-chat-notifications-design.md`
(lot 1 line of « Lots », « Decisions », « Controller's calls », the Odoo 18 /
ntfy 2.34 / app constraints, « Left to the builder »). User decisions:
`tasks/chat/p2-decisions.md`. Readings with file:line:
`tasks/chat/p2-recon-odoo.md`, `p2-recon-ntfy.md`, `p2-recon-mobile.md` (not
versioned). Conventions for every implementer: `tasks/chat/p2l1-conventions.md`.

Repos, all on `dev/mobile_chat`, never switch, never push: **M** =
`mobile/erplibre_home_mobile`, **E** = the ERPLibre root. **No change in the
addons repo**: module `erplibre_mobile_chat` stays 18.0.1.4.0 (1.5 is lot 2).
Paths are relative to their repo. Odoo sources cited as `mail/…` live in
`odoo18.0/odoo/addons/`; ntfy sources as `ntfy:…` are tag v2.34.0 (a clone
sits in the session scratchpad, `ntfysrc/src`). Java classes without a
package below are in `ca.erplibre.home.chatpush`, under
`android/app/src/main/java/ca/erplibre/home/chatpush/` (tests under
`android/app/src/test/java/ca/erplibre/home/chatpush/`).

## Rulings recorded here (the builder's, inside the spec)

- **R1 Native credential in lot 1.** The Odoo-direct summary runs with the
  WebView dead, so lot 1 introduces what the spec allows for lot 2: an
  encrypted copy of each account's Odoo session id (AES-GCM, key in the
  Android Keystore), never the password. Lot 1 uses it only for
  `/web/session/get_session_info`, `/mail/data` and `unregister_devices`;
  lot 2 reuses the same store for the actions. Mirrored by the JS each time a
  session is stored, only while the level is 1–4; level 5 and account removal
  erase it. A dead session (JSON-RPC code 100 or HTTP 401) stops that
  account's summary and says « ouvrez l'app » once; nothing re-authenticates
  natively.
- **R2 Read path that marks nothing read.** The summary reads
  `/web/session/get_session_info` (global mute) and `POST /mail/data`
  `{init_messaging: {}, channels_as_member: true}` — the route is
  `readonly=True` (`mail/controllers/webclient.py:24-29`), the app's own load
  call (`chatService.ts:390`), and carries every member channel's
  `message_unread_counter`, `message_needaction_counter`, `mute_until_dt`
  and the inbox counter (`mail/models/res_users.py:299-321`,
  `mail/controllers/discuss/channel.py:14-22`). Counting is `unreadTotal`'s
  (`chatService.ts:489-506`, `chatUnread.ts:16-48`). Never
  `/discuss/channel/messages`, `/mail/thread/messages`, `mark_as_read`,
  `set_message_done`.
- **R3 QR.** The terminal QR uses `segno` (pure Python, no dependency),
  declared in `requirement/erplibre_require-ments.txt` and imported lazily;
  without it the command prints the link and the install line. The app
  decodes a photo taken with `@capacitor/camera` through ML Kit
  barcode-scanning (bundled model, the ML Kit family the app already ships);
  pasting the link always works. No QR library in JS.
- **R4 Link.** `erplibre-ntfy:setup?v=1&url=<phone URL>&token=<tk_…>&prefix=<up…>&cache=<seconds>[&odoo=<Odoo-side URL>]`,
  values percent-encoded. Prefix `up` + 8 of `[a-z0-9]` (per phone and per
  ntfy); topic = prefix + 22 of `[a-z0-9]` (32 characters, ntfy allows 64,
  `ntfy:server/server.go:94`). `cache` comes from `cache-duration` of the
  server's `server.yml` (12 h when absent). Invented example used by every
  test on both sides: `erplibre-ntfy:setup?v=1&url=http%3A%2F%2Fntfy.exemple.test%3A8080&token=tk_exempleexempleexempleexemple&prefix=upab12cd34&cache=43200&odoo=http%3A%2F%2Fodoo-ntfy.exemple.test%3A8080`.
- **R5 One permanent notification.** The chat service and the SMS gateway
  post the same notification id (9101) on one shared channel
  `erplibre_permanent` (importance MIN), its text built from whoever holds
  it; the holder that stops while the other runs detaches
  (`STOP_FOREGROUND_DETACH`) and kicks the other, which re-asserts
  `startForeground` with the combined text. The old `erplibre_sms_gateway`
  channel is deleted on first post (the user's answer: the SMS gateway's
  notification becomes as discreet as the chat one, its old channel
  settings are lost).
- **R6 Build variant.** `-PnoChatRealtime` leaves out
  `android/app/src/realtime/` (the service class and its manifest fragment,
  added to the `debug` and `release` source sets only without the property)
  and sets `BuildConfig.CHAT_REALTIME = false`; main code reaches the service
  only by class name (the Whisper pattern, `MainActivity.java:31-43`), and
  the level policy maps 1–2 to 3. Task names stay `assembleDebug`.
- **R7 Registration.** At the first chat load of each foreground session the
  app calls `get_web_push_vapid_public_key` then `register_devices` with the
  same endpoint and keys: a no-op for a known device, a fresh row after a
  VAPID wipe or a 404/410 removal (`mail/models/mail_push_device.py:30-70`).
  Keys never change for a topic: a new key pair means a new topic, and the
  old endpoint is unregistered first (Odoo ignores new keys for a known
  endpoint of the same partner, `:54-63`). A new link for a known ntfy URL
  replaces its token and prefix and moves every account on it to a new topic.
  Removing an account unregisters online; offline, native code keeps the
  endpoint with the session copy and unregisters at its next run (7 days at
  most), then forgets both.
- **R8 Tap.** A notification's tap is `PendingIntent.getActivity` to
  `MainActivity` with extras `erplibre.push_open` (an app path) and
  `erplibre.push_key` (a per-install random secret): `MainActivity` is
  exported, so an intent without the secret is ignored. Paths allowed:
  `/chat`, `/chat/inbox?s=<configId>&thread=<model>,<resId>`,
  `/chat/<configId>/<channelId>`.
- **R9 Odoo-direct summary.** One notification per server, tag
  `summary:<configId>`, in its chat channel: posted (alerting) when the
  counted total rises above what it last showed, updated silently when it
  drops, cancelled at 0; tap → `/chat`. Accounts without ntfy are checked at
  every 15-minute job run at levels 1–4; an account on an ntfy whose last
  contact is older than the link's `cache` is checked once when contact
  comes back.
- **R10 Status of listening.** Levels 1–2: the permanent notification's line
  says the state (listening to N servers / waiting for the network /
  checking every 15 minutes / the failure reason). Levels 3–4: two failed
  runs in a row post one status notification (channel `status`, LOW)
  naming the server and the reason, cancelled when the next run succeeds.
  In the app: a banner in the chat list and a status panel in the
  notification options (Task 11).
- **R11 Default level: 3** (every 15 minutes, no permanent notification, no
  battery exemption) for an install that never chose one — the user's
  answer. `DEFAULT_CHAT_SETTINGS.notifyLevel` and
  `PushSettingsStore.level()`'s fallback both carry it.

## Global Constraints

- Everything in the project 1 plans' Global Constraints still holds (Odoo 18 only for chat, one commit per task per repo, `[TYPE] scope: subject` ≤ 72 chars in English, bilingual body EN then `--- FR ---`, ≤ 8 lines per language, `Assisted-by:` trailer, never an AI in `Co-authored-by:`, files named at `git add`, never `-A`).
- **One migration**: 2026102801 (`chat_push`). A guarded `DatabaseService.addChatPush()` (`CREATE TABLE IF NOT EXISTS`), the same table in `createChatTables`, in `renameChatRows` and in `ChatRepository.dropSource`. The latest migration today is 2026102705 (`src/services/migrations/index.ts:243`).
- Strings only through `t()`, keys in both `src/i18n/en.ts` and `fr.ts`. French labels fixed by the spec: « Préparer ntfy pour ERPLibre mobile », « Clavardage », « Boîte de réception », « Nouveau message — <serveur> », « Nouveau message », « N nouveaux messages — <serveur> », « Autoriser http ». Native code shows only strings the JS mirrored (Task 5 `PushStrings` keys), with French fallbacks for a first boot before any mirror.
- Every new `.ts`, `.scss` and `.java` file appears in `src/data/featureCatalog.ts`, leaf `chat.notifications` (label « Notifications du clavardage » / « Chat notifications », demo `{kind: "options"}`), sub-leaves `chat.notifications.native` (Java) and `chat.notifications.settings` (JS) when `files[]` passes 10.
- Nothing identifying anywhere — code, comments, tests, fixtures, commits: the invented values of `tasks/chat/p2l1-conventions.md` and the R4 link only. Comments say how the code works, present tense.
- Docs: edit `.base.md` only, regenerate with mmg (skill `erplibre-doc-i18n`).
- `HARNESS_API` 5 → 6 (`src/testing/syncTestKit.ts:59`, `long_test/mobile_sync_odoo.py:58`) and `DEVICE_HOOK_API` 6 → 7 (`src/testing/deviceTestHook.ts:31`, `long_test/mobile_sync_device.py:53`), each pair in Task 12; `test/test_mobile_sync_harness.py:368,749` follow.
- **Nothing in this lot marks anything read** (R2). Native code calls Odoo only on `/web/session/get_session_info`, `/mail/data` and `call_kw mail.push.device unregister_devices`.
- **Never the password natively**; the session copy, the ntfy token, the private keys and the auth secrets are sealed with `SecretBox` (Task 3) and never logged.
- **http**: native code refuses an `http://` URL (ntfy or Odoo) while the mirrored « Autoriser http » is off, with its own reason; an OS cleartext refusal (`UnknownServiceException` from OkHttp, APK built without `-PlanCleartext`, `android/app/build.gradle:39-53`) is a different reason. Loopback stays allowed by `network_security_config.xml`, which the device tests use through `adb reverse`.
- The ntfy `keepalive-interval` is never changed; `server.yml` is written only after the diff is shown and the operator said yes, with a timestamped backup; ntfy is restarted only after a second yes.
- Tests and tools never touch the user's ntfy (port 8080, `/etc/ntfy`, `/var/lib/ntfy`); every `ntfy` CLI call carries `--config <file>`.
- Odoo pushes synchronously only when the recipients have fewer than 5 devices (`mail/models/mail_thread.py:3816-3849`); the test servers run no cron, so every test keeps a recipient under 5 devices.
- `script/todo/ntfy_mobile.py` imports only the standard library at module level: the long-test harness imports it with any `python3`.
- Phone: only the test app `ca.erplibre.home.synctest`; never lock the screen; restore `stay_on_while_plugged_in` and the deviceidle allowlist; `./gradlew --stop` after builds.

## Review Focus

1. **An ntfy on the LAN over http with « Autoriser http » off, or reached by an APK built without the cleartext flag:** the account is shown as not listening with the right reason (« http non autorisé » vs « http bloqué par cette version de l'app »), nothing leaves in clear, and turning the option on resumes without a restart (Task 4 `http is refused before any request when not allowed`, `cleartext refusal by the system has its own kind`; Task 7 `turning allowHttp on reconnects`; Task 11 `the banner names the http reason`).
2. **A phone silent longer than the ntfy cache, or back with a cursor ntfy no longer knows:** ntfy replays its whole cache; nothing shows twice, and the server gets one Odoo-direct summary instead of the lost pushes (Task 4 `an unknown since id replays and duplicates are dropped by id`; Task 7 `silence above the cache runs the Odoo-direct summary once`, `a replay after reconnect shows each message once`).
3. **Odoo regenerates its VAPID keys (restored or neutralised database) or drops the device after a 404/410:** the next app load registers the same endpoint again and pushes resume, without new keys (Task 10 `a wiped device is registered again at the next foreground load`; Task 12 long test `a VAPID wipe is healed by the next load`).
4. **A QR re-applied for a known ntfy (new prefix), or an account removed while offline:** the accounts move to new topics, every old endpoint is unregistered (now or at the next native run), and no stale key decrypts anything (Task 10 `a new prefix moves every account to a new topic and unregisters the old endpoint`, `a removal offline leaves the endpoint to native code`; Task 7 `a pending unregister runs with the session copy then forgets it`; Task 12 long test).
5. **Default lock screen on a confidential server, with the longest body Odoo sends (3993 bytes of accented JSON, 4096 encrypted):** the body decrypts; the locked screen shows only « Nouveau message — <serveur> »; « jamais affiché » shows « Nouveau message » even unlocked (Task 3 `a 4096-byte body decrypts`; Task 5 the three lock-screen tests; Task 12 device `dumpsys notification --noredact` check).

---

## File Structure

Each task's **Files** block is the authority. In short: **E** gains `script/todo/ntfy_mobile.py` (pure functions, runners) and `ntfy_mobile_menu.py` (menu mixin), `long_test/mobile_sync_ntfy.py` (the harness ntfy) and `long_test/mobile_sync/chatPush.test.ts`. **M** gains the Java package `chatpush/` (pure, JVM-tested: crypto, ntfy client, model, policy, stores, Odoo-direct, engine; Android glue: notifier, open intent, runtime, job, boot receiver, permanent notice), `ChatPushPlugin.java` and `BatteryExemption.java` beside the other plugins, the source set `android/app/src/realtime/` (the service alone), and on the JS side `src/plugins/chatPushPlugin.ts`, `src/services/chat/chatPushLink.ts`, `chatPush.ts`, `chatPushOpen.ts`, the migration `addChatPush.ts`, the options component `chat_notifications/`, and the test kit's `webPushNode.ts` and `pushNodeNative.ts`.

---

### Task 0: Validation spike (Odoo 18 → throwaway ntfy → decrypt) and the lot 5 carry-over

Nothing below Task 0 is built until its checks pass and their outcomes are in `tasks/chat/p2l1-sdd/ledger.md`.

**Files:** spike under `tasks/chat/p2l1-sdd/spike/` (not versioned): `spike.py` (run with `.venv.erplibre/bin/python -I`, uses `requests` and `cryptography`), `server.yml` written by it; output vector `tasks/chat/p2l1-sdd/odoo18_push_vector.json`. Carry-over: M `src/services/chat/chatOutbox.ts` (`giveUpMessage` `:3925-3946`), `src/__tests__/chatOutbox.test.ts`.

**Interfaces:**
- Produces for Task 3: `odoo18_push_vector.json` = `{ua_private_pkcs8: <base64>, ua_public: <base64url, 65 bytes>, auth: <base64url, 16 bytes>, body: <base64 of the ntfy message, as received>, encoding: "base64", plaintext: <the decrypted JSON text>}` — keys generated for the spike, message text invented (« Bonjour du test de notification »).
- Produces for Tasks 5 and 12: the exact plaintext JSON shapes for a chat, a group, a channel mention and a record comment, copied into the ledger.

- [ ] **Step 1: Start the pieces.** `./long_test/mobile_sync.py --versions 18 --filtre smoke --garder` (a kept Odoo 18 with `admin`, `chat_user`, « ms chat »; its URL and database in the run's `targets.json`). In the spike: a free port, a temp dir, `server.yml` = `listen-http: "127.0.0.1:<port>"`, `base-url`, `cache-file`, `cache-duration: "12h"`, `auth-file`, `auth-default-access: "deny-all"`; `ntfy serve --config <yml>` in the background; once `/v1/health` answers, `ntfy access --config <yml> everyone 'up*' write-only`, `NTFY_PASSWORD=<random> ntfy user add --config <yml> --ignore-exists erm_spike`, `ntfy access --config <yml> erm_spike 'upab12cd34*' read-only`, `ntfy token add --config <yml> --label=erplibre-mobile erm_spike`.
- [ ] **Step 2: Odoo → ntfy.** As admin (JSON-RPC), `get_web_push_vapid_public_key`, then `register_devices` with `endpoint=http://127.0.0.1:<port>/upab12cd34<22 random>`, `keys={p256dh, auth}` of a P-256 pair made by `cryptography`; as `chat_user`, post in its chat with admin (`/mail/message/post`); then in « ms chat » with `@admin`; then a comment on a record admin follows. Record the post's duration.
- [ ] **Step 3: Checks, each written to the ledger with its evidence:**
  (a) Odoo's log shows `Failed push notification … 200` for each push (ntfy answers 200, `ntfy:server/server.go:1130-1137`) — expected, accepted until module 1.5;
  (b) `GET /<topic>/json?poll=1&since=all` with `Authorization: Bearer <token>` returns one `message` event per push with `"encoding":"base64"`;
  (c) anonymous publish with Odoo's `Authorization: vapid …` header was accepted under deny-all (b proves it); anonymous `GET` of the topic → 403; the token on `upzz99yy88aaa` → 403; anonymous `POST` to a topic not starting with `up` → 403;
  (d) RFC 8291 decryption of each body with the spike's private key and auth gives JSON with `title`, `options.body`, `options.data.{model,res_id[,action]}` — shapes copied to the ledger, the chat one into the vector file;
  (e) with a phone plugged: `adb reverse tcp:<port> tcp:<port>`, then `adb shell 'printf "GET /v1/health HTTP/1.0\r\n\r\n" | toybox nc 127.0.0.1 <port>'` answers `"healthy":true` — the device tests use one URL, `http://127.0.0.1:<port>`, for the phone and for Odoo;
  (f) a device registered with an unreachable endpoint (`http://127.0.0.1:<closed port>/…`) makes the post take about 5 s (informational, for the docs).
- [ ] **Step 4: Outcome rule.** All of (a)–(e) as expected → go. (b) shows raw text instead of base64 → no change (Task 4 already accepts both). (c) refused → STOP and report: the transport design rests on anonymous write-only `up*`. Stop the spike's ntfy, `./long_test/mobile_sync.py --detruire`, remove the temp dir.
- [ ] **Step 5: Carry-over (lot 5 final review, parked):** failing test `a load landing while a refused edit is given up keeps the original body` and the same for a delete (`chatOutbox.test.ts`, the pattern of « a load landing while a refused star is given up »); then the edit/delete branch of `giveUpMessage` runs its `showBody` through `giveUpRestoring` (restore and blocked mark in one `exclusive()` task); `npm test`.
- [ ] **Step 6: Commit** (M): `[FIX] chat: edit and delete give-ups restore inside the account lock`.

### Task 1: `ntfy_mobile.py` — checks, phone access script, link, QR (E)

**Files:** E create `script/todo/ntfy_mobile.py`, `test/test_ntfy_mobile.py`; modify `requirement/erplibre_require-ments.txt` (`segno`, with a comment: the QR of `ntfy_mobile.render_qr`, imported lazily).

**Interfaces** (all pure unless marked; stdlib only at module level):
- `DEFAULT_CONFIG = "/etc/ntfy/server.yml"`; `PHONE_USER_PREFIX = "erm_"`; `LINK_SCHEME = "erplibre-ntfy:"`.
- `random_prefix(rng=secrets) -> str` (`up` + 8 of `[a-z0-9]`); `phone_user(label: str) -> str` (`erm_` + label folded (NFD, marks removed), lowered, characters outside `[a-z0-9_-]` dropped; empty → `ValueError`).
- `read_yml_keys(text: str) -> dict[str, str]`: top-level `key: value` lines of a `server.yml` (quotes stripped, comments ignored) — no YAML library: the file is flat.
- `config_problems(keys: dict) -> list[str]` (i18n keys): no `auth-file` → `"ntfy_mobile_no_auth_file"`; `auth-default-access` not `deny-all` → `"ntfy_mobile_not_deny_all"`; `visitor-subscriber-rate-limiting` true → `"ntfy_mobile_subscriber_rate_limiting"`.
- `cache_seconds(keys) -> int` (`cache-duration` as `12h`/`30m`/`3600s`/`2d`, absent → 43200).
- `with_exempt_hosts(text: str, hosts: list[str]) -> str`: sets `visitor-request-limit-exempt-hosts` to the union of the present value and `hosts` (comma list, order kept, no duplicate), replacing the active line or appending one; every other line byte-identical (keepalive included). `with_subscriber_rate_limiting_off(text) -> str` likewise.
- `unified_diff(old, new, path) -> str` (difflib).
- `access_script(config: str, user: str, prefix: str, label: str = "erplibre-mobile") -> str`: a POSIX `sh` script that runs, each `ntfy` call with `--config '<config>'`, `set -e`: `ntfy access … everyone 'up*' write-only`; `NTFY_PASSWORD="$(head -c 32 /dev/urandom | base64)" ntfy user add … --ignore-exists '<user>'`; `ntfy access … '<user>' '<prefix>*' read-only`; `ntfy token add … --label='<label>' '<user>'` (no `--expires`: never expires); values shell-quoted (`shlex.quote`).
- `inspect_script(config) -> str`: prints `@@VERSION <ntfy --help version line>`, `@@OWNER <stat -c %U of the auth file>` , `@@YML <base64 of server.yml>`, `@@HEALTH <curl or wget of /v1/health on the listen address, else "?">`.
- `parse_markers(output: str) -> dict[str, str]`; `parse_token(output: str) -> str | None` (`token (tk_[A-Za-z0-9]+) created`, `ntfy:cmd/token.go:133-136`).
- `revoke_script(config, user) -> str` (`ntfy user del`), `list_script(config) -> str` (`ntfy access` output), `phone_users(output) -> list[str]` (users starting `erm_`).
- `write_yml_script(config: str, new_text: str, stamp: str) -> str` (backup `<config>.bak-<stamp>`, then the content through base64, ownership and mode kept); `restart_script() -> str` (`systemctl restart ntfy`, then health).
- `build_link(phone_url, token, prefix, cache_s, odoo_url=None) -> str` (R4, `urllib.parse.quote(…, safe="")`).
- `render_qr(link: str) -> str | None`: `segno.make(link, error="m").terminal(compact=True)` captured to a string; `None` when `segno` is not importable.
- Runners: `class LocalHost(sudo: tuple[str, ...] = ("sudo",)): run(script: str, sudo_user: str | None) -> tuple[int, str]` (`sudo [-u <user>] sh -c <script>`; `sudo=()` runs `sh -c` as the current user, which the tests and the harness use; output streamed to the terminal byte by byte and captured; the sudo prompt reaches the terminal); `class SshHost(target: str): run(...)` (`ssh -t <target> sudo [-u <user>] sh -c <quoted script>` with the same tee, `env=TODO._qemu_c_env()` as `_ssh_probe` does, `todo.py:2697-2720`).

- [ ] **Step 1: Failing tests** (`test/test_ntfy_mobile.py`, no subprocess but the runner test with `sh` in place of `sudo`): `test_prefix_shape_and_randomness`; `test_phone_user_sanitized` (« Téléphone de Bruno » → `erm_telephonedebruno`; « !! » → ValueError); `test_config_problems` (the three keys, and none for the installer's file of `script/install/install_ntfy.sh`); `test_cache_seconds_units`; `test_exempt_hosts_merge_keeps_other_lines_byte_identical` (a file with a commented `# keepalive-interval: "45s"` and an active `keepalive-interval: "45s"`: both unchanged; `127.0.0.1` added to `"odoo.exemple.test"` gives `"odoo.exemple.test,127.0.0.1"`; adding a present host changes nothing); `test_subscriber_rate_limiting_turned_off`; `test_access_script_every_ntfy_call_has_config` (regex over every line calling `ntfy`); `test_access_script_never_sets_expiry_or_keepalive`; `test_access_script_quotes_values` (a label with a quote cannot break out); `test_parse_token` (the CLI's line, and None on an error text); `test_link_round_trip` (the R4 example string exactly); `test_render_qr_none_without_segno` (`sys.modules["segno"] = None`); `test_render_qr_draws_with_segno` (skipped when segno absent); `test_local_runner_tees_and_captures` (`LocalHost(sudo=())`, script `printf 'a'; printf '@@TOKEN x\n'` → on stdout and in the result); `test_module_imports_only_stdlib` (ast scan of top-level imports).
- [ ] **Step 2: Run** `.venv.erplibre/bin/python -m unittest test.test_ntfy_mobile` → FAIL.
- [ ] **Step 3: Implement** the interfaces; `.venv.erplibre/bin/pip install segno` locally; `test/test_tooling_requirements.py` stays green.
- [ ] **Step 4: Run** the two test modules → PASS; black, flake8.
- [ ] **Step 5: Commit** (E): `[ADD] todo: ntfy for ERPLibre mobile, ACL, phone user, link, QR`.

### Task 2: todo menu « Préparer ntfy pour ERPLibre mobile » — prepare, list, revoke, local or ssh (E)

**Files:** E create `script/todo/ntfy_mobile_menu.py`, `test/test_todo_ntfy_mobile.py`; modify `script/todo/todo.py` (import and mixin; the deploy menu: new entry right after « Deploy - Install NTFY notification server », statuses 9→10, 10→11, 11→12 shifted), `script/todo/todo_i18n.py` (a `# NTFY for ERPLibre mobile` group after `:3371`).

**Interfaces:**
- Consumes Task 1 entirely.
- `class NtfyMobileMenuMixin`: `prompt_execute_ntfy_mobile(self)` (submenu: [1] prepare a phone, [2] list phones, [3] revoke a phone; [0] back), `_ntfy_mobile_host(self) -> LocalHost | SshHost | None` (asks « Sur cette machine ou par ssh ? »; ssh uses `self._ask_ssh_target()` `todo.py:2763`, its `cible`), `_ntfy_mobile_prepare(self)`, `_ntfy_mobile_list(self)`, `_ntfy_mobile_revoke(self)`.
- i18n keys (both languages): `"Deploy - Prepare ntfy for ERPLibre mobile"` → fr « 📱 Déployer - Préparer ntfy pour ERPLibre mobile », and every prompt and message the flow shows (config path, phone label, phone-side URL, Odoo-side URL, Odoo source addresses, diff confirmation, restart confirmation, link warning, revoke confirmation, the three `config_problems` keys).
- Prepare flow, in this order:
  1. host; config path (default `DEFAULT_CONFIG`); `inspect_script` through `host.run(…, sudo_user=None)` (root reads every file); problems from `config_problems` other than subscriber rate limiting → printed, stop (the installer's job, entry 8);
  2. the Odoo source addresses to exempt (default `127.0.0.1` locally, none over ssh; blank skips with a warning that a busy Odoo hits 429 and loses pushes) and the subscriber-rate-limiting fix when needed → new text via `with_exempt_hosts` / `with_subscriber_rate_limiting_off`; when it differs: print `unified_diff`, ask y/N; yes → `write_yml_script`, then ask y/N to restart → `restart_script`; no → continue with a warning naming what stays;
  3. phone label → `phone_user`; `random_prefix()`; `access_script` run as the auth file's owner (`@@OWNER`); token from `parse_token`, none → error printed, stop;
  4. phone-side URL (default: `base-url` when it is not `localhost`/`127.0.0.1`, else `http://<LAN address of this host>:<port of listen-http>` locally, `http://<ssh host>:<port>` over ssh) and Odoo-side URL (blank: the same);
  5. `build_link`; `render_qr` drawn, or the hint `pip install -r requirement/erplibre_require-ments.txt`; the link printed under it with « Ce lien donne accès aux notifications de ce téléphone : ne le partagez pas. » The token is never written to a file.
- List: `list_script` → `phone_users`. Revoke: choose one, confirm, `revoke_script` (`ntfy user del` removes its tokens and ACL rows).

- [ ] **Step 1: Failing tests** (`test/test_todo_ntfy_mobile.py`: a `TODO` built as in `test/test_todo_menu.py`, `input` and `click.prompt` patched, a fake host recording scripts and returning canned outputs): `test_menu_entry_after_install_and_numbering_shifted` (statuses 1–12 map to the same methods as before, 9 is the new one); `test_prepare_stops_on_missing_auth_file`; `test_prepare_shows_diff_and_writes_only_after_yes`; `test_prepare_no_to_diff_writes_nothing_and_warns`; `test_restart_asked_separately`; `test_prepare_runs_access_as_auth_file_owner`; `test_prepare_prints_link_and_never_writes_token` (no `open(` for writing during the flow); `test_prepare_without_segno_prints_install_hint`; `test_ssh_host_quotes_the_script_once` (the argv of `SshHost`); `test_revoke_confirms_then_deletes_user`; `test_every_new_string_translated` (each key used by the mixin exists in `TRANSLATIONS` with `fr` and `en`).
- [ ] **Step 2–3:** FAIL → implement → PASS; `python3 -m py_compile script/todo/todo.py script/todo/todo_i18n.py`; `test/test_todo_i18n.py`, `test/test_todo_menu.py` green.
- [ ] **Step 4: Manual check against the user's ntfy: none.** The real-ntfy proof of these scripts is Task 12's harness, which runs `access_script` against its throwaway server.
- [ ] **Step 5: Commit** (E): `[ADD] todo: menu to prepare ntfy for ERPLibre mobile, local or ssh`.

### Task 3: RFC 8291 decryption, key pairs, sealed secrets (M, Java)

**Files:** M create `chatpush/Hkdf.java`, `WebPushKeys.java`, `WebPushDecrypt.java`, `WebPushException.java`, `SecretBox.java`, `KeystoreKeys.java`; tests `HkdfTest.java`, `WebPushDecryptTest.java`, `SecretBoxTest.java`, `WebPushTestEncrypt.java` (test helper), resource `chatpush/odoo18_push.json` (Task 0's vector).

**Interfaces:**
- `final class Hkdf { static byte[] extract(byte[] salt, byte[] ikm); static byte[] expand(byte[] prk, byte[] info, int length); }` (HMAC-SHA256, RFC 5869).
- `final class WebPushKeys { static KeyPair generate(); static byte[] encodePublic(ECPublicKey k) /* 65 bytes, 0x04‖X‖Y */; static ECPublicKey decodePublic(byte[] raw); static ECPrivateKey decodePrivate(byte[] pkcs8); static byte[] newAuthSecret() /* 16 bytes, SecureRandom */; static String b64url(byte[] b) /* no padding */; static byte[] unb64url(String s); }` — `secp256r1` through `KeyPairGenerator("EC")`, software keys (minSdk 24 has no Keystore ECDH).
- `final class WebPushDecrypt { static byte[] decrypt(byte[] body, ECPrivateKey uaPrivate, byte[] uaPublic, byte[] authSecret) throws WebPushException; }` — RFC 8188 header: salt(16) ‖ rs(uint32 BE) ‖ idlen(1) ‖ keyid (the 65-byte server public key); `ecdh = ECDH(uaPrivate, keyid)`; `prk_key = HMAC(auth, ecdh)`; `ikm = expand(prk_key, "WebPush: info\0" ‖ uaPublic ‖ keyid, 32)`; `prk = HMAC(salt, ikm)`; `cek = expand(prk, "Content-Encoding: aes128gcm\0", 16)`, `nonce = expand(prk, "Content-Encoding: nonce\0", 12)` XOR the record sequence number; records of `rs` bytes, AES-128-GCM, padding removed back to the delimiter (`0x02` last record, `0x01` others).
- `final class WebPushException extends Exception { enum Reason { TRUNCATED, BAD_HEADER, AUTH_FAILED, BAD_PADDING } Reason reason(); }` — the message never carries key or body bytes.
- `final class SecretBox { interface KeyProvider { javax.crypto.SecretKey key() throws GeneralSecurityException; } SecretBox(KeyProvider p); String seal(byte[] plain) /* "v1:<b64 iv>:<b64 ct>", AES-256-GCM, 12-byte iv */; byte[] open(String sealed) throws GeneralSecurityException; }`; `KeystoreKeys.provider(String alias): SecretBox.KeyProvider` (AndroidKeyStore AES-256 GCM, created on first use; not JVM-tested).
- Test helper `WebPushTestEncrypt.encrypt(byte[] plaintext, byte[] uaPublic, byte[] authSecret, int recordSize): byte[]` (the RFC's sender side, a fresh server key per call; Tasks 4 and 7 use it).

- [ ] **Step 1: Failing JUnit:** `HkdfTest` RFC 5869 test case 1 (values copied verbatim from the RFC's appendix A.1); `WebPushDecryptTest`: `rfc8291 appendix A vector decrypts` (every value copied verbatim from RFC 8291 Appendix A, plaintext « When I grow up, I want to be a watermelon »); `odoo 18 vector decrypts to its JSON` (resource file, Task 0); `a 4096-byte body decrypts` (WebPushTestEncrypt, rs 4096, the plaintext padded to 4096 − 86 − 17 = 3993 bytes of `é`-escaped JSON as Odoo sizes it); `a wrong auth secret fails with AUTH_FAILED`; `a flipped ciphertext byte fails with AUTH_FAILED`; `a body shorter than the header is TRUNCATED`; `a keyid not 65 bytes is BAD_HEADER`; `two records decrypt` (rs 32); `the exception message holds no key bytes`; `SecretBoxTest`: `seal then open`, `two seals differ`, `a tampered seal fails`, `an unknown version prefix fails` (KeyProvider over a fixed test key).
- [ ] **Step 2: Run** `BUNDLE_SKIP_WHISPER=1 ./gradlew :app:testDebugUnitTest --tests 'ca.erplibre.home.chatpush.*'` → FAIL.
- [ ] **Step 3: Implement** the interfaces.
- [ ] **Step 4: Run** → PASS; `./gradlew --stop`.
- [ ] **Step 5: Commit** (M): `[ADD] chat push: RFC 8291 decryption and per-account key pairs`.

### Task 4: ntfy client, messages, payload, dedup (M, Java)

**Files:** M create `chatpush/HttpPolicy.java`, `NtfyServer.java`, `NtfyMessage.java`, `NtfyException.java`, `NtfyClient.java`, `SeenIds.java`, `PushPayload.java`; tests `NtfyClientTest.java`, `PushPayloadTest.java`, `SeenIdsTest.java`.

**Interfaces:**
- `final class HttpPolicy { static boolean allowed(String url, boolean allowHttp); }` (`https://` always; `http://` only with allowHttp).
- `final class NtfyServer { final String url /* phone side, normalized: scheme and host lower case, no trailing slash */; final String token; final String prefix; final int cacheSeconds; static String normalize(String url); }`
- `final class NtfyMessage { final String id; final long time; final String event /* open|keepalive|message|message_delete|message_clear|poll_request */; final String topic; final byte[] body /* base64-decoded when "encoding":"base64", else the message's UTF-8 bytes */; static NtfyMessage parse(String jsonLine) throws NtfyException; }` (`ntfy:model/model.go:14-52`).
- `final class NtfyException extends Exception { enum Kind { UNAUTHORIZED, FORBIDDEN, RATE_LIMITED, UNREACHABLE, HTTP_REFUSED, CLEARTEXT_BLOCKED, PROTOCOL } Kind kind(); }` — 401 → UNAUTHORIZED, 403 → FORBIDDEN, 429 → RATE_LIMITED, connect/timeout/DNS → UNREACHABLE, `UnknownServiceException` → CLEARTEXT_BLOCKED, policy → HTTP_REFUSED, anything else → PROTOCOL.
- `final class NtfyClient { NtfyClient(OkHttpClient base); interface Listener { void onOpen(); void onMessage(NtfyMessage m); void onKeepalive(); void onClosed(NtfyException cause /* null on a clean close */); } okhttp3.Call stream(NtfyServer s, List<String> topics, String since, boolean allowHttp, Listener l); List<NtfyMessage> poll(NtfyServer s, List<String> topics, String since, boolean allowHttp) throws NtfyException; void checkRead(NtfyServer s, String topic, boolean allowHttp) throws NtfyException; static final int MAX_TOPICS = 150; }`
  - `stream`: `GET <url>/<t1>,<t2>/json?since=<since>`, `Authorization: Bearer <token>`, read timeout 120 s (covers a server keepalive up to about 100 s; the keepalive is the server's, never changed), one line per event, on OkHttp's thread;
  - `poll`: `…/json?poll=1&since=<since>` — `since` is required (a poll without it returns the whole cache, `ntfy:server/server.go:1982-1984`);
  - `checkRead`: `GET <url>/<topic>/auth` (`ntfy:server/server.go:812-813`);
  - more than `MAX_TOPICS` topics → `IllegalArgumentException`; the policy check comes before any request.
- `final class SeenIds { SeenIds(String serialized, int capacity /* 500 */); boolean add(String id) /* false when seen */; String serialize(); }` (oldest dropped first).
- `final class PushPayload { final String title; final String body; final String model; final long resId /* 0 when "" */; final String action; boolean isChat() /* model == "discuss.channel" */; static PushPayload parse(byte[] json) throws JSONException; }` (`mail/models/mail_thread.py:3851-3892`, `discuss_channel.py:669-689`; shapes as recorded by Task 0).

- [ ] **Step 1: Failing JUnit** (MockWebServer as ntfy): `stream sends the bearer token and the since cursor`; `stream delivers open, keepalive and message events in order`; `a base64 message body is decoded, a raw one taken as UTF-8`; `poll always sends since`; `an unknown since id replays and duplicates are dropped by id` (server replays three events, two already in SeenIds → one new); `401, 403 and 429 map to their kinds`; `a refused connection is UNREACHABLE`; `http is refused before any request when not allowed` (MockWebServer sees no request); `cleartext refusal by the system has its own kind` (an interceptor throwing `UnknownServiceException`); `more than 150 topics is refused`; `checkRead passes on 200 and fails FORBIDDEN on 403`; `SeenIds keeps the last 500 and round-trips`; `PushPayload` of each Task 0 shape: a chat, a channel with `action`, a record comment (no `action`, other model), `res_id` empty string → 0, accented title escaped `é`.
- [ ] **Step 2–4:** FAIL → implement → PASS; `./gradlew --stop`.
- [ ] **Step 5: Commit** (M): `[ADD] chat push: native ntfy client, stream, poll and read check`.

### Task 5: Notification model per server, lock screen, levels 1 to 5 (M, Java)

**Files:** M create `chatpush/LockScreenMode.java`, `PushStrings.java`, `NotificationModel.java`, `PushLevelPolicy.java`; tests `NotificationModelTest.java`, `PushLevelPolicyTest.java`.

**Interfaces:**
- `enum LockScreenMode { HIDDEN_LOCKED("hidden_locked"), NEVER("never"), ALWAYS("always"); static LockScreenMode fromKey(String k) /* unknown → HIDDEN_LOCKED */; }`
- `final class PushStrings { PushStrings(Map<String, String> mirrored); String get(String key); String format(String key, Map<String, String> vars) /* {name} placeholders */; }` — keys and French fallbacks: `new_message` « Nouveau message »; `new_message_server` « Nouveau message — {server} »; `summary_one` « 1 nouveau message — {server} »; `summary` « {n} nouveaux messages — {server} »; `channel_chat` « Clavardage »; `channel_inbox` « Boîte de réception »; `channel_status` « État des notifications »; `channel_permanent` « Services permanents »; `permanent_listening_one` « À l'écoute d'un serveur »; `permanent_listening` « À l'écoute de {n} serveurs »; `permanent_waiting` « En attente du réseau »; `permanent_polling` « Vérification toutes les 15 minutes »; `permanent_failing` « {server} : {reason} »; `status_not_listening` « Les notifications de {server} ne passent plus : {reason} »; `status_session_expired` « Ouvrez l'app pour reprendre les notifications de {server} »; `reason_unauthorized` « jeton refusé par ntfy »; `reason_forbidden` « accès refusé par ntfy »; `reason_unreachable` « ntfy injoignable »; `reason_rate_limited` « trop de requêtes »; `reason_http_refused` « http non autorisé »; `reason_cleartext_blocked` « http bloqué par cette version de l'app »; `reason_session_expired` « session Odoo expirée »; `reason_protocol` « réponse inattendue ».
- `final class AccountView { final String configId; final String label; final LockScreenMode lockScreen; final Map<Long, ChannelInfo> channels; }`, `final class ChannelInfo { final String name; final String type /* chat|group|channel */; }` (mirrored by Task 10).
- `final class NotificationModel`:
  - `static String hashOf(String configId)` (first 12 hex of SHA-256); channel ids `chat.<h>`, `inbox.<h>`, `status`, group id `server.<h>`;
  - `static Shown chat(AccountView a, PushPayload p, PushStrings s)` — tag `chat:<configId>:<resId>`; conversation title = the mirrored channel name, else the payload title; author = the payload title with the known prefix removed (channel: `#<name> - `, group: `<name> - `, chat: the whole title, `discuss_channel.py:669-689`), else the whole title; text = body (empty body → `new_message`); open url `/chat/<encoded configId>/<resId>`;
  - `static Shown inbox(AccountView a, PushPayload p, PushStrings s)` — tag `inbox:<configId>:<model>:<resId>`; title = payload title; open url `/chat/inbox?s=<encoded configId>&thread=<model>,<resId>`;
  - `static Shown summary(AccountView a, int count, PushStrings s)` — tag `summary:<configId>`, channel `chat.<h>`, open url `/chat`, public content (no message text in it);
  - `final class Shown { String channelId, groupId, tag, conversationTitle, author, text, publicTitle, openUrl; boolean messaging; boolean privateVisibility; }` — lock screen: HIDDEN_LOCKED → `privateVisibility` with `publicTitle` = `new_message_server`; NEVER → title and text both `new_message`, `messaging` false, `publicTitle` = `new_message`; ALWAYS → public, full content.
- `final class PushLevelPolicy`:
  - `enum Mode { REALTIME, POLL_15, POLL_60, OFF }`; `final class PowerState { final boolean wifi, charging, saver; final int batteryPct; }`;
  - `interface LevelClimber { int climb(int chosen, PowerState s); }`, `LevelClimber NO_CLIMB = (c, s) -> c;` — lot 3 supplies the battery-saver and threshold climber here, nothing else changes;
  - `static Effective resolve(int chosen, PowerState s, boolean realtimeBuild, LevelClimber climber)` → `final class Effective { final int level; final Mode mode; final boolean permanentService; final boolean odooDirect; }`: level = climber result clamped 1–5, then 1–2 → 3 when `!realtimeBuild`; 1 → REALTIME + permanent; 2 → REALTIME when wifi or charging else POLL_15, permanent either way; 3 → POLL_15; 4 → POLL_60; 5 → OFF; `odooDirect` = level ≤ 4.

- [ ] **Step 1: Failing JUnit:** `NotificationModelTest`: `a chat push is titled by the conversation, the author from the title`; `a channel push strips the #name - prefix`; `a group push strips the name - prefix`; `an unknown conversation keeps the payload title`; `an empty body says new message`; `hidden when locked is private with the server in the public title`; `never shown says new message even unlocked`; `always shown is public with the text`; `a record push goes to the inbox channel and opens its thread in the inbox`; `channel ids are per server and carry no configId text`; `the summary says 1 or n new messages and is public`; `mirrored strings win over the French fallbacks`. `PushLevelPolicyTest`: the 5 × (wifi, charging) table; `levels 1 and 2 map to 3 without the realtime build`; `a climber result above 5 is 5`; `odooDirect off only at level 5`.
- [ ] **Step 2–4:** FAIL → implement → PASS; `./gradlew --stop`.
- [ ] **Step 5: Commit** (M): `[ADD] chat push: notification model per server, levels 1 to 5`.

### Task 6: Native stores, session copy, Odoo unread summary (M, Java)

**Files:** M create `chatpush/KeyValue.java`, `PrefsKeyValue.java`, `PushStore.java`, `PushSettingsStore.java`, `NativeSessions.java`, `UnreadSummary.java`, `OdooDirect.java`; tests `PushStoreTest.java`, `UnreadSummaryTest.java`, `OdooDirectTest.java`, resource `chatpush/mail_data_counters.json` (hand-written, the shape of `chatStore.ts` `parseStore` `:258-347`: two chats, a group, a channel with and without mention, a muted chat, the inbox counter).

**Interfaces:**
- `interface KeyValue { String get(String k); void put(String k, String v); void remove(String k); Set<String> keys(); }`; `PrefsKeyValue(Context, String file)` writes with `commit()` (a kill right after a write keeps it); tests use a `HashMap`-backed implementation in the test tree.
- `final class PushStore { PushStore(KeyValue kv, SecretBox box); void putNtfy(NtfyServer s); NtfyServer ntfy(String url); List<NtfyServer> ntfys(); void removeNtfy(String url); Subscription subscribe(String configId, String ntfyUrl, boolean renew); Subscription subscription(String configId); Subscription byTopic(String topic); List<Subscription> subscriptions(String ntfyUrl); void unsubscribe(String configId); String cursor(String url); void setCursor(String url, String lastId, long contactAt); long lastContactAt(String url); SeenIds seen(String url); void saveSeen(String url, SeenIds s); }` with `final class Subscription { final String configId, ntfyUrl, topic; final byte[] publicKey, authSecret; ECPrivateKey privateKey(); }` — `subscribe` returns the existing subscription unless `renew` or the ntfy prefix changed, else a new key pair (Task 3), a new auth secret and a new topic (prefix + 22 of `[a-z0-9]`, R4); token, private key and auth secret sealed.
- `final class PushSettingsStore { PushSettingsStore(KeyValue kv); void put(int level, boolean allowHttp, Map<String,String> strings, List<AccountView> accounts); int level() /* 3 before any mirror */; boolean allowHttp(); PushStrings strings(); AccountView account(String configId); List<AccountView> accounts(); boolean foreground(); void setForeground(boolean f); void beat(long at); long lastBeat(); String openKey() /* random per install, R8 */; }`
- `final class NativeSessions { NativeSessions(KeyValue kv, SecretBox box); void put(NativeSession s); NativeSession get(String configId); void forget(String configId); void markExpired(String configId); boolean expired(String configId); void addPendingUnregister(String configId, String endpoint); List<PendingUnregister> pending(); void donePending(String configId); }`, `final class NativeSession { final String configId, odooUrl, database, sessionId; final long savedAt; }`, `PendingUnregister { configId, endpoint, since }` (dropped after 7 days).
- `final class UnreadSummary { final int total; final Set<Long> readChannelIds /* counted unread 0 */; static UnreadSummary of(JSONObject mailData, String globalMuteUntil, long nowMs); }` — chat/group count `message_unread_counter`, channel counts `message_needaction_counter`, a channel muted (its `mute_until_dt` or the global one ahead of now) counts nothing, plus the inbox counter minus the channels' mentions, never below 0: `chatService.ts:489-506` and `chatUnread.ts:16-48` exactly.
- `final class OdooDirect { OdooDirect(OkHttpClient base); UnreadSummary check(NativeSession s, boolean allowHttp, long nowMs) throws OdooDirectException; void unregister(NativeSession s, String endpoint, boolean allowHttp) throws OdooDirectException; }` — `Cookie: session_id=<id>`, no cookie jar, no redirect (as `ChatFileTransfer.java`); `check` = `POST /web/session/get_session_info` (global mute from `storeData.settings.mute_until_dt`, as `odooRpcClient.ts:406`) then `POST /mail/data` `{init_messaging: {}, channels_as_member: true}`; `unregister` = `/web/dataset/call_kw/mail.push.device/unregister_devices` kwargs `{endpoint}`; `OdooDirectException.Kind { SESSION_EXPIRED /* JSON-RPC code 100 or HTTP 401, odooRpcClient.ts:360 */, UNREACHABLE, HTTP_REFUSED, CLEARTEXT_BLOCKED, PROTOCOL }`.

- [ ] **Step 1: Failing JUnit:** `PushStoreTest`: `a subscription is kept until renewed`; `a new prefix renews every subscription of that ntfy`; `byTopic finds the account`; `secrets are stored sealed` (no `tk_` and no key bytes in any raw value); `unsubscribe forgets keys and topic`; `cursor and contact time round-trip`. `UnreadSummaryTest` (resource): `chats count unread, channels count mentions`; `a muted conversation and the global mute count nothing`; `the inbox counts once without the channel mentions`; `conversations at zero are listed as read`. `OdooDirectTest` (MockWebServer): `check reads session info then mail data with the session cookie`; `check never calls a route that marks read` (the recorded paths are exactly the two); `code 100 is SESSION_EXPIRED`, `HTTP 401 is SESSION_EXPIRED`; `http refused before any request`; `unregister sends the endpoint to unregister_devices`.
- [ ] **Step 2–4:** FAIL → implement → PASS; `./gradlew --stop`.
- [ ] **Step 5: Commit** (M): `[ADD] chat push: native stores, session copy, Odoo unread summary`.

### Task 7: Push engine — one connection per ntfy, dedup, summaries, health (M, Java)

**Files:** M create `chatpush/HealthSnapshot.java`, `PushEngine.java`; test `PushEngineTest.java`.

**Interfaces:**
- Consumes Tasks 3–6.
- `interface Notifier { void show(NotificationModel.Shown n); void cancel(String tag); void cancelAll(String configId); java.util.Set<String> shownTags(); void status(HealthSnapshot h); }` (Task 8 implements it on Android; the test uses a recording fake).
- `interface Clock { long now(); }`, `interface Scheduler { void schedule(Runnable r, long delayMs); void cancelAll(); }` (the test runs them by hand).
- `final class PushEngine { PushEngine(PushStore store, PushSettingsStore settings, NativeSessions sessions, NtfyClient ntfy, OdooDirect odoo, Notifier notifier, Clock clock, Scheduler scheduler); void startRealtime(); void stopRealtime(); void runDue(PushLevelPolicy.Effective e); void onNetworkAvailable(); void onSettingsChanged(); HealthSnapshot health(); static final long[] RECONNECT_MS = {5_000, 15_000, 30_000, 60_000, 120_000, 300_000}; }`
  - `startRealtime`: one `NtfyClient.stream` per ntfy of `store.ntfys()` that has subscriptions, all its topics on it, since = its cursor, else the time of its first subscription (seconds); `stopRealtime` closes them;
  - a message event: `SeenIds.add` false → dropped; topic → `store.byTopic`, none → dropped; `WebPushDecrypt` failure → dropped, counted in health, the next message still processed; `settings.foreground()` → nothing shown; else `PushPayload` → `NotificationModel.chat` or `.inbox` → `notifier.show`; then the cursor and contact time saved; `message_delete`, `message_clear`, `poll_request` change nothing;
  - a closed stream reconnects after `RECONNECT_MS[i]` plus up to 20 % jitter (`i` grows to the last value, reset by an `open`), at once on `onNetworkAvailable`; UNAUTHORIZED and FORBIDDEN and HTTP_REFUSED and CLEARTEXT_BLOCKED keep the last delay (300 s) and stay in health until `onSettingsChanged`;
  - on (re)open or poll of an ntfy whose `lastContactAt` is older than its `cacheSeconds`: one Odoo-direct check for each of its accounts (R9);
  - `runDue(e)`: OFF → nothing; POLL_15 → `poll` every ntfy; POLL_60 → `poll` an ntfy when its last poll is 60 min old or more; at `e.odooDirect`: Odoo-direct check of each mirrored account without a subscription; then every pending unregister (`OdooDirect.unregister`, success or 404-like answer → `donePending` and `sessions.forget` when the account is gone); poll results go through the same message path;
  - Odoo-direct check: `UnreadSummary` → `NotificationModel.summary` shown when the total rises above the last shown, updated silently when it drops, cancelled at 0 (R9); the chat notifications of `readChannelIds` cancelled; SESSION_EXPIRED → `sessions.markExpired`, one `status_session_expired` status notification, no further check until a new session is mirrored;
  - two failed runs in a row at POLL_15 / POLL_60 for an ntfy or an account → one `status_not_listening` status notification (tag `status:<configId>`), cancelled by the next success (R10);
  - `onSettingsChanged`: accounts no longer mirrored → `notifier.cancelAll(configId)`; ntfy set changed or allowHttp changed → streams reopened.
- `final class HealthSnapshot { JSONObject toJson(); }` = `{at, level, effectiveLevel, mode: "realtime"|"poll_15"|"poll_60"|"off", realtimeBuild, serviceAlive, ntfys: [{url, state: "connected"|"connecting"|"polling"|"error"|"off", reason: <NtfyException.Kind lower case>|null, lastContactAt, configIds}], accounts: [{configId, via: "ntfy"|"odoo", state: "ok"|"waiting"|"error"|"session_expired"|"no_session", reason, lastCheckAt}], undecryptable}`; `serviceAlive` = the effective policy is permanent and `settings.lastBeat()` is under 10 min old; the plugin adds `notificationsAllowed` and `batteryExempt`.

- [ ] **Step 1: Failing JUnit** (MockWebServer as ntfy and as Odoo, payloads from `WebPushTestEncrypt`): `two accounts on one ntfy share one stream`; `two ntfy servers get one stream each`; `a message shows on its account's conversation`; `a replay after reconnect shows each message once`; `an undecryptable message is dropped and the next one shows`; `nothing shows while the app is in the foreground`; `a message_clear event changes nothing`; `a dropped stream reconnects with the saved cursor after the backoff`; `network back reconnects at once`; `401 keeps the long delay and shows unauthorized in health`; `turning allowHttp on reconnects`; `silence above the cache runs the Odoo-direct summary once`; `an account without ntfy is checked at each due run`; `the summary alerts on a rise, updates silently on a drop, goes at zero`; `read conversations lose their notification at the check`; `an expired session stops the checks and says so once`; `two failed polls post one status notification, a success removes it`; `level 4 polls once an hour`; `a pending unregister runs with the session copy then forgets it`; `an account removed from the mirror loses its notifications`.
- [ ] **Step 2–4:** FAIL → implement → PASS; `./gradlew --stop`.
- [ ] **Step 5: Commit** (M): `[ADD] chat push: engine, one connection per ntfy, dedup, health`.

### Task 8: Android notifications, tap to open, plugin bridge, QR decoding (M)

**Files:** M create `chatpush/ChatNotifier.java`, `ChatPushOpen.java`, `ChatPushRuntime.java`, `ca/erplibre/home/ChatPushPlugin.java`, `ca/erplibre/home/BatteryExemption.java`, `src/plugins/chatPushPlugin.ts`, `src/__mocks__/chatPushNative.ts`, `src/__tests__/chatPushPlugin.test.ts`; modify `SmsGatewayPlugin.java` (`:236-310`: its battery and exact-alarm helpers move to `BatteryExemption`, behaviour unchanged), `MainActivity.java` (`registerPlugin(ChatPushPlugin.class)` beside NoteSyncPlugin, `:55`), `android/app/build.gradle` (`implementation "com.google.mlkit:barcode-scanning:17.3.0"`), `featureCatalog.ts`.

**Interfaces:**
- Consumes Task 7 (`Notifier`, `PushEngine`, `HealthSnapshot`), Task 5 (`Shown`, `PushStrings`).
- `ChatNotifier implements Notifier`: channels created per mirrored account — `chat.<h>` IMPORTANCE_HIGH named `channel_chat`, `inbox.<h>` IMPORTANCE_DEFAULT named `channel_inbox`, inside a `NotificationChannelGroup` `server.<h>` named by the account label; `status` LOW; deleted with the account. `show`: `MessagingStyle` for `messaging` — the style of the active notification of the same tag extracted (`MessagingStyle.extractMessagingStyleFromNotification`) and the new message appended, so a stack survives a process death; `setVisibility(PRIVATE)` with a `setPublicVersion` holding `publicTitle` for `privateVisibility`, PUBLIC otherwise; `setGroup(groupId)`; content intent `ChatPushOpen.intent(ctx, openUrl)`; `setAutoCancel(true)`. `shownTags` from `NotificationManager.getActiveNotifications()`.
- `final class ChatPushOpen { static final String EXTRA_URL = "erplibre.push_open", EXTRA_KEY = "erplibre.push_key"; static PendingIntent intent(Context c, String url); static String takeUrl(Context c, Intent i) /* the url when the key matches and the path is allowed (R8), the extras removed */; static boolean allowedPath(String url); }`
- `final class ChatPushRuntime { static ChatPushRuntime get(Context c); PushEngine engine(); PushStore store(); PushSettingsStore settings(); NativeSessions sessions(); }` (one engine per process; `KeystoreKeys.provider("erplibre_chat_push")`, `PrefsKeyValue` files `erplibre_chat_push`, `erplibre_chat_push_settings`, `erplibre_chat_push_sessions`).
- `ChatPushPlugin` (`@CapacitorPlugin(name = "ChatPushPlugin")`): `handleOnResume`/`handleOnPause` write the foreground flag synchronously (`NoteSyncPlugin.java:23-48`) and `handleOnNewIntent` emits `pushOpen {url}` for an accepted tap. Methods, mirrored in the TS bridge:
  - `capabilities(): Promise<{ realtime: boolean }>`;
  - `publishSettings(o: { level: number; allowHttp: boolean; strings: Record<string, string>; accounts: { configId: string; label: string; lockScreen: "hidden_locked" | "never" | "always"; channels: { id: number; name: string; type: string }[] }[] }): Promise<void>` (then `engine.onSettingsChanged()` and the service/job applied, Task 9);
  - `setNtfy(o: { url: string; token: string; prefix: string; cacheSeconds: number }): Promise<{ ok: boolean; reason: string | null }>` (`checkRead` on `<prefix>` + `check` first; stored only when ok);
  - `removeNtfy(o: { url: string }): Promise<void>`;
  - `subscribe(o: { configId: string; ntfyUrl: string; renew: boolean }): Promise<{ topic: string; p256dh: string; auth: string }>` (base64url);
  - `unsubscribe(o: { configId: string; pendingEndpoint: string | null }): Promise<void>` (a pending endpoint keeps the session copy for `PushEngine`'s pending unregister);
  - `mirrorSession(o: { configId: string; odooUrl: string; database: string; sessionId: string }): Promise<void>`, `forgetSession(o: { configId: string }): Promise<void>`;
  - `status(): Promise<PushHealth>` (`HealthSnapshot.toJson()` plus `notificationsAllowed`, `batteryExempt`);
  - `checkNow(): Promise<void>` (one `runDue` off the main thread);
  - `clear(o: { configId: string; channelId?: number; inbox?: boolean; summary?: boolean }): Promise<void>`; `shown(): Promise<{ tag: string }[]>`;
  - `takeLaunchUrl(): Promise<{ url: string | null }>`;
  - `decodeQr(o: { path: string }): Promise<{ text: string | null }>` (ML Kit `BarcodeScanning` on `InputImage.fromFilePath`, QR format only);
  - `batteryExempt(): Promise<{ exempt: boolean }>`, `requestBatteryExemption(): Promise<void>` (the list screen, as the SMS gateway opens it, `SmsGatewayPlugin.java:273-290`).
- TS: `export interface ChatPushNative { … the methods above … }`, `export type PushHealth = {…}` (the JSON of Task 7), `export const chatPushNative: ChatPushNative | null` (null off a native platform); `src/__mocks__/chatPushNative.ts` an in-memory fake recording calls (unit tests of Tasks 10–11).

- [ ] **Step 1: Failing tests:** JUnit `ChatPushOpenTest`: `allowed paths pass, others are refused` (`/chat`, `/chat/inbox?s=…&thread=project.task,7`, `/chat/<enc>/42` vs `//evil`, `/note/1`, `javascript:`). Vitest `chatPushPlugin.test.ts`: the bridge forwards every method's arguments and maps a rejected call to an Error naming the method; `chatPushNative` is null off native.
- [ ] **Step 2–3:** FAIL → implement → PASS (`./gradlew :app:testDebugUnitTest`, `npm test`); `BUNDLE_SKIP_WHISPER=1 ./gradlew assembleDebug` builds; `./gradlew --stop`.
- [ ] **Step 4: Commit** (M): `[ADD] chat push: notifications, tap to open, plugin, QR decoding`.

### Task 9: Permanent service apart, 15-minute job, boot, one permanent notification (M)

**Files:** M create `chatpush/RealtimeHost.java`, `PermanentNotice.java`, `ChatPushJob.java`, `ChatPushBootReceiver.java`, `android/app/src/realtime/java/ca/erplibre/home/chatpush/realtime/ChatPushService.java`, `android/app/src/realtime/AndroidManifest.xml`, test `PermanentNoticeTest.java`; modify `android/app/build.gradle` (R6), `AndroidManifest.xml` (job, receiver), `SmsGatewayService.java` (`:91-92`, `startForegroundCompat` and its stop path use `PermanentNotice`), `ChatPushPlugin.java` (`publishSettings` applies the policy), `featureCatalog.ts`.

**Interfaces:**
- `final class RealtimeHost { static boolean available() /* BuildConfig.CHAT_REALTIME and the class loads */; static void start(Context c); static void stop(Context c); }` — `Class.forName("ca.erplibre.home.chatpush.realtime.ChatPushService")`.
- `ChatPushService` (realtime source set): `specialUse` foreground service (`PROPERTY_SPECIAL_USE_FGS_SUBTYPE` text as the SMS gateway's, `AndroidManifest.xml:69-86`, saying a messenger's permanent connection to the user's own ntfy), `START_STICKY`, `PermanentNotice.hold(this, Holder.CHAT, line)`; network callback → `engine.onNetworkAvailable()` and the policy re-read (level 2 Wi-Fi); `ACTION_POWER_CONNECTED/DISCONNECTED` receiver → policy re-read; mode REALTIME → `engine.startRealtime()`, else `stopRealtime()`; a 10 s partial wakelock around each message's processing, none otherwise (`SmsGatewayService.java:62-74` reasons); `settings.beat(now)` at most every 5 min (health `serviceAlive`).
- `final class PermanentNotice { enum Holder { SMS, CHAT } static final int ID = 9101; static final String CHANNEL = "erplibre_permanent"; static void hold(Service s, Holder h, String line); static void release(Service s, Holder h); static final class State { void hold(Holder h, String line); Holder release(Holder h) /* the holder that must re-assert, or null */; String title(); List<String> lines(); boolean empty(); } }` — R5; the SMS gateway keeps its « Arrêter » action while it holds.
- `ChatPushJob` (JobScheduler, `JOB_ID = 4823`, beside 4821 and 4822): periodic 15 min, persisted, `NETWORK_TYPE_ANY`; each run: `PushLevelPolicy.resolve(settings.level(), power state, BuildConfig.CHAT_REALTIME, NO_CLIMB)`; permanent → `RealtimeHost.start` when the service is not alive; then `engine.runDue(effective)`; level 5 → cancels itself. `static void apply(Context c)` (called by `publishSettings`, the boot receiver and the job): schedules or cancels the job, starts or stops the service.
- `ChatPushBootReceiver`: `BOOT_COMPLETED`, `QUICKBOOT_POWERON`, `MY_PACKAGE_REPLACED` → `ChatPushJob.apply` (as `SmsBootReceiver.java:30-50`).
- Gradle (R6): without `-PnoChatRealtime`, `android.sourceSets.debug` and `.release` get `java.srcDirs += 'src/realtime/java'` and `manifest.srcFile 'src/realtime/AndroidManifest.xml'`; `buildConfigField "boolean", "CHAT_REALTIME", "<true|false>"`.

- [ ] **Step 1: Failing JUnit** `PermanentNoticeTest`: `one holder shows its line`; `two holders show one notification with both lines`; `releasing one while the other holds names the other to re-assert`; `releasing the last empties it`.
- [ ] **Step 2–3:** FAIL → implement → PASS; `BUNDLE_SKIP_WHISPER=1 ./gradlew assembleDebug` and `… assembleDebug -PnoChatRealtime` both build; `aapt2 dump xmltree` (or `apkanalyzer manifest print`) of the second APK shows no `ChatPushService`; `./gradlew --stop`.
- [ ] **Step 4: Commit** (M): `[ADD] chat push: permanent service apart, shared with SMS gateway`.

### Task 10: ntfy per account, registration with Odoo, mirrors (M, JS)

**Files:** M create `src/services/chat/chatPushLink.ts`, `src/services/chat/chatPush.ts`, `src/services/migrations/addChatPush.ts`, tests `chatPushLink.test.ts`, `chatPush.test.ts`; modify `migrations/index.ts` (`{version: 2026102801, description: "Clavardage : notifications par ntfy, par compte", run: addChatPush}`), `databaseService.ts` (`createChatTables`, `addChatPush()`, `renameChatRows`), `chatRepository.ts` (`pushRow`, `setPushRow`, `dropSource`), `chatService.ts` (`push` member; `loadNow` end), `chatLifecycle.ts` (`follow`), `chatSettings.ts`, `odoo/httpPolicy.ts`, `odoo/odooRpcClient.ts` (`:259-261`), `appService.ts` (`delete` `:134-147`, `clear`), `syncService.ts` (construction), `src/__mocks__/@capacitor-community/sqlite.ts` if a query shape is new, `migrations.test.ts`, `featureCatalog.ts`.

**Interfaces:**
- `chatPushLink.ts`: `interface NtfyLink { url: string; token: string; prefix: string; cacheSeconds: number; odooUrl: string | null }`; `parseNtfyLink(text: string): NtfyLink | null` — trimmed, scheme `erplibre-ntfy:`, `v=1`, `url`/`odoo` http(s), `token` `^tk_[A-Za-z0-9]+$`, `prefix` `^up[a-z0-9]{8}$`, `cache` integer 60…604800; anything else null.
- Table `chat_push`: `config_id TEXT PRIMARY KEY`, `ntfy_url TEXT` (null: no ntfy), `odoo_ntfy_url TEXT`, `prefix TEXT`, `topic TEXT`, `endpoint TEXT`, `p256dh TEXT`, `auth TEXT`, `vapid_key TEXT`, `registered_at TEXT`, `stale_endpoints TEXT NOT NULL DEFAULT '[]'`, `lock_screen TEXT NOT NULL DEFAULT 'hidden_locked'`. `models/chat.ts`: `ChatPushRow` with the same fields camel-cased (`staleEndpoints: string[]`, `lockScreen: LockScreen`), `type LockScreen = "hidden_locked" | "never" | "always"`.
- `ChatSettings` gains `notifyLevel: 1 | 2 | 3 | 4 | 5`, default **3** (R11), any other stored value read as the default.
- `httpPolicy.ts`: `onHttpPolicyChange(listener: (allowed: boolean) => void): () => void`, called by `setHttpAllowed`.
- `OdooRpcClient.onSessionStored: ((creds: SyncCredentials, stored: StoredSession) => void) | null`, called after the SecureStorage write.
- `AppService.beforeDelete: ((configId: string) => Promise<void>) | null`, awaited before `deleteApplication` in `delete` and `clear` (a hook that fails is logged, the delete goes on — as `beforeRename`).
- `class ChatPush { constructor(repo: ChatRepository, rpc: OdooRpcClient, native: ChatPushNative | null, sources: () => Promise<ChatSource[]>, now: () => Date); }` (`ChatService.push`, null native → every method a no-op):
  - `applyLink(configIds: string[], link: NtfyLink): Promise<{ ok: boolean; reason: string | null; registered: string[] }>` — `native.setNtfy` (not ok → nothing written); per account `native.subscribe({configId, ntfyUrl: link.url, renew})` (renew when the account's ntfy or prefix differs); `endpoint = (link.odooUrl ?? link.url) + "/" + topic`; a previous different endpoint appended to `staleEndpoints`; row written; `ensureRegistered` each; `publish()`;
  - `setOdooUrl(configId, url: string | null)`, `removeNtfy(configId)` (endpoint to `staleEndpoints`, `native.unsubscribe`, `native.removeNtfy` when no account is left on it), `setLockScreen(configId, mode)`, `setLevel(level)` (level 5 → every session copy forgotten);
  - `ensureRegistered(src: ChatSource): Promise<"registered" | "offline" | "refused" | "none">` — once per foreground session per account (`newSession()` clears the set): each stale endpoint `callKw("mail.push.device", "unregister_devices", [], {endpoint})` then removed from the list; `callKw("mail.push.device", "get_web_push_vapid_public_key", [], {})`; `callKw("mail.push.device", "register_devices", [], {endpoint, keys: {p256dh, auth}, vapid_public_key, expirationTime: null})`; `vapid_key`, `registered_at` written (R7);
  - `forget(configId)` (the `beforeDelete` hook): online, unregister the endpoint and the stale ones with a 5 s bound; what fails goes to `native.unsubscribe({configId, pendingEndpoint})`; else `native.unsubscribe({configId, pendingEndpoint: null})` and `native.forgetSession`;
  - `mirrorSession(creds, stored)` — Odoo 18 chat account and level ≤ 4 only; at start, `mirrorAll()` copies the stored sessions of every chat account without re-authenticating (`getSession`);
  - `publish(): Promise<void>` — `native.publishSettings` with `chatSettings().notifyLevel`, `isHttpAllowed()`, the strings of Task 5's keys from `t("chat.push_<key>")`, and per account the label (`sourceLabels`), `lockScreen`, and its shown conversations `{id, name: displayNameOf, type}`; called after `applyLink`, a settings change, an http policy change, each account load, `forget`;
  - `reconcileShown(configId): Promise<void>` — after a load: `native.clear({configId, channelId})` for every conversation whose counted unread (`unreadOf`, not muted) is 0, and `native.clear({configId, summary: true})`.
- `ChatService.loadNow` ends with `push.ensureRegistered(src)` and `push.reconcileShown(configId)` (failures logged, never failing the load); `ChatLifecycle.follow(true)` calls `push.newSession()`.

- [ ] **Step 1: Failing tests** (`chatPush.test.ts`: the fake native of Task 8, the fake Odoo of `chatService.test.ts` through `state.onKw`): `parseNtfyLink` accepts the R4 example and refuses a bad scheme, a token without tk_, a prefix not up+8, a missing url, an ftp url, a cache of 10; `applyLink subscribes each account and registers its endpoint with the vapid key`; `the endpoint uses the Odoo-side url when the link has one`; `a refused token writes nothing`; `a wiped device is registered again at the next foreground load` (register called again after `newSession`, same endpoint and keys); `registration happens once per foreground session`; `a new prefix moves every account to a new topic and unregisters the old endpoint`; `removeNtfy unregisters and unsubscribes`; `a removal online unregisters before the account goes`; `a removal offline leaves the endpoint to native code`; `level 5 forgets every session copy`; `a session is mirrored only for chat accounts at levels 1 to 4`; `turning Autoriser http on publishes the settings`; `publish sends labels, lock screen and conversation names`; `a load clears notifications of conversations read elsewhere`; migration 2026102705 → 2026102801 adds the table once; rename and drop source cover `chat_push`; `beforeDelete runs before the application row goes`.
- [ ] **Step 2–3:** FAIL → implement → PASS; `npm test`.
- [ ] **Step 4: Commit** (M): `[ADD] chat: ntfy per account, registration with Odoo, mirrors`.

### Task 11: Notification settings, health banner, open from a tap (M, JS)

**Files:** M create `src/components/options/chat_notifications/options_chat_notifications_component.ts|.scss`, `src/services/chat/chatPushOpen.ts`, tests `optionsChatNotifications.test.ts`, `chatPushOpen.test.ts`; modify `options_component.ts` (mounted after `OptionsChatComponent`), `chat_list_component.ts` (banner), `chat_mailbox_component.ts` (`?thread=`, beside the `?s=` read `:265`), `js/app.ts` (launch url and `pushOpen` listener after the router is ready), `src/css/components.scss`, i18n, `featureCatalog.ts`, tests `chatListComponent.test.ts`, `chatMailboxComponent.test.ts`.

**Interfaces:**
- Consumes Task 10 (`ChatPush`, `parseNtfyLink`) and Task 8 (`ChatPushNative`, `PushHealth`).
- `chatPushOpen.ts`: `allowedOpenUrl(url: string): boolean` (the same three paths as `ChatPushOpen.allowedPath`, R8); `listeningOf(h: PushHealth, rows: ChatPushRow[]): { off: boolean; alarms: { configId: string | null; reason: string }[]; warnings: string[] }` — level 5 → `off`; `!notificationsAllowed` → alarm; levels 1–2 and `!serviceAlive` → alarm; an account `error`/`session_expired`/`no_session` or its ntfy `error` → alarm with the reason; levels 1–2 and `!batteryExempt` → warning.
- `OptionsChatNotificationsComponent` (« Notifications du clavardage », `chat.push_title`):
  - level: five choices `chat.push_level_1` … `_5` with one-line descriptions from the spec's five levels; levels 1–2 hidden when `capabilities().realtime` is false; choosing 1 or 2 → `batteryExempt()`, not exempt → `Dialog.confirm(chat.push_exemption_ask)` → `requestBatteryExemption()`; still not exempt on return → `chat.push_exemption_refused` (what it costs: Android may cut the connection, notifications arrive late) with « Passer au niveau 3 » (`chat.push_use_level_3`);
  - notifications permission: `LocalNotifications.checkPermissions/requestPermissions` (the existing pattern, `pendingSyncNotice.ts:88-101`) when a level 1–4 is chosen or a link is applied; refused → the alarm line;
  - per Odoo 18 account a card: its ntfy (URL or « aucun »), the Odoo-side URL (editable, blank = the same), « Scanner le code QR » (`Camera.getPhoto` → `decodeQr` → `parseNtfyLink`) and « Coller le lien », with « Appliquer aussi aux comptes sans ntfy » (`chat.push_apply_others`, checked by default) → `applyLink`; « Retirer ntfy »; lock screen three choices « Masqué quand verrouillé » (default), « Jamais affiché », « Toujours affiché »; registration state (`registered_at` or the last failure);
  - status panel from `status()` every 5 s while shown: per ntfy and per account state and reason in words; « Vérifier maintenant » → `checkNow()`.
- Chat list: with `alarms` non-empty and the level not 5, a banner `chat.push_not_listening` (« Le téléphone n'écoute pas : {raison} ») above the rows, a tap opens the options section; level 5 → a quiet line `chat.push_off`.
- Launch: `app.ts` reads `takeLaunchUrl()` once the routes are mounted and subscribes to `pushOpen`; an allowed url → `ROUTER_NAVIGATION` (`app.ts:47-48`), else ignored. Thread open → `native.clear({configId, channelId})`.
- Mailbox: `?thread=<model>,<resId>` with `?s=` → after the inbox page is shown, the newest item of that thread opens through `ChatInbox.openItem` (`chatInbox.ts:209-230`); none → the inbox stays, filtered on `s`.

- [ ] **Step 1: Failing tests:** `allowedOpenUrl` cases (as Task 8's JUnit); `listeningOf` table (off, denied permission, dead service at 1, account session expired, ntfy unauthorized, not exempt is a warning only); options: `choosing level 1 asks for the exemption and offers level 3 when refused`; `levels 1 and 2 are hidden without the realtime build`; `a pasted link applies to the account and to the others without ntfy`; `a bad link says why and changes nothing`; `a scanned photo goes through decodeQr`; `the lock-screen choice is saved and published`; `the status panel names the http reason` (`http_refused` and `cleartext_blocked` worded differently); list: `the banner names the http reason`, `no banner when listening`, `level 5 shows the quiet line`; mailbox: `a thread parameter opens the newest item of that record`; app: `a launch url opens the conversation`, `a disallowed launch url is ignored`.
- [ ] **Step 2–3:** FAIL → implement → PASS; `npm run build`.
- [ ] **Step 4: Commit** (M): `[ADD] chat: notification settings, health banner, open from a tap`.

### Task 12: Kit, device hook, harness ntfy, long tests, device scenario

**Files:** M create `src/testing/webPushNode.ts`, `src/testing/pushNodeNative.ts`, `src/__tests__/webPushNode.test.ts`; modify `src/testing/syncTestKit.ts` (`HARNESS_API = 6`; exports `parseNtfyLink`, `decryptWebPush`, `pollNtfy`, `pushNodeNative`; `SyncEnv` gains `push: ChatPush` over the node native), `src/testing/deviceTestHook.ts` (`DEVICE_HOOK_API = 7`). E create `long_test/mobile_sync_ntfy.py`, `long_test/mobile_sync/chatPush.test.ts`; modify `long_test/mobile_sync.py` (start, keep, stop the ntfy; `ntfy` in `targets.json`; plan line), `long_test/mobile_sync_odoo.py` (`HARNESS_API = 6`), `long_test/mobile_sync/harness.ts` (`Target.ntfy?`), `long_test/mobile_sync/chatPeer.ts`, `long_test/mobile_sync_device.py` (`DEVICE_HOOK_API = 7`; ntfy port reversed; scenario in `SCENARIOS` `:2141`; `rendre` restores the deviceidle allowlist), `test/test_mobile_sync_harness.py` (`:368` 6, `:749` 7, the ntfy cases).

**Interfaces:**
- `webPushNode.ts`: `decryptWebPush(body: Uint8Array, privateKey: KeyObject, uaPublic: Uint8Array, auth: Uint8Array): Uint8Array` (node:crypto, the same RFC 8291 steps as Task 3; test-only); `webPushNode.test.ts` decrypts RFC 8291 Appendix A and Task 0's vector, the same values as `WebPushDecryptTest`.
- `pushNodeNative(): ChatPushNative & { keysOf(configId): { privateKey: KeyObject; publicKey: Uint8Array; auth: Uint8Array; topic: string }; sessions: Map<string, …>; calls: … }` (keys from `generateKeyPairSync("ec", {namedCurve: "prime256v1"})`, topic per R4); `pollNtfy(ntfy: {url, token}, topics: string[], since: string): Promise<{id, topic, body: Uint8Array}[]>`.
- `mobile_sync_ntfy.py`: `ntfy_disponible() -> bool` (`shutil.which("ntfy")`); `demarrer_ntfy(repertoire: Path) -> Ntfy` (free port from `odoo.port_libre()`, `server.yml` with `listen-http: "127.0.0.1:<port>"`, `base-url`, `cache-file`, `cache-duration: "12h"`, `auth-file`, `auth-default-access: "deny-all"`, `visitor-request-limit-exempt-hosts: "127.0.0.1"`, all under `repertoire/ntfy/`; `ntfy serve --config <yml>`; once healthy, `ntfy_mobile.access_script(yml, "erm_course", prefix)` run through `LocalHost(sudo=())`; token parsed) ; `Ntfy(url, port, config, token, prefix, link, processus)`; `arreter_ntfy(ntfy)`. `--garder` keeps it with the servers (`noter_gardes`), `--detruire` stops kept ones. Absent binary → no `ntfy` key, the plan line « ntfy : absent, tests de notification sautés », and `chatPush.test.ts` skips under a name saying so.
- `Target.ntfy?: { url: string; token: string; prefix: string; link: string }`.
- Hook: `chatPushApply(configId, link): Promise<{ok, reason, registered}>`, `chatPushLevel(level)`, `chatPushLockScreen(configId, mode)`, `chatPushRemove(configId)`, `chatPushStatus(): Promise<PushHealth>`, `chatPushCheckNow()`, `chatPushRow(configId): Promise<ChatPushRow | null>`.
- `ChatPeer`: `pushDevices(endpoint): Promise<number>` (admin `search_count` on `mail.push.device`), `wipeVapid()` (admin unlinks the two `mail.web_push_vapid_*` parameters), `seenOf(login, channelId)`, `needactionCount(login)`.

Long tests (`chatPush.test.ts`, `eachVersionFrom(18, …)`, app as admin, link from `target.ntfy` with `odoo` = the same 127.0.0.1 URL, a fresh account label per test):
- `a chat message reaches ntfy encrypted and decrypts to its conversation` (chat_user posts in its chat with admin → one base64 message on the topic → decrypted JSON: title chat_user's name, body the text, `data.model` `discuss.channel`, `res_id` the chat);
- `a channel mention, a group message and a record comment each have their payload` (Task 0's shapes; the record one: the record's model, no `action`);
- `a muted conversation is not pushed` (muted chat, then a message in another conversation as the marker: only the marker arrives);
- `the phone token reads only its prefix` (another prefix's topic 403, anonymous read 403, anonymous write outside `up*` 403);
- `a VAPID wipe is healed by the next load` (`wipeVapid`, `newSession` + load → `pushDevices(endpoint)` 1 again, a push arrives);
- `removing the account unregisters its device` (`pushDevices` 0, a later message reaches no topic);
- `a new link for the same ntfy moves the account to a new topic` (old endpoint 0 devices, new 1);
- `the harness ntfy is never the user's` (`target.ntfy.url` port ≠ 8080, its config under the run directory).

Device scenario « notifications du clavardage, app fermée » (18 only; preconditions: `pm grant <pkg> android.permission.POST_NOTIFICATIONS`, `dumpsys deviceidle whitelist +<pkg>`, both undone in `rendre`):
1. the hook applies the link (phone URL `http://127.0.0.1:<port>` through `adb reverse`), level 1, « Autoriser http » on; `chatPushStatus` shows the ntfy `connected`; `dumpsys notification` holds exactly one ongoing notification of the package;
2. HOME; chat_user posts → within 15 s `dumpsys notification --noredact` holds the record of tag `chat:<configId>:<channelId>`, channel `chat.<h>`, `vis=PRIVATE`, a public version titled « Nouveau message — <label> », the private text holding the posted words;
3. the app process killed (`run-as <pkg> kill -9 <pid>`); the service back by START_STICKY, or forced with `cmd jobscheduler run -f <pkg> 4823`, within 60 s; chat_user posts again → the same conversation's notification holds both messages (MessagingStyle);
4. the shade expanded (`cmd statusbar expand-notifications`), the notification tapped at its bounds from `uiautomator dump` → CDP reads `location.pathname` `/chat/<configId>/<channelId>`; the notification is gone;
5. app in the foreground on the list: chat_user posts → no record for that conversation;
6. lock screen « Jamais affiché » through the hook, HOME, a post → title and text « Nouveau message »;
7. ntfy removed for the account through the hook, HOME, chat_user posts twice, the job forced → a record of tag `summary:<configId>` « 2 nouveaux messages — <label> »; on the server admin's `seen_message_id` on that chat and needaction count are unchanged;
8. screenshots at 2, 4 and 7 kept by the runner; the screen is never turned off.

- [ ] **Steps:** failing kit tests (`webPushNode.test.ts`), then write; harness unit tests: `test_ntfy_config_is_local_and_temporary` (no 8080, no `/etc/ntfy`, `127.0.0.1` listen), `test_every_ntfy_call_has_config`, `test_ntfy_absent_skips_with_a_plan_line`, API assertions 6 and 7 → green; `./long_test/mobile_sync.py --versions 18 --filtre push` green ×3; `--filtre chat` green; full run green; `--appareil` green (the personal app's `lastUpdateTime` unchanged, `stay_on_while_plugged_in` and the allowlist restored); `./gradlew --stop`; `--detruire`; record durations (post → notification seconds at step 2) in the ledger. Commits M `[ADD] testing: chat push in the kit and the device hook`, E `[ADD] long_test: chat push through a real ntfy on Odoo 18`.

### Task 13: Contracts, docs, changelogs

- [ ] `contracts/odoo-api.json`: `chat.push.register` (`get_web_push_vapid_public_key`, `register_devices` kwargs, the no-update rule for a known endpoint, the VAPID wipe, `unregister_devices` without partner check), `chat.push.payload` (the four shapes of Task 0, no message id, ntfy's 200 logged by Odoo with the topic until module 1.5), `chat.push.summary` (the two read-only routes, the counting, never marking read), `chat.push.ntfy` (`up*` write-only, `<prefix>*` read-only, base64 body, `since` dedup, cache), migration 2026102801; `contracts/compatibility.json`: the push works with module 1.4 or none, what 1.5 adds later (one sentence).
- [ ] `mobile/erplibre_home_mobile/README.base.md` gains « Notifications du clavardage »: prepare ntfy (`TODO › Deploy › Préparer ntfy pour ERPLibre mobile`, local or ssh), scan or paste, the two URLs and when they differ, « Autoriser http » and the `-PlanCleartext` APK for a LAN ntfy over http, the five levels and the battery exemption, the lock-screen choices, revoking a phone, the build property `-PnoChatRealtime`; `long_test/README.base.md` gains the push section (harness ntfy, `--filtre push`, the device scenario and what it restores); ERPLibre and mobile `CHANGELOG.base.md`; mmg; `check_comment_hygiene.py --staged` clean.
- [ ] Commits: E `[UPD] contracts: Odoo 18 web push registration, payload, summary`; E `[UPD] doc: ntfy for ERPLibre mobile, push long tests, changelog`; M `[UPD] doc: chat notifications, levels, lock screen, changelog`.
