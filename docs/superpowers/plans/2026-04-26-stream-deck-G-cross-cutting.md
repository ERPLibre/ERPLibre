# Plan G — Stream Deck Cross-Cutting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add i18n (gettext FR/EN), theming (icon overrides), drag-reorder of buttons, auto-refresh timers, D-Bus method extensions, backup/restore (Advanced prefs page), and git-based settings sync.

**Architecture:** Mostly small additive modules: `lib/i18n.js`, `lib/git-sync.js`, plus modifications to existing indicators (apply icon overrides + auto-refresh timers), `extension.js` (D-Bus surface), `prefs.js` (drag, theming, advanced, sync pages).

**Tech Stack:** GJS, gettext, `msgfmt`, GSettings.

**Spec reference:** §7.2 (i18n), §7.5 (sync), §7.6 (backup), §8.1 (drag), §8.2 (theming), §8.4 (auto-refresh), §8.10 (D-Bus).

**Depends on:** Plans A–F.

---

## File structure

| File | Action | Purpose |
|---|---|---|
| `lib/i18n.js` | create | gettext wrapper |
| `po/streamdeck-tiler.pot` | create | gettext template |
| `po/en.po` | create | English translations |
| `po/fr.po` | create | French translations |
| `locale/en/LC_MESSAGES/streamdeck-tiler.mo` | generated | compiled English |
| `locale/fr/LC_MESSAGES/streamdeck-tiler.mo` | generated | compiled French |
| `lib/git-sync.js` | create | git pull/commit/push helper |
| `indicators/*.js` | modify | apply icon overrides, auto-refresh timers |
| `extension.js` | modify | D-Bus method extensions, register sync hook |
| `prefs.js` | modify | drag rows, Theming page, Advanced page, Sync page |
| `conf/make.installation.Makefile` | modify | `extension_i18n_compile` target |
| `test/unit/git-sync.test.js` | create | sync logic tests |
| `test/unit/i18n.test.js` | create | wrapper smoke test |
| `test/manual.md` | modify | append cross-cutting section |

---

## Task 1: i18n wrapper

**Files:**
- Create: `lib/i18n.js`
- Create: `po/streamdeck-tiler.pot`
- Create: `po/en.po`
- Create: `po/fr.po`
- Create: `test/unit/i18n.test.js`

- [ ] **Step 1: Failing test**

Create `test/unit/i18n.test.js`:

```javascript
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {_, _identity} from '../../lib/i18n.js';

test('_identity returns its input verbatim', () => {
    assert.equal(_identity('Hello'), 'Hello');
    assert.equal(_identity(''), '');
});

test('_ in node falls back to identity (no .mo loaded)', () => {
    assert.equal(_('Hello'), 'Hello');
});
```

- [ ] **Step 2: Run, verify fail**

Run: `node --test script/stream_deck/gnome-extension/test/unit/i18n.test.js`
Expected: fail.

- [ ] **Step 3: Implement i18n.js**

Create `lib/i18n.js`:

```javascript
/**
 * gettext wrapper. In GJS the actual gettext lookup is done via the
 * extension's `gettext()` method (provided by ExtensionPreferences /
 * Extension); we expose a thin `_()` that dispatches to it when
 * configured. In Node tests, we degrade to an identity function.
 */

let _gettext = (s) => s;

export function setGettext(fn) {
    _gettext = typeof fn === 'function' ? fn : (s) => s;
}

export function _(s) { return _gettext(s); }

export function _identity(s) { return s; }
```

- [ ] **Step 4: Wire `setGettext` in extension.js + prefs.js**

In `extension.js` `enable()`, after `this.#settings = this.getSettings();`:

```javascript
import {setGettext} from './lib/i18n.js';
// …
setGettext((s) => this.gettext ? this.gettext(s) : s);
```

In `prefs.js` `fillPreferencesWindow(window)`:

```javascript
import {setGettext} from './lib/i18n.js';
// …
setGettext((s) => this.gettext ? this.gettext(s) : s);
```

- [ ] **Step 5: Create po stubs**

Create `po/streamdeck-tiler.pot`:

```
msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\n"
"Project-Id-Version: streamdeck-tiler 1.0\n"

msgid "Open prefs"
msgstr ""

msgid "Add path…"
msgstr ""

msgid "Add film…"
msgstr ""

msgid "Add remote instance…"
msgstr ""

msgid "Refresh scan"
msgstr ""

msgid "Re-scan USB"
msgstr ""

msgid "Re-scan local"
msgstr ""
```

Create `po/en.po`:

