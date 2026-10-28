# ERPLibre mobile: chat notifications while the app is closed

**Status:** draft for project 2 of the mobile chat
(`2026-10-25-erplibre-mobile-chat-design.md`, project 1 done in five lots).
**Builds on:** the chat of `erplibre_home_mobile` (accounts per Odoo 18
server, store of conversations, outbox, module `erplibre_mobile_chat` 1.4),
the SMS gateway's foreground service, the ntfy installer of `todo.py`.

## Intent

Project 1 made the app the team's messenger, but only while it is open: a
message sent to someone whose app is closed waits until they happen to open
it. Project 2 makes the phone ring, as a messenger does, without giving the
messages to anyone else: Odoo encrypts each notification for the phone, the
user's own ntfy server carries it without being able to read it, and the
phone decrypts it. No Firebase, no third-party relay.

Two things set it apart from a plain push integration:

- **Confidentiality per server.** Some Odoo servers are confidential, others
  are not. What a notification shows, and when, is chosen per server.
- **Battery as a choice, not a gamble.** The user picks how reactive the
  phone is, from realtime to off, and the app becomes more economical by
  itself when the battery needs it.

## Success

- With the app closed (swiped away, phone locked, after a reboot), a message
  posted in Odoo rings the phone within a few seconds at level 1.
- The notification can be answered, marked read, muted for an hour or given a
  👍 without opening the app; nothing is lost, nothing is done twice.
- A conversation read in the browser stops ringing on the phone at once (with
  the module).
- The settings that decide what rings are Odoo's own: changing them on the
  phone changes them in the browser, and back.
- Nobody but Odoo and the phone can read a notification: ntfy only sees
  ciphertext and random topic names.

## Failure, even if it technically works

- A notification lost silently while the user believes the phone is listening
  (the service is dead and nothing says so).
- A confidential server's message text on a locked screen.
- A reply sent twice, or a reply typed in a notification that vanishes.
- The battery visibly drained at a level the user chose as economical.
- The phone ringing for a conversation the user is reading in the browser,
  when they asked it not to.
- Notifications that disagree with Odoo's settings (rings for a muted
  conversation).

## Decisions (the user's)

- **ntfy is the user's own**, installed by `script/install/install_ntfy.sh`
  (access denied by default). Project 2 works and is tested with an ntfy on
  the local network over http (the app's « Autoriser http » switch); a public
  https ntfy for production Odoo servers comes with project 3.
- **ntfy access:** one ntfy user per phone, read-only, authenticated by a
  token the app receives by QR code or typed; Odoo publishes without an
  account, write-only, on `up…` topics. The payload is end-to-end encrypted
  by Odoo (Web Push, RFC 8291) anyway.
- **ntfy setup is a `todo.py` command**, « Préparer ntfy pour ERPLibre
  mobile », on the local machine or over ssh: rights, phone user, token,
  shown as a QR code. Project 3 reuses it.
- **What rings is decided by Odoo's own settings** (Discuss general setting:
  all / mentions / nothing; per conversation: custom notifications and mute),
  which the app reads and changes, so the browser and the phone agree. On top
  of them, a **phone-side filter per server** that can only be stricter (the
  phone cannot ring what Odoo does not push).
- **Comments on followed records and assigned activities ring by default**,
  as Odoo pushes them, in their own Android channel « Boîte de réception »,
  separate from the chat; tapping one opens the item in the app's inbox.
- **Lock screen, per server.** Three choices: hidden when locked (default for
  a new server: « Nouveau message — <server> » on the locked screen, author
  and text once unlocked), never shown (always « Nouveau message », even
  unlocked), always shown.
  « Hidden when locked » is guaranteed, by the user's decision: when Android
  hides sensitive content on the lock screen, the notification shows
  « Nouveau message — <server> » there; when Android shows all content, or the
  app cannot read that setting, the notification does not appear on the lock
  screen at all and shows normally once unlocked. The decision is taken at
  each post: a notification drawn while Android hid content keeps that form if
  the user later changes the Android setting, until it is posted again.
