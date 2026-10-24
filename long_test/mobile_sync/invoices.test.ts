/**
 * A note drafted as an invoice, customer or vendor: its type, partner,
 * lines and product at creation, its text as the narration afterwards, and
 * an invoice tied to the note's opportunity by a message in each chatter
 * (no field ties them on a server without a custom module).
 */
import { appFor, eachVersion, note, unique } from "./harness";
import { FaultProxy } from "./faultProxy";
import { OdooAdmin } from "./odooAdmin";

eachVersion("factures", (target) => {
	let proxy: FaultProxy;
	let admin: OdooAdmin;
	let partnerId: number;
	let productId: number;

	beforeAll(async () => {
		proxy = await FaultProxy.start(target);
		admin = new OdooAdmin(target);
		partnerId = await admin.create("res.partner", { name: unique("client") });
		productId = await admin.create("product.product", { name: unique("heure"), list_price: 80 });
	});
	afterAll(async () => {
		await proxy.stop();
	});

	const invoice = (moveType: "out_invoice" | "in_invoice", linkKind: "lead" | null = null) => ({
		moveType, partnerId, invoiceDate: "2026-11-01", ref: unique("ref"), extra: {}, linkKind,
		lines: [
			{ name: "Travail", quantity: 2, priceUnit: 50, productId },
			{ name: "Deplacement", quantity: 1, priceUnit: null, productId },
		],
	});

	for (const moveType of ["out_invoice", "in_invoice"] as const) {
		it(`crée le brouillon ${moveType}, puis n'écrit que sa narration`, async () => {
			const env = await appFor(proxy.via(target));
			const id = unique("note");
			await env.db.addNote(note(id, "Chantier", ["Fait sur place"]));
			await env.sync.setTarget(id, env.configIds[0], "invoice", invoice(moveType));
			await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
			const link = (await env.db.findNoteLink(id, env.configIds[0], "account.move", "create"))!;
			const move = await admin.read("account.move", link.resId, ["move_type", "state", "partner_id", "narration", "invoice_line_ids"]);
			expect(move).toMatchObject({ move_type: moveType, state: "draft" });
			expect(move.partner_id[0]).toBe(partnerId);
			expect(move.narration).toContain("Fait sur place");
			const lines = await admin.searchRead("account.move.line", [["id", "in", move.invoice_line_ids], ["display_type", "=", "product"]],
				["name", "quantity", "price_unit", "product_id"]);
			expect(lines.map((l: any) => [l.name, l.quantity, l.product_id[0]]).sort()).toEqual([["Deplacement", 1, productId], ["Travail", 2, productId]]);
			expect(lines.find((l: any) => l.name === "Travail").price_unit).toBe(50);

			const current = (await env.db.getNoteById(id))!;
			await env.notes.crud.edit(id, { ...current, title: "Chantier termine" });
			const before = proxy.callsOf("account.move", "write").length;
			await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
			const [, values] = proxy.callsOf("account.move", "write").slice(before)[0].args!;
			expect(Object.keys(values)).toEqual(["narration"]);
			expect((await admin.read("account.move", link.resId, ["narration"])).narration).toContain("Chantier termine");
		});
	}

	it("lie la facture à l'opportunité de la note par un message dans chaque fil", async () => {
		const env = await appFor(proxy.via(target));
		const id = unique("note");
		await env.db.addNote(note(id, "Vendu"));
		await env.sync.setTarget(id, env.configIds[0], "lead", { partnerId });
		await env.sync.setTarget(id, env.configIds[0], "invoice", invoice("out_invoice", "lead"));
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
		const leadId = (await env.db.findNoteLink(id, env.configIds[0], "crm.lead", "create"))!.resId;
		const invoiceLink = (await env.db.findNoteLink(id, env.configIds[0], "account.move", "create"))!;
		expect(invoiceLink.params).toMatchObject({ crossLinked: true });
		const onLead = await admin.searchRead("mail.message", [["model", "=", "crm.lead"], ["res_id", "=", leadId]], ["body"]);
		const onInvoice = await admin.searchRead("mail.message", [["model", "=", "account.move"], ["res_id", "=", invoiceLink.resId]], ["body"]);
		expect(onLead.some((m: any) => m.body.includes(`data-oe-id="${invoiceLink.resId}"`))).toBe(true);
		expect(onInvoice.some((m: any) => m.body.includes(`data-oe-id="${leadId}"`))).toBe(true);
	});
});
