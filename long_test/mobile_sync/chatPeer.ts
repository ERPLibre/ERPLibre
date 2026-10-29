/**
 * The other end of a chat scenario: chat_user in a browser (a web session
 * posting through /mail/message/post and /discuss/channel/notify_typing, as
 * Odoo's web client does), and what the server holds of the conversations
 * the app's user (admin) reads, through execute_kw. A mention is a post
 * whose partner_ids name admin. Files go as the web client sends them:
 * uploaded pending through /mail/attachment/upload, then named by the post.
 * Reactions, edits and deletes go through the web client's routes too
 * (/mail/message/reaction, /mail/message/update_content), an edit's body
 * built from its text as the browser composer builds it (the kit's
 * composeBody). Records are read and set up as admin: their chatter, their
 * followers, assignments, stars, notifications and outgoing emails.
 */
import { composeBody, emojiConversions, EMPTY_MENTIONS } from "./harness";
import type { Login, Mentions, Target } from "./harness";
import { OdooAdmin } from "./odooAdmin";

const CHANNEL = "discuss.channel";

/** A system parameter of the tests' own, written then removed to clear Odoo's get_param cache. */
const CACHE_FLUSH = "erplibre_mobile_sync.cache_bump";

/** The CSRF token of a page Odoo renders (the login form's input, or the layout's `csrf_token: "…"`). */
const CSRF = /name=["']csrf_token["'][^>]*value=["']([^"']+)["']|csrf_token\s*:\s*["']([^"']+)["']/;

/** An attachment as the server holds it, as attachmentsOf reads it. */
export interface ServerAttachment {
	id: number;
	name: string;
	mimetype: string;
	checksum: string;
	file_size: number;
	res_model: string;
	res_id: number;
	create_uid: [number, string];
	voice_ids: number[];
	erplibre_client_uuid: string | false;
}

const ATTACHMENT_FIELDS = [
	"name", "mimetype", "checksum", "file_size", "res_model", "res_id", "create_uid", "voice_ids", "erplibre_client_uuid",
];

export class ChatPeer {
	/** chat_user's partner and the app user's (admin) partner. */
	partnerId = 0;
	adminPartnerId = 0;

	private constructor(readonly user: OdooAdmin, readonly admin: OdooAdmin, private target: Target) {}

	static async open(target: Target): Promise<ChatPeer> {
		if (!target.chat) throw new Error(`no chat user on Odoo ${target.version}`);
		const peer = new ChatPeer(new OdooAdmin(target, target.chat), new OdooAdmin(target), target);
		await peer.user.sessionLogin();
		peer.partnerId = await peer.partnerOf(target.chat.login);
		peer.adminPartnerId = await peer.partnerOf(target.admin.login);
		return peer;
	}

	/** The partner of the user whose login is given. */
	async partnerOf(login: string): Promise<number> {
		return (await this.admin.searchRead("res.users", [["login", "=", login]], ["partner_id"]))[0].partner_id[0];
	}

	private async idByName(name: string): Promise<number> {
		const [row] = await this.user.searchRead(CHANNEL, [["name", "=", name]], ["id"]);
		if (!row) throw new Error(`conversation ${name} not found`);
		return row.id;
	}

	/** A new group of chat_user and `withPartner` (admin by default), named name; its id. */
	async group(name: string, withPartner = this.adminPartnerId): Promise<number> {
		await this.user.execute(CHANNEL, "create_group", [], { partners_to: [withPartner], name });
		return this.idByName(name);
	}

	/**
	 * A new channel (channel_type "channel") created by chat_user, open to
	 * internal users; admin invited unless invite is false; its id.
	 */
	async channel(name: string, opts: { invite?: boolean } = {}): Promise<number> {
		await this.user.execute(CHANNEL, "channel_create", [name, null]);
		const id = await this.idByName(name);
		if (opts.invite ?? true) await this.user.execute(CHANNEL, "add_members", [[id]], { partner_ids: [this.adminPartnerId] });
		return id;
	}

	/** chat_user's direct chat with `withPartner` (channel_get, as the browser opens it); its id. */
	async chat(withPartner: number): Promise<number> {
		await this.user.execute(CHANNEL, "channel_get", [], { partners_to: [withPartner] });
		const [row] = await this.user.searchRead(
			CHANNEL, [["channel_type", "=", "chat"], ["channel_partner_ids", "in", [withPartner]]], ["id"],
		);
		if (!row) throw new Error(`no chat of chat_user with partner ${withPartner}`);
		return row.id;
	}

	/** The partners of the conversation's members on the server, in member-id order. */
	async members(channelId: number): Promise<number[]> {
		const rows = await this.admin.searchRead(
			"discuss.channel.member", [["channel_id", "=", channelId]], ["partner_id"], { order: "id asc" },
		);
		return rows.map((r) => r.partner_id[0]);
	}

	/** The member row of partnerId in the conversation (fields as asked), or null when not a member. */
	async memberOf(channelId: number, partnerId: number, fields: string[]): Promise<any | null> {
		const [row] = await this.admin.searchRead(
			"discuss.channel.member", [["channel_id", "=", channelId], ["partner_id", "=", partnerId]], fields,
		);
		return row ?? null;
	}

	/**
	 * chat_user's bus, as their browser opens it: a websocket straight to
	 * Odoo in their web session, subscribed from last 0 (the server adds
	 * their partner and member channels). notifications collects every
	 * notification received; close() ends it.
	 */
	async listen(): Promise<{ notifications: any[]; close(): void }> {
		const { ws, notifications } = await this.openBus(this.user);
		return { notifications, close: () => ws.close() };
	}

	/**
	 * A bus websocket straight to Odoo in the web session of session (its
	 * sessionLogin done), as a browser opens it (the server's Origin),
	 * subscribed from last 0; notifications collects what it receives.
	 */
	private async openBus(session: OdooAdmin): Promise<{ ws: WebSocket; notifications: any[] }> {
		const info = await session.jsonRoute("/web/session/get_session_info");
		const base = new URL(session.url);
		const url = `${base.origin.replace(/^http/, "ws")}/websocket?version=${encodeURIComponent(info.websocket_worker_version)}`;
		const notifications: any[] = [];
		const ws: WebSocket = new (WebSocket as any)(url, { headers: { Cookie: session.cookie, Origin: base.origin } });
		await new Promise<void>((resolve, reject) => {
			ws.onopen = () => resolve();
			ws.onerror = () => reject(new Error("the browser's websocket did not open"));
		});
		ws.onmessage = (event: MessageEvent) => {
			if (typeof event.data === "string") notifications.push(...JSON.parse(event.data));
		};
		ws.send(JSON.stringify({ event_name: "subscribe", data: { channels: [], last: 0 } }));
		return { ws, notifications };
	}

	/**
	 * A browser of the user of login: a web session of its own
	 * (/web/session/authenticate) and its bus websocket, as listen() opens
	 * chat_user's. markRead reads the conversation up to lastId as the web
	 * client does (/discuss/channel/mark_as_read); presence sends the bus's
	 * update_presence with that inactivity (ms) and resolves once Odoo
	 * wrote it (the browser poll of the user's bus.presence moved);
	 * setMessageDone marks an inbox message done (set_message_done); post
	 * posts text in the conversation as the user (/mail/message/post), the
	 * new message's id; close() ends the websocket.
	 */
	async browserSession(login: Login): Promise<{
		markRead(channelId: number, lastId: number): Promise<void>;
		post(channelId: number, text: string): Promise<number>;
		presence(inactivityMs: number): Promise<void>;
		setMessageDone(messageId: number): Promise<void>;
		close(): void;
	}> {
		const browser = new OdooAdmin(this.target, login);
		await browser.sessionLogin();
		const { ws } = await this.openBus(browser);
		return {
			markRead: async (channelId, lastId) => {
				await browser.jsonRoute("/discuss/channel/mark_as_read", { channel_id: channelId, last_message_id: lastId });
			},
			presence: async (inactivityMs) => {
				const before = (await this.browserPresenceOf(login.login)).poll;
				// The poll is written to the second: a send in the second of the last one moves nothing
				await new Promise((resolve) => setTimeout(resolve, 1100));
				ws.send(JSON.stringify({
					event_name: "update_presence",
					data: { inactivity_period: inactivityMs, im_status_ids_by_model: {} },
				}));
				const deadline = performance.now() + 10000;
				while ((await this.browserPresenceOf(login.login)).poll === before) {
					if (performance.now() > deadline) throw new Error(`no browser presence written for ${login.login}`);
					await new Promise((resolve) => setTimeout(resolve, 100));
				}
			},
			post: async (channelId, text) => {
				const result = await browser.jsonRoute("/mail/message/post", {
					thread_model: CHANNEL,
					thread_id: channelId,
					post_data: { body: text, message_type: "comment", subtype_xmlid: "mail.mt_comment" },
				});
				const id = result?.["mail.message"]?.[0]?.id;
				if (typeof id !== "number") throw new Error("post answered no message id");
				return id;
			},
			setMessageDone: async (messageId) => {
				await browser.jsonRoute("/web/dataset/call_kw/mail.message/set_message_done", {
					model: "mail.message", method: "set_message_done", args: [[messageId]], kwargs: {},
				});
			},
			close: () => ws.close(),
		};
	}

	/**
	 * The presence of the user of login (bus.presence, admin's read): the
	 * browser poll and activity the module keeps, and Odoo's own last poll
	 * (every bus, the app's included); false when unset.
	 */
	async browserPresenceOf(login: string): Promise<{ poll: string | false; presence: string | false; lastPoll: string | false }> {
		const [user] = await this.admin.searchRead("res.users", [["login", "=", login]], ["id"]);
		const [row] = await this.admin.searchRead(
			"bus.presence", [["user_id", "=", user.id]], ["erplibre_browser_poll", "erplibre_browser_presence", "last_poll"],
		);
		return {
			poll: row?.erplibre_browser_poll ?? false,
			presence: row?.erplibre_browser_presence ?? false,
			lastPoll: row?.last_poll ?? false,
		};
	}

	/**
	 * The device of endpoint marked quiet while a browser is online (quiet
	 * true) or not, through the module's route in the web session of
	 * session (the app's own: the mark keeps the hash of the session that
	 * calls it, which tells the app's bus from a browser). Throws unless
	 * Odoo answers ok.
	 */
	async markDeviceQuiet(session: { sessionId: string }, endpoint: string, quiet: boolean): Promise<void> {
		const response = await fetch(`${this.target.url}/erplibre_mobile_chat/push/device`, {
			method: "POST",
			headers: { "Content-Type": "application/json", Cookie: `session_id=${session.sessionId}` },
			body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: { endpoint, quiet_while_online: quiet } }),
		});
		const body: any = await response.json();
		if (body.error || body.result?.ok !== true) throw new Error(`device not marked: ${JSON.stringify(body.error ?? body.result)}`);
	}

	/** The device of endpoint as the module holds it: its id and marks; null when Odoo holds none. */
	async appDevice(endpoint: string): Promise<{ id: number; app: boolean; quiet: boolean } | null> {
		const [row] = await this.admin.searchRead(
			"mail.push.device", [["endpoint", "=", endpoint]], ["erplibre_app", "erplibre_quiet_while_online"],
		);
		return row ? { id: row.id, app: row.erplibre_app, quiet: row.erplibre_quiet_while_online } : null;
	}

	/**
	 * A new internal user named name, its login and password both login
	 * (unique to the run, the caller's), with project's user rights and
	 * notified in Odoo's inbox when inbox is true (Odoo creates its
	 * settings with it). Its Login and partner.
	 */
	async createUser(name: string, login: string, opts: { inbox?: boolean } = {}): Promise<{ login: Login; partnerId: number }> {
		const xmlids = ["base.group_user", ...(opts.inbox ? ["project.group_project_user", "mail.group_mail_notification_type_inbox"] : [])];
		const groups: number[] = [];
		for (const xmlid of xmlids) {
			const [module, name] = xmlid.split(".");
			const [row] = await this.admin.searchRead("ir.model.data", [["module", "=", module], ["name", "=", name]], ["res_id"]);
			groups.push(row.res_id);
		}
		const userId = await this.admin.create("res.users", {
			name, login, password: login, groups_id: [[6, 0, groups]], ...(opts.inbox ? { notification_type: "inbox" } : {}),
		});
		if (!userId) throw new Error(`user ${login} not created`);
		return { login: { login, password: login }, partnerId: await this.partnerOf(login) };
	}

	/** The mute end of the member of the user of login in the conversation (mute_until_dt, UTC), false when not muted. */
	async muteOf(login: string, channelId: number): Promise<string | false> {
		const row = await this.memberOf(channelId, await this.partnerOf(login), ["mute_until_dt"]);
		if (!row) throw new Error(`${login} is not a member of ${channelId}`);
		return row.mute_until_dt;
	}

	/**
	 * Uploads bytes as chat_user's pending attachment of the conversation,
	 * as the web client's composer does (multipart, its session and the
	 * CSRF token of its login page; voice=true for a voice message): the
	 * attachment's id and access token, for post().
	 */
	async upload(
		channelId: number, filename: string, bytes: Uint8Array, opts: { voice?: boolean; mimetype?: string } = {},
	): Promise<{ id: number; token: string | false }> {
		const page = await this.user.httpGet("/web/login", this.user.cookie);
		const found = CSRF.exec(page.bytes.toString("utf8"));
		if (!found) throw new Error(`no csrf token on /web/login (HTTP ${page.status})`);
		const form = new FormData();
		form.append("thread_id", String(channelId));
		form.append("thread_model", CHANNEL);
		form.append("is_pending", "true");
		form.append("csrf_token", found[1] ?? found[2]);
		if (opts.voice) form.append("voice", "true");
		form.append("ufile", new Blob([bytes], { type: opts.mimetype ?? "application/octet-stream" }), filename);
		const response = await fetch(`${this.user.url}/mail/attachment/upload`, {
			method: "POST", headers: { Cookie: this.user.cookie }, body: form,
		});
		const text = await response.text();
		const record = response.ok ? JSON.parse(text)?.data?.["ir.attachment"]?.[0] : null;
		if (typeof record?.id !== "number") throw new Error(`upload refused (HTTP ${response.status}): ${text.slice(0, 200)}`);
		return { id: record.id, token: record.access_token ?? false };
	}

	/**
	 * Posts text as chat_user, mentioning admin when asked, with the
	 * attachments upload() gave; the new message's id.
	 */
	async post(
		channelId: number, text: string, opts: { mentionAdmin?: boolean; attachments?: { id: number; token: string | false }[] } = {},
	): Promise<number> {
		const files = opts.attachments ?? [];
		const result = await this.user.jsonRoute("/mail/message/post", {
			thread_model: CHANNEL,
			thread_id: channelId,
			post_data: {
				body: text,
				message_type: "comment",
				subtype_xmlid: "mail.mt_comment",
				...(opts.mentionAdmin ? { partner_ids: [this.adminPartnerId] } : {}),
				...(files.length ? { attachment_ids: files.map((f) => f.id) } : {}),
			},
			...(files.length ? { attachment_tokens: files.map((f) => f.token) } : {}),
		});
		const id = result?.["mail.message"]?.[0]?.id;
		if (typeof id !== "number") throw new Error("post answered no message id");
		return id;
	}

	/** Posts text as chat_user in the conversation, naming partnerId in partner_ids: a mention of them; the message's id. */
	async mention(channelId: number, partnerId: number, text: string): Promise<number> {
		const result = await this.user.jsonRoute("/mail/message/post", {
			thread_model: CHANNEL,
			thread_id: channelId,
			post_data: { body: text, message_type: "comment", subtype_xmlid: "mail.mt_comment", partner_ids: [partnerId] },
		});
		const id = result?.["mail.message"]?.[0]?.id;
		if (typeof id !== "number") throw new Error("mention answered no message id");
		return id;
	}

	/**
	 * Posts text as chat_user in a record's chatter, as the browser's
	 * chatter does: a message to the followers (mail.mt_comment) or an
	 * internal note (mail.mt_note); the message's id.
	 */
	async postOnRecord(model: string, resId: number, text: string, subtype: "mail.mt_comment" | "mail.mt_note"): Promise<number> {
		const result = await this.user.jsonRoute("/mail/message/post", {
			thread_model: model,
			thread_id: resId,
			post_data: { body: text, message_type: "comment", subtype_xmlid: subtype },
		});
		const id = result?.["mail.message"]?.[0]?.id;
		if (typeof id !== "number") throw new Error("record post answered no message id");
		return id;
	}

	/** partnerId (chat_user by default) made a follower of the record, by admin (message_subscribe). */
	async follow(model: string, resId: number, partnerId = this.partnerId): Promise<void> {
		await this.admin.execute(model, "message_subscribe", [[resId]], { partner_ids: [partnerId] });
	}

	/** chat_user pins the message in the conversation, or unpins it (set_message_pin, as the browser). */
	async pin(channelId: number, messageId: number, pinned: boolean): Promise<void> {
		await this.user.execute(CHANNEL, "set_message_pin", [[channelId]], { message_id: messageId, pinned });
	}

	/** Whether the user of `login` holds the message starred (its partner in starred_partner_ids). */
	async starredBy(login: string, messageId: number): Promise<boolean> {
		const message = await this.admin.read("mail.message", messageId, ["starred_partner_ids"]);
		if (!message) throw new Error(`message ${messageId} not found`);
		return message.starred_partner_ids.includes(await this.partnerOf(login));
	}

	/** The notification of the message for the user of `login` (mail.notification), null when there is none. */
	async needactionOf(login: string, messageId: number): Promise<{ notification_type: string; is_read: boolean } | null> {
		const [row] = await this.admin.searchRead(
			"mail.notification",
			[["mail_message_id", "=", messageId], ["res_partner_id", "=", await this.partnerOf(login)]],
			["notification_type", "is_read"],
		);
		return row ?? null;
	}

	/** The outgoing emails (mail.mail, sent or not) whose recipients hold partnerId. */
	mailCountFor(partnerId: number): Promise<number> {
		return this.admin.execute("mail.mail", "search_count", [[["recipient_ids", "in", [partnerId]]]]);
	}

	/** The notification_type of the user of `login` on the server: "email" or "inbox". */
	async notificationTypeOf(login: string): Promise<string> {
		const [row] = await this.admin.searchRead("res.users", [["login", "=", login]], ["notification_type"]);
		if (!row) throw new Error(`user ${login} not found`);
		return row.notification_type;
	}

	/** The task assigned to the user of `login` too, by admin: Odoo notifies them of the assignment. */
	async assignTask(taskId: number, login: string): Promise<void> {
		const [user] = await this.admin.searchRead("res.users", [["login", "=", login]], ["id"]);
		if (!user) throw new Error(`user ${login} not found`);
		await this.admin.write("project.task", [taskId], { user_ids: [[4, user.id]] });
	}

	/**
	 * The messages of a record on the server (admin's view), oldest first:
	 * body, message type, subtype as its xml id (mail.mt_note,
	 * mail.mt_comment; "" for another) and attachment ids.
	 */
	async messagesOf(model: string, resId: number): Promise<{
		id: number; body: string; messageType: string; subtype: string; attachmentIds: number[];
	}[]> {
		const subtypes = await this.admin.searchRead(
			"ir.model.data", [["module", "=", "mail"], ["model", "=", "mail.message.subtype"], ["name", "in", ["mt_note", "mt_comment"]]],
			["name", "res_id"],
		);
		const xmlid = new Map(subtypes.map((d) => [d.res_id as number, `mail.${d.name}`]));
		const rows = await this.admin.searchRead(
			"mail.message", [["model", "=", model], ["res_id", "=", resId]],
			["body", "message_type", "subtype_id", "attachment_ids"], { order: "id asc" },
		);
		return rows.map((r) => ({
			id: r.id,
			body: r.body || "",
			messageType: r.message_type,
			subtype: r.subtype_id ? xmlid.get(r.subtype_id[0]) ?? "" : "",
			attachmentIds: r.attachment_ids,
		}));
	}

	/**
	 * The attachments of a message on the server, oldest first (a
	 * many2many reads in ir.attachment's own order, so the order a post
	 * named them in is not kept).
	 */
	async attachmentsOf(messageId: number): Promise<ServerAttachment[]> {
		const message = await this.admin.read("mail.message", messageId, ["attachment_ids"]);
		if (!message) throw new Error(`message ${messageId} not found`);
		return this.admin.searchRead("ir.attachment", [["id", "in", message.attachment_ids]], ATTACHMENT_FIELDS, { order: "id asc" });
	}

	/** chat_user's own reaction content on the message, added or removed (never a toggle, as the browser sends it). */
	react(messageId: number, content: string, action: "add" | "remove"): Promise<any> {
		return this.user.jsonRoute("/mail/message/reaction", { message_id: messageId, content, action });
	}

	/**
	 * chat_user's own message edited to text in the browser: the composer's
	 * HTML for text and the people picked (mentions; the browser starts from
	 * the message's recipients), its partner_ids, and the message's current
	 * attachments sent back as the browser sends them, so none is removed.
	 */
	async edit(messageId: number, text: string, mentions: Mentions = EMPTY_MENTIONS): Promise<any> {
		const composed = composeBody(text, mentions, await emojiConversions());
		const { attachment_ids } = await this.admin.read("mail.message", messageId, ["attachment_ids"]);
		return this.user.jsonRoute("/mail/message/update_content", {
			message_id: messageId,
			body: composed.body,
			attachment_ids,
			partner_ids: composed.partnerIds,
		});
	}

	/** chat_user's own message deleted in the browser: the body, the files and the subject emptied. */
	deleteMessage(messageId: number): Promise<any> {
		return this.user.jsonRoute("/mail/message/update_content", {
			message_id: messageId, body: "", attachment_ids: [], attachment_tokens: [], subject: "",
		});
	}

	/** The message's reaction rows on the server (admin's view), oldest first: content and partner. */
	async reactionsOf(messageId: number): Promise<{ content: string; partnerId: number | false }[]> {
		const rows = await this.admin.searchRead(
			"mail.message.reaction", [["message_id", "=", messageId]], ["content", "partner_id"], { order: "id asc" },
		);
		return rows.map((r) => ({ content: r.content, partnerId: r.partner_id ? r.partner_id[0] : false }));
	}

	/** The message's body as the server stores it ("" for an emptied one). */
	async bodyOf(messageId: number): Promise<string> {
		const message = await this.admin.read("mail.message", messageId, ["body"]);
		if (!message) throw new Error(`message ${messageId} not found`);
		return message.body || "";
	}

	/** The id of the message this one replies to on the server, false for none. */
	async parentOf(messageId: number): Promise<number | false> {
		const message = await this.admin.read("mail.message", messageId, ["parent_id"]);
		if (!message) throw new Error(`message ${messageId} not found`);
		return message.parent_id ? message.parent_id[0] : false;
	}

	/** chat_user's notification of the message (mail.notification), null when the message notifies them of nothing. */
	async needaction(messageId: number): Promise<{ notification_type: string; is_read: boolean } | null> {
		const [row] = await this.admin.searchRead(
			"mail.notification",
			[["mail_message_id", "=", messageId], ["res_partner_id", "=", this.partnerId]],
			["notification_type", "is_read"],
		);
		return row ?? null;
	}

	typing(channelId: number, isTyping: boolean): Promise<void> {
		return this.user.jsonRoute("/discuss/channel/notify_typing", { channel_id: channelId, is_typing: isTyping });
	}

	/** The comments of the conversation as chat_user reads them on the server, oldest first. */
	comments(channelId: number, fields: string[] = ["id", "body", "author_id"]): Promise<any[]> {
		return this.user.searchRead(
			"mail.message",
			[["model", "=", CHANNEL], ["res_id", "=", channelId], ["message_type", "=", "comment"]],
			fields,
			{ order: "id asc" },
		);
	}

	/** Admin's member row: message_unread_counter, seen_message_id, as the server computes them. */
	async adminMember(channelId: number): Promise<{ message_unread_counter: number; seen_message_id: number | false }> {
		const [row] = await this.admin.searchRead(
			"discuss.channel.member",
			[["channel_id", "=", channelId], ["partner_id", "=", this.adminPartnerId]],
			["message_unread_counter", "seen_message_id"],
		);
		return { ...row, seen_message_id: row.seen_message_id ? row.seen_message_id[0] : false };
	}

	/**
	 * Posts text as inbox_user in a record's chatter (a message to the
	 * followers), as their browser does; the message's id. chat_user
	 * cannot post on records it does not reach: inbox_user has project's
	 * user rights.
	 */
	async postOnRecordAsInbox(model: string, resId: number, text: string): Promise<number> {
		if (!this.target.inbox) throw new Error(`no inbox user on Odoo ${this.target.version}`);
		const inbox = new OdooAdmin(this.target, this.target.inbox);
		await inbox.sessionLogin();
		const result = await inbox.jsonRoute("/mail/message/post", {
			thread_model: model,
			thread_id: resId,
			post_data: { body: text, message_type: "comment", subtype_xmlid: "mail.mt_comment" },
		});
		const id = result?.["mail.message"]?.[0]?.id;
		if (typeof id !== "number") throw new Error("record post answered no message id");
		return id;
	}

	/** The Web Push devices Odoo holds for this endpoint (admin's search_count on mail.push.device). */
	pushDevices(endpoint: string): Promise<number> {
		return this.admin.execute("mail.push.device", "search_count", [[["endpoint", "=", endpoint]]]);
	}

	/** The Web Push devices of these endpoints, unlinked by admin; how many there were. */
	async dropPushDevicesOf(endpoints: string[]): Promise<number> {
		if (endpoints.length === 0) return 0;
		const rows = await this.admin.searchRead("mail.push.device", [["endpoint", "in", endpoints]], ["id"]);
		if (rows.length) await this.admin.unlink("mail.push.device", rows.map((r) => r.id));
		return rows.length;
	}

	/**
	 * Odoo's VAPID key pair removed (admin unlinks the two
	 * mail.web_push_vapid_* parameters), as on a restored or neutralised
	 * database: Odoo pushes nothing until get_web_push_vapid_public_key
	 * draws new keys, which also drops every device. get_param is cached
	 * per server: a request that reads the keys while the unlink runs (any
	 * push to a recipient with a device does) caches them again from its
	 * older snapshot, so the wipe is repeated, the cache cleared by writing
	 * a parameter of its own, until get_param answers false for both.
	 */
	async wipeVapid(): Promise<void> {
		const keys = ["mail.web_push_vapid_private_key", "mail.web_push_vapid_public_key"];
		for (let attempt = 0; ; attempt++) {
			const rows = await this.admin.searchRead("ir.config_parameter", [["key", "in", keys]], ["id"]);
			if (rows.length) await this.admin.unlink("ir.config_parameter", rows.map((r) => r.id));
			const left = await Promise.all(keys.map((k) => this.admin.getParam(k)));
			if (left.every((v) => v === false)) return;
			if (attempt >= 10) throw new Error("the VAPID keys stay readable after their removal");
			await this.admin.setParam(CACHE_FLUSH, "1");
			await this.admin.setParam(CACHE_FLUSH, false);
		}
	}

	/** The last message the user of `login` has seen in the conversation (seen_message_id of their member), 0 for none. */
	async seenOf(login: string, channelId: number): Promise<number> {
		const row = await this.memberOf(channelId, await this.partnerOf(login), ["seen_message_id"]);
		if (!row) throw new Error(`${login} is not a member of ${channelId}`);
		return row.seen_message_id ? row.seen_message_id[0] : 0;
	}

	/** The unread inbox notifications of the user of `login` (mail.notification of their partner, not read). */
	async needactionCount(login: string): Promise<number> {
		return this.admin.execute("mail.notification", "search_count", [
			[["res_partner_id", "=", await this.partnerOf(login)], ["is_read", "=", false]],
		]);
	}

	/** Admin's mentions still to read in the conversation (message_needaction_counter). */
	async adminMentions(channelId: number): Promise<number> {
		return (await this.admin.read(CHANNEL, channelId, ["message_needaction_counter"])).message_needaction_counter;
	}
}
