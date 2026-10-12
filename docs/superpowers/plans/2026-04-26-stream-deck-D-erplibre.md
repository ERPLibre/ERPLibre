# Plan D — Stream Deck ERPLibre Indicator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an ERPLibre panel button listing local (auto-detected) and remote (manual) instances. Per instance: open URL, start server (local), auto-login via Selenium or xdotool, copy creds from KeepassXC, open KeepassXC, edit instance.

**Architecture:** New `indicators/erplibre.js`, dialog `ui/instance-dialog.js`, master-password modal `ui/master-pw-dialog.js`, KeepassXC wrapper `lib/keepass.js`, env_var.sh parser `lib/erplibre-detect.js`.

**Tech Stack:** GJS, `keepassxc-cli` (subprocess), `python script/selenium/web_login.py`, `xdotool`.

**Spec reference:** §5.4, §6.4, §7 keepass cache, §8.8, §8.9.

**Depends on:** Plan A.

---

## File structure

| File | Action | Purpose |
|---|---|---|
| `script/stream_deck/gnome-extension/lib/keepass.js` | create | keepassxc-cli wrapper + master-pw cache |
| `script/stream_deck/gnome-extension/lib/erplibre-detect.js` | create | env_var.sh parser, glob expander |
| `script/stream_deck/gnome-extension/ui/master-pw-dialog.js` | create | master password modal |
| `script/stream_deck/gnome-extension/ui/instance-dialog.js` | create | add/edit instance |
| `script/stream_deck/gnome-extension/indicators/erplibre.js` | create | ERPLibre indicator |
| `script/stream_deck/gnome-extension/extension.js` | modify | register descriptor |
| `script/stream_deck/gnome-extension/prefs.js` | modify | ERPLibre page |
| `script/stream_deck/gnome-extension/test/unit/keepass.test.js` | create | parser tests |
| `script/stream_deck/gnome-extension/test/unit/erplibre-detect.test.js` | create | parser tests |
| `script/stream_deck/gnome-extension/test/fixtures/keepassxc-cli-show.txt` | create | sample CLI output |
| `script/stream_deck/gnome-extension/test/fixtures/env_var.sh.sample` | create | sample env_var.sh |
| `script/stream_deck/gnome-extension/test/manual.md` | modify | append section |

---

## Task 1: KeepassXC parser + tests

**Files:**
- Create: `script/stream_deck/gnome-extension/lib/keepass.js`
- Create: `script/stream_deck/gnome-extension/test/unit/keepass.test.js`
- Create: `script/stream_deck/gnome-extension/test/fixtures/keepassxc-cli-show.txt`

`keepassxc-cli show DB ENTRY -a username` prints the username on stdout. `-a password` likewise. We test extraction logic + cache TTL.

- [ ] **Step 1: Create fixture**

Create `test/fixtures/keepassxc-cli-show.txt` (content of `keepassxc-cli show ... -a username` mocked):

```
admin@example.com
```

(One line, no trailing whitespace expected from `keepassxc-cli`.)

- [ ] **Step 2: Write failing tests**

Create `test/unit/keepass.test.js`:

