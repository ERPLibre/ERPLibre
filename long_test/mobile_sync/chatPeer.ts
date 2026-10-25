/**
 * The other end of a chat scenario: chat_user in a browser (a web session
 * posting through /mail/message/post and /discuss/channel/notify_typing, as
 * Odoo's web client does), and what the server holds of the conversations
 * the app's user (admin) reads, through execute_kw. A mention is a post
 * whose partner_ids name admin.
 */
import type { Target } from "./harness";
import { OdooAdmin } from "./odooAdmin";

const CHANNEL = "discuss.channel";

export class ChatPeer {
	/** chat_user's partner and the app user's (admin) partner. */
	partnerId = 0;
	adminPartnerId = 0;

	private constructor(readonly user: OdooAdmin, readonly admin: OdooAdmin) {}

	static async open(target: Target): Promise<ChatPeer> {
		if (!target.chat) throw new Error(`no chat user on Odoo ${target.version}`);
		const peer = new ChatPeer(new OdooAdmin(target, target.chat), new OdooAdmin(target));
		await peer.user.sessionLogin();
		const partnerOf = async (login: string) =>
			(await peer.admin.searchRead("res.users", [["login", "=", login]], ["partner_id"]))[0].partner_id[0];
		peer.partnerId = await partnerOf(target.chat.login);
		peer.adminPartnerId = await partnerOf(target.admin.login);
		return peer;
	}

	private async idByName(name: string): Promise<number> {
		const [row] = await this.user.searchRead(CHANNEL, [["name", "=", name]], ["id"]);
		if (!row) throw new Error(`conversation ${name} not found`);
		return row.id;
	}

	/** A new group of chat_user and admin, named name; its id. */
	async group(name: string): Promise<number> {
		await this.user.execute(CHANNEL, "create_group", [], { partners_to: [this.adminPartnerId], name });
		return this.idByName(name);
	}

	/** A new channel (channel_type "channel") created by chat_user, admin invited; its id. */
	async channel(name: string): Promise<number> {
		await this.user.execute(CHANNEL, "channel_create", [name, null]);
		const id = await this.idByName(name);
		await this.user.execute(CHANNEL, "add_members", [[id]], { partner_ids: [this.adminPartnerId] });
		return id;
	}

	/** Posts text as chat_user, mentioning admin when asked; the new message's id. */
	async post(channelId: number, text: string, opts: { mentionAdmin?: boolean } = {}): Promise<number> {
		const result = await this.user.jsonRoute("/mail/message/post", {
			thread_model: CHANNEL,
			thread_id: channelId,
			post_data: {
				body: text,
				message_type: "comment",
				subtype_xmlid: "mail.mt_comment",
				...(opts.mentionAdmin ? { partner_ids: [this.adminPartnerId] } : {}),
			},
		});
		const id = result?.["mail.message"]?.[0]?.id;
		if (typeof id !== "number") throw new Error("post answered no message id");
		return id;
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
