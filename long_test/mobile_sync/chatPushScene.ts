/**
 * What the chat push scenarios share: the app as admin with the run's ntfy
 * link applied (the kit's pushNodeNative for the phone's native side), and
 * what Odoo pushed, read from the topic with the phone's token and
 * decrypted with the account's own keys, as the phone does.
 *
 * Odoo pushes to every device of the recipients, synchronously while they
 * hold fewer than 5 (the run's servers have no cron for the rest): end()
 * drops admin's devices on this ntfy after each case. Other files post to
 * admin meanwhile, so a topic may hold their pushes too: a case looks for
 * its own text in the decrypted payloads.
 */
import { appFor, decryptWebPush, parseNtfyLink, pollNtfy, until } from "./harness";
import type { NtfyLink, SyncEnv, Target, TargetNtfy } from "./harness";
import type { ChatPeer } from "./chatPeer";

/** Odoo's decrypted push: the notification's title and options. */
export interface Payload {
	title: string;
	options: { icon?: string; body: string; data: { model: string; res_id: number; action?: string } };
}

export type PushKeys = ReturnType<SyncEnv["pushNative"]["keysOf"]>;

export class PushScene {
	env: SyncEnv | null = null;

	constructor(readonly target: Target, readonly ntfy: TargetNtfy, readonly peer: () => ChatPeer) {}

	/** After a case: the app's chat stopped, admin's devices on this ntfy unlinked. */
	async end(): Promise<void> {
		this.env?.chat.dispose();
		this.env = null;
		await this.peer().dropPushDevices(this.ntfy.url);
	}

	/** The app as admin, its chat source loaded and the push work it queued settled. */
	async app() {
		const env = await appFor(this.target, "admin");
		this.env = env;
		const [src] = await env.chat.sources();
		await env.chat.load(src);
		await env.push.idle();
		return { env, src };
	}

	/** The run's link, or the second phone's (other): the same ntfy for the phone and for Odoo. */
	link(access: "phone" | "other" = "phone"): NtfyLink {
		const parsed = parseNtfyLink(access === "phone" ? this.ntfy.link : this.ntfy.other.link);
		if (!parsed) throw new Error("the run's ntfy link does not parse");
		expect(parsed.odooUrl).toBe(this.ntfy.url);
		return parsed;
	}

	/** The app with the link applied to its account, registered with Odoo; its push row. */
	async linked(access: "phone" | "other" = "phone") {
		const { env, src } = await this.app();
		const applied = await env.push.applyLink([src.configId], this.link(access));
		expect(applied).toEqual({ ok: true, reason: null, registered: [src.configId] });
		const row = await env.chat.repo.pushRow(src.configId);
		expect(row.endpoint).toBe(`${this.ntfy.url}/${row.topic}`);
		return { env, src, row };
	}

	/** The token of the access whose prefix starts the topic. */
	tokenOf(topic: string): string {
		return topic.startsWith(this.ntfy.other.prefix) ? this.ntfy.other.token : this.ntfy.token;
	}

	/** The messages the topic holds, read with its phone's token. */
	messages(topic: string) {
		return pollNtfy({ url: this.ntfy.url, token: this.tokenOf(topic) }, [topic], "all");
	}

	/** The payloads of the topic decrypted with the account's keys (taken before a removal drops them). */
	async payloads(keys: PushKeys): Promise<{ raw: Uint8Array; payload: Payload }[]> {
		return (await this.messages(keys.topic)).map((m) => ({
			raw: m.body,
			payload: JSON.parse(Buffer.from(decryptWebPush(m.body, keys.privateKey, keys.publicKey, keys.auth)).toString("utf8")),
		}));
	}

	/** The pushes whose body holds text, once there are `count` of them (Odoo pushes before its commit: polled). */
	pushed(keys: PushKeys, text: string, count = 1) {
		return until(`${count} push(es) of « ${text} »`, async () => {
			const found = (await this.payloads(keys)).filter((p) => p.payload.options.body.includes(text));
			return found.length >= count ? found : null;
		});
	}
}
