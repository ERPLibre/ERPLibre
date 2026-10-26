/**
 * Chat attachments against a real Odoo 18, the app as admin, chat_user at
 * the other end, each case through the server module's upload route
 * (module 1.2, idempotent on the file's client uuid) and through Odoo's own
 * (chatModule "ignore"): an upload or a post whose answer is lost still
 * gives one attachment in one message; a voice message is a voice for
 * Odoo; a photo keeps its original bytes through the module and is reduced
 * by Odoo's route; « Wi-Fi only » holds an upload off Wi-Fi; an upload in
 * an expired session lands once after the app logs in again; chat_user's
 * image reaches the app as a preview and an original equal to the server's
 * bytes; and loading a conversation of twenty attachments fetches none of
 * their files. The server's size limit has its own file,
 * chatAttachmentsLimit.serial.test.ts.
 *
 * The quiet window (3 minutes) and the retry delays pass on a faked Date:
 * only the app's clock moves, the requests stay real.
 */
import { eachVersionFrom, fixture, setNetwork, stageChatVoice, unique } from "./harness";
import { ChatPeer } from "./chatPeer";
import { FaultProxy } from "./faultProxy";
import type { RpcCall } from "./faultProxy";
import {
	attachmentScene, filler, jpegSize, MODULE_ROUTE, PHOTO, QUIET_WINDOW_PASSED_MS, ROUTES, sha1,
} from "./chatAttachmentScene";