```
msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\n"
"Language: en\n"

msgid "Open prefs"
msgstr "Open prefs"

msgid "Add path…"
msgstr "Add path…"

msgid "Add film…"
msgstr "Add film…"

msgid "Add remote instance…"
msgstr "Add remote instance…"

msgid "Refresh scan"
msgstr "Refresh scan"

msgid "Re-scan USB"
msgstr "Re-scan USB"

msgid "Re-scan local"
msgstr "Re-scan local"
```

Create `po/fr.po`:

```
msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\n"
"Language: fr\n"

msgid "Open prefs"
msgstr "Ouvrir les préférences"

msgid "Add path…"
msgstr "Ajouter un chemin…"

msgid "Add film…"
msgstr "Ajouter un film…"

msgid "Add remote instance…"
msgstr "Ajouter une instance distante…"

msgid "Refresh scan"
msgstr "Relancer le scan"

msgid "Re-scan USB"
msgstr "Re-scan USB"

msgid "Re-scan local"
msgstr "Re-scan local"
```

- [ ] **Step 6: Wrap visible strings**

In each indicator, replace user-visible strings (`'Open prefs'`, `'+ Add path…'`, `'🔄 Refresh scan'`, etc.) by `_(...)`. Add `import {_} from '../lib/i18n.js';` at the top of each indicator file. Do NOT wrap log strings or icon names.

Concretely, in `indicators/pencil.js`:
- `'+ Add path…'` → `'+ ' + _('Add path…')`
- `'⚙ Open prefs'` → `'⚙ ' + _('Open prefs')`

Apply the same transformation in `controller.js`, `film.js`, `erplibre.js`, `network.js`, `device.js`.

- [ ] **Step 7: Add Makefile target**

In `conf/make.installation.Makefile`, append:

```makefile
extension_i18n_compile:
	@for lang in en fr; do \
		mkdir -p script/stream_deck/gnome-extension/locale/$$lang/LC_MESSAGES; \
		msgfmt -o script/stream_deck/gnome-extension/locale/$$lang/LC_MESSAGES/streamdeck-tiler.mo \
		       script/stream_deck/gnome-extension/po/$$lang.po; \
	done

.PHONY: extension_i18n_compile
```

- [ ] **Step 8: Compile + run tests + commit**

```bash
make extension_i18n_compile
node --test script/stream_deck/gnome-extension/test/unit/i18n.test.js
git add script/stream_deck/gnome-extension/lib/i18n.js \
        script/stream_deck/gnome-extension/po/ \
        script/stream_deck/gnome-extension/locale/ \
        script/stream_deck/gnome-extension/test/unit/i18n.test.js \
        conf/make.installation.Makefile \
        script/stream_deck/gnome-extension/indicators/ \
        script/stream_deck/gnome-extension/extension.js \
        script/stream_deck/gnome-extension/prefs.js
git commit -m "[ADD] stream_deck/gnome-extension: i18n + en/fr translations"
```

NOTE: gettext-domain in `metadata.json` was already set in Plan A. The `locale/` directory tree is what GNOME Shell loads.

---

## Task 2: Theming (icon overrides)

**Files:**
- Modify: `lib/registry.js` (apply icon override at mount)
- Modify: each `indicators/*.js` (constructor accepts `iconName` opt)
- Modify: `extension.js` (read overrides; pass to ctor)
- Modify: `prefs.js` (Theming page)

- [ ] **Step 1: Indicator ctor accepts iconName**

In every indicator's `_init({extension, openPrefs, iconName})`:
1. Add `iconName` to the destructured options.
2. When constructing `St.Icon`, default to the existing constant but use `iconName` when provided.

Example for `indicators/pencil.js`:

```javascript
_init({extension, openPrefs, iconName = 'document-edit-symbolic'}) {
    super._init(0.0, 'Stream Deck Pencil');
    this._extension = extension;
    this._openPrefs = openPrefs;
    this._settings = extension.getSettings();
    const icon = iconName.startsWith('/')
        ? new St.Icon({
            gicon: Gio.icon_new_for_string(iconName),
            style_class: 'system-status-icon'})
        : new St.Icon({
            icon_name: iconName,
            style_class: 'system-status-icon'});
    this.add_child(icon);
    // …
}
```

Apply analogous change to controller, film, erplibre, network, device.

- [ ] **Step 2: extension.js passes override**

In `_mount(id)`:

```javascript
const overrides = parseObject(this.#settings.get_string('icon-overrides'));
const ind = desc.ctor({
    openPrefs: () => this.openPreferences(),
    extension: this,
    iconName: overrides[id] || undefined,
});
```

Add `import {parseObject} from './lib/settings.js';` at the top.

Wire a settings signal:

```javascript
const ovSig = this.#settings.connect('changed::icon-overrides',
    () => this._reorderIndicators());
this.#signalIds.push(ovSig);
```

