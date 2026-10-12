# Plan E — Stream Deck Network Indicator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a network panel button listing SSH-reachable hosts. Two sections: configured (parsed from `~/.ssh/config`) and scanned (live `nmap -p22 --open` or `nc` fallback). Per host: SSH terminal, copy IP, sftp, details modal.

**Architecture:** New `lib/network.js` (CIDR expansion, nmap parser, scan dispatcher), `lib/ssh-config.js` (Host stanza parser), `indicators/network.js`. Register + prefs page.

**Tech Stack:** GJS, `nmap` / `nc`, `ip -4 -j route`, `getent hosts`.

**Spec reference:** §5.5, §6.5, §8.3.

**Depends on:** Plan A.

---

## File structure

| File | Action | Purpose |
|---|---|---|
| `lib/network.js` | create | CIDR expand, nmap parser, route detect, async scan |
| `lib/ssh-config.js` | create | parse `~/.ssh/config` Host stanzas |
| `indicators/network.js` | create | Network indicator UI |
| `extension.js` | modify | register descriptor |
| `prefs.js` | modify | Network page |
| `test/unit/network.test.js` | create | parser tests |
| `test/unit/ssh-config.test.js` | create | parser tests |
| `test/fixtures/nmap-oG.txt` | create | sample `nmap -oG` output |
| `test/fixtures/ssh-config.txt` | create | sample ssh config |
| `test/fixtures/ip-route.json` | create | sample `ip -4 -j route` output |
| `test/manual.md` | modify | Network section |

(All paths under `script/stream_deck/gnome-extension/`.)

---

## Task 1: Network parser + tests

**Files:**
- Create: `lib/network.js`
- Create: `test/unit/network.test.js`
- Create: `test/fixtures/nmap-oG.txt`
- Create: `test/fixtures/ip-route.json`

- [ ] **Step 1: Fixtures**

Create `test/fixtures/nmap-oG.txt`:

```
# Nmap 7.94 scan initiated Mon Apr 27 08:00:00 2026 as: nmap -p22 --open -oG - 192.168.1.0/24
Host: 192.168.1.10 ()	Status: Up
Host: 192.168.1.10 ()	Ports: 22/open/tcp//ssh///	Ignored State: closed (999)
Host: 192.168.1.42 ()	Status: Up
Host: 192.168.1.42 ()	Ports: 22/open/tcp//ssh///	Ignored State: closed (999)
# Nmap done at Mon Apr 27 08:00:05 2026 -- 256 IP addresses (2 hosts up)
```

Create `test/fixtures/ip-route.json`:

```json
[{"dst":"default","gateway":"192.168.1.1","dev":"wlan0","protocol":"dhcp","prefsrc":"192.168.1.42","metric":600,"flags":[]},
 {"dst":"192.168.1.0/24","dev":"wlan0","protocol":"kernel","scope":"link","prefsrc":"192.168.1.42","metric":600,"flags":[]}]
```

- [ ] **Step 2: Write failing tests**

Create `test/unit/network.test.js`:

```javascript
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {parseNmapOG, deriveCidrFromIpRoute, expandCidrV4Slash24}
    from '../../lib/network.js';

const nmapFx = readFileSync(
    new URL('../fixtures/nmap-oG.txt', import.meta.url), 'utf8');
const routeFx = readFileSync(
    new URL('../fixtures/ip-route.json', import.meta.url), 'utf8');

test('parseNmapOG extracts hosts with port 22 open', () => {
    const hosts = parseNmapOG(nmapFx);
    assert.deepEqual(hosts.map(h => h.ip).sort(),
        ['192.168.1.10', '192.168.1.42']);
});

test('parseNmapOG empty input', () => {
    assert.deepEqual(parseNmapOG(''), []);
});

test('deriveCidrFromIpRoute returns /24 of default-gateway iface', () => {
    assert.equal(deriveCidrFromIpRoute(routeFx), '192.168.1.0/24');
});

test('deriveCidrFromIpRoute returns null when no default route', () => {
    const noDefault = JSON.stringify(
        [{dst: '10.0.0.0/8', dev: 'eth0', prefsrc: '10.0.0.5'}]);
    assert.equal(deriveCidrFromIpRoute(noDefault), null);
});

test('expandCidrV4Slash24 returns 256 addresses', () => {
    const ips = expandCidrV4Slash24('192.168.1.0/24');
    assert.equal(ips.length, 256);
    assert.equal(ips[0], '192.168.1.0');
    assert.equal(ips[255], '192.168.1.255');
});

test('expandCidrV4Slash24 rejects non-/24', () => {
    assert.throws(() => expandCidrV4Slash24('10.0.0.0/16'), /only \/24/);
});
```

