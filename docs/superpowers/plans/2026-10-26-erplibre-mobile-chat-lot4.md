# ERPLibre mobile chat, lot 4 (actions and writing) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From the phone, react to a message with an emoji, edit or delete
one's own messages, reply with a quote, copy a message's text, and write
with @mentions, #channel links, emoji and links, all of it queued offline,
never lost, never applied twice, and stored exactly as the Odoo 18 browser
composer stores it; a late edit never overwrites a newer browser edit.

**Architecture:** Three new outbox kinds (`chat.reaction`, `chat.edit`,
`chat.delete`) sent as target states, resolving a not-yet-sent target by its
client uuid and chained behind its post. A pure builder (`chatCompose.ts`)
reproduces Odoo 18's `prettifyMessageContent` byte for byte, pinned by
goldens produced once by the real function in a headless Chromium. Emoji
data are converted once from Odoo 18's `emoji_data.js` into a JSON asset
loaded as its own chunk. A new `chat_reactions` table and three message
columns (migration 2026102607) hold reactions, reply parents and
recipients; drafts keep a reply target, an edit in progress and mention
picks (migration 2026102608). The server module 18.0.1.3.0 adds a guarded
edit route and a body fingerprint field that also marks the level; without
it the app re-reads the message just before sending.

**Tech Stack:** as lots 1–3 (TypeScript, Owl 2, Capacitor 8, SQLite,
Vitest; Odoo 18 module in Python; ERPLibre long tests) plus Chromium
headless over CDP (`long_test/mobile_sync_cdp.py`) for the composer goldens.

**Spec:** `docs/superpowers/specs/2026-10-25-erplibre-mobile-chat-design.md`
(« Message actions », « Writing », « Failure, even if it technically
works », « Details decided for later lots » lot 4 lines, the late edit
included). Binding rulings: `tasks/chat/lot4-decisions.md` (user's
decisions, then controller rulings numbered 1–13, cited D1…D13). Odoo 18
and app readings: `tasks/chat/lot4-recon-odoo.md`, `lot4-recon-mobile.md`
(not versioned; their mobile line numbers predate lot 3, the ones below are
current).

Repos, all on `dev/mobile_chat`, never switch, never push:
**M** = `mobile/erplibre_home_mobile`, **A** =
`odoo18.0/addons/ERPLibre_erplibre_addons/erplibre_mobile_chat`, **E** =
the ERPLibre root. Paths are relative to their repo. `src/public/repo/` in M
is a build copy, never edited. Odoo sources cited as `mail/…`, `web/…` live
in `odoo18.0/odoo/addons/`.

## Global Constraints

