# Plan C — Stream Deck Film Indicator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a film panel button listing user-curated films. Each entry click expands a sub-menu with `Browser`, `mpv` and `Edit` actions; the row label shows `Name · episode · position`.

**Architecture:** New `indicators/film.js` consuming Plan A spawn helpers (`buildBrowserArgv`, `buildMpvArgv`, `parsePosition`, `formatPosition`). New `ui/film-dialog.js` for add/edit. Registered in `extension.js`.

**Tech Stack:** GJS (GNOME Shell ESM), `PopupMenu.PopupSubMenuMenuItem` per row.

**Spec reference:** §5.3, §6.3.

**Depends on:** Plan A.

---

## File structure

| File | Action | Purpose |
|---|---|---|
| `script/stream_deck/gnome-extension/indicators/film.js` | create | Film indicator + helpers |
| `script/stream_deck/gnome-extension/ui/film-dialog.js` | create | Add/edit film modal |
| `script/stream_deck/gnome-extension/extension.js` | modify | register film indicator |
| `script/stream_deck/gnome-extension/prefs.js` | modify | add Film page |
| `script/stream_deck/gnome-extension/test/unit/film.test.js` | create | label formatter tests |
| `script/stream_deck/gnome-extension/test/manual.md` | modify | film section |

---

## Task 1: Film label formatter + tests

**Files:**
- Create: `script/stream_deck/gnome-extension/indicators/film.js`
- Create: `script/stream_deck/gnome-extension/test/unit/film.test.js`

- [ ] **Step 1: Write failing tests**

Create `test/unit/film.test.js`:

```javascript
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {buildFilmLabel, defaultFilmEntry, validatePositionInput}
    from '../../indicators/film.js';

test('buildFilmLabel joins fields with bullets', () => {
    assert.equal(
        buildFilmLabel({name: 'Foundation', episode: 'S2E5',
            position: '01:23:45'}),
        'Foundation · S2E5 · 01:23:45');
    assert.equal(
        buildFilmLabel({name: 'Solo', episode: '', position: ''}),
        'Solo');
    assert.equal(
        buildFilmLabel({name: 'Solo', episode: 'E1', position: ''}),
        'Solo · E1');
});

test('defaultFilmEntry stamps id + defaults', () => {
    const f = defaultFilmEntry({name: 'X', url: 'https://x'});
    assert.match(f.id, /^[0-9a-f]{8}-/);
    assert.equal(f.name, 'X');
    assert.equal(f.url, 'https://x');
    assert.equal(f.episode, '');
    assert.equal(f.position, '');
});

test('validatePositionInput accepts hh:mm:ss / mm:ss / seconds', () => {
    assert.equal(validatePositionInput(''), true);
    assert.equal(validatePositionInput('01:23:45'), true);
    assert.equal(validatePositionInput('5:30'), true);
    assert.equal(validatePositionInput('120'), true);
    assert.equal(validatePositionInput('1:2:3:4'), false);
    assert.equal(validatePositionInput('xx'), false);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test script/stream_deck/gnome-extension/test/unit/film.test.js`
Expected: fail.

- [ ] **Step 3: Implement helpers**

Create `indicators/film.js`:

```javascript
import {uuid4} from '../lib/settings.js';

export function buildFilmLabel(entry) {
    const parts = [entry?.name || ''];
    if (entry?.episode && entry.episode.trim() !== '') parts.push(entry.episode);
    if (entry?.position && entry.position.trim() !== '') parts.push(entry.position);
    return parts.filter(Boolean).join(' · ');
}

export function defaultFilmEntry({name = '', url = '', episode = '',
    position = ''} = {}) {
    return {id: uuid4(), name, url, episode, position};
}

export function validatePositionInput(text) {
    if (typeof text !== 'string' || text === '') return true;
    return /^\d+(:\d+){0,2}$/.test(text.trim());
}

// Indicator class added in Task 3.
```

- [ ] **Step 4: Run tests + verify pass**

Run: `node --test script/stream_deck/gnome-extension/test/unit/film.test.js`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add script/stream_deck/gnome-extension/indicators/film.js \
        script/stream_deck/gnome-extension/test/unit/film.test.js
git commit -m "[ADD] stream_deck/gnome-extension: film helpers + tests"
```

---

## Task 2: Film dialog

**Files:**
- Create: `script/stream_deck/gnome-extension/ui/film-dialog.js`

- [ ] **Step 1: Write the dialog**

Create `ui/film-dialog.js`:

```javascript
import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';
import {ModalDialog} from 'resource:///org/gnome/shell/ui/modalDialog.js';

import {validatePositionInput} from '../indicators/film.js';

