/**
 * Module erplibre_mobile_chat 1.5 against a real Odoo 18 and the run's own
 * ntfy (PushScene): a device the app marks gets the message id and the
 * channel type in Odoo's payload, sent after commit and accepted on ntfy's
 * 200; a device the module does not know (the app with chatModule
 * "ignore") gets Odoo's own payload; a read in a browser, the author's own
 * post and an inbox item done send a control push to the marked device
 * only; a device marked quiet is not pushed while a browser of its user is
 * online, and the app's own bus never counts as one.
 *
 * The inbox and quiet cases sign the app in as a user of their own (a
 * browser presence and an inbox are per user, and other files run beside
 * this one as admin).
 */
import { readFileSync, statSync } from "node:fs";
import { eachVersionFrom, nodeTransport, unique, until } from "./harness";
import type { Target } from "./harness";
import { ChatPeer } from "./chatPeer";
import { PushScene } from "./chatPushScene";

/** The time left to a push or a log line that must not come, once what comes before it arrived. */
const SILENCE_MS = 5000;
/** A browser activity older than the module's away timer (30 min). */
const AWAY_MS = 31 * 60_000;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

eachVersionFrom(18, "chat push, module 1.5", (target: Target) => {
	if (!target.ntfy) {
		describe.skip("ntfy absent: notification tests skipped", () => {
			it("the ntfy command is not installed", () => {});
		});
		return;
	}
	const ntfy = target.ntfy;
	let peer: ChatPeer;
	let chatName: string;
	const scene = new PushScene(target, ntfy, () => peer);

	beforeAll(async () => {
		peer = await ChatPeer.open(target);
		chatName = (await peer.admin.read("res.partner", peer.partnerId, ["name"])).name;
	});
	afterEach(() => scene.end());

	it("a marked device gets the message id and channel type", async () => {
		const { env, src } = await scene.markedApp();
		const keys = env.pushNative.keysOf(src.configId);
		const chat = await peer.chat(peer.adminPartnerId);
		const group = await peer.group(unique("groupe"));
		const channel = await peer.channel(unique("canal"));
		const inChat = unique("bonjour du module");
		const inGroup = unique("réunion jeudi à 10 h");
		const inChannel = unique("peux-tu relire le devis");
		const chatId = await peer.post(chat, inChat);
		const groupId = await peer.post(group, inGroup);
		const channelId = await peer.mention(channel, peer.adminPartnerId, inChannel);
		for (const [text, resId, messageId, type] of [
			[inChat, chat, chatId, "chat"],
			[inGroup, group, groupId, "group"],
			[inChannel, channel, channelId, "channel"],
		] as const) {
			const [one] = await scene.pushed(keys, text);
			expect(one.payload.options!.data).toEqual({
				model: "discuss.channel",
				res_id: resId,
				action: "mail.action_discuss",
				erplibre: { v: 1, message_id: messageId, channel_type: type },
			});
		}
	});

	it("an unmarked device gets Odoo's own payload", async () => {
		const { env, src, row } = await scene.linked("phone", { chatModule: "ignore" });
		expect(await peer.appDevice(row.endpoint!)).toMatchObject({ app: false, quiet: false });
		const keys = env.pushNative.keysOf(src.configId);
		const chat = await peer.chat(peer.adminPartnerId);
		const text = unique("sans le module");
		await peer.post(chat, text);
		const [one] = await scene.pushed(keys, text);
		expect(one.payload).toEqual({
			title: chatName,
			options: {
				icon: expect.any(String),
				body: text,
				data: { model: "discuss.channel", res_id: chat, action: "mail.action_discuss" },
			},
		});
	});

	const logName = "a marked device's push leaves no failed push line in Odoo's log";
	(target.log ? it : it.skip)(target.log ? logName : `${logName}: skipped, targets.json gives no server log`, async () => {
		const log = target.log!;
		const marked = await scene.markedApp();
		const plain = await scene.linked("other", { chatModule: "ignore" });
		const markedKeys = marked.env.pushNative.keysOf(marked.src.configId);
		const plainKeys = plain.env.pushNative.keysOf(plain.src.configId);
		const from = statSync(log).size;
		const since = () => readFileSync(log).subarray(from).toString("utf8");
		const text = unique("journal propre");
		await peer.post(await peer.chat(peer.adminPartnerId), text);
		await scene.pushed(markedKeys, text);
		await scene.pushed(plainKeys, text);
		// Odoo's own sender takes ntfy's 200 for a failure: the unmarked device shows the check sees one
		await until("Odoo's warning for the unmarked device", async () =>
			since().includes(`Failed push notification ${plain.row.endpoint} 200`));
		await sleep(SILENCE_MS);
		const lines = since();
		expect(lines).not.toContain(marked.row.endpoint!);
		expect(lines).not.toContain(`App push to device ${marked.device.id} `);
	});

	it("reading in the browser sends a read push to the app device only", async () => {
		const marked = await scene.markedApp();
		const other = await scene.linked("other", { chatModule: "ignore" });
		const markedKeys = marked.env.pushNative.keysOf(marked.src.configId);
		const otherKeys = other.env.pushNative.keysOf(other.src.configId);
		const chat = await peer.chat(peer.adminPartnerId);
		const text = unique("lu au navigateur");
		const id = await peer.post(chat, text);
		await scene.pushed(markedKeys, text);
		await scene.pushed(otherKeys, text);
		const browser = await peer.browserSession(target.admin);
		try {
			await browser.markRead(chat, id);
		} finally {
			browser.close();
		}
		const read = await scene.control(markedKeys, "the read push", (c) => c.type === "read" && c.channel_id === chat);
		expect(read).toEqual({ v: 1, type: "read", channel_id: chat, last_message_id: id });
		await sleep(SILENCE_MS);
		expect(await scene.controls(otherKeys, () => true)).toEqual([]);
	});

	it("the author's own post in the browser sends a read push", async () => {
		const { env, src } = await scene.markedApp();
		const keys = env.pushNative.keysOf(src.configId);
		const chat = await peer.chat(peer.adminPartnerId);
		const browser = await peer.browserSession(target.admin);
		let id: number;
		try {
			id = await browser.post(chat, unique("écrit au navigateur"));
		} finally {
			browser.close();
		}
		const read = await scene.control(keys, "the read push of the author's post", (c) =>
			c.type === "read" && c.channel_id === chat && c.last_message_id === id);
		expect(read).toEqual({ v: 1, type: "read", channel_id: chat, last_message_id: id });
	});

	it("an inbox read sends inbox_done with the record", async () => {
		const login = unique("boite");
		const user = await peer.createUser(`MS ${login}`, login, { inbox: true });
		const { env, src } = await scene.markedApp("phone", { as: user.login });
		const keys = env.pushNative.keysOf(src.configId);
		const project = await peer.admin.create("project.project", { name: unique("projet"), privacy_visibility: "employees" });
		const task = await peer.admin.create("project.task", { name: unique("tâche"), project_id: project });
		await peer.follow("project.task", task, user.partnerId);
		const text = unique("le client a confirmé la date");
		const message = await peer.postOnRecordAsInbox("project.task", task, text);
		await scene.pushed(keys, text);
		expect(await peer.needactionOf(login, message)).toEqual(expect.objectContaining({ notification_type: "inbox", is_read: false }));
		const browser = await peer.browserSession(user.login);
		try {
			await browser.setMessageDone(message);
		} finally {
			browser.close();
		}
		const done = await scene.control(keys, "the inbox_done push", (c) => c.type === "inbox_done");
		expect(done).toEqual({ v: 1, type: "inbox_done", threads: [["project.task", task]] });
	});

	it("quiet while a browser is online", async () => {
		const login = unique("discret");
		const user = await peer.createUser(`MS ${login}`, login);
		const { env, src, row, device } = await scene.markedApp("phone", { as: user.login });
		const keys = env.pushNative.keysOf(src.configId);
		// The app's own session marks it: the device keeps the hash of the app's bus
		await peer.markDeviceQuiet(env.pushNative.sessions.get(src.configId)!, row.endpoint!, true);
		expect(await peer.appDevice(row.endpoint!)).toEqual({ id: device.id, app: true, quiet: true });
		const chat = await peer.chat(user.partnerId);

		const browser = await peer.browserSession(user.login);
		try {
			await browser.presence(0);
			const online = unique("navigateur actif");
			await peer.post(chat, online);
			await sleep(SILENCE_MS);
			expect((await scene.payloads(keys)).some((p) => p.payload.options?.body.includes(online))).toBe(false);

			await browser.presence(AWAY_MS);
			const away = unique("navigateur absent");
			await peer.post(chat, away);
			await scene.pushed(keys, away);
		} finally {
			browser.close();
		}

		// The browser's poll is still recent: had the app's bus counted as a browser, its activity of now would silence the phone
		const before = await peer.browserPresenceOf(login);
		// Odoo writes a poll to the second: the app's must fall in a later one to be seen
		await sleep(1100);
		await env.chat.startRealtime(() => nodeTransport());
		await until("the app's bus presence", async () =>
			(await peer.browserPresenceOf(login)).lastPoll !== before.lastPoll);
		const after = await peer.browserPresenceOf(login);
		expect([after.poll, after.presence]).toEqual([before.poll, before.presence]);
		const appOnly = unique("app seule");
		await peer.post(chat, appOnly);
		await scene.pushed(keys, appOnly);
	});
});
