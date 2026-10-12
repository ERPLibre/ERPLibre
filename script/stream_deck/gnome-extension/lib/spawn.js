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
    // mpv defaults to looking up `youtube-dl` for stream extraction.
    // That binary is obsolete on Debian 13+; point at `yt-dlp` instead.
    // `--save-position-on-quit` writes a `start=` line to mpv's
    // watch-later store on every quit (q / Shift-Q / window close);
    // the film indicator reads that file back to refresh the entry's
    // `position` field so the next launch resumes where the user left.
    const argv = [
        'mpv',
        '--script-opts=ytdl_hook-ytdl_path=yt-dlp',
        '--save-position-on-quit=yes',
    ];
    if (position && String(position).trim() !== '') {
        argv.push(`--start=${position}`);
    }
    argv.push(String(url));
    return argv;
}

/**
 * Open a Spotify URI (`spotify:track:…`, `https://open.spotify.com/…`)
 * via xdg-open so the host's default handler picks it up — typically
 * the Spotify desktop app when installed, falling back to the web
 * player. Returning a single argv keeps the spawn path uniform with
 * the other media launchers.
 */
export function buildSpotifyArgv(url) {
    return ['xdg-open', String(url)];
}

export function buildVlcArgv(url, position) {
    const startArg = (() => {
        if (!position || String(position).trim() === '') return '';
        const seconds = parsePosition(position);
        return seconds > 0 ? ` --start-time=${seconds}` : '';
    })();

    // VLC's bundled youtube.lua plugin is broken on Debian 13 (it
    // depends on the obsolete youtube-dl). Resolve the playable URL
    // through `yt-dlp -g` first when it is available, then fall back
    // to passing the URL directly for local files / direct streams.
    //
    // Pass the URL as `$1` so we never have to escape it inside the
    // shell command — bash's `bash -c '<script>' <name> <args...>`
    // syntax sets `$0=<name>` and `$1+=<args>`.
    const cmd =
        'URL=$(yt-dlp -g -f best "$1" 2>/dev/null | head -n1); '
        + `exec vlc${startArg} "${'$'}{URL:-${'$'}1}"`;
    return ['bash', '-c', cmd, 'sdt-vlc', String(url)];
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

async function _logSpawnError(argv, message) {
    try {
        const {logError} = await import('./log.js');
        await logError(argv?.[0] || 'spawn',
            `${(argv || []).join(' ')} :: ${message}`);
    } catch (_e) {}
}

async function _logSpawnOk(argv, exit) {
    try {
        const {logInfo} = await import('./log.js');
        await logInfo(argv?.[0] || 'spawn',
            `${(argv || []).join(' ')} :: exit=${exit}`);
    } catch (_e) {}
}

/**
 * GJS-only — spawn argv asynchronously via Gio.Subprocess. Returns
 * a promise resolving to {ok, stdout, stderr, exit}. Errors notify
 * via the provided notify callback (typically Main.notify) and are
 * appended to the extension log file so the prefs Log page can
 * surface them.
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
                    if (!ok) {
                        if (notify) notify(title || 'Stream Deck',
                            `Command failed: ${argv[0]}`);
                        _logSpawnError(argv,
                            `exit=${p.get_exit_status()} ${stderr || ''}`);
                    } else {
                        _logSpawnOk(argv, p.get_exit_status());
                    }
                    resolve({ok, stdout, stderr, exit: p.get_exit_status()});
                } catch (e) {
                    if (notify) notify(title || 'Stream Deck', e.message);
                    _logSpawnError(argv, e.message || String(e));
                    resolve({ok: false, stdout: '', stderr: e.message, exit: -1});
                }
            });
        } catch (e) {
            if (notify) notify(title || 'Stream Deck',
                `Spawn failed: ${e.message}`);
            _logSpawnError(argv, e.message || String(e));
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
        _logSpawnOk(argv, 'detached');
        return true;
    } catch (e) {
        if (notify) notify(title || 'Stream Deck',
            `Spawn failed: ${e.message}`);
        _logSpawnError(argv, e.message || String(e));
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
