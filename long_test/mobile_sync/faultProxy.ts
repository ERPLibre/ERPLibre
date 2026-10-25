/**
 * A proxy between the app and one Odoo server: it relays every request and
 * records each JSON-RPC call, so a scenario checks what crossed the wire
 * (one create only, a write of the changed fields only), and it breaks the
 * link on demand: down (every request cut, as a network gone), or the
 * response of one chosen call lost after Odoo ran it (the case a retry must
 * adopt instead of creating again). WebSocket upgrades (/websocket) are piped
 * as raw TCP to Odoo; down refuses them and cutSockets() drops the live ones.
 */
import http from "node:http";
import net from "node:net";
import type { AddressInfo, Socket } from "node:net";
import type { Target } from "./harness";

export interface RpcCall {
	path: string;
	model?: string;
	method?: string;
	args?: any[];
	kwargs?: Record<string, any>;
	/** The raw JSON-RPC params, for routes (/mail/message/post) that carry no model/method. */
	params?: Record<string, any>;
}

export class FaultProxy {
	readonly calls: RpcCall[] = [];
	/** Every request cut before it reaches Odoo. */
	down = false;
	private dropNext: ((call: RpcCall) => boolean) | null = null;
	/** Both ends of every upgraded (websocket) connection still open. */
	private upgraded = new Set<Socket>();

	private constructor(private server: http.Server, readonly url: string, private upstream: string) {}

	/** A proxy on a free local port in front of target. */
	static async start(target: Target): Promise<FaultProxy> {
		let proxy: FaultProxy;
		const server = http.createServer((req, res) => {
			void proxy.relay(req, res);
		});
		server.on("upgrade", (req, socket, head) => proxy.tunnel(req, socket as Socket, head));
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

	/** Drops every live websocket; the app sees a closed connection and reconnects. */
	cutSockets(): void {
		for (const socket of this.upgraded) socket.destroy();
		this.upgraded.clear();
	}

	async stop(): Promise<void> {
		this.cutSockets();
		this.server.closeAllConnections();
		await new Promise<void>((resolve) => this.server.close(() => resolve()));
	}

	/** Pipes an upgrade request and what follows it, raw, to Odoo; refused while down. */
	private tunnel(req: http.IncomingMessage, socket: Socket, head: Buffer): void {
		this.calls.push({ path: req.url ?? "" });
		if (this.down) {
			socket.destroy();
			return;
		}
		const { hostname, port } = new URL(this.upstream);
		const remote = net.connect(Number(port) || 80, hostname);
		this.upgraded.add(socket);
		this.upgraded.add(remote);
		const forget = () => {
			this.upgraded.delete(socket);
			this.upgraded.delete(remote);
			socket.destroy();
			remote.destroy();
		};
		socket.on("error", forget);
		remote.on("error", (error) => {
			console.debug(`faultProxy: upgrade upstream error on ${req.url}: ${error.message}`);
			forget();
		});
		socket.on("close", forget);
		remote.on("close", forget);
		remote.on("connect", () => {
			const lines = [`${req.method} ${req.url} HTTP/${req.httpVersion}`];
			for (let i = 0; i < req.rawHeaders.length; i += 2) {
				lines.push(`${req.rawHeaders[i]}: ${req.rawHeaders[i + 1]}`);
			}
			remote.write(lines.join("\r\n") + "\r\n\r\n");
			if (head.length) remote.write(head);
			socket.pipe(remote);
			remote.pipe(socket);
		});
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
		const call: RpcCall = { path: req.url ?? "", model: params.model, method: params.method, args: params.args, kwargs: params.kwargs, params };
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
