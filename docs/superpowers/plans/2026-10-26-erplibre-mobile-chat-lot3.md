# ERPLibre mobile chat, lot 3 (attachments) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From the phone, send camera photos, gallery photos, any file and
voice messages in an Odoo 18 conversation, online or offline, never lost
and never doubled; see received images as previews, open originals, play
voice, open other files with another app; keep a cache whose space is shown
per conversation and in total, purged on request or, when turned on,
periodically.

**Architecture:** A new native plugin (`ChatFile`, OkHttp) streams
multipart uploads from a file and downloads to a `.part` file, with the
session cookie and a CSRF token scraped from `GET /web/login`. Each file is
a `chat.upload` outbox op chained before its `chat.post` (the post maps
local refs to server ids at drain); uploads run in a lane beside the drain
so a long one never holds another conversation. A new `chat_attachments`
table (migration 2026102604) records every attachment, local copy and byte
count; `ChatAttachmentCache` downloads, previews, measures and purges. The
server module 18.0.1.2.0 adds an idempotent upload route that keeps the
original; without it the app uses Odoo's `/mail/attachment/upload`.

**Tech Stack:** as lots 1–2 (TypeScript, Owl 2, Capacitor 8, SQLite,
Vitest; Java + OkHttp 4.12 for the plugin, JUnit + MockWebServer; Odoo 18
module in Python; ERPLibre long tests) plus `lamejs` (LGPL-3.0) for MP3.

**Spec:** `docs/superpowers/specs/2026-10-25-erplibre-mobile-chat-design.md`
(Lot 3, « Details decided for later lots »). Binding rulings:
`tasks/chat/lot3-decisions.md` (numbered 1–17, cited below as D1…D17).
Odoo 18 and app readings: `tasks/chat/lot3-recon-odoo.md`,
`lot3-recon-mobile.md`, `lot3-recon-tests.md` (not versioned).

Repos, all on `dev/mobile_chat`, never switch, never push:
**M** = `mobile/erplibre_home_mobile`, **A** =
`odoo18.0/addons/ERPLibre_erplibre_addons/erplibre_mobile_chat`, **E** =
the ERPLibre root. Paths below are relative to their repo. `src/public/repo/`
in M is a build copy (vite.config.ts:346), never edited.

## Global Constraints

- Everything in the lot 1 and lot 2 plans' Global Constraints still holds (Odoo 18 only, https/wss policy, catalog + i18n fr/en in the same commit, comments say how code works, nothing identifying anywhere, one commit per task per repo, `[TYPE] scope: subject` ≤ 72 chars, bilingual body, `Assisted-by:` trailer).
- Size limit: the session's `max_file_upload_size` (default 128 MiB = 134217728), read into `SessionInfo.maxUploadSize`; it bounds the whole request, so a file passes when `size + UPLOAD_SLACK_BYTES (65536) <= maxUploadSize`. Refused at pick time with a message naming the limit; a 413 at send refuses the file once, never retried. The note sync's `maxMb` does not apply to chat.
- Wi-Fi: `attachmentSettings().wifiOnly` (localStorage `options.sync.attachments`) holds uploads and originals' downloads off Wi-Fi; previews load whatever the network.
- Upload fields: `thread_id`, `thread_model=discuss.channel`, `is_pending=true`, `csrf_token`, one `ufile`; `voice=true` only for a voice file (never `voice=false`); `client_uuid` only on the module route.
- Module route `POST /erplibre_mobile_chat/attachment/upload` when the module level is `1.2`; otherwise `POST /mail/attachment/upload`. Pending attachments are `res_model=mail.compose.message, res_id=0` (verified: Odoo `mail/controllers/attachment.py:73-81`).
- Post: `post_data.attachment_ids = [ids in pick order]` and top-level `attachment_tokens = ids.map(() => false)` (same length).
- Preview URL `/web/image/<id>/512x512?unique=<checksum>&download=true` (`download=true` turns an error into 404 instead of a placeholder PNG served with 200, `web/controllers/binary.py` `content_image`); original URL `/web/content/<id>?unique=<checksum>&download=true`. Previews two at a time.
- Voice: MP3 mono 128 kbit/s, name `Voice-YYYY-MM-DD-<0..99999>.mp3`, mimetype `audio/mpeg`, 60 s max (auto-stop sends), a tap starts, a tap stops and sends, a separate ✕ discards; one voice per composer, as Odoo.
- Camera photos original by default; « ask to compress » (off by default) asks before sending, compression on the phone to fit 1920 px, JPEG quality 80; it applies to camera and gallery images, not to « any file ». HEIC/HEIF converted to JPEG (quality 92) whatever the setting.
- Cache: purge off by default; limit 2048 MB editable; warning at 80 % of the limit (shown even with purge off); purge removes least recently opened originals first (`COALESCE(last_opened_at, created_at)`), then previews, until under the limit; runs at start and resume when the last run is older than 24 h, and on request. Purge and « clear » never touch a file an outbox op or a pending message still needs.
- Files live under `Directory.Data/chat/<fileDir>/` where `fileDir` is a random id stored per account in `chat_sources.file_dir` (never the configId, url or user name): `out/<localUuid>/<name>` (owned by the outbox), `files/<attachmentId>/<name>` (cached originals), `thumbs/<attachmentId>` (previews).
- Strings through `t()`; new catalog leaves `chat.attachments`, `chat.attachment-view`, `chat.attachment-cache`.

## Review Focus

1. **An upload whose answer is lost**, with the module and without: one `ir.attachment`, one message holding it (Task 6 tests `lost upload answer with the module adopts the first attachment`, `lost upload answer without the module reuses its pending upload`; Task 13 long tests).
2. **Three photos and a text queued offline, the app killed during the second upload, network back:** one message with the three files in pick order and the text; the first file is not uploaded twice (Task 6 test `three files survive a kill during the second upload`).
3. **The server limit lowered after the files were queued (or a proxy answering 413):** that file is refused once with a notice, the text and the other files still go, no request is retried for it (Task 6 test `413 refuses the file once and the text still goes`; Task 13 long test).
4. **« Clear all », a purge or an account rename while an upload waits:** the outgoing file is intact and the server receives the original bytes (Task 7 test `purge and clear never touch an outgoing file`; Task 3 test `rename keeps the file directory`).
5. **An interrupted or expired download:** no truncated file is counted or opened, a preview of an expired session is never cached as the image (Task 2 JUnit `download failure leaves no part file`, Task 7 test `a 404 preview caches nothing and offers retry`).

---

## File Structure

**A** (version → `18.0.1.2.0`): `controllers/attachment.py` (new route), `models/ir_attachment.py` (field, unique index, context uuid on create), `models/discuss_channel.py` (third lock namespace), `tests/test_attachment_upload.py`, manifest, `__init__` files, `i18n/fr_CA.po`.

