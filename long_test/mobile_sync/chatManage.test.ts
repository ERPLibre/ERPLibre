/**
 * Managing conversations against a real Odoo 18, the app as admin through
 * the proxy, chat_user at the other end: who to write to and the direct
 * message, a group created offline and the app restarted before the
 * network comes back (with the server module and on the fingerprint path
 * without it), new channels and their access group, joining, inviting,
 * renaming, the description, leaving with a post still queued, hiding a
 * direct message, muting (a conversation, a mute queued past its end, the
 * whole account) and removing a member. Every outcome is read back from
 * the server.
 *
 * The quiet window (3 minutes) and a mute's end pass on a faked Date: only
 * the app's clock moves, the requests stay real. Scenarios that need the
 * bus run the app's realtime client and wait on its cache with a bounded
 * poll (until); a fixed pause only checks that a state reached still holds.
 */
import { appFor, chatTitle, eachVersionFrom, nodeTransport, restartSyncEnv, setOnline, unique, until } from "./harness";
import type { SyncEnv } from "./harness";
import { ChatPeer } from "./chatPeer";
import { FaultProxy } from "./faultProxy";

const CHANNEL = "discuss.channel";
const QUIET_WINDOW_PASSED_MS = 4 * 60 * 1000;
const MINUTE_MS = 60 * 1000;
/** How far a server's mute end may stand from the one computed here: the request's own delay. */
const MUTE_SLACK_MS = 2 * MINUTE_MS;

/** Epoch ms of an Odoo "YYYY-MM-DD HH:MM:SS" UTC datetime. */
const utcMs = (dt: string) => Date.parse(dt.replace(" ", "T") + "Z");