```javascript
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {extractAttribute, MasterPasswordCache, cacheKey}
    from '../../lib/keepass.js';

const fixture = readFileSync(
    new URL('../fixtures/keepassxc-cli-show.txt', import.meta.url),
    'utf8');

test('extractAttribute trims trailing newline', () => {
    assert.equal(extractAttribute(fixture), 'admin@example.com');
    assert.equal(extractAttribute('p\n'), 'p');
    assert.equal(extractAttribute(''), '');
});

test('cacheKey deterministic', () => {
    assert.equal(
        cacheKey({db: '/d.kdbx', keyfile: '', yubikey_serial: ''}),
        '/d.kdbx::');
    assert.equal(
        cacheKey({db: '/d.kdbx', keyfile: '/k', yubikey_serial: '12'}),
        '/d.kdbx:/k:12');
});

test('MasterPasswordCache stores + expires', async () => {
    const c = new MasterPasswordCache({ttlMs: 50, now: () => Date.now()});
    c.set('k', 'pw');
    assert.equal(c.get('k'), 'pw');
    await new Promise(r => setTimeout(r, 70));
    assert.equal(c.get('k'), undefined);
});

test('MasterPasswordCache invalidate', () => {
    const c = new MasterPasswordCache({ttlMs: 5000, now: () => Date.now()});
    c.set('k', 'pw');
    c.invalidate('k');
    assert.equal(c.get('k'), undefined);
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `node --test script/stream_deck/gnome-extension/test/unit/keepass.test.js`
Expected: fail.

- [ ] **Step 4: Implement keepass.js (pure parts)**

Create `lib/keepass.js`:

```javascript
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
```

NOTE: The GJS subprocess block uses `GLib.Bytes` which must be imported lazily inside the function body. Adjust the imports section as follows (replace the function body's `Gio` import):

```javascript
const {default: Gio} = await import('gi://Gio');
const {default: GLib} = await import('gi://GLib');
```

- [ ] **Step 5: Run tests + verify pass**

Run: `node --test script/stream_deck/gnome-extension/test/unit/keepass.test.js`
Expected: 4 tests pass.

- [ ] **Step 6: Commit**

```bash
git add script/stream_deck/gnome-extension/lib/keepass.js \
        script/stream_deck/gnome-extension/test/unit/keepass.test.js \
        script/stream_deck/gnome-extension/test/fixtures/keepassxc-cli-show.txt
git commit -m "[ADD] stream_deck/gnome-extension: keepass parser + cache + tests"
```

---

## Task 2: ERPLibre auto-detection helpers

**Files:**
- Create: `script/stream_deck/gnome-extension/lib/erplibre-detect.js`
- Create: `script/stream_deck/gnome-extension/test/unit/erplibre-detect.test.js`
- Create: `script/stream_deck/gnome-extension/test/fixtures/env_var.sh.sample`

- [ ] **Step 1: Create env_var.sh fixture**

Create `test/fixtures/env_var.sh.sample`:

```bash
#!/usr/bin/env bash
# Sample env_var.sh for tests
export ERPLIBRE_PORT_HTTP=8071
export ERPLIBRE_PORT_LONGPOLLING=8072
export EL_LANG="fr"
```

- [ ] **Step 2: Write failing tests**

Create `test/unit/erplibre-detect.test.js`:

```javascript
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {parseEnvVarSh, deriveInstanceFromDir, expandHome}
    from '../../lib/erplibre-detect.js';

const sample = readFileSync(
    new URL('../fixtures/env_var.sh.sample', import.meta.url), 'utf8');

test('parseEnvVarSh extracts ERPLIBRE_PORT_HTTP', () => {
    const env = parseEnvVarSh(sample);
    assert.equal(env.ERPLIBRE_PORT_HTTP, '8071');
    assert.equal(env.ERPLIBRE_PORT_LONGPOLLING, '8072');
    assert.equal(env.EL_LANG, 'fr');
});

test('parseEnvVarSh tolerates missing file content', () => {
    assert.deepEqual(parseEnvVarSh(''), {});
});

test('deriveInstanceFromDir builds canonical entry', () => {
    const inst = deriveInstanceFromDir('/home/x/erplibre01', sample);
    assert.equal(inst.type, 'local');
    assert.equal(inst.local_path, '/home/x/erplibre01');
    assert.equal(inst.port, 8071);
    assert.equal(inst.url, 'http://localhost:8071');
    assert.equal(inst.name, 'erplibre01');
});

test('deriveInstanceFromDir falls back to 8069 when no port', () => {
    const inst = deriveInstanceFromDir('/home/x/erplibre', '');
    assert.equal(inst.port, 8069);
    assert.equal(inst.url, 'http://localhost:8069');
});

test('expandHome resolves ~', () => {
    assert.equal(expandHome('~/foo', '/home/x'), '/home/x/foo');
    assert.equal(expandHome('/abs', '/home/x'), '/abs');
});
```

- [ ] **Step 3: Run tests + verify they fail**

Run: `node --test script/stream_deck/gnome-extension/test/unit/erplibre-detect.test.js`
Expected: fail.

- [ ] **Step 4: Implement erplibre-detect.js**

Create `lib/erplibre-detect.js`:

```javascript
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
```

- [ ] **Step 5: Run tests + verify pass**

Run: `node --test script/stream_deck/gnome-extension/test/unit/erplibre-detect.test.js`
Expected: 5 tests pass.

- [ ] **Step 6: Commit**

```bash
git add script/stream_deck/gnome-extension/lib/erplibre-detect.js \
        script/stream_deck/gnome-extension/test/unit/erplibre-detect.test.js \
        script/stream_deck/gnome-extension/test/fixtures/env_var.sh.sample
