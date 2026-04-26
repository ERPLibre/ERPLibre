# Plan A — Stream Deck Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lay the registry-based architecture, GSettings schema, JSON migration, base shared libraries (`spawn`, `settings`, `registry`), extracted controller indicator, prefs skeleton with Buttons page. No new user-visible features beyond preserving the existing controller behaviour.

**Architecture:** A central `IndicatorRegistry` exposes `register({id, ctor, defaultEnabled})`. `extension.js` enable() iterates the registry, instantiates each indicator whose `enable-<id>` GSettings key is true, and listens to changes for live add/remove. JSON list-shaped settings are serialised as `'s'` GSettings keys for dconf legibility.

**Tech Stack:** GJS (GNOME Shell ESM), Adwaita (libadwaita) for prefs, `Gio.Settings` schema XML, Node `node --test` for pure-logic unit tests.

**Spec reference:** `docs/superpowers/specs/2026-04-26-stream-deck-multi-indicator-design.md` §3, §4, §6, §7.1, §7.3, §9.

---

## File structure (this plan)

| File | Action | Purpose |
|---|---|---|
| `script/stream_deck/gnome-extension/metadata.json` | modify | add `gettext-domain`, `settings-schema` |
| `script/stream_deck/gnome-extension/schemas/org.gnome.shell.extensions.streamdeck-tiler.gschema.xml` | create | GSettings schema for foundation keys |
| `script/stream_deck/gnome-extension/lib/settings.js` | create | GSettings wrapper, JSON helpers, migration |
| `script/stream_deck/gnome-extension/lib/registry.js` | create | IndicatorRegistry |
| `script/stream_deck/gnome-extension/lib/spawn.js` | create | subprocess + notify helpers |
| `script/stream_deck/gnome-extension/indicators/controller.js` | create | extracted controller indicator |
| `script/stream_deck/gnome-extension/extension.js` | modify | use registry; preserve D-Bus + HotReload |
| `script/stream_deck/gnome-extension/prefs.js` | create | Adwaita prefs skeleton with Buttons page |
| `script/stream_deck/gnome-extension/test/unit/settings.test.js` | create | unit tests for settings helpers + migration |
| `script/stream_deck/gnome-extension/test/unit/registry.test.js` | create | unit tests for registry |
| `script/stream_deck/gnome-extension/test/unit/spawn.test.js` | create | unit tests for spawn cmdline builders |
| `script/stream_deck/gnome-extension/test/fixtures/legacy-extension-settings.json` | create | migration fixture |
| `script/stream_deck/gnome-extension/test/manual.md` | create | manual smoke checklist |
| `conf/make.test.Makefile` | modify | add `test_gnome_extension` target |

---

## Task 1: Add metadata.json fields and seed directory tree

**Files:**
- Modify: `script/stream_deck/gnome-extension/metadata.json`
- Create: `script/stream_deck/gnome-extension/lib/.keep`
- Create: `script/stream_deck/gnome-extension/indicators/.keep`
- Create: `script/stream_deck/gnome-extension/ui/.keep`
- Create: `script/stream_deck/gnome-extension/schemas/.keep`
- Create: `script/stream_deck/gnome-extension/test/unit/.keep`
- Create: `script/stream_deck/gnome-extension/test/fixtures/.keep`

- [ ] **Step 1: Read current metadata**

```bash
cat script/stream_deck/gnome-extension/metadata.json
```

- [ ] **Step 2: Add gettext-domain and settings-schema fields**

Edit `metadata.json` so it contains (in addition to existing fields):

```json
{
  "gettext-domain": "streamdeck-tiler",
  "settings-schema": "org.gnome.shell.extensions.streamdeck-tiler"
}
```

Preserve existing keys (`uuid`, `name`, `description`, `shell-version`, `url`).

- [ ] **Step 3: Create empty subdirectories**

```bash
mkdir -p script/stream_deck/gnome-extension/{lib,indicators,ui,schemas,test/unit,test/fixtures}
touch script/stream_deck/gnome-extension/{lib,indicators,ui,schemas,test/unit,test/fixtures}/.keep
```

- [ ] **Step 4: Verify tree exists**

Run: `find script/stream_deck/gnome-extension -type d | sort`
Expected: lists `gnome-extension`, `gnome-extension/indicators`, `gnome-extension/lib`, `gnome-extension/schemas`, `gnome-extension/test`, `gnome-extension/test/fixtures`, `gnome-extension/test/unit`, `gnome-extension/ui`.

- [ ] **Step 5: Commit**

```bash
git add script/stream_deck/gnome-extension/metadata.json \
        script/stream_deck/gnome-extension/lib/.keep \
        script/stream_deck/gnome-extension/indicators/.keep \
        script/stream_deck/gnome-extension/ui/.keep \
        script/stream_deck/gnome-extension/schemas/.keep \
        script/stream_deck/gnome-extension/test/unit/.keep \
        script/stream_deck/gnome-extension/test/fixtures/.keep
git commit -m "[ADD] stream_deck/gnome-extension: scaffold dirs + metadata fields"
```

---

## Task 2: Write GSettings schema for foundation keys

**Files:**
- Create: `script/stream_deck/gnome-extension/schemas/org.gnome.shell.extensions.streamdeck-tiler.gschema.xml`

- [ ] **Step 1: Write the schema file**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<schemalist gettext-domain="streamdeck-tiler">
  <schema id="org.gnome.shell.extensions.streamdeck-tiler"
          path="/org/gnome/shell/extensions/streamdeck-tiler/">

    <!-- Per-indicator toggles -->
    <key name="enable-controller" type="b"><default>true</default><summary>Enable controller indicator</summary></key>
    <key name="enable-pencil"     type="b"><default>true</default><summary>Enable pencil indicator</summary></key>
    <key name="enable-film"       type="b"><default>true</default><summary>Enable film indicator</summary></key>
    <key name="enable-erplibre"   type="b"><default>true</default><summary>Enable ERPLibre indicator</summary></key>
    <key name="enable-network"    type="b"><default>true</default><summary>Enable network indicator</summary></key>
    <key name="enable-device"     type="b"><default>true</default><summary>Enable device indicator</summary></key>

    <!-- Top-bar ordering -->
    <key name="button-order" type="as">
      <default>['device','network','erplibre','film','pencil','controller']</default>
      <summary>Order of indicators left to right in the top bar</summary>
    </key>

    <!-- Catalogues (JSON serialised) -->
    <key name="paths"        type="s"><default>"[]"</default><summary>Paths catalogue (JSON array)</summary></key>
    <key name="films"        type="s"><default>"[]"</default><summary>Films catalogue (JSON array)</summary></key>
    <key name="instances"    type="s"><default>"[]"</default><summary>ERPLibre instances catalogue (JSON array)</summary></key>
    <key name="recent-paths" type="s"><default>"[]"</default><summary>Recently opened paths (JSON array, capped at 10)</summary></key>

    <!-- Pencil -->
    <key name="terminal-claude-cmd" type="s">
      <default>"claude --resume"</default>
      <summary>Default command run inside gnome-terminal for pencil entries</summary>
    </key>

    <!-- ERPLibre -->
    <key name="erplibre-auto-detect"   type="b"><default>true</default><summary>Auto-detect local ERPLibre instances</summary></key>
    <key name="erplibre-local-pattern" type="s"><default>"~/erplibre*"</default><summary>Glob pattern for local ERPLibre dirs</summary></key>

    <!-- Network -->
    <key name="network-cidrs"            type="as"><default>[]</default><summary>CIDR ranges to scan; empty = auto-detect</summary></key>
    <key name="network-ssh-user"         type="s"><default>""</default><summary>SSH user; empty = $USER</summary></key>
    <key name="network-use-nmap"         type="b"><default>true</default><summary>Use nmap when available, else nc fallback</summary></key>
    <key name="network-read-ssh-config"  type="b"><default>true</default><summary>Show ~/.ssh/config hosts in network indicator</summary></key>
    <key name="network-auto-refresh-sec" type="i"><default>0</default><summary>Auto-refresh interval seconds; 0 disables</summary></key>

    <!-- Device -->
    <key name="device-auto-refresh-sec"  type="i"><default>0</default><summary>Auto-refresh interval seconds; 0 disables</summary></key>

    <!-- Theming -->
    <key name="icon-overrides" type="s"><default>"{}"</default><summary>Per-indicator icon overrides (JSON object)</summary></key>

    <!-- Sync -->
    <key name="enable-git-sync" type="b"><default>false</default><summary>Enable settings sync via git</summary></key>
    <key name="git-sync-path"   type="s"><default>""</default><summary>Path to a git repo holding the sync JSON</summary></key>

    <!-- Migration -->
    <key name="schema-version"  type="i"><default>1</default><summary>Schema version, bumped per migration</summary></key>
    <key name="migration-done"  type="b"><default>false</default><summary>True after legacy JSON has been migrated</summary></key>
  </schema>
