# ERPLibre mobile chat, lot 2 (new conversations and management) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From the phone, start a direct message, create a group or a
channel, join a public channel, manage members, rename and describe,
leave or hide, and mute (per conversation and globally) — online or
offline, never doubled, matching what Odoo 18's browser shows.

**Architecture:** Lot 1's `ChatService` / `ChatOutbox` / `ChatRepository`
grow new outbox kinds (create, join, invite, rename, describe, leave,
hide, mute, global mute, remove) that carry `params.channelId` and chain
through `dependsOn`. A conversation created offline lives under a
negative temporary channel id that is swapped for the server's id when
its create settles. Group and channel creation are idempotent through
the server module (version 18.0.1.1.0, client uuid in the context) or,
without it, a fingerprint search after the quiet window. Two new screens:
`/chat/new` and `/chat/:source/:channelId/info`.

**Tech Stack:** as lot 1 (TypeScript, Owl 2, Capacitor 8, SQLite, Vitest;
Odoo 18 module in Python; ERPLibre long tests).

**Spec:** `docs/superpowers/specs/2026-10-25-erplibre-mobile-chat-design.md`
(Lot 2, « Details decided for later lots »). Lot 1 facts and the Odoo 18
reading for lot 2: `tasks/chat/odoo-facts.md`, `tasks/chat/lot2-recon.md`
(not versioned).

## Global Constraints