git commit -m "[ADD] stream_deck/gnome-extension: erplibre-detect + tests"
```

---

## Task 3: Master password dialog

**Files:**
- Create: `script/stream_deck/gnome-extension/ui/master-pw-dialog.js`

- [ ] **Step 1: Write the modal**

Create `ui/master-pw-dialog.js`:

```javascript
import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';
import {ModalDialog} from 'resource:///org/gnome/shell/ui/modalDialog.js';

export const MasterPwDialog = GObject.registerClass(
class MasterPwDialog extends ModalDialog {
    _init({db, onConfirm, onCancel}) {
        super._init({styleClass: 'streamdeck-tiler-dialog'});
        this._onConfirm = onConfirm;
        this._onCancel = onCancel;

        const box = new St.BoxLayout({vertical: true,
            style: 'spacing: 8px;'});
        this.contentLayout.add_child(box);
        box.add_child(new St.Label({text: `Unlock ${db}`,
            style: 'font-weight: bold;'}));
        this._entry = new St.PasswordEntry({hint_text: 'Master password'});
        box.add_child(this._entry);

        this.setButtons([
            {label: 'Cancel', action: () => { this._onCancel?.(); this.close(); },
                key: Clutter.KEY_Escape},
            {label: 'Unlock', action: () => this._confirm(), default: true},
        ]);

        // Focus password entry when dialog opens.
        this.connect('opened', () => this._entry.grab_key_focus?.());
    }

    _confirm() {
        const pw = this._entry.get_text();
        if (!pw) return;
        this._onConfirm(pw);
        this.close();
    }
});
```

- [ ] **Step 2: Syntax check + commit**

```bash
node --check script/stream_deck/gnome-extension/ui/master-pw-dialog.js
git add script/stream_deck/gnome-extension/ui/master-pw-dialog.js
git commit -m "[ADD] stream_deck/gnome-extension: master-pw-dialog"
```

---

## Task 4: Instance dialog

**Files:**
- Create: `script/stream_deck/gnome-extension/ui/instance-dialog.js`

- [ ] **Step 1: Write dialog**

Create `ui/instance-dialog.js`:

```javascript
import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';
import {ModalDialog} from 'resource:///org/gnome/shell/ui/modalDialog.js';

export const InstanceDialog = GObject.registerClass(
class InstanceDialog extends ModalDialog {
    _init({title = 'Add instance', entry = null, onConfirm, onDelete}) {
        super._init({styleClass: 'streamdeck-tiler-dialog'});
        this._onConfirm = onConfirm;
        this._onDelete = onDelete;

        const box = new St.BoxLayout({vertical: true,
            style: 'spacing: 6px;'});
        this.contentLayout.add_child(box);
        box.add_child(new St.Label({text: title,
            style: 'font-weight: bold;'}));

        this._fields = {};
        this._addField(box, 'name', entry?.name, 'Name');
        this._addField(box, 'url', entry?.url, 'URL (https://…)');
        this._addField(box, 'port', String(entry?.port ?? ''), 'Port (8069)');
        this._addField(box, 'keepass_db', entry?.keepass_db, 'KeePassXC DB path');
        this._addField(box, 'keepass_keyfile', entry?.keepass_keyfile,
            'KeePassXC key file (optional)');
        this._addField(box, 'keepass_yubikey_slot',
            String(entry?.keepass_yubikey_slot ?? ''),
            'YubiKey slot (1, 2, or empty)');
        this._addField(box, 'keepass_yubikey_serial', entry?.keepass_yubikey_serial,
            'YubiKey serial (optional)');
        this._addField(box, 'keepass_entry', entry?.keepass_entry,
            'KeePassXC entry title');
        this._addField(box, 'auto_login_method',
            entry?.auto_login_method ?? 'selenium',
            'auto_login_method: selenium | xdotool | none');

        const buttons = [
            {label: 'Cancel', action: () => this.close(),
                key: Clutter.KEY_Escape},
            {label: 'Save', action: () => this._confirm(), default: true},
        ];
        if (onDelete) {
            buttons.unshift({label: 'Delete',
                action: () => { onDelete(); this.close(); }});
        }
        this.setButtons(buttons);
    }

    _addField(box, key, initial, hint) {
        const e = new St.Entry({hint_text: hint, text: initial ?? ''});
        this._fields[key] = e;
        box.add_child(e);
    }

    _confirm() {
        const data = {};
        for (const [k, e] of Object.entries(this._fields))
            data[k] = e.get_text().trim();
        data.port = parseInt(data.port || '8069', 10) || 8069;
        data.keepass_yubikey_slot =
            parseInt(data.keepass_yubikey_slot || '0', 10) || 0;
        if (!['selenium', 'xdotool', 'none'].includes(data.auto_login_method))
            data.auto_login_method = 'selenium';
        if (!data.name || !data.url) return;
        this._onConfirm(data);
        this.close();
    }
});
```

- [ ] **Step 2: Commit**

```bash
node --check script/stream_deck/gnome-extension/ui/instance-dialog.js
git add script/stream_deck/gnome-extension/ui/instance-dialog.js
git commit -m "[ADD] stream_deck/gnome-extension: instance-dialog"
```

---

## Task 5: ERPLibre indicator

**Files:**
- Create: `script/stream_deck/gnome-extension/indicators/erplibre.js`

- [ ] **Step 1: Write indicator**

Create `indicators/erplibre.js`:

```javascript
import GObject from 'gi://GObject';
import GLib from 'gi://GLib';
import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {parseList, serializeList, uuid4} from '../lib/settings.js';
import {buildBrowserArgv, buildTerminalArgv, findTerminal,
    spawnDetached, runProcess} from '../lib/spawn.js';
