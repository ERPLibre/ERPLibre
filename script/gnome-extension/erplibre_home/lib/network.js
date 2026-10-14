/**
 * Network scan helpers. Pure parsers + GJS subprocess dispatcher.
 */

export function parseNmapOG(text) {
    if (typeof text !== 'string' || text === '') return [];
    const seen = new Map();
    for (const line of text.split('\n')) {
        if (!line.startsWith('Host:')) continue;
        const ipMatch = line.match(/^Host:\s+(\S+)/);
        if (!ipMatch) continue;
        const ip = ipMatch[1];
        if (line.includes('Ports:') && /22\/open\/tcp/.test(line)) {
            seen.set(ip, {ip, port22: true});
        } else if (line.includes('Status: Up') && !seen.has(ip)) {
            seen.set(ip, {ip, port22: false});
        }
    }
    return [...seen.values()].filter(h => h.port22);
}

export function deriveCidrFromIpRoute(jsonText) {
    let arr;
    try { arr = JSON.parse(jsonText); }
    catch (_e) { return null; }
    if (!Array.isArray(arr)) return null;
    const def = arr.find(r => r?.dst === 'default');
    if (!def) return null;
    const subnet = arr.find(
        r => r?.dev === def.dev && r?.dst && r.dst.includes('/'));
    return subnet?.dst || null;
}

export function expandCidrV4Slash24(cidr) {
    const m = /^(\d+)\.(\d+)\.(\d+)\.\d+\/24$/.exec(cidr);
    if (!m) throw new Error('expandCidrV4Slash24: only /24 is supported');
    const out = [];
    for (let i = 0; i < 256; i++) out.push(`${m[1]}.${m[2]}.${m[3]}.${i}`);
    return out;
}

/**
 * GJS-only — auto-detect a /24 CIDR via `ip -4 -j route`. Returns null
 * if auto-detection failed.
 */
export async function autoDetectCidrGjs() {
    const {default: GLib} = await import('gi://GLib');
    const [, stdout] = GLib.spawn_command_line_sync('ip -4 -j route');
    return deriveCidrFromIpRoute(
        new TextDecoder().decode(stdout || new Uint8Array()));
}

/**
 * GJS-only — run nmap -p22 --open -oG - on cidr. Resolves to {hosts, error}.
 */
export async function scanNmapGjs(cidr, cancellable) {
    const {default: Gio} = await import('gi://Gio');
    return new Promise(resolve => {
        try {
            const proc = Gio.Subprocess.new(
                ['nmap', '-p22', '--open', '-oG', '-', cidr],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
            proc.communicate_utf8_async(null, cancellable || null, (p, res) => {
                try {
                    const [, stdout] = p.communicate_utf8_finish(res);
                    resolve({hosts: parseNmapOG(stdout), error: null});
                } catch (e) {
                    resolve({hosts: [], error: e.message});
                }
            });
        } catch (e) {
            resolve({hosts: [], error: e.message});
        }
    });
}

/**
 * GJS-only fallback when nmap is missing. nc -z -w1 IP 22 over the /24.
 */
export async function scanNcGjs(cidr, cancellable) {
    const ips = expandCidrV4Slash24(cidr);
    const {default: Gio} = await import('gi://Gio');
    const hosts = [];
    for (const ip of ips) {
        if (cancellable?.is_cancelled?.()) break;
        const ok = await new Promise(resolve => {
            try {
                const proc = Gio.Subprocess.new(
                    ['nc', '-z', '-w1', ip, '22'],
                    Gio.SubprocessFlags.NONE);
                proc.wait_async(null, () => resolve(proc.get_successful()));
            } catch (_e) { resolve(false); }
        });
        if (ok) hosts.push({ip, port22: true});
    }
    return {hosts, error: null};
}

/**
 * GJS-only — best-effort reverse DNS via getent hosts.
 */
export async function reverseDnsGjs(ip) {
    const {default: GLib} = await import('gi://GLib');
    try {
        const [, stdout] = GLib.spawn_command_line_sync(`getent hosts ${ip}`);
        const text = new TextDecoder()
            .decode(stdout || new Uint8Array()).trim();
        const parts = text.split(/\s+/);
        return parts.length >= 2 ? parts[1] : '';
    } catch (_e) { return ''; }
}
