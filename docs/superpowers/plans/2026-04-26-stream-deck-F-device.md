# Plan F — Stream Deck Device Indicator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a device panel button listing Stream Deck USB devices (Elgato vendor `0fd9`) with `Status`, `Open controller UI`, `Restart deck`, `Show details` actions.

**Architecture:** New `lib/usb.js` (lsusb -v parser), `indicators/device.js`. Register + prefs page.

**Tech Stack:** GJS, `lsusb -d 0fd9: -v`, controller pidfile at `~/.cache/streamdeck-tiler/controller.pid`.

**Spec reference:** §5.6, §6.6.

**Depends on:** Plan A.

**Open question carried from spec §12:** `erplibre_controller.py` does not yet write a pidfile. This plan implements coordination by patching the controller (Task 3). If rejected, swap Task 2's `_restart` body to use `pkill -f erplibre_controller.py` as a less-safe fallback.

---

## File structure

| File | Action | Purpose |
|---|---|---|
| `lib/usb.js` | create | parse `lsusb -d 0fd9: -v` |
| `indicators/device.js` | create | Device indicator |
| `extension.js` | modify | register descriptor |
| `prefs.js` | modify | Device page |
| `script/stream_deck/erplibre_controller.py` | modify | write/remove pidfile |
| `test/unit/usb.test.js` | create | parser tests |
| `test/fixtures/lsusb-elgato.txt` | create | sample lsusb -v output |
| `test/manual.md` | modify | append section |

---

## Task 1: usb.js parser + tests

**Files:**
- Create: `lib/usb.js`
- Create: `test/unit/usb.test.js`
- Create: `test/fixtures/lsusb-elgato.txt`

- [ ] **Step 1: Fixture**

Create `test/fixtures/lsusb-elgato.txt`:

```
Bus 003 Device 010: ID 0fd9:0084 Elgato Systems GmbH Stream Deck XL
Device Descriptor:
  bLength                18
  bDescriptorType         1
  bcdUSB               1.10
  idVendor           0x0fd9 Elgato Systems GmbH
  idProduct          0x0084 Stream Deck XL
  iManufacturer           1 Elgato
  iProduct                2 Stream Deck XL
  iSerial                 3 AL01K1A12345
Bus 003 Device 011: ID 0fd9:0080 Elgato Systems GmbH Stream Deck Mini
Device Descriptor:
  bLength                18
  iManufacturer           1 Elgato
  iProduct                2 Stream Deck Mini
  iSerial                 3 AL02K9B98765
```

- [ ] **Step 2: Failing tests**

Create `test/unit/usb.test.js`:

```javascript
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {parseLsusbVerbose} from '../../lib/usb.js';

const fx = readFileSync(
    new URL('../fixtures/lsusb-elgato.txt', import.meta.url), 'utf8');

test('parseLsusbVerbose finds two Elgato devices', () => {
    const devs = parseLsusbVerbose(fx);
    assert.equal(devs.length, 2);
    assert.equal(devs[0].product, 'Stream Deck XL');
    assert.equal(devs[0].serial, 'AL01K1A12345');
    assert.equal(devs[0].bus, '003');
    assert.equal(devs[0].device, '010');
    assert.equal(devs[1].product, 'Stream Deck Mini');
});

test('parseLsusbVerbose handles empty input', () => {
    assert.deepEqual(parseLsusbVerbose(''), []);
});
```

- [ ] **Step 3: Run tests, verify fail**

Run: `node --test script/stream_deck/gnome-extension/test/unit/usb.test.js`
Expected: fail.

- [ ] **Step 4: Implement usb.js**

Create `lib/usb.js`:

