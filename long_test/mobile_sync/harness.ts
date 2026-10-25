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
	createSyncEnv, installLocalStorage, resetMocks, memoryAttachmentIO,
} from "../../mobile/erplibre_home_mobile/src/testing/syncTestKit";
import type { SyncEnv } from "../../mobile/erplibre_home_mobile/src/testing/syncTestKit";
import { readFileSync } from "node:fs";

export { memoryAttachmentIO };
export type { SyncEnv };

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
 * their applications and the sync service, http allowed, no session yet.
 */
export async function appFor(targets: Target | Target[], as: "admin" | "multi" = "admin"): Promise<SyncEnv> {
	resetMocks();
	installLocalStorage({ allowHttp: true });
	const list = Array.isArray(targets) ? targets : [targets];
	return createSyncEnv(list.map((t) => ({
		url: t.url, username: t[as].login, password: t[as].password, database: t.database,
	})));
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