export const FilmDialog = GObject.registerClass(
class FilmDialog extends ModalDialog {
    _init({title = 'Add film', entry = null, onConfirm, onDelete}) {
        super._init({styleClass: 'streamdeck-tiler-dialog'});
        this._onConfirm = onConfirm;
        this._onDelete = onDelete;

        const box = new St.BoxLayout({vertical: true,
            style: 'spacing: 8px;'});
        this.contentLayout.add_child(box);

        box.add_child(new St.Label({text: title,
            style: 'font-weight: bold;'}));

        this._nameEntry = new St.Entry({hint_text: 'Name (required)',
            text: entry?.name ?? ''});
        box.add_child(this._nameEntry);

        this._urlEntry = new St.Entry({hint_text: 'URL (required)',
            text: entry?.url ?? ''});
        box.add_child(this._urlEntry);

        this._epEntry = new St.Entry({hint_text: 'Episode (e.g. S2E5)',
            text: entry?.episode ?? ''});
        box.add_child(this._epEntry);

        this._posEntry = new St.Entry({
            hint_text: 'Position (hh:mm:ss or seconds)',
            text: entry?.position ?? '',
        });
        box.add_child(this._posEntry);
        this._posError = new St.Label({text: '',
            style: 'color: #d33; font-size: 0.85em;'});
        box.add_child(this._posError);

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

    _confirm() {
        const name = this._nameEntry.get_text().trim();
        const url = this._urlEntry.get_text().trim();
        const position = this._posEntry.get_text().trim();
        if (!name || !url) return;
        if (!validatePositionInput(position)) {
            this._posError.set_text('Invalid position format');
            return;
        }
        this._onConfirm({
            name, url,
            episode: this._epEntry.get_text(),
            position,
        });
        this.close();
    }
});
```

- [ ] **Step 2: Syntax check**

Run: `node --check script/stream_deck/gnome-extension/ui/film-dialog.js`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add script/stream_deck/gnome-extension/ui/film-dialog.js
git commit -m "[ADD] stream_deck/gnome-extension: film-dialog modal"
```

---

## Task 3: Film indicator UI

**Files:**
- Modify: `script/stream_deck/gnome-extension/indicators/film.js`

- [ ] **Step 1: Append imports + indicator class**

Append to `indicators/film.js`:

```javascript
import GObject from 'gi://GObject';
import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {parseList, serializeList} from '../lib/settings.js';
import {buildBrowserArgv, buildMpvArgv, spawnDetached}
    from '../lib/spawn.js';
import {FilmDialog} from '../ui/film-dialog.js';

function _notify(title, body) {
    try { Main.notify(title, body); } catch (_e) {}
}

export const FilmIndicator = GObject.registerClass(
class FilmIndicator extends PanelMenu.Button {
    _init({extension, openPrefs}) {
        super._init(0.0, 'Stream Deck Film');
        this._extension = extension;
        this._openPrefs = openPrefs;
        this._settings = extension.getSettings();
        this.add_child(new St.Icon({
            icon_name: 'video-x-generic-symbolic',
            style_class: 'system-status-icon',
        }));
        this._sig = this._settings.connect('changed::films',
            () => this._rebuildMenu());
        this._rebuildMenu();
    }

    destroy() {
        if (this._sig) this._settings.disconnect(this._sig);
        super.destroy();
    }

    _rebuildMenu() {
        this.menu.removeAll();
        const films = parseList(this._settings.get_string('films'));
        if (!films.length) {
            this.menu.addMenuItem(new PopupMenu.PopupMenuItem(
                '(no films — use + Add film)', {reactive: false}));
        } else {
            for (const film of films) this.menu.addMenuItem(this._makeRow(film));
        }
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const add = new PopupMenu.PopupMenuItem('+ Add film…');
        add.connect('activate', () => this._openAddDialog());
        this.menu.addMenuItem(add);

        const prefsItem = new PopupMenu.PopupMenuItem('⚙ Open prefs');
        prefsItem.connect('activate', () => this._openPrefs?.());
        this.menu.addMenuItem(prefsItem);
    }

    _makeRow(film) {
        const sub = new PopupMenu.PopupSubMenuMenuItem(buildFilmLabel(film));

        const browserItem = new PopupMenu.PopupMenuItem('▶ Browser');
        browserItem.connect('activate', () => this._launch(film, 'browser'));
        sub.menu.addMenuItem(browserItem);

        const mpvItem = new PopupMenu.PopupMenuItem('▶ mpv');
        mpvItem.connect('activate', () => this._launch(film, 'mpv'));
        sub.menu.addMenuItem(mpvItem);

        const editItem = new PopupMenu.PopupMenuItem('✎ Edit');
        editItem.connect('activate', () => this._editEntry(film));
        sub.menu.addMenuItem(editItem);

        return sub;
    }

    async _launch(film, player) {
        const argv = player === 'mpv'
            ? buildMpvArgv(film.url, film.position || '')
            : buildBrowserArgv(film.url);
        await spawnDetached(argv, {notify: _notify, title: 'Stream Deck'});
    }

    _openAddDialog() {
        const dlg = new FilmDialog({
            title: 'Add film',
            onConfirm: data => {
                const list = parseList(this._settings.get_string('films'));
                list.push(defaultFilmEntry(data));
                this._settings.set_string('films', serializeList(list));
            },
        });
        dlg.open();
    }

    _editEntry(entry) {
        const dlg = new FilmDialog({
            title: 'Edit film',
            entry,
            onConfirm: data => {
                const list = parseList(this._settings.get_string('films'));
                const i = list.findIndex(e => e.id === entry.id);
                if (i >= 0) {
                    list[i] = {...list[i], ...data};
                    this._settings.set_string('films', serializeList(list));
                }
            },
            onDelete: () => {
                const list = parseList(this._settings.get_string('films'))
                    .filter(e => e.id !== entry.id);
                this._settings.set_string('films', serializeList(list));
            },
        });
        dlg.open();
    }
});

export const indicatorDescriptor = {
    id: 'film',
    displayName: 'Film',
    defaultEnabled: true,
    ctor: (opts) => new FilmIndicator(opts),
};
```

- [ ] **Step 2: Syntax check**

Run: `node --check script/stream_deck/gnome-extension/indicators/film.js`
Expected: no output.

- [ ] **Step 3: Re-run unit tests**

Run: `node --test script/stream_deck/gnome-extension/test/unit/film.test.js`
Expected: 3 tests still pass.

- [ ] **Step 4: Commit**

```bash
git add script/stream_deck/gnome-extension/indicators/film.js
git commit -m "[ADD] stream_deck/gnome-extension: film indicator UI"
```

---

## Task 4: Register + prefs page

**Files:**
- Modify: `script/stream_deck/gnome-extension/extension.js`
- Modify: `script/stream_deck/gnome-extension/prefs.js`

- [ ] **Step 1: Register descriptor**

In `extension.js`, add:

```javascript
import {indicatorDescriptor as filmDescriptor}
    from './indicators/film.js';
```

In `enable()` after pencil registration:

```javascript
this.#registry.register(filmDescriptor);
```

- [ ] **Step 2: Add Film prefs page**

In `prefs.js`, after the Pencil page is added, append:

```javascript
window.add(this._buildFilmPage(settings));
```

Add method:

```javascript
_buildFilmPage(settings) {
    const page = new Adw.PreferencesPage({
        title: 'Film', icon_name: 'video-x-generic-symbolic',
    });
    const group = new Adw.PreferencesGroup({
        title: 'Films',
        description: 'Edit via the Add film dialog from the panel button.',
    });
    page.add(group);
    return page;
}
```

- [ ] **Step 3: Reload + smoke**

```bash
glib-compile-schemas script/stream_deck/gnome-extension/schemas/
gnome-extensions disable streamdeck-tiler@technolibre.ca
gnome-extensions enable  streamdeck-tiler@technolibre.ca
```

Verify film icon in panel; "+ Add film…" → fill name/URL/episode/position → save → entry shows. Click row → sub-menu with Browser/mpv/Edit. Browser opens xdg-open. mpv opens mpv with `--start=`.

- [ ] **Step 4: Commit**

```bash
git add script/stream_deck/gnome-extension/extension.js \
        script/stream_deck/gnome-extension/prefs.js
git commit -m "[ADD] stream_deck/gnome-extension: register film + prefs page"
```

- [ ] **Step 5: Update manual checklist**

Append to `test/manual.md`:

```markdown
## Film (Plan C)

- [ ] Film indicator in panel with `video-x-generic-symbolic` icon
- [ ] Empty state: "(no films — use + Add film)"
- [ ] Add film with name + URL only → entry shows just name
- [ ] Add film with name + URL + episode + position → label "Name · S2E5 · 01:23:45"
- [ ] Position invalid format (e.g. `xx`) → dialog shows "Invalid position format"
- [ ] Click row → sub-menu Browser / mpv / Edit
- [ ] Browser → xdg-open URL
- [ ] mpv → spawns mpv with `--start=<position>` (verify in `pgrep -af mpv`)
- [ ] Edit dialog has Delete button; deleting removes entry
```

```bash
git add script/stream_deck/gnome-extension/test/manual.md
git commit -m "[ADD] stream_deck/gnome-extension: film manual checklist"
```

---

## Self-review

- Spec §5.3 sub-menu Browser/mpv/Edit → Task 3 ✓
- Spec §5.3 position parser handles hh:mm:ss / seconds → reuses `parsePosition` (Plan A) ✓
- Spec §6.3 Film page → Task 4 step 2 ✓
- Spec §5.3 mention "DRM sites only Browser works" → noted in README (Plan H) — referenced but not coded here ✓

No placeholders.
