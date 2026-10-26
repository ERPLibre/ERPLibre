/**
 * The server's upload limit (web.max_file_upload_size) against the chat's
 * attachments on a real Odoo 18: lowered before the app reads it, a file is
 * refused at staging without a request; lowered after the file was queued,
 * the upload meets one 413, the file is refused once with a notice, the
 * text is still posted, and nothing is sent again.
 *
 * The limit bounds every request of the server: a file named
 * *.serial.test.ts runs alone, after the files that run side by side
 * (long_test/mobile_sync.py), so no other case meets the lowered limit.
 * It is put back after each case. The quiet window passes on a faked Date.
 */
import { eachVersionFrom, setOnline, stageChatFile, unique, until } from "./harness";
import { ChatPeer } from "./chatPeer";
import { FaultProxy } from "./faultProxy";
import { attachmentScene, filler, MODULE_ROUTE, QUIET_WINDOW_PASSED_MS } from "./chatAttachmentScene";

const LIMIT_KEY = "web.max_file_upload_size";
/** A parameter written only to clear Odoo's parameter cache again (see setLimit). */
const CACHE_BUMP_KEY = "erplibre_mobile_sync.cache_bump";
/** Odoo's limit when the parameter is unset (DEFAULT_MAX_CONTENT_LENGTH). */
const ODOO_DEFAULT_LIMIT = 128 * 1024 * 1024;
/** A limit far under the files of the cases and above every JSON request of a case. */
const LOW_LIMIT = 20000;

eachVersionFrom(18, "chat attachments limit", (target) => {
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

	async function lowerLimit(bytes: number): Promise<void> {
		limitLowered = true;
		await setLimit(String(bytes));
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

	const { later, uploadsOf, app, staged, idle, withText, named, mine } = attachmentScene(target, () => ({ proxy, peer }));

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
});