```javascript
const HEADER_RE = /^Bus\s+(\d+)\s+Device\s+(\d+):\s+ID\s+([0-9a-f]{4}):([0-9a-f]{4})\s+(.*)$/;

export function parseLsusbVerbose(text) {
    if (typeof text !== 'string' || text === '') return [];
    const out = [];
    let cur = null;
    for (const line of text.split('\n')) {
        const h = line.match(HEADER_RE);
        if (h) {
            if (cur) out.push(cur);
            cur = {
                bus: h[1], device: h[2],
                vendor_id: h[3], product_id: h[4],
                vendor_name: h[5].trim(),
                product: '', serial: '', manufacturer: '',
            };
            continue;
        }
        if (!cur) continue;
        const t = line.trim();
        const grab = (label) => {
            const r = new RegExp(`^${label}\\s+\\d+\\s+(.+)$`);
            const m = t.match(r);
            return m ? m[1].trim() : null;
        };
        const prod = grab('iProduct');
        if (prod !== null) cur.product = prod;
        const ser = grab('iSerial');
        if (ser !== null) cur.serial = ser;
        const man = grab('iManufacturer');
        if (man !== null) cur.manufacturer = man;
    }
    if (cur) out.push(cur);
    return out;
}

/**
 * GJS-only — run lsusb -d 0fd9: -v and parse.
 */
export async function detectStreamDecksGjs() {
    const {default: GLib} = await import('gi://GLib');
    if (!GLib.find_program_in_path('lsusb')) return [];
    const [, stdout] = GLib.spawn_command_line_sync('lsusb -d 0fd9: -v');
    return parseLsusbVerbose(
        new TextDecoder().decode(stdout || new Uint8Array()));
}
```

- [ ] **Step 5: Run tests + commit**

```bash
node --test script/stream_deck/gnome-extension/test/unit/usb.test.js
git add script/stream_deck/gnome-extension/lib/usb.js \
        script/stream_deck/gnome-extension/test/unit/usb.test.js \
        script/stream_deck/gnome-extension/test/fixtures/lsusb-elgato.txt
git commit -m "[ADD] stream_deck/gnome-extension: usb parser + tests"
```

---

## Task 2: Device indicator

**Files:**
- Create: `indicators/device.js`

- [ ] **Step 1: Write indicator**

Create `indicators/device.js`:

