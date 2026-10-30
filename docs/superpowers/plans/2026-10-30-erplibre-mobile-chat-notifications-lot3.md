# ERPLibre mobile chat notifications, lot 3 (preferences and battery) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** What rings on the phone follows Odoo's own settings, changed from
the app as from the browser, and a phone-side filter, quiet hours and a
browser-active choice that can only be stricter; the phone becomes more
economical by itself on battery saver and low battery, never switching
notifications off unless the user chose it, and says why; module
`erplibre_mobile_chat` 18.0.1.6.0 tells the app, per recipient, whether
the user is mentioned and whether a browser of theirs is active; the Google
Play justifications are written down.

**Architecture:** In A, the device mark becomes a mode (`ring|wait|quiet`)
and the app payload gains per-recipient `mentioned` and `browser_online`
(payload v 2, only for devices a 1.6 app marked). In M native code
(`ca.erplibre.home.chatpush`), pure JVM-tested classes decide the climb
(`BatteryClimber`), the filter (`PushFilter`), quiet hours (`QuietHours`)
and the browser-active hold (`HeldStore` of ciphertext messages, its own
timer); thin Android glue re-evaluates on power broadcasts and a plug-in
job. In M JS, one migration adds per-server columns, `ChatSettings` gains
the phone settings, everything is mirrored to native with the existing
mirror, Odoo's general and per-conversation settings go through the outbox.

**Tech Stack:** Odoo 18 (Python); Java 11, AndroidX, JobScheduler,
`BatteryManager` sticky intent; TypeScript, Owl 2, Capacitor 8, Vitest;
ntfy 2.34 and Odoo 18 in the long tests.

**Spec:** `docs/superpowers/specs/2026-10-28-erplibre-mobile-chat-notifications-design.md`
(lot 3 line of « Lots », « Decisions », « Controller's calls »,
« Constraints »). User decisions: `tasks/chat/p2-decisions.md`, last section
« The user's, lot 3 plan (2026-10-30) », binding and overriding the spec where
they differ. Lot 1 rulings R1–R11 and lot 2 rulings L1–L16 (cited « lot 2 Ln »)
stay in force. Recon with file:line: `tasks/chat/p2l3-recon-odoo.md`,
`p2l3-recon-js.md`, `p2l3-recon-native.md`, `p2l3-recon-tests.md`. Lot 2
ledger: `tasks/chat/p2l2-sdd/progress.md`. Conventions for every
implementer: `tasks/chat/p2l3-conventions.md`.

Repos, all on `dev/mobile_chat`, never switch, never push: **M** =
`mobile/erplibre_home_mobile`, **E** = the ERPLibre root, **A** =
`odoo18.0/addons/ERPLibre_erplibre_addons` (module `erplibre_mobile_chat/`).
Odoo sources cited as `mail/…`, `bus/…` live in `odoo18.0/odoo/addons/`.
Java classes without a package are in `ca.erplibre.home.chatpush`
(`android/app/src/main/java/ca/erplibre/home/chatpush/`, tests under
`android/app/src/test/java/ca/erplibre/home/chatpush/`, resources under
`android/app/src/test/resources/chatpush/`); `RT` = `android/app/src/realtime/java/ca/erplibre/home/chatpush/realtime/`,
`ST` = `android/app/src/synctest/java/ca/erplibre/home/chatpush/`.

## Rulings recorded here (the controller's calls and the builder's, inside the spec)

