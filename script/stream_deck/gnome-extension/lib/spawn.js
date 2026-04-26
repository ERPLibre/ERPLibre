/**
 * Subprocess + cmdline helpers. Pure builders are unit-tested; the
 * runProcess + notify execution paths are GJS-only and exercised
 * via manual smoke.
 */

export function shellQuote(s) {
    if (s === '' || /[^\w@%+=:,./-]/.test(s)) {
        return `'${String(s).replace(/'/g, `'\\''`)}'`;
    }
    return s;
}

export function buildTerminalArgv({cwd, command, terminal = 'gnome-terminal'}) {
    if (terminal === 'gnome-terminal' || terminal === 'kgx') {
        return [
            terminal,
            `--working-directory=${cwd}`,
            '--', 'bash', '-lc', `${command}; exec bash`,
        ];
    }
    // xterm style
    return [terminal, '-e',
        `bash -lc "cd ${cwd} && ${command}; exec bash"`];
}

export function buildBrowserArgv(url) {
    return ['xdg-open', String(url)];
}

export function buildMpvArgv(url, position) {
    const argv = ['mpv'];
    if (position && String(position).trim() !== '') {
        argv.push(`--start=${position}`);
    }
    argv.push(String(url));
    return argv;
}

export function parsePosition(text) {
    if (typeof text !== 'string' || text.trim() === '') return 0;
    const cleaned = text.trim();
    if (!/^\d+(:\d+){0,2}$/.test(cleaned)) return 0;
    const parts = cleaned.split(':').map(Number);
    if (parts.length === 1) return parts[0];
    if (parts.length === 2) return parts[0] * 60 + parts[1];
    return parts[0] * 3600 + parts[1] * 60 + parts[2];
}

export function formatPosition(seconds) {
    const s = Math.max(0, parseInt(seconds, 10) || 0);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const ss = s % 60;
    const pad = n => String(n).padStart(2, '0');
    return `${pad(h)}:${pad(m)}:${pad(ss)}`;
}

/**
 * GJS-only — spawn argv asynchronously via Gio.Subprocess. Returns
 * a promise resolving to {ok, stdout, stderr, exit}. Errors notify
 * via the provided notify callback (typically Main.notify).
 */
export async function runProcess(argv, {notify, title} = {}) {
    const {default: Gio} = await import('gi://Gio');
    return new Promise(resolve => {
        try {
            const proc = Gio.Subprocess.new(
                argv,
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
            );
            proc.communicate_utf8_async(null, null, (p, res) => {
                try {
                    const [, stdout, stderr] = p.communicate_utf8_finish(res);
                    const ok = p.get_successful();
                    if (!ok && notify) {
                        notify(title || 'Stream Deck',
                            `Command failed: ${argv[0]}`);
                    }
                    resolve({ok, stdout, stderr, exit: p.get_exit_status()});
                } catch (e) {
                    if (notify) notify(title || 'Stream Deck', e.message);
                    resolve({ok: false, stdout: '', stderr: e.message, exit: -1});
                }
            });
        } catch (e) {
            if (notify) notify(title || 'Stream Deck',
                `Spawn failed: ${e.message}`);
            resolve({ok: false, stdout: '', stderr: e.message, exit: -1});
        }
    });
}

/**
 * GJS-only — fire-and-forget spawn (e.g. a terminal that the user
 * interacts with). Returns true if spawn succeeded.
 */
export async function spawnDetached(argv, {notify, title} = {}) {
    const {default: Gio} = await import('gi://Gio');
    try {
        Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE);
        return true;
    } catch (e) {
        if (notify) notify(title || 'Stream Deck',
            `Spawn failed: ${e.message}`);
        return false;
    }
}

/**
 * GJS-only — find the first available terminal binary. Returns its name.
 */
export async function findTerminal() {
    const {default: GLib} = await import('gi://GLib');
    for (const t of ['gnome-terminal', 'kgx', 'xterm']) {
        if (GLib.find_program_in_path(t)) return t;
    }
    return null;
}