```javascript
import GObject from 'gi://GObject';
import GLib from 'gi://GLib';
import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {detectStreamDecksGjs} from '../lib/usb.js';
import {spawnDetached} from '../lib/spawn.js';

function _notify(title, body) {
    try { Main.notify(title, body); } catch (_e) {}
}

const PIDFILE = `${GLib.get_user_cache_dir()}/streamdeck-tiler/controller.pid`;
const CONTROLLER_REL = 'script/stream_deck/erplibre_controller.py';

export const DeviceIndicator = GObject.registerClass(
class DeviceIndicator extends PanelMenu.Button {
    _init({extension, openPrefs}) {
        super._init(0.0, 'Stream Deck Device');
        this._extension = extension;
        this._openPrefs = openPrefs;
        this._settings = extension.getSettings();
        this._cache = [];
        this.add_child(new St.Icon({
            icon_name: 'input-tablet-symbolic',
            style_class: 'system-status-icon',
        }));
        this._rescanThenRebuild();
    }

    destroy() {
        if (this._timerId) GLib.source_remove(this._timerId);
        this._timerId = 0;
        super.destroy();
    }

    async _rescanThenRebuild() {
        this._cache = await detectStreamDecksGjs();
        this._rebuildMenu();
    }

    _rebuildMenu() {
        this.menu.removeAll();
        if (!this._cache.length) {
            this.menu.addMenuItem(new PopupMenu.PopupMenuItem(
                '(no Stream Deck found)', {reactive: false}));
        } else {
            for (const d of this._cache)
                this.menu.addMenuItem(this._row(d));
        }
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const rescan = new PopupMenu.PopupMenuItem('🔄 Re-scan USB');
        rescan.connect('activate', () => this._rescanThenRebuild());
        this.menu.addMenuItem(rescan);
        const prefs = new PopupMenu.PopupMenuItem('⚙ Open prefs');
        prefs.connect('activate', () => this._openPrefs?.());
        this.menu.addMenuItem(prefs);
    }

    _row(dev) {
        const sub = new PopupMenu.PopupSubMenuMenuItem(
            `${dev.product || 'Stream Deck'} (${dev.serial || '?'})`);

        const status = new PopupMenu.PopupMenuItem('Status');
        status.connect('activate', () => _notify(dev.product || 'Stream Deck',
            `Bus ${dev.bus} Device ${dev.device}\n` +
            `Vendor: ${dev.vendor_name}\n` +
            `Serial: ${dev.serial}`));
        sub.menu.addMenuItem(status);

        const open = new PopupMenu.PopupMenuItem('Open controller UI');
        open.connect('activate', () => this._launchController());
        sub.menu.addMenuItem(open);

        const restart = new PopupMenu.PopupMenuItem('Restart deck');
        restart.connect('activate', () => this._restart());
        sub.menu.addMenuItem(restart);

        const det = new PopupMenu.PopupMenuItem('Show details');
        det.connect('activate', async () => {
            const {default: GLib2} = await import('gi://GLib');
            const [, stdout] = GLib2.spawn_command_line_sync(
                `lsusb -s ${dev.bus}:${dev.device} -v`);
            _notify(dev.product || 'Stream Deck',
                new TextDecoder().decode(stdout || new Uint8Array())
                    .slice(0, 800));
        });
        sub.menu.addMenuItem(det);
        return sub;
    }

    _projectRoot() {
        return this._extension.path.replace(
            /\/script\/stream_deck\/gnome-extension\/?$/, '');
    }

    _launchController() {
        const root = this._projectRoot();
        const py = `${root}/.venv.erplibre/bin/python`;
        const script = `${root}/${CONTROLLER_REL}`;
        if (!GLib.file_test(py, GLib.FileTest.IS_EXECUTABLE)) {
            _notify('Stream Deck',
                'Python venv not found at .venv.erplibre');
            return;
        }
        spawnDetached([py, script], {notify: _notify, title: 'Stream Deck'});
    }

    _restart() {
        if (GLib.file_test(PIDFILE, GLib.FileTest.EXISTS)) {
            try {
                const [ok, contents] = GLib.file_get_contents(PIDFILE);
                if (ok) {
                    const pid = parseInt(
                        new TextDecoder().decode(contents).trim(), 10);
                    if (pid > 0) spawnDetached(['kill', String(pid)],
                        {notify: _notify, title: 'Stream Deck'});
                }
            } catch (_e) {}
        }
        // Give it half a second to die, then relaunch.
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 500, () => {
            this._launchController();
            return GLib.SOURCE_REMOVE;
        });
    }
});

export const indicatorDescriptor = {
    id: 'device',
    displayName: 'Device',
    defaultEnabled: true,
    ctor: (opts) => new DeviceIndicator(opts),
};
```

- [ ] **Step 2: Syntax check + commit**

```bash
node --check script/stream_deck/gnome-extension/indicators/device.js
git add script/stream_deck/gnome-extension/indicators/device.js
git commit -m "[ADD] stream_deck/gnome-extension: device indicator"
```

---

## Task 3: Controller pidfile patch

**Files:**
- Modify: `script/stream_deck/erplibre_controller.py`

Make `erplibre_controller.py` write its pid to `~/.cache/streamdeck-tiler/controller.pid` on startup and remove it on graceful exit.

- [ ] **Step 1: Read the controller**

Run: `head -80 script/stream_deck/erplibre_controller.py`
Identify the `if __name__ == '__main__':` block (or the main function called there).

- [ ] **Step 2: Add pidfile management at module top + main**

Insert near the top of the file (below imports):

```python
import atexit
import os
from pathlib import Path

PIDFILE = Path(os.environ.get(
    "XDG_CACHE_HOME", str(Path.home() / ".cache")
)) / "streamdeck-tiler" / "controller.pid"


def _write_pidfile():
    PIDFILE.parent.mkdir(parents=True, exist_ok=True)
    PIDFILE.write_text(str(os.getpid()))


def _remove_pidfile():
    try:
        PIDFILE.unlink()
    except FileNotFoundError:
        pass
```

