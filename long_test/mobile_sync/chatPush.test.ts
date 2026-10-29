/**
 * The closed-app chat notifications against a real Odoo 18 and the run's
 * own ntfy (long_test/mobile_sync_ntfy.py), the app as admin, chat_user at
 * the other end (PushScene): what Odoo pushes for a chat, a group, a
 * channel mention and a record comment, what it leaves out (a muted
 * conversation, a channel post without mention), what the phone's token
 * may read, and the device Odoo holds after a removal or a new link. The
 * VAPID wipe, which drops every device of the server, runs alone in
 * chatPushVapid.serial.test.ts.
 */
import { dirname } from "node:path";
import { readFileSync } from "node:fs";
import { eachVersionFrom, pollNtfy, unique, until } from "./harness";
import type { Target } from "./harness";
import { ChatPeer } from "./chatPeer";
import { PushScene } from "./chatPushScene";

eachVersionFrom(18, "chat push", (target: Target) => {
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

	it("a chat message reaches ntfy encrypted and decrypts to its conversation", async () => {
		const { env, src } = await scene.linked();
		const keys = env.pushNative.keysOf(src.configId);
		const chat = await peer.chat(peer.adminPartnerId);
		const text = unique("bonjour");
		await peer.post(chat, text);
		const [one] = await scene.pushed(keys, text);
		expect(Buffer.from(one.raw).includes(Buffer.from(text))).toBe(false);
		expect(one.payload).toMatchObject({
			title: chatName,
			options: { body: text, data: { model: "discuss.channel", res_id: chat, action: "mail.action_discuss" } },
		});
		expect((await scene.payloads(keys)).filter((p) => p.payload.options?.body.includes(text))).toHaveLength(1);
	});

	it("a channel mention, a group message and a record comment each have their payload", async () => {
		const { env, src } = await scene.linked();
		const keys = env.pushNative.keysOf(src.configId);
		const groupName = unique("groupe");
		const group = await peer.group(groupName);
		const channelName = unique("canal");
		const channel = await peer.channel(channelName);
		const project = await peer.admin.create("project.project", { name: unique("projet"), privacy_visibility: "employees" });
		const taskName = unique("tâche");
		const task = await peer.admin.create("project.task", { name: taskName, project_id: project });
		await peer.follow("project.task", task, peer.adminPartnerId);
		const inboxName = (await peer.admin.read("res.partner", await peer.partnerOf(target.inbox!.login), ["name"])).name;

		const inGroup = unique("réunion jeudi à 10 h");
		await peer.post(group, inGroup);
		const mention = unique("peux-tu relire le devis");
		await peer.mention(channel, peer.adminPartnerId, mention);
		const unmentioned = unique("sans mention");
		await peer.post(channel, unmentioned);
		const onRecord = unique("le client a confirmé la date");
		const recordMessage = await peer.postOnRecordAsInbox("project.task", task, onRecord);

		const [g] = await scene.pushed(keys, inGroup);
		expect(g.payload).toMatchObject({
			title: `${groupName} - ${chatName}`,
			options: { body: inGroup, data: { model: "discuss.channel", res_id: group, action: "mail.action_discuss" } },
		});
		const [c] = await scene.pushed(keys, mention);
		expect(c.payload).toMatchObject({
			title: `#${channelName} - ${chatName}`,
			options: { data: { model: "discuss.channel", res_id: channel, action: "mail.action_discuss" } },
		});
		const [r] = await scene.pushed(keys, onRecord);
		expect(r.payload.title).toBe(`${inboxName}: ${taskName}`);
		expect(r.payload.options!.body).toBe(onRecord);
		// The app marks its device on module 1.5: its push names the message, no channel type off a channel
		expect(r.payload.options!.data).toEqual({
			model: "project.task", res_id: task, erplibre: { v: 1, message_id: recordMessage, channel_type: null },
		});
		expect((await scene.payloads(keys)).some((p) => p.payload.options?.body.includes(unmentioned))).toBe(false);
	});

	it("a muted conversation is not pushed", async () => {
		const muted = await peer.group(unique("muet"));
		const marker = await peer.group(unique("témoin"));
		const { env, src } = await scene.linked();
		await env.chat.mute(src, muted, -1);
		await until("the mute on the server", async () =>
			(await peer.memberOf(muted, peer.adminPartnerId, ["mute_until_dt"]))?.mute_until_dt || null);
		const keys = env.pushNative.keysOf(src.configId);
		const silent = unique("en sourdine");
		await peer.post(muted, silent);
		const shown = unique("témoin");
		await peer.post(marker, shown);
		await scene.pushed(keys, shown);
		expect((await scene.payloads(keys)).some((p) => p.payload.options?.body.includes(silent))).toBe(false);
	});

	it("the phone token reads only its prefix", async () => {
		const otherTopic = `${ntfy.other.prefix}${"a".repeat(22)}`;
		const refused = await pollNtfy({ url: ntfy.url, token: ntfy.token }, [otherTopic], "all").catch((e) => e);
		expect(refused).toMatchObject({ status: 403 });
		const own = `${ntfy.prefix}${"b".repeat(22)}`;
		expect(await pollNtfy({ url: ntfy.url, token: ntfy.token }, [own], "all")).toEqual([]);
		const anonymousRead = await fetch(`${ntfy.url}/${own}/json?poll=1`);
		expect(anonymousRead.status).toBe(403);
		await anonymousRead.arrayBuffer();
		const outside = await fetch(`${ntfy.url}/zz${ntfy.prefix.slice(2)}`, { method: "POST", body: "x" });
		expect(outside.status).toBe(403);
		await outside.arrayBuffer();
		// Odoo publishes without an identity: anonymous writes on up* are what let it in
		const odooLike = await fetch(`${ntfy.url}/${own}`, { method: "POST", body: "x" });
		expect(odooLike.status).toBe(200);
		await odooLike.arrayBuffer();
	});

	it("removing the account unregisters its device", async () => {
		const { env, src, row } = await scene.linked();
		const keys = env.pushNative.keysOf(src.configId);
		expect(await peer.pushDevices(row.endpoint!)).toBe(1);
		await env.push.forget(src.configId);
		expect(await peer.pushDevices(row.endpoint!)).toBe(0);
		expect(env.pushNative.pending).toEqual([]);
		expect(env.pushNative.sessions.has(src.configId)).toBe(false);
		// A push of another file's post that read the device before its removal may still land: the
		// message posted after the removal is the one that must reach no topic
		const after = unique("après le retrait");
		await peer.post(await peer.chat(peer.adminPartnerId), after);
		env.chat.dispose();
		const marker = await scene.linked();
		const markerKeys = marker.env.pushNative.keysOf(marker.src.configId);
		const witness = unique("témoin du retrait");
		await peer.post(await peer.chat(peer.adminPartnerId), witness);
		await scene.pushed(markerKeys, witness);
		expect((await scene.payloads(keys)).some((p) => p.payload.options?.body.includes(after))).toBe(false);
	});

	it("a new link for the same ntfy moves the account to a new topic", async () => {
		const { env, src, row } = await scene.linked();
		const old = env.pushNative.keysOf(src.configId);
		const moved = await env.push.applyLink([src.configId], scene.link("other"));
		expect(moved).toEqual({ ok: true, reason: null, registered: [src.configId] });
		const now = await env.chat.repo.pushRow(src.configId);
		expect(now.prefix).toBe(ntfy.other.prefix);
		expect(now.topic!.startsWith(ntfy.other.prefix)).toBe(true);
		expect(now.endpoint).not.toBe(row.endpoint);
		expect(now.staleEndpoints).toEqual([]);
		expect(await peer.pushDevices(row.endpoint!)).toBe(0);
		expect(await peer.pushDevices(now.endpoint!)).toBe(1);
		const keys = env.pushNative.keysOf(src.configId);
		expect(Buffer.from(keys.publicKey)).not.toEqual(Buffer.from(old.publicKey));
		const text = unique("au nouveau sujet");
		await peer.post(await peer.chat(peer.adminPartnerId), text);
		await scene.pushed(keys, text);
	});

	it("the harness ntfy is never the user's", () => {
		const url = new URL(ntfy.url);
		expect(url.hostname).toBe("127.0.0.1");
		expect(url.port).not.toBe("8080");
		const run = dirname(process.env.MOBILE_SYNC_TARGETS!);
		expect(ntfy.config.startsWith(`${run}/ntfy/`)).toBe(true);
		const config = readFileSync(ntfy.config, "utf8");
		expect(config).toContain(`listen-http: "127.0.0.1:${url.port}"`);
		expect(config).not.toMatch(/\/etc\/ntfy|\/var\/lib\/ntfy/);
	});
});
