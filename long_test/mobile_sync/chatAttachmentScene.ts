/**
 * What the chat attachment scenarios share: the upload routes, the photo
 * fixture, byte helpers, and the steps of a case against one Odoo 18 seen
 * through a FaultProxy, chat_user (ChatPeer) at the other end. Each test
 * file owns its proxy and peer (started in its beforeAll) and hands them
 * over through live().
 */
import { createHash } from "node:crypto";
import { appFor, stageChatFile, unique } from "./harness";
import type { SyncEnv, Target } from "./harness";
import type { ChatPeer } from "./chatPeer";
import type { FaultProxy } from "./faultProxy";

export const QUIET_WINDOW_PASSED_MS = 4 * 60 * 1000;
export const MODULE_ROUTE = "/erplibre_mobile_chat/attachment/upload";
export const ODOO_ROUTE = "/mail/attachment/upload";
export const PHOTO = "photo-2400x1600.jpg";

/** Each case once through the module's route and once through Odoo's (chatModule "ignore"). */
export const ROUTES = [
	{ label: "with the module", chatModule: "auto", route: MODULE_ROUTE },
	{ label: "through Odoo's route", chatModule: "ignore", route: ODOO_ROUTE },
] as const;

export const sha1 = (bytes: Uint8Array) => createHash("sha1").update(bytes).digest("hex");

/** Width and height of a JPEG, from its first frame header (SOFn). */
export function jpegSize(bytes: Buffer): [number, number] {
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
export function filler(size: number): Uint8Array {
	const line = Buffer.from(`${unique("bytes")}\n`);
	const out = Buffer.alloc(size);
	for (let i = 0; i < size; i += line.length) line.copy(out, i);
	return out;
}

/** The steps of a case against target, over the proxy and the peer live() gives once beforeAll ran. */
export function attachmentScene(target: Target, live: () => { proxy: FaultProxy; peer: ChatPeer }) {
	/** The app's clock moved on (a faked Date), the requests left real. */
	const later = (ms: number) => vi.setSystemTime(Date.now() + ms);
	const uploadsOf = (route: string) => live().proxy.calls.filter((c) => c.path === route);
	/** The file requests (/web/image, /web/content) the app made since the proxy recorded mark calls. */
	const fileCallsSince = (mark: number) =>
		live().proxy.calls.slice(mark).filter((c) => /^\/web\/(image|content)\b/.test(c.path));

	/** The app through the proxy, its chat source loaded. */
	async function app(opts: { chatModule?: "auto" | "ignore" } = {}) {
		const env = await appFor(live().proxy.via(target), "admin", opts);
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
		(await live().peer.comments(channelId, ["id", "body", "attachment_ids"])).filter((m) => m.body.includes(text));

	/** The server's attachments of that name. */
	const named = (name: string) =>
		live().peer.admin.searchRead("ir.attachment", [["name", "=", name]], ["id", "res_model", "res_id", "checksum", "file_size"]);

	/** The app's cached message of clientUuid. */
	const mine = async (env: SyncEnv, configId: string, channelId: number, clientUuid: string | null) =>
		(await env.chat.messages(configId, channelId)).find((m) => m.clientUuid === clientUuid)!;

	return { later, uploadsOf, fileCallsSince, app, staged, idle, withText, named, mine };
}