- [ ] **Step 3: Run tests + verify they fail**

Run: `node --test script/stream_deck/gnome-extension/test/unit/network.test.js`
Expected: fail.

- [ ] **Step 4: Implement network.js (pure parts)**

Create `lib/network.js`:

```javascript
/**
 * Network scan helpers. Pure parsers + GJS subprocess dispatcher.
 */

export function parseNmapOG(text) {
    if (typeof text !== 'string' || text === '') return [];
    const seen = new Map();
    for (const line of text.split('\n')) {
        if (!line.startsWith('Host:')) continue;
        const ipMatch = line.match(/^Host:\s+(\S+)/);
        if (!ipMatch) continue;
        const ip = ipMatch[1];
        if (line.includes('Ports:') && /22\/open\/tcp/.test(line)) {
            seen.set(ip, {ip, port22: true});
        } else if (line.includes('Status: Up') && !seen.has(ip)) {
            seen.set(ip, {ip, port22: false});
        }
    }
    return [...seen.values()].filter(h => h.port22);
}

export function deriveCidrFromIpRoute(jsonText) {
    let arr;
    try { arr = JSON.parse(jsonText); }
    catch (_e) { return null; }
    if (!Array.isArray(arr)) return null;
    const def = arr.find(r => r?.dst === 'default');
    if (!def) return null;
    const subnet = arr.find(
        r => r?.dev === def.dev && r?.dst && r.dst.includes('/'));
    return subnet?.dst || null;
}

export function expandCidrV4Slash24(cidr) {
    const m = /^(\d+)\.(\d+)\.(\d+)\.\d+\/24$/.exec(cidr);
    if (!m) throw new Error('expandCidrV4Slash24 only handles /24');
    const out = [];
    for (let i = 0; i < 256; i++) out.push(`${m[1]}.${m[2]}.${m[3]}.${i}`);
    return out;
}

/**
 * GJS-only — auto-detect a /24 CIDR via `ip -4 -j route`. Returns null
 * if auto-detection failed.
 */
export async function autoDetectCidrGjs() {
    const {default: GLib} = await import('gi://GLib');
    const [, stdout] = GLib.spawn_command_line_sync('ip -4 -j route');
    return deriveCidrFromIpRoute(
        new TextDecoder().decode(stdout || new Uint8Array()));
}

/**
 * GJS-only — run nmap -p22 --open -oG - on cidr. Resolves to {hosts, error}.
 */
export async function scanNmapGjs(cidr, cancellable) {
    const {default: Gio} = await import('gi://Gio');
    return new Promise(resolve => {
        try {
            const proc = Gio.Subprocess.new(
                ['nmap', '-p22', '--open', '-oG', '-', cidr],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
            proc.communicate_utf8_async(null, cancellable || null, (p, res) => {
                try {
                    const [, stdout] = p.communicate_utf8_finish(res);
                    resolve({hosts: parseNmapOG(stdout), error: null});
                } catch (e) {
                    resolve({hosts: [], error: e.message});
                }
            });
        } catch (e) {
            resolve({hosts: [], error: e.message});
        }
    });
}

/**
 * GJS-only fallback when nmap is missing. nc -z -w1 IP 22 over the /24.
 */
export async function scanNcGjs(cidr, cancellable) {
    const ips = expandCidrV4Slash24(cidr);
    const {default: Gio} = await import('gi://Gio');
    const hosts = [];
    for (const ip of ips) {
        if (cancellable?.is_cancelled?.()) break;
        const ok = await new Promise(resolve => {
            try {
                const proc = Gio.Subprocess.new(
                    ['nc', '-z', '-w1', ip, '22'],
                    Gio.SubprocessFlags.NONE);
                proc.wait_async(null, () => resolve(proc.get_successful()));
            } catch (_e) { resolve(false); }
        });
        if (ok) hosts.push({ip, port22: true});
    }
    return {hosts, error: null};
}

/**
 * GJS-only — best-effort reverse DNS via getent hosts.
 */
export async function reverseDnsGjs(ip) {
    const {default: GLib} = await import('gi://GLib');
    try {
        const [, stdout] = GLib.spawn_command_line_sync(`getent hosts ${ip}`);
        const text = new TextDecoder()
            .decode(stdout || new Uint8Array()).trim();
        const parts = text.split(/\s+/);
        return parts.length >= 2 ? parts[1] : '';
    } catch (_e) { return ''; }
}
```