- **Five levels, from the most reactive to the most economical:**
  1. realtime (permanent connection);
  2. realtime on Wi-Fi or while charging, otherwise every 15 minutes;
  3. every 15 minutes;
  4. every hour;
  5. off.

  The user picks a level. The app climbs to more economical levels by itself
  when Android's battery saver turns on or the battery drops under thresholds
  the user sets, and comes back down to the chosen level when charging.
- **Actions in the notification:** reply, mark as read, mute 1 h, react 👍.
- **Native code may keep an encrypted copy of each account's Odoo session**
  (Android Keystore), never the password. An action whose session has expired
  opens the app, which signs in again and sends it.
- **Read elsewhere:** the ERPLibre module (next level, 1.5) sends a silent
  « read » push to the app's devices so the phone removes its notification at
  once; without the module, the notification goes at the next check or when
  the app opens.
- **While the user is active in a browser,** the phone's behaviour is a
  setting on the phone (choices below, under « Left to the builder » for the
  default).
- **Levels 3 and 4 check ntfy** (one request per ntfy) when ntfy is
  configured, and Odoo directly for an account without ntfy.
- **Checking Odoo directly gives one summary per server**, « N nouveaux
  messages — <server> », from the unread counters, never marking anything
  read in Odoo; a tap opens the conversation list. This covers an account
  without ntfy (checked every 15 minutes at levels 1 to 4) and the catch-up
  after a silence longer than the ntfy cache.
- **ntfy per account, shared when the same.** Each Odoo account chooses its
  ntfy (one QR per ntfy); accounts on the same ntfy share one connection.
  Accounts of different organisations may use different ntfy servers, one
  connection each.
- **« Marquer lu » is an explicit gesture:** it marks the conversation read
  in Odoo even when the app's automatic read receipts are off.
- **Quiet hours:** Android's Do Not Disturb is the default answer; per-server
  quiet hours may be offered as an optional setting on the phone, off by
  default.
- **Levels 1 and 2 ask for the battery optimisation exemption** when chosen;
  refused, the app says what it costs and offers level 3.
- **Google Play later.** The app is installed by APK today, but nothing in
  project 2 may close the door to Google Play: the permanent service, the
  battery exemption request and the permissions must each be justifiable
  under Play's policies, with the justification written down. If Play ever
  refuses the permanent service, the Play build drops levels 1 and 2 and
  keeps 3 to 5; the direct APK keeps all five. The service is built so that a
  build variant can leave it out without touching the rest.
- **iOS later:** the alert transport stays abstract so APNs can replace ntfy
  on iOS; no iOS work in project 2.

## Controller's calls (the user may overrule)

- **One connection per distinct ntfy** (ntfy carries up to 150 topics on
  one subscription); one secret topic per Odoo account, under a random prefix
  per phone and per ntfy, so that adding an account on a known ntfy needs no
  server command.
- **Two URLs when they differ.** The QR carries the URL the phone uses and,
  optionally, the URL Odoo uses to reach the same ntfy (Odoo in a VM or a
  container, `adb reverse` in the device tests); the endpoint registered in
  Odoo is the latter when given. The `todo.py` command asks for it.
- **The ntfy keepalive is not changed** by the `todo.py` command: the server
  may serve other clients (the official ntfy app breaks above about 70 s).
- **The notes poll's existing ntfy fields** keep serving the notes; the chat
  setting is per account, and the builder may reuse those fields where they
  mean the same thing.
- **One notification per conversation**, messages stacked (MessagingStyle);
  one Android channel per server for chat and one for its inbox, so sound and
  vibration are tuned in Android per server.
- **Battery thresholds by default:** one level more under 30 %, two under
  15 %; battery saver on means level 3 at least. Charging returns to the
  chosen level.
- **The permanent notification** exists only at levels 1 and 2, at minimal
  priority. The user sees at most one permanent notification from the app,
  even with the SMS gateway running.
