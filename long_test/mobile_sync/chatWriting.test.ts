/**
 * What the app writes into a chat message, against a real Odoo 18: a
 * mention notifies the person mentioned, @everyone names every member, a
 * #channel is stored as Odoo's channel link, and the app's HTML survives a
 * browser edit: for every case of the composer goldens
 * (src/__tests__/fixtures/composer-cases.json of the mobile repo, their
 * people and channels made real on the server), the body the app posts,
 * read back as the browser's edit reads it (bodyText) and composed again
 * with the message's recipients (composeBody), then saved by chat_user's
 * browser, is stored as it was, the edited span aside. The stored form of a
 * body that starts with a mention is pinned.
 *
 * The app writes as chat_user where the browser edits after it (Odoo lets
 * an author edit only their own message), as admin elsewhere. A mention
 * notifies only a partner with an email address, in the inbox only for a
 * user notified there: chat_user gets both for the file and has them back
 * after. Nothing here changes a server-wide setting, so the file runs with
 * the others.
 */
import { readFileSync } from "node:fs";
import { appFor, bodyText, composeBody, eachVersionFrom, EMPTY_MENTIONS, emojiConversions, unique } from "./harness";
import type { Mentions, SyncEnv } from "./harness";
import { ChatPeer } from "./chatPeer";
import { FaultProxy } from "./faultProxy";

const CHANNEL = "discuss.channel";
/** chat_user's address for the file: invented, on a domain reserved for examples. */
const CHAT_EMAIL = "ms-chat@example.com";
const EDITED = '<span class="o-mail-Message-edited"></span>';
/** The marker comment the app appends to a post, which a browser edit drops (its textContent is empty). */
const MARKER = /<!-- erplibre-mobile:[^>]* -->/g;

interface ComposerCase {
	name: string;
	text: string;
	mentions?: Mentions;
}

const CASES: ComposerCase[] = JSON.parse(readFileSync(
	new URL("../../mobile/erplibre_home_mobile/src/__tests__/fixtures/composer-cases.json", import.meta.url), "utf8"));

