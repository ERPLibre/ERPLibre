/**
 * A proxy between the app and one Odoo server: it relays every request and
 * records each JSON-RPC call, so a scenario checks what crossed the wire
 * (one create only, a write of the changed fields only), and it breaks the
 * link on demand: down (every request cut, as a network gone), or the
 * response of one chosen call lost after Odoo ran it (the case a retry must
 * adopt instead of creating again).
 */
import http from "node:http";
import type { AddressInfo } from "node:net";
import type { Target } from "./harness";

export interface RpcCall {
	path: string;
	model?: string;
	method?: string;
	args?: any[];
	kwargs?: Record<string, any>;
}

export class FaultProxy {
	readonly calls: RpcCall[] = [];
	/** Every request cut before it reaches Odoo. */
	down = false;
	private dropNext: ((call: RpcCall) => boolean) | null = null;

	private constructor(private server: http.Server, readonly url: string, private upstream: string) {}

	/** A proxy on a free local port in front of target. */
	static async start(target: Target): Promise<FaultProxy> {
		let proxy: FaultProxy;
		const server = http.createServer((req, res) => {
			void proxy.relay(req, res);
		});
		await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
		const { port } = server.address() as AddressInfo;
		proxy = new FaultProxy(server, `http://127.0.0.1:${port}`, target.url);
		return proxy;
	}

	/** The target as the app should see it: through this proxy. */
	via(target: Target): Target {
		return { ...target, url: this.url };
	}

	/** Loses the response of the next call matching: Odoo runs it, the app never hears back. */
	loseResponseOf(match: (call: RpcCall) => boolean): void {
		this.dropNext = match;
	}

	/** The calls of model.method recorded so far. */
	callsOf(model: string, method: string): RpcCall[] {
		return this.calls.filter((c) => c.model === model && c.method === method);
	}

	async stop(): Promise<void> {
		this.server.closeAllConnections();
		await new Promise<void>((resolve) => this.server.close(() => resolve()));
	}

	private async relay(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
		const chunks: Buffer[] = [];
		for await (const chunk of req) chunks.push(chunk as Buffer);
		const body = Buffer.concat(chunks);
		let params: any = {};
		try {
			params = JSON.parse(body.toString("utf8")).params ?? {};
		} catch {
			// Not JSON: recorded by its path only
		}
		const call: RpcCall = { path: req.url ?? "", model: params.model, method: params.method, args: params.args, kwargs: params.kwargs };
		this.calls.push(call);
		if (this.down) {
			req.socket.destroy();
			return;
		}
		const headers: Record<string, string> = {};
		for (const name of ["content-type", "cookie", "x-openerp-session-id"]) {
			const value = req.headers[name];
			if (typeof value === "string") headers[name] = value;
		}
		let upstream: Response;
		try {
			upstream = await fetch(this.upstream + (req.url ?? ""), {
				method: req.method, headers, body: req.method === "POST" ? body : undefined,
			});
		} catch {
			req.socket.destroy();
			return;
		}
		const payload = Buffer.from(await upstream.arrayBuffer());
		if (this.dropNext?.(call)) {
			this.dropNext = null;
			req.socket.destroy();
			return;
		}
		const out: Record<string, string | string[]> = {};
		const type = upstream.headers.get("content-type");
		if (type) out["content-type"] = type;
		const cookies = upstream.headers.getSetCookie();
		if (cookies.length) out["set-cookie"] = cookies;
		res.writeHead(upstream.status, out);
		res.end(payload);
	}
}