- **While the app is in the foreground,** no system notification: project 1's
  in-app indicator is enough.
- **Tokens never expire**; the `todo.py` command also revokes a phone.
- **Phone-side filter choices per server:** everything Odoo pushes; mentions
  and direct messages only; nothing from this server; plus a switch for the
  inbox (records and activities).
- **Browser-active choices:** ring at once; wait a few seconds (10 s by
  default) and drop the notification if the « read » push arrives meanwhile;
  ask the module not to push to the phone while a browser of the user is
  online. Default: wait 10 s (falls back to ring at once without the module).

## Constraints found in Odoo 18, ntfy 2.34 and the app

Facts from the recon (`tasks/chat/p2-recon-odoo.md`, `p2-recon-ntfy.md`,
`p2-recon-mobile.md`, not versioned); file and line references are there.

**Odoo 18 Web Push**
- Devices are `mail.push.device` rows registered by
  `register_devices(endpoint, keys, vapid_public_key)`; Odoo does not update
  the keys of an endpoint the partner already registered, so a key change
  means a new topic, or unregister then register. Any logged-in user can
  register. A missing VAPID parameter makes Odoo generate a new key pair and
  wipe every device (restored or neutralised database).
- Any http or https endpoint is accepted (only `.invalid` hosts are refused).
- With fewer than 5 devices among the recipients, Odoo pushes inside the
  posting request, before the commit, with a 5 s timeout per device: an
  unreachable ntfy slows each post, and the phone may receive a push before
  the message is readable over RPC.
- One attempt, no retry; only 404/410 remove a device. Success is 201 only;
  anything else is logged with the endpoint, i.e. the secret topic.
- The payload has `title`, `options.body` (plain text, at most 4096 bytes
  before encryption), `options.icon`, `options.data.{model, res_id, action}`:
  no message id, no channel type.
- Odoo pushes only from `_notify_thread` (posted messages, notify, scheduled
  messages): never for reads, calls, reactions, edits, deletions.
- Odoo does not skip users who are online; only the browser hides its own
  notification. Chat and group pushes ignore the per-conversation setting;
  only mute stops them. Comments on followed records push to users with the
  email preference too.
- Fetching messages (`/discuss/channel/messages` without `around`,
  `/mail/thread/messages`) marks the user's Inbox entries done: a background
  fetch must never do that.
- Settings routes: `/discuss/settings/custom_notifications`,
  `/discuss/settings/mute` (minutes; -1 until unmuted); the general setting in
  `res.users.settings`.
- Odoo's service worker shows every push it receives: a silent push sent to a
  browser device would show an empty notification. `mail.push.device` cannot
  tell the app's devices from browsers today.
- Read hook: `discuss.channel.member._set_last_seen_message` covers
  mark-as-read and the author's own post; inbox reads go through
  `set_message_done` / `mark_all_as_read`.

**ntfy 2.34**
- `Content-Encoding: aes128gcm` switches ntfy to UnifiedPush mode: the binary
  body comes back base64 (`"encoding":"base64"`), never as an attachment. TTL
  and the VAPID header are ignored; Odoo publishes as anonymous.
- ntfy answers 200, never 201: without the module every successful push logs
  an Odoo warning carrying the topic.
- Bodies over 4096 bytes are cut silently; Odoo's largest encrypted body is
  4096 today, no margin.
- `visitor-subscriber-rate-limiting` must stay off (a read-only phone would
  make every push fail). The Odoo server counts as one visitor (burst 60, then
  one request every 5 s) unless exempted; a 429 is a lost push.
- Write access on `up*` also allows deleting or clearing a topic: the topic
  name is its only protection.
- A poll without `since`, or with an unknown id, returns the whole cache
  (12 h here): the app deduplicates by message id. A phone silent longer than
  the cache loses those pushes and must catch up from Odoo.
- A token carries all its user's rights; per-phone scope comes from the
  user's ACL (`<prefix>*` read-only).