- [ ] **Step 5: Run tests + verify pass**

Run: `node --test script/stream_deck/gnome-extension/test/unit/network.test.js`
Expected: 6 tests pass.

- [ ] **Step 6: Commit**

```bash
git add script/stream_deck/gnome-extension/lib/network.js \
        script/stream_deck/gnome-extension/test/unit/network.test.js \
        script/stream_deck/gnome-extension/test/fixtures/nmap-oG.txt \
        script/stream_deck/gnome-extension/test/fixtures/ip-route.json
git commit -m "[ADD] stream_deck/gnome-extension: network parsers + tests"
```

---

## Task 2: SSH config parser + tests

**Files:**
- Create: `lib/ssh-config.js`
- Create: `test/unit/ssh-config.test.js`
- Create: `test/fixtures/ssh-config.txt`

- [ ] **Step 1: Fixture**

Create `test/fixtures/ssh-config.txt`:

```
# top-level comment
Host gateway
    HostName 192.168.1.1
    User admin

Host dev-*
    User dev

Host dev-1
    HostName 10.0.0.10
    Port 2222
    IdentityFile ~/.ssh/id_dev1

Host *
    ServerAliveInterval 60
```

- [ ] **Step 2: Failing tests**

Create `test/unit/ssh-config.test.js`:

```javascript
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {parseSshConfig, isWildcardHost} from '../../lib/ssh-config.js';

const text = readFileSync(
    new URL('../fixtures/ssh-config.txt', import.meta.url), 'utf8');

test('parseSshConfig collects Host stanzas', () => {
    const hosts = parseSshConfig(text);
    assert.equal(hosts.length, 4);
    const gw = hosts.find(h => h.alias === 'gateway');
    assert.equal(gw.fields.HostName, '192.168.1.1');
    assert.equal(gw.fields.User, 'admin');
});

test('parseSshConfig keeps wildcards but flag isWildcardHost', () => {
    const hosts = parseSshConfig(text);
    assert.equal(isWildcardHost('dev-*'), true);
    assert.equal(isWildcardHost('*'), true);
    assert.equal(isWildcardHost('gateway'), false);
    const wildcards = hosts.filter(h => isWildcardHost(h.alias));
    assert.equal(wildcards.length, 2);
});

test('parseSshConfig empty', () => {
    assert.deepEqual(parseSshConfig(''), []);
});
```

- [ ] **Step 3: Run tests, verify fail**

Run: `node --test script/stream_deck/gnome-extension/test/unit/ssh-config.test.js`
Expected: fail.

- [ ] **Step 4: Implement ssh-config.js**

Create `lib/ssh-config.js`:

```javascript
export function parseSshConfig(text) {
    if (typeof text !== 'string' || text === '') return [];
    const out = [];
    let current = null;
    for (const rawLine of text.split('\n')) {
        const line = rawLine.replace(/#.*$/, '').trim();
        if (!line) continue;
        const m = /^([A-Za-z]+)\s+(.+)$/.exec(line);
        if (!m) continue;
        const key = m[1];
        const value = m[2].trim();
        if (key.toLowerCase() === 'host') {
            current = {alias: value, fields: {}};
            out.push(current);
        } else if (current) {
            current.fields[key] = value;
        }
    }
    return out;
}

export function isWildcardHost(alias) {
    return /[*?]/.test(String(alias || ''));
}
```

- [ ] **Step 5: Run tests + commit**

```bash
node --test script/stream_deck/gnome-extension/test/unit/ssh-config.test.js
git add script/stream_deck/gnome-extension/lib/ssh-config.js \
        script/stream_deck/gnome-extension/test/unit/ssh-config.test.js \
        script/stream_deck/gnome-extension/test/fixtures/ssh-config.txt
git commit -m "[ADD] stream_deck/gnome-extension: ssh-config parser + tests"
```

---

## Task 3: Network indicator

**Files:**
- Create: `indicators/network.js`

- [ ] **Step 1: Write indicator**

Create `indicators/network.js`:

