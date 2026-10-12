# Plan B — Stream Deck Pencil Indicator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pencil panel button listing user-curated paths. Each entry exposes `[Resume] [Fresh] [Custom…] [✎]` inline buttons that launch `gnome-terminal` with the chosen claude command in the path's working directory.

**Architecture:** New module `indicators/pencil.js` consuming `lib/spawn.js` (Plan A) and `lib/settings.js` (Plan A). New dialog `ui/path-dialog.js` for add/edit. Registered in `extension.js` next to the controller descriptor.

**Tech Stack:** GJS (GNOME Shell ESM), `St.BoxLayout` for inline button row, `Gtk.FileChooserDialog` via `Adw.PreferencesPage` for path picker.

**Spec reference:** `docs/superpowers/specs/2026-04-26-stream-deck-multi-indicator-design.md` §5.2, §6.2.

**Depends on:** Plan A (foundation).

---

## File structure (this plan)

| File | Action | Purpose |
|---|---|---|
| `script/stream_deck/gnome-extension/indicators/pencil.js` | create | Pencil indicator |
| `script/stream_deck/gnome-extension/ui/path-dialog.js` | create | Add/edit path modal |
| `script/stream_deck/gnome-extension/extension.js` | modify | register pencil indicator |
| `script/stream_deck/gnome-extension/prefs.js` | modify | add "Pencil" preferences page |
| `script/stream_deck/gnome-extension/test/unit/pencil.test.js` | create | unit tests for pure-logic helpers |
| `script/stream_deck/gnome-extension/test/manual.md` | modify | append pencil section |

---

## Task 1: Pencil pure-logic helpers + tests

**Files:**
- Create: `script/stream_deck/gnome-extension/test/unit/pencil.test.js`

We extract the small bits of pure logic (label resolution, recent-paths bumping wrapper) into `pencil.js` and test them via Node.

- [ ] **Step 1: Write failing tests**

Create `test/unit/pencil.test.js`:

```javascript
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {resolveLabel, defaultPathEntry}
    from '../../indicators/pencil.js';

test('resolveLabel uses label when present', () => {
    assert.equal(
        resolveLabel({label: 'My Lab', path: '/home/x/lab'}),
        'My Lab');
});

test('resolveLabel falls back to basename', () => {
    assert.equal(resolveLabel({label: '', path: '/home/x/lab'}), 'lab');
    assert.equal(resolveLabel({path: '/home/x/lab/'}),         'lab');
    assert.equal(resolveLabel({path: '/'}),                    '/');
});

test('defaultPathEntry produces id + claude --resume default', () => {
    const e = defaultPathEntry({label: 'L', path: '/p'});
    assert.match(e.id, /^[0-9a-f]{8}-/);
    assert.equal(e.label, 'L');
    assert.equal(e.path, '/p');
    assert.equal(e.default_cmd, 'claude --resume');
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test script/stream_deck/gnome-extension/test/unit/pencil.test.js`
Expected: fail — module not found.

- [ ] **Step 3: Implement pencil.js skeleton (logic functions only first)**

Create `indicators/pencil.js`:

```javascript
import {uuid4} from '../lib/settings.js';

export function resolveLabel(entry) {
    if (entry?.label && entry.label.trim() !== '') return entry.label;
    const path = entry?.path || '';
    if (path === '/') return '/';
    const trimmed = path.replace(/\/+$/, '');
    const idx = trimmed.lastIndexOf('/');
    return idx >= 0 ? trimmed.slice(idx + 1) : trimmed;
}

export function defaultPathEntry({label = '', path = '', default_cmd} = {}) {
    return {
        id: uuid4(),
        label,
        path,
        default_cmd: default_cmd || 'claude --resume',
    };
}

// Indicator class + descriptor are added in Task 2.
```

- [ ] **Step 4: Run tests + verify pass**

Run: `node --test script/stream_deck/gnome-extension/test/unit/pencil.test.js`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add script/stream_deck/gnome-extension/indicators/pencil.js \
        script/stream_deck/gnome-extension/test/unit/pencil.test.js
git commit -m "[ADD] stream_deck/gnome-extension: pencil pure-logic helpers"
```

---

## Task 2: Path dialog (add / edit modal)

**Files:**
- Create: `script/stream_deck/gnome-extension/ui/path-dialog.js`

Modal `St`-based dialog with three rows: label, path (with file-chooser button), recent suggestions list. Confirms or cancels.

- [ ] **Step 1: Write the dialog module**

Create `ui/path-dialog.js`:

```javascript
import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import {ModalDialog} from 'resource:///org/gnome/shell/ui/modalDialog.js';