import {detectLocalInstancesGjs} from '../lib/erplibre-detect.js';
import {callKeepassCli, masterPasswordCache, cacheKey}
    from '../lib/keepass.js';
import {InstanceDialog} from '../ui/instance-dialog.js';
import {MasterPwDialog} from '../ui/master-pw-dialog.js';

function _notify(title, body) {
    try { Main.notify(title, body); } catch (_e) {}
}

export const ErpLibreIndicator = GObject.registerClass(
class ErpLibreIndicator extends PanelMenu.Button {
    _init({extension, openPrefs}) {
        super._init(0.0, 'Stream Deck ERPLibre');
        this._extension = extension;
        this._openPrefs = openPrefs;
        this._settings = extension.getSettings();
        this._localCache = [];
        this.add_child(new St.Icon({
            icon_name: 'network-server-symbolic',
            style_class: 'system-status-icon',
        }));
        this._sigInstances = this._settings.connect('changed::instances',
            () => this._rebuildMenu());
        this._sigPattern = this._settings.connect(
            'changed::erplibre-local-pattern', () => this._rescanThenRebuild());
        this._sigAuto = this._settings.connect(
            'changed::erplibre-auto-detect', () => this._rescanThenRebuild());
        this._rescanThenRebuild();
    }

    destroy() {
        for (const s of [this._sigInstances, this._sigPattern, this._sigAuto])
            if (s) this._settings.disconnect(s);
        super.destroy();
    }

    async _rescanThenRebuild() {
        if (this._settings.get_boolean('erplibre-auto-detect')) {
            this._localCache = await detectLocalInstancesGjs(
                this._settings.get_string('erplibre-local-pattern'));
        } else {
            this._localCache = [];
        }
        this._rebuildMenu();
    }

    _rebuildMenu() {
        this.menu.removeAll();
        const remotes = parseList(this._settings.get_string('instances'));

        const localHeader = new PopupMenu.PopupMenuItem('— Local —',
            {reactive: false});
        this.menu.addMenuItem(localHeader);
        if (this._localCache.length === 0) {
            this.menu.addMenuItem(new PopupMenu.PopupMenuItem(
                '(no local instances)', {reactive: false}));
        } else {
            for (const inst of this._localCache)
                this.menu.addMenuItem(this._makeRow(inst, true));
        }

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        const remoteHeader = new PopupMenu.PopupMenuItem('— Remote —',
            {reactive: false});
        this.menu.addMenuItem(remoteHeader);
        if (remotes.length === 0) {
            this.menu.addMenuItem(new PopupMenu.PopupMenuItem(
                '(no remote instances — use Add)', {reactive: false}));
        } else {
            for (const inst of remotes)
                this.menu.addMenuItem(this._makeRow(inst, false));
        }

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const add = new PopupMenu.PopupMenuItem('+ Add remote instance…');
        add.connect('activate', () => this._openAddDialog());
        this.menu.addMenuItem(add);
        const rescan = new PopupMenu.PopupMenuItem('🔄 Re-scan local');
        rescan.connect('activate', () => this._rescanThenRebuild());
        this.menu.addMenuItem(rescan);
    }

    _makeRow(inst, isLocal) {
        const sub = new PopupMenu.PopupSubMenuMenuItem(inst.name);
        const open = new PopupMenu.PopupMenuItem('Open URL');
        open.connect('activate', () => this._launchBrowser(inst));
        sub.menu.addMenuItem(open);

        if (isLocal) {
            const start = new PopupMenu.PopupMenuItem('Start server');
            start.connect('activate', () => this._startServer(inst));
            sub.menu.addMenuItem(start);
        }

        const hasKeepass = inst.keepass_db && inst.keepass_entry;
        if (hasKeepass) {
            if (inst.auto_login_method !== 'none') {
                const login = new PopupMenu.PopupMenuItem(
                    `Auto-login (${inst.auto_login_method})`);
                login.connect('activate', () => this._autoLogin(inst));
                sub.menu.addMenuItem(login);
            }
            const cu = new PopupMenu.PopupMenuItem('Copy username');
            cu.connect('activate', () => this._copyAttr(inst, 'username'));
            sub.menu.addMenuItem(cu);
            const cp = new PopupMenu.PopupMenuItem('Copy password');
            cp.connect('activate', () => this._copyAttr(inst, 'password'));
            sub.menu.addMenuItem(cp);
            const ok = new PopupMenu.PopupMenuItem('Open in KeePassXC');
            ok.connect('activate', () => this._openInKeepassXC(inst));
            sub.menu.addMenuItem(ok);
        }

        const edit = new PopupMenu.PopupMenuItem('Edit instance');
        edit.connect('activate', () => this._editEntry(inst, isLocal));
        sub.menu.addMenuItem(edit);
        return sub;
    }

    _launchBrowser(inst) {
        spawnDetached(buildBrowserArgv(inst.url),
            {notify: _notify, title: 'ERPLibre'});
    }

    async _startServer(inst) {
        const terminal = await findTerminal();
        if (!terminal) return;
        const argv = buildTerminalArgv({
            cwd: inst.local_path,
            command: 'make run',
            terminal,
        });
        spawnDetached(argv, {notify: _notify, title: 'ERPLibre'});
    }

    async _withMasterPw(inst, action) {
        const key = cacheKey({
            db: inst.keepass_db,
            keyfile: inst.keepass_keyfile,
            yubikey_serial: inst.keepass_yubikey_serial,
        });
        const cached = masterPasswordCache.get(key);
        const run = pw => action(pw, key);
        if (cached !== undefined) return run(cached);
        const dlg = new MasterPwDialog({
            db: inst.keepass_db,
            onConfirm: pw => {
                masterPasswordCache.set(key, pw);
                run(pw);
            },
        });
        dlg.open();
    }

    async _fetchAttr(inst, attribute) {
        return new Promise(resolve => {
            this._withMasterPw(inst, async (pw, key) => {
                const result = await callKeepassCli({
                    db: inst.keepass_db,
                    keyfile: inst.keepass_keyfile,
                    yubikey_slot: inst.keepass_yubikey_slot,
                    yubikey_serial: inst.keepass_yubikey_serial,
                    entry: inst.keepass_entry,
                    attribute,
                    masterPassword: pw,
                });
                if (result === null) {
                    masterPasswordCache.invalidate(key);
                    _notify('ERPLibre', 'KeePassXC unlock failed');
                }
                resolve(result);
            });
        });
    }

    async _copyAttr(inst, attribute) {
        const value = await this._fetchAttr(inst, attribute);
        if (value === null || value === undefined) return;
        try {
            const Clipboard = St.Clipboard.get_default();
            Clipboard.set_text(St.ClipboardType.CLIPBOARD, value);
            _notify('ERPLibre', `${attribute} copied`);
        } catch (_e) {}
    }

    _openInKeepassXC(inst) {
        const argv = ['keepassxc', inst.keepass_db];
        if (inst.keepass_keyfile) argv.push('--keyfile', inst.keepass_keyfile);
        spawnDetached(argv, {notify: _notify, title: 'ERPLibre'});
    }

    async _autoLogin(inst) {
        const user = await this._fetchAttr(inst, 'username');
        if (!user) return;
        const pass = await this._fetchAttr(inst, 'password');
        if (!pass) return;
        if (inst.auto_login_method === 'selenium')
            this._autoLoginSelenium(inst, user, pass);
        else if (inst.auto_login_method === 'xdotool')
            this._autoLoginXdotool(inst, user, pass);
    }

    _autoLoginSelenium(inst, user, pass) {
        // Resolve project root: assume extension lives in
        //   script/stream_deck/gnome-extension; root is three dirs up.
        const home = GLib.get_home_dir();
        const root = this._settings.get_string('git-sync-path').trim()
            || this._extension.path.replace(
                /\/script\/stream_deck\/gnome-extension\/?$/, '');
        const venv = `${root}/.venv.erplibre/bin/python`;
        const script = `${root}/script/selenium/web_login.py`;
        const argv = [venv, script,
            '--url', inst.url, '--user', user, '--pass', pass];
        if (!GLib.file_test(venv, GLib.FileTest.IS_EXECUTABLE)) {
            _notify('ERPLibre',
                `.venv.erplibre missing — falling back to xdotool`);
            this._autoLoginXdotool(inst, user, pass);
            return;
        }
        runProcess(argv, {notify: _notify, title: 'ERPLibre'});
    }

    async _autoLoginXdotool(inst, user, pass) {
        spawnDetached(buildBrowserArgv(inst.url),
            {notify: _notify, title: 'ERPLibre'});
        // Wait for browser focus to land. xdotool itself is the runner.
        const seq = [
            ['sleep', '2'],
            ['xdotool', 'type', user],
            ['xdotool', 'key', 'Tab'],
            ['xdotool', 'type', pass],
            ['xdotool', 'key', 'Return'],
        ];
        for (const argv of seq)
            await runProcess(argv, {notify: _notify, title: 'ERPLibre'});
    }

    _openAddDialog() {
        const dlg = new InstanceDialog({
            title: 'Add remote instance',
            onConfirm: data => {
                const list = parseList(this._settings.get_string('instances'));
                list.push({id: uuid4(), type: 'remote',
                    local_path: '', ...data});
                this._settings.set_string('instances', serializeList(list));
            },
        });
        dlg.open();
    }

    _editEntry(inst, isLocal) {
        if (isLocal) {
            // Local instances aren't persisted; promote to remote on save.
            const dlg = new InstanceDialog({
                title: 'Edit local override → save as remote',
                entry: inst,
                onConfirm: data => {
                    const list = parseList(this._settings.get_string('instances'));
                    list.push({id: uuid4(), type: 'remote',
                        local_path: '', ...data});
                    this._settings.set_string('instances', serializeList(list));
                },
            });
            dlg.open();
            return;
        }
        const dlg = new InstanceDialog({
            title: 'Edit instance',
            entry: inst,
            onConfirm: data => {
                const list = parseList(this._settings.get_string('instances'));
                const i = list.findIndex(e => e.id === inst.id);
                if (i >= 0) {
                    list[i] = {...list[i], ...data};
                    this._settings.set_string('instances', serializeList(list));
                }
            },
            onDelete: () => {
                const list = parseList(this._settings.get_string('instances'))
                    .filter(e => e.id !== inst.id);
                this._settings.set_string('instances', serializeList(list));
            },
        });
        dlg.open();
    }
});

