/**
 * Fake GJS runtime for node --test, so the GJS code paths (extension.js,
 * the indicator classes, the dialogs, the lib/ functions that import gi
 * modules) run under node.
 *
 * Importing this module installs in-thread module hooks: every `gi://` and
 * `resource:///` specifier then loads the fakes below. The modules that use
 * them must be imported AFTER this one, through `await import()`: a static
 * import is linked before this module runs. A lib/ module that imports gi
 * only from inside its functions can stay a static import.
 *
 * What the fakes do:
 * - Gio.Subprocess.new records each argv in `fake.spawned` and answers
 *   through `fake.onSpawn(argv, record)`: it returns {exit, stdout, stderr}
 *   (all optional), or throws to make the spawn itself fail. The stdin a
 *   caller writes lands in `record.stdin`.
 * - GLib file functions and Gio.File read and write the real file system;
 *   the user directories, `$USER` and the host name come from `fake.env`,
 *   which points at a fresh temporary directory, removed at the next
 *   `fake.reset()` or at process exit.
 * - GLib.find_program_in_path finds only the names in `fake.programs`.
 * - GLib.timeout_add and friends record {ms, fn} in `fake.timeouts` and
 *   never fire by themselves.
 * - Main.notify records [title, body] in `fake.notified`; the panel records
 *   each addToStatusArea in `fake.panel`; St.Clipboard records in
 *   `fake.clipboard`; each St widget records {type, props} in
 *   `fake.widgets`, and each panel record carries the widget count at its
 *   mount, so the widgets of one indicator are the slice between two;
 *   Gio.DBusExportedObject.wrapJSObject records {xml, object} in
 *   `fake.exported`; each Soup message records
 *   {method, uri, headers} in `fake.http`; each ModalDialog subclass
 *   instance lands in `fake.dialogs`.
 * - Anything else is loose: any property, call or `new` of it gives another
 *   loose value, so widget-building code runs without being asserted on.
 *
 * `makeSettings(overrides)` gives a Gio.Settings stand-in holding the
 * gschema defaults; a set_* call fires the `changed::<key>` handlers.
 */

import {registerHooks} from 'node:module';
import {spawnSync} from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const SCHEMA = new URL(
    '../../schemas/org.gnome.shell.extensions.erplibre-home.gschema.xml',
    import.meta.url);

/** A value that stands for anything: properties, calls and `new` work. */
export function loose() {
    const target = function () {};
    return new Proxy(target, {
        get(t, k) {
            if (k in t) return t[k];
            if (k === 'then') return undefined;
            if (k === Symbol.iterator) return function* () {};
            if (k === Symbol.toPrimitive) return () => 0;
            if (typeof k === 'symbol') return undefined;
            const v = loose();
            Reflect.defineProperty(t, k,
                {value: v, writable: true, configurable: true});
            return v;
        },
        set(t, k, v) {
            return Reflect.defineProperty(t, k,
                {value: v, writable: true, configurable: true});
        },
        apply() { return loose(); },
        construct() { return loose(); },
    });
}

/** `explicit` with a loose value for every other property. */
function looseObject(explicit) {
    return new Proxy(explicit, {
        get(t, k) {
            if (k in t) return t[k];
            if (k === 'then' || typeof k === 'symbol') return undefined;
            t[k] = loose();
            return t[k];
        },
    });
}

function freshEnv() {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'gjs-fake-'));
    const env = {
        HOME: path.join(root, 'home'),
        XDG_CONFIG_HOME: path.join(root, 'config'),
        XDG_CACHE_HOME: path.join(root, 'cache'),
        XDG_STATE_HOME: path.join(root, 'state'),
        XDG_RUNTIME_DIR: path.join(root, 'run'),
        USER: 'deckuser',
        HOSTNAME: 'deckhost',
    };
    for (const k of ['HOME', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME',
        'XDG_STATE_HOME', 'XDG_RUNTIME_DIR'])
        fs.mkdirSync(env[k], {recursive: true});
    return {root, env};
}

/** Remove a directory made by freshEnv; '' (none yet) is a no-op. */
function removeRoot(root) {
    if (root) fs.rmSync(root, {recursive: true, force: true});
}

