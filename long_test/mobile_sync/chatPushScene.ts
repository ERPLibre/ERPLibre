/**
 * What the chat push scenarios share: the app as admin (or another user)
 * with the run's ntfy link applied (the kit's pushNodeNative for the
 * phone's native side), and what Odoo pushed, read from the topic with the
 * phone's token and decrypted with the account's own keys, as the phone
 * does.
 *
 * Odoo pushes to every device of the recipients, synchronously while they
 * hold fewer than 5 (the run's servers have no cron for the rest): end()
 * drops the devices of the endpoints this scene linked after each case,
 * and leaves those of the other files running beside it. Other files post
 * to admin meanwhile, so a topic may hold their pushes too: a case looks
 * for its own text in the decrypted payloads, or its own conversation in
 * a control push.
 */
import { appFor, decryptWebPush, parseNtfyLink, pollNtfy, until } from "./harness";
import type { Login, NtfyLink, SyncEnv, Target, TargetNtfy } from "./harness";
import type { ChatPeer } from "./chatPeer";

/**
 * Odoo's decrypted push. A message push has the notification's title and
 * options (module 1.5 adds options.data.erplibre for a marked device); a
 * control push of the module (read, inbox_done) has only erplibre.
 */
export interface Payload {
	title?: string;
	options?: {
		icon?: string;
		body: string;
		data: {
			model: string;
			res_id: number;
			action?: string;
			erplibre?: { v: number; message_id: number; channel_type: string | null };
		};
	};
	erplibre?: { v: number; type: string; channel_id?: number; last_message_id?: number; threads?: [string, number][] | null };
}

export type PushKeys = ReturnType<SyncEnv["pushNative"]["keysOf"]>;

/** Who the app signs in as and how it treats the server module, for app() and linked(). */
export interface AppOptions {
	as?: "admin" | Login;
	chatModule?: "auto" | "ignore";
}

export class PushScene {
	/** The app of the case, the last one started. */
	env: SyncEnv | null = null;
	/** Every app the case started, stopped by end(). */
	private envs: SyncEnv[] = [];
	/** The endpoints the case's apps were registered under, unlinked by end(). */
	private endpoints = new Set<string>();

	constructor(readonly target: Target, readonly ntfy: TargetNtfy, readonly peer: () => ChatPeer) {}

	/** After a case: the apps' chat stopped, the devices of their endpoints unlinked. */
	async end(): Promise<void> {
		for (const env of this.envs) {
			for (const row of await env.chat.repo.pushRows()) {
				if (row.endpoint) this.endpoints.add(row.endpoint);
			}
			env.chat.dispose();
		}
		this.envs = [];
		this.env = null;
		await this.peer().dropPushDevicesOf([...this.endpoints]);
		this.endpoints.clear();
	}

	/** The app as admin (or opts.as), its chat source loaded and the push work it queued settled. */
	async app(opts: AppOptions = {}) {
		const env = await appFor(this.target, opts.as ?? "admin", { chatModule: opts.chatModule });
		this.env = env;
		this.envs.push(env);
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
	async linked(access: "phone" | "other" = "phone", opts: AppOptions = {}) {
		const { env, src } = await this.app(opts);
		const applied = await env.push.applyLink([src.configId], this.link(access));
		expect(applied).toEqual({ ok: true, reason: null, registered: [src.configId] });
		const row = await env.chat.repo.pushRow(src.configId);
		expect(row.endpoint).toBe(`${this.ntfy.url}/${row.topic}`);
		this.endpoints.add(row.endpoint!);
		return { env, src, row };
	}

	/**
	 * linked() with the module in use (chatModule "auto"), once Odoo holds
	 * the device marked as the app's (the app marks it after registering,
	 * module 1.5); the device's id is in device.
	 */
	async markedApp(access: "phone" | "other" = "phone", opts: Pick<AppOptions, "as"> = {}) {
		const linked = await this.linked(access, { ...opts, chatModule: "auto" });
		const device = await until("the device marked as the app's", async () => {
			const found = await this.peer().appDevice(linked.row.endpoint!);
			return found?.app ? found : null;
		});
		return { ...linked, device };
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

	/** The message pushes whose body holds text, once there are `count` of them (Odoo may push after its answer: polled). */
	pushed(keys: PushKeys, text: string, count = 1) {
		return until(`${count} push(es) of « ${text} »`, async () => {
			const found = (await this.payloads(keys)).filter((p) => p.payload.options?.body.includes(text));
			return found.length >= count ? found : null;
		});
	}

	/** The control pushes of the module on the topic for which match is true. */
	async controls(keys: PushKeys, match: (c: NonNullable<Payload["erplibre"]>) => boolean): Promise<NonNullable<Payload["erplibre"]>[]> {
		return (await this.payloads(keys))
			.map((p) => p.payload.erplibre)
			.filter((c): c is NonNullable<Payload["erplibre"]> => !!c && match(c));
	}

	/** The first control push for which match is true, once the topic holds it. */
	control(keys: PushKeys, what: string, match: (c: NonNullable<Payload["erplibre"]>) => boolean) {
		return until(what, async () => (await this.controls(keys, match))[0] ?? null);
	}
}
