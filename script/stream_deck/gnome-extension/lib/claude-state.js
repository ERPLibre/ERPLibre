/**
 * Claude session state tracking.
 *
 * The hook scripts in hooks/ write one JSON file per Claude session in
 * the state directory (default `$XDG_STATE_HOME/streamdeck-tiler/claude/`,
 * fallback `~/.local/state/streamdeck-tiler/claude/`).
 *
 * File contents:
 *   {
 *     "session_id": "uuid…",
 *     "pid": 12345,
 *     "cwd": "/abs/path",
 *     "status": "active" | "awaiting_stop" | "awaiting_notification",
 *     "ts": 1700000000123                     // ms since epoch
 *   }
 *
 * Pure helpers (parseStateEntry, indexSessions) are exported for unit
 * tests; the GJS-only ClaudeStateWatcher class wraps Gio.FileMonitor.
 */

export const STATUS_ACTIVE = 'active';
export const STATUS_AWAIT_STOP = 'awaiting_stop';
export const STATUS_AWAIT_NOTIFY = 'awaiting_notification';

export const STATE_DIR_REL =
    'streamdeck-tiler/claude';

/**
 * Parse one state file payload (already JSON-decoded). Returns the
 * normalised shape, or null when invalid.
 *
 * The on-disk format keeps three independent timestamps; the status
 * is derived as "the most recent of the three", so a fresh
 * UserPromptSubmit clears a stale Stop/Notification.
 *
 * Backwards-compatible: an old-style file with `status` + `ts` is
 * mapped onto the timestamp triplet using `ts` as the value of the
 * matching field.
 */
export function parseStateEntry(raw) {
    if (!raw || typeof raw !== 'object') return null;
    const session_id = String(raw.session_id || '').trim();
    if (!session_id) return null;
    const pid = Number.isFinite(raw.pid) ? Math.floor(raw.pid) : 0;
    const cwdRaw = typeof raw.cwd === 'string' ? raw.cwd : '';
    const cwd = cwdRaw.replace(/\/+$/, '');

    let ts_active = _num(raw.ts_active);
    let ts_stop = _num(raw.ts_stop);
    let ts_notification = _num(raw.ts_notification);
    if (!ts_active && !ts_stop && !ts_notification) {
        const ts = _num(raw.ts);
        if (raw.status === STATUS_AWAIT_STOP) ts_stop = ts;
        else if (raw.status === STATUS_AWAIT_NOTIFY) ts_notification = ts;
        else ts_active = ts;
    }

    let status = STATUS_ACTIVE;
    const max = Math.max(ts_active, ts_stop, ts_notification);
    if (max > 0) {
        if (ts_notification === max) status = STATUS_AWAIT_NOTIFY;
        else if (ts_stop === max) status = STATUS_AWAIT_STOP;
        else status = STATUS_ACTIVE;
    }

    return {
        session_id, pid, cwd, status,
        ts_active, ts_stop, ts_notification,
        ts: max,
    };
}

function _num(v) {
    return Number.isFinite(v) ? Math.floor(v) : 0;
}

/**
 * Group a list of normalised entries by `cwd` and produce the totals
 * the indicators consume.
 */
export function indexSessions(entries) {
    const list = (entries || []).filter(Boolean);
    const byPath = new Map();
    let totalActive = 0;
    let totalAwaitStop = 0;
    let totalAwaitNotify = 0;
    for (const e of list) {
        const cwd = e.cwd || '';
        if (!byPath.has(cwd)) {
            byPath.set(cwd, {
                total: 0, active: 0,
                awaitStop: 0, awaitNotify: 0,
                sessions: [],
            });
        }
        const bucket = byPath.get(cwd);
        bucket.total += 1;
        bucket.sessions.push(e);
        if (e.status === STATUS_AWAIT_STOP) {
            bucket.awaitStop += 1;
            totalAwaitStop += 1;
        } else if (e.status === STATUS_AWAIT_NOTIFY) {
            bucket.awaitNotify += 1;
            totalAwaitNotify += 1;
        } else {
            bucket.active += 1;
            totalActive += 1;
        }
    }
    return {
        total: list.length,
        totalActive,
        totalAwaitStop,
        totalAwaitNotify,
        totalAwaiting: totalAwaitStop + totalAwaitNotify,
        byPath,
    };
}