**M** (new): `android/.../ChatFileTransfer.java` (OkHttp logic, JVM-testable), `android/.../ChatFilePlugin.java` (Capacitor glue: transfers, `toJpeg`, `openWith`), `android/app/src/test/java/ca/erplibre/home/ChatFileTransferTest.java`, `src/plugins/chatFilePlugin.ts`, `src/services/chat/chatFiles.ts` (layout + device files), `chatCsrf.ts`, `chatTransfer.ts`, `chatAttachmentCache.ts`, `chatCapture.ts`, `chatVoice.ts`, `chatMp3.ts` (+ `chatMp3Worker.ts`), `src/services/migrations/addChatAttachments.ts`, `src/testing/chatFakes.ts` (memory files, fake http), components `chat_composer_attach_component.ts|.scss`, `chat_attachments_component.ts|.scss`, `chat_image_viewer_component.ts|.scss`. Modified: `chatOutbox.ts`, `chatService.ts`, `chatRepository.ts`, `chatStore.ts`, `chatModule.ts`, `chatSettings.ts`, `chatLifecycle.ts`, `chatBody.ts`, `outboxService.ts`, `odooRpcClient.ts`, `databaseService.ts`, `migrations/index.ts`, `models/chat.ts`, thread/list/info components, `options_chat_component.ts`, `applications_component.ts`, `applications_edit_component.ts`, `MainActivity.java`, `res/xml/file_paths.xml`, `android/app/build.gradle`, `package.json`, i18n, `featureCatalog.ts`, `src/css/components.scss`, `syncTestKit.ts`, `deviceTestHook.ts`, `CHANGELOG.base.md`.

**E:** `long_test/mobile_sync/chatAttachments.test.ts` (new), `faultProxy.ts`, `odooAdmin.ts`, `chatPeer.ts`, `harness.ts`, `long_test/mobile_sync/fixtures/` (new, generated JPEG + PROVENANCE), `long_test/mobile_sync_odoo.py`, `long_test/mobile_sync_device.py`, `test/test_mobile_sync_harness.py`, `contracts/odoo-api.json`, `contracts/compatibility.json`, `long_test/README.base.md`, `CHANGELOG.base.md`.

---

### Task 0: Lot 2 carry-overs (D17)

**Files:** M `src/components/chat/chat_new_component.ts:199-216`, `src/components/chat/chat_info_component.ts:314`, `src/services/chat/chatOutbox.ts:987-1028` (`sendCreate`), tests `chatNewComponent.test.ts`, `chatInfoComponent.test.ts`, `chatOutbox.test.ts`; E `long_test/README.base.md:387,842`.

**Interfaces:** none new.

