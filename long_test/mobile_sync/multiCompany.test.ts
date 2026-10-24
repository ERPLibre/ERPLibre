/**
 * A user of two companies (mc_user): the app reads both, current first,
 * and a creation goes to the company chosen for it, its calls made in both.
 * The task is created in a project of that company: on 17+ a task without
 * a project has no company.
 */
import { appFor, eachVersion, note, unique } from "./harness";
import { FaultProxy } from "./faultProxy";
import { OdooAdmin } from "./odooAdmin";

eachVersion("multi-société", (target) => {
	let proxy: FaultProxy;
	let admin: OdooAdmin;

	beforeAll(async () => {
		proxy = await FaultProxy.start(target);
		admin = new OdooAdmin(target);
	});
	afterAll(async () => {
		await proxy.stop();
	});

	it("lit les deux sociétés et crée la tâche dans celle choisie", async () => {
		const env = await appFor(proxy.via(target), "multi");
		const { companies } = await env.sync.serverCompanies(env.creds[0], { online: true });
		expect(companies).toHaveLength(2);
		const second = companies[1];
		// The admin of the run joins the second company, whose records its rules hide otherwise
		await admin.write("res.users", [await admin.login()], { company_ids: [[4, second.id]] });
		const both = { allowed_company_ids: companies.map((c) => c.id) };
		const projectId = await admin.create("project.project", { name: unique("projet"), company_id: second.id }, both);

		const id = unique("note");
		await env.db.addNote(note(id, unique("titre")));
		await env.sync.setTarget(id, env.configIds[0], "task", { projectId });
		await env.sync.setCreationCompany(id, env.configIds[0], second.id);
		await env.sync.pushNote(env.creds[0], id, { userInitiated: true });

		const taskId = (await env.db.findNoteLink(id, env.configIds[0], "project.task", "create"))!.resId;
		const [task] = await admin.searchRead("project.task", [["id", "=", taskId]], ["company_id"], { context: both });
		expect(task.company_id[0]).toBe(second.id);
		const [create] = proxy.callsOf("project.task", "create").slice(-1);
		expect(create.kwargs!.context.allowed_company_ids).toEqual([second.id, companies[0].id]);
		expect((await env.sync.serverCompanies(env.creds[0], { online: false })).last).toBe(second.id);
	});
});
