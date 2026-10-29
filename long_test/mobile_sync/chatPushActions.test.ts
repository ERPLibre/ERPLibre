/**
 * The notification actions native code ended or handed over, drained by
 * the app against a real Odoo 18 (module 1.5 installed): the kit's
 * pushNodeNative stands for the phone, its action store holding the
 * records a receiver would have written (addAction). A handed-over reply
 * reaches Odoo once through the app's outbox, with the module (its
 * erplibre_client_uuid) and without it (chatModule "ignore": the marker);
 * a reply Odoo already holds is not posted again; a handed-over read and
 * mute reach Odoo; a done reply's Store answer fills the cache offline.
 */
import { randomUUID } from "node:crypto";
import { appFor, chatMarker, composeBody, EMPTY_MENTIONS, eachVersionFrom, setOnline, unique, until } from "./harness";
import type { SyncEnv, Target } from "./harness";
import { ChatPeer } from "./chatPeer";
import { OdooAdmin } from "./odooAdmin";

/** How long native code's mute lasts from the tap (ActionRunner.MUTE_MS). */
const MUTE_MS = 60 * 60_000;
/** Past the outbox's quiet window (3 min) counted from a send that may have reached Odoo. */
const PAST_QUIET_WINDOW_MS = 4 * 60_000;
/** The time left to a second post that must not come, once the outbox is empty. */
const SILENCE_MS = 3000;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** A UTC « YYYY-MM-DD HH:MM:SS » of Odoo as epoch ms. */
const odooTime = (value: string) => Date.parse(`${value.replace(" ", "T")}Z`);