export const indicatorDescriptor = {
    id: 'erplibre',
    displayName: 'ERPLibre',
    defaultEnabled: true,
    ctor: (opts) => new ErpLibreIndicator(opts),
};
```

- [ ] **Step 2: Syntax check + commit**

```bash
node --check script/stream_deck/gnome-extension/indicators/erplibre.js
git add script/stream_deck/gnome-extension/indicators/erplibre.js
git commit -m "[ADD] stream_deck/gnome-extension: erplibre indicator"
```

---

## Task 6: Register + prefs page + manual checklist

**Files:**
- Modify: `script/stream_deck/gnome-extension/extension.js`
- Modify: `script/stream_deck/gnome-extension/prefs.js`
- Modify: `script/stream_deck/gnome-extension/test/manual.md`

- [ ] **Step 1: Register descriptor**

Add to `extension.js`:

```javascript
import {indicatorDescriptor as erplibreDescriptor}
    from './indicators/erplibre.js';
```

In `enable()` after film registration:

```javascript
this.#registry.register(erplibreDescriptor);
```

- [ ] **Step 2: Add prefs page**

Append to `prefs.js`:

```javascript
window.add(this._buildErpLibrePage(settings));
```

```javascript
_buildErpLibrePage(settings) {
    const page = new Adw.PreferencesPage({
        title: 'ERPLibre', icon_name: 'network-server-symbolic',
    });
    const detect = new Adw.PreferencesGroup({title: 'Local detection'});
    const autoRow = new Adw.SwitchRow({
        title: 'Auto-detect local instances'});
    settings.bind('erplibre-auto-detect', autoRow, 'active',
        Gio.SettingsBindFlags.DEFAULT);
    detect.add(autoRow);
    const patternRow = new Adw.EntryRow({title: 'Local search pattern'});
    settings.bind('erplibre-local-pattern', patternRow, 'text',
        Gio.SettingsBindFlags.DEFAULT);
    detect.add(patternRow);
    page.add(detect);

    const remotes = new Adw.PreferencesGroup({
        title: 'Remote instances',
        description: 'Edit via the Add instance dialog from the panel button.',
    });
    page.add(remotes);
    return page;
}
```

- [ ] **Step 3: Reload + smoke**

```bash
glib-compile-schemas script/stream_deck/gnome-extension/schemas/
gnome-extensions disable streamdeck-tiler@technolibre.ca
gnome-extensions enable  streamdeck-tiler@technolibre.ca
```

- [ ] **Step 4: Append manual checklist**

Append to `test/manual.md`:

```markdown
## ERPLibre (Plan D)