- [ ] **Step 3: Theming prefs page**

Append to `prefs.js`:

```javascript
window.add(this._buildThemingPage(settings));
```

```javascript
_buildThemingPage(settings) {
    const page = new Adw.PreferencesPage({
        title: 'Theming', icon_name: 'preferences-color-symbolic',
    });
    const group = new Adw.PreferencesGroup({title: 'Icon overrides'});
    page.add(group);

    const indicators = [
        ['controller', 'input-gaming-symbolic'],
        ['pencil',     'document-edit-symbolic'],
        ['film',       'video-x-generic-symbolic'],
        ['erplibre',   'network-server-symbolic'],
        ['network',    'network-wired-symbolic'],
        ['device',     'input-tablet-symbolic'],
    ];

    for (const [id, defaultIcon] of indicators) {
        const row = new Adw.EntryRow({
            title: id,
            text: this._currentOverride(settings, id) || defaultIcon,
        });
        row.connect('changed', () => this._setOverride(settings, id,
            row.get_text()));
        group.add(row);
    }
    return page;
}

_currentOverride(settings, id) {
    try {
        const obj = JSON.parse(settings.get_string('icon-overrides') || '{}');
        return obj[id] || '';
    } catch (_e) { return ''; }
}

_setOverride(settings, id, value) {
    let obj = {};
    try { obj = JSON.parse(settings.get_string('icon-overrides') || '{}');
    } catch (_e) {}
    if (value && value.trim() !== '') obj[id] = value.trim();
    else delete obj[id];
    settings.set_string('icon-overrides', JSON.stringify(obj));
}
```

- [ ] **Step 4: Reload + smoke**

```bash
glib-compile-schemas script/stream_deck/gnome-extension/schemas/
gnome-extensions disable streamdeck-tiler@technolibre.ca
gnome-extensions enable  streamdeck-tiler@technolibre.ca
gnome-extensions prefs   streamdeck-tiler@technolibre.ca
```

Set pencil's icon to `applications-utilities-symbolic`. Reopen panel — pencil button uses the new icon.

- [ ] **Step 5: Commit**

```bash
git add script/stream_deck/gnome-extension/indicators/ \
        script/stream_deck/gnome-extension/extension.js \
        script/stream_deck/gnome-extension/prefs.js
git commit -m "[ADD] stream_deck/gnome-extension: per-indicator icon overrides"
```

---

## Task 3: Drag-reorder buttons

**Files:**
- Modify: `prefs.js`

GTK ListBox supports drag via `Gtk.DragSource` + `Gtk.DropTarget`. We add a "Order in top bar" group with 6 draggable rows.

- [ ] **Step 1: Build the reorder group**

Inside `_buildButtonsPage(settings)` (Plan A), after the toggles group, add:

```javascript
const orderGroup = new Adw.PreferencesGroup({
    title: 'Order in top bar',
    description: 'Drag rows to change the left-to-right order.',
});
buttonsPage.add(orderGroup);

const list = new Gtk.ListBox({selection_mode: Gtk.SelectionMode.NONE});
orderGroup.add(list);
this._refreshOrderList(list, settings);

const apply = () => {
    const ids = [];
    let row = list.get_first_child();
    while (row) {
        const id = row.get_name?.();
        if (id) ids.push(id);
        row = row.get_next_sibling();
    }
    settings.set_strv('button-order', ids);
};

list.connect('row-activated', () => apply());
list.connect('move-cursor', () => apply());
```

(For brevity drag-source / drop-target wiring is in `_refreshOrderList`.)

- [ ] **Step 2: Implement `_refreshOrderList` with native drag**

Add the helper:

```javascript
_refreshOrderList(list, settings) {
    const known = new Set(['controller','pencil','film','erplibre',
        'network','device']);
    let order = settings.get_strv('button-order')
        .filter(id => known.has(id));
    for (const id of known)
        if (!order.includes(id)) order.push(id);

    while (list.get_first_child())
        list.remove(list.get_first_child());

    for (const id of order) {
        const row = new Gtk.ListBoxRow({name: id});
        const lbl = new Gtk.Label({label: id, xalign: 0, margin_start: 8,
            margin_end: 8, margin_top: 6, margin_bottom: 6});
        row.set_child(lbl);
        // Drag source
        const src = new Gtk.DragSource();
        src.connect('prepare', () => Gdk.ContentProvider.new_for_value(id));
        row.add_controller(src);
        // Drop target
        const tgt = new Gtk.DropTarget({
            actions: Gdk.DragAction.MOVE,
            formats: Gdk.ContentFormats.new_for_gtype(GObject.TYPE_STRING),
        });
        tgt.connect('drop', (_t, value) => {
            if (typeof value !== 'string') return false;
            const fromIdx = order.indexOf(value);
            const toIdx = order.indexOf(id);
            if (fromIdx === -1 || toIdx === -1 || fromIdx === toIdx) return false;
            order.splice(fromIdx, 1);
            order.splice(toIdx, 0, value);
            settings.set_strv('button-order', order);
            this._refreshOrderList(list, settings);
            return true;
        });
        row.add_controller(tgt);
        list.append(row);
    }
}
```

