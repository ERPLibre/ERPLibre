/**
 * Activities a note schedules on a record it did not create: created on
 * the record chosen, its title and text written later, marked done with the
 * note. Done, the activity leaves the record's live ones: deleted, or
 * archived on 17+ when its type keeps done activities (keep_done).
 */
import { appFor, eachVersion, note, unique } from "./harness";
import { FaultProxy } from "./faultProxy";
import { OdooAdmin } from "./odooAdmin";

eachVersion("activités", (target) => {
	let proxy: FaultProxy;
	let admin: OdooAdmin;
	let partnerId: number;

	beforeAll(async () => {
		proxy = await FaultProxy.start(target);
		admin = new OdooAdmin(target);
		partnerId = await admin.create("res.partner", { name: unique("client") });
	});
	afterAll(async () => {
		await proxy.stop();
	});

	const onPartner = () => ({
		resModel: "res.partner", resId: partnerId, resName: "client", typeId: null, deadline: "2026-11-02", userId: null,
	});

	it("crée l'activité sur le client, l'écrit, puis la marque faite avec la note", async () => {
		const env = await appFor(proxy.via(target));
		const id = unique("note");
		await env.db.addNote(note(id, "Rappeler", ["Demander la soumission"]));
		await env.sync.setActivity(id, env.configIds[0], onPartner());
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
		expect(proxy.callsOf("project.task", "create")).toHaveLength(0);

		const [link] = (await env.db.getNoteLinks(id)).filter((l) => l.kind === "activity");
		const activity = await admin.read("mail.activity", link.resId, ["res_model", "res_id", "summary", "note", "date_deadline"]);
		expect(activity).toMatchObject({ res_model: "res.partner", res_id: partnerId, summary: "Rappeler", date_deadline: "2026-11-02" });
		expect(activity.note).toContain("Demander la soumission");

		let current = (await env.db.getNoteById(id))!;
		await env.notes.crud.edit(id, { ...current, title: "Rappeler demain" });
		const before = proxy.callsOf("mail.activity", "write").length;
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
		const [, values] = proxy.callsOf("mail.activity", "write").slice(before)[0].args!;
		expect(Object.keys(values)).toEqual(["summary"]);
		expect((await admin.read("mail.activity", link.resId, ["summary"])).summary).toBe("Rappeler demain");

		current = (await env.db.getNoteById(id))!;
		await env.notes.crud.edit(id, { ...current, done: true });
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
		expect((await env.sync.activityStates(id, env.configIds[0]))[0].state).toBe("done");
		expect(await admin.searchRead("mail.activity", [["id", "=", link.resId]], ["id"])).toEqual([]);
	});

	it("garde en historique une activité supprimée sur le serveur, la note quittant sa file", async () => {
		const env = await appFor(proxy.via(target));
		const id = unique("note");
		await env.db.addNote(note(id, "A supprimer"));
		await env.sync.setActivity(id, env.configIds[0], onPartner());
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
		const [link] = (await env.db.getNoteLinks(id)).filter((l) => l.kind === "activity");
		await admin.unlink("mail.activity", [link.resId]);

		const current = (await env.db.getNoteById(id))!;
		await env.notes.crud.edit(id, { ...current, title: "Change apres suppression" });
		await env.sync.syncAll(env.creds[0]);
		expect((await env.sync.activityStates(id, env.configIds[0]))[0].state).toBe("deleted");
		expect(await env.sync.pendingNoteIds(env.configIds[0])).not.toContain(id);
	});
});