export const PathDialog = GObject.registerClass(
class PathDialog extends ModalDialog {
    _init({title = 'Add path', entry = null, recentPaths = [], onConfirm}) {
        super._init({styleClass: 'streamdeck-tiler-dialog'});
        this._onConfirm = onConfirm;

        const box = new St.BoxLayout({vertical: true, style: 'spacing: 8px;'});
        this.contentLayout.add_child(box);

        box.add_child(new St.Label({text: title,
            style: 'font-weight: bold;'}));

        this._labelEntry = new St.Entry({
            hint_text: 'Label (optional)',
            text: entry?.label ?? '',
        });
        box.add_child(this._labelEntry);

        const pathRow = new St.BoxLayout({style: 'spacing: 4px;'});
        this._pathEntry = new St.Entry({
            hint_text: '/path/to/project',
            text: entry?.path ?? '',
            x_expand: true,
        });
        pathRow.add_child(this._pathEntry);
        const pickBtn = new St.Button({label: '📁'});
        pickBtn.connect('clicked', () => this._launchChooser());
        pathRow.add_child(pickBtn);
        box.add_child(pathRow);

        if (recentPaths.length) {
            box.add_child(new St.Label({text: 'Recent:',
                style: 'opacity: 0.7;'}));
            for (const r of recentPaths.slice(0, 5)) {
                const btn = new St.Button({label: r,
                    style: 'text-align: left;'});
                btn.connect('clicked', () => {
                    this._pathEntry.set_text(r);
                });
                box.add_child(btn);
            }
        }

        this.setButtons([
            {label: 'Cancel', action: () => this.close(),
                key: Clutter.KEY_Escape},
            {label: 'Save', action: () => this._confirm(),
                default: true},
        ]);
    }

    _launchChooser() {
        // Use zenity as the cross-DE file chooser invokable from a shell context.
        const proc = Gio.Subprocess.new(
            ['zenity', '--file-selection', '--directory',
                '--title=Select project path'],
            Gio.SubprocessFlags.STDOUT_PIPE);
        proc.communicate_utf8_async(null, null, (p, res) => {
            try {
                const [, stdout] = p.communicate_utf8_finish(res);
                const path = (stdout || '').trim();
                if (path) this._pathEntry.set_text(path);
            } catch (_e) {}
        });
    }

    _confirm() {
        const label = this._labelEntry.get_text();
        const path = this._pathEntry.get_text().trim();
        if (!path) return;
        const expanded = path.startsWith('~')
            ? GLib.build_filenamev([GLib.get_home_dir(), path.slice(1)])
            : path;
        this._onConfirm({label, path: expanded});
        this.close();
    }
});
```

- [ ] **Step 2: Syntax check**

Run: `node --check script/stream_deck/gnome-extension/ui/path-dialog.js`
Expected: no output.

- [ ] **Step 3: Verify zenity is installed**

Run: `which zenity`
Expected: a path. If not, `apt install zenity` (documented in the manual checklist).

- [ ] **Step 4: Commit**

```bash
git add script/stream_deck/gnome-extension/ui/path-dialog.js
git commit -m "[ADD] stream_deck/gnome-extension: path-dialog modal"
```

---

## Task 3: Pencil indicator UI

**Files:**
- Modify: `script/stream_deck/gnome-extension/indicators/pencil.js`

Append the indicator class + descriptor to the existing pencil.js (Task 1 created the helpers).

- [ ] **Step 1: Append imports + indicator class**

Append to `indicators/pencil.js`:

```javascript
import GObject from 'gi://GObject';
import GLib from 'gi://GLib';
import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {parseList, serializeList, pushRecent} from '../lib/settings.js';
import {findTerminal, buildTerminalArgv, spawnDetached}
    from '../lib/spawn.js';
import {PathDialog} from '../ui/path-dialog.js';

function _notify(title, body) {
    try { Main.notify(title, body); } catch (_e) {}
}