Add imports at top of `prefs.js`:

```javascript
import Gdk from 'gi://Gdk';
import GObject from 'gi://GObject';
```

- [ ] **Step 3: Reload + smoke**

```bash
gnome-extensions prefs streamdeck-tiler@technolibre.ca
```

Drag a row in "Order in top bar". Verify the panel reorders the visible icons. Verify `gsettings get org.gnome.shell.extensions.streamdeck-tiler button-order` reflects the new order.

- [ ] **Step 4: Commit**

```bash
git add script/stream_deck/gnome-extension/prefs.js
git commit -m "[ADD] stream_deck/gnome-extension: drag reorder buttons in prefs"
```

---

## Task 4: Auto-refresh timers (network + device)

**Files:**
- Modify: `indicators/network.js`
- Modify: `indicators/device.js`

- [ ] **Step 1: Network timer**

In `NetworkIndicator._init`, after `this._rebuildMenu();`, add:

```javascript
this._sigTimer = this._settings.connect(
    'changed::network-auto-refresh-sec', () => this._resetTimer());
this._resetTimer();
```

Add method:

```javascript
_resetTimer() {
    if (this._timerId) GLib.source_remove(this._timerId);
    this._timerId = 0;
    const sec = this._settings.get_int('network-auto-refresh-sec');
    if (sec > 0) {
        this._timerId = GLib.timeout_add_seconds(GLib.PRIORITY_LOW, sec, () => {
            this._startScan();
            return GLib.SOURCE_CONTINUE;
        });
    }
}
```

In `destroy()`, also disconnect `this._sigTimer`. The existing `if (this._timerId) GLib.source_remove…` already covers cleanup.

- [ ] **Step 2: Device timer (analogous)**

In `DeviceIndicator._init`, append:

```javascript
this._sigTimer = this._settings.connect(
    'changed::device-auto-refresh-sec', () => this._resetTimer());
this._resetTimer();
```

Add:

```javascript
_resetTimer() {
    if (this._timerId) GLib.source_remove(this._timerId);
    this._timerId = 0;
    const sec = this._settings.get_int('device-auto-refresh-sec');
    if (sec > 0) {
        this._timerId = GLib.timeout_add_seconds(GLib.PRIORITY_LOW, sec, () => {
            this._rescanThenRebuild();
            return GLib.SOURCE_CONTINUE;
        });
    }
}
```

`destroy()` already removes `_timerId`.

- [ ] **Step 3: Smoke + commit**

Set `network-auto-refresh-sec` to 60. Wait 60s. Verify scan re-runs (last-scan timestamp advances). Set back to 0; verify timer stops.

```bash
git add script/stream_deck/gnome-extension/indicators/network.js \
        script/stream_deck/gnome-extension/indicators/device.js
git commit -m "[ADD] stream_deck/gnome-extension: auto-refresh timers"
```

---

## Task 5: D-Bus method extensions

**Files:**
- Modify: `extension.js`

- [ ] **Step 1: Update IFACE_XML**

Inside the existing `IFACE_XML` constant, before the closing `</interface>`, append:

```xml
<method name="OpenPath">
  <arg type="s" direction="in" name="path"/>
  <arg type="b" direction="out" name="ok"/>
</method>
<method name="OpenFilm">
  <arg type="s" direction="in" name="film_id"/>
  <arg type="s" direction="in" name="player"/>
  <arg type="b" direction="out" name="ok"/>
</method>
<method name="OpenInstance">
  <arg type="s" direction="in" name="id"/>
  <arg type="s" direction="in" name="action"/>
  <arg type="b" direction="out" name="ok"/>
</method>
<method name="ScanNetwork">
  <arg type="s" direction="out" name="json"/>
</method>
<method name="ListDevices">
  <arg type="s" direction="out" name="json"/>
</method>
<method name="ListPaths">
  <arg type="s" direction="out" name="json"/>
</method>
<method name="ListFilms">
  <arg type="s" direction="out" name="json"/>
</method>
<method name="ListInstances">
  <arg type="s" direction="out" name="json"/>
</method>
```

- [ ] **Step 2: Add method bodies on the extension class**

Add to `extension.js`:

