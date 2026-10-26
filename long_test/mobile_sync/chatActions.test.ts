/**
 * Actions on chat messages against a real Odoo 18, the app through the
 * proxy, chat_user at the other end in a browser session: reactions sent
 * as the target state (one row after a lost answer, nothing sent for an
 * add then a remove offline), chat_user's reaction and edit reaching the
 * app by the bus, an edit that keeps the message's files, a late edit
 * refused (chat_user, the same user in a browser, edits or deletes the
 * message while the app's edit waits offline) through the module's guarded
 * route and through the re-read without it, a delete that empties the
 * message for both ends, and replies (the parent kept, an emptied parent
 * quoted as deleted, a parent of another channel dropped by the server).
 * Every outcome is read back from the server.
 *
 * Retry delays are skipped by a forced flush; nothing here changes a
 * server-wide setting, so the file runs with the others.
 */
import {
	appFor, bodyText, eachVersionFrom, EMPTY_MENTIONS, isEmptyMessage, nodeTransport, setOnline, unique, until,
} from "./harness";
import type { MessageTarget, SyncEnv } from "./harness";
import { ChatPeer } from "./chatPeer";
import { FaultProxy } from "./faultProxy";
import { attachmentScene, filler, ROUTES } from "./chatAttachmentScene";

const REACTION_ROUTE = "/mail/message/reaction";
const MODULE_EDIT_ROUTE = "/erplibre_mobile_chat/message/update_content";
const ODOO_EDIT_ROUTE = "/mail/message/update_content";
/** The routes of a reload: the whole account, or a page of a conversation. */
const RELOAD_ROUTES = ["/mail/data", "/discuss/channel/messages"];