- [ ] ERPLibre indicator with `network-server-symbolic` icon
- [ ] Local section lists all `~/erplibre*` directories with `.git` + `env_var.sh`
- [ ] Local instance "Open URL" → browser opens `http://localhost:<port>`
- [ ] Local instance "Start server" → terminal opens at the dir running `make run`
- [ ] Add remote instance with valid keepass DB + entry → submenu shows Auto-login, Copy username, Copy password, Open in KeePassXC
- [ ] First Copy username triggers master-pw dialog; correct pw → notify "username copied"
- [ ] Wrong pw → notify "KeePassXC unlock failed", cache invalidated, next click re-prompts
- [ ] Auto-login (selenium) → opens browser + Selenium script logs in (visible in browser)
- [ ] Auto-login (selenium) when `.venv.erplibre/bin/python` missing → falls back to xdotool, notifies
- [ ] Auto-login (xdotool) → browser opens, fields fill in
- [ ] Edit remote instance → dialog pre-filled, Save updates, Delete removes
- [ ] `gsettings set erplibre-auto-detect false` → local section becomes empty
- [ ] Re-scan local item rebuilds the local list
```

- [ ] **Step 5: Commit**

```bash
git add script/stream_deck/gnome-extension/extension.js \
        script/stream_deck/gnome-extension/prefs.js \
        script/stream_deck/gnome-extension/test/manual.md
git commit -m "[ADD] stream_deck/gnome-extension: register erplibre + prefs + checklist"
```

---

## Self-review

- Spec §5.4 local + remote sections + sub-menu actions → Task 5 ✓
- Spec §7 keepass cache 5-min TTL → Task 1 (`MasterPasswordCache` default `ttlMs`) ✓
- Spec §8.8 keyfile + YubiKey fields → Task 1 `callKeepassCli` argv + Task 4 dialog fields ✓
- Spec §8.9 xdotool fallback flagged experimental → Task 5 `_autoLoginXdotool`. Experimental warning is in the dialog hint text and README (Plan H).
- Spec §6.4 prefs page → Task 6 ✓
- Migration of legacy `erplibre_path` → handled by Plan A; ERPLibre detection on top reads existing instances/auto-detect ✓
- Spec §12 open question on `.venv.erplibre` presence → Task 5 `_autoLoginSelenium` falls back to xdotool with notify ✓

No placeholders.
