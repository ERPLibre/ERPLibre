/**
 * What rings follows Odoo's own settings, changed from the app as from the
 * browser, against a real Odoo 18 (module erplibre_mobile_chat 1.6) and the
 * run's own ntfy (PushScene): the general channel setting
 * (res.users.settings.channel_notifications, « mentions » stored false) and
 * a channel's setting (its member's custom_notifications), sent by the
 * app's outbox and followed from the browser on the app's bus; Odoo then
 * pushes no plain post of a channel set to mentions, and pushes a group
 * whatever its setting. The browser mode the app sets marks its device
 * (mode and payload v 2); the 1.5 route marks quiet and keeps the payload
 * v 1. The payload v 2 says whether the recipient is mentioned (a mention,
 * @everyone) and whether a browser of theirs is active (poll and activity
 * recent): a browser whose last presence is over 65 s old is not, its
 * websocket open or not.
 *
 * Settings, presence and admin's chat with chat_user are shared with the
 * other files, which run beside this one as admin: every case but the
 * browser mode signs the app in as the file's own user, created once (a
 * user created while other files create theirs may meet Odoo's
 * serialization failure).
 */
import { eachVersionFrom, nodeTransport, unique, until } from "./harness";
import type { Target } from "./harness";
import { ChatPeer } from "./chatPeer";
import { PushScene } from "./chatPushScene";

/** A browser activity older than the module's activity window (BROWSER_ACTIVE_S, 5 min). */
const INACTIVE_MS = 6 * 60_000;
/**
 * A silence after which the module holds a browser closed: its last
 * presence older than Odoo's DISCONNECTION_TIMER (65 s), plus a margin. A
 * browser under module 1.6's client patch sends one every 60 s while open.
 */
const BROWSER_CLOSED_MS = 70_000;

