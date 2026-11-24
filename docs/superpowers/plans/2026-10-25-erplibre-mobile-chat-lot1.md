# ERPLibre mobile chat, lot 1 (core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From a 💬 tile on the home screen, read and write the Odoo 18
Discuss conversations of every configured Odoo 18 server, realtime while
the app is open, readable and writable offline, never doubled.

**Architecture:** A `ChatService` (built inside `SyncService`, like the
calendar) keeps a SQLite cache of channels, members, partners and
messages per server (`configId`), fed by `/mail/data`, paged history and
the Odoo bus. The bus runs over a native websocket plugin (OkHttp) behind
a `BusTransport` interface; tests swap in Node's `WebSocket`. Every write
goes through the existing outbox under the pseudo note id `"chat"`; a post
is idempotent through the `erplibre_mobile_chat` server module when it is
installed, else through a hidden HTML comment marker searched before a
resend.

**Tech Stack:** TypeScript, Owl 2 (precompiled templates), Capacitor 8,
`@capacitor-community/sqlite`, Vitest; Java + OkHttp 4 for the plugin;
Odoo 18 module (Python); ERPLibre long tests (Python runner + Vitest).

**Spec:** `docs/superpowers/specs/2026-10-25-erplibre-mobile-chat-design.md`
(lot 1 of « Lots », plus every « Decisions » line lot 1 touches).

## Global Constraints

