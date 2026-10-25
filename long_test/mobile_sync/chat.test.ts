/**
 * The chat against a real Odoo 18, the app as admin, chat_user at the other
 * end: the server is a chat source, load takes its counters, a post reaches
 * the conversation once whether its answer is lost or not (server module or
 * marker path), posts queued offline keep their order, history pages leave
 * mentions alone, and reading marks the conversation seen on the server.
 *
 * Mentions count only for a user notified in Odoo's inbox: admin is switched
 * to it for the file and switched back after. The quiet window (3 minutes)
 * and the retry delay pass on a faked Date: only the app's clock moves, the
 * requests stay real.
 */
import { appFor, eachVersionFrom, TARGETS, unique } from "./harness";
import type { SyncEnv } from "./harness";
import { ChatPeer } from "./chatPeer";
import { FaultProxy } from "./faultProxy";

const QUIET_WINDOW_PASSED_MS = 4 * 60 * 1000;

eachVersionFrom(18, "chat", (target) => {
	let proxy: FaultProxy;
	let peer: ChatPeer;
	let adminUid: number;
	let notificationType: string;

	beforeAll(async () => {
		proxy = await FaultProxy.start(target);
		peer = await ChatPeer.open(target);
		adminUid = await peer.admin.login();
		notificationType = (await peer.admin.read("res.users", adminUid, ["notification_type"])).notification_type;
		await peer.admin.write("res.users", [adminUid], { notification_type: "inbox" });
	});
	afterAll(async () => {
		await peer?.admin.write("res.users", [adminUid], { notification_type: notificationType });
		await proxy.stop();
	});
	afterEach(() => {
		proxy.down = false;
		vi.useRealTimers();
	});

	const later = (ms: number) => vi.setSystemTime(Date.now() + ms);
	const posts = () => proxy.calls.filter((c) => c.path === "/mail/message/post");

	/** The app through the proxy, its chat source loaded. */
	async function app(opts: { chatModule?: "auto" | "ignore" } = {}) {
		const env = await appFor(proxy.via(target), "admin", opts);
		const [src] = await env.chat.sources();
		await env.chat.load(src);
		return { env, src };
	}

	const conversation = async (env: SyncEnv, configId: string, channelId: number) =>
		(await env.chat.conversations([configId])).find((c) => c.channelId === channelId)!;

	const withText = async (channelId: number, text: string, fields?: string[]) =>
		(await peer.comments(channelId, fields)).filter((m) => m.body.includes(text));

	it("sources lists the Odoo 18 server", async () => {
		const env = await appFor(TARGETS);
		const sources = await env.chat.sources();
		const expected = TARGETS.map((t, i) => (t.version === 18 ? env.configIds[i] : null)).filter((id) => id !== null);
		expect(sources.map((s) => s.configId)).toEqual(expected);
		const app = (await env.db.getAllApplications()).find((a) => a.url === target.url)!;
		expect(app.odooVersion).toBe("18.0");
	});

	it("load matches server counters", async () => {
		const group = await peer.group(unique("group"));
		const channel = await peer.channel(unique("channel"));
		await peer.post(group, "first");
		await peer.post(group, "second");
		await peer.post(channel, "look", { mentionAdmin: true });
		await peer.post(channel, "no mention");
		const { env, src } = await app();

		const g = await conversation(env, src.configId, group);
		const c = await conversation(env, src.configId, channel);
		expect(g.unreadCounter).toBe(2);
		expect(g.unreadCounter).toBe((await peer.adminMember(group)).message_unread_counter);
		expect(g.needactionCounter).toBe(await peer.adminMentions(group));
		expect(c.needactionCounter).toBe(1);
		expect(c.needactionCounter).toBe(await peer.adminMentions(channel));
		expect(c.unreadCounter).toBe((await peer.adminMember(channel)).message_unread_counter);
	});

	it("post appears once for chat_user", async () => {
		const group = await peer.group(unique("group"));
		const { env, src } = await app();
		const text = unique("hello");
		const sent = await env.chat.send(src, group, text);

		const found = await withText(group, text);
		expect(found).toHaveLength(1);
		expect(found[0].author_id[0]).toBe(peer.adminPartnerId);
		const mine = (await env.chat.messages(src.configId, group)).filter((m) => m.clientUuid === sent.clientUuid);
		expect(mine).toMatchObject([{ status: "sent", messageId: found[0].id }]);
	});

	/** A post whose answer is lost after Odoo ran it, retried once the quiet window is over. */
	async function lostThenRetried(chatModule: "auto" | "ignore") {
		vi.useFakeTimers({ toFake: ["Date"] });
		const group = await peer.group(unique("group"));
		const { env, src } = await app({ chatModule });
		const text = unique("lost");
		proxy.loseResponseOf((c) => c.path === "/mail/message/post");
		const sent = await env.chat.send(src, group, text);
		const sentBody = posts().at(-1)!.params!.post_data;
		expect(await withText(group, text)).toHaveLength(1);
		expect((await env.chat.messages(src.configId, group)).find((m) => m.clientUuid === sent.clientUuid)!.status).toBe("pending");

		later(QUIET_WINDOW_PASSED_MS);
		const before = posts().length;
		await env.chat.flushAll();
		const found = await withText(group, text, ["id", "body", "erplibre_client_uuid"]);
		expect(found).toHaveLength(1);
		const mine = (await env.chat.messages(src.configId, group)).filter((m) => m.clientUuid === sent.clientUuid);
		expect(mine).toMatchObject([{ status: "sent", messageId: found[0].id }]);
		return { env, src, sent, sentBody, stored: found[0], reposts: posts().length - before };
	}

	it("lost response with module: one message", async () => {
		const { env, src, sent, sentBody, stored } = await lostThenRetried("auto");
		expect((await env.chat.repo.sourceState(src.configId)).moduleState).toBe("installed");
		expect(sentBody.erplibre_client_uuid).toBe(sent.clientUuid);
		expect(stored.erplibre_client_uuid).toBe(sent.clientUuid);
	});

	it("lost response with marker: one message", async () => {
		const { sentBody, stored, reposts } = await lostThenRetried("ignore");
		// Without the module only the marker search stands between a retry and a second message
		expect(reposts).toBe(0);
		expect(sentBody).not.toHaveProperty("erplibre_client_uuid");
		expect(stored.erplibre_client_uuid).toBeFalsy();
	});

	it("offline queue keeps order", async () => {
		vi.useFakeTimers({ toFake: ["Date"] });
		const group = await peer.group(unique("group"));
		const { env, src } = await app();
		proxy.down = true;
		const texts = [1, 2, 3].map((i) => unique(`order-${i}`));
		for (const text of texts) {
			await env.chat.send(src, group, text);
			// A second apart, as typed: the outbox runs its rows by creation time
			later(1000);
		}
		expect(await peer.comments(group)).toEqual([]);

		proxy.down = false;
		later(QUIET_WINDOW_PASSED_MS);
		await env.chat.flushAll();
		const bodies = (await peer.comments(group)).map((m) => m.body);
		expect(bodies).toHaveLength(3);
		expect(texts.map((text) => bodies.findIndex((b) => b.includes(text)))).toEqual([0, 1, 2]);
		const cached = await env.chat.messages(src.configId, group);
		expect(cached.map((m) => m.status)).toEqual(["sent", "sent", "sent"]);
	});

	it("history paging leaves mentions", async () => {
		const channel = await peer.channel(unique("channel"));
		await peer.post(channel, "look", { mentionAdmin: true });
		for (const n of [1, 2, 3]) await peer.post(channel, `after ${n}`);
		expect(await peer.adminMentions(channel)).toBe(1);
		const { env, src } = await app();

		expect(await env.chat.loadAll(src, channel)).toBeGreaterThan(0);
		const cached = new Set((await env.chat.messages(src.configId, channel)).map((m) => m.messageId));
		for (const m of await peer.comments(channel)) expect(cached.has(m.id)).toBe(true);
		expect((await env.chat.repo.channel(src.configId, channel))!.historyComplete).toBe(true);
		expect(await peer.adminMentions(channel)).toBe(1);
		expect((await conversation(env, src.configId, channel)).needactionCounter).toBe(1);
	});

	it("read marks seen on server", async () => {
		const group = await peer.group(unique("group"));
		await peer.post(group, "first");
		const last = await peer.post(group, "look", { mentionAdmin: true });
		const { env, src } = await app();
		expect((await peer.adminMember(group)).message_unread_counter).toBe(2);
		expect(await peer.adminMentions(group)).toBe(1);

		await env.chat.markRead(src, group);
		const member = await peer.adminMember(group);
		expect(member.seen_message_id).toBe(last);
		expect(member.message_unread_counter).toBe(0);
		expect(await peer.adminMentions(group)).toBe(0);
	});
});
