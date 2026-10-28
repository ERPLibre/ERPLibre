/**
 * Odoo's VAPID keys wiped (a restored or neutralised database) against a
 * real Odoo 18 and the run's ntfy, the app as admin (PushScene): the next
 * load registers the same endpoint again under Odoo's new keys, and pushes
 * resume without new keys on the phone.
 *
 * Drawing new VAPID keys drops every device of the server, and the keys
 * are read by every push: a file named *.serial.test.ts runs alone, after
 * the files that run side by side (long_test/mobile_sync.py), so no other
 * case loses its device or reads the keys while they change.
 */
import { eachVersionFrom, unique } from "./harness";
import type { Target } from "./harness";
import { ChatPeer } from "./chatPeer";
import { PushScene } from "./chatPushScene";

eachVersionFrom(18, "chat push VAPID", (target: Target) => {
	if (!target.ntfy) {
		describe.skip("ntfy absent: notification tests skipped", () => {
			it("the ntfy command is not installed", () => {});
		});
		return;
	}
	let peer: ChatPeer;
	const scene = new PushScene(target, target.ntfy, () => peer);

	beforeAll(async () => {
		peer = await ChatPeer.open(target);
	});
	afterEach(() => scene.end());

	it("a VAPID wipe is healed by the next load", async () => {
		const { env, src, row } = await scene.linked();
		const keys = env.pushNative.keysOf(src.configId);
		expect(await peer.pushDevices(row.endpoint!)).toBe(1);
		await peer.wipeVapid();
		env.push.newSession();
		await env.chat.load(src);
		await env.push.idle();
		expect(await peer.pushDevices(row.endpoint!)).toBe(1);
		const healed = await env.chat.repo.pushRow(src.configId);
		expect(healed.endpoint).toBe(row.endpoint);
		expect(healed.vapidKey).not.toBe(row.vapidKey);
		expect(env.pushNative.keysOf(src.configId).topic).toBe(keys.topic);
		const text = unique("après la remise à zéro");
		await peer.post(await peer.chat(peer.adminPartnerId), text);
		await scene.pushed(keys, text);
	});
});