```javascript
ListPaths()    { return this.#settings.get_string('paths'); }
ListFilms()    { return this.#settings.get_string('films'); }
ListInstances(){ return this.#settings.get_string('instances'); }

OpenPath(path) {
    const ind = this.#indicators.get('pencil');
    if (!ind) return false;
    const all = JSON.parse(this.#settings.get_string('paths') || '[]');
    const entry = all.find(e => e.path === path) || {path, label: ''};
    ind._launch(entry, this.#settings.get_string('terminal-claude-cmd'));
    return true;
}

OpenFilm(filmId, player) {
    const ind = this.#indicators.get('film');
    if (!ind) return false;
    const all = JSON.parse(this.#settings.get_string('films') || '[]');
    const film = all.find(f => f.id === filmId);
    if (!film) return false;
    ind._launch(film, player === 'mpv' ? 'mpv' : 'browser');
    return true;
}

OpenInstance(id, action) {
    const ind = this.#indicators.get('erplibre');
    if (!ind) return false;
    const remotes = JSON.parse(this.#settings.get_string('instances') || '[]');
    const local = ind._localCache || [];
    const inst = remotes.find(e => e.id === id) || local.find(e => e.id === id);
    if (!inst) return false;
    switch (action) {
        case 'url':           ind._launchBrowser(inst); return true;
        case 'login':         ind._autoLogin(inst);     return true;
        case 'copy_user':     ind._copyAttr(inst, 'username'); return true;
        case 'copy_pass':     ind._copyAttr(inst, 'password'); return true;
        case 'open_keepass':  ind._openInKeepassXC(inst); return true;
        case 'start_server':  if (inst.type === 'local') {
            ind._startServer(inst); return true; } return false;
        default: return false;
    }
}

ScanNetwork() {
    const ind = this.#indicators.get('network');
    if (!ind) return '[]';
    ind._startScan();
    return JSON.stringify(ind._scanResult.hosts || []);
}

ListDevices() {
    const ind = this.#indicators.get('device');
    if (!ind) return '[]';
    return JSON.stringify(ind._cache || []);
}
```

- [ ] **Step 2 bis: Make `_launch`, `_launchBrowser`, `_autoLogin`, `_copyAttr`, `_openInKeepassXC`, `_startServer` accessible**

These are already public methods on the indicator instance (no `#` prefix). No further work needed — JavaScript class methods named with `_` are accessible.

- [ ] **Step 3: Reload + smoke via gdbus**

```bash
gnome-extensions disable streamdeck-tiler@technolibre.ca
gnome-extensions enable  streamdeck-tiler@technolibre.ca
gdbus call --session --dest org.gnome.Shell \
  --object-path /org/gnome/Shell/Extensions/StreamDeckTiler \
  --method org.gnome.Shell.Extensions.StreamDeckTiler.ListPaths
```

Expected: JSON string of paths. Likewise for `ListFilms`, `ListInstances`, `ListDevices`.

- [ ] **Step 4: Commit**

```bash
git add script/stream_deck/gnome-extension/extension.js
git commit -m "[ADD] stream_deck/gnome-extension: D-Bus method extensions"
```

---

## Task 6: Backup / restore (Advanced page)

**Files:**
- Modify: `lib/settings.js`
- Modify: `prefs.js`

- [ ] **Step 1: Add export/import helpers**

Append to `lib/settings.js`:

```javascript
export const SCHEMA_KEYS = [
    'enable-controller','enable-pencil','enable-film',
    'enable-erplibre','enable-network','enable-device',
    'button-order','paths','films','instances','recent-paths',
    'terminal-claude-cmd','erplibre-auto-detect','erplibre-local-pattern',
    'network-cidrs','network-ssh-user','network-use-nmap',
    'network-read-ssh-config','network-auto-refresh-sec',
    'device-auto-refresh-sec','icon-overrides','enable-git-sync',
    'git-sync-path','schema-version',
];

export function exportSettingsAsObj(settings) {
    const out = {};
    for (const k of SCHEMA_KEYS) {
        const v = settings.get_value(k);
        out[k] = v.deep_unpack ? v.deep_unpack() : v.unpack();
    }
    return {schema_version: settings.get_int('schema-version'),
        settings: out};
}

export function importSettingsFromObj(settings, obj) {
    if (!obj || typeof obj !== 'object' || !obj.settings) return false;
    for (const [k, raw] of Object.entries(obj.settings)) {
        if (!SCHEMA_KEYS.includes(k)) continue;
        try {
            const cur = settings.get_value(k);
            // Recreate a Variant of matching type via set_value's GVariant.
            const variantType = cur.get_type_string();
            const variant = imports.gi.GLib.Variant.new(variantType, raw);
            settings.set_value(k, variant);
        } catch (_e) { /* skip mismatched */ }
    }
    return true;
}

export function resetAllSettings(settings) {
    for (const k of SCHEMA_KEYS) settings.reset(k);
}
```

