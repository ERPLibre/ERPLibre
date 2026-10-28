/**
 * The chat bus against a real Odoo 18: the app (admin) runs its realtime
 * client over Node's WebSocket through the proxy, chat_user posts and types
 * in a browser session, and what Odoo pushes reaches the app's cache. A
 * socket the proxy cuts reconnects and catches up, from the last bus id it
 * saved, on what was posted meanwhile.
 *
 * Each scenario waits on the app's cache with a bounded poll (until), never a
 * fixed sleep, and stops the realtime client after it.
 */
import { appFor, eachVersionFrom, nodeTransport, unique, until } from "./harness";
import type { SyncEnv } from "./harness";
import { ChatPeer } from "./chatPeer";
import { FaultProxy } from "./faultProxy";

eachVersionFrom(18, "chat realtime", (target) => {
	let proxy: FaultProxy;
	let peer: ChatPeer;
	let env: SyncEnv | null = null;
	let random: { mockRestore(): void } | null = null;

	beforeAll(async () => {
		proxy = await FaultProxy.start(target);
		peer = await ChatPeer.open(target);
	});
	afterAll(async () => {
		await proxy.stop();
	});
	afterEach(() => {
		env?.chat.stopRealtime();
		env = null;
		proxy.down = false;
		random?.mockRestore();
		random = null;
	});

	const sockets = () => proxy.calls.filter((c) => c.path.startsWith("/websocket")).length;

	/**
	 * The app through the proxy with its bus started, once its websocket is
	 * asked for; delivered collects every notification the bus hands the chat.
	 */
	async function live() {
		const started = await appFor(proxy.via(target));
		env = started;
		const applyBus = vi.spyOn(started.chat, "applyBus");
		const opened = sockets();
		await started.chat.startRealtime(() => nodeTransport());
		const [src] = await started.chat.sources();
		await until("the app's websocket", async () => sockets() > opened);
		const delivered = () => applyBus.mock.calls.flatMap(([, notifications]) => notifications);
		return { env: started, src, delivered };
	}

	const newMessage = (n: any, messageId: number) =>
		n.message?.type === "discuss.channel/new_message"
		&& (n.message.payload?.data?.["mail.message"] ?? []).some((m: any) => m.id === messageId);

	const lastIs = (e: SyncEnv, configId: string, channelId: number, messageId: number) => async () =>
		(await e.chat.repo.channel(configId, channelId))?.lastMessageId === messageId;

	it("bus delivers a message of chat_user", async () => {
		const group = await peer.group(unique("group"));
		const { env, src, delivered } = await live();
		const text = unique("live");
		const id = await peer.post(group, text);

		// The bus brings it; a reload some other notification triggers may bring it first
		await until("its bus notification", async () => delivered().some((n) => newMessage(n, id)));
		await until("the message as the conversation's last", lastIs(env, src.configId, group, id));
		const [message] = (await env.chat.messages(src.configId, group)).filter((m) => m.messageId === id);
		expect(message.body).toContain(text);
		expect((await env.chat.repo.channel(src.configId, group))!.unreadCounter)
			.toBe((await peer.adminMember(group)).message_unread_counter);
	});

	it("typing of chat_user reaches the app", async () => {
		const group = await peer.group(unique("group"));
		const { env, src } = await live();
		const typing = (on: boolean) => async () =>
			(await env.chat.repo.members(src.configId, group)).find((m) => m.partnerId === peer.partnerId && m.isTyping === on);

		await peer.typing(group, true);
		const member = await until("chat_user typing in the app", typing(true));
		expect(member.typingAt).toBeTruthy();
		await peer.typing(group, false);
		await until("chat_user no longer typing in the app", typing(false));
	});

	it("first connection keeps the counters load read", async () => {
		// A conversation created and written to less than 50 s before: the first
		// poll (last=0) replays its creation, whose records carry the counters of then
		const group = await peer.group(unique("group"));
		await peer.post(group, unique("early"));
		const { env, src } = await live();
		await until("the replay applied", async () => (await env.chat.repo.sourceState(src.configId)).lastBusId > 0);
		expect((await env.chat.repo.channel(src.configId, group))!.unreadCounter)
			.toBe((await peer.adminMember(group)).message_unread_counter);
	});

	it("socket cut then reconnect delivers missed messages", { timeout: 150000 }, async () => {
		// No jitter: the reconnect comes after the backoff's first step (1 s)
		random = vi.spyOn(Math, "random").mockReturnValue(0);
		const group = await peer.group(unique("group"));
		const { env, src, delivered } = await live();
		const first = await peer.post(group, unique("before"));
		await until("the first message", lastIs(env, src.configId, group, first));
		await until("its bus id saved", async () => (await env.chat.repo.sourceState(src.configId)).lastBusId > 0);
		const opened = sockets();

		proxy.down = true;
		proxy.cutSockets();
		// Two of them: a reload brings only a conversation's last message, the bus catch-up brings both
		const missed = [await peer.post(group, unique("missed-1")), await peer.post(group, unique("missed-2"))];
		proxy.down = false;

		// The first connection replays the bus from 0, and each message of a conversation the app does not
		// hold in it reloads the account: a reload brings the conversation's last message ahead of the bus,
		// so the wait is on both missed messages in the cache, not on the last one
		const cachedIds = async () => (await env.chat.messages(src.configId, group)).map((m) => m.messageId);
		await until("the missed messages after the reconnect", async () => {
			const ids = await cachedIds();
			return missed.every((id) => ids.includes(id));
		}, 90000);
		expect(await lastIs(env, src.configId, group, missed[1])()).toBe(true);
		expect(sockets()).toBeGreaterThan(opened);
		for (const id of missed) expect(delivered().some((n) => newMessage(n, id))).toBe(true);
		const ids = (await env.chat.messages(src.configId, group)).map((m) => m.messageId);
		for (const id of [first, ...missed]) expect(ids.filter((x) => x === id)).toHaveLength(1);
		expect(ids).not.toContain(null);
		expect((await env.chat.repo.channel(src.configId, group))!.unreadCounter)
			.toBe((await peer.adminMember(group)).message_unread_counter);
	});
});
