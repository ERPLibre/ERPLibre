/**
 * One note on every server of the run at once (16, 17 and 18): a change
 * pulled from one reaches the others, and a server cut off leaves the
 * others synced, itself retried once back.
 */
import { appFor, note, unique, nextServerSecond, TARGETS } from "./harness";
import type { SyncEnv } from "./harness";
import { FaultProxy } from "./faultProxy";
import { OdooAdmin } from "./odooAdmin";

const describeMany = TARGETS.length > 1 ? describe : describe.skip;

describeMany(`Odoo ${TARGETS.map((t) => t.version).join(", ")} — plusieurs serveurs`, () => {
	let proxies: FaultProxy[];
	let admins: OdooAdmin[];

	beforeAll(async () => {
		proxies = await Promise.all(TARGETS.map((t) => FaultProxy.start(t)));
		admins = TARGETS.map((t) => new OdooAdmin(t));
	});
	afterAll(async () => {
		await Promise.all(proxies.map((p) => p.stop()));
	});
	afterEach(() => {
		for (const p of proxies) p.down = false;
	});

	async function everywhere(): Promise<{ env: SyncEnv; id: string; taskIds: number[] }> {
		const env = await appFor(TARGETS.map((t, i) => proxies[i].via(t)));
		const id = unique("note");
		await env.db.addNote(note(id, unique("titre"), ["Partout"]));
		const taskIds: number[] = [];
		for (let i = 0; i < TARGETS.length; i++) {
			await env.sync.setTarget(id, env.configIds[i], "task", { projectId: null });
			await env.sync.pushNote(env.creds[i], id, { userInitiated: true });
			taskIds.push((await env.db.findNoteLink(id, env.configIds[i], "project.task", "create"))!.resId);
		}
		return { env, id, taskIds };
	}

	const names = (taskIds: number[]) =>
		Promise.all(taskIds.map(async (taskId, i) => (await admins[i].read("project.task", taskId, ["name"])).name));

	it("porte sur les autres serveurs un changement tiré de l'un d'eux", async () => {
		const { env, id, taskIds } = await everywhere();
		await nextServerSecond();
		await admins[1].write("project.task", [taskIds[1]], { name: "Renomme sur un serveur" });
		await env.sync.syncAll(env.creds[1]);
		expect((await env.db.getNoteById(id))!.title).toBe("Renomme sur un serveur");
		for (let i = 0; i < TARGETS.length; i++) await env.sync.syncAll(env.creds[i]);
		expect(await names(taskIds)).toEqual(TARGETS.map(() => "Renomme sur un serveur"));
		expect(Object.values(await env.db.getNotePerServerStatus(id))).toEqual(TARGETS.map(() => "synced"));
	});

	it("laisse les autres serveurs à jour quand l'un est coupé, et le reprend à son retour", async () => {
		const { env, id, taskIds } = await everywhere();
		const current = (await env.db.getNoteById(id))!;
		await env.notes.crud.edit(id, { ...current, title: "Change pendant la coupure" });
		proxies[0].down = true;
		for (let i = 0; i < TARGETS.length; i++) await env.sync.syncAll(env.creds[i]);
		const status = await env.db.getNotePerServerStatus(id);
		expect(status[env.configIds[0]]).not.toBe("synced");
		for (let i = 1; i < TARGETS.length; i++) expect(status[env.configIds[i]]).toBe("synced");
		expect((await names(taskIds)).slice(1)).toEqual(TARGETS.slice(1).map(() => "Change pendant la coupure"));

		proxies[0].down = false;
		await env.sync.syncAll(env.creds[0], undefined, { force: true });
		expect(await names(taskIds)).toEqual(TARGETS.map(() => "Change pendant la coupure"));
		expect((await env.db.getNotePerServerStatus(id))[env.configIds[0]]).toBe("synced");
	});
});
