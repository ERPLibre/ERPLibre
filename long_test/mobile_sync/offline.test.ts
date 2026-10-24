/**
 * A creation the network cut: retried after its delay, in the background
 * as on a tap, it reaches Odoo once. An answer lost after Odoo ran the
 * create is found again by its marker once the quiet window is over, and
 * two records carrying the marker wait for the user to pick one.
 *
 * The quiet window (3 minutes) and the retry delay pass on a faked Date:
 * only the app's clock moves, the requests stay real.
 */
import { appFor, eachVersion, note, unique } from "./harness";
import type { SyncEnv } from "./harness";
import { FaultProxy } from "./faultProxy";
import { OdooAdmin } from "./odooAdmin";

const QUIET_WINDOW_PASSED_MS = 4 * 60 * 1000;

eachVersion("hors ligne", (target) => {
	let proxy: FaultProxy;
	let admin: OdooAdmin;

	beforeAll(async () => {
		proxy = await FaultProxy.start(target);
		admin = new OdooAdmin(target);
	});
	afterAll(async () => {
		await proxy.stop();
	});
	afterEach(() => {
		proxy.down = false;
		vi.useRealTimers();
	});

	const isTaskCreate = (c: { model?: string; method?: string }) => c.model === "project.task" && c.method === "create";
	const later = (ms: number) => vi.setSystemTime(Date.now() + ms);

	async function queued(): Promise<{ env: SyncEnv; id: string }> {
		vi.useFakeTimers({ toFake: ["Date"] });
		const env = await appFor(proxy.via(target));
		const id = unique("note");
		await env.db.addNote(note(id, unique("titre"), ["Ecrit hors ligne"]));
		await env.sync.setTarget(id, env.configIds[0], "task", { projectId: null });
		return { env, id };
	}

	const markedTasks = async (env: SyncEnv, id: string) => {
		const [op] = await env.db.getOutboxOpsForNote(id);
		const uuid = op?.clientUuid ?? (await env.db.findNoteLink(id, env.configIds[0], "project.task", "create"))!.clientUuid!;
		return admin.withMarker("project.task", "description", uuid);
	};

	it("garde la création en file réseau coupé, puis crée une seule fois au retour du réseau", async () => {
		const { env, id } = await queued();
		proxy.down = true;
		await expect(env.sync.pushNote(env.creds[0], id, { userInitiated: true })).rejects.toThrow();
		const [op] = await env.db.getOutboxOpsForNote(id);
		expect(op).toMatchObject({ status: "failed", attempts: 1 });

		proxy.down = false;
		await env.sync.syncAll(env.creds[0], undefined, { force: true });
		expect(await markedTasks(env, id)).toHaveLength(1);
		expect(await env.db.getOutboxOpsForNote(id)).toEqual([]);
		expect((await env.db.getNoteSyncInfo(id)).syncStatus).toBe("synced");
	});

	it("en arrière-plan, attend le délai de reprise, puis la reprend", async () => {
		const { env, id } = await queued();
		proxy.down = true;
		await expect(env.sync.pushNote(env.creds[0], id, { userInitiated: true })).rejects.toThrow();
		proxy.down = false;
		const creates = proxy.calls.filter(isTaskCreate).length;
		expect(await env.sync.hasDueWork(env.configIds[0])).toBe(false);
		await env.sync.syncAll(env.creds[0]);
		expect(proxy.calls.filter(isTaskCreate).length).toBe(creates);

		later(QUIET_WINDOW_PASSED_MS);
		expect(await env.sync.hasDueWork(env.configIds[0])).toBe(true);
		await env.sync.syncAll(env.creds[0]);
		expect(await markedTasks(env, id)).toHaveLength(1);
		expect(await env.sync.hasDueWork(env.configIds[0])).toBe(false);
	});

	it("adopte la tâche d'une réponse perdue au lieu d'en créer une seconde", async () => {
		const { env, id } = await queued();
		proxy.loseResponseOf(isTaskCreate);
		await expect(env.sync.pushNote(env.creds[0], id, { userInitiated: true })).rejects.toThrow();
		const [made] = await markedTasks(env, id);
		expect(made).toBeDefined();

		later(QUIET_WINDOW_PASSED_MS);
		const creates = proxy.calls.filter(isTaskCreate).length;
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });
		expect(proxy.calls.filter(isTaskCreate).length).toBe(creates);
		expect((await env.db.findNoteLink(id, env.configIds[0], "project.task", "create"))!.resId).toBe(made.id);
		expect(await markedTasks(env, id)).toHaveLength(1);
	});

	it("demande laquelle quand deux tâches portent le marqueur, puis lie celle choisie", async () => {
		const { env, id } = await queued();
		proxy.loseResponseOf(isTaskCreate);
		await expect(env.sync.pushNote(env.creds[0], id, { userInitiated: true })).rejects.toThrow();
		const [made] = await markedTasks(env, id);
		const original = await admin.read("project.task", made.id, ["name", "description"]);
		const twin = await admin.create("project.task", { name: original.name, description: original.description });

		later(QUIET_WINDOW_PASSED_MS);
		await expect(env.sync.pushNote(env.creds[0], id, { userInitiated: true })).rejects.toMatchObject({ reason: "ambiguous" });
		const [op] = await env.db.getOutboxOpsForNote(id);
		expect([...op.params.candidates].sort()).toEqual([made.id, twin].sort());

		const creates = proxy.calls.filter(isTaskCreate).length;
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true, adoptTaskId: twin });
		expect(proxy.calls.filter(isTaskCreate).length).toBe(creates);
		expect((await env.db.findNoteLink(id, env.configIds[0], "project.task", "create"))!.resId).toBe(twin);
	});
});
