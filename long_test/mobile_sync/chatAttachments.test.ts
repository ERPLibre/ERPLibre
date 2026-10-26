/**
 * Chat attachments against a real Odoo 18, the app as admin, chat_user at
 * the other end, each case through the server module's upload route
 * (module 1.2, idempotent on the file's client uuid) and through Odoo's own
 * (chatModule "ignore"): an upload or a post whose answer is lost still
 * gives one attachment in one message; a voice message is a voice for
 * Odoo; a photo keeps its original bytes through the module and is reduced
 * by Odoo's route; the server's size limit refuses a file at staging, or
 * once at sending with the text still posted; « Wi-Fi only » holds an
 * upload off Wi-Fi; an upload in an expired session lands once after the
 * app logs in again; chat_user's image reaches the app as a preview and an
 * original equal to the server's bytes; and loading a conversation of
 * twenty attachments fetches none of their files.
 *
 * The quiet window (3 minutes) and the retry delays pass on a faked Date:
 * only the app's clock moves, the requests stay real. The upload limit
 * (web.max_file_upload_size) is lowered by two cases only and put back
 * after each; it bounds every request of the server, those of the files
 * running beside this one too, so it stays above any JSON request of the
 * run.
 */
import { createHash } from "node:crypto";
import { appFor, eachVersionFrom, fixture, setNetwork, setOnline, stageChatFile, stageChatVoice, unique, until } from "./harness";
import type { SyncEnv } from "./harness";
import { ChatPeer } from "./chatPeer";
import { FaultProxy } from "./faultProxy";
import type { RpcCall } from "./faultProxy";

const QUIET_WINDOW_PASSED_MS = 4 * 60 * 1000;
const MODULE_ROUTE = "/erplibre_mobile_chat/attachment/upload";
const ODOO_ROUTE = "/mail/attachment/upload";
const LIMIT_KEY = "web.max_file_upload_size";
/** A parameter written only to clear Odoo's parameter cache again (see setLimit). */
const CACHE_BUMP_KEY = "erplibre_mobile_sync.cache_bump";
/** Odoo's limit when the parameter is unset (DEFAULT_MAX_CONTENT_LENGTH). */
const ODOO_DEFAULT_LIMIT = 128 * 1024 * 1024;
/** A limit far under the photo and above every JSON request of a case. */
const LOW_LIMIT = 20000;
const PHOTO = "photo-2400x1600.jpg";

const ROUTES = [
	{ label: "with the module", chatModule: "auto", route: MODULE_ROUTE },
	{ label: "through Odoo's route", chatModule: "ignore", route: ODOO_ROUTE },
] as const;

const sha1 = (bytes: Uint8Array) => createHash("sha1").update(bytes).digest("hex");

/** Width and height of a JPEG, from its first frame header (SOFn). */
function jpegSize(bytes: Buffer): [number, number] {
	let at = 2;
	while (at + 9 < bytes.length) {
		if (bytes[at] !== 0xff) throw new Error(`no JPEG marker at ${at}`);
		const marker = bytes[at + 1];
		if (marker >= 0xc0 && marker <= 0xcf && ![0xc4, 0xc8, 0xcc].includes(marker)) {
			return [bytes.readUInt16BE(at + 7), bytes.readUInt16BE(at + 5)];
		}
		at += 2 + bytes.readUInt16BE(at + 2);
	}
	throw new Error("no JPEG frame header");
}

/** Invented bytes of a given size, unique to the run: no two files of a case share their content. */
function filler(size: number): Uint8Array {
	const line = Buffer.from(`${unique("bytes")}\n`);
	const out = Buffer.alloc(size);
	for (let i = 0; i < size; i += line.length) line.copy(out, i);
	return out;
}

