/**
 * The server side of a scenario: an Odoo user's own JSON-RPC session
 * (/jsonrpc, execute_kw), apart from the app's, to set data up as another
 * user would and to check what the app wrote.
 */
import type { Login, Target } from "./harness";

export class OdooAdmin {
	private uid: number | null = null;
	private sessionCookie: string | null = null;

	constructor(private target: Target, private user: Login = target.admin) {}

	/** The url of the server this session talks to. */
	get url(): string {
		return this.target.url;
	}

	private async call(service: string, method: string, args: any[]): Promise<any> {
		const response = await fetch(`${this.target.url}/jsonrpc`, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: { service, method, args } }),
		});
		const body: any = await response.json();
		if (body.error) {
			const data = body.error.data ?? {};
			throw new Error(`${data.name ?? "Odoo"}: ${data.message ?? body.error.message}`);
		}
		return body.result;
	}

	async login(): Promise<number> {
		if (this.uid === null) {
			this.uid = await this.call("common", "login", [this.target.database, this.user.login, this.user.password]);
			if (!this.uid) throw new Error(`login refusé pour ${this.user.login} sur ${this.target.url}`);
		}
		return this.uid;
	}

	/** Opens a web session as this user, keeping its session_id cookie for jsonRoute. */
	async sessionLogin(): Promise<void> {
		const response = await fetch(`${this.target.url}/web/session/authenticate`, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				jsonrpc: "2.0", method: "call",
				params: { db: this.target.database, login: this.user.login, password: this.user.password },
			}),
		});
		const body: any = await response.json();
		if (body.error || !body.result?.uid) throw new Error(`session refusée pour ${this.user.login} sur ${this.target.url}`);
		const cookie = response.headers.getSetCookie().map((c) => c.split(";")[0]).find((c) => c.startsWith("session_id="));
		if (!cookie) throw new Error("pas de cookie session_id");
		this.sessionCookie = cookie;
	}

	/** The session_id cookie sessionLogin() keeps, as a Cookie header value. */
	get cookie(): string {
		if (!this.sessionCookie) throw new Error("sessionLogin() d'abord");
		return this.sessionCookie;
	}

	/** POSTs JSON-RPC params to a route (/mail/message/post, ...) as this user's browser would. */
	async jsonRoute(path: string, params: Record<string, any> = {}): Promise<any> {
		if (!this.sessionCookie) throw new Error("sessionLogin() d'abord");
		const response = await fetch(`${this.target.url}${path}`, {
			method: "POST",
			headers: { "Content-Type": "application/json", Cookie: this.sessionCookie },
			body: JSON.stringify({ jsonrpc: "2.0", method: "call", params }),
		});
		const body: any = await response.json();
		if (body.error) {
			const data = body.error.data ?? {};
			throw new Error(`${data.name ?? "Odoo"}: ${data.message ?? body.error.message}`);
		}
		return body.result;
	}

	/** model.method(*args, **kwargs) as this user. */
	async execute(model: string, method: string, args: any[] = [], kwargs: Record<string, any> = {}): Promise<any> {
		const uid = await this.login();
		return this.call("object", "execute_kw", [this.target.database, uid, this.user.password, model, method, args, kwargs]);
	}

	create(model: string, values: Record<string, any>, context: Record<string, any> = {}): Promise<number> {
		return this.execute(model, "create", [values], { context });
	}

	write(model: string, ids: number[], values: Record<string, any>): Promise<boolean> {
		return this.execute(model, "write", [ids, values]);
	}

	searchRead(model: string, domain: any[], fields: string[], kwargs: Record<string, any> = {}): Promise<any[]> {
		return this.execute(model, "search_read", [domain], { fields, ...kwargs });
	}

	async read(model: string, id: number, fields: string[]): Promise<any> {
		const rows = await this.searchRead(model, [["id", "=", id]], fields, { context: { active_test: false } });
		return rows[0] ?? null;
	}

	unlink(model: string, ids: number[]): Promise<boolean> {
		return this.execute(model, "unlink", [ids]);
	}

	/** The records whose field holds the app's marker of the note's creation. */
	withMarker(model: string, field: string, clientUuid: string, fields: string[] = ["id"]): Promise<any[]> {
		return this.searchRead(model, [[field, "ilike", `erplibre-mobile:${clientUuid}`]], fields, { context: { active_test: false } });
	}
}
