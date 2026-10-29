# ERPLibre mobile chat notifications, lot 2 (actions and module 1.5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A chat notification can be answered, marked read, muted for an
hour or given a 👍 with the app closed (process dead, WebView dead):
native code sends each action to Odoo with the mirrored session, durably
first, never twice, and hands it to the app when the session is dead or
Odoo refuses it; the app then sends it through its own outbox with the same
client uuid and shows what native code did. Module `erplibre_mobile_chat`
18.0.1.5.0 recognises the app's devices: their pushes carry the message id
and the channel type, are sent after commit and accepted on ntfy's 200, a
« read » push reaches them (never a browser) when the user reads a
conversation or an inbox item elsewhere, and a device may ask not to be
pushed while a browser of the user is online.

**Architecture:** In the module (A), a device route marks a
`mail.push.device` as the app's; `_notify_thread_by_web_push` sends the
marked devices of the recipients through the module's own sender in a
postcommit callback (Odoo's own code keeps every other device, untouched);
`_set_last_seen_message`, `set_message_done` and `mark_all_as_read` queue a
« read » push to the reader's marked devices, coalesced per transaction. In
M, the Capacitor-free package `ca.erplibre.home.chatpush` gains an Odoo
action client (`OdooActions`), a sealed action store and its runner (one
state machine per action, JVM-tested), the control pushes in the engine
(read, inbox done), and thin Android glue: notification actions, a
non-exported `BroadcastReceiver` with `RemoteInput`, a retry job. The JS
learns level 1.5, marks its device, mirrors the module level, and drains
the native action store into the outbox (handoffs) and into the cache
(catch-up).

**Tech Stack:** Odoo 18 (Python, `requests`, `mail.tools.web_push`); Java 11
JCA, OkHttp 4.12, AndroidX NotificationCompat (`RemoteInput`,
`MessagingStyle`), JobScheduler; TypeScript, Owl 2, Capacitor 8, Vitest;
ntfy 2.34 and Odoo 18 in the long tests.

**Spec:** `docs/superpowers/specs/2026-10-28-erplibre-mobile-chat-notifications-design.md`
(lot 2 line of « Lots », « Decisions », « Controller's calls », the Odoo 18 /
ntfy 2.34 / app constraints, « Left to the builder »). User decisions:
`tasks/chat/p2-decisions.md`. Lot 1 baseline: its plan
(`2026-10-28-erplibre-mobile-chat-notifications-lot1.md`, rulings R1–R11 stay
in force) and `tasks/chat/p2l1-sdd/ledger.md`. Readings with file:line:
`tasks/chat/p2-recon-odoo.md` (§5 settings routes, §6 module hook),
`p2-recon-mobile.md` (§2 actions with a dead WebView). Conventions for every
implementer: `tasks/chat/p2l2-conventions.md`.

Repos, all on `dev/mobile_chat`, never switch, never push: **M** =
`mobile/erplibre_home_mobile`, **E** = the ERPLibre root, **A** =
`odoo18.0/addons/ERPLibre_erplibre_addons` (module path
`erplibre_mobile_chat/`). Odoo sources cited as `mail/…` or `bus/…` live in
`odoo18.0/odoo/addons/`. Java classes without a package are in
`ca.erplibre.home.chatpush` (`android/app/src/main/java/ca/erplibre/home/chatpush/`,
tests under `android/app/src/test/java/ca/erplibre/home/chatpush/`, test
resources under `android/app/src/test/resources/chatpush/`).

## Rulings recorded here (the builder's, inside the spec)

- **L1 Which actions a notification offers.** Chat notifications only
  (`discuss.channel`); inbox, summary, status and handoff notifications get
  none (a record reply, done-marking and its mute are not in the spec's lot 2
  line; the controller's call, recorded in `tasks/chat/p2-decisions.md`).
  Every lock-screen mode, `never` included (the user's decision: the text
  stays hidden, the actions do not), offers « Répondre », « Marquer lu »,
  « Muet 1 h », and « 👍 » when the newest stacked message has a message id
  (module 1.5, L5). On a `never` server the notification stays « Nouveau
  message » before and after an action: a reply is not appended as text
  (L15), the stack's message ids live in the notification's extras
  (`erplibre.message_ids`, Task 3) rather than in a visible
  `MessagingStyle`. Every action except on `always` servers asks for
  authentication on API 31+ (`setAuthenticationRequired(true)`; no effect on
  the Android 11 test phone, where a PRIVATE public version and a SECRET
  notification show no action on the locked screen anyway).
- **L2 One action, one durable record, one client uuid.** The receiver draws
  a UUID v4 (`clientUuid`) and writes the action to the sealed
  `ActionStore` (`commit()`) BEFORE any network call and before touching the
  notification. A reply's body is the app's `escapeAndCompact` of the text
  (no mentions, no emoji conversion) followed by `chatMarker(clientUuid)`
  (`<!-- erplibre-mobile:<uuid> -->`, `chatBody.ts:18-20`); with the module
  mirrored (`module` ≠ "") `post_data.erplibre_client_uuid = clientUuid`, and
  always `context.temporary_id = clientUuid` — exactly `sendPost`
  (`chatOutbox.ts:2627-2663`). A resend: with the module, sent again as is
  (Odoo's module returns the first message); without it, after the quiet
  window `CREATE_QUIET_WINDOW_MS` (3 min, `outboxMarker.ts:7`) counted from
  the first send that may have reached Odoo (`sentAt`), a marker search
  (`findSent`'s domain, `chatOutbox.ts:2782-2815`) first; two hits → handoff
  « ambiguous ». Mark read, mute and 👍 are target states, repeat-safe
  (`mail/models/discuss/discuss_channel_member.py:492-511`,
  `mail/models/mail_message.py:893-913`); mute is « muted until
  createdAt + 1 h », sent as the minutes left at each attempt, dropped when
  none are left.
- **L3 Alive check before every action.** `/mail/message/post`,
  `/discuss/channel/mark_as_read` and `/mail/message/reaction` are
  `auth="public"` (`mail/controllers/thread.py:125`, `discuss/channel.py:81`,
  `message_reaction.py:12`): with a dead session they run as the public user
  and `mark_as_read` returns `null` having done nothing. Each attempt
  therefore starts with `/web/session/get_session_info` (`auth="user"`,
  `web/controllers/session.py:23`): JSON-RPC code 100 or HTTP 401 →
  `SESSION_EXPIRED` (the session copy marked expired, the action handed off);
  its `partner_id` / `Store.self` is the author the marker search needs
  (`OdooDirect.selfPartnerOf`). Task 0 proves the trap on the real server.
- **L4 Mark read finds its message id without fetching.** With the module:
  the newest stacked message's `message_id`. Without it: `call_kw
  mail.message search` `[["model","=","discuss.channel"],["res_id","=",c],["date","<=",<UTC "YYYY-MM-DD HH:MM:SS" of the newest stacked push's ntfy time>]]`,
  `{order: "id desc", limit: 1}` — an ORM search, which never runs
  `set_message_done` (only the fetch routes do,
  `mail/controllers/discuss/channel.py:64-65`, `thread.py:40-41`); none →
  nothing to mark, done. Then `/discuss/channel/mark_as_read
  {channel_id, last_message_id}` and, as the app's own read does
  (`chatOutbox.ts:3999-4013`), `mail.message.mark_all_as_read` bounded to
  `[model = discuss.channel, res_id = c, id <= last_message_id]`: the
  conversation's own mentions up to that message leave the Inbox, nothing
  else does (the user's decision). It runs whatever `sendRead` says (the
  user's decision: an explicit gesture).
- **L5 👍 needs the message id.** Offered only on a notification whose
  newest message carries `message_id` (module 1.5 and a marked device);
  `/mail/message/reaction {message_id, content: "👍", action: "add"}`.
  Without the module the button is absent (the user's decision: never
  without the message id): a time-bounded search could name another
  message, and a reaction on the wrong message is visible to all.
- **L6 Handoff.** An action goes to the app (state `HANDOFF`, reason
  `session_expired` | `refused` | `ambiguous` | `stale`) on a dead session,
  an Odoo error that is not transient (JSON-RPC error other than code 100,
  HTTP 4xx other than 401/408/429), two marker hits, or 24 h of transient
  failures. Android forbids an activity start from a background broadcast
  (10+ background starts, 12+ notification trampolines), so « opens the
  app » is one notification per server, tag `handoff:<configId>`, channel
  `chat.<h>`, alerting once, text without message content (« Ouvrez l'app
  pour terminer une action — {server} » / « … {n} actions … »), tap →
  `/chat` (R8's allowed path) — the user accepted this form of « opens the
  app ». The app drains at every start and resume and on the plugin's
  `actions` event, signs in again through its outbox as it always does, and
  sends.
- **L7 Drain, two phases.** `actions()` lists the records that are `DONE`
  or `HANDOFF` (never `PENDING`/`RUNNING`: native code still owns those);
  the JS applies each, then `ackActions(ids)` removes them. A handoff reply
  is queued with `queuePost(…, {clientUuid, maybeSentAt: sentAt})`: the op
  keeps the native uuid and, when `sentAt` is set, its first attempt waits
  out the quiet window and searches the marker (`findSent`) before posting.
  A record whose uuid already has a message row (`repo.messageByClientUuid`)
  or an op is skipped: a drain cut before its ack repeats nothing. A
  handoff read is `queue.queueRead` (no `sendRead` gate), a mute
  `queue.queueMute(until)` unless `until` passed, a 👍 ChatService's reaction call (`chatService.ts:1230-1234`, over
  `queueReaction`) after `chat.loadUntil(src, channelId, messageId)`; an account no longer
  configured → acked and dropped (its removal took its notifications).
- **L8 Catch-up after a native success.** A `DONE` reply or 👍 carries
  Odoo's Store answer (≤ 32 KiB, else none): the JS applies it with
  `repo.applyDelta(configId, parseStore(answer, configId, self))`, so the
  reply shows at once, even offline, and no op ever exists for it. A `DONE`
  read patches the cached channel (`seenMessageId` raised to
  `lastMessageId`, unread and needaction counters 0 when it covers
  `lastMessageId`); a `DONE` mute patches `muteUntil`. Then `CHAT_CHANGED`;
  the next load reconciles with Odoo either way.
- **L9 Native retry.** A transient failure (UNREACHABLE, timeout, HTTP
  5xx/408/429) puts the record back to `PENDING` with `nextAt` =
  30 s × 2ⁿ capped at 1 h; `ChatActionJob` (JobScheduler, `JOB_ID = 4824`,
  network required, persisted) runs the due records, and so does every
  `ChatPushJob` run. The receiver's first attempt runs inside `goAsync()` with
  an 8 s call timeout; a process death leaves `RUNNING`, which `recover()`
  turns back to `PENDING` keeping `sentAt` (maybe sent).
- **L10 Module 1.5: app devices.** `mail.push.device` gains
  `erplibre_app` (Boolean), `erplibre_quiet_while_online` (Boolean),
  `erplibre_session_hash` (Char, SHA-256 hex of the session id that marked
  it). Route `POST /erplibre_mobile_chat/push/device` (`type="json"`,
  `auth="user"`) `{endpoint, quiet_while_online=False}` marks the current
  partner's device of that endpoint and answers `{"ok": true}`, or
  `{"ok": false}` when the partner holds no such device. `register_devices`
  moving an endpoint to another partner clears the three fields. The app
  calls the route after each `register_devices` and after each new session
  of the account (L14).
- **L11 Module 1.5: their pushes.** The module's `_notify_thread_by_web_push`
  (on `mail.thread`, under discuss's filter) takes the recipients' marked
  devices (`_extract_partner_ids_for_notifications`, the same partners), drops
  those asking quiet while a browser of their user is online (L13), and calls
  super with context `erplibre_skip_app_devices`, under which
  `mail.push.device._search` adds `[("erplibre_app", "=", False)]`: every other
  device takes Odoo's own code, byte for byte. The marked devices get Odoo's
  payload plus `options.data.erplibre = {"v": 1, "message_id": <id>,
  "channel_type": "chat"|"group"|"channel"|null}`, through
  `_truncate_payload` again. Fewer than `MAX_DIRECT_PUSH` (5) marked devices →
  sent in a `postcommit` callback (data gathered before, no ORM inside;
  404/410 unlinked in a fresh cursor); more → `mail.push` rows, which the
  module's `_push_notification_to_endpoint` sends first through the same
  sender. The sender (`tools/app_push.py`) reuses `mail.tools.web_push`'s
  encryption and VAPID header, takes 200 and 201 as success and logs a
  failure with the device id only, never the endpoint.
- **L12 Module 1.5: « read » pushes.** After super,
  `discuss.channel.member._set_last_seen_message` (mark-as-read and the
  author's own post, `discuss_channel.py:741-750`) records, when
  `seen_message_id` advanced, `(partner, channel, seen id)` in
  `cr.postcommit.data["erplibre.read"]`, one postcommit callback per
  transaction sending the highest id per (device, channel):
  `{"erplibre": {"v": 1, "type": "read", "channel_id": c, "last_message_id": m}}`.
  `mail.message.set_message_done` and `mark_all_as_read` send
  `{"erplibre": {"v": 1, "type": "inbox_done", "threads": [[model, res_id], …]}}`
  for the non-channel threads of the messages done for the current partner,
  `threads: null` above 40. Only to the reader's marked devices; never a
  read push to a browser (Odoo's service worker would draw it empty,
  `mail/static/src/service_worker.js:57-60`).
- **L13 Module 1.5: quiet while a browser is online.** `bus.presence` gains
  `erplibre_browser_poll` and `erplibre_browser_presence` (Datetime). The
  module's `ir.websocket._update_bus_presence` writes them, after Odoo's own
  update, for a websocket whose session hash is no marked device's of that
  user (the app's own bus never counts as a browser). A browser is online
  when `erplibre_browser_poll ≥ now − 65 s` (`bus/models/bus_presence.py:9`
  `DISCONNECTION_TIMER`) and `erplibre_browser_presence ≥ now − 30 min`
  (`AWAY_TIMER`). Only message pushes are skipped, read pushes never; the
  phone setting that turns it on is lot 3: in lot 2 the app sends
  `quiet_while_online` false and the long tests drive the route directly.
- **L14 The app learns 1.5.** `ChatModuleLevel` gains "1.5", the current
  level (`moduleProbe` installed only at 1.5, outdated at 1.0–1.4, as lot 5's
  pattern); `features(configId).appPush` = `at("1.5")`. Each mirrored account
  gains `module`: the level the outbox would use for a post (`""` when
  `moduleMode` is "ignore" or none is seen): native code adds
  `erplibre_client_uuid` when it is not empty. Native code never infers the
  module from a payload except for L5.
- **L15 Notification after an action.** Reply: the text is appended at once
  as the user's own message (`you`), silently, actions kept — on a `never`
  server the notification is re-posted silently unchanged, no text; the module's
  read push for the author's post then removes the notification. Mark read
  and mute: cancelled at once. 👍: re-posted silently without « 👍 ». A
  handoff adds the server's handoff notification. A read push trims the
  stack: the ids of `erplibre.message_ids` ≤ `last_message_id` (and the
  messages carrying none) go; with only the user's own left, the
  notification goes; else re-posted silently (a `never` server's stays
  « Nouveau message »). Control pushes apply in the foreground too.
- **L16 « Without the module » in tests** is a device the module does not
  know (the app with `chatModule: "ignore"` never calls the route): Odoo's
  own code path, which the module tests pin byte for byte (same
  `push_to_end_point` call, same payload, same warning on 200). The run's
  Odoo 18 template keeps the module installed.

## Global Constraints

- Everything in the project 1 and lot 1 Global Constraints still holds (Odoo 18 only for chat; one commit per task per repo; `[TYPE] scope: subject` ≤ 72 chars in English; bilingual body EN then `--- FR ---`, ≤ 8 lines per language; `Assisted-by:`; never an AI in `Co-authored-by:`; files named at `git add`, never `-A`, never `-N`).
- **No migration in M** (the latest stays 2026102801). Module version **18.0.1.5.0**, level key `("1.5", "1.5")` appended to `erplibre_chat_level`'s selection.
- French labels fixed here: « Répondre », « Votre réponse », « Marquer lu », « Muet 1 h », « 👍 », « Ouvrez l'app pour terminer une action — {server} », « Ouvrez l'app pour terminer {n} actions — {server} ». Native strings only through `PUSH_STRING_KEYS` (`chat.push_<key>`, en and fr) with French fallbacks in `PushStrings`.
- Secrets never logged nor unsealed natively: the ntfy token, keys, the session copy, **a waiting reply's text**. The module never logs an endpoint.
- Native code calls Odoo on: lot 1's three routes, plus `/mail/message/post`, `/discuss/channel/mark_as_read`, `/discuss/settings/mute`, `/mail/message/reaction`, and `call_kw` `mail.message` `search`, `search_read` (marker), `mark_all_as_read` (bounded). Never `/discuss/channel/messages`, `/mail/thread/messages`, `set_message_done`.
- Every action is durable before the network; nothing marks an action done without Odoo's answer; nothing is dropped except an action of an account removed or a mute whose hour passed.
- PendingIntents of actions: explicit to the non-exported `ChatActionReceiver`, request codes unique per (tag, kind); the reply one `FLAG_MUTABLE` (RemoteInput), the others `FLAG_IMMUTABLE`.
- `HARNESS_API` 6 → 7 (`src/testing/syncTestKit.ts:73`, `long_test/mobile_sync_odoo.py:58`) and `DEVICE_HOOK_API` 7 → 8 (`src/testing/deviceTestHook.ts:34`, `long_test/mobile_sync_device.py`), in Task 9; `test/test_mobile_sync_harness.py` follows.
- The test servers run no cron: a long test keeps a recipient under 5 devices (marked or not) unless it tests the queue path through `mail.push` explicitly by running the cron method.
- Phone: Android 11, PIN — never lock; only the test app; restore everything (`tasks/chat/p2l2-conventions.md`).

## Review Focus

1. **A session that died on the server while its copy looks fine:** Odoo answers the public user, `mark_as_read` returns `null`; nothing must be recorded done, the action goes to the app and the app sends it once (Task 4 `a dead session is SESSION_EXPIRED before any action route`; Task 5 `an expired session hands every kind off and marks the copy expired`; Task 9 device step 8).
2. **A reply whose answer was lost (timeout after Odoo posted), or whose process died mid-call, without the module:** one message in Odoo, found by its marker after the quiet window, whether native code or the app's outbox resumes it (Task 5 `a lost answer without module is found by its marker after the quiet window`, `a running action cut by a death resumes as maybe sent`; Task 8 `a handoff reply maybe sent searches before posting`; Task 9 long test `a handoff reply that Odoo already holds posts nothing`).
3. **The app opened while an action is pending or running, or a drain cut before its ack:** the action is sent by exactly one side, and a repeated drain queues nothing new (Task 5 `a pending or running record is not listed for the drain`; Task 8 `a drained reply whose uuid already has a message is skipped`).
4. **A read in the browser at message N while message N+1 already rang the phone:** the notification keeps N+1 and drops N, it does not vanish (Task 3 `a read push keeps the messages after the read point`; Task 2 `two marks in one request send one read push with the highest id`).
5. **Quiet while a browser is online, with the app's own websocket connected or just closed:** the app never counts as a browser, an away browser does not silence the phone, and a read push is never skipped (Task 2 `the app's own session never counts as a browser`, `an away browser lets the push through`; Task 9 long test `quiet while a browser is online`).

---

## File Structure

Each task's **Files** block is the authority. In short: **A** gains
`models/mail_push_device.py`, `models/mail_push.py`,
`models/discuss_channel_member.py`, `models/bus_presence.py`,
`models/ir_websocket.py`, `tools/app_push.py`, `controllers/push.py`, tests
`test_app_push.py`, `test_read_push.py`; extends `models/mail_thread.py`,
`models/mail_message.py`. **M** gains in `chatpush/` `OdooJson.java`
(shared JSON-RPC call), `OdooActions.java`, `ReplyBody.java`,
`ChatAction.java`, `ActionStore.java`, `ActionRunner.java` (pure, JVM-tested)
and `ChatActionReceiver.java`, `ChatActionJob.java` (Android glue); on the JS
side `src/services/chat/chatPushActions.ts`. **E** gains
`long_test/mobile_sync/chatPushModule.test.ts`, `chatPushActions.test.ts`.

---

### Task 0: Validation spike (real action answers, the dead-session trap) and the lot 1 carry-over

Nothing below Task 0 is built until its checks pass and their outcomes are in `tasks/chat/p2l2-sdd/ledger.md`.

**Files:** spike under `tasks/chat/p2l2-sdd/spike/` (not versioned): `actions.py` (run with `.venv.erplibre/bin/python -I`, `requests` only); shapes written to `tasks/chat/p2l2-sdd/shapes/`. Carry-over: M `chatpush/PushEngine.java` (`:813`), `chatpush/NotificationModel.java` (`inbox`), `src/services/chat/chatPush.ts` (`forget`, `registerOnce`), `src/components/options/chat_notifications/options_chat_notifications_component.ts`, tests `PushEngineTest.java`, `NotificationModelTest.java`, `chatPush.test.ts`, `optionsChatNotifications.test.ts`.

**Interfaces:**
- Produces for Tasks 4, 5, 8: `shapes/session_info.json`, `post_answer.json` (`/mail/message/post` result as Odoo 18 answers a cookie-only client), `post_answer_module_resend.json`, `mark_as_read.json`, `mark_all_as_read.json`, `search_latest.json`, `search_read_marker.json`, `mute.json`, `reaction_add.json`, `reaction_add_again.json`, `dead_session_info.json` (the code-100 error), `dead_post.json`, `dead_mark_as_read.json`, `dead_reaction.json` — each the full JSON-RPC response body, verbatim.

- [ ] **Step 1: Start.** `./long_test/mobile_sync.py --versions 18 --filtre smoke --garder` (module 1.4 installed, `admin`, `chat_user`, « ms chat »; URL and database in `targets.json`).
- [ ] **Step 2: Capture with a cookie-only session** (`/web/session/authenticate` as admin, then only `Cookie: session_id=…` on every call, no CSRF, as `OdooDirect` sends): `get_session_info`; a post in admin's chat with chat_user with body `Bonjour du test d'action<!-- erplibre-mobile:<uuid> -->`, `post_data.erplibre_client_uuid = <uuid>`, `context.temporary_id = <uuid>`; the same post again (the module must answer the same message id); the same body without `erplibre_client_uuid` under another uuid, then `call_kw mail.message search_read` with L2's marker domain; `call_kw mail.message search` with L4's date domain; `mark_as_read`; the bounded `mark_all_as_read`; `/discuss/settings/mute {minutes: 60, channel_id}` (then `{minutes: 0, channel_id}` to unmute); `/mail/message/reaction` add twice.
- [ ] **Step 3: The dead session.** `/web/session/destroy` on that cookie, then `get_session_info`, `mark_as_read`, `/mail/message/post`, `/mail/message/reaction` with the dead cookie; record each answer and, as chat_user, admin's `seen_message_id` before and after the dead `mark_as_read`.
- [ ] **Step 4: Checks, each written to the ledger with its evidence:** (a) the resend with `erplibre_client_uuid` answers the first message id and Odoo holds one message; (b) the marker search finds exactly the post; (c) the date search returns the post's id and the fetch routes were not called (a needaction of admin on another message stays); (d) `get_session_info` with the dead cookie is JSON-RPC code 100; (e) the dead `mark_as_read` answers without error and changes nothing (L3's trap) — any other answer is recorded and L3 still holds; (f) the reaction added twice leaves one reaction.
- [ ] **Step 5: Outcome rule.** (a), (b), (d) as expected → go. (a) gives two messages → STOP and report (module dedup broken, L2 rests on it). Copy the shapes, mask hosts and ports per the conventions; stop the kept servers (`./long_test/mobile_sync.py --detruire`).
- [ ] **Step 6: Carry-over (lot 1, parked minors on lot 2's path), each test first:** `PushEngineTest` `a session copied in the same millisecond as the mirror is kept` (`:813` `<=` → `<`: lot 2's actions depend on the copy); `NotificationModelTest` `an inbox push with an empty title is titled by the server`; `chatPush.test.ts` `forget is bounded as a whole, its queue wait included` (`UNREGISTER_BOUND_MS` covers the wait for the push queue and the unregister calls, as final review B asked) and `a registration failure reason is shown until the next success` (`ChatPush.registrationError(configId): string | null`, in memory, set by `registerOnce` on « offline » / « refused » with the reason's i18n key, cleared on « registered »); the options card shows it under the registration line (`optionsChatNotifications.test.ts`); `npm test`, the JVM suite.
- [ ] **Step 7: Commit** (M): `[FIX] chat push: same-ms session copy, bounded forget, registration reason`.

### Task 1: Module 1.5 — app devices, their payload, the after-commit sender (A)

**Files:** A create `erplibre_mobile_chat/tools/__init__.py`, `tools/app_push.py`, `models/mail_push_device.py`, `models/mail_push.py`, `models/res_users.py` (`_erplibre_browser_online` returning False until Task 2), `controllers/push.py`, `tests/test_app_push.py`; modify `models/__init__.py`, `controllers/__init__.py`, `models/mail_thread.py`, `models/mail_message.py` (selection `[("1.4", "1.4"), ("1.5", "1.5")]`), `tests/__init__.py`, `__manifest__.py` (`18.0.1.5.0`, summary and description: notifications of the app), `i18n/fr_CA.po`, `README.md`.

**Interfaces:**
- `tools/app_push.py`: `send(session, base_url: str, device: dict, payload: str, vapid_private_key: str, vapid_public_key: str, timeout: int = 5) -> str` — `"sent"` on 200 or 201, `"gone"` on 404 or 410, `"failed"` otherwise (logged at warning with `device["id"]` and the status, never the endpoint); the `.invalid` host rule and the body as `mail.tools.web_push.push_to_end_point` (`_encrypt_payload`, the same JWT claims and `Authorization: vapid t=…, k=…`, `Content-Encoding: aes128gcm`, `TTL: 60`). `send_all(env, items: list[tuple[dict, str]]) -> None` — one `requests.Session`, the VAPID keys and base URL read before; the `"gone"` device ids unlinked in `with env.registry.cursor() as cr` (a fresh cursor). `schedule(env, items)` — `env.cr.postcommit.add` of a closure over plain data (endpoint, keys, id, payload JSON, keys of VAPID, base URL), no record inside.
- `mail.push.device` (L10): the three fields; `_search` adds `[("erplibre_app", "=", False)]` under context `erplibre_skip_app_devices`; `register_devices` clears the three fields when it moves an endpoint to another partner; `_erplibre_app_devices(partner_ids) -> recordset` (sudo).
- `controllers/push.py`: `POST /erplibre_mobile_chat/push/device` (L10), `quiet_while_online` stored as given, `erplibre_session_hash = sha256(request.session.sid)`.
- `mail.thread._notify_thread_by_web_push(message, recipients_data, msg_vals=False, **kwargs)` (L11); `_erplibre_app_payload(message, msg_vals) -> dict`; quiet skipping calls Task 2's `res.users._erplibre_browser_online()` — a stub returning False in this task, filled by Task 2.
- `mail.push._push_notification_to_endpoint(batch_size=50)`: the rows of marked devices sent through `app_push.send_all` and unlinked first, then super.

- [ ] **Step 1: Failing tests** (`tests/test_app_push.py`, `HttpCase`, users by `new_test_user`, VAPID keys from `get_web_push_vapid_public_key`, `patch.object(requests.Session, "post")` answering a chosen status, `self.env.cr.postcommit.run()` where after-commit is asserted): `test_level_selection_ends_with_1_5`; `test_route_marks_own_device_only` (another partner's endpoint → `{"ok": false}`, unchanged); `test_route_stores_session_hash_and_quiet`; `test_register_to_other_partner_clears_marks`; `test_unmarked_device_takes_odoo_path_unchanged` (`patch` of `odoo.addons.mail.models.mail_thread.push_to_end_point`: called once with the stock payload, the stock warning logged on 200); `test_marked_device_skips_odoo_path`; `test_marked_payload_has_message_id_and_channel_type` (chat, group, channel mention: `options.data.erplibre == {"v": 1, "message_id": <the post's id>, "channel_type": …}`; a record comment: `channel_type` null); `test_marked_push_waits_for_commit` (no `post` before `postcommit.run()`); `test_marked_200_logs_nothing_with_the_endpoint` (`assertNoLogs` at WARNING on the mail web push logger, and the module's log line names the device id only); `test_marked_410_unlinks_device`; `test_long_body_still_fits` (a body of 4000 accented characters: the app payload's JSON, encoded, ≤ the limit `_truncate_payload` keeps); `test_five_marked_devices_go_through_mail_push` (rows created, the cron method sends them through the module sender and leaves the browsers' rows to Odoo).
- [ ] **Step 2: Run** the module tests (conventions) → FAIL, output pasted.
- [ ] **Step 3: Implement** the interfaces; README and manifest description in French, `fr_CA.po` for the new fields' labels and helps.
- [ ] **Step 4: Run** → PASS (the existing 1.4 tests green too); black, ruff, isort; `dropdb chat_module_test`.
- [ ] **Step 5: Commit** (A): `[ADD] erplibre_mobile_chat: app push devices, message id, after commit`.

### Task 2: Module 1.5 — « read » pushes and quiet while a browser is online (A), shapes captured

**Files:** A create `models/discuss_channel_member.py`, `models/bus_presence.py`, `models/ir_websocket.py`, `tests/test_read_push.py`; modify `models/__init__.py`, `models/mail_message.py`, `models/res_users.py` (`_erplibre_browser_online`), `tests/__init__.py`, `i18n/fr_CA.po`, `README.md`. Capture: `tasks/chat/p2l2-sdd/spike/module_shapes.py` → `tasks/chat/p2l2-sdd/shapes/push_module_{chat,group,channel,record}.json`, `push_read.json`, `push_inbox_done.json` (decrypted plaintexts).

**Interfaces:**
- `discuss.channel.member._set_last_seen_message(message, notify=True)` (L12); `mail.message.set_message_done()`, `mark_all_as_read(domain=None)` (L12, their return values unchanged).
- `bus.presence` fields (L13); `ir.websocket._update_bus_presence(inactivity_period, im_status_ids_by_model)` (L13; the write wrapped as Odoo's own, `tools.mute_logger("odoo.sql_db")`, concurrency errors rolled back and ignored).
- `res.users._erplibre_browser_online() -> bool` (L13 timers, `DISCONNECTION_TIMER`, `AWAY_TIMER` imported from `bus.models.bus_presence`).

- [ ] **Step 1: Failing tests** (`tests/test_read_push.py`): `test_mark_as_read_sends_read_push_after_commit` (payload exactly L12's); `test_own_post_sends_read_push` (the author's post in the browser); `test_no_read_push_when_seen_does_not_advance`; `test_two_marks_in_one_request_send_one_read_push_with_the_highest_id`; `test_read_push_never_reaches_a_browser_device`; `test_set_message_done_sends_inbox_done_with_threads` (a `project.task` comment, the channel threads left out); `test_mark_all_as_read_over_40_threads_sends_null`; `test_inbox_done_without_record_threads_sends_nothing`; `test_browser_presence_written_for_a_browser_session` (`_update_bus_presence` under a websocket request mock carrying a session id no device holds); `test_the_apps_own_session_never_counts_as_a_browser`; `test_quiet_device_skipped_while_browser_online`; `test_an_away_browser_lets_the_push_through` (presence 31 min); `test_a_stale_browser_lets_the_push_through` (poll 66 s ago); `test_read_push_sent_even_while_browser_online`.
- [ ] **Step 2–4:** FAIL (pasted) → implement → PASS; black, ruff, isort; `dropdb`.
- [ ] **Step 5: Capture the 1.5 shapes for M.** On a kept harness Odoo 18 with the branch's module upgraded (`-u erplibre_mobile_chat`), the lot 1 spike's ntfy and keys (`tasks/chat/p2l1-sdd/spike/spike.py` as the model), a device marked through the route: decrypt and save a chat, group, channel-mention and record push, a read push (chat_user's browser session marks read) and an inbox_done push; then `--detruire`. Ledger: the six plaintexts.
- [ ] **Step 6: Commit** (A): `[ADD] erplibre_mobile_chat: read pushes, quiet while a browser is online`.

### Task 3: Phone side of 1.5 — message ids, actions offered, control pushes (M, Java)

**Files:** M modify `chatpush/PushPayload.java`, `NotificationModel.java`, `PushEngine.java` (`deliver`, `Notifier`), `ChatNotifier.java`, `AccountView.java`, `ChatPushRuntime.java` (`publishSettings` reads `module`), `PushStrings.java`; tests `PushPayloadTest.java`, `NotificationModelTest.java`, `PushEngineTest.java`; resources `chatpush/push_module_*.json`, `push_read.json`, `push_inbox_done.json` (Task 2's captures).

**Interfaces:**
- `PushPayload`: `enum Kind { MESSAGE, READ, INBOX_DONE }`; new fields `kind`, `messageId` (0 absent), `channelType` ("" absent), `channelId` and `lastMessageId` (READ), `List<String[]> threads` (INBOX_DONE, `{model, resId}`; null = every inbox notification). `isChat()` unchanged.
- `AccountView` gains `final String module` ("" none); the 4-argument constructor stays (module "").
- `enum ActionKind { REPLY, READ, MUTE, REACT }`.
- `NotificationModel.Shown` gains `String configId`, `long channelId`, `long messageId`, `EnumSet<ActionKind> actions`. `chat(…)` fills them per L1; `channelType` from the payload stands in for a missing mirrored type in `authorOf`.
- `static List<Long> keptAfterRead(List<Long> ids /* stack order, 0 = no id */, long lastMessageId)` — the ids of messages kept (L15).
- `PushEngine.Notifier` gains `void trimRead(String tag, long lastMessageId)` and `Map<String, Long> shownAt()`; READ → `trimRead("chat:<configId>:<channelId>", last)`; INBOX_DONE → `cancel` of the matching `inbox:` tags posted at or before the push's ntfy time (`NotificationModel.Clear`, `before`); both applied in the foreground too, neither shown.
- `ChatNotifier.show` keeps the stack's ids in the notification's extras, `erplibre.message_ids` (`long[]`, stack order, 0 for a message without id, the previous notification's array extended), for every chat notification, `never` servers included, and also stores `erplibre.message_id` in each `MessagingStyle.Message`'s extras; `trimRead` reads the array, keeps `keptAfterRead`, cancels or re-posts silently (L15: a `never` server's re-post stays generic); the action buttons themselves are Task 6's.
- `PushStrings` keys and French fallbacks: `action_reply` « Répondre », `action_reply_hint` « Votre réponse », `action_mark_read` « Marquer lu », `action_mute` « Muet 1 h », `action_react` « 👍 », `handoff_one` « Ouvrez l'app pour terminer une action — {server} », `handoff` « Ouvrez l'app pour terminer {n} actions — {server} ».

- [ ] **Step 1: Failing JUnit:** `PushPayloadTest` over each captured shape: `a 1.5 chat push carries its message id and type`; `a stock push has no message id` (lot 1's `odoo18_push.json`); `a read push is READ with its channel and id`; `an inbox_done push lists its threads, null for all`. `NotificationModelTest`: `hidden and always servers offer the four actions with a message id`; `without a message id there is no react`; `a never server offers every action with its text hidden` (four actions with a message id, `conversationTitle` and `text` « Nouveau message », `messaging` false); `inbox and summary offer nothing`; `keptAfterRead drops ids up to the read point and those without id`. `PushEngineTest`: `a read push trims its conversation and shows nothing`; `a read push keeps the messages after the read point` (the fake notifier's stack holds ids 7 and 9, read at 7: 9 stays, re-posted silently); `a read push applies in the foreground`; `inbox_done cancels the records named, posted before it`; `inbox_done null cancels every inbox notification of the account`; `a read push is never counted undecryptable`; `a read push trims a never server's notification by its ids` (the fake notifier's id array, the re-post still « Nouveau message »).
- [ ] **Step 2–4:** FAIL (pasted) → implement → PASS; `./gradlew --stop`.
- [ ] **Step 5: Commit** (M): `[ADD] chat push: message ids, read pushes trim notifications`.

### Task 4: Native Odoo action client (M, Java)

**Files:** M create `chatpush/OdooJson.java`, `OdooActions.java`, `ReplyBody.java`; modify `OdooDirect.java` (its `call` and `requireAllowed` move to `OdooJson`, behaviour unchanged), `OdooDirectException.java` (kinds `REFUSED`: a JSON-RPC error other than code 100, or HTTP 4xx other than 401/404/408/410/429; `TRANSIENT`: 408, 429, 5xx, or a post answer without a message id; `AMBIGUOUS`: two marker hits); tests `OdooActionsTest.java`, `ReplyBodyTest.java`; resources `chatpush/actions/*.json` (Task 0's shapes).

**Interfaces:**
- `final class OdooJson { OdooJson(OkHttpClient c); Object call(NativeSession s, String path, JSONObject params, boolean allowHttp) throws OdooDirectException; }` (lot 1's rules: cookie only, no redirect, no message carrying a URL or the session).
- `final class OdooActions { OdooActions(OkHttpClient base /* call timeout 8 s, connect 4 s */); long alive(NativeSession s, boolean allowHttp) throws OdooDirectException /* self partner id; SESSION_EXPIRED on code 100 / 401 */; Posted post(NativeSession s, long channelId, String bodyHtml, String clientUuid, boolean useModule, boolean allowHttp) throws OdooDirectException; Long findSent(NativeSession s, long channelId, String clientUuid, long selfPartnerId, boolean allowHttp) throws OdooDirectException /* null none; AMBIGUOUS on two */; Long latestMessageId(NativeSession s, long channelId, long atMostEpochS, boolean allowHttp) throws …; void markRead(NativeSession s, long channelId, long lastMessageId, boolean allowHttp) throws …; void mute(NativeSession s, long channelId, int minutes, boolean allowHttp) throws …; String react(NativeSession s, long messageId, String content, boolean allowHttp) throws … /* the Store answer JSON */; }`, `final class Posted { final long messageId; final String answer /* null above 32 KiB */; }`.
- `final class ReplyBody { static String of(String text, String clientUuid); }` — `escapeAndCompact` (`chatCompose.ts:79-87`) then `<!-- erplibre-mobile:<uuid> -->`.

- [ ] **Step 1: Failing JUnit** (MockWebServer answering Task 0's captured bodies): `ReplyBodyTest` `the body is escaped and compacted as the app does` (cases copied from the JS tests of `composeBody` with no mention: `<b>`, `a  b`, `\n\n\n`, CRLF, leading spaces) and `the marker ends the body`; `OdooActionsTest`: `a dead session is SESSION_EXPIRED before any action route` (the dead `get_session_info` shape, then no other request recorded); `post sends the marker, the temporary id and the uuid with the module`; `post without the module sends no uuid field`; `a post answer without an id is TRANSIENT` (Odoo may have posted); `findSent filters on the whole marker comment` (a body quoting the uuid without the comment is not taken); `findSent with two hits is ambiguous`; `latestMessageId uses search with the date bound, never a fetch route` (recorded paths); `markRead bounds mark_all_as_read to the channel and the id`; `mute sends the minutes and the channel`; `react adds and returns the Store answer`; `http refused before any request`; `a 503 is TRANSIENT, a 403 REFUSED`; `no exception message carries the session id or a URL`.
- [ ] **Step 2–4:** FAIL (pasted) → implement → PASS (`OdooDirectTest` green unchanged); `./gradlew --stop`.
- [ ] **Step 5: Commit** (M): `[ADD] chat push: native Odoo actions with the session copy`.

### Task 5: Action store and runner — durable, once, handed off (M, Java)

**Files:** M create `chatpush/ChatAction.java`, `ActionStore.java`, `ActionRunner.java`; tests `ActionStoreTest.java`, `ActionRunnerTest.java`.

**Interfaces:**
- Consumes Task 4 (`OdooActions`, `ReplyBody`), lot 1's `NativeSessions`, `PushSettingsStore`, `SecretBox`, `KeyValue`.
- `final class ChatAction { enum State { PENDING, RUNNING, DONE, HANDOFF } final String id, configId, clientUuid; final ActionKind kind; final long channelId, messageId /* 0 */, atMostS /* L4 bound */, createdAt; final String text /* reply, else "" */, content /* "👍" */; State state; long sentAt /* 0: never possibly sent */, nextAt; int attempts; String reason /* handoff */, answer /* Store JSON or null */; long doneAt; JSONObject toJson(); }` — `toJson` is the drain's shape, Task 6's `NativeAction`: kind and state in lower case, `messageId` and `sentAt` null when 0.
- `final class ActionStore { ActionStore(KeyValue kv, SecretBox box, LongSupplier clock); ChatAction add(String configId, ActionKind k, long channelId, long messageId, long atMostS, String text); boolean claim(String id); void markSent(String id); void done(String id, String answer); void retryLater(String id); void handoff(String id, String reason); List<ChatAction> due(); List<ChatAction> forDrain() /* DONE and HANDOFF */; void ack(Collection<String> ids) /* ignores PENDING and RUNNING */; int recover() /* RUNNING → PENDING, sentAt kept */; int handoffCount(String configId); void prune() /* DONE older than 7 days */; static final long QUIET_MS = 180_000, STALE_MS = 86_400_000; }` — every write `commit()`ed; the whole record sealed (the reply text inside).
- `final class ActionRunner { ActionRunner(ActionStore store, NativeSessions sessions, PushSettingsStore settings, OdooActions odoo, LongSupplier clock); Outcome run(String id); void runDue(); enum Outcome { DONE, RETRY, HANDOFF, SKIPPED } }` — per L2–L6, L9: unknown account → dropped (acked as done without answer); session null or expired → HANDOFF `session_expired`; `alive` SESSION_EXPIRED → `sessions.markExpired` + HANDOFF; REPLY: module → `post` (`markSent` before the call); no module and `sentAt` set → wait `QUIET_MS` from `sentAt` (RETRY with `nextAt`), then `findSent`, found → DONE with that id, else `post`; READ: `messageId` or `latestMessageId`, then `markRead`; MUTE: minutes left from `createdAt + 1 h`, none → DONE; REACT: `react`; TRANSIENT/UNREACHABLE → RETRY (`nextAt` 30 s × 2ⁿ, 1 h cap) unless older than `STALE_MS` → HANDOFF `stale`; REFUSED → HANDOFF `refused`; AMBIGUOUS → HANDOFF `ambiguous`.

- [ ] **Step 1: Failing JUnit** (MockWebServer as Odoo with Task 0's shapes, a manual clock): `ActionStoreTest`: `an action is durable and sealed before it is claimed` (no reply text in any raw value); `claim refuses a claimed record`; `a pending or running record is not listed for the drain`; `ack leaves pending and running records`; `recover turns running back to pending and keeps sentAt`; `done records older than seven days are pruned`. `ActionRunnerTest`: `a reply with the module posts once and is done with the Store answer`; `a resend with the module posts again with the same uuid`; `a lost answer without module is found by its marker after the quiet window` (first post answers a timeout after Odoo recorded it; RETRY before 3 min; then `findSent` hit → DONE, one `post` call in all); `a running action cut by a death resumes as maybe sent`; `two marker hits hand off as ambiguous`; `an expired session hands every kind off and marks the copy expired`; `mark read without a message id searches by date then marks`; `mark read with a message id does not search`; `a mute retried later sends the minutes left`; `a mute whose hour passed is done without a call`; `react sends the message id`; `a 403 hands off as refused`; `an action failing for a day hands off as stale`; `an account no longer mirrored drops its action`; `runDue runs only due records, oldest first`.
- [ ] **Step 2–4:** FAIL (pasted) → implement → PASS; `./gradlew --stop`.
- [ ] **Step 5: Commit** (M): `[ADD] chat push: durable native actions, once, handed off`.

### Task 6: Notification actions, receiver, retry job, plugin bridge (M, Android + TS bridge)

**Files:** M create `chatpush/ChatActionIntent.java`, `chatpush/ChatActionReceiver.java`, `chatpush/ChatActionJob.java`, test `ChatActionIntentTest.java`; modify `ChatNotifier.java` (actions, handoff notification), `ChatPushRuntime.java` (`actions()`, the store and runner built with the engine, `setActionsListener(Runnable)` that the plugin sets to emit `actions`; `ChatPushJob` run also calls `runner.runDue()`), `ChatPushJob.java`, `ChatPushPlugin.java` (`actions`, `ackActions`, event `actions`), `AndroidManifest.xml` (receiver `android:exported="false"`, job service), `src/plugins/chatPushPlugin.ts`, `src/__mocks__/chatPushNative.ts`, `src/__tests__/chatPushPlugin.test.ts`, `featureCatalog.ts`.

**Interfaces:**
- Consumes Tasks 3 (`Shown.actions`, `ActionKind`, strings) and 5 (`ActionStore`, `ActionRunner`, `ChatAction.toJson`).
- `final class ChatActionIntent { static final String ACTION = "ca.erplibre.home.chatpush.ACTION"; static final String KEY_REPLY = "erplibre.reply"; static Intent of(Context c, NotificationModel.Shown n, ActionKind k); static Parsed parse(Intent i) /* configId, channelId, messageId, atMostS, kind, tag; null when incomplete */; static int requestCode(String tag, ActionKind k); }` (pure parts JVM-tested through a plain `Map` of extras).
- `ChatActionReceiver.onReceive`: `parse`, `ActionStore.add` (reply text from `RemoteInput.getResultsFromIntent`, blank → ignored), the notification updated per L15, then `goAsync()` + one executor thread: `runner.run(id)` within 9 s, `PendingResult.finish()` in `finally`; RETRY → `ChatActionJob.schedule(c, nextAt)`; HANDOFF → `ChatNotifier.handoff(configId, store.handoffCount(configId))`; any outcome → the runtime's actions listener (the plugin's `actions` event when the app runs).
- `ChatActionJob` (`JOB_ID = 4824`, beside 4821–4823): one-off, `NETWORK_TYPE_ANY`, persisted, minimum latency until the earliest `nextAt`; `onStartJob` → `recover()` then `runDue()` off the main thread, rescheduled while records are pending.
- `ChatNotifier`: `NotificationCompat.Action`s per `Shown.actions` (reply with `RemoteInput` labelled `action_reply_hint`, `setAllowGeneratedReplies(false)`, `SEMANTIC_ACTION_REPLY`; mark read `SEMANTIC_ACTION_MARK_AS_READ`, `setShowsUserInterface(false)`; mute `SEMANTIC_ACTION_MUTE`; react `SEMANTIC_ACTION_THUMBS_UP`); `setAuthenticationRequired(true)` per L1; `appendOwnReply(tag, text)` (on a `never` server a silent re-post without the text), `withoutReact(tag)`, `handoff(String configId, int count)` (tag `handoff:<configId>`; cancelled when the count is 0).
- TS (`chatPushPlugin.ts`): `export interface NativeAction { id: string; configId: string; kind: "reply" | "read" | "mute" | "react"; state: "done" | "handoff"; reason: string | null; channelId: number; messageId: number | null; clientUuid: string; text: string; content: string; createdAt: number; sentAt: number | null; answer: string | null; }`; `ChatPushNative.actions(): Promise<NativeAction[]>`, `ackActions(o: { ids: string[] }): Promise<void>`, `addListener(event: "actions", fn: () => void)`; the mock records and serves them.

- [ ] **Step 1: Failing tests:** JUnit `ChatActionIntentTest`: `an action intent carries what the runner needs`; `an incomplete intent parses to null`; `request codes differ per tag and kind`. Vitest `chatPushPlugin.test.ts`: `actions` and `ackActions` forwarded, a rejection names the method, the `actions` event reaches a listener.
- [ ] **Step 2–3:** FAIL (pasted) → implement → PASS (`./gradlew :app:testDebugUnitTest`, `npm test`); `BUNDLE_SKIP_WHISPER=1 ./gradlew assembleDebug` and `-PnoChatRealtime` both build; `aapt2 dump xmltree` shows `ChatActionReceiver` with `exported=false`; `./gradlew --stop`.
- [ ] **Step 4: Commit** (M): `[ADD] chat push: reply, mark read, mute and 👍 from the notification`.

### Task 7: The app learns 1.5, marks its device, mirrors the module level (M, JS)

**Files:** M modify `src/services/chat/chatModule.ts`, `src/services/chat/chatService.ts` (`features`), `src/services/chat/chatPush.ts` (`registerOnce`, `mirrorSession`, `publishNow`, `PUSH_STRING_KEYS`), `src/components/options/chat_notifications/options_chat_notifications_component.ts` (one line per account), `src/i18n/en.ts`, `fr.ts`, tests `chatModule.test.ts`, `chatPush.test.ts`, `optionsChatNotifications.test.ts`.

**Interfaces:**
- `ChatModuleLevel` gains `"1.5"`, `CURRENT_LEVEL = "1.5"`; `features(configId)` gains `appPush: boolean` (`at("1.5")` and `moduleMode` "auto").
- `ChatPush.markAppDevice(src: ChatSource): Promise<boolean>` — `jsonRoute(…, "/erplibre_mobile_chat/push/device", {endpoint, quiet_while_online: false})`, `PUSH_RPC_TIMEOUT_MS`; called by `registerOnce` after `register_devices` and by the `onSessionStored` path after `mirrorSession`, both only when `appPush` and the row has an endpoint; a failure is logged and kept as `registrationError` (Task 0), never failing the registration.
- Mirror: each account of `publishSettings` gains `module: string` (L14: `""` when the outbox would post without the module); `PushAccountMirror` in `chatPushPlugin.ts` gains the field.
- `PUSH_STRING_KEYS` gains Task 3's seven keys; `chat.push_<key>` in both languages (the French of Task 3, the English « Reply », « Your reply », « Mark read », « Mute 1 h », « 👍 », « Open the app to finish an action — {server} », « Open the app to finish {n} actions — {server} »).
- Options card line `chat.push_actions_full` « Actions : répondre, marquer lu, muet 1 h, 👍 » / `chat.push_actions_no_react` « Actions : répondre, marquer lu, muet 1 h (👍 avec le module 1.5) ».

- [ ] **Step 1: Failing tests:** `chatModule.test.ts`: the level matrix gains `[["1.4","1.4"],["1.5","1.5"]]` → 1.5, `[["1.4","1.4"],["1.6","1.6"]]` → 1.5, a 1.4 server is outdated and `appPush` false; `chatPush.test.ts`: `a 1.5 account marks its device after registering`; `a new session marks the device again`; `a 1.4 account never calls the device route`; `with the module ignored the device is not marked and the mirror says no module`; `a failed mark keeps the registration and shows the reason`; `the mirror carries the module level`; `publish sends the action strings`; options: `the actions line says whether 👍 is there`.
- [ ] **Step 2–3:** FAIL (pasted) → implement → PASS; `npm test`, `npm run build`.
- [ ] **Step 4: Commit** (M): `[ADD] chat: module 1.5 detection, app device marked, level mirrored`.

### Task 8: Drain native actions into the outbox and the cache (M, JS)

**Files:** M create `src/services/chat/chatPushActions.ts`, `src/__tests__/chatPushActions.test.ts`; modify `src/services/outboxService.ts` (`enqueue` takes an optional `clientUuid`), `src/services/chat/chatOutbox.ts` (`PostOpts` gains `clientUuid?: string`, `maybeSentAt?: string`; `queuePostNow` uses them; `sendPost`'s search condition `op.attempts > 1 || op.params.maybeSent`), `src/services/chat/chatLifecycle.ts` (`follow(true)` drains), `src/services/syncService.ts` (construction), `src/js/app.ts` (drain after the first chat load), `featureCatalog.ts`, `src/__tests__/chatOutbox.test.ts`.

**Interfaces:**
- Consumes Task 6 (`NativeAction`, `actions`, `ackActions`, event) and lot 1's `ChatService` (`queue`, `repo`, `sources`, `loadUntil`).
- `ChatService.pushActions: ChatPushActions` (set at construction, as `push`). `class ChatPushActions { constructor(chat: ChatService, native: ChatPushNative | null, now: () => Date); start(): void /* subscribes to "actions" */; drain(): Promise<{ applied: string[]; kept: string[] }>; dispose(): void; }` — one drain at a time (a drain asked while one runs runs once after it); per record L7 (handoff) or L8 (done); `ackActions` with `applied`; a record whose apply fails (offline `loadUntil`, a queue error) is kept for the next drain.
- `queuePost(configId, channelId, text, useModule, { clientUuid, maybeSentAt })`: the op keeps `clientUuid`; `maybeSentAt` → params `createSentAt = maybeSentAt`, `maybeSent: true`.

- [ ] **Step 1: Failing tests** (`chatPushActions.test.ts`, the mock native, the fake Odoo of `chatService.test.ts`): `a done reply shows in its conversation offline`; `a done reply is never sent by the outbox`; `a done read clears the conversation's unread count`; `a done mute patches the mute`; `a handoff reply is queued with the native uuid`; `a handoff reply maybe sent searches before posting` (the fake Odoo already holds the marked message: no `/mail/message/post`); `a drained reply whose uuid already has a message is skipped`; `a handoff read is sent with read receipts off`; `a handoff mute whose hour passed is dropped`; `a handoff 👍 loads its message then reacts`; `a handoff 👍 offline is kept for the next drain`; `an action of a removed account is acked and dropped`; `the actions event drains once while a drain runs`; `chatOutbox.test.ts`: `enqueue keeps a given client uuid`.
- [ ] **Step 2–3:** FAIL (pasted) → implement → PASS; `npm test`.
- [ ] **Step 4: Commit** (M): `[ADD] chat: native actions drained into the outbox and the cache`.

### Task 9: Kit, device hook, long tests with and without the module, device scenario

**Files:** M modify `src/testing/syncTestKit.ts` (`HARNESS_API = 7`; `pushNodeNative` gains an action store: `addAction(partial: Partial<NativeAction>)`, `actions`, `ackActions`; `SyncEnv` gains `pushActions: ChatPushActions`), `src/testing/pushNodeNative.ts`, `src/testing/deviceTestHook.ts` (`DEVICE_HOOK_API = 8`; `chatPushActions(): Promise<NativeAction[]>`, `chatPushDrain()`, `chatPushBreakSession(configId)` = `mirrorSession` with the sid `invalide`). E create `long_test/mobile_sync/chatPushModule.test.ts`, `long_test/mobile_sync/chatPushActions.test.ts`; modify `long_test/mobile_sync_odoo.py` (`HARNESS_API = 7`; `targets.json` gains `log`, the server's log file), `long_test/mobile_sync/harness.ts` (`Target.log?: string`), `long_test/mobile_sync/chatPeer.ts`, `long_test/mobile_sync/chatPushScene.ts` (`markedApp()`), `long_test/mobile_sync_device.py` (`DEVICE_HOOK_API = 8`, scenario), `test/test_mobile_sync_harness.py`.

**Interfaces:**
- `ChatPeer`: `browserSession(login): Promise<{ markRead(channelId, lastId): Promise<void>; presence(inactivityMs: number): Promise<void>; close(): void }>` (a fresh `/web/session/authenticate` and a bus websocket through `listen()`'s transport, sending `update_presence`); `markDeviceQuiet(creds, endpoint, quiet: boolean)`; `setMessageDone(login, messageId)`; `seenOf`, `muteOf(login, channelId)`, `reactionsOf` (lot 1/5's).
- `chatPushScene.markedApp()`: `linked()` with `chatModule: "auto"`, then waits for the device route.

Long tests (`eachVersionFrom(18, …)`):
- `chatPushModule.test.ts`: `a marked device gets the message id and channel type` (chat, group, channel mention); `an unmarked device gets Odoo's own payload` (`chatModule: "ignore"`, same server); `a marked device's push leaves no failed push line in Odoo's log` (`target.log` read before and after; skipped with its name saying why when absent); `reading in the browser sends a read push to the app device only` (a second device of admin, unmarked, on the other phone's prefix receives nothing); `the author's own post in the browser sends a read push`; `an inbox read sends inbox_done with the record` (inbox_user's comment on a task admin follows, then admin's `set_message_done` from the browser session); `quiet while a browser is online` (route with quiet true; browser presence 0 → chat_user's post reaches no app topic within 5 s; presence 31 min → it does; the app's own bus connected alone → it does).
- `chatPushActions.test.ts` (the kit's native as the phone; with and without the module): `a handoff reply posts once` (both modes); `a handoff reply that Odoo already holds posts nothing` (the message posted first with the record's uuid and marker, `sentAt` set: both modes); `a handoff read marks the conversation read with read receipts off`; `a handoff mute mutes for the hour left`; `a done reply's answer shows the message in the cache`.

Device scenario « actions du clavardage, app tuée » (18 only; module 1.5 on the run's server; preconditions and restoration as lot 1's « notifications du clavardage, app fermée », plus the conversation un-muted at the end):
1. the hook applies the link, level 1, « Autoriser http » on; `chatPushStatus` connected; the device marked (peer reads `erplibre_app`);
2. HOME; `am crash <pkg>`; chat_user posts → within 15 s the record of tag `chat:<configId>:<channelId>` lists four actions (`dumpsys notification --noredact`);
3. « Répondre » tapped at its bounds (`uiautomator dump`), the words typed (`input text`), sent → within 15 s exactly one message of admin with those words in the channel; 60 s later still one; the notification gone (read push of the author's post);
4. chat_user posts; « Marquer lu » → admin's `seen_message_id` is that message; the notification gone;
5. chat_user posts; « Muet 1 h » → the member's `mute_until_dt` ≈ now + 1 h; then un-muted by the peer;
6. chat_user posts; « 👍 » → one 👍 of admin on that message; the notification still there without « 👍 »;
7. chat_user posts; the peer's browser session of admin marks read → the notification gone within 15 s;
7b. lock screen « Jamais affiché » through the hook; HOME; chat_user posts → the record shows « Nouveau message » as title and text and lists four actions; « Répondre », words, sent → one message of admin with those words; the notification still « Nouveau message » until the read push removes it; lock screen back to « Masqué quand verrouillé »;
8. `chatPushBreakSession`; HOME; `am crash`; chat_user posts; « Répondre », words, sent → a `handoff:<configId>` notification; tapped → the app opens, drains, the message posted once (`--noredact` and the peer);
9. screenshots at 2, 3, 7b and 8 kept; the screen never turned off. Fallback recorded in the ledger only if step 3's tap-and-type cannot reach the RemoteInput field on this phone: a `-PsyncTest`-only receiver alias guarded by `android:permission="android.permission.DUMP"` (held by the shell, no app) fed by `am broadcast` with the same extras and a RemoteInput result.

- [ ] **Steps:** kit tests first (`src/__tests__/pushNodeNative.test.ts`: the action store lists done and handoff records, ack keeps the others) → RED pasted → write; harness unit tests (API 7 and 8, `log` in targets) → green; `./long_test/mobile_sync.py --versions 18 --filtre push` green ×3; `--filtre chat` green; full run green; `--appareil` green (the personal app's `lastUpdateTime` unchanged, `stay_on_while_plugged_in`, the allowlist, the reverses and the mute restored); `./gradlew --stop`; `--detruire`; durations (tap → message in Odoo at step 3, read in the browser → notification gone at step 7) in the ledger. Commits M `[ADD] testing: native actions in the kit and the device hook`, E `[ADD] long_test: chat push actions and module 1.5 on Odoo 18`.

### Task 10: Contracts, docs, changelogs, spec amendment

- [ ] `contracts/odoo-api.json`: `chat.push.actions` (the routes and `call_kw` of Task 4 with their answers, L2's idempotency, L3's dead-session trap, L4's bound, L5), `chat.push.module` (route `/erplibre_mobile_chat/push/device`, the fields, `options.data.erplibre`, the read and inbox_done payloads, after commit, 200 accepted, quiet while a browser is online and its timers); `chat.push.payload` gains the 1.5 shapes; `contracts/compatibility.json`: module `18.0.1.5.0` (one sentence per thing it adds; without it: no 👍, read found by date, no read push, Odoo logs ntfy's 200).
- [ ] M `README.base.md` « Notifications du clavardage » gains « Actions » (the four, per lock-screen mode, what needs module 1.5, the handoff notification and why the app does not open by itself); module `README.md` (A) already written in Tasks 1–2, checked; `long_test/README.base.md` gains the two files and the device scenario; ERPLibre and mobile `CHANGELOG.base.md`; the spec's « Decisions » sentence « An action whose session has expired opens the app » amended to L6's form, and the lot 2 line marked done; mmg (`mmg --yes README.base.md` in M, `make doc_markdown` in E); `check_comment_hygiene.py --staged` clean.
- [ ] Commits: E `[UPD] contracts: chat push actions and module 1.5`; E `[UPD] doc: chat push actions, long tests, spec, changelog`; M `[UPD] doc: chat notification actions, changelog`.
