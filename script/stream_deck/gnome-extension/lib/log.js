/**
 * Tiny append-only logger backed by a JSONL file under
 * `$XDG_STATE_HOME/streamdeck-tiler/log.jsonl`.
 *
 * Indicators and helpers route notable events here so the prefs
 * window's "Log" page can surface what is going on inside the
 * extension — particularly when a spawn silently fails on a remote
 * machine where journalctl is not at hand.
 */

export const LOG_LEVELS = ['debug', 'info', 'warn', 'error'];
export const MAX_LOG_LINES = 500;

let _gjs = null;

async function _loadGjs() {
    if (_gjs) return _gjs;
    const [{default: Gio}, {default: GLib}] = await Promise.all([
        import('gi://Gio'),
        import('gi://GLib'),
    ]);
    _gjs = {Gio, GLib};
    return _gjs;
}

export function _logFilePath(GLib) {
    const base = GLib.getenv('XDG_STATE_HOME')
        || `${GLib.get_home_dir()}/.local/state`;
    return `${base}/streamdeck-tiler/log.jsonl`;
}

/** Format a single log line. Pure for unit testing. */
export function formatLogEntry({ts, source, level, message}) {
    return JSON.stringify({
        ts: Number.isFinite(ts) ? ts : Date.now(),
        source: String(source || ''),
        level: LOG_LEVELS.includes(level) ? level : 'info',
        message: String(message || ''),
    }) + '\n';
}

/** Drop lines beyond `keep` (oldest first) so the file stays bounded. */
export function trimLog(text, keep = MAX_LOG_LINES) {
    if (!text) return '';
    const lines = text.split('\n').filter(Boolean);
    if (lines.length <= keep) return lines.join('\n') + '\n';
    return lines.slice(-keep).join('\n') + '\n';
}

export async function appendLog(entry) {
    try {
        const {Gio, GLib} = await _loadGjs();
        const path = _logFilePath(GLib);
        GLib.mkdir_with_parents(path.replace(/\/[^/]+$/, ''), 0o700);
        const line = formatLogEntry(entry);
        const file = Gio.File.new_for_path(path);
        let out;
        try {
            out = file.append_to(Gio.FileCreateFlags.NONE, null);
        } catch (_e) {
            out = file.create(Gio.FileCreateFlags.NONE, null);
        }
        out.write_all(new TextEncoder().encode(line), null);
        out.close(null);
    } catch (_e) {
        try {
            console.log(
                `[StreamDeckTiler:${entry?.source ?? '?'}] ${entry?.message}`);
        } catch (_e2) {}
    }
}

export async function readLogTail(maxLines = 200) {
    try {
        const {GLib} = await _loadGjs();
        const path = _logFilePath(GLib);
        if (!GLib.file_test(path, GLib.FileTest.EXISTS)) return [];
        const [ok, contents] = GLib.file_get_contents(path);
        if (!ok) return [];
        const text = new TextDecoder().decode(contents);
        const lines = text.trim().split('\n').slice(-maxLines);
        const out = [];
        for (const l of lines) {
            try { out.push(JSON.parse(l)); } catch (_e) {}
        }
        return out;
    } catch (_e) { return []; }
}

export async function clearLog() {
    try {
        const {GLib} = await _loadGjs();
        const path = _logFilePath(GLib);
        GLib.mkdir_with_parents(path.replace(/\/[^/]+$/, ''), 0o700);
        // Gio.File.replace_contents with a 0-byte Uint8Array silently
        // misbehaves on some GJS bindings. GLib.file_set_contents is
        // a one-shot sync write that always truncates to the given
        // length, so it actually empties the file.
        GLib.file_set_contents(path, '');
        return true;
    } catch (_e) { return false; }
}

/** Convenience helpers for callers. */
export function logInfo(source, message) {
    return appendLog({source, level: 'info', message});
}
export function logWarn(source, message) {
    return appendLog({source, level: 'warn', message});
}
export function logError(source, message) {
    return appendLog({source, level: 'error', message});
}
