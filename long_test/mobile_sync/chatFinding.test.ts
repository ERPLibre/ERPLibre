/**
 * Finding things in the chat against a real Odoo 18, the app as admin
 * through the proxy, chat_user at the other end in a browser session: the
 * server search (the module's route, and search_read without it) finds
 * only messages of admin's member channels, a term with `&` and `%`
 * finds the same messages on both routes and on the phone, a hit older
 * than the loaded history is paged in with `around` only and nothing is
 * marked read; a pin whose answer is lost is set once with one notice,
 * chat_user's pin reaches the pinned panel; a star whose answer is lost
 * ends starred on both routes, and a star made in admin's browser since
 * the load stays starred when the phone stars it (the re-read without the
 * module). Every outcome is read back from the server.
 *
 * Retry delays are skipped by a forced flush; nothing here changes a
 * server-wide setting or a shared user's settings, so the file runs with
 * the others.
 */
import { appFor, composeBody, eachVersionFrom, emojiConversions, EMPTY_MENTIONS, setOnline, unique } from "./harness";
import type { MessageTarget, SyncEnv } from "./harness";
import { ChatPeer } from "./chatPeer";
import { FaultProxy } from "./faultProxy";
import { ROUTES } from "./chatAttachmentScene";

const CHANNEL = "discuss.channel";
const SEARCH_ROUTE = "/erplibre_mobile_chat/message/search";
const PAGE_ROUTE = "/discuss/channel/messages";
/** The routes that mark what they return read: the app's finding never calls them. */
const READING_ROUTES = ["/mail/thread/messages"];
/** Messages posted after a hit so that it lies below the first history page (CHAT_PAGE, 30). */
const ABOVE_THE_HIT = 40;

