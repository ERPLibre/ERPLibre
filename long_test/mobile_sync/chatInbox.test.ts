/**
 * Odoo's inbox from the app against a real Odoo 18, the app as inbox_user
 * (notified in Odoo, an email address, project's user rights, a member of
 * « ms chat ») through the proxy, chat_user at the other end: a mention in
 * « ms chat », a comment on a task inbox_user follows and an assignment
 * fill the three kinds; a server search leaves the mention unread; one
 * item marked read, then « Tout marquer comme lu » tapped offline while a
 * newer mention arrives, which stays unread. A reply in a task's chatter,
 * with a photo, is an internal note that emails no one, or a message to
 * the followers that emails the one notified by email; a reply whose
 * upload answer then post answer are lost posts once with one attachment,
 * on the module's routes and on Odoo's. With the app's bus open, two
 * comments on a followed task and a mention reach its inbox with no page
 * read. A user notified by email, made by the file, switches to the inbox
 * from the app. Every outcome is read
 * back from the server.
 *
 * The tests run in order: the first fills the inbox the next three read
 * and mark. inbox_user is this file's alone; the follower notified by
 * email is a user the file makes, as chat_user's notification settings
 * change under chatWriting.test.ts. The test servers' SMTP refuses every
 * connection, so an email stays as its mail.mail (in exception) for the
 * count. Quiet windows pass on a faked Date; nothing here changes a
 * server-wide setting, so the file runs with the others.
 */
import {
	appFor, eachVersionFrom, fixture, mailboxKindOf, nodeTransport, setOnline, stageChatFile, unique, until, EMPTY_MENTIONS,
} from "./harness";
import type { ChatMailboxItem, Login, SyncEnv } from "./harness";
import { ChatPeer } from "./chatPeer";
import { FaultProxy } from "./faultProxy";
import { PHOTO, QUIET_WINDOW_PASSED_MS, ROUTES } from "./chatAttachmentScene";

const CHANNEL = "discuss.channel";
const TASK = "project.task";