export const fake = {
    spawned: [],
    onSpawn: () => ({}),
    programs: [],
    timeouts: [],
    notified: [],
    panel: [],
    clipboard: [],
    widgets: [],
    exported: [],
    http: [],
    dialogs: [],
    settings: null,
    root: '',
    env: {},
    /**
     * Forget every record and start from a fresh temporary directory; the
     * previous one is removed, and the last one goes at process exit.
     */
    reset() {
        removeRoot(this.root);
        for (const k of ['spawned', 'timeouts', 'notified', 'panel',
            'clipboard', 'widgets', 'exported', 'http', 'dialogs'])
            this[k] = [];
        this.onSpawn = () => ({});
        this.programs = [];
        this.settings = null;
        const {root, env} = freshEnv();
        this.root = root;
        this.env = env;
    },
};
fake.reset();
process.on('exit', () => removeRoot(fake.root));

/** Let the pending callbacks and promise chains of the fakes run. */
export async function settle(rounds = 20) {
    for (let i = 0; i < rounds; i++)
        await new Promise(r => setImmediate(r));
}

/**
 * Runs the recorded argv for real (env without the user's git config) and
 * returns what onSpawn expects: for a fake.onSpawn that needs a real
 * command, such as git in a temporary repository.
 */
export function runForReal(argv, env = {}) {
    const r = spawnSync(argv[0], argv.slice(1), {
        encoding: 'utf8',
        env: {
            ...process.env,
            GIT_CONFIG_GLOBAL: '/dev/null',
            GIT_CONFIG_NOSYSTEM: '1',
            ...env,
        },
    });
    return {exit: r.status ?? 1, stdout: r.stdout || '',
        stderr: r.stderr || ''};
}

// ---------------------------------------------------------------- GLib

class Bytes {
    constructor(data) { this._data = data; }
    get_data() { return this._data; }
}

const FileTest = {EXISTS: 1, IS_REGULAR: 2, IS_DIR: 4, IS_SYMLINK: 8,
    IS_EXECUTABLE: 16};

function fileTest(p, test) {
    let st;
    try { st = fs.lstatSync(p); } catch (_e) { return false; }
    if (test & FileTest.IS_SYMLINK) return st.isSymbolicLink();
    try { st = fs.statSync(p); } catch (_e) { return false; }
    if (test & FileTest.IS_DIR) return st.isDirectory();
    if (test & FileTest.IS_REGULAR) return st.isFile();
    if (test & FileTest.IS_EXECUTABLE) {
        try { fs.accessSync(p, fs.constants.X_OK); } catch (_e) {
            return false;
        }
        return st.isFile();
    }
    return true;
}

let _sourceId = 0;
function addTimeout(ms, fn) {
    const id = ++_sourceId;
    fake.timeouts.push({id, ms, fn, removed: false});
    return id;
}

const GLib = looseObject({
    Bytes,
    FileTest,
    PRIORITY_DEFAULT: 0,
    PRIORITY_LOW: 300,
    SOURCE_REMOVE: false,
    SOURCE_CONTINUE: true,
    file_test: fileTest,
    file_get_contents: p => [true, new Uint8Array(fs.readFileSync(p))],
    file_set_contents: (p, s) => { fs.writeFileSync(p, s); return true; },
    rename: (a, b) => { fs.renameSync(a, b); return 0; },
    unlink: p => { fs.unlinkSync(p); return 0; },
    mkdir_with_parents: p => { fs.mkdirSync(p, {recursive: true}); return 0; },
    build_filenamev: parts => path.join(...parts),
    get_home_dir: () => fake.env.HOME,
    get_user_config_dir: () => fake.env.XDG_CONFIG_HOME,
    get_user_cache_dir: () => fake.env.XDG_CACHE_HOME,
    get_user_runtime_dir: () => fake.env.XDG_RUNTIME_DIR,
    get_tmp_dir: () => fake.root,
    get_user_name: () => fake.env.USER,
    get_host_name: () => fake.env.HOSTNAME,
    getenv: k => fake.env[k] ?? null,
    find_program_in_path: n =>
        fake.programs.includes(n) ? `/usr/bin/${n}` : null,
    timeout_add: (_prio, ms, fn) => addTimeout(ms, fn),
    timeout_add_seconds: (_prio, s, fn) => addTimeout(s * 1000, fn),
    idle_add: (_prio, fn) => addTimeout(0, fn),
    source_remove: id => {
        const t = fake.timeouts.find(x => x.id === id);
        if (t) t.removed = true;
        return true;
    },
    spawn_command_line_sync: cmd => {
        const r = fake.onSpawn(['__sync__', cmd], {argv: [cmd]}) ?? {};
        const enc = new TextEncoder();
        return [true, enc.encode(r.stdout ?? ''), enc.encode(r.stderr ?? ''),
            r.exit ?? 0];
    },
    get_real_time: () => Date.now() * 1000,
    Variant: {new: (type, value) => ({type, value})},
});