eachVersionFrom(18, "chat finding", (target) => {
	let proxy: FaultProxy;
	let peer: ChatPeer;
	let inboxPartner: number;
	let env: SyncEnv | null = null;

	beforeAll(async () => {
		proxy = await FaultProxy.start(target);
		peer = await ChatPeer.open(target);
		inboxPartner = await peer.partnerOf(target.inbox!.login);
	});
	afterAll(async () => {
		await proxy.stop();
	});
	afterEach(() => {
		env?.chat.stopRealtime();
		env = null;
		proxy.down = false;
		setOnline(true);
	});

	/** The app as admin through the proxy, its chat source loaded. */
	async function app(opts: { chatModule?: "auto" | "ignore" } = {}) {
		const started = await appFor(proxy.via(target), "admin", { chatModule: opts.chatModule });
		env = started;
		const [src] = await started.chat.sources();
		await started.chat.load(src);
		return { env: started, src };
	}

	const idle = (e: SyncEnv, configId: string) => e.chat.queue.whenIdle(configId);
	const sent = (messageId: number): MessageTarget => ({ messageId, clientUuid: null });
	const callsTo = (path: string, since = 0) => proxy.calls.slice(since).filter((c) => c.path === path);
	const callsOf = (method: string, since = 0) => proxy.calls.slice(since).filter((c) => c.method === method);
	const opsOf = async (e: SyncEnv, configId: string, kind: string) =>
		(await e.db.getOutboxOpsForConfig(configId)).filter((o: any) => o.kind === kind);

	/** chat_user's post of text as the browser's composer sends it (its HTML, `&` escaped). */
	async function postText(channelId: number, text: string): Promise<number> {
		return peer.post(channelId, composeBody(text, EMPTY_MENTIONS, await emojiConversions()).body);
	}

	for (const { label, chatModule } of ROUTES) {
		it(`server search ${label}: only admin's member channels, never a public channel or others' chat`, async () => {
			const word = unique("secret");
			const group = await peer.group(unique("group"));
			const mine = await postText(group, `${word} in the group`);
			const open = await peer.channel(unique("public"), { invite: false });
			await postText(open, `${word} in a public channel`);
			const chat = await peer.chat(inboxPartner);
			await postText(chat, `${word} between chat_user and inbox_user`);
			expect(await peer.members(open)).not.toContain(peer.adminPartnerId);

			const { env, src } = await app({ chatModule });
			expect((await env.chat.features(src.configId)).serverSearch).toBe(chatModule === "auto");
			const mark = proxy.calls.length;
			const found = await env.chat.search.server(src, word);
			expect(found.offline).toBe(false);
			expect(found.hits.map((h) => [h.channelId, h.messageId])).toEqual([[group, mine]]);
			expect(found.count).toBe(1);
			expect(callsTo(SEARCH_ROUTE, mark)).toHaveLength(chatModule === "auto" ? 1 : 0);
			for (const path of READING_ROUTES) expect(callsTo(path, mark)).toEqual([]);
		});
	}

	it("a term with & and %: the module, the fallback and the phone find the same messages", async () => {
		const tag = unique("term");
		const group = await peer.group(unique("group"));
		const hit = await postText(group, `${tag} & 100% pur`);
		// `%` matches only itself, `&` only itself
		await postText(group, `${tag} & 1000 pur`);
		await postText(group, `${tag} et 100% pur`);
		const term = `${tag} & 100%`;
		const ids: Record<string, number[]> = {};
		for (const { label, chatModule } of ROUTES) {
			const { env, src } = await app({ chatModule });
			ids[label] = (await env.chat.search.server(src, term)).hits.map((h) => h.messageId!);
			await env.chat.loadOlder(src, group);
			const local = await env.chat.search.local([src.configId], term);
			expect(local.messages.map((h) => h.messageId)).toEqual([hit]);
		}
		expect(Object.values(ids)).toEqual([[hit], [hit]]);
	});

	it("open at a hit older than the loaded history: paged with around only, nothing marked read", async () => {
		const word = unique("old");
		const group = await peer.group(unique("group"));
		const hit = await postText(group, `${word} far back`);
		for (let i = 0; i < ABOVE_THE_HIT; i++) await peer.post(group, `filler ${i}`);
		const { env, src } = await app();
		await env.chat.loadOlder(src, group);
		expect(await env.chat.repo.message(src.configId, hit)).toBeNull();
		const before = await peer.adminMember(group);
		expect(before.message_unread_counter).toBeGreaterThan(ABOVE_THE_HIT);

		const [found] = (await env.chat.search.server(src, word)).hits;
		expect(found.messageId).toBe(hit);
		const mark = proxy.calls.length;
		expect(await env.chat.loadUntil(src, group, hit)).toBe(true);
		expect(await env.chat.repo.message(src.configId, hit)).toMatchObject({ messageId: hit, channelId: group });
		const pages = callsTo(PAGE_ROUTE, mark);
		expect(pages.length).toBeGreaterThan(0);
		for (const page of pages) expect(page.params).toMatchObject({ channel_id: group, around: expect.any(Number) });
		for (const path of READING_ROUTES) expect(callsTo(path, mark)).toEqual([]);
		expect(await peer.adminMember(group)).toEqual(before);
	});

	it("pin whose answer is lost: pinned_at set, the notice posted once", async () => {
		const group = await peer.group(unique("group"));
		const messageId = await peer.post(group, unique("to-pin"));
		const { env, src } = await app();
		await env.chat.loadOlder(src, group);
		proxy.loseResponseOf((c) => c.method === "set_message_pin");
		await env.chat.pin(src, group, sent(messageId), true);
		await idle(env, src.configId);
		expect((await peer.admin.read("mail.message", messageId, ["pinned_at"])).pinned_at).toBeTruthy();
		expect(await opsOf(env, src.configId, "chat.pin")).toHaveLength(1);

		await env.chat.flushAll({ force: true });
		await idle(env, src.configId);
		expect(callsOf("set_message_pin")).toHaveLength(2);
		expect((await peer.admin.read("mail.message", messageId, ["pinned_at"])).pinned_at).toBeTruthy();
		const notices = await peer.admin.searchRead(
			"mail.message",
			[["model", "=", CHANNEL], ["res_id", "=", group], ["message_type", "=", "notification"],
				["body", "ilike", 'data-oe-type="pin"'], ["body", "ilike", `data-oe-id="${messageId}"`]],
			["id"],
		);
		expect(notices).toHaveLength(1);
		expect(await opsOf(env, src.configId, "chat.pin")).toEqual([]);
		expect((await env.chat.repo.message(src.configId, messageId))!.pinnedAt).toBeTruthy();
	});

	it("chat_user's pin reaches the pinned panel", async () => {
		const group = await peer.group(unique("group"));
		const messageId = await peer.post(group, unique("pinned-by-peer"));
		await peer.post(group, unique("not-pinned"));
		await peer.pin(group, messageId, true);
		const { env, src } = await app();
		const panel = await env.chat.pinnedMessages(src, group);
		expect(panel.offline).toBe(false);
		expect(panel.messages.map((m) => m.messageId)).toEqual([messageId]);
	});

	for (const { label, chatModule } of ROUTES) {
		it(`star whose answer is lost ${label}: starred once after the retry`, async () => {
			const group = await peer.group(unique("group"));
			const messageId = await peer.post(group, unique("to-star"));
			const { env, src } = await app({ chatModule });
			expect((await env.chat.features(src.configId)).idempotentStar).toBe(chatModule === "auto");
			await env.chat.loadOlder(src, group);
			const method = chatModule === "auto" ? "erplibre_set_starred" : "toggle_message_starred";
			const mark = proxy.calls.length;
			proxy.loseResponseOf((c) => c.method === method);
			await env.chat.star(src, messageId, true, group);
			await idle(env, src.configId);
			expect(await peer.starredBy(target.admin.login, messageId)).toBe(true);
			expect(await opsOf(env, src.configId, "chat.star")).toHaveLength(1);

			await env.chat.flushAll({ force: true });
			await idle(env, src.configId);
			expect(await peer.starredBy(target.admin.login, messageId)).toBe(true);
			// Without the module the retry reads the star first and sends no second toggle
			expect(callsOf(method, mark)).toHaveLength(chatModule === "auto" ? 2 : 1);
			expect(await opsOf(env, src.configId, "chat.star")).toEqual([]);
			expect((await env.chat.repo.message(src.configId, messageId))!.starred).toBe(true);
		});
	}

	it("a star made in admin's browser since the load, starred on the phone: still starred", async () => {
		const group = await peer.group(unique("group"));
		const messageId = await peer.post(group, unique("starred-elsewhere"));
		const { env, src } = await app({ chatModule: "ignore" });
		await env.chat.loadOlder(src, group);
		expect((await env.chat.repo.message(src.configId, messageId))!.starred).toBe(false);
		await peer.admin.execute("mail.message", "toggle_message_starred", [[messageId]]);
		expect(await peer.starredBy(target.admin.login, messageId)).toBe(true);

		const mark = proxy.calls.length;
		await env.chat.star(src, messageId, true, group);
		await idle(env, src.configId);
		expect(await peer.starredBy(target.admin.login, messageId)).toBe(true);
		expect(callsOf("toggle_message_starred", mark)).toEqual([]);
		expect(await opsOf(env, src.configId, "chat.star")).toEqual([]);
		expect((await env.chat.repo.message(src.configId, messageId))!.starred).toBe(true);
	});
});