eachVersionFrom(18, "chat management", (target) => {
	let proxy: FaultProxy;
	let peer: ChatPeer;
	let adminUid: number;
	let env: SyncEnv | null = null;
	let internalGroupId: number;

	beforeAll(async () => {
		proxy = await FaultProxy.start(target);
		peer = await ChatPeer.open(target);
		adminUid = await peer.admin.login();
		const [ref] = await peer.admin.searchRead("ir.model.data", [["module", "=", "base"], ["name", "=", "group_user"]], ["res_id"]);
		internalGroupId = ref.res_id;
	});
	afterAll(async () => {
		await proxy.stop();
	});
	afterEach(() => {
		env?.chat.stopRealtime();
		env = null;
		proxy.down = false;
		setOnline(true);
		vi.useRealTimers();
	});

	const later = (ms: number) => vi.setSystemTime(Date.now() + ms);

	/** The app as `as` through the proxy, its chat source loaded. */
	async function app(opts: { as?: "admin" | "multi" | "chat"; chatModule?: "auto" | "ignore" } = {}) {
		const started = await appFor(proxy.via(target), opts.as ?? "admin", { chatModule: opts.chatModule });
		env = started;
		const [src] = await started.chat.sources();
		await started.chat.load(src);
		return { env: started, src };
	}

	/** app() with its bus started, once its websocket is asked for; delivered collects what the bus hands the chat. */
	async function live(as: "admin" | "multi" = "admin") {
		const { env: started, src } = await app({ as });
		const applyBus = vi.spyOn(started.chat, "applyBus");
		const sockets = () => proxy.calls.filter((c) => c.path.startsWith("/websocket")).length;
		const opened = sockets();
		await started.chat.startRealtime(() => nodeTransport());
		await until("the app's websocket", async () => sockets() > opened);
		const delivered = () => applyBus.mock.calls.flatMap(([, notifications]) => notifications);
		return { env: started, src, delivered };
	}

	const newMessage = (n: any, messageId: number) =>
		n.message?.type === "discuss.channel/new_message"
		&& (n.message.payload?.data?.["mail.message"] ?? []).some((m: any) => m.id === messageId);

	const server = (channelId: number, fields: string[]) => peer.admin.read(CHANNEL, channelId, fields);

	/** The ids of the server's conversations named name, archived ones included. */
	const named = async (name: string) =>
		(await peer.admin.searchRead(CHANNEL, [["name", "=", name]], ["id"], { context: { active_test: false } })).map((c) => c.id);

	const shown = async (e: SyncEnv, configId: string, channelId: number) =>
		(await e.chat.conversations([configId])).find((c) => c.channelId === channelId) ?? null;

	it("direct message to chat_user found by name, made once and reused", async () => {
		const { env, src } = await app();
		const found = await env.chat.people.searchPeople(src, "MS Chat");
		expect(found.map((p) => p.partnerId)).toContain(peer.partnerId);

		const gets = () => proxy.callsOf(CHANNEL, "channel_get").length;
		const first = await env.chat.startDirect(src, peer.partnerId);
		expect(first.channelId).toBeGreaterThan(0);
		const dm = await server(first.channelId, ["channel_type", "channel_partner_ids"]);
		expect(dm.channel_type).toBe("chat");
		expect([...dm.channel_partner_ids].sort()).toEqual([peer.adminPartnerId, peer.partnerId].sort());
		const before = gets();
		expect(await env.chat.startDirect(src, peer.partnerId)).toEqual(first);
		expect(gets()).toBe(before);
		expect((await env.chat.people.recentPeople(src.configId)).map((p) => p.partnerId)).toContain(peer.partnerId);

		// Another phone gets the same conversation: Odoo's channel_get finds it again
		const other = await app();
		expect((await other.env.chat.startDirect(other.src, peer.partnerId)).channelId).toBe(first.channelId);
		const chats = (await peer.admin.searchRead(CHANNEL, [["channel_type", "=", "chat"], ["channel_partner_ids", "in", [peer.partnerId]]], ["channel_partner_ids"]))
			.filter((c) => c.channel_partner_ids.length === 2 && c.channel_partner_ids.includes(peer.adminPartnerId));
		expect(chats.map((c) => c.id)).toEqual([first.channelId]);
	});

	/**
	 * A group with chat_user created offline, two texts written into it, a
	 * rename and a mute queued on it, the app killed, then the network back
	 * with the create's answer lost: after the quiet window the retry
	 * settles on the one group, the texts reach it once each, in order, and
	 * the group ends with the name and the mute queued.
	 */
	async function offlineGroupThenRestart(chatModule: "auto" | "ignore") {
		vi.useFakeTimers({ toFake: ["Date"] });
		const first = await app({ chatModule });
		setOnline(false);
		const name = unique("offline-group");
		const creates = () => proxy.callsOf(CHANNEL, "create_group").length;
		const createsBefore = creates();
		const { channelId: tempId } = await first.env.chat.createGroup(first.src, [peer.partnerId], name);
		expect(tempId).toBeLessThan(0);
		const texts = [unique("first"), unique("second")];
		for (const text of texts) {
			await first.env.chat.send(first.src, tempId, text);
			later(1000);
		}
		// Managed while only the phone knows it: queued behind the create
		const renamed = unique("renamed-group");
		await first.env.chat.rename(first.src, tempId, renamed);
		await first.env.chat.mute(first.src, tempId, -1);
		expect(creates()).toBe(createsBefore);

		const restarted = await restartSyncEnv(first.env);
		env = restarted;
		const [src] = await restarted.chat.sources();
		setOnline(true);
		proxy.loseResponseOf((c) => c.method === "create_group");
		await restarted.chat.flushAll();
		expect(creates()).toBe(createsBefore + 1);
		expect(await restarted.chat.realIdOf(src.configId, tempId)).toBeNull();

		later(QUIET_WINDOW_PASSED_MS);
		await restarted.chat.flushAll();
		// The fingerprint and the uuid found the group under its first name; the rename went after
		expect(await named(name)).toEqual([]);
		const groups = await peer.admin.searchRead(CHANNEL, [["name", "=", renamed]], ["id", "channel_type", "channel_partner_ids", "erplibre_client_uuid"]);
		expect(groups).toHaveLength(1);
		const [group] = groups;
		expect((await peer.memberOf(group.id, peer.adminPartnerId, ["mute_until_dt"])).mute_until_dt).toBe("9999-12-31 23:59:59");
		expect(group.channel_type).toBe("group");
		expect([...group.channel_partner_ids].sort()).toEqual([peer.adminPartnerId, peer.partnerId].sort());
		const bodies = (await peer.comments(group.id)).map((m) => m.body);
		expect(bodies).toHaveLength(2);
		expect(texts.map((text) => bodies.findIndex((b) => b.includes(text)))).toEqual([0, 1]);

		expect(await restarted.chat.realIdOf(src.configId, tempId)).toBe(group.id);
		expect(await restarted.chat.repo.channel(src.configId, tempId)).toBeNull();
		expect(await restarted.chat.repo.channel(src.configId, group.id)).toMatchObject({
			isMember: true, createOpId: null, name: renamed, muteUntilDt: "9999-12-31 23:59:59",
		});
		expect((await restarted.chat.messages(src.configId, group.id)).map((m) => m.status)).toEqual(["sent", "sent"]);
		expect(await restarted.db.getOutboxOpsForConfig(src.configId)).toEqual([]);
		return { group, creates: creates() - createsBefore };
	}

	it("offline group, restart, network back with module: one group, posts in order", async () => {
		const { group, creates } = await offlineGroupThenRestart("auto");
		// The retry is sent again; the module answers with the group the lost one made
		expect(creates).toBe(2);
		expect(group.erplibre_client_uuid).toBeTruthy();
	});

	it("offline group, restart, network back without module: fingerprint finds it", async () => {
		const { group, creates } = await offlineGroupThenRestart("ignore");
		// Only the fingerprint search stands between the retry and a second group
		expect(creates).toBe(1);
		expect(group.erplibre_client_uuid).toBeFalsy();
	});

	it("new channel takes the internal users group by default, or everyone", async () => {
		const { env, src } = await app();
		const groups = await env.chat.people.accessGroups(src);
		expect(groups.defaultId).toBe(internalGroupId);
		expect(groups.groups.map((g) => g.id)).toEqual(expect.arrayContaining([internalGroupId, false]));

		const internalName = unique("channel");
		const internal = await env.chat.createChannel(src, internalName, groups.defaultId);
		expect(internal.channelId).toBeGreaterThan(0);
		expect(await named(internalName)).toEqual([internal.channelId]);
		const read = await server(internal.channelId, ["channel_type", "group_public_id", "create_uid", "channel_partner_ids"]);
		expect(read.channel_type).toBe("channel");
		expect(read.group_public_id[0]).toBe(internalGroupId);
		expect(read.create_uid[0]).toBe(adminUid);
		expect(read.channel_partner_ids).toEqual([peer.adminPartnerId]);

		const everyoneName = unique("everyone");
		const everyone = await env.chat.createChannel(src, everyoneName, false);
		expect(await named(everyoneName)).toEqual([everyone.channelId]);
		expect((await server(everyone.channelId, ["group_public_id"])).group_public_id).toBe(false);
		expect(await env.chat.repo.channel(src.configId, everyone.channelId)).toMatchObject({ channelType: "channel", isMember: true });
	});

	it("chat_user's new group reaches the app live, its messages by the bus, no reload each", async () => {
		// The app is the two-company user here: no other file's conversation involves it, so
		// every load through this file's proxy is this scenario's own
		const multiPartnerId = await peer.partnerOf(target.multi.login);
		const { env, src, delivered } = await live("multi");
		const group = await peer.group(unique("their-group"), multiPartnerId);
		await until("their group in the app", async () => (await env.chat.repo.channel(src.configId, group))?.isMember);

		// A new_message reaches the socket only once it subscribed again with the group; the
		// Store of the channel may land a frame before it
		const loads = () => proxy.calls.filter((c) => c.path === "/mail/data").length;
		const lastIs = (id: number) => async () => (await env.chat.repo.channel(src.configId, group))?.lastMessageId === id;
		let afterFirst = 0;
		for (const label of ["first", "second", "third"]) {
			const id = await peer.post(group, unique(label));
			await until(`their ${label} message on the bus`, async () => delivered().some((n) => newMessage(n, id)));
			await until(`their ${label} message`, lastIs(id));
			if (label === "first") afterFirst = loads();
			else expect(loads()).toBe(afterFirst);
		}
	});

	it("join a channel chat_user created", async () => {
		const name = unique("their-channel");
		const channel = await peer.channel(name, { invite: false });
		const { env, src } = await app();
		const { channels } = await env.chat.people.joinableChannels(src, name);
		expect(channels.map((c) => c.channelId)).toEqual([channel]);

		expect(await env.chat.join(src, channel, name)).toEqual({ configId: src.configId, channelId: channel });
		expect(await named(name)).toEqual([channel]);
		expect(await peer.members(channel)).toContain(peer.adminPartnerId);
		expect(await env.chat.repo.channel(src.configId, channel)).toMatchObject({ isMember: true, createOpId: null });
		expect((await env.chat.people.joinableChannels(src, name)).channels).toEqual([]);
	});

	it("invite chat_user, rename, describe", async () => {
		const { env, src } = await app();
		const name = unique("channel");
		const { channelId: channel } = await env.chat.createChannel(src, name, internalGroupId);
		expect(await named(name)).toEqual([channel]);
		const candidates = await env.chat.people.inviteCandidates(src, channel, "MS Chat");
		expect(candidates.partners.map((p) => p.partnerId)).toContain(peer.partnerId);
		await env.chat.invite(src, channel, [peer.partnerId]);
		expect(await peer.members(channel)).toEqual(expect.arrayContaining([peer.adminPartnerId, peer.partnerId]));

		const renamed = unique("renamed");
		await env.chat.rename(src, channel, renamed);
		await env.chat.describe(src, channel, "What the channel is for");
		expect(await named(renamed)).toEqual([channel]);
		expect(await named(name)).toEqual([]);
		expect(await server(channel, ["name", "description"])).toMatchObject({ name: renamed, description: "What the channel is for" });
		// A channel keeps a name
		await expect(env.chat.rename(src, channel, "  ")).rejects.toThrow();
		expect((await server(channel, ["name"])).name).toBe(renamed);
		expect(await env.db.getOutboxOpsForConfig(src.configId)).toEqual([]);
	});

	it("group renamed, then renamed to nothing shows its members' names", async () => {
		const { env, src } = await app();
		const { channelId: group } = await env.chat.createGroup(src, [peer.partnerId], unique("named"));
		const renamed = unique("renamed");
		await env.chat.rename(src, group, renamed);
		expect(await named(renamed)).toEqual([group]);
		expect(await chatTitle(env, src.configId, group)).toBe(renamed);

		await env.chat.rename(src, group, "");
		expect((await server(group, ["name"])).name).toBeFalsy();
		const names = await Promise.all((await peer.members(group)).map(async (id) =>
			(await peer.admin.read("res.partner", id, ["name"])).name));
		const expected = new Intl.ListFormat("en", { type: "conjunction", style: "long" }).format(names);
		expect(await chatTitle(env, src.configId, group)).toBe(expected);
		// As a new phone shows it, from a load alone
		const other = await app();
		expect(await chatTitle(other.env, other.src.configId, group)).toBe(expected);
	});

	it("leave with a post queued: the post never reaches the server", async () => {
		const group = await peer.group(unique("group"));
		const { env, src } = await app();
		setOnline(false);
		const text = unique("unsent");
		const sent = await env.chat.send(src, group, text);
		await env.chat.leave(src, group);
		setOnline(true);
		await env.chat.flushAll();

		expect(await peer.members(group)).not.toContain(peer.adminPartnerId);
		const comments = await peer.comments(group, ["body", "author_id", "message_type"]);
		expect(comments.some((m) => m.body.includes(text))).toBe(false);
		const left = (await peer.user.searchRead("mail.message",
			[["model", "=", CHANNEL], ["res_id", "=", group], ["author_id", "=", peer.adminPartnerId]], ["body"]));
		expect(left.filter((m) => m.body.includes("left the channel"))).toHaveLength(1);
		const mine = (await env.chat.messages(src.configId, group)).find((m) => m.clientUuid === sent.clientUuid);
		expect(mine).toMatchObject({ status: "failed", messageId: null });
		expect(await env.chat.repo.channel(src.configId, group)).toMatchObject({ isMember: false, leftUnsent: true });
		expect(await shown(env, src.configId, group)).not.toBeNull();
		expect(await env.db.getOutboxOpsForConfig(src.configId)).toEqual([]);
	});

	it("hidden direct message shows again when chat_user writes", async () => {
		const { env, src, delivered } = await live();
		const { channelId: dm } = await env.chat.startDirect(src, peer.partnerId);
		const unpins = () => delivered().filter((n) => n.message?.type === "discuss.channel/unpin" && n.message.payload?.id === dm).length;
		const unpinsBefore = unpins();
		await env.chat.hide(src, dm);
		expect(await peer.memberOf(dm, peer.adminPartnerId, ["is_pinned"])).toMatchObject({ is_pinned: false });
		// A chat created moments before may still get the pin of its creation from the bus after
		// the hide, and shows until the unpin that follows it, as in Odoo's web client, which
		// applies the same frames in the same order. Once that unpin is applied it stays hidden
		await until("the unpin on the bus", async () => unpins() > unpinsBefore);
		await until("the direct message hidden in the app", async () => (await shown(env, src.configId, dm)) === null);
		await new Promise((resolve) => setTimeout(resolve, 1000));
		expect(await shown(env, src.configId, dm)).toBeNull();

		const id = await peer.post(dm, unique("again"));
		await until("the message on the bus", async () => delivered().some((n) => newMessage(n, id)));
		await until("the direct message shown again", async () => (await shown(env, src.configId, dm))?.lastMessageId === id);
		expect(await peer.memberOf(dm, peer.adminPartnerId, ["is_pinned"])).toMatchObject({ is_pinned: true });
	});

	it("mute an hour, then a mute queued past its end unmutes", async () => {
		vi.useFakeTimers({ toFake: ["Date"] });
		const group = await peer.group(unique("group"));
		const { env, src } = await app();
		const muteOnServer = async () => (await peer.memberOf(group, peer.adminPartnerId, ["mute_until_dt"])).mute_until_dt;

		const asked = Date.now();
		await env.chat.mute(src, group, 60);
		const end = await muteOnServer();
		expect(end).toBeTruthy();
		expect(Math.abs(utcMs(end) - (asked + 60 * MINUTE_MS))).toBeLessThan(MUTE_SLACK_MS);
		expect((await env.chat.repo.channel(src.configId, group))!.muteUntilDt).toBeTruthy();

		// Queued offline for 15 minutes, sent 20 minutes later: the mute is over, the server unmutes
		setOnline(false);
		await env.chat.mute(src, group, 15);
		later(20 * MINUTE_MS);
		setOnline(true);
		await env.chat.flushAll();
		expect(await muteOnServer()).toBe(false);
		expect(await env.db.getOutboxOpsForConfig(src.configId)).toEqual([]);
	});

	it("global mute an hour, then back on", async () => {
		const { env, src } = await app();
		const row = async () => (await peer.admin.searchRead("res.users.settings", [["user_id", "=", adminUid]], ["mute_until_dt"]))[0];
		const settings = async () => (await row())?.mute_until_dt ?? false;
		try {
			const asked = Date.now();
			await env.chat.globalMute(src, 60);
			const end = await settings();
			expect(end).toBeTruthy();
			expect(Math.abs(utcMs(end) - (asked + 60 * MINUTE_MS))).toBeLessThan(MUTE_SLACK_MS);
			expect((await env.chat.repo.sourceState(src.configId)).globalMuteUntil).toBeTruthy();

			await env.chat.globalMute(src, false);
			expect(await settings()).toBe(false);
			expect((await env.chat.repo.sourceState(src.configId)).globalMuteUntil).toBeNull();
		} finally {
			// The other scenarios count unread messages: never leave the account muted
			const settled = await row();
			if (settled?.mute_until_dt) await peer.admin.write("res.users.settings", [settled.id], { mute_until_dt: false });
		}
	});

	it("admin removes chat_user: told by the bus, the thread says they left", async () => {
		const { env, src } = await app();
		expect(await env.chat.features(src.configId)).toEqual({
			canRemoveMembers: true, idempotentCreate: true, idempotentUpload: true, guardedEdit: true,
		});
		const { channelId: group } = await env.chat.createGroup(src, [peer.partnerId], unique("group"));
		const bus = await peer.listen();
		try {
			await env.chat.removeMember(src, group, peer.partnerId);
			expect(await peer.members(group)).toEqual([peer.adminPartnerId]);
			await until("the leave on chat_user's bus", async () => bus.notifications.some((n) =>
				n.message?.type === "discuss.channel/leave"
				&& (n.message.payload?.[CHANNEL] ?? []).some((c: any) => c.id === group)));
		} finally {
			bus.close();
		}
		const left = await peer.admin.searchRead("mail.message",
			[["model", "=", CHANNEL], ["res_id", "=", group], ["author_id", "=", peer.partnerId]], ["body"]);
		expect(left.filter((m) => m.body.includes("left the channel"))).toHaveLength(1);
		expect((await env.chat.repo.members(src.configId, group)).map((m) => m.partnerId)).not.toContain(peer.partnerId);
		expect(await env.db.getOutboxOpsForConfig(src.configId)).toEqual([]);
	});

	it("chat_user may not remove a member", async () => {
		const group = await peer.group(unique("group"));
		const { env, src } = await app({ as: "chat" });
		expect((await env.chat.features(src.configId)).canRemoveMembers).toBe(false);
		await expect(env.chat.removeMember(src, group, peer.adminPartnerId)).rejects.toThrow();
		await expect(peer.user.execute(CHANNEL, "erplibre_remove_member", [[group], peer.adminPartnerId])).rejects.toThrow(/AccessError/);
		expect(await peer.members(group)).toEqual(expect.arrayContaining([peer.adminPartnerId, peer.partnerId]));
	});
});
