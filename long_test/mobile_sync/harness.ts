/**
 * What every scenario shares: the Odoo servers of the run (targets.json,
 * written by long_test/mobile_sync.py, named by MOBILE_SYNC_TARGETS), the
 * app's sync code set up for one of them, and names unique to the run.
 *
 * Runs under the mobile repo's Vitest, with its globals and mocks: these
 * files import nothing from "vitest" (it does not resolve from here), and
 * nothing of the app but its test kit.
 */
import {
	createSyncEnv, installLocalStorage, resetMocks, memoryAttachmentIO, nodeTransport,
	restartSyncEnv, setOnline, setNetwork, chatTitle, stageChatFile, stageChatVoice,
	composeBody, bodyText, emojiConversions, isEmptyMessage, EMPTY_MENTIONS,
	foldText, htmlTerm, mailboxKindOf, noteForRecord,
} from "../../mobile/erplibre_home_mobile/src/testing/syncTestKit";
import type {
	ChatMailboxItem, Mentions, MemoryChatFiles, MessageTarget, SearchResults, SyncEnv,
} from "../../mobile/erplibre_home_mobile/src/testing/syncTestKit";
import { readFileSync } from "node:fs";

export { memoryAttachmentIO, nodeTransport, restartSyncEnv, setOnline, setNetwork, chatTitle, stageChatFile, stageChatVoice };
export { composeBody, bodyText, emojiConversions, isEmptyMessage, EMPTY_MENTIONS };
export { foldText, htmlTerm, mailboxKindOf, noteForRecord };
export type { ChatMailboxItem, Mentions, MessageTarget, SearchResults, SyncEnv };

export interface Login {
	login: string;
	password: string;
}

/** One Odoo server of the run: its major version, url, database and users. */
export interface Target {
	version: number;
	url: string;
	database: string;
	admin: Login;
	/** A user of two companies (see mobile_sync_odoo.POST_INSTALLATION). */
	multi: Login;
	/** A second internal user, the other end of the chat (Odoo 18 only). */
	chat?: Login;
	/**
	 * An internal user notified in Odoo's inbox, with an email address and
	 * project's user rights, a member of « ms chat » (Odoo 18 only): the
	 * app's user of chatInbox.test.ts alone.
	 */
	inbox?: Login;
}

function readTargets(): Target[] {
	const path = process.env.MOBILE_SYNC_TARGETS;
	if (!path) {
		throw new Error(
			"MOBILE_SYNC_TARGETS absent : ces tests se lancent par ./long_test/mobile_sync.py, qui démarre les Odoo",
		);
	}
	return JSON.parse(readFileSync(path, "utf8"));
}

export const TARGETS: Target[] = readTargets();

/** The scenarios of fn, once per server of the run, in a block named « Odoo <version> ». */
export function eachVersion(name: string, fn: (target: Target) => void): void {
	describe.each(TARGETS)(`Odoo $version — ${name}`, (target: Target) => fn(target));
}

/**
 * The scenarios of fn, once per server of the run whose major version is at
 * least min, in a block named « Odoo <version> » (lire_rapport counts by that
 * name). A run with no such server skips the block under a name that says why,
 * so a 16/17-only run does not fail for lack of tests.
 */
export function eachVersionFrom(min: number, name: string, fn: (target: Target) => void): void {
	const targets = TARGETS.filter((t) => t.version >= min);
	if (targets.length === 0) {
		describe.skip(`Odoo ${min}+ only — ${name}`, () => {
			it("no server of this version in the run", () => {});
		});
		return;
	}
	describe.each(targets)(`Odoo $version — ${name}`, (target: Target) => fn(target));
}

/**
 * The app as a user of one or more servers sees it: a new database with
 * their applications and the sync service, http allowed, no session yet,
 * the network on. as names the user: admin, the two-company user, the
 * chat's second user or the inbox's user (Odoo 18), or any other Login of
 * the servers (a user a test created).
 * chatModule "ignore" makes chat posts take the marker path, and uploads
 * Odoo's own route, even where the server module is installed. The chat's
 * files are in memory (env.chatFiles; chatFiles to give them).
 */
export async function appFor(
	targets: Target | Target[],
	as: "admin" | "multi" | "chat" | "inbox" | Login = "admin",
	opts: { chatModule?: "auto" | "ignore"; chatFiles?: MemoryChatFiles } = {},
): Promise<SyncEnv> {
	resetMocks();
	installLocalStorage({ allowHttp: true });
	const list = Array.isArray(targets) ? targets : [targets];
	return createSyncEnv(list.map((t) => {
		const user = typeof as === "string" ? t[as] : as;
		if (!user) throw new Error(`no ${as} user on Odoo ${t.version}`);
		return { url: t.url, username: user.login, password: user.password, database: t.database };
	}), opts);
}

/** The bytes of a file of fixtures/ (see fixtures/PROVENANCE.md). */
export function fixture(name: string): Buffer {
	return readFileSync(new URL(`./fixtures/${name}`, import.meta.url));
}

let counter = 0;

/** A name no other record of the run has, for records found by name. */
export function unique(label: string): string {
	counter += 1;
	return `ms-${process.pid}-${Date.now().toString(36)}-${counter}-${label}`;
}

/** A note as the app stores it: a title and one text entry per paragraph. */
export function note(id: string, title: string, paragraphs: string[] = [], extra: Record<string, any> = {}): any {
	return {
		id, title, done: false, archived: false, pinned: false, tags: [],
		entries: paragraphs.map((text, i) => ({ id: `${id}-t${i}`, type: "text", params: { text, readonly: false } })),
		...extra,
	};
}

/** Waits until the server's clock has moved to the next second: write_date reaches the app to the second. */
export async function nextServerSecond(): Promise<void> {
	await new Promise((resolve) => setTimeout(resolve, 1100));
}

/**
 * Polls probe every 100 ms until it returns a value other than undefined,
 * null or false, and returns that value; fails after ms with what it waited
 * for. For what reaches the app on its own (the bus), with no fixed sleep.
 * The deadline runs on performance.now(), which a faked Date leaves alone.
 */
export async function until<T>(what: string, probe: () => Promise<T | undefined | null | false>, ms = 20000): Promise<T> {
	const deadline = performance.now() + ms;
	for (;;) {
		const value = await probe();
		if (value !== undefined && value !== null && value !== false) return value;
		if (performance.now() > deadline) throw new Error(`still waiting after ${ms} ms: ${what}`);
		await new Promise((resolve) => setTimeout(resolve, 100));
	}
}