/**
 * Per-cwd summary lookup helper used by pencil rows.
 */
export function summaryForCwd(index, cwd) {
    if (!index || !index.byPath) return null;
    return index.byPath.get(cwd) || null;
}

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

export async function defaultStateDir() {
    const {GLib} = await _loadGjs();
    const base = GLib.getenv('XDG_STATE_HOME') ||
        `${GLib.get_home_dir()}/.local/state`;
    return `${base}/${STATE_DIR_REL}`;
}

/**
 * Watch the state directory and notify subscribers whenever it changes.
 *
 * Usage:
 *   const w = new ClaudeStateWatcher({stateDir});
 *   await w.start();
 *   const off = w.subscribe(index => …);
 *   w.stop();
 */
export class ClaudeStateWatcher {
    constructor({stateDir, isPidAlive} = {}) {
        this._stateDir = stateDir || null;
        this._isPidAlive = isPidAlive || _defaultIsPidAlive;
        this._monitor = null;
        this._monitorSig = 0;
        this._index = indexSessions([]);
        this._subs = new Set();
        this._refreshing = false;
        this._dirty = false;
    }

    async start() {
        const {Gio, GLib} = await _loadGjs();
        if (!this._stateDir) this._stateDir = await defaultStateDir();
        try {
            GLib.mkdir_with_parents(this._stateDir, 0o700);
        } catch (_e) {}
        const dir = Gio.File.new_for_path(this._stateDir);
        this._monitor = dir.monitor_directory(
            Gio.FileMonitorFlags.NONE, null);
        this._monitorSig = this._monitor.connect(
            'changed', () => this._scheduleRefresh());
        await this._refresh();
    }

    stop() {
        if (this._monitor) {
            if (this._monitorSig)
                this._monitor.disconnect(this._monitorSig);
            this._monitor.cancel?.();
            this._monitor = null;
            this._monitorSig = 0;
        }
        this._subs.clear();
    }

    subscribe(cb) {
        if (typeof cb !== 'function') return () => {};
        this._subs.add(cb);
        try { cb(this._index); } catch (_e) {}
        return () => this._subs.delete(cb);
    }

    getIndex() { return this._index; }

    _scheduleRefresh() {
        if (this._refreshing) { this._dirty = true; return; }
        this._refresh();
    }

    async _refresh() {
        this._refreshing = true;
        this._dirty = false;
        try {
            const entries = await this._loadAll();
            this._index = indexSessions(entries);
            for (const cb of this._subs) {
                try { cb(this._index); } catch (_e) {}
            }
        } finally {
            this._refreshing = false;
            if (this._dirty) this._scheduleRefresh();
        }
    }

    async _loadAll() {
        const {Gio, GLib} = await _loadGjs();
        const dir = Gio.File.new_for_path(this._stateDir);
        if (!dir.query_exists(null)) return [];
        let enumerator;
        try {
            enumerator = dir.enumerate_children(
                'standard::name,standard::type',
                Gio.FileQueryInfoFlags.NONE, null);
        } catch (_e) { return []; }
        const out = [];
        let info;
        while ((info = enumerator.next_file(null)) !== null) {
            const name = info.get_name();
            if (!name.endsWith('.json')) continue;
            const path = `${this._stateDir}/${name}`;
            const entry = this._readEntry(GLib, path);
            if (!entry) continue;
            if (entry.pid > 0 && !this._isPidAlive(entry.pid)) {
                try { GLib.unlink(path); } catch (_e) {}
                continue;
            }
            out.push(entry);
        }
        enumerator.close(null);
        return out;
    }

    _readEntry(GLib, path) {
        try {
            const [ok, contents] = GLib.file_get_contents(path);
            if (!ok) return null;
            const text = new TextDecoder().decode(contents);
            return parseStateEntry(JSON.parse(text));
        } catch (_e) {
            return null;
        }
    }
}

function _defaultIsPidAlive(pid) {
    if (!pid || pid <= 0) return true;
    try {
        // GLib is loaded eagerly via _loadGjs; reach back through cache.
        const GLib = _gjs?.GLib;
        if (!GLib) return true;
        return GLib.file_test(`/proc/${pid}`, GLib.FileTest.EXISTS);
    } catch (_e) {
        return true;
    }
}