- Odoo 18 only: a server counts as a chat source when its major version is 18.
- Server choice: 0 sources → chat unavailable with a way to add a server; 1 → no choice shown; 2–4 → chips (with « All » in the list); ≥ 5 → dropdown.
- Unread: chat/group count `message_unread_counter`; channel counts only `message_needaction_counter` (unread without mention: bold, not counted, not lifted); tile and chips show a total in messages, inbox counter included, muted conversations excluded (as Odoo's menu).
- Sort: conversations with a non-zero unread count first, then `last_interest_dt` descending.
- « Rich text » = what the browser composer produces: escaped text, line breaks, URLs as links. No bold, no lists.
- Read and typing are sent by default; each can be turned off (`options.chat`). The read switch also stops `channel_fetched`; its hint says posting still marks the conversation read.
- History pages always use `around` on `/discuss/channel/messages` (never `before`/`after`/none), so fetching never clears mentions.
- Typing is sent only in conversations where the user is a member.
- Nothing lost, nothing doubled: every post is queued in the outbox before any request.
- https/wss only unless `options.sync.allowHttp`; `ws://` follows the same rule as `http://`.
- Every new `.ts`/`.scss` file under `src/` appears in `src/data/featureCatalog.ts` (new root `chat`) in the task that creates it, or `featureCatalog.test.ts` fails.
- Every user-visible string goes through `t()` with the key in both `src/i18n/en.ts` and `fr.ts`.
- Owl templates contain no `${}` interpolation (CSP, precompiled templates).
- Comments describe how the code works, in the present tense; nothing identifying anywhere outside `private/`.
- Commits: one per task, per repository touched; bilingual message (English, `--- FR ---`, French), `[TAG] scope: subject` ≤ 72 chars, trailer `Assisted-by: <model>`, never an AI in `Co-authored-by`; identity `-c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca"`; name files at `git add`, never `-A`; never push.
- Branches: `dev/mobile_chat` in each repository touched, created from the current HEAD (ERPLibre and mobile from `dev/mobile_sync`, `ERPLibre_erplibre_addons` from its detached `0f98e51`).

## Review Focus

1. **Bus echo before the post response.** The `discuss.channel/new_message` of the user's own post can arrive before `/mail/message/post` answers; the thread must show one bubble, not two (Task 7 test `own post echoed by bus before response stays one message`).
2. **Two accounts on the same server.** Same url and database, two users: each is its own source with its own cache and socket, the tag shows the user (Task 2 `sourceLabels` test, Task 4 repository test keyed by configId).
3. **A post queued for a server deleted from the app.** The outbox row of a removed application must neither block nor crash a drain (Task 5 test `drain ignores chat rows of a removed application`).
4. **Bus gap over 24 h** (phone off over a weekend): the server resets `last` to 0; the client must reload `/mail/data` instead of trusting the empty catch-up (Task 8 test `gap over bus retention reloads`).
5. **A message body Odoo renders but the WebView cannot** (images, iframes, scripts in an email-originated body): rendered as text-safe HTML with images replaced by a placeholder, never executing anything (Task 2 `renderBody` tests).

---

## File Structure

**ERPLibre_erplibre_addons** (`odoo18.0/addons/ERPLibre_erplibre_addons/erplibre_mobile_chat/`):
`__init__.py`, `__manifest__.py`, `models/__init__.py`, `models/mail_message.py` (field), `models/discuss_channel.py` (allowed param, idempotent post), `tests/__init__.py`, `tests/test_erplibre_mobile_chat.py`, `README.md`, `i18n/fr_CA.po`.

**Mobile** (`mobile/erplibre_home_mobile/`):
- `src/models/chat.ts` — record types.
- `src/services/chat/chatSources.ts` — which apps are sources, labels, choice mode.
- `src/services/chat/chatUnread.ts` — counters and sort.
- `src/services/chat/chatBody.ts` — text → body, marker, safe render, preview.
- `src/services/chat/chatSettings.ts` — `options.chat`.
- `src/services/chat/chatStore.ts` — Odoo Store result → normalized delta.
- `src/services/chat/chatRepository.ts` — SQLite CRUD of the chat tables.
- `src/services/chat/chatOutbox.ts` — outbox kinds and handlers.
- `src/services/chat/chatBus.ts` — bus protocol and reconnection over a `BusTransport`.
- `src/services/chat/chatService.ts` — the façade screens and lifecycle use.
- `src/services/chat/chatModule.ts` — server module status and install.
- `src/services/migrations/addChatTables.ts` — migration `2026102501`.
- `src/plugins/chatSocketPlugin.ts` + `android/app/src/main/java/ca/erplibre/home/ChatSocketPlugin.java`.
- `src/components/chat/chat_list_component.ts|.scss`, `src/components/chat/chat_thread_component.ts|.scss`, `src/components/options/chat/options_chat_component.ts`.
- Modified: `databaseService.ts` (DDL, rename), `outboxService.ts` (drain filter), `syncService.ts` (construct chat, skip chat in syncAll/hasDueWork), `odooRpcClient.ts` (session info fields), `notificationService.ts` (chat flush hooks), `app.ts`, `enhancedComponent.ts`, `routes.ts`, `events.ts`, `home_component.ts|.scss`, `options_component.ts`, `applications_edit_component.ts`, `css/components.scss`, `featureCatalog.ts`, `i18n/en.ts|fr.ts`, `__mocks__/@odoo/owl.ts`, `testing/syncTestKit.ts`, `testing/deviceTestHook.ts`, `android/app/build.gradle`, `MainActivity.java`, `CHANGELOG.base.md`.

**ERPLibre**:
- Modified: `long_test/mobile_sync_odoo.py`, `long_test/mobile_sync.py`, `long_test/mobile_sync/harness.ts`, `long_test/mobile_sync/faultProxy.ts`, `long_test/mobile_sync/odooAdmin.ts`, `long_test/mobile_sync_device.py`, `test/test_mobile_sync_harness.py`, `contracts/odoo-api.json`, `contracts/compatibility.json`, `long_test/README.base.md` (+ mmg outputs), `CHANGELOG.base.md` (+ outputs).
- Create: `long_test/mobile_sync/chat.test.ts`, `long_test/mobile_sync/chatRealtime.test.ts`.

---

### Task 1: Server module `erplibre_mobile_chat`

**Files:**
- Create: the module tree listed above (copy layout, headers and manifest style of `erplibre_user_signature`).
- Test: `erplibre_mobile_chat/tests/test_erplibre_mobile_chat.py`

**Interfaces:**
- Produces: field `mail.message.erplibre_client_uuid` (Char, `index="btree_not_null"`, `copy=False`, `readonly=True`); `discuss.channel._get_allowed_message_post_params()` adds `"erplibre_client_uuid"`; `discuss.channel.message_post(**kwargs)` returns the existing message when a message of the same channel by the same author already has that uuid, without posting or notifying.
- Manifest: `"name": "ERPLibre — Clavardage mobile"`, `"version": "18.0.1.0.0"`, `"depends": ["mail"]`, `"license": "AGPL-3"`, `"author": "TechnoLibre"`, `"category": "Technical"`.

- [ ] **Step 1: Write the failing tests** (`@tagged("post_install", "-at_install")`, `HttpCase`, two users from `new_test_user(..., groups="base.group_user")`, a group channel with both):
  - `test_post_same_uuid_twice_gives_one_message`: two `make_jsonrpc_request("/mail/message/post", {"thread_model": "discuss.channel", "thread_id": ch.id, "post_data": {"body": "hi", "message_type": "comment", "subtype_xmlid": "mail.mt_comment", "erplibre_client_uuid": "u-1"}})` as user A → `len(ch.message_ids.filtered(lambda m: m.erplibre_client_uuid == "u-1")) == 1` and both responses carry the same `mail.message` id.
  - `test_other_uuid_posts_again`: uuids `u-1` then `u-2` → two messages.
  - `test_uuid_of_other_author_not_adopted`: user B posts with A's uuid → a second message exists, B is its author.
  - `test_uuid_in_other_channel_not_adopted`: same uuid in a second channel → one message per channel.
  - `test_post_without_uuid_unchanged`: no key → message posted, `erplibre_client_uuid` false.
- [ ] **Step 2: Run, verify they fail** — `.venv.odoo18.0_python3.12.10/bin/python odoo18.0/odoo/odoo-bin -c config.conf -d chat_module_test -i erplibre_mobile_chat --test-tags /erplibre_mobile_chat --stop-after-init --log-level=test` (`config.conf` already carries the ERPLibre addons path); drop the base afterwards with `dropdb chat_module_test`. Expected before the code: module not found, or the 5 tests fail.
- [ ] **Step 3: Implement** the field and the two overrides; the duplicate lookup is `self.env["mail.message"].search([("model","=","discuss.channel"),("res_id","=",self.id),("erplibre_client_uuid","=",uuid),("author_id","=",self.env.user.partner_id.id)], limit=1)` inside `message_post`, before `super()`.
- [ ] **Step 4: Run, verify they pass.** Expected: 5 tests, 0 failures.
- [ ] **Step 5: Commit** in `ERPLibre_erplibre_addons` on `dev/mobile_chat`: `[ADD] erplibre_mobile_chat: idempotent Discuss post by client uuid`.

### Task 2: Pure helpers — sources, unread, body, settings

**Files:**
- Create: `src/models/chat.ts`, `src/services/chat/chatSources.ts`, `chatUnread.ts`, `chatBody.ts`, `chatSettings.ts`
- Test: `src/__tests__/chatSources.test.ts`, `chatUnread.test.ts`, `chatBody.test.ts`, `chatSettings.test.ts`
- Modify: `src/data/featureCatalog.ts` (root `chat`, leaves `chat.sources`, `chat.unread`, `chat.body`, `chat.settings`)

**Interfaces:**
- Produces (`src/models/chat.ts`):
  ```ts
  export type ChannelType = "chat" | "group" | "channel";
  export interface ChatChannel { configId: string; channelId: number; channelType: ChannelType; name: string; description: string;
    lastInterestDt: string | null; unreadCounter: number; needactionCounter: number; newMessageSeparator: number;
    seenMessageId: number | null; muteUntilDt: string | null; customNotifications: string | null; isMember: boolean;
    localPinned: boolean; lastMessageId: number | null; oldestLoadedId: number | null; historyComplete: boolean;
    correspondentPartnerId: number | null; }
  export type ChatMessageStatus = "sent" | "pending" | "failed";
  export interface ChatMessage { configId: string; channelId: number; messageId: number | null; clientUuid: string | null;
    authorPartnerId: number | null; body: string; date: string; messageType: string; status: ChatMessageStatus;
    outboxOpId: string | null; writeDate: string | null; }
  export interface ChatMember { configId: string; channelId: number; memberId: number; partnerId: number;
    seenMessageId: number | null; fetchedMessageId: number | null; isTyping: boolean; typingAt: string | null; }
  export interface ChatPartner { configId: string; partnerId: number; name: string; imStatus: string | null; }
  export type ChatModuleState = "installed" | "available" | "absent" | "unknown";
  export interface ChatSourceState { configId: string; selfPartnerId: number | null; lastBusId: number; busSeenAt: string | null;
    wsVersion: string | null; isSystem: boolean; moduleState: ChatModuleState; inboxCounter: number; loadedAt: string | null; }
  ```
  Dates are Odoo's `"YYYY-MM-DD HH:MM:SS"` UTC strings, kept as given.
- Produces (`chatSources.ts`): `parseOdooMajor(version: string): number | null`; `type ChoiceMode = "unavailable" | "none" | "chips" | "dropdown"`; `serverChoiceMode(n: number): ChoiceMode`; `sourceLabels(apps: Pick<Application,"url"|"username"|"database">[]): string[]`; `export const CHAT_MAJOR = 18`.
- Produces (`chatUnread.ts`): `unreadOf(c: ChatChannel): number`; `isBold(c: ChatChannel): boolean`; `isMuted(c: ChatChannel, now: Date): boolean`; `totalUnread(channels: ChatChannel[], inboxCounters: number[], now: Date): number`; `sortConversations(channels: ChatChannel[]): ChatChannel[]`.
- Produces (`chatBody.ts`): `chatMarker(uuid: string): string` → `"<!-- erplibre-mobile:" + uuid + " -->"`; `textToBody(text: string, markerUuid: string | null): string`; `bodyHasMarker(body: string, uuid: string): boolean`; `renderBody(html: string): string`; `bodyPreview(html: string, max?: number): string`.
- Produces (`chatSettings.ts`): `CHAT_SETTINGS_KEY = "options.chat"`; `interface ChatSettings { sendRead: boolean; sendTyping: boolean }`; `DEFAULT_CHAT_SETTINGS = { sendRead: true, sendTyping: true }`; `chatSettings(): ChatSettings`; `setChatSettings(s: ChatSettings): void` (pattern of `attachmentService.ts` L6–48).

- [ ] **Step 1: Write the failing tests**
  - `parseOdooMajor`: `"18.0"→18`, `"18.0+e"→18`, `"saas~17.4"→17`, `""→null`, `"abc"→null`.
  - `serverChoiceMode`: `0→"unavailable"`, `1→"none"`, `2→"chips"`, `4→"chips"`, `5→"dropdown"`, `9→"dropdown"`.
  - `sourceLabels`: `[{url:"https://bureau.example.org",…}]→["bureau"]`; two hosts sharing the first label → full hosts; same host, two databases → `"host/db"` each; same host and db, users `ana` and `bob` → `"bureau · ana"`, `"bureau · bob"`.
  - `unreadOf`: chat with `unreadCounter 3, needaction 0` → 3; group same → 3; channel with `unreadCounter 5, needaction 0` → 0 and `isBold` true; channel `needaction 2` → 2.
  - `isMuted`: `muteUntilDt` in the future → true; `"9999-12-31 23:59:59"` (Odoo stores « forever » as `datetime.max`) → true; past or null → false; `customNotifications "no_notif"` → true.
  - `totalUnread([chat 3, channel needaction 2, muted group 4], [1], now)` → 6.
  - `sortConversations`: unread ones first, each group by `lastInterestDt` desc, a bold channel with 0 counted unread stays in the second group.
  - `textToBody("a < b\nc", null)` → `"a &lt; b<br>c"`; URLs `https://x.org/a?b=1&c` become `<a href="https://x.org/a?b=1&amp;c" target="_blank" rel="noreferrer noopener">…</a>`; with uuid `"u1"` the result ends with `<!-- erplibre-mobile:u1 -->`; `bodyHasMarker` finds it.
  - `renderBody`: keeps `p, br, a[href], span, b, strong, i, em, u, ul, ol, li, blockquote, code, pre`; removes `script`, `style`, `iframe`, event attributes, `javascript:` hrefs; replaces `<img>` with `<span class="chat-msg__image">🖼️</span>`; drops comments (the marker never shows).
  - `bodyPreview("<p>Hello<br>world</p><!-- erplibre-mobile:u -->", 80)` → `"Hello world"`.
  - `chatSettings()` defaults when the key is missing or holds bad JSON; round trip through `setChatSettings`.
- [ ] **Step 2: Run** `npx vitest run src/__tests__/chat` — expected FAIL (modules missing).
- [ ] **Step 3: Implement.** `renderBody` and `bodyPreview` walk a `DOMParser` tree and rebuild only whitelisted nodes and attributes (no regex HTML parsing). `chatBody.test.ts` starts with `// @vitest-environment jsdom`; add `"jsdom": "25.0.1"` (the version already in `node_modules`) to `devDependencies` and run `npm install` so it no longer rests on a transitive dependency.
- [ ] **Step 4: Run, verify PASS**, then `npx vitest run src/__tests__/featureCatalog.test.ts src/__tests__/i18n*.test.ts`.
- [ ] **Step 5: Commit** (mobile): `[ADD] chat: sources, unread rules, message body and settings`.

### Task 3: Odoo Store parser

**Files:**
- Create: `src/services/chat/chatStore.ts`
- Test: `src/__tests__/chatStore.test.ts` (fixtures as literal objects in the test, shaped as in the spec's Odoo notes)
- Modify: `featureCatalog.ts` (`chat.store`)

**Interfaces:**
- Consumes: types of Task 2.
- Produces:
  ```ts
  export interface StoreDelta { channels: (Partial<ChatChannel> & { channelId: number })[]; deletedChannelIds: number[];
    members: (Partial<ChatMember> & { memberId: number })[]; deletedMemberIds: number[];
    messages: (Partial<ChatMessage> & { messageId: number })[]; partners: ChatPartner[];
    inboxCounter: number | null; selfPartnerId: number | null; }
  export function parseStore(result: any, configId: string, selfPartnerId: number | null): StoreDelta;
  export function mergeDeltas(a: StoreDelta, b: StoreDelta): StoreDelta;
  ```
  Only keys present in a record appear in its partial (an insert updates, never blanks). The self member row's `message_unread_counter`, `new_message_separator`, `seen_message_id` go onto the channel partial. `channelMembers: [["DELETE",[id]]]` adds to `deletedMemberIds`; `_DELETE: true` on a channel adds to `deletedChannelIds`. `Store.inbox.counter` → `inboxCounter`; `Store.self.id` → `selfPartnerId`. For a `chat`, the non-self member's partner → `correspondentPartnerId`, and `name` falls back to that partner's name.

- [ ] **Step 1: Write the failing tests:** `/mail/data` result with a chat, a group and a channel + last messages → three channel partials with types, counters from self members, `lastMessageId`; a `mail.record/insert` with only `{"discuss.channel":[{id:5, name:"x"}]}` → partial with exactly `channelId` and `name`; message edit insert (`body`, `write_date`) → message partial without `authorPartnerId`; member left → `deletedMemberIds`; typing insert → member `isTyping true`; `Store.inbox` → `inboxCounter`; `mergeDeltas` keeps the later value of a key.
- [ ] **Step 2: Run** `npx vitest run src/__tests__/chatStore.test.ts` — FAIL.
- [ ] **Step 3: Implement** `parseStore` and `mergeDeltas`.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit**: `[ADD] chat: parse the Odoo 18 Store result into cache records`.

### Task 4: Chat tables, repository, config rename

**Files:**
- Create: `src/services/migrations/addChatTables.ts`, `src/services/chat/chatRepository.ts`
- Modify: `src/services/migrations/index.ts` (entry `{ version: 2026102501, description: "Tables du clavardage", run: addChatTables }`), `src/services/databaseService.ts` (`createChatTables()`, `renameSyncConfigId` re-keys chat tables)
- Test: `src/__tests__/chatRepository.test.ts`, extend `src/__tests__/migrations.test.ts` if it lists versions
- Modify: `featureCatalog.ts` (`chat.cache`)

**Interfaces:**
- Produces: tables (first column is the text primary key; the SQLite mock needs it first):
  - `chat_channels(id /*configId#channelId*/, config_id, channel_id, channel_type, name, description, last_interest_dt, unread_counter, needaction_counter, new_message_separator, seen_message_id, mute_until_dt, custom_notifications, is_member, local_pinned, last_message_id, oldest_loaded_id, history_complete, correspondent_partner_id, updated_at)`
  - `chat_messages(id /*configId#m<messageId> or configId#u<clientUuid>*/, config_id, channel_id, message_id, client_uuid, author_partner_id, body, date, message_type, status, outbox_op_id, write_date)`
  - `chat_members(id /*configId#memberId*/, config_id, channel_id, member_id, partner_id, seen_message_id, fetched_message_id, is_typing, typing_at)`
  - `chat_partners(id /*configId#partnerId*/, config_id, partner_id, name, im_status)`
  - `chat_sources(config_id, self_partner_id, last_bus_id, bus_seen_at, ws_version, is_system, module_state, inbox_counter, loaded_at)`
- Produces (`ChatRepository`, `constructor(db: DatabaseService)`): `applyDelta(configId: string, d: StoreDelta): Promise<void>`; `channels(configId?: string): Promise<ChatChannel[]>`; `channel(configId: string, channelId: number): Promise<ChatChannel | null>`; `patchChannel(configId, channelId, p: Partial<ChatChannel>): Promise<void>`; `messages(configId, channelId, opts?: { beforeId?: number; limit?: number }): Promise<ChatMessage[]>` (oldest first; pending ones last); `putPending(m: ChatMessage): Promise<void>`; `settlePending(configId, clientUuid, messageId: number, patch?: Partial<ChatMessage>): Promise<void>` (moves `#u<uuid>` to `#m<id>`, merging with a row the bus already wrote); `markFailed(configId, clientUuid, error: string)`; `members(configId, channelId)`; `partners(configId)`; `sourceState(configId): Promise<ChatSourceState>` (defaults when absent); `setSourceState(s: Partial<ChatSourceState> & { configId: string })`; `dropSource(configId)`.
- SQL limits: WHERE with `col = ?` only; sort and slice in JS after each query (the mock ignores ORDER BY/LIMIT).

- [ ] **Step 1: Write the failing tests:** migration creates the five tables (`PRAGMA table_info`); `applyDelta` then `channels()` round trip; a second partial delta updates only its keys; `messages` order with a pending last; `settlePending` when the bus already inserted `#m42` leaves one row with status `sent`; two configIds on the same server keep separate rows (Review Focus 2); `renameSyncConfigId(old,new)` keeps a pending message and its channel under the new id; `dropSource` removes every row of that config only.
- [ ] **Step 2: Run** `npx vitest run src/__tests__/chatRepository.test.ts` — FAIL.
- [ ] **Step 3: Implement** DDL in `DatabaseService.createChatTables()`, the migration, the repository, the rename.
- [ ] **Step 4: Run** the new test plus `databaseService.test.ts`, `migrations.test.ts`, `syncService.test.ts` — PASS.
- [ ] **Step 5: Commit**: `[ADD] chat: SQLite cache of channels, messages, members and sources`.

### Task 5: Chat outbox — posts and reads, apart from the note sync

**Files:**
- Create: `src/services/chat/chatOutbox.ts`
- Modify: `src/services/outboxService.ts` (`drain` option `onlyNoteIds?: Set<string>`), `src/services/syncService.ts` (`syncAll` passes `CHAT_NOTE` in `skipNoteIds`; `hasDueWork` ignores `CHAT_NOTE` rows), `src/services/odoo/odooRpcClient.ts` (`SessionInfo` gains `partnerId: number`, `isSystem: boolean`, `websocketWorkerVersion: string | null`)
- Test: `src/__tests__/chatOutbox.test.ts` (fake Odoo built like `src/__tests__/helpers/fakeOdoo.ts`), extend `outboxService.test.ts`, `odooRpcClient.test.ts`
- Modify: `featureCatalog.ts` (`chat.outbox`)

**Interfaces:**
- Consumes: `OutboxService` (`enqueue`, `attempt`, `registerHandler`, `drain`, `setParams`), `OdooRpcClient.callWithAuth/jsonRoute/searchRead/callKw`, `clientMarker`, `CREATE_QUIET_WINDOW_MS` (syncService.ts), Task 2 `textToBody`, Task 4 repository.
- Produces:
  ```ts
  export const CHAT_NOTE = "chat";
  export const CHAT_POST = "chat.post";   // params { channelId, text, useModule: boolean, createSentAt? }
  export const CHAT_READ = "chat.read";   // params { channelId, lastMessageId, mentions: boolean }
  export class ChatOutbox {
    constructor(db: DatabaseService, rpc: OdooRpcClient, outbox: OutboxService, repo: ChatRepository, now?: () => Date);
    queuePost(configId: string, channelId: number, text: string, useModule: boolean): Promise<ChatMessage>; // pending row + op, dependsOn previous pending post of the channel
    queueRead(configId: string, channelId: number, lastMessageId: number, mentions: boolean): Promise<void>; // one op per channel, lastMessageId = max
    flush(creds: SyncCredentials, opts?: { force?: boolean }): Promise<DrainResult>; // drain with onlyNoteIds {CHAT_NOTE}
  }
  ```
  Post handler: `useModule` → `post_data.erplibre_client_uuid = op.clientUuid`; else body ends with `chatMarker(op.clientUuid)` and, when `op.attempts > 1`, first `searchRead("mail.message", [["model","=","discuss.channel"],["res_id","=",channelId],["body","ilike", clientMarker(op.clientUuid)]], ["id"], {limit: 2})`: one → adopt, two → `OutboxBlockedError(…, "ambiguous")`; inside the quiet window → `OutboxRetryLaterError`. Request: `jsonRoute(url, sid, "/mail/message/post", { thread_model: "discuss.channel", thread_id, post_data: { body, message_type: "comment", subtype_xmlid: "mail.mt_comment", … }, context: { temporary_id: op.clientUuid } })`. Success → `repo.settlePending` with the id of `result["mail.message"][0]`, and the channel's `seenMessageId`/`unreadCounter 0` (Odoo marks it read on post). Read handler: `/discuss/channel/mark_as_read {channel_id, last_message_id}`, then when `mentions` `callKw("mail.message","mark_all_as_read",[[["model","=","discuss.channel"],["res_id","=",channelId]]])`.

- [ ] **Step 1: Write the failing tests:**
  - `post with module sends uuid and settles` (fake asserts `post_data.erplibre_client_uuid`).
  - `post without module appends marker` (body ends with the comment).
  - `lost response then retry adopts the marked message` (fake executes then throws; second run finds it, no second post).
  - `lost response with module retries the same uuid` (fake dedups by uuid; one message).
  - `two queued posts keep their order when the first fails` (second waits on `dependsOn`).
  - `reads coalesce to the highest message id` and `read with mentions also calls mark_all_as_read`.
  - `syncAll leaves chat rows alone` and `hasDueWork ignores chat rows`.
  - `drain ignores chat rows of a removed application` (Review Focus 3: `flush` for an unknown config completes without throwing).
  - `sessionInfo returns partner id, system flag and websocket version`.
- [ ] **Step 2: Run** `npx vitest run src/__tests__/chatOutbox.test.ts src/__tests__/outboxService.test.ts` — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** those plus `syncService.test.ts`, `odooRpcClient.test.ts` — PASS.
- [ ] **Step 5: Commit**: `[ADD] chat: outbox posts and reads, idempotent by module or marker`.

### Task 6: Server module status and install

**Files:**
- Create: `src/services/chat/chatModule.ts`
- Test: `src/__tests__/chatModule.test.ts`
- Modify: `featureCatalog.ts` (`chat.module`)

**Interfaces:**
- Consumes: `CapabilityService.ensure(creds, "mail.message", {online, maxAgeMs})`, `rpc.sessionInfo`, `rpc.searchRead`, `rpc.callKw`, repository `setSourceState`.
- Produces: `export const CHAT_MODULE = "erplibre_mobile_chat"`, `export const CHAT_UUID_FIELD = "erplibre_client_uuid"`; `moduleState(creds: SyncCredentials, opts: { online: boolean; fresh?: boolean }): Promise<ChatModuleState>`; `installModule(creds: SyncCredentials): Promise<ChatModuleState>`.
  - `installed` when `cap.fields` holds `CHAT_UUID_FIELD`; else when `isSystem`: `searchRead("ir.module.module", [["name","=",CHAT_MODULE]], ["state"])` → none `absent`, `installed` (registry not reloaded yet) `installed`, other `available`; else `unknown`.
  - `installModule`: `callKw("ir.module.module","button_immediate_install",[[id]])`; a timeout or lost response is not an error: it re-probes with `fresh: true` and returns the probed state.

- [ ] **Step 1: Write the failing tests:** field present → `installed`; no field, system, module row `uninstalled` → `available`; no row → `absent`; no field, not system → `unknown`; install then probe → `installed`; install whose call times out but the probe sees the field → `installed`.
- [ ] **Step 2–4:** run (FAIL), implement, run (PASS) `npx vitest run src/__tests__/chatModule.test.ts`.
- [ ] **Step 5: Commit**: `[ADD] chat: detect and install the server chat module`.

### Task 7: ChatService — sources, load, history, send, read, typing

**Files:**
- Create: `src/services/chat/chatService.ts`
- Modify: `src/services/syncService.ts` (`readonly chat: ChatService`, built next to `this.calendar`), `src/constants/events.ts` (`CHAT_CHANGED: "chatchanged"`)
- Test: `src/__tests__/chatService.test.ts`
- Modify: `featureCatalog.ts` (`chat.service`)

**Interfaces:**
- Consumes: Tasks 2–6.
- Produces:
  ```ts
  export const CHAT_PAGE = 30, CHAT_FULL_PAGE = 100;
  export interface ChatSource { configId: string; app: Application; creds: SyncCredentials; label: string; }
  export class ChatService {
    constructor(db: DatabaseService, rpc: OdooRpcClient, outbox: OutboxService, capabilities: CapabilityService, now?: () => Date);
    readonly repo: ChatRepository; readonly queue: ChatOutbox;
    onChange: ((configId: string, channelId: number | null) => void) | null;
    sources(opts?: { online?: boolean }): Promise<ChatSource[]>;
    load(src: ChatSource): Promise<void>;                          // session info + /mail/data → repo; module state
    conversations(configIds?: string[]): Promise<ChatChannel[]>;   // sorted (Task 2)
    unreadTotal(configIds?: string[]): Promise<number>;
    messages(configId: string, channelId: number): Promise<ChatMessage[]>;
    loadOlder(src: ChatSource, channelId: number): Promise<number>; // count added; sets historyComplete
    loadAll(src: ChatSource, channelId: number, onProgress?: (n: number) => void): Promise<number>;
    send(src: ChatSource, channelId: number, text: string): Promise<ChatMessage>; // queue, then try at once when online
    markRead(src: ChatSource, channelId: number): Promise<void>;   // no-op when sendRead is off
    typing(src: ChatSource, channelId: number, isTyping: boolean): Promise<void>; // only when member and sendTyping
    applyBus(configId: string, notifications: BusNotification[]): Promise<void>;
    flushAll(): Promise<void>;
  }
  ```
  `sources()`: apps from `db.getAllApplications()` with a database whose `parseOdooMajor(app.odooVersion)` is 18; when the string is empty and `online`, `rpc.odooVersion(creds)` decides and `db.setApplicationOdooVersion(app.url, app.username, "<major>.0")` stores it; offline, an app with a `chat_sources` row counts. Labels from `sourceLabels`. `loadOlder` calls `/discuss/channel/messages {channel_id, around: oldestLoadedId - 1, limit: 2 * CHAT_PAGE}` and keeps the ids below `oldestLoadedId`; fewer than `CHAT_PAGE` older ones sets `historyComplete`. With nothing loaded it uses `around: lastMessageId + 1`. `typing` throttles: one `true` per 50 s while typing, `false` 5 s after the last keystroke (constants `TYPING_RESEND_MS = 50000`, `TYPING_STOP_MS = 5000`). `markRead` also calls `channel_fetched` for `chat` channels with the same switch. `applyBus` handles: `discuss.channel/new_message` (matching `temporary_id` to a pending `clientUuid` → `settlePending`), `mail.record/insert`, `discuss.channel.member/fetched`, `discuss.channel/joined` (then `load`), `discuss.channel/leave`, `discuss.channel/delete`, `mail.message/mark_as_read` and `mail.message/inbox` (inbox counter), `bus.bus/im_status_updated`; each ends with `onChange`.

- [ ] **Step 1: Write the failing tests** (fake Odoo, in-memory db through `createSyncEnv`-style setup):
  - `sources keeps only Odoo 18 apps`, `sources with empty version asks the server once and stores it`, `offline sources keep a known chat server`.
  - `load fills conversations and unread total` (values from the Global Constraints rules).
  - `loadOlder pages with around and never before` (fake records the params; asserts `around` present, `before` absent) and `loadOlder marks history complete`.
  - `send offline keeps a pending message` then `flushAll on reconnect posts it once`.
  - `own post echoed by bus before response stays one message` (Review Focus 1).
  - `markRead does nothing when sendRead is off`; `typing is not sent in a channel the user is not a member of`; `typing throttles to one true per 50 s`.
  - `bus message of another user raises unread and calls onChange`.
- [ ] **Step 2–4:** `npx vitest run src/__tests__/chatService.test.ts` FAIL → implement → PASS, plus the whole `npm test`.
- [ ] **Step 5: Commit**: `[ADD] chat: service for sources, history, sending, read and typing`.

### Task 8: Bus client over a transport

**Files:**
- Create: `src/services/chat/chatBus.ts`
- Test: `src/__tests__/chatBus.test.ts` (fake transport + fake timers)
- Modify: `featureCatalog.ts` (`chat.bus`)

**Interfaces:**
- Produces:
  ```ts
  export interface BusNotification { id: number; message: { type: string; payload: any } }
  export interface BusTransport {
    open(url: string, headers: Record<string, string>): void;
    send(text: string): void; close(): void;
    onOpen: () => void; onMessage: (text: string) => void; onClose: (code: number, reason: string) => void;
  }
  export const BUS_VERSION_FALLBACK = "18.0-7", BUS_RETENTION_MS = 24 * 3600 * 1000,
    BACKOFF_START_MS = 1000, BACKOFF_MAX_MS = 120000, BACKOFF_JITTER_MS = 30000, KEEPALIVE_MS = 60000;
  export class ChatBus {
    constructor(src: ChatSource, deps: { transport: () => BusTransport; session: () => Promise<{ sessionId: string; version: string }>;
      reauth: () => Promise<void>; state: () => Promise<ChatSourceState>; saveLast: (id: number) => Promise<void>;
      channels: () => Promise<string[]>; // "odoo-presence-res.partner_<id>" of every chat correspondent
      deliver: (n: BusNotification[]) => Promise<void>; reload: () => Promise<void>; random?: () => number; });
    start(): void; stop(): void; readonly connected: boolean;
  }
  ```
  URL: `odooUrl` with `http`→`ws` and `https`→`wss` + `/websocket?version=<version>`; refuses `ws://` unless http is allowed (`InsecureHttpError`). Headers: `Origin: <odooUrl origin>`, `Cookie: session_id=<sid>`. On open: `{"event_name":"subscribe","data":{"channels":<channels()>,"last":<lastBusId>}}` (member channels are implicit on the server; only presences are listed), then `{"event_name":"update_presence","data":{"inactivity_period":0,"im_status_ids_by_model":{}}}`. Every frame: `deliver`, then `saveLast(last id)`. A `0x00`-equivalent keepalive is the plugin's job (OkHttp ping); the client resends `subscribe` after `discuss.channel/joined`. Close codes: 4001 → `reauth` then backoff; 4002 → reconnect now; 1000 with `OUTDATED_VERSION` → stop and report; others → backoff `min(start·2^n, max) + random·jitter`. When `busSeenAt` is older than `BUS_RETENTION_MS` → `reload()` before subscribing and subscribe with `last: 0`.

- [ ] **Step 1: Write the failing tests:** `subscribes with the saved last id and the presence channels`; `wss url and headers from https server`; `ws url refused unless http allowed`; `frames delivered then last id saved`; `4001 re-authenticates then reconnects`; `4002 reconnects at once`; `outdated version stops`; `backoff doubles to 120 s plus jitter`; `gap over bus retention reloads` (Review Focus 4); `stop closes and never reconnects`.
- [ ] **Step 2–4:** FAIL → implement → PASS (`npx vitest run src/__tests__/chatBus.test.ts`).
- [ ] **Step 5: Commit**: `[ADD] chat: Odoo bus client with resubscribe and reconnection rules`.

### Task 9: Native websocket plugin

**Files:**
- Create: `android/app/src/main/java/ca/erplibre/home/ChatSocketPlugin.java`, `src/plugins/chatSocketPlugin.ts`
- Modify: `android/app/build.gradle` (`implementation "com.squareup.okhttp3:okhttp:4.12.0"`), `MainActivity.java` (`registerPlugin(ChatSocketPlugin.class)`), `featureCatalog.ts` (`chat.socket`, `permissions` none)
- Test: `src/__tests__/chatSocketPlugin.test.ts` (the TS adapter over a mocked plugin)

**Interfaces:**
- Produces (TS): `ChatSocket = registerPlugin<ChatSocketPlugin>("ChatSocket")` with `open({ id, url, headers }): Promise<void>`, `send({ id, text }): Promise<void>`, `close({ id }): Promise<void>`, events `"chatSocketOpen" {id}`, `"chatSocketMessage" {id, text}`, `"chatSocketClose" {id, code, reason}`; `nativeTransport(id: string): BusTransport` adapts it (Task 8 interface). One OkHttp `WebSocket` per `id` (the configId); `pingInterval(30, SECONDS)`; connect/read timeouts 30 s; cleartext follows `network_security_config.xml`.
- [ ] **Step 1: Write the failing test:** `nativeTransport routes events by id` (two ids, events for one never reach the other) and `close event carries code and reason`.
- [ ] **Step 2–4:** FAIL → implement TS and Java → PASS.
- [ ] **Step 5: Verify the build:** `npm run build && npx cap sync android && (cd android && ./gradlew assembleDebug)` — expected `BUILD SUCCESSFUL`. If OkHttp does not resolve offline, stop and report (dependency decision for the user).
- [ ] **Step 6: Commit**: `[ADD] chat: native websocket plugin on OkHttp for the Odoo bus`.

### Task 10: Lifecycle wiring

**Files:**
- Modify: `src/js/app.ts` (after `notificationService.start()`: `chatLifecycle.start()`), `src/services/notificationService.ts` (`onNetworkRestore` and `flushDue` also call `syncService.chat.flushAll()`; `scheduleRetry` includes chat rows), `src/services/chat/chatService.ts` (`startRealtime(transportFor: (configId) => BusTransport)`, `stopRealtime()`), `src/js/enhancedComponent.ts` (getter `chatService`)
- Test: extend `src/__tests__/notificationService.test.ts`
- Modify: `featureCatalog.ts` (files on `chat.service`)

**Interfaces:**
- `ChatService.startRealtime(transportFor)` builds one `ChatBus` per source and `load`s each; `stopRealtime()` stops them. `app.ts` starts realtime when the app becomes active and stops it when inactive, through the same `App.addListener("appStateChange")` path `NotificationService` uses (never inside the `ChatService` constructor: `syncTestKit` builds it without `@capacitor/app`). `onChange` → `eventBus.trigger(Events.CHAT_CHANGED, {configId, channelId})`.
- [ ] **Step 1: Write the failing tests:** `network restore flushes chat`; `going inactive stops realtime, active starts it`; `retry timer counts chat rows`.
- [ ] **Step 2–4:** FAIL → implement → PASS (`npx vitest run src/__tests__/notificationService.test.ts`), then `npm test`.
- [ ] **Step 5: Commit**: `[ADD] chat: realtime follows the app state, queue flushes on reconnect`.

### Task 11: Home tile and conversation list

**Files:**
- Create: `src/components/chat/chat_list_component.ts`, `chat_list_component.scss`
- Modify: `src/components/home/home_component.ts|.scss` (tile 💬 `label.chat`, badge `state.chatUnread`, refresh on `CHAT_CHANGED`), `src/js/routes.ts` (`/chat`), `src/css/components.scss`, `__mocks__/@odoo/owl.ts` (export `markup`), i18n, `featureCatalog.ts` (`chat.list`, demo `{kind:"route", url:"/chat"}`)
- Test: `src/__tests__/chatListComponent.test.ts`

**Interfaces:**
- List state: `{ mode: ChoiceMode; sources: {configId, label, unread}[]; filter: string | null /* configId, null = All */; rows: Row[]; query: string }` with `Row { configId, channelId, title, serverLabel, preview, time, unread, bold, typeIcon /* "👤"|"👥"|"#" */ }`. `mode "unavailable"` shows `chat.unavailable` text and a button to `/applications/add`; `"none"` shows no chips; `"chips"` chips with unread; `"dropdown"` a `<select>`. The last filter is kept in `localStorage["chat.filter"]` (try/catch). Tapping a row navigates to `/chat/<encodeURIComponent(configId)>/<channelId>`. Search filters `title` and `preview` locally (lot 5 adds the server).
- The tile's time budget: the list renders from the cache before any network call; `sources({online:false})` first, then refresh.
- [ ] **Step 1: Write the failing tests:** `mode follows the number of sources` (0,1,3,6); `rows sorted unread first`; `chip filter keeps one server`; `unavailable mode offers adding a server`; `home badge shows the unread total`.
- [ ] **Step 2–4:** FAIL → implement → PASS; `npx vitest run src/__tests__/chatListComponent.test.ts src/__tests__/featureCatalog.test.ts src/__tests__/i18n*.test.ts`.
- [ ] **Step 5: Commit**: `[ADD] chat: home tile with unread badge and the mixed conversation list`.

### Task 12: Conversation screen

**Files:**
- Create: `src/components/chat/chat_thread_component.ts`, `chat_thread_component.scss`
- Modify: `routes.ts` (`/chat/:source/:channelId`, before `*`), i18n, `featureCatalog.ts` (`chat.thread`)
- Test: `src/__tests__/chatThreadComponent.test.ts`

**Interfaces:**
- Bubbles from `chatService.messages`, own ones right; body through `renderBody` with `markup()`; meta line: time, `✓✓` when every other member's `seenMessageId ≥ messageId` (chat/group only), `⏳ chat.pending` for pending, `⚠️ chat.failed` + retry for failed; « X écrit… » from members with `isTyping` in the last 60 s; header: title, server label, presence of the correspondent. Scroll to top → `loadOlder`; menu entry `chat.load_all` → `loadAll` with progress; when `historyComplete` the menu says so. Composer: textarea, Enter inserts a newline, ➤ sends (`send`), empty text never sent; typing via `chatService.typing`. Opening and reaching the bottom → `markRead`.
- [ ] **Step 1: Write the failing tests:** `send clears the composer and shows the pending bubble`; `empty text is not sent`; `seen by all shows double check`; `typing line names the member`; `scroll top loads older`; `reaching bottom marks read`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit**: `[ADD] chat: conversation screen with history, pending and read marks`.

### Task 13: Options and the module line in « Edit an application »

**Files:**
- Create: `src/components/options/chat/options_chat_component.ts`
- Modify: `options_component.ts` (section `chat`, `useFeatureSection("chat", …)`), `applications_edit_component.ts` (line after the detected version: `chat.module_installed|available|absent|unknown`, button `chat.module_install` only when `available`), i18n, `featureCatalog.ts` (`chat.options` demo `{kind:"options", sectionId:"chat"}`, `chat.module` gains the edit component file)
- Test: `src/__tests__/optionsChatComponent.test.ts`, `src/__tests__/applicationsEditChatModule.test.ts`

**Interfaces:**
- Two checkboxes bound to `chatSettings()`: `chat.send_read` with hint `chat.send_read_hint` (« Odoo marque quand même la conversation lue quand tu envoies un message ; l'accusé « reçu » suit ce réglage. »), `chat.send_typing`. The edit screen calls `chatModule.moduleState(creds, {online})` on load for an Odoo 18 app only and shows nothing for others.
- [ ] **Step 1: Write the failing tests:** `toggles persist in options.chat`; `install button only when available`; `install updates the line to installed`; `no line for a non-18 app`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit**: `[ADD] chat: read and typing options, server module status and install`.

### Task 14: Test kit and device hook for chat

**Files:**
- Modify: `src/testing/syncTestKit.ts` (`HARNESS_API = 2`; `SyncEnv` gains `chat: ChatService` = `sync.chat`; `createSyncEnv(targets, opts?: { chatModule?: "auto" | "ignore" })`; export `nodeTransport(): BusTransport` over Node's global `WebSocket` with `headers`), `src/testing/deviceTestHook.ts` (`DEVICE_HOOK_API = 2`; `chatSources()`, `chatSend(configId, channelId, text)`, `chatMessages(configId, channelId)`), `ChatService` (constructor option `moduleMode: "auto" | "ignore"`)
- Test: extend `src/__tests__/syncTestKit.test.ts`

- [ ] **Step 1: Failing test:** `createSyncEnv exposes chat sharing the sync rpc and outbox`; `ignore mode never sends the uuid`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit**: `[ADD] testing: chat in the sync test kit and the device hook`.

### Task 15: Long-test infrastructure for Odoo 18 chat (ERPLibre)

**Files:**
- Modify: `long_test/mobile_sync_odoo.py`: `HARNESS_API = 2`; `VersionOdoo.addons_path` adds `odoo18.0/addons/ERPLibre_erplibre_addons` for 18; `MODULES_EN_PLUS[18] = ("erplibre_mobile_chat",)`; `cle_gabarit` also hashes `git -C <addons repo> rev-parse HEAD` plus the module directory content for 18; `POST_INSTALLATION` creates for `VERSION >= 18` user `chat_user`/`chat_user` (group `base.group_user`) and a group channel « ms chat » with admin and chat_user.
- Modify: `long_test/mobile_sync.py` (`targets.json` entries gain `chat: {login, password}` for 18), `long_test/mobile_sync/harness.ts` (`Target.chat?: Login`; `eachVersionFrom(min: number, name, fn)` naming blocks `Odoo $version — name`), `faultProxy.ts` (`RpcCall.params`; `'upgrade'` handler piping raw TCP with `net.connect`, honouring `down`; `cutSockets()` drops live websockets), `odooAdmin.ts` (`sessionLogin()`, `jsonRoute(path, params)`)
- Test: `test/test_mobile_sync_harness.py` (addons path for 18 holds the ERPLibre addons; template key changes when the addons HEAD changes; 16/17 unchanged)

- [ ] **Step 1: Failing unit tests** as listed; run `./script/test/run_unit_test.sh test/test_mobile_sync_harness.py` — FAIL.
- [ ] **Step 2: Implement**; rerun — PASS.
- [ ] **Step 3: Live check:** `./long_test/mobile_sync.py --versions 18 --rebuild --garder` then `curl` the 18 server's `/web/webclient/version_info`; expected template rebuilt with the module installed, all existing scenarios green. Then `--detruire`.
- [ ] **Step 4: Commit** (ERPLibre): `[IMP] long_test: Odoo 18 chat module, chat user, websocket proxy`.

### Task 16: Chat long tests (ERPLibre)

**Files:**
- Create: `long_test/mobile_sync/chat.test.ts`, `long_test/mobile_sync/chatRealtime.test.ts` (both `eachVersionFrom(18, …)`)

Scenarios (each asserts against the server through `OdooAdmin` as chat_user):
- `chat.test.ts`: `sources lists the Odoo 18 server`; `load matches server counters` (chat_user posts 2 messages and mentions admin in a channel; app's unread equals `message_unread_counter` / `message_needaction_counter`); `post appears once for chat_user`; `lost response with module: one message` (`loseResponseOf(c => c.path === "/mail/message/post")`); `lost response with marker: one message` (`chatModule: "ignore"`); `offline queue keeps order` (`down = true`, send 3, `down = false`, flush → server order 1,2,3); `history paging leaves mentions` (`loadAll`, then server `message_needaction_counter` unchanged); `read marks seen on server` (`seen_message_id` of admin's member = last id).
- `chatRealtime.test.ts`: `bus delivers a message of chat_user` (Node transport through the proxy, `chatService.startRealtime`); `typing of chat_user reaches the app`; `socket cut then reconnect delivers missed messages` (`cutSockets()`, chat_user posts, reconnect → message present, no duplicate).
- [ ] **Step 1: Write the tests.**
- [ ] **Step 2: Run** `./long_test/mobile_sync.py --versions 18 --filtre chat` — expected all green, report counts tests under « Odoo 18 ».
- [ ] **Step 3: Mutation check:** comment out the marker search in the post handler → `lost response with marker` fails; restore. Remove `around` in `loadOlder` → `history paging leaves mentions` fails; restore.
- [ ] **Step 4: Full run** `./long_test/mobile_sync.py` (16/17/18) — green.
- [ ] **Step 5: Commit** (ERPLibre): `[ADD] long_test: Odoo 18 chat against a real server and its bus`.

### Task 17: Device scenario (ERPLibre)

**Files:**
- Modify: `long_test/mobile_sync_device.py` (`DEVICE_HOOK_API = 2`; scenario `clavardage`, run only for `cible["version"] == 18`)

- Scenario: add the 18 application through the hook; touch the 💬 tile; measure time to the list (≤ 2 s from touch to the list's first row in the DOM, the spec's « slow to send » bar), open « ms chat », type through `taper`, touch ➤; poll the server until chat_user sees the message; chat_user posts a reply; poll the DOM until it appears (realtime through the native plugin over `adb reverse`).
- [ ] **Step 1:** implement; **Step 2:** `./long_test/mobile_sync.py --versions 18 --appareil` with a phone plugged — green; **Step 3: Commit** (ERPLibre): `[ADD] long_test: chat on a plugged phone, tile to realtime reply`.

### Task 18: Contracts, docs, changelogs

**Files:**
- Modify (ERPLibre): `contracts/odoo-api.json` (`chat.data`, `chat.messages`, `chat.post`, `chat.read`, `chat.typing`, `chat.fetched`, `chat.websocket`, `chat.module`, with the shapes of Tasks 5–8; `sqlite_tables_added.chat_*` for migration 2026102501), `contracts/compatibility.json` (`erplibre_mobile_chat` with `source` `odoo18.0/addons/ERPLibre_erplibre_addons/erplibre_mobile_chat`, depends `["mail"]`, optional), `long_test/README.base.md` (chat scenarios, `--versions 18 --filtre chat`) then `mmg`, `CHANGELOG.base.md` then `mmg`.
- Modify (mobile): `CHANGELOG.base.md` (bilingual entry) and its generated files.
- [ ] **Step 1:** edit; **Step 2:** `python3 -c "import json;json.load(open('contracts/odoo-api.json'));json.load(open('contracts/compatibility.json'))"` and `source .venv.erplibre/bin/activate && make doc_markdown` — no diff besides the intended; **Step 3: Commits**: ERPLibre `[UPD] contracts: Odoo 18 chat routes, bus and module`, ERPLibre `[UPD] doc: chat long tests and changelog`, mobile `[UPD] changelog: chat with Odoo 18 Discuss, lot 1`.