- Everything in the lot 1 plan's Global Constraints still holds (Odoo 18 only, server choice modes, unread rules — with « no_notif » NOT muted, https/wss policy, catalog/i18n/no-`${}`, comments, commit and branch rules: branch `dev/mobile_chat` in each repo, never push).
- Muted = the conversation's `mute_until_dt` in the future OR the account's global mute (`res.users.settings.mute_until_dt`) in the future, as Odoo's `Thread.isMuted`.
- Mute durations offered: 15 min, 1 h, 3 h, 8 h, 24 h, until turned back on (minutes 15, 60, 180, 480, 1440, -1). Unmute = `false`.
- A group without a name is shown with its members' names, self included, ordered by member id, joined by `Intl.ListFormat(lang, {type:"conjunction", style:"long"})`; renaming a group to `""` brings that back. A channel is renamed only to a non-empty name. A chat's rename is the user's own label (`channel_set_custom_name`).
- Who to write to: recent people (cached shown chats with a correspondent, by `lastInterestDt` desc then channel id desc), then a server search (`res.partner.im_search`).
- New channel: access group defaults to Odoo's (`Store.internalUserGroupId` = internal users), changeable on the spot among the user's own groups, or « everyone » (false).
- Leaving: confirmation for a group or a channel; hiding a direct message asks nothing. Leave is offered as Odoo's `canLeave` (channel or group, no mention pending, not group-based subscription, no parent channel).
- Removing another member: only when `isSystem` (Settings group) AND the server module ≥ 18.0.1.1.0 is installed; the person is told (Odoo's leave flow). Otherwise only oneself leaves.
- Global mute: settable in Options › Chat with the same durations; while active, per-conversation mute controls are hidden.
- Mute, typing, rename and invite are sent only for conversations where the user is a member (Odoo's mute route joins a non-member).
- Every action queues offline and leaves by itself; a create is never doubled; an action whose conversation vanished is dropped with a notice.

## Review Focus

1. **Group created offline, app killed, network back:** one group on the server, the messages written into it while offline posted once, in order, into the real group (Task 6 test `offline group then posts survive a restart and the id swap`).
2. **The other person's new DM or group:** their first message arrives live on this phone without a full reload per message (resubscribe on new self membership; Task 4 test `a channel that gains self membership resubscribes once`).
3. **Leaving a conversation with a post still queued:** the post is not sent after the leave; the bubble turns failed with « conversation quittée » (Task 7 test `leave cancels the queued posts of that conversation with a notice`).
4. **A mute queued offline longer than its duration:** sent after it expired it unmutes (or no-op) instead of muting for the full duration from send time (Task 7 test `an expired queued mute sends false`).
5. **Server with the 1.0 module (or none):** creating a group never doubles (fingerprint path), and an admin is offered the module upgrade (Task 2 and Task 6 tests).

---

## File Structure

**Addons** `erplibre_mobile_chat/` (version → `18.0.1.1.0`): `models/discuss_channel.py` (create dedupe by context uuid, `erplibre_remove_member`), field on `discuss.channel`, tests.

**Mobile** (new): `src/services/chat/chatPeople.ts` (people, recent, channels to join, invite candidates, access groups), `src/services/chat/chatNames.ts` (`displayNameOf`), `src/services/chat/chatManage.ts` (manage actions façade used by screens), `src/services/migrations/addChatLot2Columns.ts` (migration `2026102601`), `src/components/chat/chat_new_component.ts|.scss`, `src/components/chat/chat_info_component.ts|.scss`. Modified: `chatOutbox.ts`, `chatService.ts`, `chatRepository.ts`, `chatStore.ts`, `chatUnread.ts`, `chatModule.ts`, `chatLifecycle.ts`, `odooRpcClient.ts` (session info), `databaseService.ts`, list/thread components, `options_chat_component.ts`, `applications_edit_component.ts`, `routes.ts`, i18n, `featureCatalog.ts`, `syncTestKit.ts`, `deviceTestHook.ts`, `CHANGELOG.base.md`.

**ERPLibre:** `long_test/mobile_sync/chatManage.test.ts` (new), `chatPeer.ts`, `long_test/mobile_sync_device.py`, `long_test/mobile_sync_odoo.py` (HARNESS key unchanged unless the kit API changes), `contracts/odoo-api.json`, `contracts/compatibility.json`, docs and changelogs.

---

### Task 1: Lot 1 carry-overs

**Files:** `chat_thread_component.ts`, `chatOutbox.ts`, `chatService.ts`, `chatLifecycle.ts`, `appService.ts` (change payload), tests beside each.

**Interfaces:**
- `ChatService.startSourceRealtime(configId)`, `stopSourceRealtime(configId)` (public; `startRealtime`/`stopRealtime` keep working on all).
- `ApplicationsChange` gains `{ kind: "add"|"edit"|"delete"; configId: string; previousConfigId?: string; realtimeRelevant: boolean }` — `realtimeRelevant` false when only autoSync / poll interval / ntfy fields changed.

- [ ] **Step 1: Failing tests:**
  - `a markRead arriving during an in-flight markRead runs once more after it` (thread; `_markAgain` rerun in finally, same for onScroll).
  - `a post settled after its account was deleted writes nothing` (`settleNow` returns when `db.getOutboxOp(op.id)` is gone).
  - `deleting an account does not wait for a pending load of that account` (forgetSource stops that source's realtime and lets its pending load be ignored by a generation check, then erases).
  - `editing autoSync restarts no bus`; `editing one account's password restarts only that account's bus`.
  - `markRead after an own send sends nothing when already seen` (skip when `seenMessageId >= lastMessageId && unreadCounter === 0 && needactionCounter === 0`).
- [ ] **Step 2–4:** FAIL → implement → PASS; `npm test`.
- [ ] **Step 5: Commit** (mobile): `[FIX] chat: lot 1 carry-overs, mark read reruns, per-account restart`.

### Task 2: Server module 18.0.1.1.0 — idempotent creates, admin removal

**Files:** addons `erplibre_mobile_chat/__manifest__.py` (version `18.0.1.1.0`), `models/discuss_channel.py`, `tests/test_erplibre_mobile_chat.py`.

**Interfaces:**
- Field `discuss.channel.erplibre_client_uuid` (Char, `index="btree_not_null"`, `copy=False`, `readonly=True`).
- `discuss.channel.create(vals_list)`: when `self.env.context.get("erplibre_client_uuid")` is set and a channel with that uuid and `create_uid = env.uid` exists, return it instead of creating; otherwise store the uuid on the created record. The app passes the uuid in the call's context for `create_group` and `channel_create` (an unknown context key is ignored by a server without the module).
- `discuss.channel.erplibre_remove_member(partner_id)` (public, on `[[channel_id]]`): raises `AccessError` unless `self.env.user._is_system()`; refuses `chat`; calls `self._action_unfollow(self.env["res.partner"].browse(partner_id))` (Odoo's leave: the removed person gets `discuss.channel/leave`, the thread shows they left).

- [ ] **Step 1: Failing tests:** `test_create_group_same_uuid_twice_gives_one_group`, `test_channel_create_same_uuid_twice_gives_one_channel`, `test_uuid_of_other_user_not_adopted`, `test_create_without_uuid_unchanged`, `test_remove_member_by_admin_leaves_with_notice` (member row gone, a « left the channel » message exists, the removed partner received `discuss.channel/leave` — assert through `bus.bus` rows), `test_remove_member_refused_for_non_admin`, `test_remove_member_refused_in_chat`.
- [ ] **Step 2–4:** run the module tests (command of lot 1 Task 1) FAIL → implement → PASS; `dropdb chat_module_test`.
- [ ] **Step 5: Commit** (addons): `[IMP] erplibre_mobile_chat: idempotent group and channel create, admin removal`.

### Task 3: Schema, parsing, session info, display names

**Files:** `src/services/migrations/addChatLot2Columns.ts` + `migrations/index.ts` (`{version: 2026102601, description: "Clavardage : colonnes du lot 2", run}`), `databaseService.ts` (ALTER pattern of L498; also add the columns to `createChatTables` for fresh installs), `chatRepository.ts`, `chatStore.ts`, `models/chat.ts`, `odooRpcClient.ts`, `src/services/chat/chatNames.ts`, `chatUnread.ts`, tests.

**Interfaces:**
- `ChatChannel` gains `isPinned: boolean` (default true), `isEditable: boolean|null`, `customChannelName: string|null`, `memberCount: number|null`, `groupPublicId: number|null`, `authorizedGroupFullName: string|null`, `createUid: number|null`, `groupBasedSubscription: boolean`, `parentChannelId: number|null`, `createOpId: string|null`. `ChatMember` gains `createDate: string|null`. `ChatSourceState` gains `internalUserGroupId: number|null`, `globalMuteUntil: string|null`, `isInternalUser: boolean`.
- `parseStore` copies `is_pinned, is_editable, custom_channel_name, memberCount, group_public_id, authorizedGroupFullName, create_uid, group_based_subscription, parent_channel_id`, member `create_date`, and `Store.settings.mute_until_dt` → `globalMuteUntil` when present.
- Partner rows merge (a record without `im_status` keeps the stored presence; a record without `name` updates the other keys of a known partner).
- A `""` name is accepted for a `group` (rename back to members' names); still ignored for other types.
- `SessionInfo` gains `internalUserGroupId` (`storeData.Store.internalUserGroupId`), `globalMuteUntil` (`storeData.Store.settings.mute_until_dt`), `isInternalUser` (`is_internal_user`).
- `displayNameOf(channel, members: ChatMember[], partners: Map<number, ChatPartner>, selfPartnerId: number|null, lang: string): string` — order: chat custom name → correspondent name → nameless group as ListFormat of members by member id → `name` → for a self-chat the self name. List and thread use it.
- `isMuted(c, now, globalMuteUntil?)`.

- [ ] **Step 1: Failing tests:** migration adds the columns on a lot 1 database (tables already present); parse of each new key; partner merge keeps `imStatus`; group renamed to `""`; `displayNameOf` cases (en and fr lists, self-chat); `isMuted` with global mute; session info parses the three fields.
- [ ] **Step 2–4:** FAIL → implement → PASS; `npm test`.
- [ ] **Step 5: Commit**: `[ADD] chat: lot 2 columns, display names, global mute in session`.

### Task 4: Bus and service — hidden DMs, resubscribe, presence, global mute

**Files:** `chatService.ts`, `chatBus.ts` (if needed), tests.

**Interfaces:**
- `shown(c) = (isMember || localPinned) && (c.channelType !== "chat" || c.isPinned)`.
- `applyOne` handles `discuss.channel/unpin {id}` (→ `isPinned false`), `res.users.settings {mute_until_dt}` (→ `globalMuteUntil`), and `{id, is_pinned:true}` inserts.
- Resubscribe rule: after any Store applied (bus or RPC) that makes self a member of a channel that was unknown or not a member, and after a leave, call `resubscribe(configId)` once per delivery batch (public `ChatService.resubscribe(configId)`).
- Presence channels: every cached partner of the account that has a user (`odoo-presence-res.partner_<id>`), capped at 200 most recent (constant `PRESENCE_CAP`).
- `applyNewMessage`: a message in a cached channel where self is not a member updates nothing and triggers no reload (no storm); an unknown channel reloads at most once per 10 s per account (constant).
- `loadNow` keeps channels with an unfinished create op (`createOpId` set).

- [ ] **Step 1: Failing tests:** `unpin hides a DM, a new message shows it again`; `a channel that gains self membership resubscribes once`; `leave resubscribes`; `global mute from settings mutes every conversation and clears`; `new_message on a non-member cached channel reloads nothing`; `unknown channels reload at most once per window`; `load keeps a channel being created offline`; presence channels include group members.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit**: `[ADD] chat: hidden direct messages, resubscribe on membership, presence`.

### Task 5: Module status 1.1 and upgrade offer

**Files:** `chatModule.ts`, `models/chat.ts` (`ChatModuleState` gains `"outdated"`), `applications_edit_component.ts`, i18n, tests.

**Interfaces:** `installed` = `discuss.channel` fields contain `erplibre_client_uuid`; `outdated` = only `mail.message` has it; `upgradeModule(rpc, capabilities, creds)` = `button_immediate_upgrade` on the module row (isSystem only), timeout treated like install (re-probe fresh). Edit screen shows `chat.module_outdated` + `chat.module_upgrade` button for admins. `ChatService` features: `canRemoveMembers = isSystem && moduleState === "installed"`, `idempotentCreate = moduleState === "installed"`.

- [ ] **Step 1: Failing tests:** state matrix (both fields / message only / none × system / not); upgrade then probe → installed; non-admin never sees the button.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit**: `[ADD] chat: module 1.1 detection and upgrade offer`.

### Task 6: Outbox — creates, join, temporary ids

**Files:** `chatOutbox.ts`, `chatRepository.ts` (`swapChannelId(configId, tempId, realId)`), `chatService.ts` (façade methods), tests.

**Interfaces:**
- Kinds: `CHAT_CREATE = "chat.create"` params `{channelId: tempId (<0), mode: "dm"|"group"|"channel", partnerIds: number[], name: string, groupId: number|false, useModule, createSentAt?}`; `CHAT_JOIN = "chat.join"` params `{channelId}`.
- `ChatService.startDirect(src, partnerId): Promise<{configId, channelId}>` — an existing cached shown chat with that correspondent is returned at once; else a temp chat row + `chat.create` (`channel_get` is idempotent server-side: a retry needs no fingerprint).
- `ChatService.createGroup(src, partnerIds, name = "")`, `createChannel(src, name, groupId: number|false)` → temp row (`createOpId` set) + op. Send: `create_group` / `channel_create` with `context: {erplibre_client_uuid: op.clientUuid}` when `useModule`; without the module, a retry after the quiet window first searches `discuss.channel` `[["create_uid","=",uid],["channel_type","=",t],["create_date",">=", createSentAt − 5 min],["is_member","=",true]]` (+ `["name","=",name]` when named) and compares members (`partner_ids` via `/discuss/channel/members` or the Store): one match adopts, several block `"ambiguous"`.
- Settle (inside `serial`): `applyDelta(parseStore(result))`, then `repo.swapChannelId(configId, tempId, realId)` — moves `chat_messages`, `chat_members`, merges into the real row if the bus already wrote it, rewrites `params.channelId` of every op of that account with `channelId === tempId`, clears `createOpId`; then `resubscribe(configId)`; `onChange(configId, realId)` so an open thread on the temp id navigates to the real one.
- `queuePost` into a temp channel: `dependsOn` = the create op when the channel's chain is empty.
- `ChatService.join(src, channelId)` → `chat.join` → `/discuss/channel/join {channel_id}` → apply Store, resubscribe.
- Cancelling a create (refused, or the user discards) cancels its dependents and marks their bubbles failed (`chat.create_failed`).

- [ ] **Step 1: Failing tests:** `direct message reuses a cached chat`; `offline group then posts survive a restart and the id swap` (Review Focus 1: restart = new ChatService over the same db); `group create lost response with module adopts`; `group create lost response without module adopts by fingerprint after the quiet window`; `two fingerprint matches block ambiguous`; `bus insert before settle merges into one row`; `join then a message arrives live`; `refused create fails its queued posts with a notice`.
- [ ] **Step 2–4:** FAIL → implement → PASS; `npm test`.
- [ ] **Step 5: Commit**: `[ADD] chat: create direct messages, groups and channels offline, join`.

### Task 7: Outbox — members, rename, describe, leave, hide, mute, remove

**Files:** `chatOutbox.ts`, `chatService.ts`, tests.

**Interfaces (all carry `params.channelId`; target-state kinds coalesce one op per channel and kind, the last value wins):**
- `chat.invite {channelId, partnerIds}` → `add_members [[cid]] {partner_ids}` (refuses chats: inviting into a chat = `createGroup(correspondent + picked)`).
- `chat.rename {channelId, name}` → group/channel `channel_rename`, chat `channel_set_custom_name`; `chat.describe {channelId, description}` → `channel_change_description`. Applied locally at once.
- `chat.leave {channelId}` → `action_unfollow [cid]`; locally: channel hidden at once, queued posts/actions of that channel cancelled and their bubbles failed with `chat.left_conversation`.
- `chat.hide {channelId}` → `channel_pin [cid] {pinned:false}`; locally `isPinned false`.
- `chat.mute {channelId, until: string|"forever"|null}` and `chat.global_mute {until}` → `/discuss/settings/mute {minutes, channel_id?}` with minutes computed at send time: forever → -1, null → false, else `ceil((until − now)/60000)`, ≤ 0 → false. Locally applied at once.
- `chat.remove {channelId, partnerId}` (only when `canRemoveMembers`) → `erplibre_remove_member [[cid]] [partnerId]`.
- `ChatService` façade: `invite, rename, describe, leave, hide, mute, globalMute, removeMember, members(src, channelId)` (pages `/discuss/channel/members {channel_id, known_member_ids}`, cached in `chat_members` + `memberCount`).

- [ ] **Step 1: Failing tests:** each kind's request shape; coalescing (two renames → one request with the last name); `leave cancels the queued posts of that conversation with a notice` (Review Focus 3); `an expired queued mute sends false` (Review Focus 4); `forever mute sends -1`; `mute is never sent for a non-member channel`; `remove refused when not admin or module old`; `invite into a chat creates a group`; `members pages until all are cached`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit**: `[ADD] chat: members, rename, leave, hide, mute and removal through the outbox`.

### Task 8: People, channels to join, access groups

**Files:** `src/services/chat/chatPeople.ts`, tests.

**Interfaces:** `recentPeople(configId): Promise<ChatPartner[]>` (cache only); `searchPeople(src, term, limit = 20): Promise<ChatPartner[]>` (`im_search [term, limit, excludedIds]`, results merged into `chat_partners`, offline → cache search by name); `joinableChannels(src, term = "", limit = 50)` (`search_read discuss.channel [["parent_channel_id","=",false],["channel_type","=","channel"],["is_member","=",false],["name","ilike",term]] ["name","description","member_count","group_public_id"]`); `inviteCandidates(src, channelId, term)` (`search_for_channel_invite [term, channelId]`); `accessGroups(src)` (`search_read res.groups [["share","=",false],["users","in",[uid]]] ["full_name"]`, plus `{id:false, fullName: t("chat.access_everyone")}`), default = `internalUserGroupId`.

- [ ] **Step 1: Failing tests:** recent order (lastInterestDt desc, id desc; hidden chats excluded); search merges partners and excludes self; offline search uses the cache; joinable domain exact; access groups default.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit**: `[ADD] chat: people, channels to join and access groups per server`.

### Task 9: New conversation screen

**Files:** `src/components/chat/chat_new_component.ts|.scss`, `routes.ts` (`/chat/new` before `/chat`), list component (＋ button `chat.new`), i18n, catalog leaf `chat.new` (route demo `/chat/new`), tests.

**Behaviour:** server choice as the list (none / chips / dropdown; the last used server preselected); « Récents » then search results (debounced 300 ms, min 0 chars → recent only); tap a person → `startDirect` → thread; « Créer un groupe » → multi-select people + optional name → `createGroup` → thread; « Créer un canal » → name (required) + access group (default internal users, a select to change it) → `createChannel` → thread; « Rejoindre un canal » → `joinableChannels` list → `join` → thread. Offline: recent and cached people only, actions queue; screens show ⏳ for a conversation still being created.

- [ ] **Step 1: Failing tests:** modes per number of servers; recent then search; tap person opens the thread of the DM (temp or real); group needs ≥ 2 people; channel needs a name, default group preselected; join list.
- [ ] **Step 2–4:** FAIL → implement → PASS; `npm run build`.
- [ ] **Step 5: Commit**: `[ADD] chat: new conversation screen, people, groups, channels, join`.

### Task 10: Conversation info screen

**Files:** `src/components/chat/chat_info_component.ts|.scss`, `routes.ts` (`/chat/:source/:channelId/info`), thread header (tap title → info), i18n, catalog leaf `chat.info`, tests.

**Behaviour:** name (rename per type rules; editable when `isEditable` or chat), description (channel and group; editable when `isEditable`), members list (presence dots; « Inviter » when allowed: channel → group matches, group → member, chat → creates a group; « Retirer » per member only when `canRemoveMembers` and not self, with confirmation), mute (durations of the Global Constraints; hidden while global mute active; shows « jusqu'au <date> » or « jusqu'à réactivation »), leave (`canLeave`, confirmation) or hide (chat, no confirmation).

- [ ] **Step 1: Failing tests:** controls shown/hidden per type, rights and module; rename rules (channel non-empty, group "" allowed); leave asks, hide does not; mute options and global-mute hiding; remove only for admins with module 1.1.
- [ ] **Step 2–4:** FAIL → implement → PASS; `npm run build`.
- [ ] **Step 5: Commit**: `[ADD] chat: conversation info, members, rename, mute, leave`.

### Task 11: Global mute in options

**Files:** `options_chat_component.ts`, i18n, tests.
- Per configured Odoo 18 server (none / chips / dropdown as elsewhere): global mute state and the six durations + « Réactiver ».
- [ ] Steps: failing tests (sets and clears through `globalMute`), implement, `npm test`, commit `[ADD] chat: global mute per server in options`.

### Task 12: Test kit, device hook, long tests, device scenario

**Files:** mobile `syncTestKit.ts` (HARNESS_API 3 if exports change incompatibly, else stays 2), `deviceTestHook.ts` (DEVICE_HOOK_API 3: `chatNewGroup(configId, partnerIds, name)`, `chatOpenInfo(configId, channelId)`), ERPLibre `long_test/mobile_sync_odoo.py` / `mobile_sync_device.py` (API constants), `long_test/mobile_sync/chatPeer.ts` (invite, rename, leave, mute, members, as chat_user), new `long_test/mobile_sync/chatManage.test.ts`.

Scenarios (Odoo 18 only, server truth through OdooAdmin): DM to chat_user (once, reused); group created offline then 2 posts, restart, network back → one group, 2 posts in order (Review Focus 1); same without the module (`chatModule: "ignore"`, fingerprint path; the 18 template has 1.1 installed); channel created with default group (server `group_public_id` = base.group_user) and with « everyone »; chat_user's new group reaches the app live (Review Focus 2); join a channel chat_user created; invite; rename (group to "" → names); description; leave with a queued post (Review Focus 3); hide a DM then chat_user writes → shown again; mute 1 h → server `mute_until_dt` ≈ now+1 h; expired queued mute → false (Review Focus 4); global mute; admin removal (chat_user receives leave, « left » message) and refusal for chat_user. Device: create a group from the phone with chat_user, send, chat_user replies → live.
- [ ] Steps: write, `./long_test/mobile_sync.py --versions 18 --filtre chat` green ×3, full run green, `--appareil` green (personal app untouched), `--detruire`, commits (mobile `[ADD] testing: lot 2 chat in the kit and the device hook`, ERPLibre `[ADD] long_test: chat management against a real Odoo 18`).

### Task 13: Contracts, docs, changelogs

- [ ] `contracts/odoo-api.json` (`chat.create_dm`, `chat.create_group`, `chat.create_channel`, `chat.join`, `chat.invite`, `chat.rename`, `chat.describe`, `chat.leave`, `chat.hide`, `chat.mute`, `chat.global_mute`, `chat.remove`, `chat.members`, `chat.people`, migration 2026102601 columns), `contracts/compatibility.json` (module 18.0.1.1.0), `long_test/README.base.md`, ERPLibre and mobile `CHANGELOG.base.md` + mmg; commits `[UPD] contracts: Odoo 18 chat lot 2 calls`, `[UPD] doc: chat lot 2 long tests and changelog`, mobile `[UPD] changelog: chat lot 2, new conversations and management`.