eachVersionFrom(18, "chat inbox", (target) => {
	let proxy: FaultProxy;
	let peer: ChatPeer;
	let inbox: Login;
	let inboxPartner: number;
	let msChat: number;
	let project: number;
	/** A user notified by email, follower of the tasks replied on. */
	let followerPartner: number;
	let env: SyncEnv | null = null;
	/** The three items of the first test: chat_user's mention, comment and admin's assignment. */
	const seeded: { mention?: number; comment?: number; assignment?: number; word?: string } = {};

	beforeAll(async () => {
		proxy = await FaultProxy.start(target);
		peer = await ChatPeer.open(target);
		inbox = target.inbox!;
		inboxPartner = await peer.partnerOf(inbox.login);
		const [group] = await peer.user.searchRead(CHANNEL, [["name", "=", "ms chat"], ["channel_type", "=", "group"]], ["id"]);
		msChat = group.id;
		project = await peer.admin.create("project.project", { name: unique("project") });
		const login = unique("follower");
		const uid = await peer.admin.create("res.users", {
			name: "MS Abonne", login, password: login, email: `${login}@example.com`, notification_type: "email",
		});
		followerPartner = (await peer.admin.read("res.users", uid, ["partner_id"])).partner_id[0];
		expect(await peer.notificationTypeOf(login)).toBe("email");
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
	const idle = (e: SyncEnv, configId: string) => e.chat.queue.whenIdle(configId);

	/** The app as `as` (inbox_user by default) through the proxy, its chat source and inbox loaded. */
	async function app(opts: { as?: Login; chatModule?: "auto" | "ignore" } = {}) {
		const started = await appFor(proxy.via(target), opts.as ?? "inbox", { chatModule: opts.chatModule });
		env = started;
		const [src] = await started.chat.sources();
		await started.chat.load(src);
		const page = await started.chat.inbox.refresh(src, "inbox");
		expect(page.offline).toBe(false);
		return { env: started, src };
	}

	/** The cached inbox item of a message; fails when the phone does not hold it. */
	async function itemOf(e: SyncEnv, configId: string, messageId: number): Promise<ChatMailboxItem> {
		const item = await e.chat.repo.mailboxItem(configId, messageId);
		expect(item).not.toBeNull();
		return item!;
	}

	/**
	 * A task of the file's project followed by inbox_user and by the
	 * follower notified by email, commented by chat_user: the task and the
	 * comment, an inbox item of inbox_user.
	 */
	async function commentedTask(): Promise<{ task: number; comment: number }> {
		const task = await peer.admin.create(TASK, { name: unique("task"), project_id: project });
		await peer.follow(TASK, task, inboxPartner);
		await peer.follow(TASK, task, followerPartner);
		const comment = await peer.postOnRecord(TASK, task, unique("comment"), "mail.mt_comment");
		return { task, comment };
	}

	/** The photo fixture staged as the composer stages a pick, under a name of the run. */
	async function photo(e: SyncEnv, src: any) {
		const name = `${unique("photo")}.jpg`;
		const staged = await stageChatFile(e, src, { name, bytes: fixture(PHOTO), mimetype: "image/jpeg" });
		if ("refused" in staged) throw new Error(`${name} refused at staging`);
		return staged;
	}

	/** The messages of the task whose body holds text, as the server holds them. */
	const repliesOf = async (task: number, text: string) => (await peer.messagesOf(TASK, task)).filter((m) => m.body.includes(text));

	it("a mention, a comment on a followed task and an assignment fill the three kinds", async () => {
		seeded.word = unique("mention");
		seeded.mention = await peer.mention(msChat, inboxPartner, `@MS Boite ${seeded.word}`);
		seeded.comment = (await commentedTask()).comment;
		const assigned = await peer.admin.create(TASK, { name: unique("assigned"), project_id: project });
		await peer.assignTask(assigned, inbox.login);
		const [notice] = await peer.admin.searchRead(
			"mail.message",
			[["model", "=", TASK], ["res_id", "=", assigned], ["message_type", "=", "user_notification"]],
			["id"],
		);
		seeded.assignment = notice.id;
		for (const id of [seeded.mention, seeded.comment, seeded.assignment]) {
			expect(await peer.needactionOf(inbox.login, id)).toMatchObject({ notification_type: "inbox", is_read: false });
		}

		const { env, src } = await app();
		const items = await env.chat.inbox.items([src.configId], "inbox");
		const kindOf = (id: number) => {
			const item = items.find((i) => i.messageId === id);
			return item ? mailboxKindOf(item) : null;
		};
		expect([kindOf(seeded.mention), kindOf(seeded.comment), kindOf(seeded.assignment)]).toEqual(["mention", "record", "assignment"]);
		expect(items.find((i) => i.messageId === seeded.mention)).toMatchObject({ threadModel: CHANNEL, threadId: msChat, needaction: true });
		expect(items.find((i) => i.messageId === seeded.assignment)).toMatchObject({ threadModel: TASK, threadId: assigned });
	});

	it("a server search on the mentioned word leaves the mention unread", async () => {
		const { env, src } = await app();
		const found = await env.chat.search.server(src, seeded.word!);
		expect(found.hits.map((h) => h.messageId)).toEqual([seeded.mention]);
		expect(await peer.needactionOf(inbox.login, seeded.mention!)).toMatchObject({ is_read: false });
		expect((await itemOf(env, src.configId, seeded.mention!)).needaction).toBe(true);
	});

	it("one item marked read: is_read on the server", async () => {
		const { env, src } = await app();
		await env.chat.markDone(src, [seeded.mention!]);
		await idle(env, src.configId);
		expect(await peer.needactionOf(inbox.login, seeded.mention!)).toMatchObject({ is_read: true });
		expect(await itemOf(env, src.configId, seeded.mention!)).toMatchObject({ needaction: false, history: true });
		expect(await env.db.getOutboxOpsForConfig(src.configId)).toEqual([]);
	});

	it("mark all tapped offline while chat_user mentions again: the newer mention stays unread", async () => {
		const { env, src } = await app();
		setOnline(false);
		await env.chat.markAllDone(src);
		const newer = await peer.mention(msChat, inboxPartner, `@MS Boite ${unique("newer")}`);
		setOnline(true);
		await env.chat.flushAll();
		await idle(env, src.configId);
		for (const id of [seeded.comment!, seeded.assignment!]) {
			expect(await peer.needactionOf(inbox.login, id)).toMatchObject({ is_read: true });
		}
		expect(await peer.needactionOf(inbox.login, newer)).toMatchObject({ is_read: false });
		expect(await env.db.getOutboxOpsForConfig(src.configId)).toEqual([]);
	});

	it("a reply as a note with a photo: one note holding the photo, no email", async () => {
		const { task, comment } = await commentedTask();
		const { env, src } = await app();
		const item = await itemOf(env, src.configId, comment);
		const mails = await peer.mailCountFor(followerPartner);
		const file = await photo(env, src);
		const text = unique("note");
		await env.chat.replyOnRecord(src, item, text, EMPTY_MENTIONS, [file], true);
		await idle(env, src.configId);
		const [reply, ...more] = await repliesOf(task, text);
		expect(more).toEqual([]);
		expect(reply).toMatchObject({ messageType: "comment", subtype: "mail.mt_note" });
		const atts = await peer.admin.searchRead("ir.attachment", [["id", "in", reply.attachmentIds]], ["name", "res_model", "res_id"]);
		expect(atts).toEqual([expect.objectContaining({ name: file.name, res_model: TASK, res_id: task })]);
		expect(await peer.mailCountFor(followerPartner)).toBe(mails);
		expect(await env.db.getOutboxOpsForConfig(src.configId)).toEqual([]);
	});

	it("a reply as a message with a photo: one comment holding the photo, one email to the follower", async () => {
		const { task, comment } = await commentedTask();
		const { env, src } = await app();
		const item = await itemOf(env, src.configId, comment);
		const mails = await peer.mailCountFor(followerPartner);
		const file = await photo(env, src);
		const text = unique("message");
		await env.chat.replyOnRecord(src, item, text, EMPTY_MENTIONS, [file], false);
		await idle(env, src.configId);
		const [reply, ...more] = await repliesOf(task, text);
		expect(more).toEqual([]);
		expect(reply).toMatchObject({ messageType: "comment", subtype: "mail.mt_comment" });
		const atts = await peer.admin.searchRead("ir.attachment", [["id", "in", reply.attachmentIds]], ["name", "res_model", "res_id"]);
		expect(atts).toEqual([expect.objectContaining({ name: file.name, res_model: TASK, res_id: task })]);
		expect(await peer.mailCountFor(followerPartner)).toBe(mails + 1);
	});

	for (const { label, chatModule, route } of ROUTES) {
		it(`a reply with a photo whose upload answer, then post answer, are lost ${label}: one message, one attachment`, async () => {
			vi.useFakeTimers({ toFake: ["Date"] });
			const { task, comment } = await commentedTask();
			const { env, src } = await app({ chatModule });
			expect((await env.chat.features(src.configId)).idempotentRecordPost).toBe(chatModule === "auto");
			const item = await itemOf(env, src.configId, comment);
			const file = await photo(env, src);
			const text = unique("lost");
			proxy.loseResponseOf((c) => c.path === route);
			await env.chat.replyOnRecord(src, item, text, EMPTY_MENTIONS, [file], true);
			await idle(env, src.configId);
			expect(await repliesOf(task, text)).toEqual([]);

			proxy.loseResponseOf((c) => c.path === "/mail/message/post");
			later(QUIET_WINDOW_PASSED_MS);
			await env.chat.flushAll();
			await idle(env, src.configId);
			expect(await repliesOf(task, text)).toHaveLength(1);
			expect(await env.db.getOutboxOpsForConfig(src.configId)).not.toEqual([]);

			later(QUIET_WINDOW_PASSED_MS);
			await env.chat.flushAll();
			await idle(env, src.configId);
			const [reply, ...more] = await repliesOf(task, text);
			expect(more).toEqual([]);
			const named = await peer.admin.searchRead("ir.attachment", [["name", "=", file.name]], ["id", "res_model", "res_id"]);
			expect(named).toEqual([expect.objectContaining({ res_model: TASK, res_id: task })]);
			expect(reply.attachmentIds).toEqual([named[0].id]);
			expect(await env.db.getOutboxOpsForConfig(src.configId)).toEqual([]);
		});
	}

	it("two comments on a followed task and a mention reach the inbox by the bus, without a page read", async () => {
		const { env, src } = await app();
		const sockets = () => proxy.calls.filter((c) => c.path.startsWith("/websocket")).length;
		const opened = sockets();
		await env.chat.startRealtime(() => nodeTransport());
		await until("the app's websocket", async () => sockets() > opened);
		const { task, comment } = await commentedTask();
		const second = await peer.postOnRecord(TASK, task, unique("comment"), "mail.mt_comment");
		const mention = await peer.mention(msChat, inboxPartner, `@MS Boite ${unique("live")}`);
		for (const id of [mention, comment, second]) {
			await until(`inbox item ${id} by the bus`, async () => (await env.chat.repo.mailboxItem(src.configId, id))?.needaction);
		}
	});

	it("a user notified by email sees why, switches to the inbox, and the server reads inbox", async () => {
		const login = unique("emailed");
		await peer.admin.create("res.users", {
			name: "MS Courriel", login, password: login, email: `${login}@example.com`, notification_type: "email",
		});
		expect(await peer.notificationTypeOf(login)).toBe("email");
		const { env, src } = await app({ as: { login, password: login } });
		expect((await env.chat.repo.sourceState(src.configId)).notificationType).toBe("email");
		expect(await env.chat.switchToInbox(src)).toBe("done");
		expect(await peer.notificationTypeOf(login)).toBe("inbox");
		expect((await env.chat.repo.sourceState(src.configId)).notificationType).toBe("inbox");
	});
});
