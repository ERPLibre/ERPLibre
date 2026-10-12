/**
 * KeepassXC integration. Pure parts (parser + cache) unit-tested.
 * GJS subprocess invocation is wrapped at the bottom.
 */

export function extractAttribute(stdout) {
    if (typeof stdout !== 'string') return '';
    const trimmed = stdout.endsWith('\n') ? stdout.slice(0, -1) : stdout;
    return trimmed;
}

export function cacheKey({db, keyfile, yubikey_serial}) {
    return `${db || ''}:${keyfile || ''}:${yubikey_serial || ''}`;
}

export class MasterPasswordCache {
    constructor({ttlMs = 5 * 60 * 1000, now = () => Date.now()} = {}) {
        this._ttl = ttlMs;
        this._now = now;
        this._store = new Map();
    }

    set(key, password) {
        this._store.set(key, {password, expiresAt: this._now() + this._ttl});
    }

    get(key) {
        const entry = this._store.get(key);
        if (!entry) return undefined;
        if (entry.expiresAt < this._now()) {
            this._store.delete(key);
            return undefined;
        }
        return entry.password;
    }

    invalidate(key) {
        this._store.delete(key);
    }

    clear() { this._store.clear(); }
}

/**
 * GJS-only — call keepassxc-cli show with master password on stdin.
 * Returns null on failure (and cache is invalidated by the caller).
 */
export async function callKeepassCli({db, keyfile, yubikey_slot,
    yubikey_serial, entry, attribute, masterPassword}) {
    const {default: Gio} = await import('gi://Gio');
    const {default: GLib} = await import('gi://GLib');
    const argv = ['keepassxc-cli', 'show', '-a', attribute];
    if (keyfile) argv.push('--key-file', keyfile);
    if (yubikey_slot && yubikey_slot > 0) {
        argv.push('--yubikey',
            yubikey_serial ? `${yubikey_slot}:${yubikey_serial}`
                           : String(yubikey_slot));
    }
    argv.push(db, entry);

    return new Promise(resolve => {
        try {
            const proc = Gio.Subprocess.new(argv,
                Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE
                | Gio.SubprocessFlags.STDERR_PIPE);
            const stdin = new TextEncoder().encode(masterPassword + '\n');
            proc.communicate_async(
                new GLib.Bytes(stdin), null, (p, res) => {
                    try {
                        const [, stdoutBytes] = p.communicate_finish(res);
                        const stdout = new TextDecoder()
                            .decode(stdoutBytes.get_data());
                        if (!p.get_successful()) resolve(null);
                        else resolve(extractAttribute(stdout));
                    } catch (_e) { resolve(null); }
                });
        } catch (_e) { resolve(null); }
    });
}

// Singleton cache (keyed via cacheKey).
export const masterPasswordCache = new MasterPasswordCache();
