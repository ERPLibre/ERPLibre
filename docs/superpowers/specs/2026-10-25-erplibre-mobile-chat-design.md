# ERPLibre mobile: chat with Odoo 18 Discuss

**Status:** draft for project 1 (text chat), five lots. Projects
2 to 4 are named here for context and get their own design.
**Builds on:** the mobile sync of `erplibre_home_mobile` (applications per
server, outbox, note links, long tests in `long_test/mobile_sync*`).

## Intent

The phone is where the team talks most, and the Odoo web client in a mobile
browser is not where anyone goes to send a quick message. The app already
holds an account per Odoo server; it becomes the team's messenger on those
servers: direct messages, groups and channels of Odoo 18 Discuss, sent in a
few seconds, readable without network, the same conversations the browser
shows.

The whole stack stays under the user's control: Odoo, the app, and later
ntfy and coturn on their own hosts. No Firebase, no third-party relay.

## The four projects, in order

1. **Text chat** (this document): conversations, realtime while the app is
   open, offline history and outbox, attachments, actions, search, inbox.
2. **Notifications when the app is closed**: the app holds one ntfy
   connection in a foreground service (persistent notification), Odoo 18
   web push registered with an ntfy endpoint, modes normal / economic /
   off, follows the phone's battery saver; the alert transport stays
   abstract so iOS can use APNs later.
3. **Infrastructure through `todo.py`**: deploy coturn (and ntfy if needed)
   on a host chosen over ssh, and write the ICE servers into Odoo
   (`mail.ice.server`).
4. **Video calls**, peer to peer, 2 to 5 colleagues, using the coturn of
   project 3.

Project 1 must not close a door on 2 and 4: the realtime connection and
the store of conversations are reused by both.

## Decisions (the user's)

- **Odoo 18 only.** Servers in 16 or 17 have no chat in the app; the
  previous versions are ignored for simplicity.
- **Entry point:** a 💬 Chat tile on the home screen, with the unread count
  of all servers on it.
- **One mixed list** of conversations from every server, most recent first,
  unread ones always above the others, each row tagged with its server
  name. With two accounts on the same server, each account is its own
  source; the tag then also shows the user.