eachVersionFrom(18, "chat actions", (target) => {
	let proxy: FaultProxy;
	let peer: ChatPeer;
	let env: SyncEnv | null = null;

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
		setOnline(true);
	});

	const { idle, staged, mine } = attachmentScene(target, () => ({ proxy, peer }));

	/** The app as `as` through the proxy, its chat source loaded. */
	async function app(opts: { as?: "admin" | "chat"; chatModule?: "auto" | "ignore" } = {}) {
		const started = await appFor(proxy.via(target), opts.as ?? "admin", { chatModule: opts.chatModule });
		env = started;
		const [src] = await started.chat.sources();
		await started.chat.load(src);
		return { env: started, src };
	}

	const callsTo = (path: string, since = 0) => proxy.calls.slice(since).filter((c) => c.path === path);
	const sent = (messageId: number): MessageTarget => ({ messageId, clientUuid: null });

	/** The app's cached message of a server id. */
	const cached = async (e: SyncEnv, configId: string, channelId: number, messageId: number) =>
		(await e.chat.messages(configId, channelId)).find((m) => m.messageId === messageId) ?? null;

	/** The app's cached reaction groups of a server message. */
	const reactionsIn = async (e: SyncEnv, configId: string, channelId: number, messageId: number) =>
		(await e.chat.reactions(configId, channelId, [`m${messageId}`])).get(`m${messageId}`) ?? [];

	/** A message of the app's user posted from the app and settled: its server id. */
	async function posted(e: SyncEnv, src: any, channelId: number, text: string, files: any[] = []) {
		const message = await e.chat.send(src, channelId, text, files);
		await idle(e, src.configId);
		const settled = await mine(e, src.configId, channelId, message.clientUuid);
		expect(settled.status).toBe("sent");
		return { messageId: settled.messageId!, clientUuid: message.clientUuid };
	}

	it("reaction whose answer is lost: one row on the server after the retry", async () => {
		const group = await peer.group(unique("group"));
		const messageId = await peer.post(group, unique("text"));
		const { env, src } = await app();
		await env.chat.loadOlder(src, group);
		proxy.loseResponseOf((c) => c.path === REACTION_ROUTE);
		await env.chat.react(src, group, sent(messageId), "👍", true);
		await idle(env, src.configId);
		// Odoo added it, the app never heard back: the op stays to be sent again
		expect(await peer.reactionsOf(messageId)).toEqual([{ content: "👍", partnerId: peer.adminPartnerId }]);
		expect((await env.db.getOutboxOpsForConfig(src.configId)).filter((o: any) => o.kind === "chat.reaction")).toHaveLength(1);

		await env.chat.flushAll({ force: true });
		await idle(env, src.configId);
		expect(callsTo(REACTION_ROUTE).map((c) => c.params!.action)).toEqual(["add", "add"]);
		expect(await peer.reactionsOf(messageId)).toEqual([{ content: "👍", partnerId: peer.adminPartnerId }]);
		expect((await env.db.getOutboxOpsForConfig(src.configId)).filter((o: any) => o.kind === "chat.reaction")).toEqual([]);
		expect(await reactionsIn(env, src.configId, group, messageId)).toEqual([
			expect.objectContaining({ content: "👍", count: 1, selfReacted: true }),
		]);
	});

	it("reaction added then removed offline: no request, nothing on the server", async () => {
		const group = await peer.group(unique("group"));
		const messageId = await peer.post(group, unique("text"));
		const { env, src } = await app();
		await env.chat.loadOlder(src, group);
		const mark = proxy.calls.length;
		setOnline(false);
		await env.chat.react(src, group, sent(messageId), "❤️", true);
		expect(await reactionsIn(env, src.configId, group, messageId)).toEqual([
			expect.objectContaining({ content: "❤️", selfReacted: true }),
		]);
		await env.chat.react(src, group, sent(messageId), "❤️", false);
		expect((await env.db.getOutboxOpsForConfig(src.configId)).filter((o: any) => o.kind === "chat.reaction")).toEqual([]);
		setOnline(true);
		await env.chat.flushAll({ force: true });
		await idle(env, src.configId);
		expect(callsTo(REACTION_ROUTE, mark)).toEqual([]);
		expect(await peer.reactionsOf(messageId)).toEqual([]);
		expect(await reactionsIn(env, src.configId, group, messageId)).toEqual([]);
	});

	it("chat_user's reaction and edit reach the app by the bus, without a reload", async () => {
		const group = await peer.group(unique("group"));
		const { env, src } = await app();
		const applyBus = vi.spyOn(env.chat, "applyBus");
		const delivered = () => applyBus.mock.calls.flatMap(([, notifications]) => notifications);
		const sockets = () => proxy.calls.filter((c) => c.path.startsWith("/websocket")).length;
		const opened = sockets();
		await env.chat.startRealtime(() => nodeTransport());
		await until("the app's websocket", async () => sockets() > opened);
		const messageId = await peer.post(group, unique("before"));
		await until("chat_user's message in the app", () => cached(env, src.configId, group, messageId));
		// The first poll replays the group's creation, which may reload the account once: over before the mark
		await until("no reload for a second", async () => {
			const last = proxy.calls.map((c, i) => [c.path, i] as const).filter(([path]) => RELOAD_ROUTES.includes(path)).at(-1);
			await new Promise((resolve) => setTimeout(resolve, 1000));
			const now = proxy.calls.map((c, i) => [c.path, i] as const).filter(([path]) => RELOAD_ROUTES.includes(path)).at(-1);
			return last?.[1] === now?.[1];
		});
		const mark = proxy.calls.length;
		const inserts = (key: string) => delivered().some((n) => n.message?.type === "mail.record/insert"
			&& JSON.stringify(n.message.payload).includes(key));

		await peer.react(messageId, "🎉", "add");
		const [chip] = await until("chat_user's reaction in the app", async () => {
			const groups = await reactionsIn(env, src.configId, group, messageId);
			return groups.length ? groups : null;
		});
		expect(chip).toMatchObject({ content: "🎉", count: 1, selfReacted: false, partnerIds: [peer.partnerId] });
		expect(inserts('"MessageReactions"')).toBe(true);

		const text = unique("after");
		await peer.edit(messageId, text);
		const edited = await until("chat_user's edit in the app", async () => {
			const m = await cached(env, src.configId, group, messageId);
			return m && bodyText(m.body) === text ? m : null;
		});
		expect(edited.body).toContain("o-mail-Message-edited");
		expect(edited.body).toBe(await peer.bodyOf(messageId));
		expect(inserts(text)).toBe(true);
		for (const path of RELOAD_ROUTES) expect(callsTo(path, mark)).toEqual([]);
	});

	for (const { label, chatModule } of ROUTES) {
		it(`edit of a message with two files ${label}: the text changes, both files stay`, async () => {
			const group = await peer.group(unique("group"));
			const { env, src } = await app({ chatModule });
			expect((await env.chat.features(src.configId)).guardedEdit).toBe(chatModule === "auto");
			const files = [
				await staged(env, src, `${unique("first")}.txt`, filler(1000), "text/plain"),
				await staged(env, src, `${unique("second")}.txt`, filler(2000), "text/plain"),
			];
			const { messageId, clientUuid } = await posted(env, src, group, unique("with-files"), files);
			const before = (await peer.attachmentsOf(messageId)).map((a) => a.id);
			expect(before).toHaveLength(2);

			const mark = proxy.calls.length;
			const text = unique("edited");
			await env.chat.editMessage(src, group, { messageId, clientUuid }, text, EMPTY_MENTIONS);
			await idle(env, src.configId);
			const body = await peer.bodyOf(messageId);
			expect(bodyText(body)).toBe(text);
			expect(body).toContain("o-mail-Message-edited");
			expect((await peer.attachmentsOf(messageId)).map((a) => a.id)).toEqual(before);
			const route = chatModule === "auto" ? MODULE_EDIT_ROUTE : ODOO_EDIT_ROUTE;
			const [edit, ...more] = callsTo(route, mark);
			expect(more).toEqual([]);
			expect(edit.params).toMatchObject({ message_id: messageId, attachment_ids: null });
			expect((await cached(env, src.configId, group, messageId))!.body).toBe(body);
		});
	}

	for (const { label, chatModule } of ROUTES) {
		for (const meanwhile of ["edits", "deletes"] as const) {
			it(`late edit ${label}: chat_user ${meanwhile} it in the browser, the app's edit is refused with its text`, async () => {
				const group = await peer.group(unique("group"));
				// The app as chat_user: the same person on the phone and in the browser
				const { env, src } = await app({ as: "chat", chatModule });
				const { messageId, clientUuid } = await posted(env, src, group, unique("first"));
				const mark = proxy.calls.length;

				setOnline(false);
				const phone = unique("phone");
				await env.chat.editMessage(src, group, { messageId, clientUuid }, phone, EMPTY_MENTIONS);
				const browser = unique("browser");
				if (meanwhile === "edits") await peer.edit(messageId, browser);
				else await peer.deleteMessage(messageId);
				const server = await peer.bodyOf(messageId);

				setOnline(true);
				await env.chat.flushAll({ force: true });
				await idle(env, src.configId);
				// Nothing written over the browser's body
				expect(await peer.bodyOf(messageId)).toBe(server);
				if (meanwhile === "edits") expect(bodyText(server)).toBe(browser);
				else expect(isEmptyMessage(server, (await peer.attachmentsOf(messageId)).length)).toBe(true);
				expect(callsTo(ODOO_EDIT_ROUTE, mark)).toEqual([]);
				expect(callsTo(MODULE_EDIT_ROUTE, mark)).toHaveLength(chatModule === "auto" ? 1 : 0);

				const notices = (await env.chat.notices([src.configId])).filter((n) => n.edit);
				expect(notices).toHaveLength(1);
				expect(notices[0]).toMatchObject({
					reason: "changed",
					edit: { target: { messageId }, text: phone, deleted: meanwhile === "deletes" },
				});
				expect((await env.db.getOutboxOpsForConfig(src.configId)).filter((o: any) => o.kind === "chat.edit" && o.status !== "blocked"))
					.toEqual([]);
				expect((await cached(env, src.configId, group, messageId))!.body).toBe(server);
			});
		}
	}

	it("delete empties the body and removes the files: hidden in the app and for chat_user", async () => {
		const group = await peer.group(unique("group"));
		const { env, src } = await app();
		const names = [`${unique("first")}.txt`, `${unique("second")}.txt`];
		const files = [
			await staged(env, src, names[0], filler(1000), "text/plain"),
			await staged(env, src, names[1], filler(2000), "text/plain"),
		];
		const { messageId, clientUuid } = await posted(env, src, group, unique("doomed"), files);
		const fileIds = (await peer.attachmentsOf(messageId)).map((a) => a.id);
		expect(fileIds).toHaveLength(2);
		const bus = await peer.listen();
		try {
			const mark = proxy.calls.length;
			await env.chat.deleteMessage(src, group, { messageId, clientUuid });
			await idle(env, src.configId);
			const [del, ...more] = callsTo(ODOO_EDIT_ROUTE, mark);
			expect(more).toEqual([]);
			expect(del.params).toMatchObject({ message_id: messageId, body: "", attachment_ids: [], attachment_tokens: [], subject: "" });

			const body = await peer.bodyOf(messageId);
			expect(isEmptyMessage(body, 0)).toBe(true);
			expect(await peer.attachmentsOf(messageId)).toEqual([]);
			expect(await peer.admin.searchRead("ir.attachment", [["id", "in", fileIds]], ["id"])).toEqual([]);
			const shown = (await cached(env, src.configId, group, messageId))!;
			const kept = (await env.chat.repo.attachmentsOf(src.configId, group, [messageId], [])).get(`m${messageId}`) ?? [];
			expect(isEmptyMessage(shown.body, kept.length)).toBe(true);

			// chat_user's thread: the server's comment emptied, and their bus told
			const [theirs] = (await peer.comments(group, ["id", "body", "attachment_ids"])).filter((m) => m.id === messageId);
			expect(isEmptyMessage(theirs.body || "", theirs.attachment_ids.length)).toBe(true);
			await until("the emptied message on chat_user's bus", async () => bus.notifications.some((n) =>
				n.message?.type === "mail.record/insert"
				&& (n.message.payload?.["mail.message"] ?? []).some((m: any) => m.id === messageId && isEmptyMessage(m.body || "", 0))));
		} finally {
			bus.close();
		}
	});

	it("reply: the server keeps the parent, the app caches it", async () => {
		const group = await peer.group(unique("group"));
		const parent = await peer.post(group, unique("question"));
		const { env, src } = await app();
		await env.chat.loadOlder(src, group);
		const message = await env.chat.send(src, group, unique("answer"), [], { replyTo: sent(parent) });
		await idle(env, src.configId);
		const reply = await mine(env, src.configId, group, message.clientUuid);
		expect(reply.status).toBe("sent");
		expect(await peer.parentOf(reply.messageId!)).toBe(parent);
		expect(reply.parentId).toBe(parent);
		const [post] = callsTo("/mail/message/post").filter((c) => c.params?.post_data?.parent_id === parent);
		expect(post).toBeTruthy();
	});

	it("reply queued offline whose parent chat_user deletes: posted on it, quoted as deleted", async () => {
		const group = await peer.group(unique("group"));
		const parent = await peer.post(group, unique("soon-gone"));
		const { env, src } = await app();
		await env.chat.loadOlder(src, group);
		setOnline(false);
		const message = await env.chat.send(src, group, unique("answer"), [], { replyTo: sent(parent) });
		await peer.deleteMessage(parent);
		setOnline(true);
		await env.chat.flushAll({ force: true });
		await idle(env, src.configId);
		const reply = await mine(env, src.configId, group, message.clientUuid);
		expect(reply.status).toBe("sent");
		// An emptied parent still exists: Odoo keeps the link, the thread quotes it as deleted
		expect(await peer.parentOf(reply.messageId!)).toBe(parent);
		expect(reply.parentId).toBe(parent);
		const quoted = (await cached(env, src.configId, group, parent))!;
		expect(isEmptyMessage(quoted.body, 0)).toBe(true);
	});

	it("reply to a message of another conversation: posted plain, no error", async () => {
		const here = await peer.group(unique("here"));
		const elsewhere = await peer.group(unique("elsewhere"));
		const parent = await peer.post(elsewhere, unique("other"));
		const { env, src } = await app();
		await env.chat.loadOlder(src, elsewhere);
		await env.chat.loadOlder(src, here);
		const text = unique("answer");
		const message = await env.chat.send(src, here, text, [], { replyTo: sent(parent) });
		await idle(env, src.configId);
		const reply = await mine(env, src.configId, here, message.clientUuid);
		expect(reply.status).toBe("sent");
		expect(await peer.parentOf(reply.messageId!)).toBe(false);
		expect(reply.parentId ?? null).toBeNull();
		expect(bodyText(await peer.bodyOf(reply.messageId!))).toBe(text);
		expect((await env.chat.notices([src.configId])).filter((n) => n.message?.messageId === reply.messageId)).toEqual([]);
	});
});
