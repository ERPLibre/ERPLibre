/**
 * A note posted as a logged note in a record's chatter: posted once,
 * edited when the note's text changes and only then, kept as history when
 * the message is deleted on the server.
 */
import { appFor, eachVersion, note, unique } from "./harness";
import { FaultProxy } from "./faultProxy";
import { OdooAdmin } from "./odooAdmin";

eachVersion("messages", (target) => {
	let proxy: FaultProxy;
	let admin: OdooAdmin;
	let leadId: number;

	beforeAll(async () => {
		proxy = await FaultProxy.start(target);
		admin = new OdooAdmin(target);
		leadId = await admin.create("crm.lead", { name: unique("piste"), type: "opportunity" });
	});
	afterAll(async () => {
		await proxy.stop();
	});

	const onLead = () => ({ resModel: "crm.lead", resId: leadId, resName: "piste", typeId: null, deadline: null, userId: null });
	const edits = () => proxy.calls.filter((c) => c.path.endsWith("/mail/message/update_content"));

	it("publie une note interne, la modifie quand le texte change et seulement alors", async () => {
		const env = await appFor(proxy.via(target));
		const id = unique("note");
		await env.db.addNote(note(id, "Appel", ["Ils acceptent"]));
		await env.sync.setMessage(id, env.configIds[0], onLead());
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
		const [link] = (await env.db.getNoteLinks(id)).filter((l) => l.kind === "message");
		const message = await admin.read("mail.message", link.resId, ["model", "res_id", "body", "message_type"]);
		expect(message).toMatchObject({ model: "crm.lead", res_id: leadId, message_type: "comment" });
		expect(message.body).toContain("Ils acceptent");

		const editsBefore = edits().length;
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
		expect(edits().length).toBe(editsBefore);

		const current = (await env.db.getNoteById(id))!;
		await env.notes.crud.edit(id, { ...current, title: "Appel rappele" });
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
		expect(edits().length).toBe(editsBefore + 1);
		expect((await admin.read("mail.message", link.resId, ["body"])).body).toContain("Appel rappele");
		expect(proxy.callsOf("crm.lead", "message_post").filter((c) => c.args?.[0]?.[0] === leadId)).toHaveLength(1);
	});

	it("garde en historique un message supprimé sur le serveur, sans erreur", async () => {
		const env = await appFor(proxy.via(target));
		const id = unique("note");
		await env.db.addNote(note(id, "Disparu"));
		await env.sync.setMessage(id, env.configIds[0], onLead());
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
		const [link] = (await env.db.getNoteLinks(id)).filter((l) => l.kind === "message");
		await admin.unlink("mail.message", [link.resId]);

		const current = (await env.db.getNoteById(id))!;
		await env.notes.crud.edit(id, { ...current, title: "Change apres suppression" });
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
		expect((await env.sync.attachedStates(id, env.configIds[0])).find((s) => s.kind === "message")!.state).toBe("deleted");
	});
});
