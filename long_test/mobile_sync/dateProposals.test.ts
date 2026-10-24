/**
 * A deadline changed on the server is proposed to the user, never applied
 * on its own: accepted, it reaches the note; refused, the note keeps its
 * date until the server's changes again. A deadline the app's calendar
 * wrote itself is not proposed back.
 */
import { appFor, eachVersion, note, unique, nextServerSecond } from "./harness";
import type { SyncEnv } from "./harness";
import { FaultProxy } from "./faultProxy";
import { OdooAdmin } from "./odooAdmin";

eachVersion("dates proposées", (target) => {
	let proxy: FaultProxy;
	let admin: OdooAdmin;

	beforeAll(async () => {
		proxy = await FaultProxy.start(target);
		admin = new OdooAdmin(target);
	});
	afterAll(async () => {
		await proxy.stop();
	});

	const dayEntry = (id: string, day: number) => ({ id: `${id}-d`, type: "date", params: { date: new Date(2026, 10, day, 9, 0).toISOString() } });
	/** Odoo's value of a deadline on that day: a Date in 16, a Datetime in 17+. */
	const deadline = (day: number) => `2026-11-${String(day).padStart(2, "0")}${target.version >= 17 ? " 12:00:00" : ""}`;
	const noteDay = async (env: SyncEnv, id: string) => {
		const entry = (await env.db.getNoteById(id))!.entries.find((e: any) => e.type === "date");
		return entry ? new Date((entry.params as any).date).getDate() : null;
	};

	/** A note dated the 2nd sent as a task, whose deadline the server then moves to day. */
	async function moved(day: number) {
		const env = await appFor(proxy.via(target));
		const id = unique("note");
		await env.db.addNote(note(id, unique("titre"), ["Texte"], { entries: [dayEntry(id, 2)] }));
		await env.sync.setTarget(id, env.configIds[0], "task", { projectId: null });
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
		const link = (await env.db.findNoteLink(id, env.configIds[0], "project.task", "create"))!;
		await nextServerSecond();
		await admin.write("project.task", [link.resId], { date_deadline: deadline(day) });
		await env.sync.syncAll(env.creds[0]);
		return { env, id, link };
	}

	it("propose la date du serveur sans la changer, puis la prend une fois acceptée", async () => {
		const { env, id, link } = await moved(9);
		expect(await noteDay(env, id)).toBe(2);
		expect((await env.sync.dateProposals(id)).map((p) => p.to)).toEqual(["2026-11-09"]);
		await env.sync.syncAll(env.creds[0]);
		expect(await env.sync.dateProposals(id)).toHaveLength(1);

		await env.sync.answerDateProposal(id, link.id, true);
		expect(await noteDay(env, id)).toBe(9);
		const before = proxy.callsOf("project.task", "write").length;
		await env.sync.syncAll(env.creds[0]);
		expect(await env.sync.dateProposals(id)).toEqual([]);
		const writes = proxy.callsOf("project.task", "write").slice(before);
		expect(writes.some((c) => "date_deadline" in c.args![1])).toBe(false);
		expect((await admin.read("project.task", link.resId, ["date_deadline"])).date_deadline).toBe(deadline(9));
	});

	it("garde la date de la note après un refus, et redemande au changement suivant du serveur", async () => {
		const { env, id, link } = await moved(5);
		await env.sync.answerDateProposal(id, link.id, false);
		expect(await noteDay(env, id)).toBe(2);
		await env.sync.syncAll(env.creds[0]);
		expect(await env.sync.dateProposals(id)).toEqual([]);
		await nextServerSecond();
		await admin.write("project.task", [link.resId], { date_deadline: deadline(7) });
		await env.sync.syncAll(env.creds[0]);
		expect((await env.sync.dateProposals(id)).map((p) => p.to)).toEqual(["2026-11-07"]);
	});

	it("ne repropose pas l'échéance que le calendrier de l'app vient d'écrire", async () => {
		const env = await appFor(proxy.via(target));
		const partnerId = await admin.create("res.partner", { name: unique("client") });
		const id = unique("note");
		await env.db.addNote(note(id, "Rendez-vous", [], { entries: [dayEntry(id, 2)] }));
		await env.sync.setActivity(id, env.configIds[0], {
			resModel: "res.partner", resId: partnerId, typeId: null, deadline: "2026-11-02", userId: null,
		});
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
		const link = (await env.db.getNoteLinks(id)).find((l) => l.kind === "activity")!;
		await nextServerSecond();
		await env.sync.calendar.reschedule(env.creds[0], {
			configId: env.configIds[0], resId: link.resId, resModel: "res.partner", recordId: partnerId, recordName: "client",
			typeId: null, typeName: null, summary: "", deadline: "2026-11-02", userId: null, userName: null, done: false,
			dateDone: null, pending: false, fetchedAt: new Date().toISOString(),
		} as any, "2026-11-20", { online: true });
		expect((await admin.read("mail.activity", link.resId, ["date_deadline"])).date_deadline).toBe("2026-11-20");
		await env.sync.syncAll(env.creds[0]);
		expect(await env.sync.dateProposals(id)).toEqual([]);
		expect(await noteDay(env, id)).toBe(2);
	});
});
