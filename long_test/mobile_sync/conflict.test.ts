/**
 * A field changed in the app and on the server to different values since
 * their last exchange: the push stops before writing, and the user's choice
 * per field (mine, theirs) settles what each side ends up with.
 */
import { appFor, eachVersion, note, unique } from "./harness";
import type { SyncEnv } from "./harness";
import { FaultProxy } from "./faultProxy";
import { OdooAdmin } from "./odooAdmin";

eachVersion("conflit", (target) => {
	let proxy: FaultProxy;
	let admin: OdooAdmin;

	beforeAll(async () => {
		proxy = await FaultProxy.start(target);
		admin = new OdooAdmin(target);
	});
	afterAll(async () => {
		await proxy.stop();
	});

	/** A note sent as a personal task, then retitled on the server (theirs) and in the app (mine). */
	async function bothRenamed(): Promise<{ env: SyncEnv; id: string; taskId: number }> {
		const env = await appFor(proxy.via(target));
		const id = unique("note");
		await env.db.addNote(note(id, unique("titre"), ["Texte"]));
		await env.sync.setTarget(id, env.configIds[0], "task", { projectId: null });
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
		const taskId = (await env.db.findNoteLink(id, env.configIds[0], "project.task", "create"))!.resId;
		await admin.write("project.task", [taskId], { name: "Theirs" });
		const current = (await env.db.getNoteById(id))!;
		await env.notes.crud.edit(id, { ...current, title: "Mine" });
		return { env, id, taskId };
	}

	it("s'arrête sans écrire, puis envoie la mienne", async () => {
		const { env, id, taskId } = await bothRenamed();
		const before = proxy.callsOf("project.task", "write").length;
		await expect(env.sync.pushNote(env.creds[0], id, { userInitiated: true })).rejects.toThrow();
		expect(proxy.callsOf("project.task", "write").length).toBe(before);
		expect((await env.db.getNoteSyncInfo(id)).syncStatus).toBe("conflict");
		const [conflict] = await env.sync.conflictsOf(id);
		expect(conflict.fields).toEqual({ title: { mine: "Mine", theirs: "Theirs" } });

		await env.sync.resolveConflict(id, conflict.linkId, { title: "mine" });
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
		expect((await admin.read("project.task", taskId, ["name"])).name).toBe("Mine");
		expect((await env.db.getNoteSyncInfo(id)).syncStatus).toBe("synced");
	});

	it("prend la leur dans la note, sans rien écrire sur le serveur", async () => {
		const { env, id, taskId } = await bothRenamed();
		await env.sync.syncAll(env.creds[0]);
		const [conflict] = await env.sync.conflictsOf(id);
		expect(conflict).toBeDefined();
		await env.sync.resolveConflict(id, conflict.linkId, { title: "theirs" });
		expect((await env.db.getNoteById(id))!.title).toBe("Theirs");
		const before = proxy.callsOf("project.task", "write").length;
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
		expect(proxy.callsOf("project.task", "write").length).toBe(before);
		expect((await admin.read("project.task", taskId, ["name"])).name).toBe("Theirs");
	});
});