In the entry block, before the run loop call:

```python
_write_pidfile()
atexit.register(_remove_pidfile)
```

- [ ] **Step 3: Test the controller boots and writes pidfile**

Run:

```bash
.venv.erplibre/bin/python script/stream_deck/erplibre_controller.py &
sleep 1
cat ~/.cache/streamdeck-tiler/controller.pid
kill %1
sleep 1
test ! -f ~/.cache/streamdeck-tiler/controller.pid && echo OK
```

Expected: `cat` prints a PID. After kill, the pidfile is gone, `OK` printed.

- [ ] **Step 4: Commit**

```bash
git add script/stream_deck/erplibre_controller.py
git commit -m "[IMP] stream_deck: controller writes pidfile for restart support"
```

---

## Task 4: Register + prefs page + manual checklist

**Files:**
- Modify: `extension.js`
- Modify: `prefs.js`
- Modify: `test/manual.md`

- [ ] **Step 1: Register**

Add to `extension.js`:

```javascript
import {indicatorDescriptor as deviceDescriptor}
    from './indicators/device.js';
```

In `enable()`:

```javascript
this.#registry.register(deviceDescriptor);
```

- [ ] **Step 2: Prefs page**

Append to `prefs.js`:

```javascript
window.add(this._buildDevicePage(settings));
```

```javascript
_buildDevicePage(settings) {
    const page = new Adw.PreferencesPage({
        title: 'Device', icon_name: 'input-tablet-symbolic',
    });
    const opts = new Adw.PreferencesGroup({title: 'Options'});
    const refreshRow = new Adw.SpinRow({
        title: 'Auto-refresh (seconds, 0 = off)',
        adjustment: new Gtk.Adjustment({lower: 0, upper: 86400,
            step_increment: 60}),
    });
    settings.bind('device-auto-refresh-sec', refreshRow, 'value',
        Gio.SettingsBindFlags.DEFAULT);
    opts.add(refreshRow);
    page.add(opts);
    return page;
}
```

- [ ] **Step 3: Reload + smoke**

```bash
glib-compile-schemas script/stream_deck/gnome-extension/schemas/
gnome-extensions disable streamdeck-tiler@technolibre.ca
gnome-extensions enable  streamdeck-tiler@technolibre.ca
```

Open Device indicator. With at least one Stream Deck connected: row appears with product + serial. Click "Status" → notification. Click "Open controller UI" → `erplibre_controller.py` launches. Click "Restart deck" → controller restarts (verify in `ps`).

- [ ] **Step 4: Append manual checklist**

Append to `test/manual.md`:

```markdown
## Device (Plan F)

- [ ] Device indicator with `input-tablet-symbolic` icon
- [ ] No deck plugged in: "(no Stream Deck found)"
- [ ] Plug deck + click "Re-scan USB" → row appears with product + serial
- [ ] Status item → notification with bus/device/vendor/serial
- [ ] Open controller UI → erplibre_controller.py runs (verify `pgrep -af erplibre_controller`)
- [ ] Pidfile `~/.cache/streamdeck-tiler/controller.pid` exists after launch
- [ ] Restart deck → controller exits + relaunches (PID changes)
- [ ] Show details → notification with truncated `lsusb -v` output
```

- [ ] **Step 5: Commit**

```bash
git add script/stream_deck/gnome-extension/extension.js \
        script/stream_deck/gnome-extension/prefs.js \
        script/stream_deck/gnome-extension/test/manual.md
git commit -m "[ADD] stream_deck/gnome-extension: register device + prefs + checklist"
```

---

## Self-review

- Spec §5.6 device sub-menu Status / Open controller UI / Restart / Show details → Task 2 ✓
- Spec §6.6 device prefs page (auto-refresh row) → Task 4 ✓
- Pidfile coordination per spec §12 → Task 3 ✓
- Auto-refresh timer wired in Plan G (cross-cutting) ✓

No placeholders.