</schemalist>
```

- [ ] **Step 2: Compile schema and verify**

Run:

```bash
glib-compile-schemas --strict --dry-run script/stream_deck/gnome-extension/schemas/
```

Expected: no output, exit 0.

- [ ] **Step 3: Compile to gschemas.compiled (for runtime)**

Run:

```bash
glib-compile-schemas script/stream_deck/gnome-extension/schemas/
```

Expected: file `schemas/gschemas.compiled` created.

- [ ] **Step 4: Add gschemas.compiled to .gitignore**

Append to `script/stream_deck/gnome-extension/.gitignore` (create if missing):

```
schemas/gschemas.compiled
```

- [ ] **Step 5: Commit**

```bash
git add script/stream_deck/gnome-extension/schemas/org.gnome.shell.extensions.streamdeck-tiler.gschema.xml \
        script/stream_deck/gnome-extension/.gitignore
git commit -m "[ADD] stream_deck/gnome-extension: GSettings schema"
```

---

## Task 3: Implement settings module pure-logic helpers

**Files:**
- Create: `script/stream_deck/gnome-extension/lib/settings.js`
- Create: `script/stream_deck/gnome-extension/test/unit/settings.test.js`

The settings module exposes pure JSON helpers (testable in Node) and a thin `Gio.Settings` wrapper (only loadable in GJS). Tests cover the JSON helpers; the `Gio.Settings` wrapper is exercised via manual smoke + integration.

- [ ] **Step 1: Write the failing test for parseList / serializeList**

Create `test/unit/settings.test.js`:

```javascript
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {parseList, serializeList, pushRecent, MAX_RECENT}
    from '../../lib/settings.js';

test('parseList returns [] on bad JSON', () => {
    assert.deepEqual(parseList('not json'), []);
    assert.deepEqual(parseList(''), []);
    assert.deepEqual(parseList('null'), []);
});

test('parseList returns array on valid JSON array', () => {
    assert.deepEqual(parseList('[{"a":1}]'), [{a: 1}]);
});

test('parseList returns [] when JSON is not an array', () => {
    assert.deepEqual(parseList('{"x":1}'), []);
    assert.deepEqual(parseList('"string"'), []);
});

test('serializeList round-trips', () => {
    const data = [{a: 1}, {b: 'two'}];
    assert.deepEqual(parseList(serializeList(data)), data);
});

test('pushRecent prepends + dedupes + caps', () => {
    let r = [];
    for (let i = 0; i < MAX_RECENT + 3; i++) r = pushRecent(r, `/p${i}`);
    assert.equal(r.length, MAX_RECENT);
    assert.equal(r[0], `/p${MAX_RECENT + 2}`);
});