// ----------------------------------------------------------------- Gio

const SubprocessFlags = {NONE: 0, STDIN_PIPE: 1, STDOUT_PIPE: 2,
    STDERR_PIPE: 4};

function newSubprocess(argv, flags) {
    const record = {argv: [...argv], flags, stdin: null};
    fake.spawned.push(record);
    const answer = fake.onSpawn([...argv], record) ?? {};
    const res = {exit: answer.exit ?? 0, stdout: answer.stdout ?? '',
        stderr: answer.stderr ?? ''};
    const enc = new TextEncoder();
    const later = (proc, cb) => setImmediate(() => cb?.(proc, null));
    const proc = {
        communicate_utf8_async(input, _c, cb) {
            record.stdin = input;
            later(proc, cb);
        },
        communicate_utf8_finish: () => [true, res.stdout, res.stderr],
        communicate_async(bytes, _c, cb) {
            record.stdin = bytes
                ? new TextDecoder().decode(bytes.get_data()) : null;
            later(proc, cb);
        },
        communicate_finish: () => [true, new Bytes(enc.encode(res.stdout)),
            new Bytes(enc.encode(res.stderr))],
        wait_async(_c, cb) { later(proc, cb); },
        wait_finish: () => true,
        wait_check_async(_c, cb) { later(proc, cb); },
        wait_check_finish: () => res.exit === 0,
        get_successful: () => res.exit === 0,
        get_exit_status: () => res.exit,
        get_if_exited: () => true,
        get_identifier: () => '4242',
        force_exit() {},
        send_signal() {},
    };
    return proc;
}

class FakeOutput {
    constructor(p) { this._p = p; }
    write_all(bytes) { fs.appendFileSync(this._p, bytes); return [true, 0]; }
    close() { return true; }
}

class FakeFile {
    constructor(p) { this._p = p; }
    get_path() { return this._p; }
    query_exists() { return fs.existsSync(this._p); }
    load_contents() {
        return [true, new Uint8Array(fs.readFileSync(this._p)), null];
    }
    replace_contents(bytes) {
        fs.writeFileSync(this._p, bytes);
        return [true, null];
    }
    append_to() {
        if (!fs.existsSync(this._p)) throw new Error('no such file');
        return new FakeOutput(this._p);
    }
    create() {
        fs.writeFileSync(this._p, '');
        return new FakeOutput(this._p);
    }
    monitor_directory() { return loose(); }
    monitor_file() { return loose(); }
}

class Cancellable {
    cancel() { this._cancelled = true; }
    is_cancelled() { return !!this._cancelled; }
}

const Gio = looseObject({
    SubprocessFlags,
    Subprocess: looseObject({new: newSubprocess}),
    File: looseObject({new_for_path: p => new FakeFile(p)}),
    FileCreateFlags: {NONE: 0, REPLACE_DESTINATION: 1},
    FileQueryInfoFlags: {NONE: 0, NOFOLLOW_SYMLINKS: 1},
    Cancellable,
    icon_new_for_string: s => ({icon: s}),
    DBus: looseObject({session: loose()}),
    DBusExportedObject: {
        wrapJSObject(xml, object) {
            fake.exported.push({xml, object});
            return {export: () => 1, unexport() {}, emit_signal() {}};
        },
    },
});

// ------------------------------------------------------- GObject, St

const GObject = looseObject({
    registerClass: (meta, cls) => cls ?? meta,
});

function widgetClass(type) {
    return class {
        constructor(props = {}) {
            this.props = props;
            this._text = props.text ?? '';
            fake.widgets.push({type, props, widget: this});
            return new Proxy(this, {
                get(t, k) {
                    if (k in t || typeof k === 'symbol' || k === 'then')
                        return t[k];
                    return loose();
                },
            });
        }
        get_text() { return this._text; }
        set_text(text) { this._text = text; }
    };
}