- [ ] **Step 1: Failing tests:**
  - `new conversation lists only servers where the user is internal` (`init()` keeps a source when `sourceState.isInternalUser || !loadedAt`, the list's ＋ rule at `chat_list_component.ts:266`).
  - `cancel the creation is offered only before the create was sent` (pending op without `params.createSentAt` → shown; with it → hidden and Leave shown; `failed` and `ambiguous` keep the cancel).
  - `a stale createOpId without its op offers no cancel` (`canCancelCreate` needs the op found).
  - `a create whose own temp pair exists settles at once from channel info` (pair stored by `repo.putTempId`, op `attempts > 1` inside the quiet window → `/discuss/channel/info {channel_id: pair.realId}` read, `settleCreate` run, no `OutboxRetryLaterError`, no create call).
  - The pending-create info test uses a real temporary id (negative id from `createGroup` offline), not a hand-written row.
- [ ] **Step 2–4:** FAIL → implement (in `sendCreate`, before `quietStamp`: `const own = await this.repo.realIdOf(op.configId, op.params.channelId)`; when set, read channel info and settle) → PASS; `npm test`.
- [ ] **Step 5:** rewrap `long_test/README.base.md` lines 387 and 842 to the file's width, regenerate with mmg (skill `erplibre-doc-i18n`).
- [ ] **Step 6: Commits:** M `[FIX] chat: lot 2 residuals, create cancel and settle rules`; E `[UPD] doc: long test README lines rewrapped`.

### Task 1: Server module 18.0.1.2.0 — idempotent upload route (D3)

**Files:** A `__manifest__.py` (version `18.0.1.2.0`, summary/description mention uploads), `__init__.py` (`from . import controllers, models`), `controllers/__init__.py`, `controllers/attachment.py`, `models/__init__.py`, `models/ir_attachment.py`, `models/discuss_channel.py:15-18` (add `LOCK_NAMESPACE_ATTACHMENT = 0x45524C03`), `tests/__init__.py`, `tests/test_attachment_upload.py`, `i18n/fr_CA.po`.

**Interfaces:**
- Field `ir.attachment.erplibre_client_uuid` (Char, `index="btree_not_null"`, `copy=False`, `readonly=True`); `init()` calls `erplibre_ensure_unique_uuid_index(cr, "ir_attachment", "ir_attachment_erplibre_client_uuid_uniq", ["create_uid", "erplibre_client_uuid"])` (helper of `models/mail_message.py:13-41`, which pre-dedupes on upgrade).
- `ir.attachment.create(vals_list)` override: when `self.env.context.get("erplibre_attachment_uuid")` is set and a vals has no `erplibre_client_uuid`, store it there. (A context key distinct from lot 2's `erplibre_client_uuid`, which `discuss.channel.create` reads.)
- Controller `ErplibreAttachmentController(AttachmentController)` (Odoo's `mail/controllers/attachment.py`), route `/erplibre_mobile_chat/attachment/upload`, `methods=["POST"], type="http", auth="public"`, CSRF left on: `erplibre_attachment_upload(self, ufile, thread_id, thread_model, client_uuid=None, is_pending=False, **kwargs)`:
  - public user (expired session) or `thread_model != "discuss.channel"` → `NotFound` (the same answer Odoo's route gives an expired session); no `client_uuid` → `BadRequest`;
  - `erplibre_lock_uuid(request.env, LOCK_NAMESPACE_ATTACHMENT, client_uuid)`; an attachment of `create_uid = uid` with that uuid (searched under sudo) → `request.make_json_response({"data": Store(existing, extra_fields=["access_token"]).get_result()})`, no new record, no second voice metadata;
  - otherwise `request.update_context(image_no_postprocess=True, erplibre_attachment_uuid=client_uuid)` then `return self.mail_attachment_upload(ufile, thread_id, thread_model, is_pending=is_pending, **kwargs)` — Odoo's own checks, company, pending placeholders, `_post_add_create(voice=…)` and response shape are reused unchanged.

- [ ] **Step 1: Failing tests** (`HttpCase`, upload as in Odoo's `mail/tests/discuss/test_message_controller.py:499-503`, `csrf_token: http.Request.csrf_token(self)`): `test_upload_same_uuid_twice_gives_one_attachment` (same id in both answers, one row), `test_uuid_of_other_user_not_adopted`, `test_upload_without_uuid_refused`, `test_public_user_gets_not_found`, `test_pending_upload_is_placeholder` (`res_model == "mail.compose.message"`, `res_id == 0`), `test_large_jpeg_kept_original` (a 2400×1600 JPEG made with PIL: stored `checksum` = sha1 of the sent bytes, width still 2400) and `test_odoo_route_reduces_large_jpeg` (same file through `/mail/attachment/upload`: max side 1920), `test_voice_sets_voice_metadata` (`voice_ids` non-empty; Store `voice: true`), `test_retry_does_not_add_voice_metadata`, `test_upload_takes_advisory_lock` (as `test_create_takes_advisory_lock`), `test_unique_index_refuses_duplicate_attachment`, `test_upgrade_clears_duplicate_uuids` (index dropped, two rows with one uuid, `init()` → one keeps it), `test_post_links_uploaded_attachment` (post with `attachment_ids` + `attachment_tokens=[False]` moves it onto the message).
- [ ] **Step 2–4:** run `.venv.odoo18.0_python3.12.10/bin/python odoo18.0/odoo/odoo-bin -c config.conf -d chat_module_test -i erplibre_mobile_chat --test-tags /erplibre_mobile_chat --stop-after-init --log-level=test` FAIL → implement → PASS (every earlier test still green); `dropdb chat_module_test`.
- [ ] **Step 5: Commit** (A): `[IMP] erplibre_mobile_chat: idempotent upload route keeping originals`.

### Task 2: Native transport, app files, CSRF, upload limit (D1, D2, D7)

**Files:** M create `android/app/src/main/java/ca/erplibre/home/ChatFileTransfer.java`, `ChatFilePlugin.java`, `android/app/src/test/java/ca/erplibre/home/ChatFileTransferTest.java`, `src/plugins/chatFilePlugin.ts`, `src/services/chat/chatFiles.ts`, `chatCsrf.ts`, `chatTransfer.ts`, `src/testing/chatFakes.ts`; modify `MainActivity.java:26` (`registerPlugin(ChatFilePlugin.class)`), `android/app/build.gradle:143` (`testImplementation "com.squareup.okhttp3:mockwebserver:4.12.0"`), `src/services/odoo/odooRpcClient.ts:22-39,363-392`; tests `chatFilePlugin.test.ts`, `chatFiles.test.ts`, `chatCsrf.test.ts`, `chatTransfer.test.ts`, `odooRpcClient` session-info test.

**Interfaces:**
- Java `ChatFileTransfer` (no Capacitor types): one `OkHttpClient` (connect 30 s, write 120 s, read 300 s, no call timeout, `followRedirects(false)`, no CookieJar so the explicit `Cookie` header is sent as given); `getText(url, headers)`, `upload(id, url, headers, fields, File file, name, mimetype, Progress)` (multipart: the fields, then `ufile` streamed from the file), `download(id, url, headers, File target, Progress)` (streams to `target + ".part"`, sha1 while writing, renames on 2xx, deletes the part otherwise and on any error), `cancel(id)`. A failure before `requestHeadersStart` (OkHttp `EventListener`) throws `UnsentException`. `File resolveInside(File chatRoot, String uri)` refuses any path outside `filesDir/chat` (canonical paths).
- Plugin `ChatFile` methods: `getText`, `upload({id,url,headers,fields,file:{uri,name,mimetype}}) → {status,headers,data}`, `download({id,url,headers,uri}) → {status,size,sha1,mimetype}`, `cancel({id})`; rejects with code `UNSENT` for `UnsentException`; event `chatFileProgress {id, done, total}` at most every 250 ms. Transfers run on a worker thread, never the bridge thread.
- TS `chatFilePlugin.ts`: `ChatFile` (registerPlugin), `CHAT_FILE_UNSENT`, `nativeChatHttp(): ChatHttp`.
- `chatFiles.ts`: `interface ChatHttp { getText(url, headers): Promise<HttpAnswer>; upload(r: UploadRequest): Promise<HttpAnswer>; download(r: DownloadRequest): Promise<DownloadAnswer>; cancel(id: string): Promise<void>; onProgress(fn: (p: TransferProgress) => void): () => void }` with `HttpAnswer {status; headers: Record<string,string>; data: string}`, `UploadRequest {id; url; headers; fields: Record<string,string>; file: {uri; name; mimetype}}`, `DownloadRequest {id; url; headers; uri}`, `DownloadAnswer {status; size; sha1: string|null; mimetype: string|null}`, `TransferProgress {id; done; total: number|null}`; `interface ChatFiles { uri(rel): Promise<string>; webUrl(rel): Promise<string>; size(rel): Promise<number|null>; writeBlob(rel, blob: Blob): Promise<number>; copyFrom(source: string, rel): Promise<number>; rename(from, to): Promise<void>; remove(rel): Promise<void>; removeDir(rel): Promise<void> }`; `deviceChatFiles` (Filesystem, `Directory.Data`; `writeBlob` appends base64 chunks of `WRITE_CHUNK_BYTES = 768 * 1024`, so a picked file is never whole in JS memory); `safeFileName(name)` (no `/ \` or controls, no leading dot, ≤ 120 chars, extension kept), `outgoingPath(fileDir, localUuid, name)`, `originalPath(fileDir, attachmentId, name)`, `previewPath(fileDir, attachmentId)`, `sourceDir(fileDir)` = `chat/<fileDir>`.
- `chatCsrf.ts`: `class ChatCsrf { constructor(rpc: OdooRpcClient, http: ChatHttp); token(creds, sessionId): Promise<string>; forget(sessionId): void }` — cache keyed by session id (a re-authentication gives a new id, so a new token); `GET <base>/web/login` (no `redirect` param, `Cookie: session_id=…`), token from `name="csrf_token" value="…"` else `csrf_token: "…"`; a 3xx or no token → `Error`.
- `chatTransfer.ts`: `MODULE_UPLOAD_ROUTE`, `ODOO_UPLOAD_ROUTE`, `UPLOAD_SLACK_BYTES = 65536`, `class ChatFileTooBigError`, `class ChatTransferRefusedError { reason: "refused"|"not_found" }`, `class ChatTransfer { constructor(rpc, http, files, csrf); upload(creds, a: {id: string; route: string; channelId: number; clientUuid: string|null; voice: boolean; path: string; name: string; mimetype: string}): Promise<any /* the ir.attachment Store record */>; download(creds, a: {id: string; urlPath: string; path: string}): Promise<DownloadAnswer>; cancel(id: string): Promise<void> }`. Both run in `rpc.callWithAuth`: a first 404, or a 400 whose body says invalid CSRF token, forgets the token and throws `SessionExpiredError` (re-auth, new token, one retry: an expired session reads as public on these `auth=public` routes, and a session gone from the store gets a new sid that fails CSRF first); a second 404 → `ChatTransferRefusedError("not_found")`; 413 → `ChatFileTooBigError`; 200 with `{error}` → `ChatTransferRefusedError("refused")`; UNSENT → `RequestNotSentError`; `assertUrlAllowed` applies.
- `SessionInfo.maxUploadSize: number` (`max_file_upload_size`, else 134217728); a `fresh` read renews it with the global mute.
- `src/testing/chatFakes.ts`: `memoryChatFiles(): ChatFiles & { bytes(rel): Uint8Array|undefined; put(rel, bytes) }`, `fakeChatHttp(handlers): ChatHttp & { calls: Array<{kind, url, fields?, file?}> }`.

- [ ] **Step 1: Failing JUnit** (`ChatFileTransferTest`, MockWebServer): `upload streams fields then the file as ufile` (parsed parts, bytes equal), `explicit cookie header reaches the server`, `download writes then renames and reports sha1`, `download failure leaves no part file` (500 and a socket cut mid-body: no target, no `.part`), `connection refused is unsent`, `path outside the chat root is refused` (`../`).
- [ ] **Step 2: Failing Vitest:** bridge forwards fields and maps UNSENT; `safeFileName` cases; `writeBlob` writes 3 chunks for a 2 MiB blob; CSRF parse of both forms, cached per session id, a new id fetches again, redirect → error; transfer: `404 then re-auth uploads once`, `404 twice is not_found`, `invalid CSRF re-auths with a new token`, `413 is too big and not retried`, `200 with error is refused`; session info reads `max_file_upload_size` and the default.
- [ ] **Step 3: Implement.** Run `cd android && ./gradlew :app:testDebugUnitTest --tests 'ca.erplibre.home.ChatFileTransferTest'` and `npm test` → PASS; `npm run build`.
- [ ] **Step 4: Commit** (M): `[ADD] chat: native file transfer, app file layout, CSRF token`.

### Task 3: Attachments table, parsing, repository (D8, D15)

**Files:** M create `src/services/migrations/addChatAttachments.ts`; modify `migrations/index.ts` (`{version: 2026102604, description: "Clavardage : pièces jointes et leur cache", run: addChatAttachments}`), `databaseService.ts:1193-1301` (`createChatTables` gets the table and the two `chat_sources` columns), `:1350` (new `addChatAttachments()` beside `addChatLeftUnsent`, guarded by `PRAGMA table_info`), `:1379-1397` (`renameChatRows` list gains `chat_attachments`), `models/chat.ts`, `chatStore.ts:14-25,76-252,269-281`, `chatRepository.ts:312` (`applyDelta`), `:527` (`swapChannelId`), `:769` (`dropSource`), `chatService.ts:1174` (`applyOne`), tests `chatRepository.test.ts`, `chatStore.test.ts`, `chatService.test.ts`.

**Interfaces:**
- Table `chat_attachments`: `id TEXT PK` (`configId#a<attachmentId>` or `configId#l<localUuid>`), `config_id TEXT NOT NULL`, `channel_id INTEGER NOT NULL`, `message_id INTEGER`, `attachment_id INTEGER`, `local_uuid TEXT`, `post_client_uuid TEXT`, `seq INTEGER NOT NULL DEFAULT 0`, `name TEXT NOT NULL`, `mimetype TEXT NOT NULL`, `size INTEGER NOT NULL`, `checksum TEXT`, `voice INTEGER NOT NULL DEFAULT 0`, `thumb_path TEXT`, `thumb_bytes INTEGER NOT NULL DEFAULT 0`, `original_path TEXT`, `original_bytes INTEGER NOT NULL DEFAULT 0`, `state TEXT NOT NULL`, `error TEXT`, `last_opened_at TEXT`, `created_at TEXT NOT NULL`; indexes `(config_id, channel_id)`, `(config_id, message_id)`, `(config_id, post_client_uuid)`. `chat_sources` gains `file_dir TEXT`, `module_level TEXT`.
- `ChatAttachment` (camelCase of the columns, `voice: boolean`), `ChatAttachmentState = "queued" | "uploaded" | "posted" | "refused"` (`posted` also for every attachment read from the server), `OutgoingFile = { localUuid; path; name; mimetype; size; voice }`. `ChatSourceState` gains `fileDir: string|null`, `moduleLevel: "1.0"|"1.1"|"1.2"|null`.
- `StoreDelta` gains `attachments: (Partial<ChatAttachment> & {attachmentId: number})[]`, `deletedAttachmentIds: number[]`; a message partial gains `attachmentIds?: number[]` (from `attachment_ids`, bare ints or `{id}`), not stored on `chat_messages`. `parseStore` copies `ir.attachment` `id, checksum, mimetype, name, size, voice` and the channel from `thread`; `mergeDeltas` merges both.
- `applyDelta`: upserts server fields only (paths, bytes, state of local work, `lastOpenedAt` kept); a message carrying `attachmentIds` sets their `message_id` and drops its other rows; a deleted channel drops its rows except `queued`/`uploaded`; dropped rows' file paths go to `repo.onFilesReleased(paths: string[])` (default no-op, wired in Task 7).
- `ChatService.applyOne` handles `ir.attachment/delete {id}` → `repo.deleteAttachments(configId, [id])`.
- `ChatRepository`: `fileDirOf(configId): Promise<string>` (creates and stores a uuid once), `putOutgoing(rows: ChatAttachment[])`, `outgoingOf(configId, postClientUuid)` (by `seq`), `setUploaded(configId, localUuid, s: {attachmentId, checksum, size, mimetype, name})`, `setRefused(configId, localUuid, reason: string)`, `requeueUpload(configId, localUuid)`, `adoptOutgoing(configId, postClientUuid, messageId): Promise<ChatAttachment[]>` (rows re-keyed `#a<id>`, merged into a row the bus already wrote, state `posted`), `attachmentsOf(configId, channelId, messageIds: number[], postClientUuids: string[]): Promise<Map<string, ChatAttachment[]>>` (keys `m<id>` / `u<uuid>`), `setPreview(configId, attachmentId, path, bytes)`, `setOriginal(configId, attachmentId, path, bytes)`, `touchOpened(configId, attachmentId, at)`, `attachmentBytes(configId?, channelId?): Promise<number>` (`SUM(thumb_bytes + original_bytes)`), `cachedRows(): Promise<ChatAttachment[]>` (rows with a file, oldest `COALESCE(last_opened_at, created_at)` first), `clearFiles(keys: string[], what: "original"|"preview"|"both")`, `deleteAttachments(configId, ids): Promise<string[]>`, `deleteOutgoing(configId, localUuids): Promise<string[]>`. `swapChannelId` moves the rows; `dropSource` deletes them.

- [ ] **Step 1: Failing tests:** migration on a database at 2026102603 (tables present) adds the table and columns, a second run changes nothing, a fresh install has them; parse of a `/discuss/channel/messages` Store with two attachments (voice flag, thread) and of a post answer; `mail.record/insert` with fewer `attachment_ids` drops the other row; `ir.attachment/delete` releases its paths; channel delete keeps an outgoing row; `adoptOutgoing` merges with a bus row and keeps local paths; `rename keeps the file directory` (renameChatRows moves rows and `file_dir`); `dropSource` removes the rows; `attachmentBytes` per channel and total.
- [ ] **Step 2–4:** FAIL → implement → PASS; `npm test`.
- [ ] **Step 5: Commit**: `[ADD] chat: attachments table, Store parsing, cache rows`.

### Task 4: Module 1.2 detection and features (D3)

**Files:** M `chatModule.ts`, `chatService.ts:335,476-491,818-822`, `applications_edit_component.ts`, i18n, tests `chatModule.test.ts`, `applicationsEditChatModule.test.ts`, `chatService.test.ts`.

**Interfaces:**
- `moduleLevel(capabilities, creds, opts: {online; fresh?}): Promise<"1.2"|"1.1"|"1.0"|null>` — `CHAT_UUID_FIELD` on `ir.attachment` → 1.2, else on `discuss.channel` → 1.1, else on `mail.message` → 1.0. `moduleState`: `installed` only at 1.2; `outdated` at 1.0 or 1.1 (an older module's row reads `installed` until upgraded, so the level decides); `available`/`absent`/`unknown` as before when the level is null. `upgradeModule` accepts 1.1.
- Load and `probeModule` store `moduleLevel` with `moduleState`.
- `levelAtLeast(level, min: "1.0"|"1.1"|"1.2"): boolean` (null is below all). `features(configId)` → `{ canRemoveMembers: isSystem && levelAtLeast(level, "1.1"), idempotentCreate: levelAtLeast(level, "1.1"), idempotentUpload: levelAtLeast(level, "1.2") }` (with `moduleMode === "auto"`); `send` uses the module for posts when the level is not null.
- Edit screen: `chat.module_outdated` text says the upgrade brings attachments sent once and photos kept original.

- [ ] **Step 1: Failing tests:** level matrix (three fields / two / one / none × system or not); a 1.1 server keeps `idempotentCreate` and `canRemoveMembers` but no `idempotentUpload`; admin on 1.1 sees the upgrade; upgrade then probe → installed.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit**: `[ADD] chat: module 1.2 detection, idempotent upload feature`.

### Task 5: Outbox engine — held operations, kinds left to the caller (D5, D6)

**Files:** M `src/services/outboxService.ts:51-56,259-292,322-348`, the two `DrainResult` literals (`outboxService.ts:327`, `chatOutbox.ts:758`), test `outboxService.test.ts`.

**Interfaces:**
- `class OutboxHeldError extends Error { constructor(message: string, readonly heldFor: string) }`: thrown by a handler that must wait for a condition (no server contacted). `recordFailure` for it: `status "queued"`, `attempts` as stored, `params.heldFor`, no `nextAttemptAt`, no `onRetryScheduled`. In `drain` it counts as `held`; the op holds its dependents for this pass.
- `DrainResult.held: number`.
- `drain` option `skipKinds?: Set<string>`: ops of those kinds are not run; they still hold their dependents.

- [ ] **Step 1: Failing tests:** `a held op keeps its attempts and gets no retry delay`; `a held op is run again by the next drain`; `a held op holds its dependent`; `skipped kinds are not run and hold their dependents`.
- [ ] **Step 2–4:** FAIL → implement → PASS; `npm test`.
- [ ] **Step 5: Commit**: `[ADD] outbox: held operations and kinds left to the caller`.

### Task 6: Chat outbox — uploads and posts with files (D4, D5, D6, D7)

**Files:** M `chatOutbox.ts` (constants `:19-76`, constructor `:194-200`, `queuePost`/`queuePostNow` `:234-294`, `sendPost` `:846-912`, `settleNow` `:952`, `flush` `:755-762`, `pendingPostCount` `:764`), `chatService.ts:146-172,487-503`, tests `chatOutbox.test.ts`, `chatService.test.ts`.

**Interfaces:**
- `CHAT_UPLOAD = "chat.upload"`, params `{channelId, localUuid, path, name, mimetype, size, voice, useModule, uploadSentAt?, uploadEndedAt?, heldFor?}` (`uploadSentAt` stamped once, at the first send that may reach the server); the op's `clientUuid` is the `client_uuid` sent. `CHAT_FILE_REFUSED = "chat.file_refused"` (notice, in `NOTICE_KINDS`), params `{channelId, name, reason: "too_big"|"missing"|"refused"|"not_found", limit?}`. `CHAT_POST` params gain `files: string[]` (local uuids, pick order), `reuploaded?: boolean`. `CHAT_UPLOADS_AT_ONCE = 2` (per account).
- `ChatOutbox.queuePost(configId, channelId, text, useModule, opts: { files?: OutgoingFile[]; idempotentUpload?: boolean } = {})`: in `exclusive`, the chain is `tail ← upload₁ ← … ← uploadₙ ← post` (`dependsOn` is single-valued, so the uploads are linear and each runs just before its post); rows `queued` with `postClientUuid` = the post's uuid and `seq`; the tail search keeps `kind === CHAT_POST` (an upload always has its post after it). A conversation that cannot take a post stores the rows `refused` (`error "channel"`) beside the failed message.
- `ChatOutbox.files: ChatFiles`, `transfer: ChatTransfer`, `onWifi: () => Promise<boolean>` (default `deviceAttachmentIO.onWifi`), set by ChatService.
- `runUpload`: leaving → row refused `"left"`, done; `wifiOnly && !onWifi()` → `setParams({heldFor: "wifi"})`, throw `OutboxHeldError`; offline → `RequestNotSentError`; file gone → refuse `missing`; `size + UPLOAD_SLACK_BYTES > maxUploadSize` → refuse `too_big`; then in `attempt`: module route with `clientUuid`, else on `attempts > 1` wait `CREATE_QUIET_WINDOW_MS` after `uploadEndedAt` (`OutboxRetryLaterError`), then `search_read ir.attachment [["res_model","=","mail.compose.message"],["res_id","=",0],["create_uid","=",uid],["name","=",name],["file_size","=",size],["create_date",">=", uploadSentAt − CREATE_CLOCK_SKEW_MS]]` order `id asc` limit 1 → reuse, else upload. A failed send other than `RequestNotSentError` stamps `uploadEndedAt = now`. `ChatFileTooBigError` → refuse `too_big`; `ChatTransferRefusedError` → refuse with its reason. Refusing = row `refused`, a `CHAT_FILE_REFUSED` notice, the op done (the post goes on). Success → `repo.setUploaded`.
- `sendPost`: ids = `outgoingOf(...)` rows `uploaded`, in `seq`; a `queued` row left → plain `Error` (retry later); no text and no id → the message fails, the op is cancelled; `post_data.attachment_ids` + `attachment_tokens`; a refused post with ids and no `reuploaded`: ids missing from `search_read ir.attachment [["id","in",ids]]` are requeued (`requeueUpload`, new upload ops chained before the post, `reuploaded: true`), then `OutboxRetryLaterError(now)`; otherwise blocked as today. After `settleNow`: `adoptOutgoing`, files renamed `out/…` → `files/<id>/…` and recorded as originals (the sender never downloads its own file).
- Upload lane: `flush` drains with `skipKinds: {CHAT_UPLOAD}` then `pumpUploads(creds, configId, force)`: starts due upload ops whose dependency is gone, up to `CHAT_UPLOADS_AT_ONCE` running for the account, not awaited; each finished upload calls `flush` again for its account and `changed(configId, channelId)`. `whenIdle(configId?): Promise<void>` resolves when no upload runs (tests, hook). `uploadProgress(localUuid): {done, total} | null` from `ChatHttp.onProgress`. `pendingUploadCount(configId)`.
- `ChatService.send(src, channelId, text, files: OutgoingFile[] = [])` (text may be empty with files; `idempotentUpload` from `features`); `ChatService.fileDirOf(configId)`; `ChatService.useFileIO({files, http, onWifi?})` replaces the device ones (unit tests, the kit); the defaults are `deviceChatFiles` and `nativeChatHttp()`.

- [ ] **Step 1: Failing tests** (fake http from `chatFakes.ts` over the fake Odoo of `chatService.test.ts:75-158`, whose post handler now echoes `attachment_ids` with `ir.attachment` records):
  - `a post with two files uploads them in order then posts their ids` (exact fields, `attachment_tokens: [false, false]`, voice field absent).
  - `voice sends voice=true`; `the module route sends client_uuid`.
  - `lost upload answer with the module adopts the first attachment` (RF1: the fake dedupes by uuid; one attachment).
  - `lost upload answer without the module reuses its pending upload` (RF1: domain exact, no second upload after the window).
  - `three files survive a kill during the second upload` (RF2: op 2 left `running`, `recoverInterrupted` + new ChatOutbox over the same db; file 1 uploaded once, one post with three ids in order).
  - `413 refuses the file once and the text still goes` (RF3: notice, row refused, post without it, one upload call after two later flushes).
  - `a file over the session limit is refused without a request`; `a missing file is refused with a notice`.
  - `wifi only holds the upload without attempt or delay; Wi-Fi sends it`.
  - `a long upload does not hold another conversation's post` (upload promise left pending; the other channel's post completes; a later post of the same channel waits).
  - `a post refused for a vanished attachment re-uploads it once`.
  - `a settled post's files become the conversation's cache, no download`.
  - `leaving cancels the conversation's uploads`; `a temporary id swap reaches upload ops and rows`.
- [ ] **Step 2–4:** FAIL → implement → PASS; `npm test`.
- [ ] **Step 5: Commit**: `[ADD] chat: upload outbox kind, posts with files, Wi-Fi hold`.

### Task 7: Cache — downloads, previews, space, purge (D7, D9, D10, D11)

**Files:** M create `src/services/chat/chatAttachmentCache.ts`; modify `chatSettings.ts`, `chatService.ts` (construct and wire; `erase` `:962-965`, `recover` `:842`, `flushAll` `:971`), `chatRepository.ts` (wire `onFilesReleased`), tests `chatAttachmentCache.test.ts`, `chatSettings.test.ts`.

**Interfaces:**
- `ChatSettings` gains `cachePurge: boolean` (false), `cacheLimitMb: number` (2048; a non-finite or ≤ 0 value reads as 2048), `askCompress: boolean` (false); same key `options.chat`. `CACHE_WARN_RATIO = 0.8`, `PURGE_EVERY_MS = 24 h`, `PREVIEWS_AT_ONCE = 2`, `PREVIEW_PX = 512`; last purge in localStorage `chat.cache.lastPurgeAt`.
- `class ChatAttachmentCache { constructor(repo, files, transfer, onWifi, now) }`:
  - `preview(src, att): Promise<string|null>` — cached path, or fetched (queue of two, the newest request first) to `previewPath`; a failure records `previewFailed(attachmentId)` and returns null; `retryPreview(id)`.
  - `open(src, att, opts: {anyNetwork?: boolean} = {}): Promise<{kind: "ready", path} | {kind: "waiting_wifi"} | {kind: "gone"} | {kind: "failed"}>` — cached original (touches `lastOpenedAt`), else held off Wi-Fi when `wifiOnly` and not `anyNetwork` — voice originals included (the user's decision) — (remembered and started by `resumeWaiting()`, which `flushAll` calls), else downloaded to `originalPath`; a sha1 different from `checksum` deletes the file → failed; `not_found` → gone. `downloadProgress(id)`, `cancel(id)`.
  - `space(configId?, channelId?)`, `warning(): Promise<boolean>` (total ≥ ratio × limit), `clear(scope: {configId?: string; channelId?: number})` (files of `posted`/`refused` rows only; rows stay), `purge(): Promise<{freed: number}>` (D9 order, stamps the time), `maybePurge()` (on and older than 24 h), `sweep(configId)` (outgoing rows whose post has neither an op nor a message → rows and files removed), `erase(configId)` (removes `sourceDir(fileDir)`).
- `ChatService.attachments: ChatAttachmentCache`; `erase` removes files then rows; `recover` sweeps every account; drops (`dropChannels`, `dropTaken`, `dropAll`, `discardCreate`) sweep their account.

- [ ] **Step 1: Failing tests:** `preview fetches the sized image with unique and download, two at a time`; `a 404 preview caches nothing and offers retry` (RF5); `open downloads, checks sha1, counts the bytes`; `a sha1 mismatch keeps no file`; `wifi only waits for an original, voice included, never for a preview`; `anyNetwork downloads one held original at once and only that one`; `cancel leaves no file`; `space per conversation and total`; `purge and clear never touch an outgoing file` (RF4); `purge off removes nothing; on frees least recently opened originals, then previews, under the limit`; `maybePurge runs once per 24 h`; `warning at 80 % even with purge off`; `erasing an account removes its directory`; `sweep removes outgoing files nothing needs`; `a bus attachment delete removes its files`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit**: `[ADD] chat: attachment cache, previews, downloads and purge`.

### Task 8: Capture — camera, gallery, any file (D13, D14)

**Files:** M create `src/services/chat/chatCapture.ts`; modify `ChatFilePlugin.java` (`toJpeg`), `chatFilePlugin.ts`, tests `chatCapture.test.ts`, JUnit `ChatImageSizeTest.java`.

**Interfaces:**
- `ChatFile.toJpeg({from, to, maxPx, quality}) → {size, width, height}`: decodes with `ImageDecoder` (API ≥ 28, applies EXIF orientation; HEIC/HEIF readable) or `BitmapFactory` + `ExifInterface` rotation below; `maxPx` 0 keeps the size, else fits the long side; writes JPEG at `quality`. Pure helper `ChatImageSize.fit(w, h, maxPx)` for JUnit. On API < 28 a HEIC is sent as is.
- `chatCapture.ts`: `pickFiles(input: HTMLInputElement, kind: "camera"|"gallery"|"file"): Promise<File[]>` (camera: `accept="image/*" capture="environment"`; gallery: `accept="image/*" multiple`; file: `multiple`, no accept); `stage(fileDir, file: File, opts: {maxUploadSize}): Promise<OutgoingFile | {refused: "too_big", limit: number}>` (size checked before any write; `writeBlob` to `outgoingPath`; HEIC/HEIF → `toJpeg(quality 92)`, name `.jpg`; a camera file named `IMG_<yyyyMMdd_HHmmss>.jpg`); `compress(file: OutgoingFile): Promise<OutgoingFile>` (`toJpeg(1920, 80)`, only JPEG/PNG/HEIC images); `ensureCameraPermission(): Promise<boolean>` (`Camera.requestPermissions({permissions: ["camera"]})`).
- Camera through the WebView chooser: Capacitor's `BridgeWebChromeClient.showImageCapturePicker` (`node_modules/@capacitor/android/.../BridgeWebChromeClient.java:328-350`) launches `ACTION_IMAGE_CAPTURE` with `EXTRA_OUTPUT`, so the file is the camera app's own; it needs the CAMERA permission granted because the merged manifest declares it, and the `IMAGE_CAPTURE` `<queries>` entry (both present in the last debug build's merged manifest). The camera plugin is not used: `chooseFromGallery` re-encodes through a Bitmap (`IONCAMRMediaProcessor.processResultFromGallery` → `processPicture(Bitmap,…)`, javap of `ioncamera-android-1.0.0`).

- [ ] **Step 1: Verify on the phone (record the outcome in `tasks/chat/lot3-ledger.md`):** build the debug APK, open devtools on the WebView, run a page snippet creating `<input type=file accept="image/*" capture="environment">`, take a photo; compare the received `File` (size, first bytes, EXIF Make/Model through `exiftool` after `adb pull` of a copy) with a photo of the stock camera app. Also check `aapt dump permissions` and `<queries>` on the built APK. Pass = same EXIF maker data and no re-encode. **Fallback** if the chooser does not open the camera or re-encodes: a native `ChatFile.capturePhoto({to})` (`ACTION_IMAGE_CAPTURE`, `EXTRA_OUTPUT` = FileProvider uri of `to`), behind the same `pickFiles("camera")` signature.
- [ ] **Step 2: Failing tests:** `a picked file is staged under the account's out dir`; `gallery multi-pick keeps the order`; `HEIC becomes JPEG with a .jpg name`; `a file over the limit is refused before any write`; `compress fits 1920 px at quality 80`; `camera permission refused gives no file`; JUnit `fit` cases (landscape, portrait, already small, 0).
- [ ] **Step 3–4:** implement → PASS; JUnit and `npm test`; `npm run build`.
- [ ] **Step 5: Commit**: `[ADD] chat: camera, gallery and file capture, HEIC to JPEG`.

### Task 9: Voice — record, MP3, 60 s (D12)

**Files:** M `package.json` (`lamejs` exact version), create `src/services/chat/chatVoice.ts`, `chatMp3.ts`, `chatMp3Worker.ts`, tests `chatVoice.test.ts`, `chatMp3.test.ts`.

**Interfaces:**
- `chatMp3.ts`: `encodeMp3(samples: Float32Array, sampleRate: number): Uint8Array` (mono, 128 kbit/s, 1152-sample blocks, Int16 clamp, flush); `mixToMono(buffer: AudioBuffer): Float32Array`; `voiceName(now: Date, random = Math.random): string` → `Voice-YYYY-MM-DD-<0..99999>.mp3`. `chatMp3Worker.ts` runs `encodeMp3` off the UI thread (`new Worker(new URL("./chatMp3Worker.ts", import.meta.url), {type: "module"})`).
- `chatVoice.ts`: `VOICE_MAX_MS = 60000`; `class ChatVoiceRecorder { start(): Promise<"recording"|"denied"|"unavailable">; elapsedMs(): number; remainingMs(): number; stop(fileDir): Promise<OutgoingFile>; discard(): Promise<void>; onAutoStop: (() => void) | null }` over `capacitor-voice-recorder` (`hasAudioRecordingPermission` / `requestAudioRecordingPermission` at first use, `startRecording({directory: Directory.Data})`); `stop` reads the AAC file, `decodeAudioData`, mixes to mono, encodes, `writeBlob` to `outgoingPath`, deletes the AAC; at 60 s the recorder stops itself and calls `onAutoStop` (the composer sends). App to the background while recording: stop and keep the file as an unsent voice chip; thread unmount: discard.

- [ ] **Step 1: Verify on the phone:** in the debug build's devtools, record 3 s with the plugin, then `await new AudioContext().decodeAudioData(arrayBuffer)` of the `.aac` read back through `Filesystem.readFile`; pass = an `AudioBuffer` of about 3 s. Record the outcome in the ledger. **Fallback** if it rejects: `ChatFile.decodePcm({from, to}) → {sampleRate}` (MediaCodec mono 16-bit PCM at the source rate, extending `android/.../AudioConverter.java`, which already decodes AAC for transcription), and `stop` encodes that PCM.
- [ ] **Step 2: Verify the bundle:** `lamejs` imports under Vite and Vitest (`new Mp3Encoder(1, 44100, 128)` in a test, `npm run build`). **Fallback** if the 1.2.1 package fails as an ES module (missing `MPEGMode` global): the `@breezystack/lamejs` fork, same LGPL-3.0 licence.
- [ ] **Step 3: Failing tests:** `encodeMp3 makes mono 128 kbit/s frames` (first frame header `0xFF 0xFB`, bitrate index 9, channel-mode bits `11` at 44.1 kHz); `voiceName format and range`; `stop before 60 s gives an MP3 OutgoingFile with voice true and audio/mpeg`; `60 s stops by itself and calls onAutoStop`; `discard deletes the recording`; `permission asked once, denied gives no recording`; `background keeps the recording unsent`.
- [ ] **Step 4–5:** implement → PASS; `npm run build`.
- [ ] **Step 6: Commit**: `[ADD] chat: voice messages recorded as MP3, 60 s limit`.

### Task 10: Composer — attach, chips, voice (D14)

**Files:** M create `src/components/chat/chat_composer_attach_component.ts|.scss` (`@use` in `src/css/components.scss`, as every component scss: lot 2's unstyled-thread bug), `src/utils/formatBytes.ts` (`formatBytes(bytes: number, lang: string): string`: o/Ko/Mo/Go in French, B/KB/MB/GB in English, one decimal from 1 MB; used by Tasks 10–12); modify `chat_thread_component.ts:110-161,587-606`, i18n, `featureCatalog.ts` (leaf `chat.attachments`, demo `{kind: "route", url: "/chat"}`), tests `chatComposerAttach.test.ts`, `chatThreadComponent.test.ts`.

**Behaviour:** 📎 opens a sheet « Appareil photo / Galerie / Fichier » with the server's limit under it (`chat.attach_limit`, from `sessionInfo().maxUploadSize`, so it is shown before sending) (`pickFiles` + `stage`); each staged file is a chip (name, `formatBytes(size)`, ✕ removes it and deletes its staged file); a refused file shows `chat.file_too_big` with the limit. 🎤 (hidden while a voice chip exists): a tap starts (timer shows the time left, ✕ discards), a tap stops and sends at once (with the typed text and the chips); auto-stop at 60 s sends. ➤ sends text + chips through `ChatService.send(src, channelId, text, files)`; with `askCompress` on and a photo chip, `Dialog.confirm(chat.compress_ask)` first (yes → `compress`). The composer clears before the first await, as `onSend` does today. Unmount discards an unsent recording.

- [ ] **Step 1: Failing tests:** sheet items; chip with size and removal (file deleted); limit refusal text; send with files only; mic start/stop sends; ✕ discards and sends nothing; timer counts down; mic hidden with a voice chip; compress asked only with the setting and a photo.
- [ ] **Step 2–4:** FAIL → implement → PASS; `npm run build`.
- [ ] **Step 5: Commit**: `[ADD] chat: composer attachments, chips and voice button`.

### Task 11: Thread display, viewer, player, open with (D10, D11, D15)

**Files:** M create `src/components/chat/chat_attachments_component.ts|.scss`, `chat_image_viewer_component.ts|.scss`; modify `chat_thread_component.ts:26-35,267-339,387-432`, `chat_list_component.ts` (preview of an attachment-only message), `chatBody.ts` (`attachmentPreview(atts)`), `ChatFilePlugin.java` (`openWith`), `chatFilePlugin.ts`, `android/app/src/main/res/xml/file_paths.xml` (`<files-path name="chat_files" path="chat/"/>`), i18n, `featureCatalog.ts` (leaf `chat.attachment-view`), tests `chatAttachmentsComponent.test.ts`, `chatThreadComponent.test.ts`, `chatListComponent.test.ts`, `chatBody.test.ts`.

**Interfaces:** (`cache` below is `ChatService.attachments`, Task 7)
- `ThreadRow` gains `attachments: AttachmentView[]` with `AttachmentView = {key; kind: "image"|"voice"|"file"; name; size; src: string|null /* webUrl of a local preview or original */; state: "uploading"|"waiting_wifi"|"refused"|"downloading"|"failed_preview"|"ready"|"remote"; progress: number|null; error: string|null}`; `MetaKind` gains `"waiting_wifi"` (an upload op of the post has `heldFor: "wifi"`). The render signature joins each attachment's `key|state|progress|src`.
- Images: grid (one image tall, several as tiles, as Odoo's 300 px / 75 px); a row's previews requested when it enters the viewport (`IntersectionObserver`, `cache.preview`); a failed preview is a tap-to-retry placeholder; own pending images show their local file. Tap → `ChatImageViewerComponent` (preview at once, original from `cache.open`, « en attente du Wi-Fi » when held, with « Télécharger quand même » that calls `cache.open(src, att, {anyNetwork: true})` for that file only).
- Voice: a player row (▶/⏸, position/duration, `<audio>` over `webUrl` of the original after `cache.open`). Other audio plays the same way without the voice badge.
- Other files: chip with name and size; tap → `cache.open` then `ChatFile.openWith({uri, mimetype})` (`ACTION_VIEW`, FileProvider uri, read grant, chooser). Download progress on the chip with a cancel ✕.
- List: an attachment-only message previews as `🎤 <voice label>`, `🖼️ <name>` or `📎 <name>` (`attachmentPreview`).

- [ ] **Step 1: Failing tests:** grid/voice/file split by mimetype and voice flag; preview asked only for visible rows, two at a time; signature change re-renders on state change only; waiting-for-Wi-Fi meta; « Télécharger quand même » on a held image, voice or file downloads that one on mobile data; progress and cancel; viewer shows the preview then the original; open with called with the mimetype; list previews.
- [ ] **Step 2–4:** FAIL → implement → PASS; `npm run build`.
- [ ] **Step 5: Commit**: `[ADD] chat: attachments in the thread, viewer, player, open with`.

### Task 12: Options, info-screen space, list warning, purge schedule (D8, D9)

**Files:** M `options_chat_component.ts:26-35`, `chat_info_component.ts:91-165`, `chat_list_component.ts`, `chatLifecycle.ts:49-53`, `src/js/app.ts:242-244` (purge check at start), `applications_component.ts:529-548`, i18n, `featureCatalog.ts` (leaf `chat.attachment-cache`, demo `{kind: "options", sectionId: "chat"}`), tests `optionsChatComponent.test.ts`, `chatInfoComponent.test.ts`, `chatListComponent.test.ts`, `chatLifecycle.test.ts` (create if absent), applications deletion test.

**Behaviour:** Options › Chat: total space, « Vider tout » (confirm), purge switch, limit in MB (number input, saved on change, 2048 default), the 80 % warning, « Demander avant d'envoyer s'il faut compresser les photos » with the hint that a server without the ERPLibre module 1.2 reduces photos to 1920 px. Info screen: « Espace utilisé » of the conversation and « Vider cette conversation ». List: a warning line at 80 % opening the options. `ChatLifecycle.follow(true)` and app start call `cache.maybePurge()`. Account deletion confirmation adds the unsent files count (`pendingUploadCount`, `dialog.confirm_delete_app_chat_files`).

- [ ] **Step 1: Failing tests:** settings round trip and defaults; clear all/conversation call the cache; warning shown at 80 %; resume calls `maybePurge`; deletion text with files.
- [ ] **Step 2–4:** FAIL → implement → PASS; `npm run build`.
- [ ] **Step 5: Commit**: `[ADD] chat: attachment space, clearing and purge settings`.

### Task 13: Test kit, device hook, long tests, device scenario (D16)

**Files:** M `src/testing/syncTestKit.ts` (`HARNESS_API = 3`), `src/testing/chatFakes.ts`, `src/testing/deviceTestHook.ts` (`DEVICE_HOOK_API = 4`); E `long_test/mobile_sync_odoo.py:58` (3), `long_test/mobile_sync_device.py:43` (4) + new scenario in `SCENARIOS` (`:915-922`, `(18,)`), `test/test_mobile_sync_harness.py:346,533`, `long_test/mobile_sync/faultProxy.ts`, `odooAdmin.ts`, `chatPeer.ts`, `harness.ts`, new `long_test/mobile_sync/chatAttachments.test.ts`, new `long_test/mobile_sync/fixtures/photo-2400x1600.jpg` + `PROVENANCE.md`.

**Interfaces:**
- Kit: `createSyncEnv(targets, {chatModule, chatFiles?})` gives the chat a memory `ChatFiles` and `nodeChatHttp(files)` (real `fetch`, `FormData` + `Blob` multipart, downloads into the memory files); exports `memoryChatFiles`, `nodeChatHttp`, `setNetwork({connected, wifi})`; `memoryAttachmentIO` accepts `Buffer | Uint8Array | string` values.
- Hook: `chatSendFile(configId, channelId, path, name, mimetype): Promise<string>` (stages the pushed file as the composer does after the picker, then sends; returns the post's clientUuid), `chatAttachments(configId, channelId)`, `chatSpace(configId?)`.
- faultProxy: `RpcCall.form?: Record<string,string>` and `files?: {field, filename, size, contentType}[]` parsed from `multipart/form-data`.
- `OdooAdmin.httpGet(path, cookie): Promise<{status, bytes}>`, `setParam(key, value)`; `ChatPeer.upload(channelId, filename, bytes, {voice?})` (chat_user session, CSRF from `/web/login`), `ChatPeer.attachmentsOf(messageId)`.
- Fixture JPEG generated once with Pillow from `.venv.odoo18.0_python3.12.10` (gradient, 2400×1600); PROVENANCE states the command; invented content only.

Long tests (`eachVersionFrom(18, "chat attachments")`, `beforeAll` sets and `afterAll` restores `web.max_file_upload_size` where lowered; the template rebuilds once for module 1.2): upload once after a dropped answer, with the module and with `chatModule: "ignore"`; the post answer dropped with files → one message; voice has `voice_ids` and `mimetype audio/mpeg`; the fixture kept original with the module (checksum = sha1 of the fixture) and reduced without (max side 1920); limit lowered before `appFor` → refused at stage, no request; limit lowered after queueing → one 413, notice, text posted, no retry after the window; Wi-Fi hold (`setNetwork({connected: true, wifi: false})` → nothing sent, `wifi: true` + flush → sent); an expired session (`/web/session/destroy` with the app's cookie) → the upload lands once after re-auth (checks D2's 404 reading on a real server); chat_user's image → preview fetched with `download=true`, original downloaded, bytes equal; loading a conversation holding 20 attachments (`chat.load`, `messages`, `loadOlder`) makes no `/web/image` or `/web/content` request (`proxy.calls`).

Device scenario « pièces jointes du clavardage » (18 only): `adb push` the fixture under the app's files dir (`run-as`), `chatSendFile`, server has it once; `pm grant RECORD_AUDIO`, tap 🎤 (`toucher_pose`), wait 3 s, tap again → server voice attachment with `voice_ids`; chat_user uploads an image → the preview shows (`chatAttachments` has a thumb), tap opens the viewer; the composer's 📎 and 🎤 sit above the navbar (lot 2's composer check). The camera and system pickers are not driven (vendor UI); say so in the report.

- [ ] **Steps:** write; `./long_test/mobile_sync.py --versions 18 --filtre chat` green ×3; full run green; `--appareil` green (the personal app untouched); `.venv.erplibre/bin/python -m unittest test.test_mobile_sync_harness` (its API assertions now 3 and 4); `--detruire`; commits M `[ADD] testing: chat attachments in the kit and the device hook`, E `[ADD] long_test: chat attachments against a real Odoo 18`.

### Task 14: Contracts, docs, changelogs

- [ ] `contracts/odoo-api.json`: `chat.upload` (both routes, fields, CSRF, idempotency per path, 404/400/413 handling), `chat.csrf` (`GET /web/login` scrape), `chat.upload_find` (fallback search domain), `chat.attachment_preview` (`/web/image/<id>/512x512?unique&download=true`), `chat.attachment_download`, `chat.attachment_delete_bus` (`ir.attachment/delete`), `chat.post` gains `attachment_ids` + `attachment_tokens`, migration 2026102604 table; `contracts/compatibility.json` module `18.0.1.2.0`; `long_test/README.base.md` (attachments section, template module 1.2), ERPLibre and mobile `CHANGELOG.base.md` (lamejs LGPL-3.0 named), mmg; commits E `[UPD] contracts: Odoo 18 chat attachments and module 1.2`, E `[UPD] doc: chat attachments long tests and changelog`, M `[UPD] changelog: chat lot 3, attachments and voice`.