eachVersionFrom(18, "chat attachments", (target) => {
	let proxy: FaultProxy;
	let peer: ChatPeer;

	beforeAll(async () => {
		proxy = await FaultProxy.start(target);
		peer = await ChatPeer.open(target);
	});
	afterEach(() => {
		proxy.down = false;
		vi.useRealTimers();
	});
	afterAll(async () => {
		await proxy.stop();
	});

	const { later, uploadsOf, fileCallsSince, app, staged, idle, withText, named, mine } =
		attachmentScene(target, () => ({ proxy, peer }));

	for (const { label, chatModule, route } of ROUTES) {
		it(`lost upload answer ${label}: one attachment in one message`, async () => {
			vi.useFakeTimers({ toFake: ["Date"] });
			const group = await peer.group(unique("group"));
			const { env, src } = await app({ chatModule });
			expect((await env.chat.features(src.configId)).idempotentUpload).toBe(chatModule === "auto");
			const name = `${unique("lost")}.txt`;
			const text = unique("text");
			const file = await staged(env, src, name, filler(3000), "text/plain");
			proxy.loseResponseOf((c) => c.path === route);
			const sent = await env.chat.send(src, group, text, [file]);
			await idle(env, src.configId);
			// Odoo stored the file, the app never heard back: nothing posted yet
			expect(await named(name)).toHaveLength(1);
			expect(await withText(group, text)).toHaveLength(0);

			later(QUIET_WINDOW_PASSED_MS);
			await env.chat.flushAll();
			await idle(env, src.configId);
			const [att, ...more] = await named(name);
			expect(more).toHaveLength(0);
			expect(att).toMatchObject({ res_model: "discuss.channel", res_id: group });
			const found = await withText(group, text);
			expect(found.map((m) => m.attachment_ids)).toEqual([[att.id]]);
			expect(await mine(env, src.configId, group, sent.clientUuid)).toMatchObject({ status: "sent", messageId: found[0].id });
			const uploads = uploadsOf(route).filter((c) => c.files?.[0]?.filename === name);
			if (chatModule === "auto") {
				// The retry sends the same uuid and the module answers the first attachment
				expect(uploads).toHaveLength(2);
				expect(uploads[1].form!.client_uuid).toBe(uploads[0].form!.client_uuid);
			} else {
				// Odoo's route has no uuid: the retry finds the pending upload instead of sending again
				expect(uploads).toHaveLength(1);
				expect(uploads[0].form).not.toHaveProperty("client_uuid");
			}
		});

		it(`lost post answer with files ${label}: one message, no file sent twice`, async () => {
			vi.useFakeTimers({ toFake: ["Date"] });
			const group = await peer.group(unique("group"));
			const { env, src } = await app({ chatModule });
			const names = [`${unique("first")}.txt`, `${unique("second")}.txt`];
			const files = [
				await staged(env, src, names[0], filler(1000), "text/plain"),
				await staged(env, src, names[1], filler(2000), "text/plain"),
			];
			const text = unique("post");
			proxy.loseResponseOf((c) => c.path === "/mail/message/post");
			const sent = await env.chat.send(src, group, text, files);
			await idle(env, src.configId);
			expect(await withText(group, text)).toHaveLength(1);
			expect((await mine(env, src.configId, group, sent.clientUuid)).status).toBe("pending");

			later(QUIET_WINDOW_PASSED_MS);
			await env.chat.flushAll();
			await idle(env, src.configId);
			const found = await withText(group, text);
			expect(found).toHaveLength(1);
			const ids = [(await named(names[0]))[0].id, (await named(names[1]))[0].id];
			expect([...found[0].attachment_ids].sort()).toEqual([...ids].sort());
			expect(uploadsOf(route).filter((c) => names.includes(c.files?.[0]?.filename ?? ""))).toHaveLength(2);
			expect(await mine(env, src.configId, group, sent.clientUuid)).toMatchObject({ status: "sent", messageId: found[0].id });
		});

		it(`voice message ${label}: audio/mpeg with Odoo's voice metadata`, async () => {
			const group = await peer.group(unique("group"));
			const { env, src } = await app({ chatModule });
			const voice = await stageChatVoice(env, src.configId, 1);
			const sent = await env.chat.send(src, group, "", [voice]);
			await idle(env, src.configId);
			const message = await mine(env, src.configId, group, sent.clientUuid);
			expect(message.status).toBe("sent");
			const [att, ...more] = await peer.attachmentsOf(message.messageId!);
			expect(more).toHaveLength(0);
			expect(att).toMatchObject({ name: voice.name, mimetype: "audio/mpeg", file_size: voice.size });
			expect(att.voice_ids).toHaveLength(1);
			const [upload] = uploadsOf(route).filter((c) => c.files?.[0]?.filename === voice.name);
			expect(upload.form!.voice).toBe("true");
			expect(upload.files![0].contentType).toBe("audio/mpeg");
		});
	}

	it("a photo keeps its original bytes with the module, Odoo's route reduces it to 1920 px", async () => {
		const photo = fixture(PHOTO);
		expect(jpegSize(photo)).toEqual([2400, 1600]);
		const group = await peer.group(unique("group"));
		for (const { chatModule } of ROUTES) {
			const { env, src } = await app({ chatModule });
			const sent = await env.chat.send(src, group, "", [await staged(env, src, `${unique("photo")}.jpg`, photo)]);
			await idle(env, src.configId);
			const message = await mine(env, src.configId, group, sent.clientUuid);
			const [att] = await peer.attachmentsOf(message.messageId!);
			const stored = await peer.user.httpGet(`/web/content/${att.id}?download=true`, peer.user.cookie);
			expect(stored.status).toBe(200);
			expect(sha1(stored.bytes)).toBe(att.checksum);
			if (chatModule === "auto") {
				expect(att.checksum).toBe(sha1(photo));
				expect(att.file_size).toBe(photo.length);
			} else {
				expect(att.checksum).not.toBe(sha1(photo));
				expect(jpegSize(stored.bytes)).toEqual([1920, 1280]);
			}
		}
	});

	it("Wi-Fi only holds an upload on a mobile network, sent once on Wi-Fi", async () => {
		const group = await peer.group(unique("group"));
		const { env, src } = await app();
		localStorage.setItem("options.sync.attachments", JSON.stringify({ wifiOnly: true, maxMb: null }));
		const name = `${unique("held")}.txt`;
		const text = unique("text");
		setNetwork({ connected: true, wifi: false });
		const sent = await env.chat.send(src, group, text, [await staged(env, src, name, filler(1000), "text/plain")]);
		await idle(env, src.configId);
		expect(uploadsOf(MODULE_ROUTE).filter((c) => c.files?.[0]?.filename === name)).toEqual([]);
		expect(await withText(group, text)).toEqual([]);
		const ops = await env.db.getOutboxOpsForConfig(src.configId);
		expect(ops.find((o: any) => o.kind === "chat.upload")!.params.heldFor).toBe("wifi");
		expect((await mine(env, src.configId, group, sent.clientUuid)).status).toBe("pending");

		setNetwork({ connected: true, wifi: true });
		await env.chat.flushAll();
		await idle(env, src.configId);
		expect(uploadsOf(MODULE_ROUTE).filter((c) => c.files?.[0]?.filename === name)).toHaveLength(1);
		const [att] = await named(name);
		expect((await withText(group, text)).map((m) => m.attachment_ids)).toEqual([[att.id]]);
		expect((await mine(env, src.configId, group, sent.clientUuid)).status).toBe("sent");
	});

	for (const { label, chatModule, route } of ROUTES) {
		it(`an upload in an expired session ${label} lands once after logging in again`, async () => {
			const group = await peer.group(unique("group"));
			const { env, src } = await app({ chatModule });
			const name = `${unique("expired")}.txt`;
			const file = await staged(env, src, name, filler(1000), "text/plain");
			const { sessionId } = await env.sync.rpc.getSession(env.creds[0]);
			const cookie = `session_id=${sessionId}`;
			const json = (path: string) => fetch(`${target.url}${path}`, {
				method: "POST",
				headers: { "Content-Type": "application/json", Cookie: cookie },
				body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: {} }),
			}).then((r) => r.json() as Promise<any>);
			await json("/web/session/destroy");
			expect((await json("/web/session/get_session_info")).error?.code).toBe(100);

			const sent = await env.chat.send(src, group, "", [file]);
			await idle(env, src.configId);
			const uploads = uploadsOf(route).filter((c) => c.files?.[0]?.filename === name);
			// The destroyed session reads the route as the public user: 404, then the app logs in again
			expect(uploads.map((c) => c.status)).toEqual([404, 200]);
			const [att, ...more] = await named(name);
			expect(more).toHaveLength(0);
			const message = await mine(env, src.configId, group, sent.clientUuid);
			expect(message.status).toBe("sent");
			expect((await peer.attachmentsOf(message.messageId!)).map((a) => a.id)).toEqual([att.id]);
		});
	}

	it("chat_user's image: a preview with download=true, then the original equal to the server's", async () => {
		const group = await peer.group(unique("group"));
		const upload = await peer.upload(group, `${unique("photo")}.jpg`, fixture(PHOTO), { mimetype: "image/jpeg" });
		const messageId = await peer.post(group, unique("look"), { attachments: [upload] });
		const [server] = await peer.attachmentsOf(messageId);
		const mark = proxy.calls.length;
		const { env, src } = await app();
		await env.chat.loadOlder(src, group);
		const [row] = (await env.chat.repo.attachmentsOf(src.configId, group, [messageId], [])).get(`m${messageId}`)!;
		expect(row).toMatchObject({ attachmentId: server.id, checksum: server.checksum, mimetype: "image/jpeg" });
		expect(fileCallsSince(mark)).toEqual([]);

		const thumb = await env.chat.attachments.preview(src, row);
		expect(thumb).not.toBeNull();
		expect(fileCallsSince(mark).map((c: RpcCall) => [c.path, c.status])).toEqual([
			[`/web/image/${server.id}/512x512?unique=${server.checksum}&download=true`, 200],
		]);
		expect(jpegSize(Buffer.from(env.chatFiles.bytes(thumb!)!))[0]).toBeLessThanOrEqual(512);

		const opened = await env.chat.attachments.open(src, row);
		expect(opened.kind).toBe("ready");
		const original = env.chatFiles.bytes((opened as { path: string }).path)!;
		const stored = await peer.user.httpGet(`/web/content/${server.id}?download=true`, peer.user.cookie);
		expect(Buffer.from(original).equals(stored.bytes)).toBe(true);
		expect(sha1(original)).toBe(server.checksum);
		expect(fileCallsSince(mark).at(-1)!.path).toBe(`/web/content/${server.id}?unique=${server.checksum}&download=true`);
	});

	it("a conversation of 20 attachments loads without fetching any file", async () => {
		const group = await peer.group(unique("group"));
		const photo = fixture(PHOTO);
		const posted: number[] = [];
		const image = async () => {
			const upload = await peer.upload(group, `${unique("photo")}.jpg`, photo, { mimetype: "image/jpeg" });
			posted.push(await peer.post(group, unique("image"), { attachments: [upload] }));
		};
		// Older images, a page of text, newer images: both history pages hold attachments
		for (let i = 0; i < 5; i++) await image();
		for (let i = 0; i < 15; i++) posted.push(await peer.post(group, unique("text")));
		for (let i = 0; i < 15; i++) await image();
		const mark = proxy.calls.length;
		const { env, src } = await app();
		await env.chat.messages(src.configId, group);
		expect(await env.chat.loadOlder(src, group)).toBeGreaterThan(0);
		expect(await env.chat.loadOlder(src, group)).toBeGreaterThan(0);
		const cached = (await env.chat.messages(src.configId, group)).map((m) => m.messageId!);
		expect(cached).toEqual(expect.arrayContaining(posted));
		const rows = await env.chat.repo.attachmentsOf(src.configId, group, cached, []);
		expect([...rows.values()].flat()).toHaveLength(20);
		expect(fileCallsSince(mark)).toEqual([]);
	});
});