eachVersionFrom(18, "chat push actions", (target: Target) => {
	let peer: ChatPeer;
	let admin: OdooAdmin;
	let env: SyncEnv | null = null;

	beforeAll(async () => {
		peer = await ChatPeer.open(target);
		admin = new OdooAdmin(target);
		await admin.sessionLogin();
	});
	afterEach(() => {
		setOnline(true);
		env?.chat.dispose();
		env = null;
	});

	/** The app as admin, a new group of chat_user and admin loaded in its cache. */
	async function appWithGroup(chatModule: "auto" | "ignore" = "auto") {
		const group = await peer.group(unique("actions"));
		env = await appFor(target, "admin", { chatModule });
		const [src] = await env.chat.sources();
		await env.chat.load(src);
		return { env, src, group };
	}

	/** The outbox of the account emptied: every op sent or dropped. */
	async function outboxEmpty(e: SyncEnv, configId: string) {
		await until("the outbox emptied", async () => (await e.db.getOutboxOpsForConfig(configId)).length === 0);
	}

	/** The comments of the conversation carrying the marker of uuid, on the server. */
	async function marked(channelId: number, uuid: string) {
		return (await peer.comments(channelId, ["id", "body", "author_id"])).filter((m) => m.body.includes(`erplibre-mobile:${uuid}`));
	}

	describe.each(["auto", "ignore"] as const)("chatModule %s", (chatModule) => {
		it("a handoff reply posts once", async () => {
			const { env, src, group } = await appWithGroup(chatModule);
			const text = unique("réponse confiée");
			const action = env.pushNative.addAction({
				configId: src.configId, kind: "reply", state: "handoff", reason: "session_expired", channelId: group, text,
			});
			expect(await env.pushActions.drain()).toEqual({ applied: [action.id], kept: [] });
			const [posted] = await until("the reply on the server", async () => {
				const found = await marked(group, action.clientUuid);
				return found.length ? found : null;
			});
			expect(posted.author_id[0]).toBe(peer.adminPartnerId);
			expect(posted.body).toContain(text);
			const [row] = await admin.searchRead("mail.message", [["id", "=", posted.id]], ["erplibre_client_uuid"]);
			expect(row.erplibre_client_uuid).toBe(chatModule === "auto" ? action.clientUuid : false);
			expect(await env.pushActions.drain()).toEqual({ applied: [], kept: [] });
			await outboxEmpty(env, src.configId);
			await sleep(SILENCE_MS);
			expect(await marked(group, action.clientUuid)).toHaveLength(1);
		});

		it("a handoff reply that Odoo already holds posts nothing", async () => {
			const { env, src, group } = await appWithGroup(chatModule);
			const text = unique("déjà sur Odoo");
			const clientUuid = randomUUID();
			// What native code posted before its answer was lost: its body, its marker and, with the module, its uuid
			await admin.jsonRoute("/mail/message/post", {
				thread_model: "discuss.channel",
				thread_id: group,
				post_data: {
					body: composeBody(text, EMPTY_MENTIONS, []).body + chatMarker(clientUuid),
					message_type: "comment",
					subtype_xmlid: "mail.mt_comment",
					...(chatModule === "auto" ? { erplibre_client_uuid: clientUuid } : {}),
				},
				context: { temporary_id: clientUuid },
			});
			expect(await marked(group, clientUuid)).toHaveLength(1);
			const sentAt = Date.now() - PAST_QUIET_WINDOW_MS;
			const action = env.pushNative.addAction({
				configId: src.configId, kind: "reply", state: "handoff", reason: "session_expired", channelId: group, text,
				clientUuid, createdAt: sentAt, sentAt, plainSent: chatModule === "ignore",
			});
			expect(await env.pushActions.drain()).toEqual({ applied: [action.id], kept: [] });
			await outboxEmpty(env, src.configId);
			await sleep(SILENCE_MS);
			expect(await marked(group, clientUuid)).toHaveLength(1);
		});
	});

	it("a handoff read marks the conversation read with read receipts off", async () => {
		const group = await peer.group(unique("lecture"));
		const id = await peer.post(group, unique("à lire"));
		const app = await appFor(target, "admin");
		env = app;
		localStorage.setItem("options.chat", JSON.stringify({ sendRead: false }));
		const [src] = await app.chat.sources();
		await app.chat.load(src);
		expect(await peer.seenOf(target.admin.login, group)).toBeLessThan(id);
		const action = app.pushNative.addAction({
			configId: src.configId, kind: "read", state: "handoff", reason: "session_expired", channelId: group, messageId: id,
		});
		expect(await app.pushActions.drain()).toEqual({ applied: [action.id], kept: [] });
		await until("the conversation read on the server", async () => (await peer.seenOf(target.admin.login, group)) === id);
	});

	it("a handoff mute mutes for the hour left", async () => {
		const { env, src, group } = await appWithGroup();
		const createdAt = Date.now() - 10 * 60_000;
		const action = env.pushNative.addAction({
			configId: src.configId, kind: "mute", state: "handoff", reason: "refused", channelId: group, createdAt,
		});
		expect(await env.pushActions.drain()).toEqual({ applied: [action.id], kept: [] });
		const mutedUntil = await until("the mute on the server", () => peer.muteOf(target.admin.login, group));
		// Odoo mutes for whole minutes from its own clock
		expect(Math.abs(odooTime(mutedUntil) - (createdAt + MUTE_MS))).toBeLessThan(2 * 60_000);
	});

	it("a done reply's answer shows the message in the cache", async () => {
		const { env, src, group } = await appWithGroup();
		const text = unique("envoyée par le natif");
		const clientUuid = randomUUID();
		const answer = await admin.jsonRoute("/mail/message/post", {
			thread_model: "discuss.channel",
			thread_id: group,
			post_data: {
				body: composeBody(text, EMPTY_MENTIONS, []).body + chatMarker(clientUuid),
				message_type: "comment",
				subtype_xmlid: "mail.mt_comment",
				erplibre_client_uuid: clientUuid,
			},
			context: { temporary_id: clientUuid },
		});
		const messageId = answer["mail.message"][0].id;
		expect((await env.chat.messages(src.configId, group)).some((m) => m.messageId === messageId)).toBe(false);
		const action = env.pushNative.addAction({
			configId: src.configId, kind: "reply", state: "done", channelId: group, text, clientUuid, messageId,
			sentAt: Date.now(), answer: JSON.stringify(answer),
		});
		setOnline(false);
		expect(await env.pushActions.drain()).toEqual({ applied: [action.id], kept: [] });
		const shown = (await env.chat.messages(src.configId, group)).find((m) => m.messageId === messageId);
		expect(shown).toBeTruthy();
		expect(shown!.body).toContain(text);
		expect(await env.db.getOutboxOpsForConfig(src.configId)).toEqual([]);
	});
});