```javascript
import GObject from 'gi://GObject';
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {scanNmapGjs, scanNcGjs, autoDetectCidrGjs, reverseDnsGjs}
    from '../lib/network.js';
import {parseSshConfig, isWildcardHost} from '../lib/ssh-config.js';
import {buildBrowserArgv, buildTerminalArgv, findTerminal,
    spawnDetached} from '../lib/spawn.js';

function _notify(title, body) {
    try { Main.notify(title, body); } catch (_e) {}
}

export const NetworkIndicator = GObject.registerClass(
class NetworkIndicator extends PanelMenu.Button {
    _init({extension, openPrefs}) {
        super._init(0.0, 'Stream Deck Network');
        this._extension = extension;
        this._openPrefs = openPrefs;
        this._settings = extension.getSettings();
        this._scanning = false;
        this._cancellable = null;
        this._scanResult = {cidr: null, hosts: [], lastScan: null};
        this.add_child(new St.Icon({
            icon_name: 'network-wired-symbolic',
            style_class: 'system-status-icon',
        }));
        this._sigUser = this._settings.connect(
            'changed::network-ssh-user', () => this._rebuildMenu());
        this._sigCfg = this._settings.connect(
            'changed::network-read-ssh-config', () => this._rebuildMenu());
        this._rebuildMenu();
    }

    destroy() {
        if (this._cancellable) this._cancellable.cancel();
        if (this._timerId) GLib.source_remove(this._timerId);
        this._timerId = 0;
        for (const s of [this._sigUser, this._sigCfg])
            if (s) this._settings.disconnect(s);
        super.destroy();
    }

    _rebuildMenu() {
        this.menu.removeAll();
        const lastTxt = this._scanResult.lastScan
            ? new Date(this._scanResult.lastScan).toLocaleTimeString()
            : 'never';
        const cidr = this._scanResult.cidr || '?';
        this.menu.addMenuItem(new PopupMenu.PopupMenuItem(
            `Subnet: ${cidr} · last scan ${lastTxt}`, {reactive: false}));
        const refresh = new PopupMenu.PopupMenuItem(
            this._scanning ? '🔄 Scanning…' : '🔄 Refresh scan');
        refresh.connect('activate', () => this._startScan());
        this.menu.addMenuItem(refresh);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        if (this._settings.get_boolean('network-read-ssh-config')) {
            this._addConfiguredHosts();
            this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        }
        this._addScannedHosts();
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const prefs = new PopupMenu.PopupMenuItem('⚙ Open prefs');
        prefs.connect('activate', () => this._openPrefs?.());
        this.menu.addMenuItem(prefs);
    }

    _addConfiguredHosts() {
        const path = `${GLib.get_home_dir()}/.ssh/config`;
        let hosts = [];
        if (GLib.file_test(path, GLib.FileTest.EXISTS)) {
            try {
                const [ok, contents] = GLib.file_get_contents(path);
                if (ok) hosts = parseSshConfig(
                    new TextDecoder().decode(contents));
            } catch (_e) {}
        }
        const real = hosts.filter(h => !isWildcardHost(h.alias));
        this.menu.addMenuItem(new PopupMenu.PopupMenuItem(
            `— Configured (${real.length}) —`, {reactive: false}));
        if (real.length === 0) {
            this.menu.addMenuItem(new PopupMenu.PopupMenuItem(
                '(no Host stanzas)', {reactive: false}));
            return;
        }
        for (const h of real) this.menu.addMenuItem(this._configuredRow(h));
    }

    _configuredRow(host) {
        const sub = new PopupMenu.PopupSubMenuMenuItem(host.alias);
        const ssh = new PopupMenu.PopupMenuItem('SSH terminal');
        ssh.connect('activate', () => this._sshAlias(host.alias));
        sub.menu.addMenuItem(ssh);
        if (host.fields?.HostName) {
            const cp = new PopupMenu.PopupMenuItem('Copy hostname');
            cp.connect('activate',
                () => this._copy(host.fields.HostName));
            sub.menu.addMenuItem(cp);
        }
        const sftp = new PopupMenu.PopupMenuItem('Open Files (sftp://)');
        sftp.connect('activate',
            () => spawnDetached(buildBrowserArgv(`sftp://${host.alias}`),
                {notify: _notify, title: 'Stream Deck'}));
        sub.menu.addMenuItem(sftp);
        const det = new PopupMenu.PopupMenuItem('Show details');
        det.connect('activate', () => {
            const lines = Object.entries(host.fields)
                .map(([k, v]) => `${k}: ${v}`).join('\n');
            _notify(host.alias, lines || '(no fields)');
        });
        sub.menu.addMenuItem(det);
        return sub;
    }

    _addScannedHosts() {
        this.menu.addMenuItem(new PopupMenu.PopupMenuItem(
            `— Scanned (${this._scanResult.hosts.length}) —`,
            {reactive: false}));
        for (const host of this._scanResult.hosts) {
            const sub = new PopupMenu.PopupSubMenuMenuItem(
                `${host.hostname || host.ip} (${host.ip})`);
            const ssh = new PopupMenu.PopupMenuItem('SSH terminal');
            ssh.connect('activate', () => this._sshIp(host.ip));
            sub.menu.addMenuItem(ssh);
            const cp = new PopupMenu.PopupMenuItem('Copy IP');
            cp.connect('activate', () => this._copy(host.ip));
            sub.menu.addMenuItem(cp);
            const sftp = new PopupMenu.PopupMenuItem('Open Files (sftp://)');
            sftp.connect('activate', () => spawnDetached(
                buildBrowserArgv(`sftp://${host.ip}`),
                {notify: _notify, title: 'Stream Deck'}));
            sub.menu.addMenuItem(sftp);
            const det = new PopupMenu.PopupMenuItem('Show details');
            det.connect('activate',
                () => _notify(host.ip,
                    `hostname: ${host.hostname || '?'}, port22: open`));
            sub.menu.addMenuItem(det);
            this.menu.addMenuItem(sub);
        }
    }

    async _sshAlias(alias) {
        const terminal = await findTerminal();
        if (!terminal) return;
        spawnDetached(
            buildTerminalArgv({cwd: GLib.get_home_dir(),
                command: `ssh ${alias}`, terminal}),
            {notify: _notify, title: 'Stream Deck'});
    }

    async _sshIp(ip) {
        const terminal = await findTerminal();
        if (!terminal) return;
        const userPref = this._settings.get_string('network-ssh-user').trim();
        const user = userPref || GLib.get_user_name();
        spawnDetached(
            buildTerminalArgv({cwd: GLib.get_home_dir(),
                command: `ssh ${user}@${ip}`, terminal}),
            {notify: _notify, title: 'Stream Deck'});
    }

    _copy(text) {
        try {
            St.Clipboard.get_default()
                .set_text(St.ClipboardType.CLIPBOARD, text);
        } catch (_e) {}
    }

    async _startScan() {
        if (this._scanning) return;
        this._scanning = true;
        this._cancellable = new Gio.Cancellable();
        this._rebuildMenu();
        try {
            const cidrs = this._settings.get_strv('network-cidrs');
            const cidr = cidrs.length > 0 ? cidrs[0]
                : (await autoDetectCidrGjs());
            if (!cidr) {
                _notify('Stream Deck', 'No network detected');
                return;
            }
            const useNmap = this._settings.get_boolean('network-use-nmap')
                && GLib.find_program_in_path('nmap');
            const scanner = useNmap ? scanNmapGjs : scanNcGjs;
            const {hosts, error} = await scanner(cidr, this._cancellable);
            if (error) _notify('Stream Deck', `Scan failed: ${error}`);
            for (const h of hosts) h.hostname = await reverseDnsGjs(h.ip);
            this._scanResult = {cidr, hosts, lastScan: Date.now()};
        } finally {
            this._scanning = false;
            this._cancellable = null;
            this._rebuildMenu();
        }
    }
});

