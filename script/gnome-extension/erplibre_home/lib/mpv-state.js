/**
 * Tracks running mpv instances launched by the film indicator.
 *
 * Each mpv process gets a state file at
 * `$XDG_STATE_HOME/streamdeck-tiler/mpv/{pid}.json` containing:
 *   {
 *     pid:          number,
 *     ipc_socket:   "/run/user/.../sdt-mpv-<id>.sock",
 *     url:          "https://...",
 *     title:        "Foundation S2E5",
 *     film_id:      "uuid",
 *     started_at:   1700000000123
 *   }
 *
 * The deck (game_tiler.py) reads the directory to surface active
 * mpv sessions; the extension uses the `ipc_socket` field to send
 * `cycle pause`, `quit` etc. to the running process.
 */

export const STATE_SUBDIR = 'streamdeck-tiler/mpv';

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

export function stateBase(GLib) {
    const base = GLib.getenv('XDG_STATE_HOME')
        || `${GLib.get_home_dir()}/.local/state`;
    return `${base}/${STATE_SUBDIR}`;
}

export async function ensureStateDir() {
    const {GLib} = await _loadGjs();
    const dir = stateBase(GLib);
    GLib.mkdir_with_parents(dir, 0o700);
    return dir;
}

export async function writeMpvEntry(entry) {
    const {Gio, GLib} = await _loadGjs();
    const dir = await ensureStateDir();
    const path = `${dir}/${entry.pid}.json`;
    const file = Gio.File.new_for_path(path);
    const data = JSON.stringify(entry);
    file.replace_contents(
        new TextEncoder().encode(data),
        null, false, Gio.FileCreateFlags.REPLACE_DESTINATION, null);
    return path;
}

export async function deleteMpvEntry(pid) {
    const {GLib} = await _loadGjs();
    const dir = stateBase(GLib);
    const path = `${dir}/${pid}.json`;
    try { GLib.unlink(path); } catch (_e) {}
}

/** Synchronous variant — safe to call from D-Bus method handlers. */
export function listMpvEntriesSync(Gio, GLib) {
    const dir = stateBase(GLib);
    if (!GLib.file_test(dir, GLib.FileTest.IS_DIR)) return [];
    const out = [];
    let enumerator;
    try {
        enumerator = Gio.File.new_for_path(dir).enumerate_children(
            'standard::name', Gio.FileQueryInfoFlags.NONE, null);
    } catch (_e) { return out; }
    let info;
    while ((info = enumerator.next_file(null)) !== null) {
        const name = info.get_name();
        if (!name.endsWith('.json')) continue;
        const path = `${dir}/${name}`;
        try {
            const [ok, contents] = GLib.file_get_contents(path);
            if (!ok) continue;
            const entry = JSON.parse(new TextDecoder().decode(contents));
            if (!entry.pid) continue;
            // Sweep dead processes.
            if (!GLib.file_test(`/proc/${entry.pid}`, GLib.FileTest.EXISTS)) {
                try { GLib.unlink(path); } catch (_e) {}
                continue;
            }
            out.push(entry);
        } catch (_e) {}
    }
    enumerator.close(null);
    out.sort((a, b) => (b.started_at || 0) - (a.started_at || 0));
    return out;
}

export async function listMpvEntries() {
    const {Gio, GLib} = await _loadGjs();
    return listMpvEntriesSync(Gio, GLib);
}

/**
 * Send a single JSON command line to mpv's input-ipc-server socket.
 * Returns true on connection success (mpv may still reject the
 * command — caller should not assume side-effects on the false path).
 */
export async function sendMpvCommand(socketPath, command) {
    const {Gio, GLib} = await _loadGjs();
    if (!socketPath) return false;
    if (!GLib.file_test(socketPath, GLib.FileTest.EXISTS)) return false;
    try {
        const client = new Gio.SocketClient();
        client.set_timeout(1);
        const addr = Gio.UnixSocketAddress.new(socketPath);
        const conn = client.connect(addr, null);
        if (!conn) return false;
        const out = conn.get_output_stream();
        const line = JSON.stringify(command) + '\n';
        out.write_all(new TextEncoder().encode(line), null);
        out.flush(null);
        try { conn.close(null); } catch (_e) {}
        return true;
    } catch (_e) {
        return false;
    }
}