eachVersionFrom(18, "chat writing", (target) => {
	let proxy: FaultProxy;
	let peer: ChatPeer;
	let env: SyncEnv | null = null;
	let chatUid: number;
	let before: { email: string | false; notification_type: string } | null = null;

	beforeAll(async () => {
		proxy = await FaultProxy.start(target);
		peer = await ChatPeer.open(target);
		chatUid = await peer.user.login();
		const { email, notification_type } = await peer.admin.read("res.users", chatUid, ["email", "notification_type"]);
		before = { email, notification_type };
		await peer.admin.write("res.users", [chatUid], { email: CHAT_EMAIL, notification_type: "inbox" });
	});
	afterAll(async () => {
		if (before) await peer.admin.write("res.users", [chatUid], before);
		await proxy.stop();
	});
	afterEach(() => {
		env?.chat.stopRealtime();
		env = null;
	});

	/** The app as `as` through the proxy, its chat source loaded. */
	async function app(as: "admin" | "chat" = "admin") {
		const started = await appFor(proxy.via(target), as);
		env = started;
		const [src] = await started.chat.sources();
		await started.chat.load(src);
		return { env: started, src };
	}

	/** Text posted from the app with its picks and settled: the server's message (body, partner_ids). */
	async function posted(e: SyncEnv, src: any, channelId: number, text: string, mentions: Mentions = EMPTY_MENTIONS) {
		const message = await e.chat.send(src, channelId, text, [], { mentions });
		await e.chat.queue.whenIdle(src.configId);
		const settled = (await e.chat.messages(src.configId, channelId)).find((m) => m.clientUuid === message.clientUuid)!;
		expect(settled.status).toBe("sent");
		return peer.admin.read("mail.message", settled.messageId!, ["body", "partner_ids"]);
	}

	const parse = (body: string) => new DOMParser().parseFromString(body, "text/html");

	it("a mention of chat_user in a channel: chat_user's notification to read", async () => {
		const channel = await peer.channel(unique("channel"));
		const { env, src } = await app();
		const message = await posted(env, src, channel, "@MS Chat bonjour", {
			partners: [{ id: peer.partnerId, name: "MS Chat" }], channels: [],
		});
		expect(message.partner_ids).toEqual([peer.partnerId]);
		const link = parse(message.body).querySelector("a.o_mail_redirect")!;
		expect(link.getAttribute("data-oe-id")).toBe(String(peer.partnerId));
		expect(link.textContent).toBe("@MS Chat");
		expect(await peer.needaction(message.id)).toEqual(expect.objectContaining({ notification_type: "inbox", is_read: false }));
		expect((await peer.user.read(CHANNEL, channel, ["message_needaction_counter"])).message_needaction_counter).toBe(1);
	});

	it("@everyone in a group: every member in partner_ids", async () => {
		const group = await peer.group(unique("group"));
		const { env, src } = await app();
		const message = await posted(env, src, group, `@everyone ${unique("meeting")}`);
		const members = await peer.members(group);
		expect(members).toHaveLength(2);
		expect([...message.partner_ids].sort()).toEqual([...members].sort());
		expect(parse(message.body).querySelector("a.o-discuss-mention")!.textContent).toBe("@everyone");
		expect(await peer.needaction(message.id)).toEqual(expect.objectContaining({ notification_type: "inbox" }));
	});

	it("#channel stored as Odoo's channel link", async () => {
		const name = unique("linked");
		const channel = await peer.channel(name);
		const group = await peer.group(unique("group"));
		const { env, src } = await app();
		const message = await posted(env, src, group, `voir #${name}`, {
			partners: [], channels: [{ id: channel, name, parentName: null }],
		});
		const link = parse(message.body).querySelector("a.o_channel_redirect")!;
		expect(link).toBeTruthy();
		expect(link.getAttribute("class")).toBe("o_channel_redirect");
		expect(link.getAttribute("data-oe-model")).toBe(CHANNEL);
		expect(link.getAttribute("data-oe-id")).toBe(String(channel));
		expect(link.textContent).toBe(`#${name}`);
		expect(message.partner_ids).toEqual([]);
	});

	// lxml wraps a fragment that opens on an element in a <span>, leading text in a <p>; contenteditable is dropped
	it("a body that starts with a mention is stored in a span, as Odoo's sanitizer leaves it", async () => {
		const group = await peer.group(unique("group"));
		const { env, src } = await app();
		const message = await posted(env, src, group, "@MS Chat bonjour", {
			partners: [{ id: peer.partnerId, name: "MS Chat" }], channels: [],
		});
		const id = peer.partnerId;
		expect(message.body.replace(MARKER, "")).toBe(
			`<span><a href="/odoo/res.partner/${id}" class="o_mail_redirect" data-oe-id="${id}" data-oe-model="res.partner"`
			+ ` target="_blank">@MS Chat</a> bonjour</span>`,
		);
	});

	describe("round trip through a browser edit", () => {
		/** Per id of the goldens, the server's partner and channel standing for it. */
		const partners = new Map<number, number>();
		const channels = new Map<number, number>();

		beforeAll(async () => {
			const names = new Map<number, string>();
			const subs: { id: number; name: string; parentName: string }[] = [];
			const tops = new Map<number, string>();
			for (const c of CASES) {
				for (const p of c.mentions?.partners ?? []) names.set(p.id, p.name);
				for (const ch of c.mentions?.channels ?? []) {
					if (ch.parentName) subs.push({ id: ch.id, name: ch.name, parentName: ch.parentName });
					else tops.set(ch.id, ch.name);
				}
			}
			for (const [id, name] of names) partners.set(id, await peer.admin.create("res.partner", { name }));
			const byName = new Map<string, number>();
			for (const [id, name] of tops) {
				const real = await peer.admin.create(CHANNEL, { name, channel_type: "channel" });
				channels.set(id, real);
				byName.set(name, real);
			}
			for (const s of subs) {
				const parent = byName.get(s.parentName) ?? await peer.admin.create(CHANNEL, { name: s.parentName, channel_type: "channel" });
				channels.set(s.id, await peer.admin.create(CHANNEL, { name: s.name, channel_type: "channel", parent_channel_id: parent }));
			}
		});

		/** A case's picks with the server's ids in place of the goldens'. */
		const real = (m: Mentions | undefined): Mentions => ({
			partners: (m?.partners ?? []).map((p) => ({ ...p, id: partners.get(p.id)! })),
			channels: (m?.channels ?? []).map((c) => ({ ...c, id: channels.get(c.id)! })),
		});

		for (const c of CASES) {
			it(`${c.name}: stored the same after chat_user's browser saves it`, async () => {
				const group = await peer.group(unique("group"));
				const { env, src } = await app("chat");
				const mentions = real(c.mentions);
				const first = await posted(env, src, group, c.text, mentions);
				// What the app sent is the browser's own HTML for the text
				const [post] = proxy.calls.filter((call) => call.path === "/mail/message/post"
					&& call.params?.thread_id === group);
				const expected = composeBody(c.text, mentions, await emojiConversions());
				expect(post.params!.post_data.body.replace(MARKER, "")).toBe(expected.body);

				// The browser's edit: the stored body read back, the recipients as the people picked
				const names = new Map((await peer.admin.searchRead("res.partner", [["id", "in", first.partner_ids]], ["name"]))
					.map((p) => [p.id, p.name]));
				const text = bodyText(first.body);
				await peer.edit(first.id, text, {
					partners: first.partner_ids.map((id: number) => ({ id, name: names.get(id)! })),
					channels: mentions.channels,
				});
				const after = await peer.admin.read("mail.message", first.id, ["body", "partner_ids"]);
				expect(after.body).toContain(EDITED);
				expect(after.body.replace(EDITED, "")).toBe(first.body.replace(MARKER, ""));
				expect([...after.partner_ids].sort()).toEqual([...first.partner_ids].sort());
			});
		}
	});
});
