/**
 * The ground the other scenarios stand on: the app logs in to each server
 * and reads its version, and refuses http while the user has not allowed it.
 */
import { TARGETS, appFor, eachVersion } from "./harness";
import { installLocalStorage } from "../../mobile/erplibre_home_mobile/src/testing/syncTestKit";

eachVersion("connexion", (target) => {
	it("se connecte et lit la version majeure du serveur", async () => {
		const env = await appFor(target);
		const session = await env.sync.authenticate(env.creds[0]);
		expect(session.sessionId).toBeTruthy();
		expect(session.odooMajorVersion).toBe(target.version);
	});

	it("refuse un serveur http tant que l'utilisateur ne l'a pas permis", async () => {
		const env = await appFor(target);
		installLocalStorage({ allowHttp: false });
		await expect(env.sync.authenticate(env.creds[0])).rejects.toSatisfy(
			(e: any) => e?.constructor?.name === "InsecureHttpError",
		);
	});
});

it("a au moins une version d'Odoo à tester", () => {
	expect(TARGETS.length).toBeGreaterThan(0);
});