- Everything in the lot 1–3 plans' Global Constraints still holds (Odoo 18 only, https/wss policy, one commit per task per repo, `[TYPE] scope: subject` ≤ 72 chars in English, bilingual body EN then `--- FR ---`, ≤ 8 lines per language, `Assisted-by:` trailer, never an AI in `Co-authored-by:`, files named at `git add`, never `-A`).
- **One new migration per schema change**: 2026102607 (reactions, parent, recipients) and 2026102608 (draft reply/edit/mentions); each a guarded `DatabaseService.addChatXxx()` (`PRAGMA table_info` / `CREATE TABLE IF NOT EXISTS`), the same pieces in `createChatTables` (`databaseService.ts:1193`), the new table in `renameChatRows` (`:1483`). The latest migration today is 2026102606 (`addChatDraftOrigin`, verified in `src/services/migrations/index.ts`).
- Strings only through `t()`, keys in both `src/i18n/en.ts` and `fr.ts`; every new outbox kind has `chat.action_<kind>` (`chat_list_component.ts` `noticeOf`). French label of the edited mark: « (modifié) », English « (edited) ».
- Owl templates are `xml` tagged literals with no `${}` interpolation.
- Every component `.scss` is `@use`d in `src/css/components.scss`.
- Every new file appears in `src/data/featureCatalog.ts` (`files[]` that exist, EN/FR labels; `.claude/rules/01-feature-catalog.md`); new leaves `chat.reactions`, `chat.message-actions`, `chat.compose`, `chat.emoji`.
- Nothing identifying anywhere — code, comments, tests, fixtures, commits: invented names only (« Alice Martin », « #général-test »), checked absent elsewhere in the repo. Comments say how the code works, present tense, no incident narrative (`.claude/rules/04-code-conventions.md`).
- Docs: edit `.base.md` only, regenerate with mmg (skill `erplibre-doc-i18n`).
- `HARNESS_API` 3 → 4 (`src/testing/syncTestKit.ts:35` and `long_test/mobile_sync_odoo.py:58`) and `DEVICE_HOOK_API` 4 → 5 (`src/testing/deviceTestHook.ts:25` and `long_test/mobile_sync_device.py:50`), each pair in the same task, `test/test_mobile_sync_harness.py:346,727` follow.
- Phone: only the test app `ca.erplibre.home.synctest`; the personal app is never touched.
- Harness unit tests: `.venv.erplibre/bin/python -m unittest discover -s test -p test_mobile_sync_harness.py`. Module tests: `.venv.odoo18.0_python3.12.10/bin/python odoo18.0/odoo/odoo-bin -c config.conf -d chat_module_test -i erplibre_mobile_chat --test-tags /erplibre_mobile_chat --stop-after-init --log-level=test`, then `dropdb chat_module_test`. M: `npm test`, `npm run build`.
- Reactions on the wire: `/mail/message/reaction {message_id, content, action: "add"|"remove"}`, never a toggle; `content` exact (❤️ = U+2764 U+FE0F) (D1).
- Bodies sent (post and edit) are the browser composer's input HTML (D4): escaped text, `<br>` breaks, Odoo's URL regex and `URL` href, partner `<a href="/odoo/res.partner/ID" class="o_mail_redirect" data-oe-id="ID" data-oe-model="res.partner" target="_blank" contenteditable="false">@Name</a>`, channel `o_channel_redirect` (sub-channel `o_channel_redirect o_channel_redirect_asThread`, text `#Parent > Name`), `<a href="#" class="o-discuss-mention">@everyone</a>`, shortcodes and emoticons turned into emoji (`mail/static/src/utils/common/format.js:24-41,148-238`). The post marker comment is appended after, at send, as today.
- A text-only edit sends `attachment_ids: null` (verified in Task 1, fallback there); a delete sends `{body: "", attachment_ids: [], attachment_tokens: [], subject: ""}` (D5, D6).
- A late edit is refused, never written: module 1.3 compares a body fingerprint under a row lock; without it the app re-reads the body just before sending. The refused text stays in a notice with « Reprendre » (spec, D5).
- The emoji JSON is produced by a committed script and committed; the app build never reads the Odoo checkout; it loads as its own chunk (D3).

## Review Focus

1. **A reaction toggled several times offline, then online with the answer dropped:** the server ends on the last state, one `mail.message.reaction` row at most, and no request at all when the last state equals the server's (Task 6 tests `add then remove offline sends nothing`, `a dropped reaction answer leaves one reaction`; Task 14 long test).
2. **An edit queued offline while the browser edits or deletes the same message:** refused, nothing overwritten, a deleted message never comes back, the text stays with « Reprendre », with module 1.3 and without (Task 1 `test_guarded_edit_refused_when_deleted`; Task 7 `a re-read that finds another body refuses the edit`; Task 14 long tests both paths).
3. **A text mixing `@Name` twice, `#channel`, `:)` before a line break, a URL with a trailing dot, `<`, `&` and quotes, three newlines:** the HTML equals the browser's golden byte for byte, and a browser-style edit of the stored body gives the same body back (Task 4 golden suite; Task 14 round trip).
4. **React, edit and delete on a message still pending offline, the app killed and restarted:** the reaction goes after its post, the edit is folded into the post text, the delete sends nothing and releases the files (Task 6 `a reaction on a pending message survives a restart`; Task 7 `edit of a pending post rewrites it`, `delete of a pending post cancels it and its uploads`).
5. **A reply whose parent is emptied, unlinked, in another channel or not loaded:** the quote reads « message d'origine supprimé » or the message posts plain, no error, a tap on a quote of an unloaded parent does nothing (Task 8 `a parent dropped by the server gives a plain message`; Task 11 `quote of an emptied parent`, `tap on a quote of an unloaded parent`).

---

## File Structure

**A** (version → `18.0.1.3.0`): `controllers/message.py` (guarded edit route), `controllers/__init__.py`, `models/mail_message.py` (fingerprint field), `tests/test_guarded_edit.py`, `tests/__init__.py`, `__manifest__.py`, `i18n/fr_CA.po`, `README.md`.

**M** (new): `scripts/convert-odoo-emoji.mjs`, `src/data/emojiData.json`, `src/assets/licenses/unicode-cldr.LICENSE.txt`, `src/services/chat/chatEmoji.ts`, `src/services/chat/chatCompose.ts`, `src/services/chat/chatMentions.ts`, `src/services/migrations/addChatActions.ts`, `addChatDraftModes.ts`, `src/components/chat/chatLongPress.ts`, components `chat_emoji_picker_component.ts|.scss`, `chat_message_menu_component.ts|.scss`, `chat_reactions_component.ts|.scss`, `chat_composer_banner_component.ts|.scss`, `chat_suggestions_component.ts|.scss`, `src/__tests__/fixtures/composer-cases.json`, `composer-golden.json`, `PROVENANCE.md`, tests `chatEmoji.test.ts`, `chatCompose.test.ts`, `chatMentions.test.ts`, `chatLongPress.test.ts`, `chatEmojiPicker.test.ts`, `chatMessageMenu.test.ts`, `chatReactionsComponent.test.ts`, `chatSuggestions.test.ts`. Modified: `chatBody.ts`, `chatStore.ts`, `chatRepository.ts`, `chatOutbox.ts`, `chatService.ts`, `chatModule.ts`, `models/chat.ts`, `databaseService.ts`, `migrations/index.ts`, thread/list components, `applications_edit_component.ts`, `options_licenses_component.ts`, `vite-env.d.ts`, i18n, `featureCatalog.ts`, `src/css/components.scss`, `syncTestKit.ts`, `deviceTestHook.ts`, `CHANGELOG.base.md`.

**E:** `long_test/mobile_sync_composer.py` (goldens generator), `long_test/mobile_sync/chatActions.test.ts`, `chatWriting.test.ts` (new), `chatPeer.ts`, `long_test/mobile_sync_odoo.py`, `long_test/mobile_sync_device.py` (+ scenario, touch-hold helper), `test/test_mobile_sync_harness.py`, `contracts/odoo-api.json`, `contracts/compatibility.json`, `long_test/README.base.md`, `CHANGELOG.base.md`.

---

### Task 0: Lot 3 carry-overs (D13)

Carry-overs from the lot 3 final review (`tasks/chat/lot3-rereview-report.md`, « New Issues In Fix Diff »).

**Files:** M `src/services/chat/chatOutbox.ts` (`twin` `:1158-1159`, `findUploaded` `:1762-1784`, `stopUploads`/the lane), `src/services/appService.ts:46-48`, the composer attach controller (staging limit), the preparing bubble in `chat_thread_component.ts`; E `contracts/odoo-api.json` (`chat.upload_find`); tests `chatOutbox.test.ts`, `chatService.test.ts`, `chatComposerAttach.test.ts`, `chatThreadComponent.test.ts`.

- [ ] **Step 1: Failing tests:**
  - `two same-named photos of different sizes in two conversations, both answers lost, each post keeps its own attachment` (no module) — N1: the photo in the wrong conversation.
  - `a rename waits for no upload and no upload writes under the old id` (pause the account's upload lane from before `whenIdle` until `renameChatRows` is done) — N3.
  - `a pick while the limit is unknown stages without the 128 MiB fallback and the late check refuses with the real limit` — N4.
  - `the preparing bubble shows small thumbnails, not full-size originals` — N5.
- [ ] **Step 2: Implement:** `twin` ignores size when both files are resizable image types (`RESIZABLE_IMAGE_TYPES`) — the match without size then has its twins ordered; pause/resume of the account's upload lane around the rename; stage with no limit while unknown; the preparing bubble uses the staged file through a downscaled `<img>` (decoding bounded, e.g. `decoding="async"` and a CSS box, or `ChatFile.toJpeg` to a thumbnail) — the lighter path that keeps memory bounded; correct the comment at `chatOutbox.ts:1762-1763`, the `chat.upload_find` contract note and `appService.ts:46-48`'s « nothing writes » claim (N6).
- [ ] **Step 3:** `npm test`, `npm run build`; `./long_test/mobile_sync.py --versions 18 --filtre chat` green.
- [ ] **Step 4: Commits:** M `[FIX] chat: same-named photos ordered, rename pauses uploads, late limit`; E `[UPD] contracts: chat upload search orders same-named photos`.

### Task 1: Server module 18.0.1.3.0 — guarded edit (D5)

**Files:** A `models/mail_message.py`, create `controllers/message.py`, `controllers/__init__.py` (`from . import attachment, message`), create `tests/test_guarded_edit.py`, `tests/__init__.py`, `__manifest__.py` (version, description gains the guarded edit), `i18n/fr_CA.po`, `README.md`.

**Interfaces:**
- Field `mail.message.erplibre_body_fingerprint`: `fields.Char(compute="_compute_erplibre_body_fingerprint")`, not stored, `@api.depends("body")`, value `hashlib.sha256(str(message.body or "").encode()).hexdigest()`. It is the guard's comparison and the level marker: `fields_get` of `mail.message`, which every internal user reads and the app already caches for level 1.0, shows it without the settings group (D5's capability requirement).
- Route `/erplibre_mobile_chat/message/update_content`, `type="json"`, `auth="user"`, `methods=["POST"]`, in `ErplibreMessageController(ThreadController)` (`mail/controllers/thread.py`): `erplibre_update_content(self, message_id, body, expected_fingerprint, attachment_ids=None, partner_ids=None, **kwargs)`:
  - `SELECT id FROM mail_message WHERE id = %s FOR UPDATE` first, so a concurrent edit waits between the comparison and the write;
  - the message read and checked as Odoo does (`_get_with_access(message_id, "create")` and `_is_message_editable`) → `NotFound` otherwise;
  - current fingerprint ≠ `expected_fingerprint`, or the message is empty (`_filter_empty()`) while `body` is not → answer `{"erplibre_conflict": "deleted" | "changed", **Store(message, for_current_user=True).get_result()}` (`deleted` when the message is empty), nothing written;
  - otherwise `return self.mail_message_update_content(message_id, body, attachment_ids, partner_ids=partner_ids, **kwargs)` (Odoo's checks, sanitizer, marker, bus and answer unchanged, as lot 3's upload route reuses Odoo's).

- [ ] **Step 1: Failing tests** (`HttpCase`, JSON-RPC through `self.url_open` as `test_attachment_upload.py` does, two internal users): `test_fingerprint_matches_store_body` (sha256 of `Store(message).get_result()["mail.message"][0]["body"]` equals the field), `test_guarded_edit_applies_when_unchanged` (body ends with the edited span, no `erplibre_conflict`), `test_guarded_edit_refused_when_changed` (a browser edit through `/mail/message/update_content` in between → `"changed"`, body = the browser's), `test_guarded_edit_refused_when_deleted` (a delete in between → `"deleted"`, the message stays empty), `test_guarded_edit_other_author_not_found`, `test_guarded_edit_locks_the_message_row` (`patch.object(cr, "execute", wraps=…)` sees the `FOR UPDATE` before the write, as `test_lock_statement_executes`), `test_fingerprint_field_in_fields_get_for_internal_user`.
- [ ] **Step 2: Verify `attachment_ids: null` (UNVERIFIED in the recon):** `test_null_attachment_ids_keeps_attachments` — a message with two attachments edited through Odoo's route and through the module route with `attachment_ids: None` keeps both ids; `test_empty_attachment_ids_deletes_them` as control. Reading of `mail/models/mail_thread.py:4693-4704` and `controllers/thread.py:170` predicts PASS (`browse(None)` is empty, `if attachment_ids:` false, `elif … is not None` false). **Fallback** if it fails: the app sends the message's current ids with `attachment_tokens` read from `ir.attachment.access_token` (search_read as the author) — record the outcome in `tasks/chat/lot4-ledger.md` and in Task 7's Interfaces before Task 7 starts.
- [ ] **Step 3–4:** run the module tests FAIL → implement → PASS (every earlier test green); `dropdb chat_module_test`.
- [ ] **Step 5: Commit** (A): `[IMP] erplibre_mobile_chat: guarded message edit, body fingerprint`.

### Task 2: Reactions, parents, recipients — schema, parsing, bus, repository (D1, D6, D8)

**Files:** M create `src/services/migrations/addChatActions.ts`; modify `migrations/index.ts` (`{version: 2026102607, description: "Clavardage : réactions, réponses et destinataires des messages", run: addChatActions}`), `databaseService.ts` (`createChatTables`, new `addChatActions()` beside `addChatDraftOrigin`, `renameChatRows` list), `models/chat.ts`, `chatStore.ts`, `chatRepository.ts`, `chatService.ts` (`applyOne` `:1384`, the history page `:502-513`), tests `chatStore.test.ts`, `chatRepository.test.ts`, `chatService.test.ts`, `migrations.test.ts`.

**Interfaces:**
- Table `chat_reactions`: `id TEXT PK` (`configId#<messageKey>#<content>`), `config_id TEXT NOT NULL`, `channel_id INTEGER NOT NULL`, `message_key TEXT NOT NULL` (`m<id>` or `u<clientUuid>`), `message_id INTEGER`, `content TEXT NOT NULL`, `count INTEGER NOT NULL`, `self_reacted INTEGER NOT NULL`, `partner_ids TEXT NOT NULL` (JSON, the server's order), `guest_count INTEGER NOT NULL DEFAULT 0`, `sequence INTEGER NOT NULL`; index `(config_id, channel_id)`. `chat_messages` gains `parent_id INTEGER`, `parent_client_uuid TEXT`, `recipient_ids TEXT` (JSON). « (edited) » gets no column: it is read from the body (`isEdited`, Task 4), as the browser does.
- `models/chat.ts`: `MessageTarget { messageId: number | null; clientUuid: string | null }`; `ChatReaction { configId; channelId; messageKey: string; messageId: number | null; content: string; count: number; selfReacted: boolean; partnerIds: number[]; guestCount: number; sequence: number }`; `ChatMessage` gains `parentId?: number | null`, `parentClientUuid?: string | null`, `recipientIds?: number[]` (optional, so existing literals stay valid; rows always fill them); `messageKeyOf(m: {messageId; clientUuid}): string`.
- `StoreDelta` gains optional `reactions?: (Omit<ChatReaction, "configId" | "channelId" | "messageKey"> & {messageId: number})[]`, `reactionSets?: {messageId: number; contents: string[]}[]` (a plain `reactions` list: the full set, groups absent from it go), `deletedReactions?: {messageId: number; content: string}[]` (`["DELETE", obj]` and `["DELETE", [obj…]]` both), `deletedMessageIds?: number[]`; a message partial gains `parentId` (`parentMessage` id, `false` → null) and `recipientIds` (`recipients`). `parseStore` reads `MessageReactions` (`mail/models/mail_message_reaction.py:27-40`: `selfReacted` = self partner in `personas`, guests counted); `mergeDeltas` merges them; the three literal deltas (`emptyDelta` at `chatOutbox.ts:181` and `chatService.ts:52`, `partnersDelta` at `chatPeople.ts:28`) need no change.
- `ChatRepository`: `applyDelta` writes them (a set replaces the message's groups; a delete removes one; a deleted message id drops the row, its reactions and its attachment rows with their files); `reactionsOf(configId, channelId, keys: string[]): Promise<Map<string, ChatReaction[]>>` (by `sequence`); `putReaction(r: ChatReaction)`, `dropReaction(configId, messageKey, content)`; `messageByClientUuid(configId, clientUuid): Promise<ChatMessage | null>`; `messageOf(configId, target: MessageTarget)` (by id, else by client uuid); `dropQueued(configId, clientUuid)` (row and its reactions). `settlePending` and the queued-merge path of `upsertMessage` re-key `u<uuid>` reactions to `m<id>`; `swapChannelId`, `dropChannel`, a deleted channel in `applyDelta` and `dropSource` cover `chat_reactions`.
- `ChatService.applyOne` gains `case "mail.message/delete"` (`{message_ids}`, `mail/models/mail_message.py` `unlink`) → `deletedMessageIds`; `mail.record/insert` already reaches `applyStore`.

- [ ] **Step 1: Failing tests:** migration on a 2026102606 database adds the table and columns, a second run changes nothing, a fresh install has them; parse of a messages page with two reaction groups (self among personas in one, a guest in the other) and a `parentMessage`; parse of the bus `ADD` group, of `["DELETE", {message, content}]` and of the list form; `recipients` → `recipientIds`; `parentMessage: false` → `parentId` null; a plain `reactions` list removes a cached group it does not name; `settlePending moves a pending reaction to the server id`; swap, drop channel, drop source remove reactions; `mail.message/delete` drops message, reactions and attachment rows.
- [ ] **Step 2–4:** FAIL → implement → PASS; `npm test`.
- [ ] **Step 5: Commit**: `[ADD] chat: reactions table, reply parents and recipients parsed`.

### Task 3: Emoji data, loader, most used, licence notice (D2, D3)

**Files:** M create `scripts/convert-odoo-emoji.mjs`, `src/data/emojiData.json`, `src/assets/licenses/unicode-cldr.LICENSE.txt`, `src/services/chat/chatEmoji.ts`; modify `src/components/options/licenses/options_licenses_component.ts`, `src/vite-env.d.ts`, i18n, `featureCatalog.ts` (leaf `chat.emoji`), tests `chatEmoji.test.ts`, `optionsLicensesComponent.test.ts`.

**Interfaces:**
- Script: `node scripts/convert-odoo-emoji.mjs <emoji_data.js> <web/i18n/fr.po>` → `src/data/emojiData.json` and the licence file (the Unicode licence text of the source header, `emoji_data.js:1-50`). It resolves every `` "` + _t("…") + `" `` to the English text and to fr.po's `msgstr` (English when missing or empty, PO escapes decoded), parses the template literals of `_getCategories` and `_getEmojisData1…8` as JSON, and fails when its count differs from the number of `"codepoints"` in the source. Run once by hand from the ERPLibre checkout; never by the build.
- JSON: `{ categories: {name; title; sortId; displayName: {en; fr}}[]; emojis: {codepoints; category; name: {en; fr}; keywords: {en: string[]; fr: string[]}; shortcodes: string[]; emoticons: string[]}[] }`, source order kept (the conversion order of Task 4 depends on it).
- `chatEmoji.ts`: `type EmojiData`, `EmojiEntry`, `EmojiCategory` (the JSON's); `loadEmojiData(): Promise<EmojiData>` (`import("../../data/emojiData.json")`, memoized; its own chunk); `type EmojiConversion = {source: string; codepoints: string}`, `emojiConversions(): Promise<EmojiConversion[]>` (per emoji in data order, its shortcodes then its emoticons, as `format.js:228-238`); `searchEmoji(data, term, lang: "fr" | "en"): EmojiEntry[]` (folded lowercase over the name and keywords of `lang` and of English, and shortcodes); `QUICK_REACTIONS = ["👍", "❤️", "😂", "😮", "😢", "🙏"]` (U+1F44D, U+2764 U+FE0F, U+1F602, U+1F62E, U+1F622, U+1F64F); `FREQUENT_KEY = "chat.emoji.frequent"` (localStorage `{codepoints: count}`, all accounts together, every access in try/catch); `countEmojiUse(codepoints: string): void`; `frequentEmoji(limit = 42): string[]` (count desc); `QUICK_MIN_USES = 3`; `quickReactions(counts?: Record<string, number>): string[]` — always six: start from QUICK_REACTIONS; each emoji outside them used at least 3 times, most used first, takes the slot of the first quick emoji, scanning from the end, that is used less than it; it stops at the first that displaces none.
- `ThirdPartyNotice` gains optional `useKey?: string` (default `options.licenses_use`), and `baseLicenseName`/`baseLicenseText` become optional; a second entry « Unicode CLDR emoji data » (licence « Unicode License v3 », source `https://github.com/unicode-org/cldr`, the converted file named as coming from Odoo 18 `web`, LGPL-3.0 — see the open question in the report).

- [ ] **Step 1: Failing tests:** the JSON holds the six quick reactions with exact codepoints, every emoji a category, French names present for « visage rieur » (😀); `emojiConversions` puts `:smiley:` before `:D` of 😃 and keeps data order; `searchEmoji("rieur", "fr")` finds 😀, `searchEmoji("grinning", "fr")` too; `quickReactions` cases (none used → defaults; one used 3 times → last slot; used twice → defaults; a heavily used default keeps its slot; seven candidates → six slots); unreadable storage counts as empty; the licence entry renders with no base licence button.
- [ ] **Step 2: Verify the chunk:** `npm run build` lists an `emojiData-*.js` chunk apart from the main bundle; record its size in the ledger.
- [ ] **Step 3–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit**: `[ADD] chat: emoji data from Odoo 18, most used, licence notice`.

### Task 4: Body builder and renderer, browser goldens (D4, D10, D12)

**Files:** E create `long_test/mobile_sync_composer.py`; M create `src/services/chat/chatCompose.ts`, `src/__tests__/fixtures/composer-cases.json`, `composer-golden.json`, `PROVENANCE.md`; modify `chatBody.ts` (renderer, text extraction; `textToBody` removed), `chatOutbox.ts` (its two callers, `queuePostNow` and `sendPost`, take `composeBody(text, EMPTY_MENTIONS, await emojiConversions()).body`; Task 8 passes real mentions), `featureCatalog.ts` (leaf `chat.compose`), tests `chatCompose.test.ts`, `chatBody.test.ts`, `chatOutbox.test.ts` (its body assertions follow the browser form: attribute order, normalised href).

**Interfaces:**
- `chatCompose.ts`: `Mentions { partners: {id: number; name: string}[]; channels: {id: number; name: string; parentName: string | null}[] }`, `EMPTY_MENTIONS`; `validMentions(text, m: Mentions): Mentions & { special: string[] }` (`store_service.js:506-526`: kept when `@name` / `#name` / `#parent > name` is in the raw text; `special` = `["everyone"]` when `@everyone` is); `composeBody(text: string, m: Mentions, conversions: EmojiConversion[]): { body: string; partnerIds: number[]; specialMentions: string[] }` — `format.js` step by step: `escapeAndCompactTextContent` (trim, `(\r|\n){2,}` → `<br/><br/>`, `(\r|\n)` → `<br/>`, the `&nbsp;` passes), mentions longest text first, each replacing its FIRST occurrence only (`htmlReplace` with a string search), then `@everyone`, anchors with attributes in `setAttributes` order; emoji `(\s|^)(escaped source)(?=\s|$)` per conversion; linkify on text nodes only with `format.js:16-17`'s regex copied verbatim, `http://` prefixed to `www.`, `URL.canParse` then `URL.parse(fixed).href`, output `<a target="_blank" rel="noreferrer noopener" href="…">typed</a>`; the final DOM pass re-serialises through `outerHTML` as the browser does (so `<br/>` → `<br>`). `linkify(text: string): string` exported for tests.
- `chatBody.ts`: `EDITED_CLASS = "o-mail-Message-edited"`; `renderBody(html, opts: {editedLabel?: string; selfPartnerId?: number | null} = {})` keeps on `a` the classes `o_mail_redirect`, `o_channel_redirect`, `o_channel_redirect_asThread`, `o-discuss-mention` (each mapped to `chat-msg__mention`, `chat-msg__channel`, `chat-msg__special`; `chat-msg__mention--self` for the user's partner) and `data-oe-id` (digits only) / `data-oe-model` (`res.partner` or `discuss.channel` only); a relative or `#` href is dropped (taps go by `data-oe-*`, Task 11); the edited span becomes `<em class="chat-msg__edited"> (modifié)</em>` with `opts.editedLabel`, where the span was, as `message.xml:137-139`; `bodyText(html): string` = `<br>` → `\n` then `textContent` (`convertBrToLineBreak`, `format.js:257-260`): copy and edit both use it; `isEdited(body)`; `isEmptyBody(body)` (`message_model.js:364-382`: the edited span and whitespace removed, then one of the browser's empty forms); `isEmptyMessage(body, attachmentCount)`; `withEditedMark(body)` (the optimistic body of a queued edit: body + `<span class="o-mail-Message-edited"></span>`); `mentionAnchors(html): {partners: number[]; channels: number[]}`.
- `long_test/mobile_sync_composer.py <url> <login> <password>`: starts `chromium --headless --remote-debugging-port`, puts a session cookie obtained by `/web/session/authenticate` (`Network.setCookie`), opens `/odoo/discuss`, waits for `odoo.loader.modules.get("@mail/utils/common/format")`, evaluates `prettifyMessageContent(text, validRecords)` for each case of `mobile/erplibre_home_mobile/src/__tests__/fixtures/composer-cases.json` (through `Cdp.evaluer` of `mobile_sync_cdp.py`), writes `composer-golden.json` beside it. Any Odoo 18 of the checkout gives the same goldens (the function is client-side).
- Cases (invented names): plain text; three newlines; leading/trailing blanks; `<b>&"'`; `https://example.com` and `https://example.com.` and `www.example.org/path?q=1`; `https://x` (not linked); `:)` alone, `:)` before a line break, `:grinning:`; `@Alice Martin` twice; `@Alice` and `@Alice Martin` both picked; `#général-test`; a sub-channel; `@everyone`; a mention at the start; an emoji typed directly.

- [ ] **Step 1: Generate the goldens (verification against the real Odoo 18 source):** run the script against the developer's Odoo 18 (default port 8069) or a run's disposable server; write `PROVENANCE.md` (command, Odoo commit of `odoo18.0/odoo`, date not needed). **Fallback** if Chromium or the module lookup fails: write the goldens by hand from `format.js`, mark them « derived from the source, not executed » in PROVENANCE, and say so in the report; Task 14's round trip then carries the check.
- [ ] **Step 2: Failing tests:** `composeBody matches every golden` (one test per case); `validMentions drops a pick whose text was edited away`; `partnerIds and specialMentions`; `renderBody keeps a mention chip and drops its href`, `renderBody refuses a data-oe-model it does not know`, `renderBody shows « (modifié) » where the span was`; `bodyText of <p>a<br>b</p> is "a\nb"`; `isEmptyBody of the lone edited span is true`; `isEmptyMessage keeps an emptied body with a file`.
- [ ] **Step 3–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commits:** E `[ADD] long_test: composer goldens from Odoo 18's own formatter`; M `[ADD] chat: browser-identical message HTML, mention and edit rendering`.

### Task 5: Module 1.3 detection (D5)

**Files:** M `chatModule.ts`, `chatService.ts` (`features` `:531`), `models/chat.ts` (`moduleLevel` union), `applications_edit_component.ts`, i18n, tests `chatModule.test.ts`, `applicationsEditChatModule.test.ts`, `chatService.test.ts`.

**Interfaces:**
- `ChatModuleLevel = "1.0" | "1.1" | "1.2" | "1.3"`, `CHAT_FINGERPRINT_FIELD = "erplibre_body_fingerprint"`; `moduleLevel` checks the cached `mail.message` capability for it first (→ 1.3), then the lot 3 order; `moduleProbe`: `installed` only at 1.3, `outdated` at 1.0–1.2; `upgradeModule` accepts 1.2.
- `features(configId)` gains `guardedEdit: levelAtLeast(level, "1.3")` (module mode `auto`).
- Edit screen: `chat.module_outdated` names guarded edits among what the upgrade brings.

- [ ] **Step 1: Failing tests:** level matrix (four fields … none); a 1.2 server is outdated and keeps `idempotentUpload` without `guardedEdit`; admin on 1.2 sees the upgrade; upgrade then probe → installed.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit**: `[ADD] chat: module 1.3 detection, guarded edit feature`.

### Task 6: Outbox — reactions, message targets (D1, D7, D11)

**Files:** M `chatOutbox.ts` (constants `:36-130`, constructor `:268-273`, `queueAction` `:726`, `overlayPending` `:911`, `notices` `:933`, `giveUp` `:2076`), `chatService.ts`, `models/chat.ts` (`ChatNotice`), i18n, tests `chatOutbox.test.ts`, `chatService.test.ts`, `chatListComponent.test.ts`.

**Interfaces:**
- `CHAT_REACTION = "chat.reaction"`, params `{channelId, messageId: number | null, clientUuid: string | null, content, action: "add" | "remove", base: boolean}` (`base`: the self reaction the server had at the first queue). `MESSAGE_KINDS = [CHAT_REACTION]` (Task 7 appends `CHAT_EDIT`, `CHAT_DELETE`), spread into `NOTICE_KINDS` and `USER_ACTIONS`, each registered to `runMessageAction`, not `runAction` (whose channel guards and `MEMBER_ONLY` do not apply to a message).
- `sameTarget(a: MessageTarget, b: MessageTarget): boolean` (same client uuid when both have one, else same message id); `targetKey(op): string` = kind, channelId, partnerId, message target, content — `giveUp`'s « a later op supersedes » uses it, so two reactions on two messages never hide each other's notice.
- `queueAction` gains `opts.after?: string | null` (the post op of a pending target; dependsOn precedence: running op of the key, then `after`, then the create) and `opts.noop?: (merged: Record<string, any>) => boolean` (with no op of the key running, a merged value that is a no-op cancels the waiting ops and queues nothing; returns null).
- `ChatOutbox.queueReaction(configId, channelId, target: MessageTarget, content: string, on: boolean): Promise<OutboxOp | null>` — key (target, content); optimistic `putReaction`/`dropReaction` (count ± 1, self in or out); the target's post op as `after` while it has no server id; `noop`: `action` equals `base`.
- `runMessageAction`: offline → `RequestNotSentError`; conversation left → dropped; target row absent, or emptied (`isEmptyMessage`), or a pending row whose post op is gone without a server id → `giveUp("vanished")`; send `/mail/message/reaction {message_id, content, action}` and apply the answer's Store; `NotFound` → `giveUp("vanished")`; other refusals → `giveUp("refused")`.
- `overlayMessages(configId, delta)`: queued reactions over `delta.reactions` / `reactionSets` of messages the delta carries; called by `overlayPending` (loads), by the history page path and by `applyStore` (bus); the channel overlay keeps its callers.
- `ChatNotice.reason` gains `"changed"`; notice text `chat.notice_message_vanished` (« {action} : non envoyé, le message n'existe plus. ») and `chat.action_reaction`.
- `ChatService.react(src, channelId, target, content, on): Promise<void>` (`countEmojiUse` when on, then `afterAction`); `ChatService.reactions(configId, channelId, keys)`.

- [ ] **Step 1: Failing tests** (fake Odoo of `chatService.test.ts:81`, `/mail/message/reaction` through `state.onRoute`, answering the group as `mail_message.py:920-933`): `a reaction sends action add with the exact content`; `add then remove offline sends nothing`; `remove then add of a server reaction sends nothing`; `add, remove, add offline sends one add`; `a reaction while one runs queues a follow-up`; `a dropped reaction answer leaves one reaction` (retry → second add, the fake keeps one row); `a reaction on a message deleted meanwhile is dropped with a notice`; `NotFound gives the vanished notice`; `notices of two messages' reactions do not supersede each other`; `a reaction on a pending message waits for its post and sends its server id`; `a reaction on a pending message survives a restart` (new ChatOutbox over the same db); `a load between the tap and the send keeps the optimistic reaction`; the list shows `chat.action_reaction` text.
- [ ] **Step 2–4:** FAIL → implement → PASS; `npm test`.
- [ ] **Step 5: Commit**: `[ADD] chat: reactions queued as target states, pending targets`.

### Task 7: Outbox — edit and delete, late edit refused (D5, D6, D7, D11)

**Files:** M `chatOutbox.ts`, `chatService.ts`, `models/chat.ts`, i18n, tests `chatOutbox.test.ts`, `chatService.test.ts`.

**Interfaces:**
- `CHAT_EDIT = "chat.edit"`, params `{channelId, messageId, clientUuid, text, mentions: Mentions, baseBody: string | null}` (`baseBody`: the server's body at the first queue, kept by later merges); `CHAT_DELETE = "chat.delete"`, params `{channelId, messageId, clientUuid}`; both appended to `MESSAGE_KINDS` (Task 6).
- `ChatOutbox.queueEdit(configId, channelId, target, text, mentions): Promise<OutboxOp | null>`:
  - pending target whose post op is not running → the post's `text` and `mentions` rewritten (`setParams`), the pending row's body rebuilt, null;
  - text equal to `bodyText` of the current body → null (the browser's own no-op, `message_model.js:480-482`);
  - otherwise one waiting edit per message (last text wins, first `baseBody` kept), `after` = the post op of a running pending post; optimistic body `withEditedMark(composeBody(...).body)`.
- `ChatOutbox.queueDelete(configId, channelId, target): Promise<OutboxOp | null>`:
  - pending target whose post op is not running → that post, its uploads and every op of that target cancelled, `dropQueued`, its outgoing rows and files released (as `queueLeave` does), null;
  - otherwise waiting edits and reactions of the target cancelled, one delete queued (`after` as above), optimistic body "".
- Send of an edit (`runMessageAction`): body `composeBody(text, mentions, await emojiConversions())`, `partner_ids` = its partner ids, `attachment_ids: null` (or Task 1's fallback); with `editGuard(configId)` true (a hook ChatService sets from `features().guardedEdit`) → the module route with `expected_fingerprint` = sha256 hex (`crypto.subtle`) of `baseBody`; `erplibre_conflict` in the answer → its Store applied, `giveUp` with reason `"changed"` and `params.conflict = "changed" | "deleted"`; a non-JSON 404 from the module route → `moduleRefused(configId)` and a plain retry. Without it → `search_read mail.message [["id","=",id]] ["body"]` just before `/mail/message/update_content`: no row or `isEmptyBody` → `"changed"` with `conflict: "deleted"`; a body ≠ `baseBody` → `"changed"`, the read body written to the cache. A successful edit applies its answer and rebases the next waiting edit of the message on that body. `NotFound` → vanished.
- Send of a delete: `/mail/message/update_content {message_id, body: "", attachment_ids: [], attachment_tokens: [], subject: ""}`; `NotFound` → done (already gone); the answer applied.
- `ChatNotice` gains `edit?: {target: MessageTarget; text: string; mentions: Mentions; deleted: boolean}` for kind `chat.edit` reason `"changed"`; texts `chat.notice_edit_changed` (« Modification non envoyée : le message a changé entre-temps. »), `chat.notice_edit_deleted`, `chat.action_edit`, `chat.action_delete`, `chat.resume` (« Reprendre »).
- `ChatOutbox.takeRefusedEdit(configId, noticeId): Promise<ChatNotice["edit"] | null>` (returns it and dismisses the notice).
- `ChatService.editMessage(src, channelId, target, text, mentions)`, `deleteMessage(src, channelId, target)`, `editDraftOf(configId, channelId, target): Promise<{text: string; mentions: Mentions} | null>` (pending: the post's params; sent: `bodyText` of the body, partners = `recipientIds` with their current cached names as the browser's `message.recipients`, channels = `mentionAnchors` with their cached names, an uncached channel left as text), `requestResume(configId, noticeId)`, `takeResume(configId, channelId): Promise<ChatNotice["edit"] | null>`.

- [ ] **Step 1: Failing tests:** `an edit sends attachment_ids null and the browser HTML`; `two offline edits send the last text once`; `edit of a pending post rewrites it` (one post with the new text, no update_content); `delete of a pending post cancels it and its uploads` (no request, files released, row gone); `delete of a running post waits and then deletes`; `a delete cancels the waiting edit of the message`; `the module path sends the fingerprint of the base body`; `a module conflict refuses the edit with its text` (notice with text and mentions, cache takes the server's body); `a re-read that finds another body refuses the edit`; `a re-read that finds no message refuses as deleted`; `takeRefusedEdit gives the text back once`; `an answered edit rebases the next one`; `delete NotFound counts as done`; `edit NotFound is vanished`; `a load keeps the optimistic edit and the hidden delete`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit**: `[ADD] chat: edit and delete queued, late edits refused`.

### Task 8: Posts with mentions, @everyone and reply (D4, D8)

**Files:** M `chatOutbox.ts` (`queuePost` `:338`, `queuePostNow` `:395`, `sendPost` `:1354`), `chatService.ts` (`send` `:553`), tests `chatOutbox.test.ts`, `chatService.test.ts`.

**Interfaces:**
- `queuePost(..., opts)` and `ChatService.send(..., opts)` gain `mentions?: Mentions` and `replyTo?: MessageTarget | null`; the post params gain `mentions` and `parent: MessageTarget | null`; the pending row gets `parentId` / `parentClientUuid` and the body `composeBody(text, mentions, conversions).body`.
- `sendPost`: `post_data.body` = `composeBody(...).body + chatMarker(uuid)`; `partner_ids` when non-empty; `special_mentions` when non-empty (every `discuss.channel`, as `store_service.js:572-574`); `parent_id` = the parent's server id, resolved by `messageOf` at send (a parent without one is left out). An answer with `parentMessage: false` is a plain message: the row's parent is cleared, no notice. `findSent`, the quiet window and the module uuid are unchanged.

- [ ] **Step 1: Failing tests:** `a mention sends partner_ids and the anchor`; `@everyone sends special_mentions`; `a reply sends parent_id`; `a reply to a pending message sends the parent's server id`; `a parent dropped by the server gives a plain message`; `a retried post with mentions is found by its marker and not re-sent`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit**: `[ADD] chat: posts with mentions, @everyone and reply parent`.

### Task 9: Emoji picker and composer emoji button (D2, D3)

**Files:** M create `src/components/chat/chat_emoji_picker_component.ts|.scss`; modify `chat_thread_component.ts` (composer row), `src/css/components.scss`, i18n, `featureCatalog.ts` (`chat.emoji` files), tests `chatEmojiPicker.test.ts`, `chatThreadComponent.test.ts`.

**Interfaces:**
- `ChatEmojiPickerComponent` props `{onPick: (codepoints: string) => void; onClose: () => void}`: loads `loadEmojiData()` on mount (a spinner until then), « Fréquents » (`frequentEmoji(42)`) then the categories in `sortId` order with their tabs (`title`), a search field (`searchEmoji`, UI language), sections rendered with `content-visibility: auto`; a pick calls `countEmojiUse` then `onPick`.
- Composer: a 😊 button (`chat-thread__emoji`, `t-on-mousedown.prevent`) opens the picker; a pick inserts at the caret (`selectionStart/End`) and keeps the draft (`draftText.typed`).

- [ ] **Step 1: Failing tests:** the data load is awaited once; search « rieur » shows 😀; frequent first; a pick counts the use; the composer inserts at the caret and the draft holds it.
- [ ] **Step 2–4:** FAIL → implement → PASS; `npm run build`.
- [ ] **Step 5: Commit**: `[ADD] chat: emoji picker and composer emoji button`.

### Task 10: Long-press menu, reaction bar, chips, copy (D2, D10)

**Files:** M create `src/components/chat/chatLongPress.ts`, `chat_message_menu_component.ts|.scss`, `chat_reactions_component.ts|.scss`; modify `chat_thread_component.ts`, `src/css/components.scss`, i18n, `featureCatalog.ts` (leaves `chat.reactions`, `chat.message-actions`), tests `chatLongPress.test.ts`, `chatMessageMenu.test.ts`, `chatReactionsComponent.test.ts`, `chatThreadComponent.test.ts`.

**Interfaces:**
- `chatLongPress.ts`: `LONG_PRESS_MS = 500`, `LONG_PRESS_SLOP_PX = 10`; `class LongPress { constructor(onLong: (key: string) => void, opts?: {delayMs?; slopPx?; setTimer?; clearTimer?}); down(key: string, x: number, y: number): void; move(x: number, y: number): void; up(): void; cancel(): void }` — a timer cancelled by a move beyond the slop, the end or a scroll; no `preventDefault` on pointerdown (scrolling and selection stay); the bubble's `contextmenu` is prevented (no system menu).
- `ChatMessageMenuComponent` props `{quick: string[]; can: {react: boolean; reply: boolean; copy: boolean; edit: boolean; delete: boolean}; onReact(content: string); onMore(); onReply(); onCopy(); onEdit(); onDelete(); onClose()}`: the six of `quickReactions()` and « … » (opens Task 9's picker), then Répondre, Copier, Modifier, Supprimer as `can` allows. Edit and delete: own `comment` messages (sent or pending); react and reply: `comment` messages; copy: any message with a body.
- Copy: `navigator.clipboard.writeText(bodyText(body))` in try/catch, then « Copié » (`chat.copied`) for 1.5 s; a refusal shows `chat.copy_failed`. Delete: `Dialog.confirm(chat.delete_confirm)` then `deleteMessage`.
- `ChatReactionsComponent` props `{reactions: ReactionView[]; onToggle(content); onWho(content)}` with `ReactionView = {content; count; self: boolean; names: string[]}` (partners by cached name, guests as `chat.guest`); a tap toggles the own reaction (`react(…, !self)`), a long press lists who reacted.

- [ ] **Step 1: Failing tests:** long press fires after 500 ms, not after a 12 px move or an early up; the menu hides Edit/Delete on another's message; a quick emoji reacts and closes; « … » opens the picker and a pick reacts; copy writes `bodyText` and shows « Copié »; delete asks and deletes only on yes; a chip tap removes an own reaction and adds another's; a chip long press lists names.
- [ ] **Step 2–4:** FAIL → implement → PASS; `npm run build`.
- [ ] **Step 5: Commit**: `[ADD] chat: long-press menu, reaction bar and chips, copy`.

### Task 11: Thread display — edited, deleted, quotes, mention taps (D4, D6, D8; spec « (edited) as in the browser »)

**Files:** M `chat_thread_component.ts` (`ThreadRow` `:52`, `build` `:384`, `sigOf` `:488`, `rowOf`), `chat_thread_component.scss`, `chat_list_component.ts` (preview `:298-316`), `chatRepository.ts` (`lastMessages`), i18n, tests `chatThreadComponent.test.ts`, `chatListComponent.test.ts`, `chatRepository.test.ts`.

**Interfaces:**
- `ThreadRow` gains `messageKey: string`, `target: MessageTarget`, `reactions: ReactionView[]`, `quote: QuoteView | null` with `QuoteView = {key: string | null; author: string; text: string; edited: boolean; state: "text" | "attachments" | "deleted"}` (`message_in_reply.xml:3-29`: author and `bodyPreview` of the parent, « (modifié) », `chat.quote_attachments`, `chat.quote_deleted` « Message d'origine supprimé »), `can` (Task 10).
- `build` reads reactions and parents in its one `Promise.all` (`reactionsOf` for the window's keys; parents by id or client uuid); hides messages `isEmptyMessage(body, files)` and those with a queued `chat.delete` op (`nonEmptyMessages`, `thread_model.js:576-578`); `renderBody(body, {editedLabel: t("chat.edited"), selfPartnerId})`; the row signature's base gains a reactions digest (`content:count:self` joined) and the quote's key, author, text and state.
- A tap on a quote scrolls to the original when its row is rendered (and highlights it 1 s), else does nothing; a tap on a partner mention opens the direct message (`startDirect`), on the user's own nothing; on a channel link the conversation when cached as a member, else the join confirmation `chat.join_confirm` then `join` (event delegation on `.chat-thread__body`, `data-oe-model` / `data-oe-id`).
- List: the preview is the newest non-empty cached message (`newestPersistentNotEmptyOfAllMessage`, `thread_model.js:542-545`): `lastMessages` falls back to the newest non-empty one when the last is empty.

- [ ] **Step 1: Failing tests:** `an edited message shows « (modifié) »`; `a deleted message is hidden`; `a queued delete hides the row at once`; `quote of a parent with text`, `quote of an emptied parent`, `quote of attachments only`; `tap on a quote scrolls to its row`, `tap on a quote of an unloaded parent`; `a reaction change repaints the row` (signature); `a mention tap opens the direct message`; `a channel link of a non-member asks to join`; `the list skips an emptied last message`.
- [ ] **Step 2–4:** FAIL → implement → PASS; `npm run build`.
- [ ] **Step 5: Commit**: `[ADD] chat: edited, deleted and quoted messages in the thread`.

### Task 12: Composer modes — reply, edit, drafts, « Reprendre » (D5, D8)

**Files:** M create `src/services/migrations/addChatDraftModes.ts`, `src/components/chat/chat_composer_banner_component.ts|.scss`; modify `migrations/index.ts` (`{version: 2026102608, description: "Clavardage : réponse, modification et mentions du brouillon", run: addChatDraftModes}`), `databaseService.ts` (`createChatDraftsTable`, `addChatDraftModes()`), `chatRepository.ts` (draft methods `:1287-1421`), `chatService.ts` (draft API `:616-700`), `chat_thread_component.ts` (`onSend`, `showDraft`), `chat_list_component.ts` (« Reprendre » on the notice), `src/css/components.scss`, i18n, tests `chatRepository.test.ts`, `chatService.test.ts`, `chatThreadComponent.test.ts`, `chatListComponent.test.ts`, `migrations.test.ts`.

**Interfaces:**
- `chat_drafts` gains `reply_to TEXT` (JSON `MessageTarget`), `edit_of TEXT` (JSON `MessageTarget`), `edit_text TEXT`, `mentions TEXT` (JSON `Mentions`, the picks of both texts; the builder keeps only those still in the text).
- `ChatService.draft()` returns also `replyTo: MessageTarget | null`, `edit: {target: MessageTarget; text: string} | null`, `mentions: Mentions`; `saveDraftReply(configId, channelId, target | null)`, `saveDraftEdit(configId, channelId, edit | null)`, `saveDraftMentions(configId, channelId, m: Mentions)`; a temporary-id swap moves them (`moveDraftText`).
- `ComposerMode = {kind: "new"} | {kind: "reply"; target: MessageTarget} | {kind: "edit"; target: MessageTarget}` in the thread state; `ChatComposerBannerComponent` props `{mode; quote: QuoteView | null; onCancel()}` above the composer.
- Reply: Répondre sets the mode and the banner, stored as `reply_to`; ➤ sends with `replyTo` and clears it with the text in the same first step as today.
- Edit: Modifier keeps the new-message text in `text` and fills the composer from `editDraftOf`; `DraftText` saves to `edit_text` while editing; ➤ calls `editMessage`; an emptied edit of a message without files asks `chat.delete_confirm` and deletes on yes (`composer.js:757-786`), with files sends the empty body; ✕ goes back to the kept text.
- « Reprendre »: in the list, `requestResume` then the thread; in the thread, its conversation's `chat.edit` notices show in the banner slot with « Reprendre » and « Ignorer ». `takeResume` → `changed`: edit mode with the refused text over the message's current body; `deleted`: the text joined into the new-message draft (`joinDraftText`), the target being gone.

- [ ] **Step 1: Failing tests:** migration 2026102607 → 08 adds the columns once; `a reply target survives leaving and reopening`; `the edit text survives a restart and the new-message text is kept`; `send in reply mode passes replyTo and clears the banner`; `an emptied edit asks to delete`; `Reprendre of a changed edit opens edit mode with the text`; `Reprendre of a deleted message puts the text in the draft`; `a swapped temporary id keeps the reply target`.
- [ ] **Step 2–4:** FAIL → implement → PASS; `npm run build`.
- [ ] **Step 5: Commit**: `[ADD] chat: reply and edit modes kept in the draft, resume refused edits`.

### Task 13: Composer suggestions @ and # (D9)

**Files:** M create `src/services/chat/chatMentions.ts`, `src/components/chat/chat_suggestions_component.ts|.scss`; modify `chatService.ts` (`mentions` member), `chat_thread_component.ts` (`onInput`, `onSend`, the slot beside `ChatComposerAttachComponent`), `src/css/components.scss`, i18n, `featureCatalog.ts` (`chat.compose` files), tests `chatMentions.test.ts`, `chatSuggestions.test.ts`, `chatThreadComponent.test.ts`.

**Interfaces:**
- `mentionQuery(text: string, caret: number): {kind: "@" | "#"; term: string; start: number} | null` (a delimiter at the start or after whitespace, no whitespace between it and the caret).
- `type Suggestion = {kind: "partner"; id; name} | {kind: "channel"; id; name; parentName: string | null} | {kind: "special"; label: "everyone"}`.
- `class ChatMentions { constructor(repo, rpc, people: ChatPeople, isOnline); local(src, channel: ChatChannel, q): Promise<Suggestion[]>; remote(src, channel, q): Promise<Suggestion[]> }`:
  - `@` local: the channel's cached members with a name (`repo.members` + `repo.partners`, nameless left out); in a public channel, also the people cache (`ChatPeople`'s private `searchCache` made public as `searchCached(configId, term, limit)`);
  - `@` remote: `res.partner.get_mention_suggestions_from_channel(channel_id, search, limit=8)` (Store parsed with `parseStore`);
  - members only in chat, group and channels with an access group (`suggestion_service.js:161-189`): there a remote partner is kept only when a member, or when the channel has an access group (the server already limits to it);
  - `@everyone` in a group or channel once at least 4 typed characters match the start of « everyone » (`suggestion_service.js:207-216`);
  - `#` local: cached member channels of type `channel`; `#` remote: `discuss.channel.get_mention_suggestions(search, limit=8)`;
  - folded matching on name; members first, then the rest.
- `MentionPick = {kind: "partner" | "channel" | "special"; id: number; text: string; start: number}`; `adjustPicks(picks, before: string, after: string): MentionPick[]` (a pick survives when its text is still whole at its shifted place); `picksToMentions(picks): Mentions`.
- Thread: on input the local list shows at once, the remote one merges when it answers (debounce 250 ms; errors and offline ignored, typing never waits); a pick replaces `@term` with `@Name ` (`#Name `, `#Parent > Name `, `@everyone `) and stores the picks (`saveDraftMentions`); ➤ passes `picksToMentions` to `send`/`editMessage`.

- [ ] **Step 1: Failing tests:** `mentionQuery` cases (`mail@x` is no mention, `@` alone, after a line break); offline a member list shows; in a group a non-member from the server is not offered; in a public channel he is; `@ever` offers @everyone in a channel, not in a chat; `#` lists member channels; a server error leaves the local list; a pick inserts the name and records the pick; editing inside a picked name drops it; the send carries the picks.
- [ ] **Step 2–4:** FAIL → implement → PASS; `npm run build`.
- [ ] **Step 5: Commit**: `[ADD] chat: @ and # suggestions in the composer`.

### Task 14: Test kit, device hook, long tests, device scenario (D12)

**Files:** M `src/testing/syncTestKit.ts` (`HARNESS_API = 4`: exports `composeBody`, `bodyText`, `emojiConversions`, `EMPTY_MENTIONS` for the round trip), `src/testing/deviceTestHook.ts` (`DEVICE_HOOK_API = 5`); E `long_test/mobile_sync_odoo.py:58` (4), `long_test/mobile_sync_device.py:50` (5) + `toucher_maintenir(selecteur, ms=700)` (CDP `Input.dispatchTouchEvent` start, wait, end) + scenario in `SCENARIOS` (`(18,)`), `test/test_mobile_sync_harness.py:346,727`, `long_test/mobile_sync/chatPeer.ts`, new `chatActions.test.ts`, `chatWriting.test.ts`.

**Interfaces:**
- Hook: `chatReact(configId, channelId, messageId, content, on)`, `chatEdit(configId, channelId, messageId, text)`, `chatDelete(configId, channelId, messageId)`, `chatSend(configId, channelId, text, opts?: {replyTo?: number; mentions?: Mentions})`, `chatReactions(configId, channelId)`.
- `ChatPeer`: `react(messageId, content, action)`, `edit(messageId, text)` (the browser's input HTML built with the kit's `composeBody`, through `/mail/message/update_content` as chat_user), `deleteMessage(messageId)`, `reactionsOf(messageId)` (`mail.message.reaction` search_read as admin), `bodyOf(messageId)`, `parentOf(messageId)`, `needaction(messageId)` (chat_user's `mail.notification`).

Long tests (`eachVersionFrom(18, …)`, fault proxy, module and `chatModule: "ignore"`; no server-wide setting, so they run in the parallel pass):
- `chatActions.test.ts`:
  - reaction add with the answer dropped → one row; add and remove offline → no request (`proxy.calls`);
  - chat_user's reaction and edit reach the app through the bus without reload;
  - edit of a message with two files keeps both (checks Task 1's `null` reading on a real server);
  - late edit: chat_user edits (then, second case, deletes) while the app's edit waits offline → module 1.3: conflict, body unchanged, notice with the text; `ignore`: the re-read refuses the same way;
  - delete empties the body, removes the files, the app hides it, chat_user's thread too;
  - reply sends `parent_id`; a reply whose parent chat_user deleted shows the deleted quote; a reply to a parent of another channel posts plain.
- `chatWriting.test.ts`:
  - a mention of chat_user in a channel creates chat_user's needaction notification;
  - `@everyone` in a group puts every member in `partner_ids`;
  - `#channel` link stored with `o_channel_redirect`;
  - round trip: for every golden case, the app's post stored body, put through `bodyText` + `composeBody` with the message's recipients and posted as a browser edit by chat_user, comes back equal except the edited span;
  - a leading mention's stored form recorded (the recon's `<span>`/`<p>` question).

Device scenario « actions du clavardage » (18 only): open a conversation where chat_user posted, `toucher_maintenir` on the bubble → the menu, tap 👍 → the chip shows and the server has the reaction (`reactionsOf`); Répondre, type, ➤ → the server message has `parent_id` and the quote shows; Modifier, change, ➤ → « (modifié) » in the bubble and on the server body; screenshots kept by the runner.

- [ ] **Steps:** write; `./long_test/mobile_sync.py --versions 18 --filtre chat` green ×3; full run green; `--appareil` green (the personal app untouched); the harness unit tests (API assertions now 4 and 5); `--detruire`; commits M `[ADD] testing: chat actions in the kit and the device hook`, E `[ADD] long_test: chat actions and writing against a real Odoo 18`.

### Task 15: Contracts, docs, changelogs

- [ ] `contracts/odoo-api.json`: `chat.reaction` (route, explicit action, idempotency, both DELETE forms), `chat.edit` (both routes, `attachment_ids` null, fingerprint, `erplibre_conflict`, re-read fallback), `chat.delete`, `chat.post` gains `partner_ids`, `special_mentions`, `parent_id` and the browser HTML rules, `chat.mention_suggestions` (both methods), `chat.message_delete_bus` (`mail.message/delete`), migrations 2026102607 and 2026102608; `contracts/compatibility.json` module `18.0.1.3.0` (the 1.3 sentence); `long_test/README.base.md` (actions and writing sections, the goldens script); ERPLibre and mobile `CHANGELOG.base.md` (the emoji data and their licence named); mmg; commits E `[UPD] contracts: Odoo 18 chat actions, writing and module 1.3`, E `[UPD] doc: chat actions long tests and changelog`, M `[UPD] changelog: chat lot 4, actions and writing`.