const _stClasses = {};
const St = new Proxy({
    Clipboard: {
        get_default: () => ({
            set_text: (_type, text) => fake.clipboard.push(text),
        }),
    },
    ClipboardType: {CLIPBOARD: 0, PRIMARY: 1},
}, {
    get(t, k) {
        if (k in t) return t[k];
        if (typeof k !== 'string' || k === 'then') return undefined;
        if (/^[A-Z]/.test(k)) {
            _stClasses[k] ??= widgetClass(k);
            return _stClasses[k];
        }
        t[k] = loose();
        return t[k];
    },
});

// ---------------------------------------------------------------- Soup

class SoupSession {
    send_and_read_async(message, _prio, _c, cb) {
        message.callback = cb;
        message.session = this;
    }
    send_and_read_finish(result) {
        if (result?.error) throw new Error(result.error);
        return new Bytes(new TextEncoder().encode(result?.body ?? ''));
    }
}

const Soup = looseObject({
    Session: SoupSession,
    Message: {
        new(method, uri) {
            const headers = {};
            const message = {
                method, uri, headers, status: 200,
                get_request_headers: () => ({
                    append: (k, v) => { headers[k] = v; },
                }),
                get_status: () => message.status,
            };
            fake.http.push(message);
            return message;
        },
    },
});

// ------------------------------------------------------- shell modules

class FakeMenu {
    constructor() { this.items = []; this.handlers = {}; }
    addMenuItem(item) { this.items.push(item); }
    removeAll() { this.items = []; }
    connect(signal, cb) {
        (this.handlers[signal] ??= []).push(cb);
        return 1;
    }
    /** Run the handlers of `signal`, as the shell does. */
    emit(signal, ...args) {
        for (const cb of this.handlers[signal] ?? []) cb(this, ...args);
    }
    disconnect() {}
    open() {}
    close() {}
    toggle() {}
}

class MenuItem {
    constructor(label = '', params = {}) {
        this.text = label;
        this.label = {text: label};
        this.params = params;
        this.handlers = {};
        this.menu = new FakeMenu();
        this.visible = true;
    }
    connect(signal, cb) { this.handlers[signal] = cb; return 1; }
    disconnect() {}
    activate() { this.handlers.activate?.(this); }
    add_child() {}
    insert_child_at_index() {}
    setOrnament() {}
    setSensitive() {}
    destroy() {}
}

class Button {
    constructor(...args) { this._init(...args); }
    _init(_align, name) {
        this.name = name;
        this.menu = new FakeMenu();
        this.visible = true;
    }
    add_child() {}
    remove_child() {}
    connect() { return 1; }
    disconnect() {}
    destroy() { this.destroyed = true; }
    hide() {}
    show() {}
}

class ModalDialog {
    constructor(...args) { this._init(...args); }
    _init(params) {
        this.params = params;
        this.contentLayout = loose();
        this.buttonLayout = loose();
        fake.dialogs.push(this);
    }
    setButtons(buttons) { this.buttons = buttons; }
    open() { this.opened = true; return true; }
    close() { this.closed = true; }
    connect() { return 1; }
    destroy() {}
}

class Extension {
    constructor(metadata = {}) {
        this.metadata = metadata;
        this.uuid = metadata.uuid ?? 'erplibre-home@technolibre.ca';
        this.path = metadata.path ?? fake.root;
    }
    getSettings() { return fake.settings; }
    openPreferences() {}
    gettext(s) { return s; }
}

const RESOURCES = {
    'resource:///org/gnome/shell/ui/main.js': {
        notify: (title, body) => fake.notified.push([title, body]),
        panel: {
            addToStatusArea: (role, indicator, position, box) =>
                fake.panel.push({role, indicator, position, box,
                    widgetCount: fake.widgets.length}),
        },
        layoutManager: loose(),
        extensionManager: loose(),
        messageTray: loose(),
        overview: loose(),
        wm: loose(),
        activateWindow() {},
    },
    'resource:///org/gnome/shell/ui/panelMenu.js': {Button},
    'resource:///org/gnome/shell/ui/popupMenu.js': {
        PopupMenuItem: MenuItem,
        PopupSubMenuMenuItem: MenuItem,
        PopupBaseMenuItem: MenuItem,
        PopupSeparatorMenuItem: MenuItem,
        PopupSwitchMenuItem: MenuItem,
        PopupMenuSection: FakeMenu,
        Ornament: loose(),
    },
    'resource:///org/gnome/shell/ui/modalDialog.js': {ModalDialog},
    'resource:///org/gnome/shell/extensions/extension.js': {Extension},
};