- The installer sets no ACL, no phone user, no token, and runs locally only;
  the ssh helpers of `todo.py` can be reused. `.venv.erplibre` has no QR
  library.

**The app**
- The SMS gateway's `SmsGatewayService` is the template: `specialUse`
  foreground service, START_STICKY, boot and update receiver, 15-minute
  watchdog, exact elapsed-time alarms, short wakelocks, network callback,
  battery level and charging reads, battery-exemption opener. Nothing reads
  battery saver yet.
- `@capacitor/local-notifications` actions always open the app: chat
  notifications are built natively (NotificationCompat, BroadcastReceiver,
  RemoteInput).
- The four actions are plain JSON routes with the session cookie
  (`/mail/message/post`, `/discuss/channel/mark_as_read`,
  `/discuss/settings/mute`, `/mail/message/reaction`); OkHttp and the
  JVM-tested `ChatFileTransfer` show how native code calls Odoo. The JS
  outbox cannot be driven from native code (in-memory lock, cached rows, no
  headless JS).
- The chat settings and « Autoriser http » live in the WebView's
  localStorage, global, unreadable from Java: whatever native code needs is
  mirrored by the JS into native storage (the `NoteSyncPlugin` pattern). LAN
  http also needs the cleartext APK build flag.
- An ntfy SSE client and per-application ntfy columns exist for the notes
  poll (foreground only, first application only).
- No crypto library is a direct dependency; RFC 8291 decryption is native
  (the WebView is dead when it matters), plain JCA plus HKDF, testable on the
  JVM with the RFC's test vector. Per-account key pairs are software keys
  (minSdk 24) wrapped by the Keystore.
- Java tests: JUnit 4 and MockWebServer, no Robolectric. JS: Vitest,
  `HARNESS_API` 5, `DEVICE_HOOK_API` 6; long tests in `long_test/mobile_sync*`.

## Lots

1. **Transport and display.** The `todo.py` command (rights, Odoo host
   exempted from rate limits, phone user, token, QR, revoke; edits
   `server.yml` only after showing the change and asking). The app: ntfy
   settings (scan or paste), per-account key pair and topic, registration with
   Odoo, the native service and levels 1–5 without automatic climbing,
   decryption, notifications per conversation and per server channel, lock
   screen per server, tap opens the conversation or the inbox item, the
   Odoo-direct summary (accounts without ntfy, silence longer than the ntfy
   cache), the service's health
   shown in the app (« the phone is not listening » never silent).
2. **Actions and module 1.5.** Reply, mark read, mute 1 h, 👍 from native
   code with the mirrored session, never twice (same idempotency as the
   app's outbox); expired session hands the action to the app. Module 1.5:
   message id and channel type in Odoo's payload, app devices recognised,
   « read » push after commit to app devices only, 200 accepted from them,
   optional no-push while a browser is online.
3. **Preferences and battery.** Odoo's settings read and changed from the
   app, the phone-side filter, the browser-active setting, automatic climbing
   (battery saver, thresholds, charging), optional quiet hours, the Google
   Play justifications written down.

Each lot ends with unit tests, long tests on Odoo 18 against a real ntfy
started by the harness, and a device scenario on the test app only.

## Left to the builder

- How the QR content is shaped (a link carrying ntfy URL, token and prefix)
  and whether the app scans it with a library or the camera intent; pasting
  the link always works.
- How a reply from the notification stays idempotent with and without the
  module, and how the JS cache catches up after native actions.
- How mark read and 👍 find the message id without the module, without ever
  marking Inbox entries done (or offering those two actions only with the
  module).
- How the permanent notification is shared with the SMS gateway.
- The ntfy keepalive and reconnection backoff, within the battery goals.
- The exact native storage for mirrored settings and sessions.

## Non-goals

- Calls and video (project 4): no ringing for calls in project 2.
- iOS, APNs, Firebase.
- The public https ntfy and its host (project 3).
- Odoo 16 and 17 (no chat in the app).
