/**
 * A note sent as a task, and the task changed on either side: what the app
 * writes (seen on the wire through the proxy) and what Odoo then holds.
 */
import { appFor, eachVersion, note, unique, nextServerSecond } from "./harness";
import type { SyncEnv } from "./harness";
import { FaultProxy } from "./faultProxy";
import { OdooAdmin } from "./odooAdmin";

eachVersion("tâches", (target) => {
	let proxy: FaultProxy;
	let admin: OdooAdmin;
	let projectId: number;

	beforeAll(async () => {
		proxy = await FaultProxy.start(target);
		admin = new OdooAdmin(target);
		projectId = await admin.create("project.project", { name: unique("projet") });
	});
	afterAll(async () => {
		await proxy.stop();
	});

	/** A note sent as a task of the project: the app, the note id, the task id. */
	async function sentTask(paragraphs: string[] = ["Premier"], extra: Record<string, any> = {}) {
		const env = await appFor(proxy.via(target));
		const id = unique("note");
		await env.db.addNote(note(id, unique("titre"), paragraphs, extra));
		await env.sync.setTarget(id, env.configIds[0], "task", { projectId });
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
		const link = (await env.db.findNoteLink(id, env.configIds[0], "project.task", "create"))!;
		return { env, id, taskId: link.resId, clientUuid: link.clientUuid! };
	}

	async function edit(env: SyncEnv, id: string, change: (n: any) => void) {
		const current = (await env.db.getNoteById(id))!;
		change(current);
		await env.notes.crud.edit(id, current);
	}

	it("crée la tâche dans son projet, marquée, une seule fois", async () => {
		const before = proxy.callsOf("project.task", "create").length;
		const { env, id, taskId, clientUuid } = await sentTask(["Premier paragraphe"]);
		const task = await admin.read("project.task", taskId, ["project_id", "description"]);
		expect(task.project_id[0]).toBe(projectId);
		expect(task.description).toContain("Premier paragraphe");
		expect(task.description).toContain(`erplibre-mobile:${clientUuid}`);
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
		expect(proxy.callsOf("project.task", "create").length - before).toBe(1);
		expect(await admin.withMarker("project.task", "description", clientUuid)).toHaveLength(1);
	});

	it("n'écrit que le champ changé dans l'app", async () => {
		const { env, id, taskId } = await sentTask();
		await edit(env, id, (n) => { n.title = "Titre change"; });
		const before = proxy.callsOf("project.task", "write").length;
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
		const writes = proxy.callsOf("project.task", "write").slice(before);
		expect(writes).toHaveLength(1);
		expect(Object.keys(writes[0].args![1])).toEqual(["name"]);
		expect((await admin.read("project.task", taskId, ["name"])).name).toBe("Titre change");
	});

	it("tire dans la note un changement fait sur le serveur", async () => {
		const { env, id, taskId } = await sentTask();
		await nextServerSecond();
		await admin.write("project.task", [taskId], { name: "Renomme dans Odoo", description: "<p>Texte serveur</p>" });
		await env.sync.syncAll(env.creds[0]);
		const stored = (await env.db.getNoteById(id))!;
		expect(stored.title).toBe("Renomme dans Odoo");
		expect(stored.entries.filter((e: any) => e.type === "text").map((e: any) => e.params.text)).toEqual(["Texte serveur"]);
		expect((await env.db.getNotePerServerStatus(id))[env.configIds[0]]).toBe("synced");
	});

	it("garde le texte tapé et le titre tiré quand une sauvegarde suit un pull", async () => {
		const { env, id, taskId } = await sentTask(["Avant"]);
		const since = JSON.parse(JSON.stringify((await env.db.getNoteById(id))!));
		await nextServerSecond();
		await admin.write("project.task", [taskId], { name: "Titre du serveur" });
		await env.sync.syncAll(env.creds[0]);
		// The screen still holds its copy read before the pull, with a paragraph typed since
		const mine = JSON.parse(JSON.stringify(since));
		mine.entries[0].params.text = "Avant, puis tape";
		const { saved } = await env.notes.crud.editSince(id, mine, since);
		expect(saved.title).toBe("Titre du serveur");
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
		const task = await admin.read("project.task", taskId, ["name", "description"]);
		expect(task.name).toBe("Titre du serveur");
		expect(task.description).toContain("Avant, puis tape");
	});

	it("envoie étiquettes, échéance, épingle, archivage et (17+) l'état fait", async () => {
		const tagId = unique("tag");
		const tagName = unique("etiquette");
		const { env, id, taskId } = await sentTask();
		await env.db.addTag({ id: tagId, name: tagName, color: "#6b7280" });
		await edit(env, id, (n) => {
			n.tags = [tagId];
			n.pinned = true;
			n.done = true;
			n.archived = true;
			n.entries.unshift({ id: `${id}-d`, type: "date", params: { date: new Date(2026, 10, 2, 9, 0).toISOString() } });
		});
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
		const fields = ["tag_ids", "priority", "active", "date_deadline", ...(target.version >= 17 ? ["state"] : [])];
		const task = await admin.read("project.task", taskId, fields);
		const tags = await admin.searchRead("project.tags", [["id", "in", task.tag_ids]], ["name"]);
		expect(tags.map((t: any) => t.name)).toEqual([tagName]);
		expect(task.priority).toBe("1");
		expect(task.active).toBe(false);
		if (target.version >= 17) {
			expect(task.state).toBe("1_done");
			expect(task.date_deadline).toMatch(/^2026-11-02 \d\d:\d\d:\d\d$/);
		} else {
			expect(task.date_deadline).toBe("2026-11-02");
		}
	});
});