NOTE: `imports.gi.GLib` is the GJS legacy form; in ESM modules use the dynamic import:

```javascript
const {default: GLib} = await import('gi://GLib');
const variant = GLib.Variant.new(variantType, raw);
```

so `importSettingsFromObj` becomes `async`. Adjust callers.

- [ ] **Step 2: Advanced prefs page**

Append to `prefs.js`:

```javascript
window.add(this._buildAdvancedPage(settings));
```

```javascript
_buildAdvancedPage(settings) {
    const page = new Adw.PreferencesPage({
        title: 'Advanced', icon_name: 'document-properties-symbolic',
    });
    const grp = new Adw.PreferencesGroup({title: 'Backup & restore'});
    page.add(grp);

    const exp = new Adw.ActionRow({title: 'Export settings…'});
    const expBtn = new Gtk.Button({label: 'Export', valign: Gtk.Align.CENTER});
    expBtn.connect('clicked', () => this._exportSettings(settings, page));
    exp.add_suffix(expBtn);
    grp.add(exp);

    const imp = new Adw.ActionRow({title: 'Import settings…'});
    const impBtn = new Gtk.Button({label: 'Import', valign: Gtk.Align.CENTER});
    impBtn.connect('clicked', () => this._importSettings(settings, page));
    imp.add_suffix(impBtn);
    grp.add(imp);

    const rst = new Adw.ActionRow({title: 'Reset to defaults'});
    const rstBtn = new Gtk.Button({label: 'Reset',
        valign: Gtk.Align.CENTER, css_classes: ['destructive-action']});
    rstBtn.connect('clicked', () => this._resetAll(settings));
    rst.add_suffix(rstBtn);
    grp.add(rst);

    return page;
}

_exportSettings(settings, parent) {
    const dlg = new Gtk.FileChooserNative({
        title: 'Export settings', action: Gtk.FileChooserAction.SAVE,
        accept_label: 'Save', cancel_label: 'Cancel',
        modal: true, transient_for: parent.get_root?.(),
    });
    dlg.set_current_name('streamdeck-tiler-settings.json');
    dlg.connect('response', (_d, response) => {
        if (response === Gtk.ResponseType.ACCEPT) {
            const file = dlg.get_file();
            const obj = exportSettingsAsObj(settings);
            file.replace_contents(
                new TextEncoder().encode(JSON.stringify(obj, null, 2)),
                null, false, Gio.FileCreateFlags.REPLACE_DESTINATION, null);
        }
        dlg.destroy();
    });
    dlg.show();
}

_importSettings(settings, parent) {
    const dlg = new Gtk.FileChooserNative({
        title: 'Import settings', action: Gtk.FileChooserAction.OPEN,
        accept_label: 'Open', cancel_label: 'Cancel',
        modal: true, transient_for: parent.get_root?.(),
    });
    dlg.connect('response', async (_d, response) => {
        if (response === Gtk.ResponseType.ACCEPT) {
            const file = dlg.get_file();
            const [, contents] = file.load_contents(null);
            const text = new TextDecoder().decode(contents);
            try {
                const obj = JSON.parse(text);
                await importSettingsFromObj(settings, obj);
            } catch (_e) {}
        }
        dlg.destroy();
    });
    dlg.show();
}

_resetAll(settings) {
    resetAllSettings(settings);
}
```

Add imports to `prefs.js`:

```javascript
import {exportSettingsAsObj, importSettingsFromObj, resetAllSettings}
    from './lib/settings.js';
```

- [ ] **Step 3: Reload + smoke**

Open prefs → Advanced. Click Export → save JSON. Verify file contains all keys + schema_version. Modify a key (toggle pencil off). Click Import → choose the JSON → pencil re-enabled. Click Reset → all keys revert to defaults.

- [ ] **Step 4: Commit**

```bash
git add script/stream_deck/gnome-extension/lib/settings.js \
        script/stream_deck/gnome-extension/prefs.js
git commit -m "[ADD] stream_deck/gnome-extension: backup/restore + reset"
```

---

## Task 7: Git-based settings sync

**Files:**
- Create: `lib/git-sync.js`
- Create: `test/unit/git-sync.test.js`
- Modify: `extension.js`
- Modify: `prefs.js`

- [ ] **Step 1: Failing test (debounce logic)**

Create `test/unit/git-sync.test.js`:

```javascript
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {Debouncer} from '../../lib/git-sync.js';

test('Debouncer fires after delay', async () => {
    const calls = [];
    const d = new Debouncer({delayMs: 30,
        scheduler: setTimeout, canceller: clearTimeout});
    d.bump(() => calls.push('a'));
    d.bump(() => calls.push('b'));
    await new Promise(r => setTimeout(r, 60));
    assert.deepEqual(calls, ['b']);
});
```

- [ ] **Step 2: Implement git-sync.js skeleton**

Create `lib/git-sync.js`:

```javascript
export class Debouncer {
    constructor({delayMs, scheduler = setTimeout, canceller = clearTimeout}) {
        this._delay = delayMs;
        this._sched = scheduler;
        this._cancel = canceller;
        this._handle = null;
    }
    bump(fn) {
        if (this._handle !== null) this._cancel(this._handle);
        this._handle = this._sched(() => { this._handle = null; fn(); },
            this._delay);
    }
    flush() {
        if (this._handle !== null) this._cancel(this._handle);
        this._handle = null;
    }
}

/**
 * GJS-only — git pull --rebase / commit / push helpers.
 */
export async function gitPull(repoPath) {
    const {default: Gio} = await import('gi://Gio');
    return new Promise(resolve => {
        try {
            const proc = Gio.Subprocess.new(
                ['git', '-C', repoPath, 'pull', '--rebase',
                 '--strategy-option=theirs'],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
            proc.communicate_utf8_async(null, null, (p, res) => {
                try {
                    p.communicate_utf8_finish(res);
                    resolve(p.get_successful());
                } catch (_e) { resolve(false); }
            });
        } catch (_e) { resolve(false); }
    });
}

export async function gitCommitPush(repoPath, hostname) {
    const {default: Gio} = await import('gi://Gio');
    const ts = new Date().toISOString();
    const message = `auto sync ${hostname} ${ts}`;
    return new Promise(resolve => {
        try {
            const proc = Gio.Subprocess.new(
                ['bash', '-c',
                 `cd "${repoPath}" && git add -A && ` +
                 `git commit -m "${message}" --allow-empty && ` +
                 `if git remote get-url origin >/dev/null 2>&1; then ` +
                 `git push; fi`],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
            proc.communicate_utf8_async(null, null, (p, res) => {
                try {
                    p.communicate_utf8_finish(res);
                    resolve(p.get_successful());
                } catch (_e) { resolve(false); }
            });
        } catch (_e) { resolve(false); }
    });
}
```

- [ ] **Step 3: Run unit test**

Run: `node --test script/stream_deck/gnome-extension/test/unit/git-sync.test.js`
Expected: 1 test passes.

- [ ] **Step 4: Wire in extension.js**

In `extension.js` `enable()`, after `runMigrationGjs(...)`:

```javascript
import {Debouncer, gitPull, gitCommitPush} from './lib/git-sync.js';
import {exportSettingsAsObj} from './lib/settings.js';
// …

this._syncDebounce = new Debouncer({delayMs: 5000,
    scheduler: (fn, ms) =>
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms, () => {fn(); return GLib.SOURCE_REMOVE;}),
    canceller: id => GLib.source_remove(id)});

if (this.#settings.get_boolean('enable-git-sync')) {
    const repo = this.#settings.get_string('git-sync-path');
    if (repo) gitPull(repo).then(() => this._syncImport(repo));
}

const watch = ['paths','films','instances','icon-overrides',
    'enable-controller','enable-pencil','enable-film','enable-erplibre',
    'enable-network','enable-device','button-order'];
for (const k of watch) {
    const sig = this.#settings.connect(`changed::${k}`,
        () => this._syncDebounceWrite());
    this.#signalIds.push(sig);
}
```

Add private methods on the extension class:

```javascript
_syncDebounceWrite() {
    if (!this.#settings.get_boolean('enable-git-sync')) return;
    const repo = this.#settings.get_string('git-sync-path');
    if (!repo) return;
    this._syncDebounce.bump(async () => {
        const obj = exportSettingsAsObj(this.#settings);
        const file = Gio.File.new_for_path(`${repo}/streamdeck-tiler.json`);
        try {
            file.replace_contents(
                new TextEncoder().encode(JSON.stringify(obj, null, 2)),
                null, false, Gio.FileCreateFlags.REPLACE_DESTINATION, null);
            await gitCommitPush(repo, GLib.get_host_name());
        } catch (e) {
            console.log(`[StreamDeckTiler] sync failed: ${e.message}`);
        }
    });
}

async _syncImport(repo) {
    const file = Gio.File.new_for_path(`${repo}/streamdeck-tiler.json`);
    if (!file.query_exists(null)) return;
    try {
        const [, contents] = file.load_contents(null);
        const obj = JSON.parse(new TextDecoder().decode(contents));
        const {importSettingsFromObj} =
            await import('./lib/settings.js');
        await importSettingsFromObj(this.#settings, obj);
    } catch (e) {
        console.log(`[StreamDeckTiler] sync import failed: ${e.message}`);
    }
}
```