- **L1 Module 1.6 (C1).** `mail.push.device` gains `erplibre_browser_mode`
  Selection `ring|wait|quiet` (default `ring`) and `erplibre_payload_v`
  Integer (1 or 2); the Boolean `erplibre_quiet_while_online` goes, a
  post-migration (`migrations/18.0.1.6.0/post-migration.py`) mapping it to
  `quiet` / `ring` then dropping the column. Route
  `/erplibre_mobile_chat/push/device {endpoint, quiet_while_online=False, browser_mode=None}`:
  `browser_mode` given (one of the three, else `{"ok": false}`) sets the mode
  and payload v 2; absent (a 1.5 app), `quiet_while_online` maps to
  `quiet`/`ring` and payload v 1. A v 2 device's message payload is
  `options.data.erplibre = {"v": 2, "message_id", "channel_type", "mentioned", "browser_online"}`;
  a v 1 device keeps lot 2 L11's object byte for byte; read and inbox_done
  pushes stay v 1 for everyone. `mentioned` = the recipient partner is in
  `message.partner_ids` (`@everyone` included: `discuss_channel.py:727-730`
  puts every member there). `browser_online` = a browser of the recipient's
  user polled within `DISCONNECTION_TIMER` (65 s) and was active within
  `BROWSER_ACTIVE_S = 300` (the module's constant, used for the quiet drop
  too; Odoo's displayed status untouched); presence is written and read only
  for users holding a `wait` or `quiet` device (false otherwise). Truncation
  (`_truncate_payload`) runs once per version: the v 1 object exactly as lot 2,
  the v 2 object with both flags `false`, whose flags are then set per device
  (`true` is shorter than `false`, so no variant outgrows the 4096-byte
  record). A 1.5 server keeps 1.5 (quiet with Odoo's 30-min away delay, which
  the per-account card states; `wait` sends quiet false: ring at once). *Why:* the filter and the
  hold need only the payload, no mirror of Odoo settings, no extra request;
  v 1 kept for 1.5-marked devices so an app not yet updated keeps its 👍 and
  read-by-id (`PushPayload.parse` drops an object whose `v` ≠ 1). *Cost if
  wrong:* a per-device payload costs one dict copy per app device per post;
  the dropped column cannot be read back by a downgrade to 1.5.
- **L2 Phone-side filter per server (C2).** `filter` `all` (default) |
  `mentions_dm` | `none`, plus `inbox` (default on) and `inboxMentions`
  (default off, L13). A record/activity push passes iff `inbox`, or iff
  `inboxMentions` and the v 2 object says `mentioned`. A chat push: `all` passes; `none` drops; `mentions_dm`
  passes a `chat` or `group` always, a `channel` only when `mentioned` —
  without a v 2 object (no 1.6), or with an unknown type (no payload type, no
  mirrored type), it passes (fail open; the options say « filtre approximatif
  sans le module 1.6 »). Applied in `PushEngine.deliver` after the control
  pushes and the foreground check, and in `applySummary`: `none` draws no
  summary, `inbox` off counts only the chat share (`UnreadSummary` already
  counts a channel by its mentions only, so `mentions_dm` needs nothing
  there). `UnreadSummary` also follows Odoo's channel settings as Odoo's push
  domain does (`discuss_channel.py:595-620`): a channel whose member
  `custom_notifications` is `no_notif`, or `false` while the account's general
  value is `no_notif`, counts nothing; the general value reaches native as the
  per-account mirror key `channelNotifications` (L11), the per-channel value is
  already in the cached `/mail/data` (`discuss_channel.py:1016`). The JS badge
  still counts those channels: this is a push-only rule, said in the class
  comment. `none` keeps the registration (Odoo still pushes; only display
  stops). *Why:* the user's decision, and a filter can only be stricter than
  Odoo. *Cost if wrong:* `none` still spends a push per message.
- **L3 Browser active (C3).** One phone setting, `ring` | `wait` (default) |
  `quiet`, mirrored as `browserMode`; device mode = the setting on a 1.6
  server; on 1.5 `quiet_while_online = (mode == quiet)`; without the module
  nothing is sent. Changing it re-marks every account at 1.5+
  (`ChatPush.remarkAll`). Any mode but `ring` holds a chat push whose v 2
  object says `browser_online: true` and carries a `message_id` (under
  `quiet` such a push only comes while the server mark lags — a re-mark owed
  in memory, lost with the process — and holding is the closest to what the
  user asked; the card shows « pas encore appliqué sur ce serveur » while a
  mark is owed), for `HOLD_MS = 10 000`; a read push of that conversation with
  `last_message_id ≥` the held id drops it; otherwise it is drawn when due.
  `handle` passes `deliver` the due time: a streamed message is due at its
  receive time + `HOLD_MS`; a polled one at `m.time·1000 + HOLD_MS` clamped
  to `[now, now + HOLD_MS]` (a phone-to-ntfy clock skew can neither lengthen
  the hold nor skip it). The held entry is the raw ntfy message (id, topic,
  time, ciphertext body) in `HeldStore` — ciphertext, so no sealing — written
  inside `deliver`, before `handle`'s `finally` saves seen ids and cursor (a
  death in the window replays from the store, never drops). Release runs on a
  dedicated single-thread timer that `stopRealtime`'s `cancelAll` never
  touches, under its own wakelock `erplibre:chat-hold` (a `PushEngine.Wake`
  of its own, not the message wakelock, whose every `acquire` re-arms
  10 s and whose `release` at `inFlight == 0` would drop it at once),
  re-armed to `latestDue − now + 2 s` on each add, never shortened, released
  when the store is empty; the monotonic delay runs only while the CPU is
  awake; no exact alarm. **Release follows catch-up, never precedes it:** a
  link's held entries are released only after that link has caught up from
  its saved cursor — in the job after `runPeriod`'s poll; in realtime after a
  poll of that link since its cursor, run when the stream opens with entries
  pending (seen ids dedupe the stream's replay) — so a read push published
  while the process was dead drops the entry before any draw; the runtime
  constructor releases nothing. After catch-up the hold timer is armed for
  `latestDue()` when entries remain. `releaseDue` adds the ntfy id to the
  link's seen ids and saves them before drawing, so a replay never draws
  twice; an entry that cannot be decrypted at release (subscription gone,
  key changed) is dropped and counted in health `heldLost`, never silent. In
  a poll batch (levels 2-off-wifi to 4) messages are handled in order, so a
  read push in the same batch drops the held one; when an entry is not yet
  due, `runDue` blocks on an injectable `PushEngine.Sleeper` (the job keeps
  the system wakelock until `jobFinished`) until the latest due time (≤ 11 s),
  polls once more, then releases every remaining entry at once (no third
  wait; filter and quiet hours re-applied). *Why:* every trap of the native
  recon §3 closed by one mechanism. *Cost if wrong:* a held message is drawn
  up to 15 min late if the process dies in the window and no service runs.
- **L4 Automatic climbing (C4).** Native only (the WebView is dead when the
  battery changes). `BatteryClimber(auto, oneBelow, twoBelow)`: plugged →
  chosen; chosen 5 → 5; else `steps = !auto ? 0 : (two > 0 && pct < two) ? 2 : (one > 0 && pct < one) ? 1 : 0`
  (threshold 0 = none; each threshold follows its own label, « deux niveaux
  de plus sous » climbs two even alone or above the first), `level = min(chosen + steps, 4)`,
  saver → `max(level, 3)`; reason `saver` when the saver set the level, else
  `below_two`/`below_one` (steps) when `level > chosen`, else `""`. The reason
  is computed after `resolve`'s build mapping: no reason when the final level
  equals the unclimbed resolved level (a chosen 1–2 mapped to 3 by a build
  without realtime is no climb). Thresholds
  from {0, 10, 15, 20, 30, 40, 50}, defaults 30 and 15, switch on. Plugged =
  `EXTRA_PLUGGED ≠ 0` of the sticky `ACTION_BATTERY_CHANGED`, percentage
  `EXTRA_LEVEL·100/EXTRA_SCALE` (both readable from a job); `PowerState.charging`
  is renamed `plugged` and also serves level 2. The three `NO_CLIMB` sites
  (`ChatPushRuntime.java:429-432`, `:435-438`, `PushEngine.java:1083-1088`)
  take `BatteryClimber.of(settings.prefs())` together; `applyRealtime` hands
  the engine its Effective (`PushEngine.setEffective`), and
  `ChatPushRuntime.health()` computes `effective()` fresh and hands it in
  before the snapshot, so health is right at every level without a run.
  Re-evaluated by the running service on
  `ACTION_POWER_SAVE_MODE_CHANGED` and `ACTION_BATTERY_CHANGED` (re-read only
  when level, mode or reason change), by job 4823, and by one-off job
  `ChatClimbJob` 4825 (`setRequiresCharging(true)`, its run is
  `ChatPushJob.apply`). 4825 is decided by the pure
  `ChatClimbJob.wanted(Effective e, boolean realPlugged)` = climb reason
  non-empty and not really plugged, where `realPlugged` is read from the
  sticky intent BEFORE `TestPower.over` (the door overrides the level only,
  never this schedule: a test phone on USB power would otherwise run 4825 at
  once and re-schedule it in a loop). `ChatClimbJob.sync` is called from
  `ChatPushJob.apply`/`run` (its OFF branch included, which cancels) and from
  `applyRealtime` (the service climbing on a broadcast stops itself; 4825 must
  be pending then). Health gains `climbReason`. The cap keeps the cursor
  younger than ntfy's cache, so no replay rule is needed. *Why:* stateless, so service, job and health agree
  after any death; never silent unless chosen (spec failure line). *Cost if
  wrong:* ≤ 15 min lag climbing down when the plug-in job is deferred.
- **L5 Battery tests (C5).** The `-PsyncTest` door gains kind `power`
  (extras `plugged`, `saver`, `pct`, or `clear`), writing the synctest-only
  `TestPower` file; main code reads it by class name (`ca.erplibre.home.chatpush.TestPower`,
  as `RealtimeHost` finds the service), absent from every other build. The
  door branches on kind `power` before its tag check (a power broadcast has
  no tag); extras parse in the pure `TestPower.fromExtras`. The override is
  cleared at the start and at the end of every device run. Real
  `dumpsys battery` / `cmd power set-mode` only behind
  `--batterie-reelle`, which refuses to start when `pm list packages
  ca.erplibre.home` shows the personal app (that marks the personal phone);
  it records `settings get global low_power` and `settings get system
  screen_off_timeout`, raises the timeout for the run (unplugged, `svc power
  stayon usb` no longer keeps the screen on, and a PIN lock blocks the run),
  then `dumpsys battery unplug` (Android refuses the saver while plugged),
  `dumpsys battery set level 12` → effective 3 `below_two` and 4825 pending in
  `dumpsys jobscheduler`, `cmd power set-mode 1` at 80 % → 3 `saver`;
  `rendre()` restores in `finally`, in order: `cmd power set-mode` and
  `low_power` to the recorded values, `dumpsys battery reset`, the timeout.
  The personal app `ca.erplibre.home` is never touched. *Cost if wrong:* the
  sticky-intent read is proven on the phone only with the option.
- **L6 Quiet hours (C6).** Per server `quiet {on, from, to}` (minutes from
  local midnight, defaults off, 1320 → 420); inside `[from, to)` (crossing
  midnight when `from > to`; `from == to` is refused by the UI and never
  inside natively) chat, inbox and summary notifications are posted with
  `Shown.silent = true` (`ChatNotifier.java:234`), never dropped. Local time
  from `Calendar` with the default `TimeZone` (no `java.time`, minSdk 24),
  injected for tests. *Cost if wrong:* a heads-up alert still shows on
  Android versions that ignore `setSilent` for a high-importance channel.
- **L7 Odoo's settings from the app (C7).** General
  `res.users.settings.channel_notifications`, which Odoo applies to channels
  only (field help `res_users_settings.py:22`; the push domain lets every chat
  and group through): the app shows it as « Canaux (réglage d'Odoo) » with
  the help line « Les discussions et les groupes sonnent toujours ; pour les
  faire taire, utilisez la sourdine », `all` /
  `mentions` / `no_notif`, and writes `false` for `mentions` (writing
  `"mentions"` there is an invalid selection value); read from
  `get_session_info` (`storeData.Store.settings`) at each load with lot 1's
  stale guard (`channel_notifications_at` as `global_mute_at`), followed on
  the bus `res.users.settings` independently of `mute_until_dt`. Per
  conversation `custom_notifications` (`all|mentions|no_notif|false` = default)
  only for `channel`; chat and group offer mute only (Odoo ignores the
  setting there); a browser change reaches the app by the bus
  `mail.record/insert` echo Task 0 captures. Writes are outbox kinds `chat.notify` and
  `chat.global_notify` beside mute, applied locally at once, coalesced per
  target, sent to `/discuss/settings/custom_notifications` (no answer
  expected, lot 2 R2-T0a); fixtures from Task 0's captures on a harness-owned
  Odoo 18. *Cost if wrong:* a stale bus value shows until the next load.
- **L8 Battery exemption (C8).** `BatteryExemption.requestExemption(Context)`
  fires `ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` with `package:<id>`
  (the permission is declared, `AndroidManifest.xml:284`), falling back to
  the list on `ActivityNotFoundException`; the SMS gateway keeps the list.
  The options box « refused » is recomputed from `batteryExempt()` when the
  app resumes (`App` `appStateChange` active), not read right after opening
  the dialog. Refused → the cost and « utiliser le niveau 3 ». The in-app
  `Dialog.confirm` before the request goes (the system dialog asks; two
  questions in a row). The `openBatterySettings` javadoc (« Google la
  refuse ») is rewritten to point at `doc/GOOGLE_PLAY` (Play's acceptable
  use). *Cost if wrong:* Play may ask why the direct request is used (L9
  writes it).
- **L9 Google Play justifications (C9).** New M doc `doc/GOOGLE_PLAY.base.md`
  (mmg header `multilingual suffix: en, fr`, as `doc/*.base.md`), linked from
  `doc/README.base.md`. It states plainly that **no Play-ready build exists
  yet**: `-PnoChatRealtime` removes only `ChatPushService`, while the main
  manifest keeps `SmsGatewayService` (specialUse), `SEND_SMS`/`RECEIVE_SMS`,
  the call-log permissions, `SCHEDULE_EXACT_ALARM` and
  `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` in every build. It lists what a Play
  variant must remove (the SMS gateway sources and manifest entries, SMS and
  call-log permissions, `SCHEDULE_EXACT_ALARM`, and the battery-exemption
  permission when realtime is absent, by `tools:node="remove"`) as an open
  gap. The user's round 4 Play build drops levels 1–2: it needs neither the
  specialUse service nor the exemption. The specialUse FGS (real-time
  messaging from the user's own server, no FCM) and exemption (Play's
  acceptable use: real-time messaging that cannot use FCM) justifications are
  given only for a build that keeps levels 1–2, with « Play may refuse it ».
  POST_NOTIFICATIONS, boot receiver, exact alarms (SMS gateway only; chat uses
  none), cleartext (loopback only by default — `localhost`, `127.0.0.1`,
  `10.0.2.2` in `network_security_config.xml` — `-PlanCleartext` never for
  distribution). Each permission the doc names is checked against the merged
  manifest of `assembleDebug -PnoChatRealtime`. The SMS comments saying Play
  « does not apply » stay (they describe the gateway, outside Play).
- **L10 Folded leftovers (C10).** Task 1: the ≈ 115 `chat_channels` rows
  rewritten per load (lot 3 adds columns on that path). Cause: Odoo stamps
  each member channel's `message_unread_counter_bus_id` /
  `message_needaction_counter_bus_id` with the current `bus_last_id`
  (`discuss_channel.py:960-1011`), which moves between any two loads, and
  `gateCounter` (`chatRepository.ts:172-195`) always takes an authoritative
  read's bus id. Ruling: a load (`/mail/data`) writes the row marks as 0 —
  the load's bus id already lives in `chat_sources.counterBusId`
  (`chatService.ts:470`), set in the same account queue — and the bus gate
  compares with `max(row mark, source counterBusId)`; other authoritative
  answers keep writing their bus id; a database reset still works (the load
  rewrites the marks and the source id). *Cost if wrong:* a channel whose
  counter came by bus is rewritten once at the next load. The flaky
  `chatRealtime` « first connection keeps the counters load read » is a 20 s
  timeout on « the replay applied » under parallel load (progress.md:202,
  :216): that wait gets 60 s, the strict counter `expect` stays right after
  it. The long press (« recherche et boîte ») re-checked in Task 10's device
  runs. Task 9:
  `chatPushOpen.ts:149` tests `effectiveLevel`. Task 11: README « a later
  version » sentences (M `README.base.md:534-535`, `:651-652`). Left as
  follow-ups: resume load queued behind a running load, one read per row, a
  deleted message flashing once.
- **L11 Storage (C11).** One M migration `2026103001`: `chat_push` gains
  `phone_filter TEXT NOT NULL DEFAULT 'all'`, `inbox_notify INTEGER NOT NULL DEFAULT 1`, `inbox_mentions INTEGER NOT NULL DEFAULT 0`,
  `quiet_on INTEGER NOT NULL DEFAULT 0`, `quiet_from INTEGER NOT NULL DEFAULT 1320`,
  `quiet_to INTEGER NOT NULL DEFAULT 420`; `chat_sources` gains
  `channel_notifications TEXT`, `channel_notifications_at TEXT`. Phone
  settings in `ChatSettings` (`climbAuto`, `climbOneBelow`, `climbTwoBelow`,
  `browserMode`). All mirrored by `publishNow`, plus the per-account
  `channelNotifications` (Odoo's general value, from `ChatSourceState`, L2).
  `HARNESS_API` 8, `DEVICE_HOOK_API` 9.
- **L12 The climb switch governs the thresholds only (builder's call).**
  Battery saver means level 3 at least even with the switch off (the user's
  words: « battery saver always means level 3 at least »; Android's saver
  restricts background network, so 1–2 under saver would promise what it
  cannot keep). *Cost if wrong:* a user who turned the switch off still sees
  level 3 under saver — one line in `BatteryClimber`.
- **L13 Inbox off, record mentions by choice (the user's decision,
  2026-10-30).** Inbox off drops every record and activity push by default,
  a record mention included (« un 100 %, c'est non »); a separate per-server
  switch `inboxMentions` (default off, shown under the inbox switch when it
  is off) lets a record push through when its v 2 object says `mentioned`.
  Without 1.6 flags such a push is dropped (the user turned the inbox off;
  the switch's help line says « avec le module 1.6 »). The chat filter
  governs conversations only. *Cost if wrong:* one branch in `PushFilter`.

## Global Constraints

- Everything in the project 1, lot 1 and lot 2 Global Constraints still holds (Odoo 18 only for chat; one commit per task per repo; `[TYPE] scope: subject` ≤ 72 chars in English; bilingual body EN then `--- FR ---`, ≤ 8 lines per language; `Assisted-by:`; never an AI in `Co-authored-by:`; files named at `git add`, never `-A`, never `-N`).
- **One migration in M**, `2026103001` (L11). Module **18.0.1.6.0**, level key `("1.6", "1.6")` appended to `erplibre_chat_level`; `ChatModuleLevel` gains `"1.6"`, `CURRENT_LEVEL = "1.6"`.
- Climbing never reaches 5 unless the user chose 5; job 4823 is never cancelled for a climbed level.
- French labels fixed here: filter « Tout ce qu'Odoo envoie » / « Mentions et messages directs » / « Rien de ce serveur », « Boîte de réception (enregistrements et activités) », « filtre approximatif sans le module 1.6 », under it « Sonner quand même si on me mentionne dans un enregistrement » with help « avec le module 1.6 »; browser « Sonner tout de suite » / « Attendre 10 s » / « Ne pas envoyer au téléphone », « pas encore appliqué sur ce serveur », on 1.5 « Ne pas envoyer : sur ce serveur (module 1.5), jusqu'à 30 min après votre dernière activité dans le navigateur »; « Économiser automatiquement », « Un niveau de plus sous », « Deux niveaux de plus sous », « aucun »; « Heures calmes », « de {from} à {to} »; « En ce moment : niveau {level} ({why}) », why « économiseur de batterie » / « batterie sous {pct} % »; Odoo « Canaux (réglage d'Odoo) » : « Tous les messages » / « Mentions seulement » / « Rien », help « Les discussions et les groupes sonnent toujours ; pour les faire taire, utilisez la sourdine », per conversation « Par défaut ({value}) ».
- Native code calls no new Odoo route; Odoo settings are written by the JS outbox only.
- The held store holds ciphertext only; no message text, token or session is logged.
- No exact alarm in chat code (L3); `SCHEDULE_EXACT_ALARM` stays the SMS gateway's.
- `HARNESS_API` 7 → 8 (`src/testing/syncTestKit.ts:76`, `long_test/mobile_sync_odoo.py:58`) and `DEVICE_HOOK_API` 8 → 9 (`src/testing/deviceTestHook.ts:35`, `long_test/mobile_sync_device.py:64`), in Task 10.
- Phone: Android 11, PIN — never lock; only `ca.erplibre.home.synctest`; no phone-wide battery or power change unless `--batterie-reelle`; restore everything (`tasks/chat/p2l3-conventions.md`).
- Never the Odoo servers on 8016–8018 nor the ntfy on 8080: Task 0 and the long tests use harness-owned servers only.

## Review Focus

1. **The process dies inside the 10 s hold** (swipe, OOM, climb stopping the service): the message is drawn after the next catch-up unless its read push came — including a read push published while the process was dead and replayed from the cursor — never lost, never doubled (Task 6 `a held message survives a restart and is drawn when due`, `a read push replayed at restart drops the held message`, `a released message is not drawn twice after a replay`).
2. **A low battery on a phone set to level 3 or 4:** level 4 at most, the 15-min job still scheduled, back to the chosen level once plugged, health saying why (Task 4 `climbing never reaches 5 unless chosen`, `plugged returns to the chosen level at any percentage`).
3. **Mixed versions:** a 1.5 app on a 1.6 server keeps v 1 payloads and its 👍; a 1.6 app on a 1.5 server never sends `browser_mode` (the 1.5 route would refuse the unknown argument) and `wait` rings at once (Task 2 `test_device_marked_without_browser_mode_gets_v1_payload`; Task 7 `a 1.5 server gets quiet_while_online only`).
4. **Nothing undecidable is dropped:** no 1.6 flags, an unknown channel type or a v 3 object → shown; a held entry that cannot be decrypted at release → dropped but counted in health `heldLost` (Task 5 `without the 1.6 flags a channel push passes`, `an unknown type passes`; Task 3 `a v3 object is ignored as unknown`; Task 6 `a held entry that cannot be decrypted at release is counted`).
5. **The general setting « mentions » and a load racing a browser change:** written as `false`, read back as « mentions », a bus change newer than the load's start wins (Task 8 `mentions is written as false`, `a load older than a bus change keeps the bus value`).

---

## File Structure

Each task's **Files** block is the authority. In short: **A** gains
`migrations/18.0.1.6.0/post-migration.py` and extends `controllers/push.py`,
`models/mail_push_device.py`, `models/mail_thread.py`, `models/res_users.py`,
`models/ir_websocket.py`, `tools/app_push.py`, `models/mail_message.py`, tests
`test_app_push.py`, `test_read_push.py`. **M** gains in `chatpush/`
`PhonePrefs.java`, `PhoneFilter.java`, `BrowserMode.java`, `BatteryClimber.java`,
`PushFilter.java`, `QuietHours.java`, `HeldStore.java` (pure, JVM-tested),
`ChatClimbJob.java` (glue), `ST/TestPower.java`; on the JS side
`src/components/options/chat_notifications/options_chat_push_account_component.ts`
(the per-account card, extracted). **E** gains
`long_test/mobile_sync/chatPushPrefs.test.ts` and a device scenario.

---

### Task 0: Live capture of Odoo's settings shapes (spike, no phone)

Task 8 (and Task 7's `chat_sources` columns) are not built until Task 0's checks pass and their outcomes are in `tasks/chat/p2l3-sdd/ledger.md`; Tasks 1–6 proceed independently, Task 1 first (C10), except Task 5's two `UnreadSummary` Odoo-settings tests, which wait for `mail_data_settings.json`.

**Files:** spike `tasks/chat/p2l3-sdd/spike/settings.py` (`.venv.erplibre/bin/python -I`, `requests` and the lot 2 bus listener as model); shapes to `tasks/chat/p2l3-sdd/shapes/`.

**Interfaces:**
- Produces for Tasks 5, 7, 8: `session_info_{all,mentions,no_notif}.json`; `custom_notifications_general.json`, `custom_notifications_channel.json` (route answers, verbatim JSON-RPC bodies); `general_mentions_string_error.json`; `bus_settings_channel_notifications.json` (the `res.users.settings` notification as a second session's bus receives it); `bus_record_insert_custom_notifications.json` (consumed by Task 8's browser-to-app test); `mail_data_settings.json` (whether `/mail/data` carries `channel_notifications` — the two recons disagree — and a member channel with `custom_notifications: "no_notif"`).

- [ ] **Step 1: Start** a harness-owned Odoo 18: `./long_test/mobile_sync.py --versions 18 --filtre smoke --garder` (URL and database in `targets.json`; never 8016–8018).
- [ ] **Step 2: Capture** as `admin` with a cookie-only session and a second bus session listening: `get_session_info` after each general value (`all`, `false`, `no_notif`); `/discuss/settings/custom_notifications` without `channel_id` (each value) and with a channel's id (`all`, `mentions`, `no_notif`, `false`); the general setting written `"mentions"` (expect an error); the two bus notifications; `/mail/data {init_messaging: {}, channels_as_member: true}` (with one channel set to `no_notif`, for Task 5's `UnreadSummary` case); a channel's setting changed by admin's browser session, the app session's bus receiving the `mail.record/insert`; `chat_user` (the harness user, never admin: an author is never notified) posts with `special_mentions: ["everyone"]` in a channel where admin is a member and admin's general setting is `false`: admin's `mail.notification` row and push are read.
- [ ] **Step 3: Checks to the ledger:** (a) `false` reads back `false` in session info; (b) `"mentions"` on the general setting fails; (c) the per-channel route works on a member channel and answers no `result`; (d) the bus `res.users.settings` payload carries `channel_notifications` with the record id; (e) `@everyone` counts as a mention for every member (L1's `mentioned`). Outcome: (a), (c), (d) as expected → go; otherwise STOP and report (L7 rests on them).
- [ ] **Step 4:** mask hosts/ports per the conventions; `./long_test/mobile_sync.py --detruire`.

### Task 1: Folded leftovers — rows rewritten per load, flaky realtime test (M, E)

**Files:** M `src/services/chat/chatRepository.ts` (`gateCounter` `:172-195`, `channelRow` `:539-540`, `putChanged` `:504`, `:854`), `src/services/chat/chatStore.ts` (`:304`, `:346`) and `src/services/chat/chatService.ts` (bus gate `:327`, `:2113`) as L10 rules, tests `src/__tests__/chatRepository.test.ts` / `chatService.test.ts` (where loads are driven). E `long_test/mobile_sync/chatRealtime.test.ts:90-98`.

- [ ] **Step 1: Failing tests** `a second load differing only in the counter bus ids writes no chat_channels row` (two `/mail/data` answers identical but for `message_unread_counter_bus_id` / `message_needaction_counter_bus_id`, as Odoo stamps them; a recording database counts `chat_channels` writes on the second: 0); `a bus counter older than the latest load is still refused` (id between the two load ids); `a load after a bus counter takes the read`. RED pasted.
- [ ] **Step 2: Fix per L10** (load marks 0, bus gate `max(row mark, source counterBusId)`), never by skipping the write of a changed value; GREEN; `npm test`.
- [ ] **Step 3: Flaky test:** `until("the replay applied", …, 60_000)`, the strict `expect(unreadCounter).toBe(peer's)` kept right after it; run `./long_test/mobile_sync.py --versions 18 --filtre chat` twice green.
- [ ] **Step 4: Commits** M `[FIX] chat: an unchanged load rewrites no conversation row`; E `[FIX] long_test: first connection test waits for the replayed counters`.

### Task 2: Module 1.6 — device mode, per-recipient flags, payload v 2 (A)

**Files:** A create `migrations/18.0.1.6.0/post-migration.py`; modify `controllers/push.py`, `models/mail_push_device.py` (`APP_FIELDS`), `models/mail_thread.py` (`_erplibre_app_payload`, `_erplibre_drop_quiet`, `_erplibre_push_to_app`), `models/res_users.py` (`BROWSER_ACTIVE_S`), `models/ir_websocket.py:45` (gate), `models/mail_push.py` (per-row payload unchanged), `tools/app_push.py` (`MESSAGE_PAYLOAD_VERSION = 2`, `PAYLOAD_VERSION = 1` kept for read/inbox_done), `models/mail_message.py:77` (selection + `("1.6", "1.6")`), `__manifest__.py` (`18.0.1.6.0` and the `description` of what app notifications carry: the two flags and the device mode), `i18n/fr_CA.po`, `README.md` (« Notifications de l'application »), tests `tests/test_app_push.py`, `tests/test_read_push.py`. Capture `tasks/chat/p2l3-sdd/spike/module16_shapes.py` → `shapes/push16_{chat,group,channel_plain,channel_mention,channel_everyone,record,v1_device,chat_browser_online,group_browser_online}.json`.

**Interfaces:**
- Route per L1: `erplibre_push_device(self, endpoint, quiet_while_online=False, browser_mode=None) -> {"ok": bool}`.
- `mail.push.device`: `erplibre_browser_mode` Selection `[("ring","Ring"),("wait","Wait"),("quiet","Quiet")]` default `ring`; `erplibre_payload_v` Integer default 1; both in `APP_FIELDS` (cleared on partner change).
- `mail.thread._erplibre_app_payloads(message, msg_vals, devices) -> dict[int, str]` — device id → payload JSON per L1 (v 1 or v 2 with flags); `_erplibre_push_to_app` sends those (postcommit under `MAX_DIRECT_PUSH`, `mail.push` rows above).
- `res.users._erplibre_browser_online_users()` uses `BROWSER_ACTIVE_S = 300`; `_erplibre_drop_quiet` drops `quiet` devices only.
- `post-migration.py`: `migrate(cr, version)` — the SQL mapping of L1, `DROP COLUMN IF EXISTS`.

- [ ] **Step 1: Failing tests.** `test_app_push.py`: `test_level_selection_ends_with_1_6` (replaces `_1_5`, `:128`); `test_route_with_browser_mode_sets_mode_and_v2`; `test_route_without_browser_mode_maps_quiet_and_v1`; `test_route_refuses_an_unknown_mode` (`{"ok": false}`, row unchanged); `test_device_marked_without_browser_mode_gets_v1_payload` (exactly lot 2's object, on a 4000-char body so the per-version truncation shows); `test_v2_payload_flags_mentioned_per_recipient` (a channel post mentioning Bruno: his device `mentioned: true`, Alice's `false`, one post); `test_everyone_counts_as_mentioned` (`special_mentions: ["everyone"]`); `test_chat_and_group_payload_not_mentioned_without_mention`; `test_record_comment_payload_has_flags`; `test_browser_online_true_for_a_wait_device_with_an_active_browser`; `test_browser_online_false_after_five_minutes_inactive` (presence 301 s); `test_ring_device_has_browser_online_false_and_no_presence_written`; `test_v2_payload_with_long_body_fits` (4000 accented chars, both flags true and false: each encoded payload ≤ the limit); `test_migration_maps_quiet_to_mode` (the old column re-added in the test transaction, `migrate` run, modes asserted). `test_read_push.py`: `test_presence_written_for_wait_and_quiet_devices_only`; `test_quiet_device_dropped_while_browser_active_five_minutes`; `test_wait_device_never_dropped`; `test_read_push_stays_v1`.
- [ ] **Step 2–4:** FAIL (pasted) → implement → PASS (the 120 existing green, adapted only where `quiet_while_online` was asserted); black, ruff, isort; `dropdb chat_module_test`.
- [ ] **Step 5: Capture** on a kept harness Odoo 18 with the branch's module upgraded (`-u erplibre_mobile_chat`), lot 2's spike as the model: one v 2 device (route with `browser_mode: "wait"`) and one v 1 device; then a cookie browser session of the recipient sends a presence update (as `chatPushModule.test.ts:182-184`, `peer.browserSession(…).presence(0)`) for the two `*_browser_online` shapes; decrypt and save the nine shapes listed; `--detruire`. Ledger: the plaintexts.
- [ ] **Step 6: Commit** (A): `[ADD] erplibre_mobile_chat: device mode, mention and browser flags`.

### Task 3: Native mirror of the lot 3 settings, payload v 2 (M, Java)

**Files:** M create `chatpush/PhonePrefs.java`, `PhoneFilter.java`, `BrowserMode.java`; modify `src/data/featureCatalog.ts` (`chat.notifications.native`), `AccountView.java`, `PushSettingsStore.java` (`put` `:54`, `accountJson`/`accountOf` `:182-215`), `ChatPushRuntime.java` (`publishSettings` `:252-273`), `J/ChatPushPlugin.java` (`publishSettings` `:148-166`), `PushPayload.java`; tests `PushSettingsStoreTest.java`, `PushPayloadTest.java`; resources `push16_*.json` (Task 2's captures).

**Interfaces:**
- `enum PhoneFilter { ALL, MENTIONS_DM, NONE; String key(); static PhoneFilter fromKey(String k) /* ALL on unknown */ }`, keys `all`, `mentions_dm`, `none`. `enum BrowserMode { RING, WAIT, QUIET; key(); fromKey /* WAIT */ }`.
- `final class PhonePrefs { final boolean climbAuto; final int oneBelow, twoBelow; final BrowserMode browserMode; static final PhonePrefs DEFAULT /* true, 30, 15, WAIT */; static PhonePrefs of(JSONObject mirror) /* climb {auto, oneBelow, twoBelow}, browserMode; a threshold outside {0,10,15,20,30,40,50} → its default */ }`.
- `AccountView` gains `final PhoneFilter filter; final boolean inbox; final boolean inboxMentions; final boolean quietOn; final int quietFrom, quietTo; final String channelNotifications /* "all" | "mentions" | "no_notif" | null */;` — a 6-argument constructor `(…, module, AccountPrefs p)`, with `AccountPrefs { filter, inbox, inboxMentions, quietOn, quietFrom, quietTo, channelNotifications; static final AccountPrefs DEFAULT }`; the 4- and 5-argument constructors keep defaults.
- `PushSettingsStore.put(int level, boolean allowHttp, PhonePrefs prefs, Map<String,String> strings, List<AccountView> accounts)`; `PhonePrefs prefs()`; JSON keys per account `filter`, `inbox`, `inboxMentions`, `quiet: {on, from, to}`, `channelNotifications`; a store written by lot 2 reads back the defaults.
- `ChatPushRuntime.publishSettings(int level, boolean allowHttp, PhonePrefs prefs, Map<String,String> strings, JSONArray accounts)`.
- `PushPayload` gains `final boolean flags /* v 2 object read */; final boolean mentioned; final boolean browserOnline;` — `v` 1 or 2 read as the message object (lot 2's fields), flags only from 2; control pushes still require 1.

- [ ] **Step 1: Failing JUnit:** `PushSettingsStoreTest` `the phone prefs round trip`, `a lot 2 store reads the default prefs and account prefs`, `an unknown filter or threshold reads as its default`; `PushPayloadTest` `a v2 push carries mentioned and browser online` (each captured shape, the `*_browser_online` ones for `true`), `a v1 push from a 1.6 server has no flags but its message id`, `a v3 object is ignored as unknown`.
- [ ] **Step 2–4:** FAIL (pasted) → implement → PASS; `./gradlew --stop`.
- [ ] **Step 5: Commit** (M): `[ADD] chat push: phone and server preferences mirrored natively`.

### Task 4: Automatic climbing, power reads, test power door (M, Java + glue)

**Files:** M create `chatpush/BatteryClimber.java`, `chatpush/ChatClimbJob.java`, `ST/TestPower.java`; modify `PushLevelPolicy.java` (`PowerState.plugged`, `Climb`, `LevelClimber`, `Effective.climbReason`), `ChatPushRuntime.java` (`effective()` `:429`, `effective(Context)` `:435`, `powerState` `:453-477` (also the real plugged state), `applyRealtime` `:390` (`setEffective`, `ChatClimbJob.sync`), `health()` `:341` (fresh effective)), `PushEngine.java` (`snapshot` `:1083-1088`, `setEffective`), `HealthSnapshot.java` (`climbReason`), `ChatPushJob.java` (`apply` incl. its OFF branch, `run`: `ChatClimbJob.sync`), `RT/ChatPushService.java` (receiver `:182-198`), `ST/ChatTestDoor.java` (kind `power` before the tag check), `AndroidManifest.xml` (job service), `featureCatalog.ts` (`chat.notifications.native`); tests `PushLevelPolicyTest.java`, `BatteryClimberTest.java`, `ChatClimbJobTest.java`, `HealthSnapshotTest.java`, `PushEngineTest.java` (`level(int)` helper `:339-341`), `TestPowerTest.java`.

**Interfaces:**
- `PushLevelPolicy`: `PowerState(boolean wifi, boolean plugged, boolean saver, int batteryPct)`; `static final class Climb { final int level; final String reason; }`; `interface LevelClimber { Climb climb(int chosen, PowerState s); }`; `NO_CLIMB` returns `(chosen, "")`; `Effective` gains `final String climbReason`.
- `final class BatteryClimber implements LevelClimber { BatteryClimber(boolean auto, int oneBelow, int twoBelow); static BatteryClimber of(PhonePrefs p); static boolean differs(Effective a, Effective b) /* level, mode or reason */ }` — L4, L12.
- `PushEngine.setEffective(PushLevelPolicy.Effective e)`; the snapshot fallback uses `BatteryClimber.of(settings.prefs())`.
- `HealthSnapshot` JSON `climbReason`: `"saver" | "below_one" | "below_two" | null`.
- `ChatClimbJob` (`JOB_ID = 4825`): pure `static boolean wanted(Effective e, boolean realPlugged)` (`!e.climbReason.isEmpty() && !realPlugged`); `static void sync(Context c, Effective e, boolean realPlugged)` schedules or cancels by it; `onStartJob` → `ChatPushJob.apply`. `realPlugged` is the sticky intent's, read before `TestPower.over` (L4).
- `ChatPushRuntime.health()` computes `effective()` and hands it to the engine before the snapshot.
- `TestPower` (synctest only): `static PowerState over(Context c, PowerState real)`; pure `static PowerState apply(Map<String, String> stored, PowerState real)` and `static Map<String, String> fromExtras(Map<String, String> extras)` (null when malformed). Door kind `power`, branched before the tag check: extras `plugged`, `saver` (booleans), `pct` (int), or `clear=true`; stores, then `ChatPushJob.apply` and `RealtimeHost.stop` (re-read); result `"sent"`.

- [ ] **Step 1: Failing JUnit:** `BatteryClimberTest` table — `plugged returns to the chosen level at any percentage`; `one level more under the first threshold`; `two levels more under the second`; `climbing never reaches 5 unless chosen` (3 at 10 % → 4; 4 at 5 % → 4; 5 → 5); `saver means level 3 at least` (1 → 3 reason saver; 3 → 3 reason ""); `saver applies with the switch off, thresholds do not`; `a threshold of none never climbs`; `the second threshold alone climbs two levels` (none / 15, at 12 % → +2); `each threshold follows its own label when the pair is inverted` (15 / 30: 20 % → +2, 12 % → +2; 30 / 15 at 20 % → +1); `the reason names what set the level`; `BatteryClimber.differs ignores a percentage change inside a band`. `PushLevelPolicyTest` climber tests adapted to `Climb`; `level 2 is realtime when plugged`; `a build clamp is no climb` (chosen 1, no realtime build, 20 % with thresholds off → 3, reason ""). `ChatClimbJobTest`: `scheduled while climbed and unplugged`; `cancelled when plugged or at the chosen level`; `not wanted for a build clamp`. `PushEngineTest` `health reports the effective level handed in realtime`, `health carries the climb reason`, `health after a power change reports the fresh level and reason without a run`. `TestPowerTest` `an override replaces plugged, saver and percentage, keeps wifi`, `clear returns the real state`, `the door reads a power broadcast without a tag` (`fromExtras`).
- [ ] **Step 2–3:** FAIL (pasted) → implement → PASS (`./gradlew :app:testDebugUnitTest`).
- [ ] **Step 4: Builds:** `assembleDebug`, `assembleDebug -PnoChatRealtime`, `-PsyncTest`; `aapt2 dump xmltree`: `ChatClimbJob` present in all, `TestPower` class absent from the two non-synctest APKs (`unzip -l` + `dexdump` grep); `./gradlew --stop`.
- [ ] **Step 5: Commit** (M): `[ADD] chat push: climbing on battery saver and low battery`.

### Task 5: Phone-side filter and quiet hours in the engine (M, Java)

**Files:** M create `chatpush/PushFilter.java`, `QuietHours.java`; modify `src/data/featureCatalog.ts` (`chat.notifications.native`), `PushEngine.java` (`deliver` `:594-628`, `applySummary` `:768-790`, constructor or setter for `LocalTime`), `UnreadSummary.java` (`chat`, `inbox`, Odoo's channel settings per L2), `ChatPushRuntime.java` (the Calendar `LocalTime`); tests `PushFilterTest.java`, `QuietHoursTest.java`, `PushEngineTest.java`, `UnreadSummaryTest.java`.

**Interfaces:**
- `final class PushFilter { static boolean allows(AccountView a, PushPayload p) }` — L2; the type is `p.channelType`, else the mirrored `a.channels.get(p.resId).type`.
- `final class QuietHours { static boolean inside(int from, int to, int minuteOfDay) }` — L6.
- `PushEngine.LocalTime { int minuteOfDay(long epochMs); }`, `void setLocalTime(LocalTime t)`; the runtime's reads `Calendar.getInstance(TimeZone.getDefault())` at each call.
- `UnreadSummary` gains `final int chat; final int inbox;` with `total == chat + inbox`.

- [ ] **Step 1: Failing JUnit:** `PushFilterTest` (on the captured `push16_*` and `push_module_*` shapes): `all lets every push through`; `none drops chat and inbox`; `mentions_dm lets chat and group through`; `mentions_dm drops a channel push without mention`; `mentions_dm lets a mentioned channel push through`; `without the 1.6 flags a channel push passes`; `an unknown type passes`; `inbox off drops a record push and keeps chat`; `inbox off drops a mentioned record push by default` (L13); `inbox off with record mentions lets a mentioned record push through`; `inbox off with record mentions drops an unmentioned record push`; `record mentions without the 1.6 flags drop the record push`. `QuietHoursTest`: `quiet hours cross midnight`; `the edges are from inclusive, to exclusive`; `equal bounds are never inside`. `PushEngineTest`: `a filtered push draws nothing and still advances the cursor`; `a read push applies on a server set to nothing`; `inside quiet hours the notification is posted silently`; `an inbox notification inside quiet hours is posted silently` (captured record push); `the zone is read at each post` (the `LocalTime` fake changes between two posts); `a server set to nothing gets no summary`; `inbox off leaves the inbox share out of the summary`; `the summary inside quiet hours is silent`. `UnreadSummaryTest` `chat and inbox shares add up to the total` (on `mail_data_counters.json`); `a channel set to nothing in Odoo counts nothing`; `a default channel counts nothing when the general setting is nothing` (both on Task 0's `mail_data_settings.json`).
- [ ] **Step 2–4:** FAIL (pasted) → implement → PASS; `./gradlew --stop`.
- [ ] **Step 5: Commit** (M): `[ADD] chat push: per-server filter, inbox switch, quiet hours`.

### Task 6: Browser-active hold (M, Java)

**Files:** M create `chatpush/HeldStore.java`; modify `src/data/featureCatalog.ts` (`chat.notifications.native`), `PushEngine.java` (`handle` passes the due time to `deliver`, READ branch `:613-616`, `poll` batch end `:551`, `runPeriod` `:253`, `runDue` with `Sleeper`, release after catch-up, `HoldTimer`, hold `Wake`), `HealthSnapshot.java` (`heldLost`), `ChatPushRuntime.java` (dedicated hold executor, wakelock `erplibre:chat-hold`, no release at construction); tests `HeldStoreTest.java`, `PushEngineTest.java` (`HandScheduler` `:61-84` as the hold timer, a recording fake `Wake`, a fake `Sleeper`).

**Interfaces:**
- `final class HeldStore { HeldStore(KeyValue kv, LongSupplier clock); void add(String linkUrl, NtfyMessage m, String configId, long channelId, long messageId, long dueAt); int dropRead(String configId, long channelId, long lastMessageId); List<Held> due(long now); List<Held> of(String linkUrl); long latestDue(); boolean isEmpty(); void remove(String ntfyId); static final int MAX = 200 /* oldest released first beyond */; }`, `Held { linkUrl, message, configId, channelId, messageId, dueAt }`; `commit()`ed writes.
- `PushEngine.HoldTimer { void at(Runnable r, long delayMs); }`, `setHoldTimer(HoldTimer)`; `PushEngine.Sleeper { void sleep(long ms) throws InterruptedException; }`, `setSleeper(Sleeper)`; `setHoldWake(Wake)` with `Wake.acquire(long timeoutMs)` added (the message wakelock keeps `acquire()`); `static final long HOLD_MS = 10_000`; `void releaseDue(String linkUrl, boolean all)` — run after that link's catch-up (L3): each due entry (every entry when `all`) has its ntfy id saved as seen, then is re-delivered with the hold skipped (filter and quiet hours re-applied, foreground → nothing), then removed; then the hold timer is armed for `latestDue()` if entries remain.
- Hold condition (L3): `prefs.browserMode != RING && p.isChat() && p.flags && p.browserOnline && p.messageId > 0`.

- [ ] **Step 1: Failing JUnit:** `HeldStoreTest`: `a held message is stored as ciphertext only` (no plaintext of the test payload in any raw value); `dropRead removes held ids up to the read point only`; `due lists entries by due time`. `PushEngineTest` (true branch on the `push16_*_browser_online` captures): `wait holds a push whose browser is online`; `a read push within the wait drops the held push` (nothing drawn); `a held push is drawn when due`; `a push without browser online rings at once`; `ring mode never holds`; `a quiet phone holds a push the server still sent`; `a push without 1.6 flags rings at once`; `stopRealtime does not drop a held push` (the hold timer still fires); `the hold takes its own wakelock and a later message does not shorten it` (fake `Wake`: `acquire(12 000)`, a second message leaves the deadline, release only once the store is empty); `a polled message is due from its ntfy time, clamped to the hold`; `a held message survives a restart and is drawn when due` (new engine on the same stores: nothing at construction, drawn after the link's catch-up, the timer armed for the entries not yet due); `a read push replayed at restart drops the held message` (new engine, the fake ntfy returns the read push first: nothing drawn); `a released message is not drawn twice after a replay` (released, then the stream replays the same ntfy id: one draw); `a held entry that cannot be decrypted at release is counted` (`heldLost`); `a poll batch drops a message whose read follows in the batch`; `a fresh message in a poll is waited for and polled once more` (fake `Sleeper`; the second poll brings the read: nothing drawn); `entries still fresh after the second poll are released before the job ends`; `a held push released in the foreground draws nothing`.
- [ ] **Step 2–4:** FAIL (pasted) → implement → PASS; `assembleDebug` both variants; `./gradlew --stop`.
- [ ] **Step 5: Commit** (M): `[ADD] chat push: wait for a browser read before ringing`.

### Task 7: JS settings, migration, mirror, device mode (M, JS)

**Files:** M modify `src/services/chat/chatSettings.ts`, `src/services/databaseService.ts` (`addChatPushPrefs`), `src/services/migrations/index.ts` (entry `2026103001`, « Clavardage : préférences de notification »), `src/models/chat.ts` (`ChatPushRow` `:373-386`, `ChatSourceState`), `src/services/chat/chatRepository.ts` (`pushRow`/`setPushRow` `:1926-1971`, source state), `src/services/chat/chatModule.ts` (`"1.6"`), `src/services/chat/chatService.ts` (`features` `:679-691`: `pushFlags`), `src/services/chat/chatPush.ts` (`markAppDevice` `:632-660`, setters, `publishNow` `:750-789`), `src/plugins/chatPushPlugin.ts`, `src/__mocks__/chatPushNative.ts` (settable `effectiveLevel`, `climbReason`); tests `chatSettings.test.ts`, `migrations.test.ts`, `chatModule.test.ts`, `chatPush.test.ts`, `chatPushPlugin.test.ts`.

**Interfaces:**
- `ChatSettings` gains `climbAuto: boolean; climbOneBelow: ClimbThreshold; climbTwoBelow: ClimbThreshold; browserMode: BrowserMode;` with `type ClimbThreshold = 0 | 10 | 15 | 20 | 30 | 40 | 50` (0 = none), `type BrowserMode = "ring" | "wait" | "quiet"`; defaults `true, 30, 15, "wait"`, invalid stored values read as defaults.
- `ChatPushRow` gains `filter: PhoneFilter; inboxNotify: boolean; inboxMentions: boolean; quietOn: boolean; quietFrom: number; quietTo: number;` (`type PhoneFilter = "all" | "mentions_dm" | "none"`); `ChatSourceState` gains `channelNotifications: OdooNotify | null; channelNotificationsAt: string | null;` (`type OdooNotify = "all" | "mentions" | "no_notif"`, used by Task 8).
- `ChatPush.setFilter(configId, filter: PhoneFilter, inbox: boolean, inboxMentions: boolean)`, `setQuietHours(configId, q: { on: boolean; from: number; to: number })` (rejects `from === to` when on), `setClimb(c: { auto: boolean; oneBelow: ClimbThreshold; twoBelow: ClimbThreshold })`, `setBrowserMode(mode: BrowserMode)` → `remarkAll()`; all inside `run()`, each ending with a publish.
- `markAppDevice`: level ≥ 1.6 → `{ endpoint, browser_mode }`; 1.5 → `{ endpoint, quiet_while_online: mode === "quiet" }`.
- Mirror (`PushSettingsMirror`): `climb: { auto, oneBelow, twoBelow }`, `browserMode`; each `PushAccountMirror`: `filter`, `inbox`, `inboxMentions`, `quiet: { on, from, to }`, `channelNotifications` (null until Task 8 fills `ChatSourceState`) — the JSON Task 3 parses. `ChatPush.markOwed(configId): boolean` read by Task 9's card. `PushHealth` gains `climbReason: "saver" | "below_one" | "below_two" | null`.

- [ ] **Step 1: Failing tests:** `chatSettings.test.ts` `the phone push settings default and validate`; `migrations.test.ts` `2026103001 adds the push preference columns with their defaults` (and is idempotent on a database that has them); `chatModule.test.ts` level matrix `[["1.5","1.5"],["1.6","1.6"]]` → 1.6, a 1.5 server outdated with `appPush` true and `pushFlags` false; `chatPush.test.ts`: `a 1.6 server gets the browser mode`; `a 1.5 server gets quiet_while_online only`; `changing the browser mode marks every 1.5 and 1.6 account again`; `an account without the module is never marked`; `the mirror carries the phone and server preferences`; `equal quiet bounds are refused`; `a renamed account keeps its preferences` (`renameChatRows`).
- [ ] **Step 2–3:** FAIL (pasted) → implement → PASS; `npm test`.
- [ ] **Step 4: Commit** (M): `[ADD] chat: push preferences stored, mirrored, device mode marked`.

### Task 8: Odoo's notification settings in the app (M, JS)

**Files:** M modify `src/services/odoo/odooRpcClient.ts` (`sessionInfo` `:405-430`), `src/services/chat/chatStore.ts` (`ChatStoreDelta` `:34`), `src/services/chat/chatService.ts` (load `:411-423`, bus `:2153-2158`, `setNotify`, `setGlobalNotify`), `src/services/chat/chatRepository.ts` (source state), `src/services/chat/chatOutbox.ts` (kinds `:122-124`, `ACTION_KINDS` `:286-288` (handler registration `:573`), sets `:312`, `:322`, apply `:1893-1904`, `runAction` channel-less guard `:3471` (`CHAT_GLOBAL_NOTIFY` beside `CHAT_GLOBAL_MUTE`), send `:3505-3526`), `chatPush.ts` (mirror `channelNotifications` from the source state), `src/components/options/chat/options_chat_component.ts` (beside the global mute `:70-92`), `src/components/chat/chat_info_component.ts` (section after mute `:155-163`), `src/i18n/en.ts`, `fr.ts` (incl. notices `chat.action_notify`, `chat.action_global_notify` beside `:1037-1047`); tests `chatService.test.ts` (fixture `:1681` replaced by the capture), `chatOutbox.test.ts`, `optionsChatComponent.test.ts`, `chatInfoComponent.test.ts`.

**Interfaces:**
- `SessionInfo.channelNotifications: OdooNotify` (`false` → `"mentions"`), renewed by a fresh read as `globalMuteUntil`.
- `ChatStoreDelta.channelNotifications?: OdooNotify | null`; `applyDelta(…, { fromBus: true })` stamps `channelNotificationsAt`.
- Outbox: `CHAT_NOTIFY = "chat.notify"` params `{ value: OdooNotify | null }` (null = default) — `MEMBER_ONLY`, `USER_ACTIONS`, channel type `channel` only; `CHAT_GLOBAL_NOTIFY = "chat.global_notify"` params `{ value: OdooNotify }`; both coalesced per target. Sent to `/discuss/settings/custom_notifications`: the general one as `{ custom_notifications: value === "mentions" ? false : value }` (no `channel_id`), the per-channel one as `{ custom_notifications: value ?? false, channel_id }` (`mentions` is valid on a member).
- `ChatService.setNotify(configId, channelId, value: OdooNotify | null)`, `setGlobalNotify(configId, value: OdooNotify)`.

- [ ] **Step 1: Failing tests:** `chatService.test.ts`: `the general setting is read from the session info`; `the bus channel_notifications updates the general setting without a mute`; `a load older than a bus change keeps the bus value`; `a browser change of a channel's setting reaches the conversation chooser` (captured `mail.record/insert`); `the general setting reaches the native mirror`; `chatOutbox.test.ts`: `mentions is written as false`; `a general notify op is sent without a channel and never given up as vanished`; `a per-channel setting is sent with the channel id`; `default sends false for the channel`; `a chat or group never queues a notify op`; `two notify ops on one target coalesce`; `the setting is applied locally at once and survives a refusal as given up`; components: `the general setting chooser per server says it governs channels only` (title and help line), `the conversation chooser shows for a channel only`, `a chat shows mute only`.
- [ ] **Step 2–3:** FAIL (pasted) → implement → PASS; `npm test`, `npm run build`.
- [ ] **Step 4: Commit** (M): `[ADD] chat: Odoo notification settings read and changed from the app`.

### Task 9: Notification options screen, effective level, battery exemption (M, JS + plugin)

**Files:** M create `src/components/options/chat_notifications/options_chat_push_account_component.ts` (+ `.scss` if needed; the per-account card moved out of the 507-line component); modify `options_chat_notifications_component.ts` (global climbing and browser blocks, status line, exemption on resume), `src/services/chat/chatPushOpen.ts:149`, `J/BatteryExemption.java` (`requestExemption`; `openBatterySettings` javadoc `:44-53` rewritten, L8), `J/ChatPushPlugin.java` (`requestBatteryExemption` `:340-346`), the in-app confirm `options_chat_notifications_component.ts:288-291` dropped, `src/i18n/en.ts`, `fr.ts`, `featureCatalog.ts` (leaf `chat.notifications.settings` `:5712`: description and file); tests `optionsChatNotifications.test.ts`, `chatPushOpen.test.ts`.

**Interfaces:**
- Card component props `{ card: AccountCard; push: ChatPush; native: ChatPushNative | null; pushFlags: boolean }`; it owns the lock-screen chips, filter chips, inbox switch and, while it is off, the record-mentions switch, quiet hours (switch + two `<input type="time">`), and the line of what browser mode applies (1.6 full; 1.5 « quiet » only, with Odoo's 30-min away delay stated, « wait » rings at once; none: rings at once), plus « pas encore appliqué sur ce serveur » while `push.markOwed(configId)`.
- `listeningOf` returns off on `h.effectiveLevel === 5`.
- Status line `chat.push_effective` when `climbReason` is non-null (a build clamp has none and shows no line), why from it (`below_*` names the threshold).
- `exemptionRefused` = chosen level ≤ 2, realtime build, asked once in this screen, and `!(await native.batteryExempt()).exempt` read on `appStateChange` active (and on mount).

- [ ] **Step 1: Failing tests:** `optionsChatNotifications.test.ts`: `the filter, inbox and record-mentions switches reach the push service`; `the record-mentions switch shows only while the inbox is off`; `quiet hours are saved and equal bounds are refused`; `the climbing switch and thresholds are saved`; `the browser mode is saved and each card says what applies` (1.5 card with the 30-min line; an owed mark shown); `the effective level and its reason are shown when climbed`; `no status line when effective differs without a climb reason`; `the direct exemption request asks no in-app question first`; `a refused exemption is shown only once the app resumes not exempt`; `returning exempt hides the refusal`; `chatPushOpen.test.ts` `an effective level 5 reads as off`.
- [ ] **Step 2–3:** FAIL (pasted) → implement → PASS; `npm test`, `npm run build`; `assembleDebug`; `./gradlew --stop`.
- [ ] **Step 4: Commit** (M): `[ADD] chat: notification preferences screen, effective level, exemption`.

### Task 10: Kit, device hook, long tests, device scenario (M, E)

**Files:** M `src/testing/syncTestKit.ts` (`HARNESS_API = 8`), `src/testing/pushNodeNative.ts` (records the new mirror; `status()` takes a settable `effectiveLevel`/`climbReason`), `src/testing/deviceTestHook.ts` (`DEVICE_HOOK_API = 9`; `chatPushFilter(configId, filter, inbox, inboxMentions)`, `chatPushQuietHours(configId, q)`, `chatPushBrowserMode(mode)`, `chatPushClimb(c)`, `chatGlobalNotify(configId, value)`, `chatNotify(configId, channelId, value)`), tests `pushNodeNative.test.ts`, `syncTestKit.test.ts:29`. E create `long_test/mobile_sync/chatPushPrefs.test.ts`; modify `long_test/mobile_sync_odoo.py:58`, `long_test/mobile_sync/chatPeer.ts` (`generalNotifyOf(login)`, `setGeneralNotify(session, value)`, `customNotifyOf(login, channelId)`, `setChannelNotify(session, channelId, value)`, `appDevice` `:240-245` reads `erplibre_browser_mode`/`erplibre_payload_v` and returns `mode` and `payloadV` (1.6 drops `erplibre_quiet_while_online`), `markDeviceQuiet` kept as the 1.5 alias call), `long_test/mobile_sync/chatPushScene.ts`, `long_test/mobile_sync/chatPushModule.test.ts` (`:75`, `:179-180`: assertions on `mode`, route with `browser_mode`), `long_test/mobile_sync_device.py` (`DEVICE_HOOK_API = 9`, scenario, `--batterie-reelle` per L5), `test/test_mobile_sync_harness.py` (guard tuple `:1469-1472`, battery guard, `--batterie-reelle` refusal and restore).

Long tests (`chatPushPrefs.test.ts`, `eachVersionFrom(18, …)`, harness ntfy): `the general setting set in the app reaches Odoo` (each value; `mentions` stored `false`); `the general setting changed in the browser reaches the app`; `a channel's setting changed in the browser reaches the app`; `a channel set to mentions in the app pushes no plain post`; `a group ignores the channel setting`; `the browser mode set in the app marks the device` (mode and v 2); `a 1.5 route call marks quiet and keeps v1`; `mentioned and browser_online in the payload` (mention, `@everyone`, plain; presence 0 → true, 6 min inactive → false).

Device scenario « préférences du clavardage, app fermée » (18 only; door mode; preconditions and restoration as lot 2's, plus the door power override cleared at start and end):
1. link, level 1, « Autoriser http »; device marked `wait` (peer);
2. filter « Rien de ce serveur »: chat_user posts → no notification in 15 s (`notifications()`, filtered to the test package); « Mentions et messages directs »: a plain channel post → none; a mention → shown; a group post → shown; inbox off: a record comment → no `inbox:` notification; record mentions on: a record comment mentioning admin → shown, a plain one → none;
3. « Attendre 10 s »: the peer's browser session of admin active; chat_user posts, the browser marks read within 5 s → no notification for 15 s; chat_user posts, no read → the notification appears between 9 and 15 s; « Sonner tout de suite » → within 3 s;
4. quiet hours covering now → the test package's record shows the silent alert (group alert behaviour / alerted field, names discovered through `notifications()` only, never a raw dump in the ledger); window off;
5. climbing by the door: `power pct=12 plugged=false` → `chatPushStatus` effective 3, reason `below_two`, the permanent notification gone; `dumpsys jobscheduler` for the test package: 4825 not run in a loop (no run count growing over 10 s; the phone stays on USB power); the test app's notification options opened through CDP show « En ce moment : niveau 3 (batterie sous 15 %) », screenshot of that screen; `plugged=true` → effective 1, service back; `saver=true plugged=false pct=80` → 3 `saver`; `clear`;
6. under `--batterie-reelle` only, L5's real branch (4825 pending after `dumpsys battery unplug`); screenshots at 5 only; screen never off.

- [ ] **Steps:** kit tests RED → pasted → GREEN; harness unit tests (API 8/9; the new scenario in the guard tuple; `dumpsys battery`, `cmd power`, `low_power` absent from the scenario's source unless under the `--batterie-reelle` branch; `--batterie-reelle refuses a phone holding the personal app`; `rendre restores the battery and power state when --batterie-reelle ran`, in L5's order) → green; `./long_test/mobile_sync.py --versions 18 --filtre push` ×3 green; `--filtre chat` green; full run green; `--appareil` ×3 (« recherche et boîte » green 3/3, else ledger and controller; the personal app's `lastUpdateTime` unchanged; everything restored); `./gradlew --stop`; `--detruire`; hold durations (post → notification with and without the read) in the ledger. Commits M `[ADD] testing: push preferences in the kit and the device hook`, E `[ADD] long_test: chat push preferences, module 1.6, climbing door`.

### Task 11: Contracts, docs, Play justifications, changelogs, spec amendment

- [ ] `contracts/odoo-api.json`: `chat.push.module` (route params `browser_mode` and the alias, the two fields, payload v 2 and its flags, 5-min activity), `chat.push.payload` (v 2 shapes), new `chat.settings.notify` (`/discuss/settings/custom_notifications` with and without `channel_id`, `false` for mentions, the general value governing channels only, bus `res.users.settings` and `mail.record/insert` echoes); `contracts/compatibility.json`: module `18.0.1.6.0` (what 1.6 adds; without it: channel messages pass the « mentions » filter, « wait » rings at once, « quiet » uses the 30-min away delay with 1.5).
- [ ] M `doc/GOOGLE_PLAY.base.md` per L9, row in `doc/README.base.md`; M `README.base.md` « Chat notifications »: Odoo's settings changed from the app, the phone filter, quiet hours, browser-active choice, climbing and its reasons; the « later version » sentences (`:534-535`, `:651-652`) replaced; A `README.md` checked (Task 2); E `long_test/README.base.md` (« The chat push tests »: the new file, the scenario, the door power and `--batterie-reelle`); E and M `CHANGELOG.base.md`; the spec's « Lots » lot 3 line marked « (done) » with module 1.6 added, « Battery thresholds by default » amended to L4/L12 (cap at 4, list of thresholds, each threshold its own label, switch), « Browser-active choices » to L3 (one phone setting, 5-min activity), « Phone-side filter choices » to L2/L13 (chat and group always, channel when mentioned, fail open without 1.6, inbox off absolute unless the record-mentions switch, L13), the « Quiet hours » decision to L6 (silent, never dropped, inbox included, one window per server crossing midnight); `doc/GOOGLE_PLAY` permissions checked against `aapt2 dump xmltree` of the `assembleDebug -PnoChatRealtime` merged manifest; mmg (`mmg --yes README.base.md`, `mmg --yes doc/GOOGLE_PLAY.base.md`, `mmg --yes doc/README.base.md` in M; `make doc_markdown` in E); `check_comment_hygiene.py --staged` clean.
- [ ] Commits: E `[UPD] contracts: chat notification settings and module 1.6`; E `[UPD] doc: chat push preferences, long tests, spec, changelog`; M `[ADD] doc: Google Play justifications, chat push preferences`.