export const PencilIndicator = GObject.registerClass(
class PencilIndicator extends PanelMenu.Button {
    _init({extension, openPrefs}) {
        super._init(0.0, 'Stream Deck Pencil');
        this._extension = extension;
        this._openPrefs = openPrefs;
        this._settings = extension.getSettings();
        this.add_child(new St.Icon({
            icon_name: 'document-edit-symbolic',
            style_class: 'system-status-icon',
        }));
        this._pathsSig = this._settings.connect('changed::paths',
            () => this._rebuildMenu());
        this._cmdSig = this._settings.connect('changed::terminal-claude-cmd',
            () => this._rebuildMenu());
        this._rebuildMenu();
    }

    destroy() {
        if (this._pathsSig) this._settings.disconnect(this._pathsSig);
        if (this._cmdSig)   this._settings.disconnect(this._cmdSig);
        super.destroy();
    }

    _rebuildMenu() {
        this.menu.removeAll();
        const paths = parseList(this._settings.get_string('paths'));
        if (!paths.length) {
            this.menu.addMenuItem(new PopupMenu.PopupMenuItem(
                '(no paths configured — use Add path…)', {reactive: false}));
        } else {
            for (const entry of paths) this.menu.addMenuItem(this._makeRow(entry));
        }
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        const addItem = new PopupMenu.PopupMenuItem('+ Add path…');
        addItem.connect('activate', () => this._openAddDialog());
        this.menu.addMenuItem(addItem);

        const prefsItem = new PopupMenu.PopupMenuItem('⚙ Open prefs');
        prefsItem.connect('activate', () => this._openPrefs?.());
        this.menu.addMenuItem(prefsItem);
    }

    _makeRow(entry) {
        const item = new PopupMenu.PopupBaseMenuItem({reactive: false});
        const box = new St.BoxLayout({vertical: false,
            style: 'spacing: 6px;', x_expand: true});

        const labelBox = new St.BoxLayout({vertical: true, x_expand: true});
        labelBox.add_child(new St.Label({text: resolveLabel(entry)}));
        labelBox.add_child(new St.Label({text: entry.path,
            style: 'opacity: 0.6; font-size: 0.85em;'}));
        box.add_child(labelBox);

        const defaultCmd = this._settings.get_string('terminal-claude-cmd');
        const resumeBtn = this._mkBtn('Resume',
            () => this._launch(entry, 'claude --resume'));
        const freshBtn  = this._mkBtn('Fresh',
            () => this._launch(entry, 'claude'));
        const customBtn = this._mkBtn('Custom…',
            () => this._launch(entry, defaultCmd));
        const editBtn   = this._mkBtn('✎',
            () => this._editEntry(entry));

        for (const b of [resumeBtn, freshBtn, customBtn, editBtn]) box.add_child(b);
        item.add_child(box);
        return item;
    }

    _mkBtn(label, onClick) {
        const btn = new St.Button({label,
            style_class: 'streamdeck-tiler-btn',
            style: 'padding: 2px 6px;'});
        btn.connect('clicked', () => onClick());
        return btn;
    }

    async _launch(entry, command) {
        const terminal = await findTerminal();
        if (!terminal) {
            _notify('Stream Deck',
                'No terminal found. Install gnome-terminal, kgx or xterm.');
            return;
        }
        const argv = buildTerminalArgv({cwd: entry.path, command, terminal});
        const ok = await spawnDetached(argv,
            {notify: _notify, title: 'Stream Deck'});
        if (ok) {
            const recent = parseList(this._settings.get_string('recent-paths'));
            this._settings.set_string('recent-paths',
                serializeList(pushRecent(recent, entry.path)));
        }
    }

    _openAddDialog() {
        const recent = parseList(this._settings.get_string('recent-paths'));
        const dlg = new PathDialog({
            title: 'Add path',
            recentPaths: recent,
            onConfirm: ({label, path}) => {
                const list = parseList(this._settings.get_string('paths'));
                list.push(defaultPathEntry({label, path}));
                this._settings.set_string('paths', serializeList(list));
            },
        });
        dlg.open();
    }

    _editEntry(entry) {
        const dlg = new PathDialog({
            title: 'Edit path',
            entry,
            onConfirm: ({label, path}) => {
                const list = parseList(this._settings.get_string('paths'));
                const i = list.findIndex(e => e.id === entry.id);
                if (i >= 0) {
                    list[i] = {...list[i], label, path};
                    this._settings.set_string('paths', serializeList(list));
                }
            },
        });
        dlg.open();
    }
});

export const indicatorDescriptor = {
    id: 'pencil',
    displayName: 'Pencil',
    defaultEnabled: true,
    ctor: (opts) => new PencilIndicator(opts),
};
```

- [ ] **Step 2: Syntax check**

Run: `node --check script/stream_deck/gnome-extension/indicators/pencil.js`
Expected: no output.

- [ ] **Step 3: Verify Node tests still pass**

Run: `node --test script/stream_deck/gnome-extension/test/unit/pencil.test.js`
Expected: 3 tests pass (Node ignores GJS imports lazily until needed).

- [ ] **Step 4: Commit**

```bash
git add script/stream_deck/gnome-extension/indicators/pencil.js
git commit -m "[ADD] stream_deck/gnome-extension: pencil indicator UI"
```

---

## Task 4: Register pencil in extension.js

**Files:**
- Modify: `script/stream_deck/gnome-extension/extension.js`

- [ ] **Step 1: Add import**

After the existing `import {indicatorDescriptor as controllerDescriptor}` line, add:

```javascript
import {indicatorDescriptor as pencilDescriptor}
    from './indicators/pencil.js';
```

- [ ] **Step 2: Register descriptor**

In `enable()`, after `this.#registry.register(controllerDescriptor);`, add:

```javascript
this.#registry.register(pencilDescriptor);
```

- [ ] **Step 3: Reload extension**