export const indicatorDescriptor = {
    id: 'network',
    displayName: 'Network',
    defaultEnabled: true,
    ctor: (opts) => new NetworkIndicator(opts),
};
```

- [ ] **Step 2: Syntax check + commit**

```bash
node --check script/stream_deck/gnome-extension/indicators/network.js
git add script/stream_deck/gnome-extension/indicators/network.js
git commit -m "[ADD] stream_deck/gnome-extension: network indicator"
```

---

## Task 4: Register + prefs page

**Files:**
- Modify: `extension.js`
- Modify: `prefs.js`

- [ ] **Step 1: Register**

Append to `extension.js`:

```javascript
import {indicatorDescriptor as networkDescriptor}
    from './indicators/network.js';
```

In `enable()`:

```javascript
this.#registry.register(networkDescriptor);
```

- [ ] **Step 2: Prefs page**

Append to `prefs.js`:

```javascript
window.add(this._buildNetworkPage(settings));
```

```javascript
_buildNetworkPage(settings) {
    const page = new Adw.PreferencesPage({
        title: 'Network', icon_name: 'network-wired-symbolic',
    });
    const opts = new Adw.PreferencesGroup({title: 'Options'});
    const userRow = new Adw.EntryRow({title: 'SSH user (empty = $USER)'});
    settings.bind('network-ssh-user', userRow, 'text',
        Gio.SettingsBindFlags.DEFAULT);
    opts.add(userRow);
    const sshRow = new Adw.SwitchRow({title: 'Read ~/.ssh/config'});
    settings.bind('network-read-ssh-config', sshRow, 'active',
        Gio.SettingsBindFlags.DEFAULT);
    opts.add(sshRow);
    const nmapRow = new Adw.SwitchRow({title: 'Use nmap if available'});
    settings.bind('network-use-nmap', nmapRow, 'active',
        Gio.SettingsBindFlags.DEFAULT);
    opts.add(nmapRow);
    const refreshRow = new Adw.SpinRow({
        title: 'Auto-refresh (seconds, 0 = off)',
        adjustment: new Gtk.Adjustment({lower: 0, upper: 86400,
            step_increment: 60}),
    });
    settings.bind('network-auto-refresh-sec', refreshRow, 'value',
        Gio.SettingsBindFlags.DEFAULT);
    opts.add(refreshRow);
    page.add(opts);

    const cidrsGroup = new Adw.PreferencesGroup({
        title: 'CIDR ranges',
        description: 'Empty list = auto-detect. Edit via dconf-editor.',
    });
    page.add(cidrsGroup);
    return page;
}
```

Add `import Gtk from 'gi://Gtk';` at the top of `prefs.js` if not yet present.

- [ ] **Step 3: Reload + smoke**

```bash
glib-compile-schemas script/stream_deck/gnome-extension/schemas/
gnome-extensions disable streamdeck-tiler@technolibre.ca
gnome-extensions enable  streamdeck-tiler@technolibre.ca
```

Open Network indicator. Verify:
- Subnet line displays `?` initially.
- Click "🔄 Refresh scan" → spins, then displays subnet + scanned hosts.
- "Configured" section lists `~/.ssh/config` Host stanzas (excluding wildcards).
- Click any host → SSH terminal opens.

- [ ] **Step 4: Append manual checklist**

Append to `test/manual.md`:

```markdown
## Network (Plan E)