eachVersionFrom(18, "chat attachments", (target) => {
	let proxy: FaultProxy;
	let peer: ChatPeer;
	/** The upload limit as the run found it (false: unset, Odoo's default). */
	let limitBefore: string | false;
	let limitLowered = false;

	/**
	 * Sets the upload limit (false: unset) and waits until the server
	 * applies it. Odoo clears its parameter cache before the write commits,
	 * so a request served in between caches the old value until the next
	 * clear: a second parameter's write and removal, made once the limit is
	 * committed, clear it again; then the session info names the new limit.
	 */
	async function setLimit(value: string | false): Promise<void> {
		await peer.admin.setParam(LIMIT_KEY, value);
		await peer.admin.setParam(CACHE_BUMP_KEY, unique("bump"));
		await peer.admin.setParam(CACHE_BUMP_KEY, false);
		const expected = value === false ? ODOO_DEFAULT_LIMIT : Number(value);
		await until(`the server's upload limit at ${expected}`, async () =>
			(await peer.user.jsonRoute("/web/session/get_session_info")).max_file_upload_size === expected);
	}

	beforeAll(async () => {
		proxy = await FaultProxy.start(target);
		peer = await ChatPeer.open(target);
		limitBefore = await peer.admin.getParam(LIMIT_KEY);
	});
	afterEach(async () => {
		proxy.down = false;
		vi.useRealTimers();
		if (limitLowered) {
			await setLimit(limitBefore);
			limitLowered = false;
		}
	});
	afterAll(async () => {
		if (peer && limitLowered) await setLimit(limitBefore);
		await proxy.stop();
	});

	const later = (ms: number) => vi.setSystemTime(Date.now() + ms);
	const uploadsOf = (route: string) => proxy.calls.filter((c) => c.path === route);
	/** The file requests (/web/image, /web/content) the app made since the proxy recorded mark calls. */
	const fileCallsSince = (mark: number) => proxy.calls.slice(mark).filter((c) => /^\/web\/(image|content)\b/.test(c.path));

	async function lowerLimit(bytes: number): Promise<void> {
		limitLowered = true;
		await setLimit(String(bytes));
	}

	/** The app through the proxy, its chat source loaded. */
	async function app(opts: { chatModule?: "auto" | "ignore" } = {}) {
		const env = await appFor(proxy.via(target), "admin", opts);
		const [src] = await env.chat.sources();
		await env.chat.load(src);
		return { env, src };
	}

	/** The file staged as the composer stages a pick; a refusal fails the case. */
	async function staged(env: SyncEnv, src: any, name: string, bytes: Uint8Array, mimetype?: string) {
		const file = await stageChatFile(env, src, { name, bytes, mimetype });
		if ("refused" in file) throw new Error(`${name} refused at staging`);
		return file;
	}

	const idle = (env: SyncEnv, configId: string) => env.chat.queue.whenIdle(configId);

	/** The server's comments of the conversation holding text, with their attachment ids. */
	const withText = async (channelId: number, text: string) =>
		(await peer.comments(channelId, ["id", "body", "attachment_ids"])).filter((m) => m.body.includes(text));

	const named = (name: string) =>
		peer.admin.searchRead("ir.attachment", [["name", "=", name]], ["id", "res_model", "res_id", "checksum"]);

	const mine = async (env: SyncEnv, configId: string, channelId: number, clientUuid: string | null) =>
		(await env.chat.messages(configId, channelId)).find((m) => m.clientUuid === clientUuid)!;

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

	it("a file over a limit lowered before the app read it is refused at staging, no request", async () => {
		await lowerLimit(LOW_LIMIT);
		const { env, src } = await app();
		expect(await env.chat.uploadLimit(src)).toBe(LOW_LIMIT);
		const before = proxy.calls.length;
		const refused = await stageChatFile(env, src, { name: `${unique("big")}.txt`, bytes: filler(LOW_LIMIT * 2) });
		expect(refused).toEqual({ refused: "too_big", limit: LOW_LIMIT });
		expect(proxy.calls.slice(before)).toEqual([]);
	});

	it("a limit lowered after the file was queued: one 413, a notice, the text posted, no retry", async () => {
		vi.useFakeTimers({ toFake: ["Date"] });
		const group = await peer.group(unique("group"));
		const { env, src } = await app();
		const name = `${unique("big")}.txt`;
		const file = await staged(env, src, name, filler(LOW_LIMIT * 2), "text/plain");
		const text = unique("text");
		setOnline(false);
		const sent = await env.chat.send(src, group, text, [file]);
		await lowerLimit(LOW_LIMIT);
		setOnline(true);
		await env.chat.flushAll();
		await idle(env, src.configId);
		const tried = () => uploadsOf(MODULE_ROUTE).filter((c) => c.files?.[0]?.filename === name);
		expect(tried().map((c) => c.status)).toEqual([413]);
		const found = await withText(group, text);
		expect(found.map((m) => m.attachment_ids)).toEqual([[]]);
		expect(await mine(env, src.configId, group, sent.clientUuid)).toMatchObject({ status: "sent", messageId: found[0].id });
		expect(await env.chat.notices([src.configId])).toEqual([expect.objectContaining({
			kind: "chat.file_refused", channelId: group, file: expect.objectContaining({ name, reason: "too_big" }),
		})]);
		expect(await named(name)).toEqual([]);

		for (let i = 0; i < 2; i++) {
			later(QUIET_WINDOW_PASSED_MS);
			await env.chat.flushAll({ force: true });
			await idle(env, src.configId);
		}
		expect(tried()).toHaveLength(1);
		expect(await withText(group, text)).toHaveLength(1);
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