test('pushRecent moves duplicate to front', () => {
    const r = pushRecent(['/a', '/b', '/c'], '/b');
    assert.deepEqual(r, ['/b', '/a', '/c']);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test script/stream_deck/gnome-extension/test/unit/settings.test.js`
Expected: failure — `Cannot find module '../../lib/settings.js'`.

- [ ] **Step 3: Implement settings.js**

Create `lib/settings.js`:

```javascript
/**
 * Settings module. Pure JSON helpers + Gio.Settings wrapper.
 *
 * Pure helpers are tested via node --test. The Gio.Settings wrapper
 * is only usable from GJS at extension runtime.
 */

export const MAX_RECENT = 10;

export function parseList(serialized) {
    if (typeof serialized !== 'string' || serialized === '') return [];
    try {
        const parsed = JSON.parse(serialized);
        return Array.isArray(parsed) ? parsed : [];
    } catch (_e) {
        return [];
    }
}

export function serializeList(arr) {
    return JSON.stringify(Array.isArray(arr) ? arr : []);
}

export function parseObject(serialized) {
    if (typeof serialized !== 'string' || serialized === '') return {};
    try {
        const parsed = JSON.parse(serialized);
        return (parsed && typeof parsed === 'object' && !Array.isArray(parsed))
            ? parsed
            : {};
    } catch (_e) {
        return {};
    }
}

export function serializeObject(obj) {
    return JSON.stringify(obj && typeof obj === 'object' ? obj : {});
}

export function pushRecent(arr, value) {
    const list = Array.isArray(arr) ? arr.slice() : [];
    const filtered = list.filter(v => v !== value);
    filtered.unshift(value);
    return filtered.slice(0, MAX_RECENT);
}

/**
 * Generate a UUID v4 (RFC 4122). Used for stable IDs on catalogue entries.
 * Pure JS so it works in both Node tests and GJS runtime.
 */
export function uuid4() {
    const bytes = new Uint8Array(16);
    if (typeof globalThis.crypto?.getRandomValues === 'function') {
        globalThis.crypto.getRandomValues(bytes);
    } else {
        for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256);
    }
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const h = [...bytes].map(b => b.toString(16).padStart(2, '0'));
    return `${h.slice(0, 4).join('')}-${h.slice(4, 6).join('')}-${h.slice(6, 8).join('')}-${h.slice(8, 10).join('')}-${h.slice(10).join('')}`;
}

/**
 * GJS-only thin wrapper around Gio.Settings. Lazily loaded so Node tests
 * importing this file don't blow up.
 */
let _gioSettings = null;
export function getSettings(extensionInstance) {
    if (_gioSettings) return _gioSettings;
    _gioSettings = extensionInstance.getSettings();
    return _gioSettings;
}

export function resetCachedSettings() {
    _gioSettings = null;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test script/stream_deck/gnome-extension/test/unit/settings.test.js`
Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add script/stream_deck/gnome-extension/lib/settings.js \
        script/stream_deck/gnome-extension/test/unit/settings.test.js
git commit -m "[ADD] stream_deck/gnome-extension: settings JSON helpers + tests"
```

---

## Task 4: Implement legacy JSON migration

**Files:**
- Modify: `script/stream_deck/gnome-extension/lib/settings.js`
- Modify: `script/stream_deck/gnome-extension/test/unit/settings.test.js`
- Create: `script/stream_deck/gnome-extension/test/fixtures/legacy-extension-settings.json`

- [ ] **Step 1: Add fixture**

Create `test/fixtures/legacy-extension-settings.json`:

```json
{
  "erplibre_path": "/home/leo/erplibre"
}
```

- [ ] **Step 2: Write failing migration tests**

Append to `test/unit/settings.test.js`:

```javascript
import {migrateLegacyJson} from '../../lib/settings.js';

test('migrateLegacyJson seeds paths from erplibre_path', () => {
    const legacy = {erplibre_path: '/home/leo/erplibre'};
    const out = migrateLegacyJson(legacy, []);
    assert.equal(out.length, 1);
    assert.equal(out[0].path, '/home/leo/erplibre');
    assert.equal(out[0].label, 'ERPLibre');
    assert.match(out[0].id, /^[0-9a-f]{8}-/);
});

test('migrateLegacyJson is no-op when paths already populated', () => {
    const existing = [{id: 'x', label: 'L', path: '/p'}];
    const out = migrateLegacyJson({erplibre_path: '/other'}, existing);
    assert.deepEqual(out, existing);
});

test('migrateLegacyJson handles missing erplibre_path', () => {
    assert.deepEqual(migrateLegacyJson({}, []), []);
});

test('migrateLegacyJson tolerates corrupted legacy', () => {
    assert.deepEqual(migrateLegacyJson(null, []), []);
    assert.deepEqual(migrateLegacyJson('garbage', []), []);
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `node --test script/stream_deck/gnome-extension/test/unit/settings.test.js`
Expected: 4 new tests fail with `migrateLegacyJson is not a function`.

- [ ] **Step 4: Implement migrateLegacyJson + helper to read legacy file**

Append to `lib/settings.js`:

```javascript
/**
 * Pure-logic migration: given the parsed legacy JSON object and the
 * existing paths array, return the new paths array. No file I/O.
 */
export function migrateLegacyJson(legacy, existingPaths) {
    if (Array.isArray(existingPaths) && existingPaths.length > 0) {
        return existingPaths;
    }
    if (!legacy || typeof legacy !== 'object') return existingPaths || [];
    const erpPath = legacy.erplibre_path;
    if (typeof erpPath !== 'string' || !erpPath.trim()) {
        return existingPaths || [];
    }
    return [{
        id: uuid4(),
        label: 'ERPLibre',
        path: erpPath,
        default_cmd: 'claude --resume',
    }];
}

/**
 * Default legacy JSON path. GJS-only — wrapped in a function so Node
 * tests don't import GLib.
 */
export async function legacyJsonPath() {
    const {default: GLib} = await import('gi://GLib');
    return GLib.build_filenamev([
        GLib.get_user_config_dir(),
        'streamdeck-tiler',
        'extension-settings.json',
    ]);
}

/**
 * Run the migration at extension enable time. Callable only from GJS.
 *
 *   1. If migration-done is true, no-op.
 *   2. Read legacy JSON; on parse failure, log + mark done + exit.
 *   3. Merge into paths; bump schema-version + migration-done.
 *   4. Rename the legacy file to <name>.bak.
 */
export async function runMigrationGjs(settings, log = console.log) {
    if (settings.get_boolean('migration-done')) return;
    const {default: GLib} = await import('gi://GLib');
    const path = await legacyJsonPath();
    let legacy = {};
    if (GLib.file_test(path, GLib.FileTest.EXISTS)) {
        try {
            const [ok, contents] = GLib.file_get_contents(path);
            if (ok) legacy = JSON.parse(new TextDecoder().decode(contents));
        } catch (e) {
            log(`[StreamDeckTiler] migration: bad legacy JSON: ${e.message}`);
            legacy = {};
        }
    }
    const existing = parseList(settings.get_string('paths'));
    const merged = migrateLegacyJson(legacy, existing);
    if (merged !== existing) {
        settings.set_string('paths', serializeList(merged));
    }
    settings.set_int('schema-version', 1);
    settings.set_boolean('migration-done', true);
    if (GLib.file_test(path, GLib.FileTest.EXISTS)) {
        try {
            GLib.rename(path, `${path}.bak`);
        } catch (_e) {}
    }
}
```

- [ ] **Step 5: Run tests + commit**

```bash
node --test script/stream_deck/gnome-extension/test/unit/settings.test.js
```

Expected: 10 tests pass.

```bash
git add script/stream_deck/gnome-extension/lib/settings.js \
        script/stream_deck/gnome-extension/test/unit/settings.test.js \
        script/stream_deck/gnome-extension/test/fixtures/legacy-extension-settings.json
git commit -m "[ADD] stream_deck/gnome-extension: legacy JSON migration"
```

---

## Task 5: Implement IndicatorRegistry

**Files:**
- Create: `script/stream_deck/gnome-extension/lib/registry.js`
- Create: `script/stream_deck/gnome-extension/test/unit/registry.test.js`

- [ ] **Step 1: Write failing tests**

Create `test/unit/registry.test.js`:

```javascript
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {IndicatorRegistry} from '../../lib/registry.js';

test('register stores entries by id', () => {
    const reg = new IndicatorRegistry();
    const ctorA = () => ({});
    reg.register({id: 'a', ctor: ctorA, displayName: 'A'});
    assert.equal(reg.list().length, 1);
    assert.equal(reg.list()[0].id, 'a');
    assert.equal(reg.get('a').ctor, ctorA);
});

test('register rejects duplicate ids', () => {
    const reg = new IndicatorRegistry();
    reg.register({id: 'a', ctor: () => ({}), displayName: 'A'});
    assert.throws(
        () => reg.register({id: 'a', ctor: () => ({}), displayName: 'A2'}),
        /already registered/
    );
});

test('list preserves registration order', () => {
    const reg = new IndicatorRegistry();
    reg.register({id: 'a', ctor: () => ({}), displayName: 'A'});
    reg.register({id: 'b', ctor: () => ({}), displayName: 'B'});
    reg.register({id: 'c', ctor: () => ({}), displayName: 'C'});
    assert.deepEqual(reg.list().map(e => e.id), ['a', 'b', 'c']);
});

test('orderedIds applies button-order, ignoring unknowns, appending missing', () => {
    const reg = new IndicatorRegistry();
    for (const id of ['a', 'b', 'c']) {
        reg.register({id, ctor: () => ({}), displayName: id});
    }
    assert.deepEqual(reg.orderedIds(['c', 'a']), ['c', 'a', 'b']);
    assert.deepEqual(reg.orderedIds(['z', 'b']), ['b', 'a', 'c']);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test script/stream_deck/gnome-extension/test/unit/registry.test.js`
Expected: fail — module not found.

- [ ] **Step 3: Implement registry.js**

Create `lib/registry.js`:

```javascript
/**
 * Registry of indicator descriptors. Decouples instantiation from
 * extension.js so adding a button = one register() call.
 */
export class IndicatorRegistry {
    constructor() {
        this._entries = new Map();
        this._order = [];
    }

    register({id, ctor, displayName, defaultEnabled = true}) {
        if (this._entries.has(id)) {
            throw new Error(`Indicator id '${id}' already registered`);
        }
        if (typeof ctor !== 'function') {
            throw new Error(`Indicator '${id}' ctor must be a function`);
        }
        this._entries.set(id, {id, ctor, displayName, defaultEnabled});
        this._order.push(id);
    }

    get(id) {
        return this._entries.get(id);
    }

    list() {
        return this._order.map(id => this._entries.get(id));
    }

    /**
     * Apply user-configured order, ignoring unknown ids, then append
     * registered ids that are not in the user list (for forward-compat).
     */
    orderedIds(userOrder) {
        const known = new Set(this._entries.keys());
        const result = [];
        const seen = new Set();
        for (const id of (userOrder || [])) {
            if (known.has(id) && !seen.has(id)) {
                result.push(id);
                seen.add(id);
            }
        }
        for (const id of this._order) {
            if (!seen.has(id)) result.push(id);
        }
        return result;
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test script/stream_deck/gnome-extension/test/unit/registry.test.js`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add script/stream_deck/gnome-extension/lib/registry.js \
        script/stream_deck/gnome-extension/test/unit/registry.test.js
git commit -m "[ADD] stream_deck/gnome-extension: IndicatorRegistry"
```

---

## Task 6: Implement spawn helpers

**Files:**
- Create: `script/stream_deck/gnome-extension/lib/spawn.js`
- Create: `script/stream_deck/gnome-extension/test/unit/spawn.test.js`

`spawn.js` separates pure cmdline builders (testable) from GJS subprocess execution (manual smoke).

- [ ] **Step 1: Write failing tests for cmdline builders**

Create `test/unit/spawn.test.js`:

```javascript
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
    buildTerminalArgv,
    buildBrowserArgv,
    buildMpvArgv,
    parsePosition,
    formatPosition,
} from '../../lib/spawn.js';

test('buildTerminalArgv with cwd + command', () => {
    const argv = buildTerminalArgv({
        cwd: '/home/x/proj',
        command: 'claude --resume',
        terminal: 'gnome-terminal',
    });
    assert.deepEqual(argv, [
        'gnome-terminal', '--working-directory=/home/x/proj',
        '--', 'bash', '-lc', 'claude --resume; exec bash',
    ]);
});

test('buildTerminalArgv falls back to xterm', () => {
    const argv = buildTerminalArgv({
        cwd: '/p', command: 'cmd', terminal: 'xterm',
    });
    assert.deepEqual(argv, ['xterm', '-e',
        'bash -lc "cd /p && cmd; exec bash"']);
});

test('buildBrowserArgv', () => {
    assert.deepEqual(
        buildBrowserArgv('https://example.com'),
        ['xdg-open', 'https://example.com']
    );
});

test('buildMpvArgv with position', () => {
    assert.deepEqual(
        buildMpvArgv('https://x', '00:01:23'),
        ['mpv', '--start=00:01:23', 'https://x']
    );
});

test('buildMpvArgv without position', () => {
    assert.deepEqual(buildMpvArgv('https://x', ''), ['mpv', 'https://x']);
});

test('parsePosition handles hh:mm:ss / mm:ss / seconds', () => {
    assert.equal(parsePosition('01:23:45'), 5025);
    assert.equal(parsePosition('05:30'),    330);
    assert.equal(parsePosition('120'),      120);
    assert.equal(parsePosition(''),         0);
    assert.equal(parsePosition('garbage'),  0);
});

test('formatPosition seconds → hh:mm:ss', () => {
    assert.equal(formatPosition(5025), '01:23:45');
    assert.equal(formatPosition(0),    '00:00:00');
    assert.equal(formatPosition(59),   '00:00:59');
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test script/stream_deck/gnome-extension/test/unit/spawn.test.js`
Expected: fail — module not found.

- [ ] **Step 3: Implement spawn.js**

Create `lib/spawn.js`:

```javascript
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test script/stream_deck/gnome-extension/test/unit/spawn.test.js`
Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add script/stream_deck/gnome-extension/lib/spawn.js \
        script/stream_deck/gnome-extension/test/unit/spawn.test.js
git commit -m "[ADD] stream_deck/gnome-extension: spawn helpers + cmdline builders"
```

---

## Task 7: Extract controller into indicator module

**Files:**
- Create: `script/stream_deck/gnome-extension/indicators/controller.js`

The controller indicator preserves all existing behaviour: panel button with `input-gaming-symbolic`, About item, Games sub-menu (via `http://localhost:8042/api/games`), Settings sub-menu. The only behavioural change is "Settings" now opens the prefs window via `extension.openPreferences()` (replaces JSON-edit dialog).

- [ ] **Step 1: Read existing indicator code from extension.js**

Run: `sed -n '87,252p' script/stream_deck/gnome-extension/extension.js`
This is the `StreamDeckTilerIndicator` class. Read fully — Task 8 will remove it from `extension.js`.

- [ ] **Step 2: Create controller.js with extracted class**

Create `indicators/controller.js`:

```javascript
import Gio from 'gi://Gio';
import GObject from 'gi://GObject';
import Soup from 'gi://Soup';
import St from 'gi://St';
import GLib from 'gi://GLib';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

const GALLERY_PORT = 8042;
const GALLERY_URL = `http://localhost:${GALLERY_PORT}`;
const PROJECT_URL = 'https://github.com/ERPLibre/ERPLibre';
const PROJECT_NAME = 'ERPLibre Stream Deck';

function _notify(title, body) {
    try {
        Main.notify(title, body);
    } catch (e) {
        console.log(`[StreamDeckTiler:controller] notify failed: ${e.message}`);
    }
}

export const ControllerIndicator = GObject.registerClass(
class ControllerIndicator extends PanelMenu.Button {
    _init({iconName = 'input-gaming-symbolic', openPrefs} = {}) {
        super._init(0.0, 'Stream Deck Controller');
        this._openPrefs = openPrefs;
        this.add_child(new St.Icon({
            icon_name: iconName,
            style_class: 'system-status-icon',
        }));
        this._buildMenu();
        this.menu.connect('open-state-changed', (_menu, isOpen) => {
            if (isOpen) this._refreshGames();
        });
    }

    _buildMenu() {
        const about = new PopupMenu.PopupMenuItem('About');
        about.connect('activate', () => {
            try {
                Gio.AppInfo.launch_default_for_uri(PROJECT_URL, null);
            } catch (_e) {
                _notify(PROJECT_NAME, `Open ${PROJECT_URL} for project info.`);
            }
        });
        this.menu.addMenuItem(about);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        this._gamesSection = new PopupMenu.PopupSubMenuMenuItem('Games');
        this.menu.addMenuItem(this._gamesSection);
        this._populateGamesPlaceholder('Loading…');

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        const settings = new PopupMenu.PopupMenuItem('Open prefs…');
        settings.connect('activate', () => {
            if (typeof this._openPrefs === 'function') this._openPrefs();
        });
        this.menu.addMenuItem(settings);
    }

    _populateGamesPlaceholder(label) {
        this._gamesSection.menu.removeAll();
        this._gamesSection.menu.addMenuItem(
            new PopupMenu.PopupMenuItem(label, {reactive: false}));
    }

    _refreshGames() {
        this._populateGamesPlaceholder('Loading…');
        const session = new Soup.Session();
        session.timeout = 3;
        const message = Soup.Message.new('GET', `${GALLERY_URL}/api/games`);
        session.send_and_read_async(
            message, GLib.PRIORITY_DEFAULT, null, (sess, result) => {
                try {
                    const bytes = sess.send_and_read_finish(result);
                    const text = new TextDecoder().decode(bytes.get_data());
                    const games = JSON.parse(text);
                    this._populateGames(Array.isArray(games) ? games : []);
                } catch (_e) {
                    this._populateGamesPlaceholder(
                        'Gallery offline (start gallery_server.py)');
                }
            });
    }

    _populateGames(games) {
        this._gamesSection.menu.removeAll();
        if (!games.length) {
            this._populateGamesPlaceholder('No games found');
            return;
        }
        games.sort((a, b) =>
            (a.name || a.id || '').localeCompare(b.name || b.id || ''));
        for (const g of games) {
            const id = g.id || '';
            const name = g.name || id;
            if (!id) continue;
            const item = new PopupMenu.PopupMenuItem(name);
            item.connect('activate', () => this._launchGame(id));
            this._gamesSection.menu.addMenuItem(item);
        }
    }

    _launchGame(gameId) {
        const session = new Soup.Session();
        session.timeout = 3;
        const message = Soup.Message.new('GET',
            `${GALLERY_URL}/launch/${gameId}`);
        session.send_and_read_async(
            message, GLib.PRIORITY_DEFAULT, null, (sess, result) => {
                try {
                    sess.send_and_read_finish(result);
                } catch (_e) {
                    _notify(PROJECT_NAME,
                        `Could not launch ${gameId}: gallery offline?`);
                }
            });
    }
});

export const indicatorDescriptor = {
    id: 'controller',
    displayName: 'Controller',
    defaultEnabled: true,
    ctor: (opts) => new ControllerIndicator(opts),
};
```

- [ ] **Step 3: Verify the file imports cleanly (syntax)**

Run: `node --check script/stream_deck/gnome-extension/indicators/controller.js`
Expected: no output. (`--check` validates syntax without executing.)

- [ ] **Step 4: Visually diff against original behaviour**

Confirm each public surface matches the spec §5.1:
- icon `input-gaming-symbolic` ✓
- About item ✓
- Games sub-menu fetching `${GALLERY_URL}/api/games` ✓
- Settings → opens prefs (changed from JSON edit) ✓
- ListWindows / TileWindow / etc. NOT in this file (they live on extension.js export, see Task 8)

- [ ] **Step 5: Commit**

```bash
git add script/stream_deck/gnome-extension/indicators/controller.js
git commit -m "[ADD] stream_deck/gnome-extension: extract controller indicator"
```

---

## Task 8: Refactor extension.js around the registry

**Files:**
- Modify: `script/stream_deck/gnome-extension/extension.js`

The D-Bus interface, HotReload, HotExit, ListWindows, ApplyLayout, TileWindow, GetMonitorGeometry, GetGridSize, ListTrackerTimers, ToggleTrackerTimer, AddTrackerTimer, ResetAllTrackerTimers, GetFocusedWindowClass, _findByStyleClass, _stackingIndexMap, _collectAllWindows, _raiseWindow, _getTrackerIndicator, _extensionsDir, _removeExtensionByUuid, _listTempUuids, _patchMetadataUuid all stay on the extension class. Only the indicator instantiation changes.

- [ ] **Step 1: Replace the whole file with registry-driven version**

Replace `extension.js` with:

```javascript
/**
 * Stream Deck Tiler — GNOME Shell Extension
 *
 * Registry-based: each panel button is an indicator module under
 * indicators/. extension.js wires the D-Bus interface, instantiates
 * indicators based on GSettings, and reacts to live toggles.
 */

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

import {IndicatorRegistry} from './lib/registry.js';
import {parseList, runMigrationGjs} from './lib/settings.js';
import {indicatorDescriptor as controllerDescriptor}
    from './indicators/controller.js';

const TRACKER_UUID = 'tracker@aliakseiz.github.com';
const MAIN_UUID = 'streamdeck-tiler@technolibre.ca';
const RELOAD_UUID_PREFIX = 'streamdeck-tiler-reload-';
const EXTENSION_TYPE_PER_USER = 2;

const IFACE_XML = `
<node>
  <interface name="org.gnome.Shell.Extensions.StreamDeckTiler">
    <method name="TileWindow">
      <arg type="i" direction="in" name="gridCols"/>
      <arg type="i" direction="in" name="gridRows"/>
      <arg type="i" direction="in" name="col1"/>
      <arg type="i" direction="in" name="row1"/>
      <arg type="i" direction="in" name="col2"/>
      <arg type="i" direction="in" name="row2"/>
      <arg type="b" direction="out" name="success"/>
    </method>
    <method name="GetMonitorGeometry">
      <arg type="i" direction="out" name="x"/>
      <arg type="i" direction="out" name="y"/>
      <arg type="i" direction="out" name="width"/>
      <arg type="i" direction="out" name="height"/>
    </method>
    <method name="GetGridSize">
      <arg type="i" direction="in" name="gridCols"/>
      <arg type="i" direction="in" name="gridRows"/>
      <arg type="i" direction="out" name="cellW"/>
      <arg type="i" direction="out" name="cellH"/>
    </method>
    <method name="ListTrackerTimers"><arg type="s" direction="out" name="json"/></method>
    <method name="ToggleTrackerTimer">
      <arg type="s" direction="in" name="id"/>
      <arg type="b" direction="out" name="success"/>
    </method>
    <method name="AddTrackerTimer"><arg type="s" direction="out" name="id"/></method>
    <method name="HotReload"><arg type="s" direction="out" name="newUuid"/></method>
    <method name="HotExit"><arg type="b" direction="out" name="success"/></method>
    <method name="ResetAllTrackerTimers"><arg type="b" direction="out" name="success"/></method>
    <method name="ListWindows"><arg type="s" direction="out" name="json"/></method>
    <method name="ApplyLayout">
      <arg type="s" direction="in" name="json"/>
      <arg type="i" direction="out" name="matched"/>
    </method>
    <method name="GetFocusedWindowClass"><arg type="s" direction="out" name="wmClass"/></method>
  </interface>
</node>`;

export default class StreamDeckTilerExtension extends Extension {
    #dbus = null;
    #registrationId = 0;
    #indicators = new Map();
    #registry = null;
    #settings = null;
    #signalIds = [];

    enable() {
        this.#dbus = Gio.DBusExportedObject.wrapJSObject(IFACE_XML, this);
        this.#registrationId = this.#dbus.export(
            Gio.DBus.session,
            '/org/gnome/Shell/Extensions/StreamDeckTiler');

        this.#settings = this.getSettings();
        runMigrationGjs(this.#settings).catch(e =>
            console.log(`[StreamDeckTiler] migration failed: ${e.message}`));

        this.#registry = new IndicatorRegistry();
        this.#registry.register(controllerDescriptor);
        // Future indicators register themselves here via subsequent plans.

        this._buildIndicators();
        this._connectToggleSignals();

        const orderSig = this.#settings.connect('changed::button-order',
            () => this._reorderIndicators());
        this.#signalIds.push(orderSig);

        console.log('[StreamDeckTiler] enabled');
    }

    disable() {
        if (this.#dbus) {
            this.#dbus.unexport();
            this.#dbus = null;
        }
        for (const id of this.#signalIds) this.#settings?.disconnect(id);
        this.#signalIds = [];
        for (const ind of this.#indicators.values()) {
            try { ind.destroy(); } catch (e) {
                console.log(`[StreamDeckTiler] destroy ${e.message}`);
            }
        }
        this.#indicators.clear();
        this.#registry = null;
        this.#settings = null;
        console.log('[StreamDeckTiler] disabled');
    }

    _buildIndicators() {
        const order = this.#registry.orderedIds(
            this.#settings.get_strv('button-order'));
        for (const id of order) {
            if (this.#settings.get_boolean(`enable-${id}`)) {
                this._mount(id);
            }
        }
    }

    _connectToggleSignals() {
        for (const desc of this.#registry.list()) {
            const sig = this.#settings.connect(
                `changed::enable-${desc.id}`,
                () => this._toggleIndicator(desc.id));
            this.#signalIds.push(sig);
        }
    }

    _toggleIndicator(id) {
        const enabled = this.#settings.get_boolean(`enable-${id}`);
        if (enabled && !this.#indicators.has(id)) this._mount(id);
        else if (!enabled && this.#indicators.has(id)) this._unmount(id);
    }

    _mount(id) {
        const desc = this.#registry.get(id);
        if (!desc) return;
        try {
            const ind = desc.ctor({
                openPrefs: () => this.openPreferences(),
                extension: this,
            });
            const role = `${this.uuid}-${id}`;
            Main.panel.addToStatusArea(role, ind);
            this.#indicators.set(id, ind);
        } catch (e) {
            console.log(`[StreamDeckTiler] mount ${id} failed: ${e.message}`);
        }
    }

    _unmount(id) {
        const ind = this.#indicators.get(id);
        if (!ind) return;
        try { ind.destroy(); } catch (_e) {}
        this.#indicators.delete(id);
    }

    _reorderIndicators() {
        const order = this.#registry.orderedIds(
            this.#settings.get_strv('button-order'));
        for (const id of [...this.#indicators.keys()]) this._unmount(id);
        for (const id of order) {
            if (this.#settings.get_boolean(`enable-${id}`)) this._mount(id);
        }
    }

    // ---------- Tiling D-Bus methods (unchanged) ----------

    TileWindow(gridCols, gridRows, col1, row1, col2, row2) {
        const win = global.display.focus_window;
        if (!win) return false;
        const monIdx = win.get_monitor();
        const workArea = win.get_work_area_for_monitor(monIdx);
        const cellW = workArea.width / gridCols;
        const cellH = workArea.height / gridRows;
        const x = workArea.x + Math.round(col1 * cellW);
        const y = workArea.y + Math.round(row1 * cellH);
        const w = Math.round((col2 - col1 + 1) * cellW);
        const h = Math.round((row2 - row1 + 1) * cellH);
        win.unmaximize(Meta.MaximizeFlags.BOTH);
        win.move_resize_frame(true, x, y, w, h);
        return true;
    }

    GetMonitorGeometry() {
        const mon = global.display.get_primary_monitor();
        const wa = Main.layoutManager.getWorkAreaForMonitor(mon);
        return [wa.x, wa.y, wa.width, wa.height];
    }

    GetGridSize(gridCols, gridRows) {
        const mon = global.display.get_primary_monitor();
        const wa = Main.layoutManager.getWorkAreaForMonitor(mon);
        return [Math.round(wa.width / gridCols),
                Math.round(wa.height / gridRows)];
    }

    // ---------- Tracker proxy methods (unchanged from previous extension) ----------

    _getTrackerIndicator() {
        try {
            const ext = Main.extensionManager.lookup(TRACKER_UUID);
            if (!ext || !ext.stateObj) return null;
            return ext.stateObj._indicator ?? null;
        } catch (_e) { return null; }
    }

    ListTrackerTimers() {
        const ind = this._getTrackerIndicator();
        if (!ind || !Array.isArray(ind._timers)) return '[]';
        return JSON.stringify(ind._timers.map(t => ({
            id: t.id, name: t.name ?? '',
            running: !!t.running,
            elapsed: Math.round(t.timeElapsed || 0),
        })));
    }

    ToggleTrackerTimer(id) {
        const ind = this._getTrackerIndicator();
        if (!ind || !Array.isArray(ind._timers)) return false;
        const timer = ind._timers.find(t => t.id === id);
        if (!timer) return false;
        const now = GLib.get_real_time();
        if (timer.running) {
            const elapsed = (now - timer.lastUpdateTime) / 1000000;
            timer.timeElapsed = (timer.timeElapsed || 0) + elapsed;
            timer.running = false;
            timer.lastUpdateTime = null;
            timer.autoResume = false;
        } else {
            timer.running = true;
            timer.lastUpdateTime = now;
        }
        const ui = ind._timerUIElements?.get?.(timer.id);
        if (ui?.playPauseIcon) {
            ui.playPauseIcon.icon_name = timer.running
                ? 'media-playback-pause-symbolic'
                : 'media-playback-start-symbolic';
        }
        if (ui?.mainRow) {
            if (timer.running) ui.mainRow.remove_style_class_name('timer-paused');
            else ui.mainRow.add_style_class_name('timer-paused');
        }
        try { ind._saveTimers?.(); } catch (_e) {}
        return true;
    }

    AddTrackerTimer() {
        const ind = this._getTrackerIndicator();
        if (!ind || typeof ind._addNewTimer !== 'function') return '';
        const beforeIds = new Set((ind._timers || []).map(t => t.id));
        try { ind._addNewTimer(); } catch (_e) { return ''; }
        const newTimer = (ind._timers || []).find(t => !beforeIds.has(t.id));
        if (!newTimer) return '';
        try {
            ind.menu?.open?.();
            ind._editTimer?.(newTimer);
            const ui = ind._timerUIElements?.get?.(newTimer.id);
            const entry = ui?.mainRow
                ? this._findByStyleClass(ui.mainRow, 'name-entry')
                : null;
            if (entry) { entry.set_text(''); entry.grab_key_focus?.(); }
        } catch (_e) {}
        return newTimer.id;
    }

    ResetAllTrackerTimers() {
        const ind = this._getTrackerIndicator();
        if (!ind || typeof ind._resetAllTimers !== 'function') return false;
        try { ind._resetAllTimers(); return true; } catch (_e) { return false; }
    }

    // ---------- Window layout capture / restore (unchanged) ----------

    _collectAllWindows() {
        const out = [];
        try {
            const wsMgr = global.workspace_manager;
            const seen = new Set();
            for (let i = 0; i < wsMgr.n_workspaces; i++) {
                const ws = wsMgr.get_workspace_by_index(i);
                for (const w of ws.list_windows()) {
                    if (!w || seen.has(w)) continue;
                    seen.add(w);
                    if (w.get_window_type() !== Meta.WindowType.NORMAL) continue;
                    if (w.is_skip_taskbar?.()) continue;
                    out.push(w);
                }
            }
        } catch (_e) {}
        return out;
    }

    _stackingIndexMap(windows) {
        const map = new Map();
        try {
            const sorted = global.display.sort_windows_by_stacking(windows);
            sorted.forEach((w, i) => map.set(w, i));
        } catch (_e) {}
        return map;
    }

    _raiseWindow(win) {
        try {
            if (typeof win.raise === 'function') win.raise();
            else if (typeof win.raise_and_make_recent === 'function')
                win.raise_and_make_recent();
        } catch (_e) {}
    }

    ListWindows() {
        try {
            const windows = this._collectAllWindows();
            const stackMap = this._stackingIndexMap(windows);
            const out = windows.map(w => {
                const rect = w.get_frame_rect();
                return {
                    wm_class: w.get_wm_class() || '',
                    title: w.get_title() || '',
                    x: rect.x, y: rect.y, w: rect.width, h: rect.height,
                    workspace: w.get_workspace()?.index() ?? 0,
                    monitor: w.get_monitor(),
                    maximized: w.get_maximized(),
                    stacking: stackMap.get(w) ?? 0,
                };
            });
            return JSON.stringify(out);
        } catch (_e) { return '[]'; }
    }

    ApplyLayout(jsonStr) {
        let entries;
        try { entries = JSON.parse(jsonStr); } catch (_e) { return 0; }
        if (!Array.isArray(entries)) return 0;
        const liveList = this._collectAllWindows();
        const used = new Set();
        const matchedPairs = [];
        const wsMgr = global.workspace_manager;
        for (const entry of entries) {
            let best = null;
            let bestScore = -1;
            for (const w of liveList) {
                if (used.has(w)) continue;
                const cls = w.get_wm_class() || '';
                if (cls !== (entry.wm_class || '')) continue;
                const title = w.get_title() || '';
                let score = 1;
                if (title === entry.title) score += 1000;
                else if (entry.title && (title.includes(entry.title) ||
                    entry.title.includes(title))) score += 100;
                if (score > bestScore) { bestScore = score; best = w; }
            }
            if (!best) continue;
            used.add(best);
            matchedPairs.push({win: best, stacking: entry.stacking ?? 0});
            try {
                const wsIdx = entry.workspace ?? 0;
                if (wsIdx >= 0 && wsIdx < wsMgr.n_workspaces) {
                    best.change_workspace_by_index(wsIdx, false);
                }
                best.unmaximize(Meta.MaximizeFlags.BOTH);
                best.move_resize_frame(true,
                    entry.x | 0, entry.y | 0, entry.w | 0, entry.h | 0);
                if (entry.maximized) best.maximize(entry.maximized);
            } catch (_e) {}
        }
        matchedPairs.sort((a, b) => a.stacking - b.stacking);
        for (const {win} of matchedPairs) this._raiseWindow(win);
        return matchedPairs.length;
    }

    GetFocusedWindowClass() {
        try {
            const win = global.display.focus_window;
            if (!win) return '';
            return win.get_wm_class() || '';
        } catch (_e) { return ''; }
    }

    _findByStyleClass(actor, className) {
        if (!actor) return null;
        if (actor.has_style_class_name?.(className)) return actor;
        const kids = actor.get_children?.() || [];
        for (const c of kids) {
            const found = this._findByStyleClass(c, className);
            if (found) return found;
        }
        return null;
    }

    // ---------- Hot-reload (UUID rename trick — unchanged) ----------

    _extensionsDir() {
        return `${GLib.get_home_dir()}/.local/share/gnome-shell/extensions`;
    }

    _removeExtensionByUuid(uuid) {
        try { Main.extensionManager.disableExtension?.(uuid); } catch (_e) {}
        const ext = Main.extensionManager.lookup?.(uuid);
        if (ext) { try { Main.extensionManager.unloadExtension?.(ext); } catch (_e) {} }
        const dir = `${this._extensionsDir()}/${uuid}`;
        GLib.spawn_command_line_sync(`rm -rf "${dir}"`);
    }

    _listTempUuids(includeSelf) {
        const out = [];
        const dir = Gio.File.new_for_path(this._extensionsDir());
        let enumerator;
        try {
            enumerator = dir.enumerate_children('standard::name',
                Gio.FileQueryInfoFlags.NONE, null);
        } catch (_e) { return out; }
        let info;
        while ((info = enumerator.next_file(null)) !== null) {
            const name = info.get_name();
            if (!name.startsWith(RELOAD_UUID_PREFIX)) continue;
            if (!includeSelf && name === this.uuid) continue;
            out.push(name);
        }
        enumerator.close(null);
        return out;
    }

    _patchMetadataUuid(dir, newUuid) {
        const path = `${dir}/metadata.json`;
        const [ok, contents] = GLib.file_get_contents(path);
        if (!ok) throw new Error(`cannot read ${path}`);
        const text = new TextDecoder().decode(contents);
        const patched = text.replace(/"uuid"\s*:\s*"[^"]+"/,
            `"uuid": "${newUuid}"`);
        GLib.file_set_contents(path, patched);
    }

    HotReload() {
        try {
            for (const uuid of this._listTempUuids(false))
                this._removeExtensionByUuid(uuid);
            const ts = Math.floor(GLib.get_real_time() / 1000);
            const newUuid = `${RELOAD_UUID_PREFIX}${ts}@technolibre.ca`;
            const srcDir = `${this._extensionsDir()}/${MAIN_UUID}`;
            const newDir = `${this._extensionsDir()}/${newUuid}`;
            const [cpOk] = GLib.spawn_command_line_sync(
                `cp -r "${srcDir}" "${newDir}"`);
            if (!cpOk) throw new Error('cp failed');
            this._patchMetadataUuid(newDir, newUuid);
            const createObj = Main.extensionManager.createExtensionObject ||
                Main.extensionManager._createExtensionObject;
            const loadExt = Main.extensionManager.loadExtension ||
                Main.extensionManager._loadExtension;
            if (!createObj || !loadExt)
                throw new Error('extensionManager API not found');
            const dirFile = Gio.File.new_for_path(newDir);
            const newExt = createObj.call(Main.extensionManager,
                newUuid, dirFile, EXTENSION_TYPE_PER_USER);
            const selfUuid = this.uuid;
            const loadResult = loadExt.call(Main.extensionManager, newExt);
            Promise.resolve(loadResult).then(() => {
                Main.extensionManager.disableExtension?.(selfUuid);
                Main.extensionManager.enableExtension(newUuid);
            }).catch(() => {});
            return newUuid;
        } catch (_e) { return ''; }
    }

    HotExit() {
        GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
            try {
                for (const uuid of this._listTempUuids(true))
                    this._removeExtensionByUuid(uuid);
                Main.extensionManager.enableExtension?.(MAIN_UUID);
            } catch (_e) {}
            return GLib.SOURCE_REMOVE;
        });
        return true;
    }
}
```

- [ ] **Step 2: Verify syntax**

Run: `node --check script/stream_deck/gnome-extension/extension.js`
Expected: no output.

- [ ] **Step 3: Install + reload**

Run:

```bash
ln -sfn $(pwd)/script/stream_deck/gnome-extension \
    ~/.local/share/gnome-shell/extensions/streamdeck-tiler@technolibre.ca
glib-compile-schemas script/stream_deck/gnome-extension/schemas/
gnome-extensions disable streamdeck-tiler@technolibre.ca || true
gnome-extensions enable  streamdeck-tiler@technolibre.ca
```

(If GNOME is on Xorg you may instead `Alt+F2 → r`. On Wayland, log out / in.)

- [ ] **Step 4: Manual smoke**

Open the controller indicator from the panel. Verify:
- icon = controller (`input-gaming-symbolic`)
- About item opens repo URL
- Games sub-menu shows "Loading…" or list when `gallery_server.py` is running
- "Open prefs…" — opens preferences window (will be skeleton; full UI in subsequent plan tasks)
- D-Bus still works:
  ```bash
  gdbus call --session --dest org.gnome.Shell \
    --object-path /org/gnome/Shell/Extensions/StreamDeckTiler \
    --method org.gnome.Shell.Extensions.StreamDeckTiler.GetMonitorGeometry
  ```
  Expected: 4 ints printed.

- [ ] **Step 5: Commit**

```bash
git add script/stream_deck/gnome-extension/extension.js
git commit -m "[REF] stream_deck/gnome-extension: registry-driven extension entry"
```

---

## Task 9: Prefs skeleton with Buttons page

**Files:**
- Create: `script/stream_deck/gnome-extension/prefs.js`

- [ ] **Step 1: Write prefs.js**

Create `prefs.js`:

```javascript
import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import {ExtensionPreferences}
    from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

const INDICATORS = [
    {id: 'controller', label: 'Controller'},
    {id: 'pencil',     label: 'Pencil'},
    {id: 'film',       label: 'Film'},
    {id: 'erplibre',   label: 'ERPLibre'},
    {id: 'network',    label: 'Network'},
    {id: 'device',     label: 'Device'},
];

export default class StreamDeckTilerPrefs extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();

        const buttonsPage = new Adw.PreferencesPage({
            title: 'Buttons',
            icon_name: 'view-grid-symbolic',
        });

        const togglesGroup = new Adw.PreferencesGroup({
            title: 'Indicators',
            description: 'Toggle each panel button on or off.',
        });
        for (const ind of INDICATORS) {
            const row = new Adw.SwitchRow({
                title: ind.label,
                subtitle: `enable-${ind.id}`,
            });
            settings.bind(`enable-${ind.id}`, row, 'active',
                Gio.SettingsBindFlags.DEFAULT);
            togglesGroup.add(row);
        }
        buttonsPage.add(togglesGroup);

        window.add(buttonsPage);
    }
}
```

- [ ] **Step 2: Syntax check**

Run: `node --check script/stream_deck/gnome-extension/prefs.js`
Expected: no output.

- [ ] **Step 3: Reload extension + open prefs**

```bash
gnome-extensions disable streamdeck-tiler@technolibre.ca
gnome-extensions enable  streamdeck-tiler@technolibre.ca
gnome-extensions prefs   streamdeck-tiler@technolibre.ca
```

Expected: window with one page "Buttons" containing 6 switch rows.

- [ ] **Step 4: Toggle each row + verify live update**

For each row, flip the switch and confirm the corresponding button appears / disappears in the top bar within 1s. Re-enable controller before finishing.

- [ ] **Step 5: Commit**

```bash
git add script/stream_deck/gnome-extension/prefs.js
git commit -m "[ADD] stream_deck/gnome-extension: prefs skeleton with Buttons page"
```

---

## Task 10: Manual smoke checklist + Makefile target

**Files:**
- Create: `script/stream_deck/gnome-extension/test/manual.md`
- Modify: `conf/make.test.Makefile`

- [ ] **Step 1: Write manual.md checklist**

Create `script/stream_deck/gnome-extension/test/manual.md`:

```markdown
# Stream Deck GNOME Extension — Manual Smoke Checklist

Run after each `gnome-extensions enable` cycle.

## Foundation (Plan A)

- [ ] Controller indicator shows in top bar with `input-gaming-symbolic` icon
- [ ] Click → menu: About, Games (loads or "offline"), "Open prefs…"
- [ ] About item launches repo URL in browser
- [ ] Open prefs item opens the preferences window
- [ ] In prefs, "Buttons" page lists 6 indicators with toggles
- [ ] Toggling `enable-controller` off removes the icon; toggling on re-adds it
- [ ] D-Bus: `gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell/Extensions/StreamDeckTiler --method org.gnome.Shell.Extensions.StreamDeckTiler.GetMonitorGeometry` → 4 ints
- [ ] HotReload via D-Bus does not crash the shell
- [ ] If `~/.config/streamdeck-tiler/extension-settings.json` exists with `erplibre_path`, after first enable: `gsettings get org.gnome.shell.extensions.streamdeck-tiler paths` returns a JSON array containing that path; the legacy file is renamed to `.bak`

## Future (Plans B–H)

(Sections added by subsequent plans.)
```

- [ ] **Step 2: Add Makefile target**

Read existing `conf/make.test.Makefile` first, then append:

```makefile
test_gnome_extension:
	@echo "→ schema strict dry-run"
	glib-compile-schemas --strict --dry-run \
	    script/stream_deck/gnome-extension/schemas/
	@echo "→ node --test for pure logic"
	node --test script/stream_deck/gnome-extension/test/unit/*.test.js

.PHONY: test_gnome_extension
```

- [ ] **Step 3: Run the target**

Run: `make test_gnome_extension`
Expected: schema dry-run silent; node --test prints `# tests <N>` and `# pass <N>` (no failures).

- [ ] **Step 4: Verify the target appears in `make help` (if such target exists)**

Run: `make -n test_gnome_extension`
Expected: prints the commands without error.

- [ ] **Step 5: Commit**

```bash
git add script/stream_deck/gnome-extension/test/manual.md conf/make.test.Makefile
git commit -m "[ADD] stream_deck/gnome-extension: manual checklist + make test target"
```

---

## Self-review (run before handoff)

- Spec §3.1 registry → Task 5 ✓
- Spec §3.2 file layout (foundation subset) → Tasks 1, 7, 9 ✓
- Spec §4 GSettings keys (full schema for the whole spec, future plans use the rest) → Task 2 ✓
- Spec §4.2 migration → Task 4 ✓
- Spec §5.1 controller behaviour preserved → Task 7 ✓
- Spec §6.1 Buttons page → Task 9 ✓
- Spec §7.1 spawn helpers (the foundational subset, mpv/browser/terminal/notify) → Task 6 ✓
- Spec §7.3 hot-reload destroy() contract → Task 8 (#unmount calls destroy) ✓
- Spec §9 unit tests + glib-compile-schemas in CI → Task 10 ✓

No placeholders. All file paths, code, and commands present.