- [ ] Network indicator with `network-wired-symbolic` icon
- [ ] On open, header shows "Subnet: ? · last scan never"
- [ ] Click "🔄 Refresh scan" → scan runs without crashing the shell
- [ ] After scan: header shows detected /24 + timestamp; scanned hosts listed
- [ ] If `~/.ssh/config` has at least one non-wildcard Host stanza, "Configured" section lists it
- [ ] Configured row "SSH terminal" opens a terminal running ssh by alias
- [ ] Scanned row "SSH terminal" opens a terminal running ssh user@ip; user = `network-ssh-user` or `$USER`
- [ ] Copy IP populates clipboard (paste verifies)
- [ ] Open Files sftp:// item launches Nautilus sftp
- [ ] When nmap missing, scan still runs via nc (slower)
- [ ] Setting `network-auto-refresh-sec` to 60 — wait 60s, scan re-runs (Plan G adds the timer; for Plan E, the SpinRow exists but no timer fires yet)
```

- [ ] **Step 5: Commit**

```bash
git add script/stream_deck/gnome-extension/extension.js \
        script/stream_deck/gnome-extension/prefs.js \
        script/stream_deck/gnome-extension/test/manual.md
git commit -m "[ADD] stream_deck/gnome-extension: register network + prefs + checklist"
```

---

## Self-review

- Spec §5.5 configured + scanned sections, sub-menu actions → Task 3 ✓
- Spec §8.3 ssh-config + multi-host → Task 2 + Task 3 ✓
- Spec §6.5 Network prefs page → Task 4 ✓
- nmap fallback to nc → Task 3 `_startScan` ✓
- Cancellable scan + destroy() cleanup → Task 3 destroy() cancels ✓
- Auto-refresh timer not yet wired (Plan G handles cross-cutting timers) — manual checklist explicitly notes this ✓

No placeholders.
