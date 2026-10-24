/**
 * A note sent as an opportunity, beside its task or alone: the client and
 * the expected revenue go at creation only, a client gone blocks the
 * creation, and a later change of the note writes its text, not those.
 */
import { appFor, eachVersion, note, unique } from "./harness";
import { FaultProxy } from "./faultProxy";
import { OdooAdmin } from "./odooAdmin";

eachVersion("opportunités", (target) => {
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

	it("crée tâche et opportunité d'une même note, client et revenu sur l'opportunité", async () => {
		const env = await appFor(proxy.via(target));
		const id = unique("note");
		await env.db.addNote(note(id, unique("titre"), ["Besoin du client"]));
		await env.sync.setTarget(id, env.configIds[0], "task", { projectId: null });
		await env.sync.setTarget(id, env.configIds[0], "lead", { partnerId, expectedRevenue: 1250 });
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });

		const link = (await env.db.findNoteLink(id, env.configIds[0], "crm.lead", "create"))!;
		const lead = await admin.read("crm.lead", link.resId, ["type", "partner_id", "expected_revenue", "description"]);
		expect(lead.type).toBe("opportunity");
		expect(lead.partner_id[0]).toBe(partnerId);
		expect(lead.expected_revenue).toBe(1250);
		expect(lead.description).toContain("Besoin du client");
		expect(await env.db.findNoteLink(id, env.configIds[0], "project.task", "create")).toBeTruthy();
		expect((await env.db.getNoteSyncInfo(id)).syncStatus).toBe("synced");

		const current = (await env.db.getNoteById(id))!;
		await env.notes.crud.edit(id, { ...current, title: "Opportunite renommee" });
		const before = proxy.callsOf("crm.lead", "write").length;
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
		const [ids, values] = proxy.callsOf("crm.lead", "write").slice(before)[0].args!;
		expect(ids).toEqual([link.resId]);
		for (const field of ["type", "partner_id", "expected_revenue", "active"]) expect(values).not.toHaveProperty(field);
		expect((await admin.read("crm.lead", link.resId, ["name"])).name).toBe("Opportunite renommee");
	});

	it("bloque, sans la créer, l'opportunité d'un client archivé", async () => {
		const gone = await admin.create("res.partner", { name: unique("client-parti") });
		await admin.write("res.partner", [gone], { active: false });
		const env = await appFor(proxy.via(target));
		const id = unique("note");
		await env.db.addNote(note(id, unique("titre")));
		await env.sync.setTarget(id, env.configIds[0], "lead", { partnerId: gone });
		const before = proxy.callsOf("crm.lead", "create").length;
		await expect(env.sync.pushNote(env.creds[0], id, { userInitiated: true })).rejects.toMatchObject({ reason: "partner_missing" });
		expect(proxy.callsOf("crm.lead", "create").length).toBe(before);
		expect(await env.sync.targetState(id, env.configIds[0], "lead")).toMatchObject({ state: "choose", reason: "partner_missing" });
	});
});