eachVersionFrom(18, "chat push preferences", (target: Target) => {
	if (!target.ntfy) {
		describe.skip("ntfy absent: notification tests skipped", () => {
			it("the ntfy command is not installed", () => {});
		});
		return;
	}
	const ntfy = target.ntfy;
	let peer: ChatPeer;
	const scene = new PushScene(target, ntfy, () => peer);

	/** The file's own internal user: every case sets the settings it relies on, and drops its device at its end. */
	let user: Awaited<ReturnType<ChatPeer["createUser"]>>;

	beforeAll(async () => {
		peer = await ChatPeer.open(target);
		const login = unique("preferences");
		user = await peer.createUser(`MS ${login}`, login);
	});
	afterEach(() => scene.end());

	it("the general setting set in the app reaches Odoo", async () => {
		const { env, src } = await scene.app({ as: user.login });
		for (const [value, stored] of [["all", "all"], ["no_notif", "no_notif"], ["mentions", false]] as const) {
			await env.chat.setGlobalNotify(src.configId, value);
			expect((await env.chat.repo.sourceState(src.configId)).channelNotifications).toBe(value);
			await until(`the general setting ${value} on the server`, async () =>
				(await peer.generalNotifyOf(user.login.login)) === stored);
		}
		expect(await env.db.getOutboxOpsForConfig(src.configId)).toEqual([]);
	});

	it("the general setting changed in the browser reaches the app", async () => {
		const { env, src } = await scene.app({ as: user.login });
		await env.chat.startRealtime(() => nodeTransport());
		const browser = await peer.webSession(user.login);
		for (const [value, shown] of [["no_notif", "no_notif"], [false, "mentions"], ["all", "all"]] as const) {
			await peer.setGeneralNotify(browser, value);
			await until(`the general setting ${shown} in the app`, async () =>
				(await env.chat.repo.sourceState(src.configId)).channelNotifications === shown);
		}
	});

	it("a channel's setting changed in the browser reaches the app", async () => {
		const channel = await peer.channel(unique("canal"), { invite: false, partners: [user.partnerId] });
		const { env, src } = await scene.app({ as: user.login });
		expect((await env.chat.repo.channel(src.configId, channel))?.customNotifications ?? null).toBeNull();
		await env.chat.startRealtime(() => nodeTransport());
		const browser = await peer.webSession(user.login);
		for (const value of ["no_notif", "all"] as const) {
			await peer.setChannelNotify(browser, channel, value);
			await until(`the channel's setting ${value} in the app`, async () =>
				(await env.chat.repo.channel(src.configId, channel))?.customNotifications === value);
		}
	});

	it("a channel set to mentions in the app pushes no plain post", async () => {
		const channel = await peer.channel(unique("canal"), { invite: false, partners: [user.partnerId] });
		const { env, src } = await scene.markedApp("phone", { as: user.login });
		const keys = env.pushNative.keysOf(src.configId);
		// Odoo's default (mentions) pushes no plain post either: « all » first shows a plain post is pushed
		await env.chat.setNotify(src.configId, channel, "all");
		await until("the channel at all on the server", async () =>
			(await peer.customNotifyOf(user.login.login, channel)) === "all");
		const before = unique("avant mentions");
		await peer.post(channel, before);
		await scene.pushed(keys, before);

		await env.chat.setNotify(src.configId, channel, "mentions");
		await until("the channel at mentions on the server", async () =>
			(await peer.customNotifyOf(user.login.login, channel)) === "mentions");
		const plain = unique("sans mention");
		await peer.post(channel, plain);
		const mention = unique("avec mention");
		await peer.mention(channel, user.partnerId, mention);
		// Odoo pushes each post before answering it: once the later mention is on the topic, the plain post would be too
		await scene.pushed(keys, mention);
		expect((await scene.payloads(keys)).some((p) => p.payload.options?.body.includes(plain))).toBe(false);
	});

	it("a group ignores the channel setting", async () => {
		const group = await peer.group(unique("groupe"), user.partnerId);
		const { env, src } = await scene.markedApp("phone", { as: user.login });
		const keys = env.pushNative.keysOf(src.configId);
		// The app offers mute only for a group; the browser can still write the setting
		await expect(env.chat.setNotify(src.configId, group, "no_notif")).rejects.toThrow(/Only a channel takes Odoo's notification setting/);
		await peer.setChannelNotify(await peer.webSession(user.login), group, "no_notif");
		expect(await peer.customNotifyOf(user.login.login, group)).toBe("no_notif");
		const text = unique("groupe malgré le réglage");
		await peer.post(group, text);
		await scene.pushed(keys, text);
	});

	it("the browser mode set in the app marks the device", async () => {
		const { env, row, device } = await scene.markedApp();
		expect(await peer.appDevice(row.endpoint!)).toEqual({ id: device.id, app: true, mode: "wait", payloadV: 2 });
		for (const mode of ["quiet", "ring", "wait"] as const) {
			await env.push.setBrowserMode(mode);
			await until(`the device marked ${mode}`, async () => {
				const found = await peer.appDevice(row.endpoint!);
				return found?.mode === mode ? found : null;
			});
			expect(await peer.appDevice(row.endpoint!)).toEqual({ id: device.id, app: true, mode, payloadV: 2 });
			expect(env.push.markOwed(row.configId)).toBe(false);
		}
	});

	it("a 1.5 route call marks quiet and keeps v1", async () => {
		const { env, src, row, device } = await scene.markedApp("phone", { as: user.login });
		const keys = env.pushNative.keysOf(src.configId);
		const session = env.pushNative.sessions.get(src.configId)!;
		await peer.markDeviceQuiet(session, row.endpoint!, true);
		expect(await peer.appDevice(row.endpoint!)).toEqual({ id: device.id, app: true, mode: "quiet", payloadV: 1 });
		await peer.markDeviceQuiet(session, row.endpoint!, false);
		expect(await peer.appDevice(row.endpoint!)).toEqual({ id: device.id, app: true, mode: "ring", payloadV: 1 });
		// A chat of the user's own: admin's chat with chat_user belongs to the other files
		const chat = await peer.chat(user.partnerId);
		const text = unique("appareil 1.5");
		const id = await peer.post(chat, text);
		const [one] = await scene.pushed(keys, text);
		expect(one.payload.options!.data).toEqual({
			model: "discuss.channel",
			res_id: chat,
			action: "mail.action_discuss",
			erplibre: { v: 1, message_id: id, channel_type: "chat" },
		});
	});

	it("mentioned and browser_online in the payload", async () => {
		const channel = await peer.channel(unique("canal"), { invite: false, partners: [user.partnerId] });
		const { env, src, row } = await scene.markedApp("phone", { as: user.login });
		const keys = env.pushNative.keysOf(src.configId);
		expect(await peer.appDevice(row.endpoint!)).toMatchObject({ mode: "wait", payloadV: 2 });
		// A plain post reaches a member whose channel is at all
		await peer.setChannelNotify(await peer.webSession(user.login), channel, "all");
		const flagsOf = async (text: string) => (await scene.pushed(keys, text))[0].payload.options!.data.erplibre;

		const browser = await peer.browserSession(user.login);
		try {
			await browser.presence(0);
			const mention = unique("mention");
			const mentionId = await peer.mention(channel, user.partnerId, mention);
			const everyone = unique("tout le monde");
			const everyoneId = await peer.post(channel, everyone, { everyone: true });
			const plain = unique("simple");
			const plainId = await peer.post(channel, plain);
			for (const [text, id, mentioned] of [[mention, mentionId, true], [everyone, everyoneId, true], [plain, plainId, false]] as const) {
				expect(await flagsOf(text)).toEqual({ v: 2, message_id: id, channel_type: "channel", mentioned, browser_online: true });
			}

			await browser.presence(INACTIVE_MS);
			const away = unique("navigateur inactif");
			const awayId = await peer.post(channel, away);
			expect(await flagsOf(away)).toEqual({
				v: 2, message_id: awayId, channel_type: "channel", mentioned: false, browser_online: false,
			});
		} finally {
			browser.close();
		}
	});

	it("a browser silent past 65 s is not online", async () => {
		const { env, src, row } = await scene.markedApp("phone", { as: user.login });
		const keys = env.pushNative.keysOf(src.configId);
		expect(await peer.appDevice(row.endpoint!)).toMatchObject({ mode: "wait", payloadV: 2 });
		const chat = await peer.chat(user.partnerId);
		const onlineOf = async (text: string) => (await scene.pushed(keys, text))[0].payload.options!.data.erplibre.browser_online;

		// The websocket stays open with no presence sent: only the age of the last one tells a closed browser
		const browser = await peer.browserSession(user.login);
		try {
			await browser.presence(0);
			const sent = performance.now();
			const open = unique("navigateur ouvert");
			await peer.post(chat, open);
			expect(await onlineOf(open)).toBe(true);

			await new Promise((resolve) => setTimeout(resolve, Math.max(0, sent + BROWSER_CLOSED_MS - performance.now())));
			const closed = unique("navigateur muet");
			await peer.post(chat, closed);
			expect(await onlineOf(closed)).toBe(false);
		} finally {
			browser.close();
		}
	}, BROWSER_CLOSED_MS + 60_000);
});