- [ ] **Step 5: Sync prefs page**

Append to `prefs.js`:

```javascript
window.add(this._buildSyncPage(settings));
```

```javascript
_buildSyncPage(settings) {
    const page = new Adw.PreferencesPage({
        title: 'Sync', icon_name: 'folder-remote-symbolic',
    });
    const grp = new Adw.PreferencesGroup({title: 'Git sync'});
    page.add(grp);

    const enRow = new Adw.SwitchRow({title: 'Enable git sync'});
    settings.bind('enable-git-sync', enRow, 'active',
        Gio.SettingsBindFlags.DEFAULT);
    grp.add(enRow);

    const pathRow = new Adw.EntryRow({
        title: 'Sync repo path (must contain a git repo)'});
    settings.bind('git-sync-path', pathRow, 'text',
        Gio.SettingsBindFlags.DEFAULT);
    grp.add(pathRow);

    const warn = new Adw.ActionRow({
        title: 'Last write wins on conflict.',
        subtitle: 'Manual merges may be required.',
    });
    grp.add(warn);

    return page;
}
```

- [ ] **Step 6: Smoke + commit**

Init a local repo (`mkdir -p ~/sdt-sync && git -C ~/sdt-sync init`). In prefs Sync, enable + set path. Toggle pencil off → wait 5s → `git -C ~/sdt-sync log` shows commit "auto sync …". File `streamdeck-tiler.json` contains current settings.

```bash
git add script/stream_deck/gnome-extension/lib/git-sync.js \
        script/stream_deck/gnome-extension/test/unit/git-sync.test.js \
        script/stream_deck/gnome-extension/extension.js \
        script/stream_deck/gnome-extension/prefs.js
git commit -m "[ADD] stream_deck/gnome-extension: git-based settings sync"
```

---

## Task 8: Manual checklist + final commit

**Files:**
- Modify: `test/manual.md`

- [ ] **Step 1: Append cross-cutting section**

Append to `test/manual.md`:

```markdown
## Cross-cutting (Plan G)

### i18n
- [ ] `LANG=fr_FR.UTF-8 gnome-extensions prefs streamdeck-tiler@technolibre.ca` shows French strings (e.g. "Ajouter un chemin…")
- [ ] `make extension_i18n_compile` succeeds; `.mo` files exist under `locale/`

### Theming
- [ ] Theming page: change pencil icon to `applications-utilities-symbolic` → top-bar icon updates after menu toggle
- [ ] Setting an absolute path to an SVG → top-bar shows that SVG

### Drag-reorder
- [ ] Drag rows in "Order in top bar" → top-bar order matches `gsettings get button-order`
- [ ] Disable an indicator + reorder → re-enable → still in correct position

### Auto-refresh
- [ ] `network-auto-refresh-sec=60` → scan re-runs every minute (timestamp advances)
- [ ] Set back to 0 → timer stops (no further scans)
- [ ] Same for `device-auto-refresh-sec`

### D-Bus
- [ ] `gdbus call … ListPaths` returns the paths JSON
- [ ] `gdbus call … OpenPath '/home/x/proj'` opens a terminal at that path
- [ ] `gdbus call … OpenFilm '<id>' 'mpv'` launches mpv
- [ ] `gdbus call … ListDevices` returns the devices JSON

### Backup/restore
- [ ] Export settings → JSON file with all keys + schema_version
- [ ] Modify keys, Import → settings restored
- [ ] Reset → all keys back to defaults

### Sync
- [ ] Set sync path to a local git repo, enable sync → toggling a setting commits the JSON within 5s
- [ ] Pre-populate the JSON in another machine → first enable() pulls + applies
```

- [ ] **Step 2: Commit**

```bash
git add script/stream_deck/gnome-extension/test/manual.md
git commit -m "[ADD] stream_deck/gnome-extension: cross-cutting manual checklist"
```

---

## Self-review

- Spec §7.2 i18n → Task 1 ✓
- Spec §8.2 theming → Task 2 ✓
- Spec §8.1 drag-reorder → Task 3 ✓
- Spec §8.4 auto-refresh → Task 4 ✓
- Spec §8.10 D-Bus extensions → Task 5 ✓
- Spec §7.6 backup/restore → Task 6 ✓
- Spec §7.5 git-sync (debounced commit + pull on enable) → Task 7 ✓

No placeholders.
