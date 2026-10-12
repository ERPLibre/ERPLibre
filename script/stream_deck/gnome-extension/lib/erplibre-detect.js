/**
 * Local ERPLibre detection helpers. Pure parsers + a GJS-only globber.
 */
import {uuid4} from './settings.js';

export function expandHome(path, home) {
    if (typeof path !== 'string') return '';
    if (path.startsWith('~/')) return `${home}/${path.slice(2)}`;
    if (path === '~') return home;
    return path;
}

const ASSIGNMENT_RE = /^\s*export\s+([A-Z_][A-Z0-9_]*)=(?:"([^"]*)"|'([^']*)'|([^\s#]*))\s*(?:#.*)?$/;

export function parseEnvVarSh(text) {
    const out = {};
    if (typeof text !== 'string' || text === '') return out;
    for (const line of text.split('\n')) {
        const m = line.match(ASSIGNMENT_RE);
        if (m) {
            out[m[1]] = m[2] ?? m[3] ?? m[4] ?? '';
        }
    }
    return out;
}

export function deriveInstanceFromDir(dir, envText) {
    const env = parseEnvVarSh(envText);
    const portStr = env.ERPLIBRE_PORT_HTTP;
    const port = parseInt(portStr || '8069', 10) || 8069;
    const name = (dir.replace(/\/+$/, '').split('/').pop()) || dir;
    return {
        id: uuid4(),
        name,
        url: `http://localhost:${port}`,
        type: 'local',
        local_path: dir,
        port,
        keepass_db: '',
        keepass_keyfile: '',
        keepass_yubikey_slot: 0,
        keepass_yubikey_serial: '',
        keepass_entry: '',
        auto_login_method: 'none',
    };
}

/**
 * GJS-only — expand a glob pattern (with leading ~) and return absolute
 * paths matching `<dir>/.git` AND `<dir>/env_var.sh`.
 */
export async function detectLocalInstancesGjs(pattern) {
    const {default: GLib} = await import('gi://GLib');
    const home = GLib.get_home_dir();
    const expanded = expandHome(pattern, home);
    // Use shell to expand the glob since GLib has no glob.
    return new Promise(resolve => {
        try {
            const [, stdout] = GLib.spawn_command_line_sync(
                `/bin/bash -c 'for d in ${expanded}; do [ -d "$d/.git" ] ` +
                `&& [ -f "$d/env_var.sh" ] && echo "$d"; done'`);
            const text = new TextDecoder().decode(stdout || new Uint8Array());
            const dirs = text.split('\n').map(s => s.trim()).filter(Boolean);
            const out = [];
            for (const d of dirs) {
                let envText = '';
                try {
                    const [ok, contents] = GLib.file_get_contents(
                        `${d}/env_var.sh`);
                    if (ok) envText = new TextDecoder()
                        .decode(contents);
                } catch (_e) {}
                out.push(deriveInstanceFromDir(d, envText));
            }
            resolve(out);
        } catch (_e) { resolve([]); }
    });
}