```bash
glib-compile-schemas script/stream_deck/gnome-extension/schemas/
gnome-extensions disable streamdeck-tiler@technolibre.ca
gnome-extensions enable  streamdeck-tiler@technolibre.ca
```

- [ ] **Step 4: Manual smoke**

In top bar: pencil icon visible. Click → "(no paths configured)". Click "+ Add path…" → dialog opens. Add a path → entry appears with `[Resume] [Fresh] [Custom…] [✎]` buttons. Click `Resume` → terminal opens at the path running `claude --resume`. After launch, `gsettings get org.gnome.shell.extensions.streamdeck-tiler recent-paths` contains the path.

- [ ] **Step 5: Commit**

```bash
git add script/stream_deck/gnome-extension/extension.js
git commit -m "[ADD] stream_deck/gnome-extension: register pencil indicator"
```

---

## Task 5: Prefs Pencil page

**Files:**
- Modify: `script/stream_deck/gnome-extension/prefs.js`

- [ ] **Step 1: Add page builder**

In `prefs.js`, inside `fillPreferencesWindow(window)` after `window.add(buttonsPage);`, append:

```javascript
window.add(this._buildPencilPage(settings));
```

Then add the method below the class (or as a private method):

```javascript
_buildPencilPage(settings) {
    const Adw = imports.gi.Adw;
    // (For ESM consistency, use the imported Adw at the top of prefs.js.)
    const page = new Adw.PreferencesPage({
        title: 'Pencil', icon_name: 'document-edit-symbolic',
    });
    const cmdGroup = new Adw.PreferencesGroup({title: 'Default command'});
    const cmdRow = new Adw.EntryRow({title: 'Default claude command'});
    settings.bind('terminal-claude-cmd', cmdRow, 'text',
        Gio.SettingsBindFlags.DEFAULT);
    cmdGroup.add(cmdRow);
    page.add(cmdGroup);

    const pathsGroup = new Adw.PreferencesGroup({
        title: 'Paths',
        description: 'Edit via the Add path dialog from the panel button.',
    });
    page.add(pathsGroup);
    return page;
}
```

NOTE: GJS ESM does not support the `imports.gi` form inside ESM modules. Replace the inline `const Adw = imports.gi.Adw;` line by importing Adw at top of file:

```javascript
import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
```

(`Gio` may already be imported; deduplicate if so.)

- [ ] **Step 2: Reload prefs**

```bash
gnome-extensions prefs streamdeck-tiler@technolibre.ca
```

Expected: a "Pencil" page appears with a single editable row "Default claude command" defaulting to `claude --resume`.

- [ ] **Step 3: Edit + verify binding**

Change the value to `claude --resume --verbose`. Run:

```bash
gsettings get org.gnome.shell.extensions.streamdeck-tiler terminal-claude-cmd
```

Expected: the new value.

- [ ] **Step 4: Commit**

```bash
git add script/stream_deck/gnome-extension/prefs.js
git commit -m "[ADD] stream_deck/gnome-extension: prefs Pencil page"
```

---

## Task 6: Update manual smoke checklist

**Files:**
- Modify: `script/stream_deck/gnome-extension/test/manual.md`

- [ ] **Step 1: Append section**

Append to `test/manual.md`:

```markdown
## Pencil (Plan B)

- [ ] Pencil indicator in panel with `document-edit-symbolic` icon
- [ ] Empty state shows "(no paths configured — use Add path…)"
- [ ] "+ Add path…" opens a dialog with label, path, file picker, recent suggestions
- [ ] Dialog confirm adds the entry; the menu rebuilds live
- [ ] Per-entry `Resume` opens gnome-terminal in path running `claude --resume`
- [ ] Per-entry `Fresh` runs `claude` (no flag)
- [ ] Per-entry `Custom…` runs the value of `terminal-claude-cmd` GSettings key
- [ ] `✎` opens the dialog pre-filled with the entry; saving updates the entry
- [ ] After a launch, `gsettings get … recent-paths` includes that path (capped at 10)
- [ ] Toggle `enable-pencil` off → button disappears; on → button reappears
```

- [ ] **Step 2: Run the checklist manually**

Tick each box. Note any failure.

- [ ] **Step 3: Commit**

```bash
git add script/stream_deck/gnome-extension/test/manual.md
git commit -m "[ADD] stream_deck/gnome-extension: pencil manual checklist"
```

---

## Self-review

- Spec §5.2 inline buttons + recent suggestions → Task 3 ✓
- Spec §6.2 prefs Pencil page → Task 5 ✓
- Path dialog with file picker → Task 2 ✓
- Migration + storage in `paths` → reuses Plan A ✓
- Recent-paths capped + dedup → reuses `pushRecent` from Plan A ✓
- Live signal-driven rebuild → Task 3 connect+rebuild on `changed::paths` ✓
- destroy() cleans signals → Task 3 destroy() ✓

No placeholders.
