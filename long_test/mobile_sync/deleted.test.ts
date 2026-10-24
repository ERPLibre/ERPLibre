/**
 * A task deleted on the server: the note leaves that server's queue and is
 * never recreated there unasked; chosen again in the picker, a new task is
 * created in the project chosen.
 */
import { appFor, eachVersion, note, unique } from "./harness";
import { FaultProxy } from "./faultProxy";
import { OdooAdmin } from "./odooAdmin";

eachVersion("supprimés", (target) => {
	let proxy: FaultProxy;
	let admin: OdooAdmin;

	beforeAll(async () => {
		proxy = await FaultProxy.start(target);
		admin = new OdooAdmin(target);
	});
	afterAll(async () => {
		await proxy.stop();
	});

	it("ne recrée la tâche supprimée que sur demande, dans le projet choisi", async () => {
		const env = await appFor(proxy.via(target));
		const id = unique("note");
		await env.db.addNote(note(id, unique("titre")));
		await env.sync.setTarget(id, env.configIds[0], "task", { projectId: null });
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
		const first = (await env.db.findNoteLink(id, env.configIds[0], "project.task", "create"))!.resId;
		await admin.unlink("project.task", [first]);

		const current = (await env.db.getNoteById(id))!;
		await env.notes.crud.edit(id, { ...current, title: "Change apres suppression" });
		const creates = proxy.callsOf("project.task", "create").length;
		await env.sync.syncAll(env.creds[0]);
		expect(proxy.callsOf("project.task", "create").length).toBe(creates);
		expect(await env.sync.pendingNoteIds(env.configIds[0])).not.toContain(id);
		expect(await env.sync.targetState(id, env.configIds[0], "task")).toMatchObject({ state: "choose", reason: "deleted", deletedResId: first });

		const projectId = await admin.create("project.project", { name: unique("projet") });
		await env.sync.setTarget(id, env.configIds[0], "task", { projectId });
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
		const again = (await env.db.findNoteLink(id, env.configIds[0], "project.task", "create"))!.resId;
		expect(again).not.toBe(first);
		const task = await admin.read("project.task", again, ["project_id", "name"]);
		expect(task.project_id[0]).toBe(projectId);
		expect(task.name).toBe("Change apres suppression");
	});
});
