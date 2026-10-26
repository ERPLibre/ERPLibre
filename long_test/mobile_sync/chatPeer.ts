/**
 * The other end of a chat scenario: chat_user in a browser (a web session
 * posting through /mail/message/post and /discuss/channel/notify_typing, as
 * Odoo's web client does), and what the server holds of the conversations
 * the app's user (admin) reads, through execute_kw. A mention is a post
 * whose partner_ids name admin. Files go as the web client sends them:
 * uploaded pending through /mail/attachment/upload, then named by the post.
 */
import type { Target } from "./harness";
import { OdooAdmin } from "./odooAdmin";

const CHANNEL = "discuss.channel";

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

	private constructor(readonly user: OdooAdmin, readonly admin: OdooAdmin) {}

	static async open(target: Target): Promise<ChatPeer> {
		if (!target.chat) throw new Error(`no chat user on Odoo ${target.version}`);
		const peer = new ChatPeer(new OdooAdmin(target, target.chat), new OdooAdmin(target));
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
		const info = await this.user.jsonRoute("/web/session/get_session_info");
		const base = new URL(this.user.url);
		const url = `${base.origin.replace(/^http/, "ws")}/websocket?version=${encodeURIComponent(info.websocket_worker_version)}`;
		const notifications: any[] = [];
		const ws: WebSocket = new (WebSocket as any)(url, { headers: { Cookie: this.user.cookie, Origin: base.origin } });
		await new Promise<void>((resolve, reject) => {
			ws.onopen = () => resolve();
			ws.onerror = () => reject(new Error("chat_user's websocket did not open"));
		});
		ws.onmessage = (event: MessageEvent) => {
			if (typeof event.data === "string") notifications.push(...JSON.parse(event.data));
		};
		ws.send(JSON.stringify({ event_name: "subscribe", data: { channels: [], last: 0 } }));
		return { notifications, close: () => ws.close() };
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

	/** Admin's mentions still to read in the conversation (message_needaction_counter). */
	async adminMentions(channelId: number): Promise<number> {
		return (await this.admin.read(CHANNEL, channelId, ["message_needaction_counter"])).message_needaction_counter;
	}
}