const GI = {
    Gio, GLib, GObject, St, Soup,
    Clutter: loose(), Meta: loose(), Shell: loose(), Gtk: loose(),
    Adw: loose(),
};

globalThis.__gjsFake = {gi: GI, resources: RESOURCES};

registerHooks({
    resolve(specifier, context, next) {
        if (specifier.startsWith('gi://') || specifier.startsWith('resource:'))
            return {url: specifier, shortCircuit: true};
        return next(specifier, context);
    },
    load(url, context, next) {
        if (url.startsWith('gi://')) {
            const name = url.slice('gi://'.length).split('?')[0];
            return {
                format: 'module',
                shortCircuit: true,
                source: 'export default globalThis.__gjsFake.gi['
                    + `${JSON.stringify(name)}];`,
            };
        }
        if (url.startsWith('resource:')) {
            const names = Object.keys(RESOURCES[url] ?? {});
            const ref = 'globalThis.__gjsFake.resources'
                + `[${JSON.stringify(url)}]`;
            return {
                format: 'module',
                shortCircuit: true,
                source: names.map(n =>
                    `export const ${n} = ${ref}[${JSON.stringify(n)}];`)
                    .join('\n'),
            };
        }
        return next(url, context);
    },
});

// ------------------------------------------------------------ settings

function parseVariant(type, text) {
    const t = text.trim();
    if (type === 'b') return t === 'true';
    if (type === 'i') return parseInt(t, 10);
    if (type === 's') return JSON.parse(`"${t.slice(1, -1)
        .replace(/\\'/g, '\'').replace(/"/g, '\\"')}"`);
    if (type === 'as') {
        const body = t.replace(/^@as\s*/, '').slice(1, -1).trim();
        if (body === '') return [];
        return body.split(',').map(s => parseVariant('s', s));
    }
    throw new Error(`gjs-fake: no parser for GVariant type ${type}`);
}

/**
 * The keys of the extension's gschema: a Map name → {type, value}, value
 * being the default as GSettings unpacks it.
 */
export function schemaDefaults() {
    const xml = fs.readFileSync(SCHEMA, 'utf8');
    const keys = new Map();
    const re = /<key\s+name="([^"]+)"\s+type="([^"]+)"\s*>([\s\S]*?)<\/key>/g;
    for (const [, name, type, body] of xml.matchAll(re)) {
        const m = /<default>([\s\S]*?)<\/default>/.exec(body);
        keys.set(name, {type, value: m ? parseVariant(type, m[1]) : null});
    }
    return keys;
}

/** A Gio.Settings stand-in: the gschema defaults, then `overrides`. */
export function makeSettings(overrides = {}) {
    const keys = schemaDefaults();
    const values = new Map([...keys].map(([k, v]) => [k, v.value]));
    for (const [k, v] of Object.entries(overrides)) values.set(k, v);
    const handlers = [];
    let nextId = 0;
    const check = k => {
        if (!keys.has(k)) throw new Error(`gjs-fake: no key ${k}`);
    };
    const set = (k, v) => {
        check(k);
        values.set(k, v);
        for (const h of handlers.filter(x => x.signal === `changed::${k}`))
            h.cb(settings, k);
        return true;
    };
    const settings = {
        get_boolean: k => { check(k); return values.get(k); },
        get_int: k => { check(k); return values.get(k); },
        get_string: k => { check(k); return values.get(k); },
        get_strv: k => { check(k); return [...values.get(k)]; },
        set_boolean: set,
        set_int: set,
        set_string: set,
        set_strv: (k, v) => set(k, [...v]),
        get_value: k => {
            check(k);
            const v = values.get(k);
            return {deep_unpack: () => v, unpack: () => v,
                get_type_string: () => keys.get(k).type};
        },
        set_value: (k, variant) => set(k, variant.value),
        reset: k => set(k, keys.get(k).value),
        connect: (signal, cb) => {
            handlers.push({id: ++nextId, signal, cb});
            return nextId;
        },
        disconnect: id => {
            const i = handlers.findIndex(h => h.id === id);
            if (i >= 0) handlers.splice(i, 1);
        },
        handlers,
    };
    return settings;
}
