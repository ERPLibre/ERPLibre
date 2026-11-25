/**
 * The files of a note sent as ir.attachment of its record, within the
 * user's settings: a file over the size limit or not found on the device is
 * left out and reported, and with Wi-Fi only set a file waits off Wi-Fi,
 * then goes at the next push on Wi-Fi.
 */
import { appFor, eachVersion, memoryAttachmentIO, note, unique } from "./harness";
import type { SyncEnv } from "./harness";
import { FaultProxy } from "./faultProxy";
import { OdooAdmin } from "./odooAdmin";

eachVersion("pièces jointes", (target) => {
	let proxy: FaultProxy;
	let admin: OdooAdmin;

	beforeAll(async () => {
		proxy = await FaultProxy.start(target);
		admin = new OdooAdmin(target);
	});
	afterAll(async () => {
		await proxy.stop();
	});

	const photo = (id: string, path: string) => ({ id, type: "photo", params: { path } });
	const settings = (value: { wifiOnly: boolean; maxMb: number | null }) =>
		localStorage.setItem("options.sync.attachments", JSON.stringify(value));
	const attached = async (taskId: number) =>
		(await admin.searchRead("ir.attachment", [["res_model", "=", "project.task"], ["res_id", "=", taskId]], ["name"]))
			.map((a: any) => a.name).sort();

	async function sent(env: SyncEnv, entries: any[]) {
		const id = unique("note");
		await env.db.addNote(note(id, unique("titre"), [], { entries }));
		await env.sync.setTarget(id, env.configIds[0], "task", { projectId: null });
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
		return { id, taskId: (await env.db.findNoteLink(id, env.configIds[0], "project.task", "create"))!.resId };
	}

	it("joint un fichier, laisse de côté le trop gros et l'introuvable, et les signale", async () => {
		const env = await appFor(proxy.via(target));
		settings({ wifiOnly: false, maxMb: 0.001 });
		env.sync.attachmentIO = memoryAttachmentIO({ files: { "file:///p/petit.jpg": "x".repeat(200), "file:///p/gros.jpg": "x".repeat(4000) } });
		const { id, taskId } = await sent(env, [
			photo("a", "file:///p/petit.jpg"), photo("b", "file:///p/gros.jpg"), photo("c", "file:///p/absent.jpg"),
		]);
		expect(await attached(taskId)).toEqual(["petit.jpg"]);
		const skipped = await env.sync.skippedFiles(id);
		expect(skipped.map((s) => [s.name, s.reason])).toEqual([["gros.jpg", 4000], ["absent.jpg", "missing"]]);
	});

	it("retient les fichiers hors Wi-Fi, puis les envoie une fois en Wi-Fi", async () => {
		const env = await appFor(proxy.via(target));
		settings({ wifiOnly: true, maxMb: null });
		const io = memoryAttachmentIO({ files: { "file:///p/plan.jpg": "plan" }, wifi: false });
		env.sync.attachmentIO = io;
		const { id, taskId } = await sent(env, [photo("a", "file:///p/plan.jpg")]);
		expect(await attached(taskId)).toEqual([]);
		expect(await env.sync.unsentFiles(id)).toEqual(["plan.jpg"]);

		io.wifi = true;
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
		expect(await attached(taskId)).toEqual(["plan.jpg"]);
		expect(await env.sync.unsentFiles(id)).toEqual([]);
	});
});