- **Choosing a server** (filter of the list, and the server of a new
  conversation), counting the configured Odoo 18 applications:
  - 0: chat is unavailable; the tile stays and says an Odoo 18 server must
    be configured, with a way to add one (the wording and the link are the
    builder's call);
  - 1: no choice is shown at all;
  - 2 to 4: chips under the title, each with its unread count, plus « All »
    in the list;
  - 5 or more: a dropdown in the title.
- **Unread counts, as Odoo counts them:** a direct message or a group
  counts its unread messages; a channel counts only its mentions (unread
  without mention shows it bold, but neither counts nor lifts it). The tile
  and the chips show a total in messages, inbox included, rather than the
  browser's number of conversations. A muted conversation is left out of
  the total; muted means a mute date still ahead, as Odoo's
  `Thread.isMuted`: « no_notif » only silences notifications and is not
  muted. The server module (below) may add counters later.
- **Offline:** the whole history the user has loaded stays on the phone.
  History loads progressively, on demand: scrolling back fetches older
  messages, and a conversation can be fetched in full on request.
- **Everything queues offline**, and leaves by itself when the network
  returns, never lost, never applied twice: messages, attachments and
  voice (the file stays on the phone until sent), reactions, edits,
  deletes, read, mute, pins, and the creation of a group or a channel (it
  exists on the phone at once, on the server on return). An action whose
  target vanished meanwhile (a message deleted by someone else) is dropped
  with a notice.
- **Duplicates: the module if present, else a marker.** Odoo 18 stores
  nothing that identifies a client post (`temporary_id` only lives in the
  request context and the bus payload). An ERPLibre server module stores a
  client id on `mail.message` (and on a created conversation) and makes
  the post idempotent; it is also where later server features go. Without
  the module, the app hides a marker in the message HTML, an HTML comment
  `<!-- erplibre-mobile:<uuid> -->` (the `mail.message.body` sanitizer
  keeps comments and strips any `data-oe-*` attribute outside its
  whitelist), and looks for it before resending. The « Edit an
  application » screen shows whether the module is available and whether
  it is installed, and offers to install it only when it is available and
  not installed. Reading `ir.module.module` and installing need the
  settings group (`is_system`): for anyone else the status says
  « installed » or « unknown ».
- **Deleting an application erases its chat from the phone:** its
  conversations, messages and sync state, and its rows in the outbox. The
  messages of that account not sent yet are announced first, by their
  count in the deletion's confirmation.
- **Storage:** text is always kept. Attachments download when opened and
  are cached. A purge removes cached attachments, periodically and on
  request; the space used is shown per conversation.
- **Message actions:** emoji reactions, edit and delete (own messages, as
  Odoo allows), reply (quote of the original), copy text.
- **Writing:** @mention, #channel link, emoji picker, and « rich text »
  meaning what the browser's composer itself produces: mentions, channel
  links, URLs as links, emoji, line breaks. No bold or lists: a message
  edited later in the browser must come out the same.
- **Attachments to send:** camera photo, gallery photos, any file, voice
  message (hold to record, as Odoo 18's voice message).
- **Conversations:** create a group with people, create a channel (name and
  access group), join a public channel, manage members, rename and
  describe, leave, mute (for a time or for good, as Odoo 18).
- **People:** the internal users of each server the user can write to, by
  server, with presence.
- **Read and typing:** sent as Odoo does, each one can be turned off in the
  settings. Turning « read » off keeps the conversation unread in Odoo too:
  it is the same server counter, the settings say so.
  *Designer's call:* the « read » switch also stops the « received » mark
  (`channel_fetched`), and its text says that posting a message still
  marks the conversation read: Odoo 18 does it on every post
  (`_message_post_after_hook`), the app cannot prevent it.
- **Finding things:** search on the phone first (works offline), completed
  by the server when online; pinned conversations (local to the phone:
  Odoo 18 has no per-user order of conversations), pinned messages of a
  channel and starred messages (both Odoo's), unread first.
- **Inbox included:** Odoo's inbox (mentions and followed records: tasks,
  opportunities…) is an entry of the chat; an item opens the app's note
  when the record is linked to one, otherwise the record.
- **Tests like the sync:** unit tests in the mobile repo with a fake Odoo;
  long tests in ERPLibre against a disposable real Odoo 18; a few
  scenarios on a plugged phone.

## Failure, even if it technically works

The user named four, all of them are acceptance criteria:

- **Slow to send:** more than about 2 s from the tile to typing in the last
  conversation, or a message that does not show at once in the thread.
- **A message lost or doubled**, offline or across a dropped response.
- **Battery drained** while the app is open or in the background.
- **Different from Odoo:** unread counts, read marks, reactions, members or
  edits that disagree with what the browser shows for the same account.

## Non-goals of project 1

- Notifications when the app is closed (project 2). While the app is in
  the foreground, a new message may raise an in-app indicator.
- Calls and video (project 4); a call started in the browser may show as
  « call in progress » but cannot be joined.
- Odoo 16 and 17, livechat, guests and portal users, chatter composition on
  records (the inbox reads them; replying in a record's chatter is not
  required).
- iOS. Nothing in the design may depend on Android-only APIs without an
  abstraction, so iOS stays reachable.

## Lots

Each lot ships, is tested and is usable on its own; the order is the
user's. Each lot queues its own actions offline through the lot 1 outbox.

1. **Core.** Tile and unread badge, server choice, mixed list,
   conversation screen, text send, realtime, read and typing, the chat
   outbox (built for every kind of action above, used here for posts and
   read), progressive history, the settings for read/typing. The server
   module (`erplibre_mobile_chat` is a working name; where it lives is the
   builder's call) with the idempotent post, the hidden-marker fallback,
   and its status and install offer in « Edit an application ».
2. **New conversation and management.** People per server with presence,
   direct message, group, channel creation and join, members, rename and
   description, leave, mute.
3. **Attachments.** Camera, gallery, file, voice; download on open, cache,
   purge (periodic and on request), space per conversation.
4. **Actions and writing.** Reactions, edit/delete, reply, copy, @mention,
   #channel, emoji picker, rich text.
5. **Finding.** Search local then server, pinned conversations, pinned
   messages, starred messages, inbox.

## Constraints found in Odoo 18 and the app

- **The websocket is native.** The WebView does not hold the Odoo session
  (the app's requests go through the native `RawHttp` with an explicit
  cookie), a WebView socket would carry its own origin (which
  `bus/websocket.py` downgrades to a public session when
  `ODOO_BUS_PUBLIC_SAMESITE_WS` is set), and project 2 needs the socket
  outside the WebView anyway. The realtime connection is a Capacitor
  plugin, sending the server's own origin and the session cookie the app
  already holds; it lives outside the screens.
- `GET /websocket?version=<bus version>` (`18.0-7`, given by
  `websocket_worker_version` in the session info) closes with
  `OUTDATED_VERSION` when a browser sends an old version; the client
  sends `subscribe` with the last notification id it saw and
  `update_presence`. Bus rows live 24 h: a longer gap reloads
  `/mail/data`. When the socket cannot be held,
  `/websocket/peek_notifications` catches up.
- **History never clears mentions behind the user's back.**
  `/discuss/channel/messages` marks the fetched messages done (clearing
  channel mentions and inbox) unless `around` is given, so the app always
  pages with `around`; reading is only ever the explicit
  `mark_as_read`, plus `mail.message.mark_all_as_read` on the channel when
  it has mentions, as the web client does.
- **Typing joins a channel**: `notify_typing` makes the user a member, so
  typing is sent only in conversations the user is a member of.
- Initial data comes from `/mail/data` (`init_messaging`,
  `channels_as_member`) and the session's store data; messages from
  `/discuss/channel/messages` (before / after / around / limit). The store
  format of 18 is keyed by model name with relations as
  `{id, model}`; the client must merge inserts and deletes rather than
  replace records.
- Sending is `/mail/message/post` with a client `temporary_id`; edit is
  `/mail/message/update_content`, delete is the same with an empty body;
  reactions `/mail/message/reaction`; read `/discuss/channel/mark_as_read`;
  typing `/discuss/channel/notify_typing`; attachments
  `/mail/attachment/upload` (multipart, csrf token).
- Direct message `discuss.channel.channel_get`, group `create_group`,
  channel `channel_create` (a channel requires an access group), members
  `add_members`, leave `action_unfollow`; people
  `res.partner.im_search` (internal users only). Only internal users can
  create conversations.
- **No duplicate on retry.** A post or a creation whose response was lost
  is recognised (module id, else hidden marker) before it is sent again;
  the outbox of the sync (marker, adoption of a found record, blocked rows)
  is the pattern to follow, and the same failure classes are tested
  (server down, response dropped, delayed). Actions that are naturally
  idempotent (read up to a message, mute, a reaction toggled to a target
  state) are sent as the target state, not as a toggle.
- The app reaches servers over https only, unless the user allowed http in
  the sync options; the websocket follows the same rule (wss).
- Every new feature appears in `src/data/featureCatalog.ts`; strings go
  through the app's i18n (French and English).

## Left to the builder

- What a conversation created offline looks like until the server has it,
  and how its local id is swapped for the server's.
- What the module stores beyond the client id, and how the app detects it
  (installed vs available, e.g. `ir.module.module` state where readable).

- The data model on the phone (tables, migrations), how the store merges,
  the cache size limit and the purge schedule's default.
- The native websocket's reconnection and backoff, how it shares the
  session with the RPC client, and how it behaves when the app goes to the
  background (it may close; project 2 decides what holds it then).
- How « fetch in full » is offered, and how far scrolling back loads per
  page.
- The voice recording format, as long as Odoo 18 plays it as a voice
  message in the browser.
- How the server search completes the local one, and how the inbox item
  finds the linked note.
- Screen layout beyond the mockups seen in brainstorming (tile on home,
  mixed list with server tag and unread, thread with read ✓✓, « typing… »,
  📎 and a pending « waiting for network ⏳ », new conversation with people
  grouped by server).
- Splitting each lot into commits, and the long-test layout in
  `long_test/` (reusing the mobile sync harness where it fits).

## Details decided for later lots

- **Lot 2, channel access group:** the creation form starts on Odoo's
  default group, with a control to change it on the spot.
- **Lot 2, who to write to:** the people the user has already chatted
  with on that server, then a search for the others (`im_search`).
- **Lot 3, attachment cache:** no automatic purge by default. A setting
  turns it on, with a limit of 2 GB by default that the user can change.
  A warning appears when the cache reaches 80 % of the limit.
- **Lot 3, camera photos:** sent as the original by default. A setting
  changes this, and the app asks before sending whether to compress.
- **Lot 4, reactions:** a long press offers six emoji in one touch
  (👍 ❤️ 😂 😮 😢 🙏 at first, then the user's most used), plus « … » for
  the full picker.
- **Lot 4, edit and delete:** as Odoo, with no time limit; an edited
  message shows « (edited) » as in the browser.
- **Lot 5, server search:** message text, conversation names, people,
  and attachments by name.
- **Lot 5, inbox item:** opens the app's note when the record is linked to
  one, otherwise the record in the web view.
