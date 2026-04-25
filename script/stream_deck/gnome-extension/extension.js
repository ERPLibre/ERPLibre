/**
 * Stream Deck Tiler — GNOME Shell Extension
 *
 * Exposes D-Bus interface for window tiling.
 * Call TileWindow(gridCols, gridRows, col1, row1, col2, row2)
 * to tile the focused window on a virtual grid.
 *
 * D-Bus: org.gnome.Shell.Extensions.StreamDeckTiler
 * Path:  /org/gnome/Shell/Extensions/StreamDeckTiler
 *
 * Example:
 *   gdbus call --session \
 *     --dest org.gnome.Shell \
 *     --object-path /org/gnome/Shell/Extensions/StreamDeckTiler \
 *     --method org.gnome.Shell.Extensions.StreamDeckTiler.TileWindow \
 *     4 4 0 0 1 3
 */

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Meta from 'gi://Meta';
import Soup from 'gi://Soup';
import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const TRACKER_UUID = 'tracker@aliakseiz.github.com';
const MAIN_UUID = 'streamdeck-tiler@technolibre.ca';
const RELOAD_UUID_PREFIX = 'streamdeck-tiler-reload-';
const EXTENSION_TYPE_PER_USER = 2;

const GALLERY_PORT = 8042;
const GALLERY_URL = `http://localhost:${GALLERY_PORT}`;
const PROJECT_URL = 'https://github.com/ERPLibre/ERPLibre';
const PROJECT_NAME = 'ERPLibre Stream Deck';
const GIT_REPO = 'https://github.com/ERPLibre/ERPLibre.git';

function _settingsPath() {
    return GLib.build_filenamev([
        GLib.get_user_config_dir(),
        'streamdeck-tiler',
        'extension-settings.json',
    ]);
}

function _readSettings() {
    try {
        const [ok, contents] = GLib.file_get_contents(_settingsPath());
        if (!ok) return {};
        return JSON.parse(new TextDecoder().decode(contents));
    } catch (e) {
        return {};
    }
}

function _writeSettings(data) {
    const path = _settingsPath();
    const dir = GLib.path_get_dirname(path);
    GLib.mkdir_with_parents(dir, 0o755);
    GLib.file_set_contents(path, JSON.stringify(data, null, 2));
}

function _erplibrePath() {
    const data = _readSettings();
    return data.erplibre_path
        || GLib.build_filenamev([GLib.get_home_dir(), 'erplibre']);
}

function _erplibreExists(path) {
    return GLib.file_test(path, GLib.FileTest.IS_DIR)
        && GLib.file_test(
            GLib.build_filenamev([path, '.git']),
            GLib.FileTest.IS_DIR);
}

function _notify(title, body) {
    try {
        Main.notify(title, body);
    } catch (e) {
        console.log(`[StreamDeckTiler] notify failed: ${e.message}`);
    }
}

const StreamDeckTilerIndicator = GObject.registerClass(
class StreamDeckTilerIndicator extends PanelMenu.Button {
    _init() {
        super._init(0.0, 'Stream Deck Tiler');
        this.add_child(new St.Icon({
            icon_name: 'input-gaming-symbolic',
            style_class: 'system-status-icon',
        }));
        this._buildMenu();
        this.menu.connect('open-state-changed', (menu, isOpen) => {
            if (isOpen) {
                this._refreshGames();
                this._refreshPathItems();
            }
        });
    }

    _buildMenu() {
        const about = new PopupMenu.PopupMenuItem('About Us');
        about.connect('activate', () => {
            try {
                Gio.AppInfo.launch_default_for_uri(PROJECT_URL, null);
            } catch (e) {
                _notify(PROJECT_NAME, `Open ${PROJECT_URL} for project info.`);
            }
        });
        this.menu.addMenuItem(about);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        this._gamesSection = new PopupMenu.PopupSubMenuMenuItem('Games');
        this.menu.addMenuItem(this._gamesSection);
        this._populateGamesPlaceholder('Loading…');

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        this._settingsSection = new PopupMenu.PopupSubMenuMenuItem('Settings');
        this.menu.addMenuItem(this._settingsSection);
    }

    _populateGamesPlaceholder(label) {
        this._gamesSection.menu.removeAll();
        const item = new PopupMenu.PopupMenuItem(label, {reactive: false});
        this._gamesSection.menu.addMenuItem(item);
    }

    _refreshGames() {
        this._populateGamesPlaceholder('Loading…');
        const session = new Soup.Session();
        session.timeout = 3;
        const message = Soup.Message.new('GET', `${GALLERY_URL}/api/games`);
        session.send_and_read_async(
            message, GLib.PRIORITY_DEFAULT, null,
            (sess, result) => {
                try {
                    const bytes = sess.send_and_read_finish(result);
                    const text = new TextDecoder().decode(bytes.get_data());
                    const games = JSON.parse(text);
                    this._populateGames(Array.isArray(games) ? games : []);
                } catch (e) {
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
        const message = Soup.Message.new(
            'GET', `${GALLERY_URL}/launch/${gameId}`);
        session.send_and_read_async(
            message, GLib.PRIORITY_DEFAULT, null,
            (sess, result) => {
                try {
                    sess.send_and_read_finish(result);
                } catch (e) {
                    _notify(PROJECT_NAME,
                        `Could not launch ${gameId}: gallery offline?`);
                }
            });
    }

    _refreshPathItems() {
        const m = this._settingsSection.menu;
        m.removeAll();
        const path = _erplibrePath();
        const exists = _erplibreExists(path);
        const status = exists ? 'OK' : 'missing';
        const display = new PopupMenu.PopupMenuItem(
            `ERPLibre: ${path} (${status})`, {reactive: false});
        m.addMenuItem(display);
        const change = new PopupMenu.PopupMenuItem('Change ERPLibre path…');
        change.connect('activate', () => this._promptForPath());
        m.addMenuItem(change);
        if (!exists) {
            const deploy = new PopupMenu.PopupMenuItem(
                `Deploy ERPLibre to ${path}`);
            deploy.connect('activate', () => this._deployErpLibre(path));
            m.addMenuItem(deploy);
        }
    }

    _promptForPath() {
        // Shell modal dialogs require ModalDialog import; keep simple by
        // editing the JSON file directly through the user's editor.
        const path = _settingsPath();
        const dir = GLib.path_get_dirname(path);
        GLib.mkdir_with_parents(dir, 0o755);
        if (!GLib.file_test(path, GLib.FileTest.EXISTS)) {
            _writeSettings({erplibre_path: _erplibrePath()});
        }
        try {
            Gio.AppInfo.launch_default_for_uri(`file://${path}`, null);
            _notify(PROJECT_NAME,
                `Edit ${path} then re-open the menu to refresh.`);
        } catch (e) {
            _notify(PROJECT_NAME, `Edit ${path} manually.`);
        }
    }

    _deployErpLibre(path) {
        _notify(PROJECT_NAME, `Cloning ${GIT_REPO} into ${path}…`);
        try {
            const proc = Gio.Subprocess.new(
                ['git', 'clone', GIT_REPO, path],
                Gio.SubprocessFlags.STDOUT_PIPE
                | Gio.SubprocessFlags.STDERR_PIPE);
            proc.communicate_utf8_async(null, null, (p, result) => {
                try {
                    const [, , stderr] = p.communicate_utf8_finish(result);
                    if (p.get_successful()) {
                        _notify(PROJECT_NAME,
                            `ERPLibre deployed at ${path}.`);
                    } else {
                        _notify(PROJECT_NAME,
                            `git clone failed: ${stderr.split('\n')[0]}`);
                    }
                } catch (e) {
                    _notify(PROJECT_NAME, `git clone error: ${e.message}`);
                }
                this._refreshPathItems();
            });
        } catch (e) {
            _notify(PROJECT_NAME, `Could not spawn git: ${e.message}`);
        }
    }
});

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
    <method name="ListTrackerTimers">
      <arg type="s" direction="out" name="json"/>
    </method>
    <method name="ToggleTrackerTimer">
      <arg type="s" direction="in" name="id"/>
      <arg type="b" direction="out" name="success"/>
    </method>
    <method name="AddTrackerTimer">
      <arg type="s" direction="out" name="id"/>
    </method>
    <method name="HotReload">
      <arg type="s" direction="out" name="newUuid"/>
    </method>
    <method name="HotExit">
      <arg type="b" direction="out" name="success"/>
    </method>
    <method name="ResetAllTrackerTimers">
      <arg type="b" direction="out" name="success"/>
    </method>
    <method name="ListWindows">
      <arg type="s" direction="out" name="json"/>
    </method>
    <method name="ApplyLayout">
      <arg type="s" direction="in" name="json"/>
      <arg type="i" direction="out" name="matched"/>
    </method>
  </interface>
</node>`;

export default class StreamDeckTilerExtension extends Extension {
    #dbus = null;
    #registrationId = 0;
    #indicator = null;

    enable() {
        this.#dbus = Gio.DBusExportedObject.wrapJSObject(IFACE_XML, this);
        this.#registrationId = this.#dbus.export(
            Gio.DBus.session,
            '/org/gnome/Shell/Extensions/StreamDeckTiler'
        );
        // The panel button uses this.uuid as the status-area key. Hot-reload
        // temp UUIDs differ from MAIN_UUID, so each reload yields a fresh
        // button after the previous instance's disable() destroys the old one.
        try {
            this.#indicator = new StreamDeckTilerIndicator();
            Main.panel.addToStatusArea(this.uuid, this.#indicator);
        } catch (e) {
            console.log(`[StreamDeckTiler] panel indicator failed: ${e.message}`);
        }
        console.log('[StreamDeckTiler] D-Bus interface registered');
    }

    disable() {
        if (this.#dbus) {
            this.#dbus.unexport();
            this.#dbus = null;
        }
        if (this.#indicator) {
            this.#indicator.destroy();
            this.#indicator = null;
        }
        console.log('[StreamDeckTiler] D-Bus interface unregistered');
    }

    /**
     * Tile the focused window on a grid.
     * Grid is gridCols x gridRows. Window spans from (col1,row1) to (col2,row2) inclusive.
     */
    TileWindow(gridCols, gridRows, col1, row1, col2, row2) {
        const win = global.display.focus_window;
        if (!win) {
            console.log('[StreamDeckTiler] No focused window');
            return false;
        }

        // Get the work area for the monitor the window is on
        const monIdx = win.get_monitor();
        const workArea = win.get_work_area_for_monitor(monIdx);

        // Calculate cell size
        const cellW = workArea.width / gridCols;
        const cellH = workArea.height / gridRows;

        // Calculate target rectangle
        const x = workArea.x + Math.round(col1 * cellW);
        const y = workArea.y + Math.round(row1 * cellH);
        const w = Math.round((col2 - col1 + 1) * cellW);
        const h = Math.round((row2 - row1 + 1) * cellH);

        // Unmaximize first
        win.unmaximize(Meta.MaximizeFlags.BOTH);
        win.move_resize_frame(true, x, y, w, h);

        console.log(`[StreamDeckTiler] Tiled to grid ${gridCols}x${gridRows} [${col1},${row1}]-[${col2},${row2}] => ${x},${y} ${w}x${h}`);
        return true;
    }

    /**
     * Get the work area of the primary monitor.
     */
    GetMonitorGeometry() {
        const mon = global.display.get_primary_monitor();
        const wa = Main.layoutManager.getWorkAreaForMonitor(mon);
        return [wa.x, wa.y, wa.width, wa.height];
    }

    /**
     * Get cell size for a given grid on the primary monitor.
     */
    GetGridSize(gridCols, gridRows) {
        const mon = global.display.get_primary_monitor();
        const wa = Main.layoutManager.getWorkAreaForMonitor(mon);
        return [Math.round(wa.width / gridCols), Math.round(wa.height / gridRows)];
    }

    /**
     * Reach into the tracker@aliakseiz.github.com extension's in-memory state.
     * Tracker has no public API — this touches private fields and may break
     * on tracker updates. Returns null if the extension is not enabled.
     */
    _getTrackerIndicator() {
        try {
            const ext = Main.extensionManager.lookup(TRACKER_UUID);
            if (!ext || !ext.stateObj) return null;
            return ext.stateObj._indicator ?? null;
        } catch (e) {
            console.log(`[StreamDeckTiler] tracker lookup failed: ${e.message}`);
            return null;
        }
    }

    /**
     * List timers managed by the tracker extension.
     * Returns a JSON string: [{id, name, running, elapsed}, ...]
     */
    ListTrackerTimers() {
        const ind = this._getTrackerIndicator();
        if (!ind || !Array.isArray(ind._timers)) return '[]';
        const out = ind._timers.map(t => ({
            id: t.id,
            name: t.name ?? '',
            running: !!t.running,
            elapsed: Math.round(t.timeElapsed || 0),
        }));
        return JSON.stringify(out);
    }

    /**
     * Toggle a tracker timer's running state by id.
     * Replicates tracker's internal play/pause logic (extension.js
     * line ~661 toggleTimerState) and updates its UI icon if present.
     */
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

        const uiElements = ind._timerUIElements?.get?.(timer.id);
        if (uiElements?.playPauseIcon) {
            uiElements.playPauseIcon.icon_name = timer.running
                ? 'media-playback-pause-symbolic'
                : 'media-playback-start-symbolic';
        }
        if (uiElements?.mainRow) {
            if (timer.running) {
                uiElements.mainRow.remove_style_class_name('timer-paused');
            } else {
                uiElements.mainRow.add_style_class_name('timer-paused');
            }
        }

        try {
            ind._saveTimers?.();
        } catch (e) {
            console.log(`[StreamDeckTiler] saveTimers failed: ${e.message}`);
        }
        return true;
    }

    /**
     * Create a new tracker timer, open tracker's panel menu, and enter
     * edit mode on the new timer so the keyboard can type its name.
     * Returns the new timer id, or '' on failure.
     */
    AddTrackerTimer() {
        const ind = this._getTrackerIndicator();
        if (!ind || typeof ind._addNewTimer !== 'function') return '';

        const beforeIds = new Set((ind._timers || []).map(t => t.id));
        try {
            ind._addNewTimer();
        } catch (e) {
            console.log(`[StreamDeckTiler] addNewTimer failed: ${e.message}`);
            return '';
        }
        const newTimer = (ind._timers || []).find(t => !beforeIds.has(t.id));
        if (!newTimer) return '';

        try {
            ind.menu?.open?.();
            ind._editTimer?.(newTimer);
            const ui = ind._timerUIElements?.get?.(newTimer.id);
            const entry = ui?.mainRow
                ? this._findByStyleClass(ui.mainRow, 'name-entry')
                : null;
            if (entry) {
                entry.set_text('');
                entry.grab_key_focus?.();
            }
        } catch (e) {
            console.log(`[StreamDeckTiler] editTimer focus failed: ${e.message}`);
        }
        return newTimer.id;
    }

    // ---------- Window layout capture / restore ----------

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
        } catch (e) {
            console.log(`[StreamDeckTiler] collectAllWindows: ${e.message}`);
        }
        return out;
    }

    _stackingIndexMap(windows) {
        const map = new Map();
        try {
            const sorted = global.display.sort_windows_by_stacking(windows);
            sorted.forEach((w, i) => map.set(w, i));
        } catch (e) {
            console.log(`[StreamDeckTiler] sort_windows_by_stacking: ${e.message}`);
        }
        return map;
    }

    _raiseWindow(win) {
        try {
            if (typeof win.raise === 'function') win.raise();
            else if (typeof win.raise_and_make_recent === 'function')
                win.raise_and_make_recent();
        } catch (e) {
            console.log(`[StreamDeckTiler] raise failed: ${e.message}`);
        }
    }

    /**
     * Dump geometry + identity of every normal window across workspaces.
     * Returns a JSON array of window records.
     */
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
        } catch (e) {
            console.log(`[StreamDeckTiler] ListWindows failed: ${e.message}`);
            return '[]';
        }
    }

    /**
     * Apply a list of window records to live windows. Matches by wm_class,
     * then prefers exact title, then substring. Greedy — each live window
     * is claimed once. Returns number of windows matched and repositioned.
     */
    ApplyLayout(jsonStr) {
        let entries;
        try {
            entries = JSON.parse(jsonStr);
        } catch (e) {
            console.log(`[StreamDeckTiler] ApplyLayout parse: ${e.message}`);
            return 0;
        }
        if (!Array.isArray(entries)) return 0;

        const liveList = this._collectAllWindows();
        const used = new Set();
        const matchedPairs = [];  // [{win, stacking}]
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
                if (score > bestScore) {
                    bestScore = score;
                    best = w;
                }
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
                best.move_resize_frame(
                    true,
                    entry.x | 0, entry.y | 0,
                    entry.w | 0, entry.h | 0
                );
                if (entry.maximized) {
                    best.maximize(entry.maximized);
                }
            } catch (e) {
                console.log(`[StreamDeckTiler] apply window: ${e.message}`);
            }
        }

        // Restore Z-order: raise bottom-to-top so the highest saved index
        // ends up on top, matching the captured stacking.
        matchedPairs.sort((a, b) => a.stacking - b.stacking);
        for (const {win} of matchedPairs) {
            this._raiseWindow(win);
        }

        return matchedPairs.length;
    }

    /**
     * Reset all tracker timers' elapsed time to 0. Running timers stay
     * running with fresh lastUpdateTime. Delegates to tracker's own
     * _resetAllTimers() which handles UI labels and persistence.
     */
    ResetAllTrackerTimers() {
        const ind = this._getTrackerIndicator();
        if (!ind || typeof ind._resetAllTimers !== 'function') return false;
        try {
            ind._resetAllTimers();
            return true;
        } catch (e) {
            console.log(`[StreamDeckTiler] resetAll failed: ${e.message}`);
            return false;
        }
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

    // ---------- Hot-reload (UUID-rename trick) ----------
    //
    // GJS caches ESM modules for the life of the shell process, so editing
    // extension.js normally requires a full shell restart. Work around by
    // duplicating the extension directory under a fresh UUID — new path =
    // new module-cache key = fresh import. Inspired by
    // https://codeberg.org/som/ExtensionReloader.

    _extensionsDir() {
        return `${GLib.get_home_dir()}/.local/share/gnome-shell/extensions`;
    }

    _removeExtensionByUuid(uuid) {
        try {
            Main.extensionManager.disableExtension?.(uuid);
        } catch (e) {}
        const ext = Main.extensionManager.lookup?.(uuid);
        if (ext) {
            try {
                Main.extensionManager.unloadExtension?.(ext);
            } catch (e) {}
        }
        const dir = `${this._extensionsDir()}/${uuid}`;
        GLib.spawn_command_line_sync(`rm -rf "${dir}"`);
    }

    _listTempUuids(includeSelf) {
        const out = [];
        const dir = Gio.File.new_for_path(this._extensionsDir());
        let enumerator;
        try {
            enumerator = dir.enumerate_children(
                'standard::name',
                Gio.FileQueryInfoFlags.NONE,
                null
            );
        } catch (e) {
            return out;
        }
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
        const patched = text.replace(
            /"uuid"\s*:\s*"[^"]+"/,
            `"uuid": "${newUuid}"`
        );
        GLib.file_set_contents(path, patched);
    }

    HotReload() {
        // GJS DBusExportedObject does not accept Promise return values,
        // so keep this method sync: do the file work + createExtensionObject
        // synchronously, then chain the async loadExtension + enable swap on
        // the returned Promise. D-Bus reply carries the new UUID immediately.
        try {
            for (const uuid of this._listTempUuids(false)) {
                this._removeExtensionByUuid(uuid);
            }

            const ts = Math.floor(GLib.get_real_time() / 1000);
            const newUuid = `${RELOAD_UUID_PREFIX}${ts}@technolibre.ca`;
            const srcDir = `${this._extensionsDir()}/${MAIN_UUID}`;
            const newDir = `${this._extensionsDir()}/${newUuid}`;

            const [cpOk] = GLib.spawn_command_line_sync(
                `cp -r "${srcDir}" "${newDir}"`
            );
            if (!cpOk) throw new Error('cp failed');

            this._patchMetadataUuid(newDir, newUuid);

            const createObj =
                Main.extensionManager.createExtensionObject ||
                Main.extensionManager._createExtensionObject;
            const loadExt =
                Main.extensionManager.loadExtension ||
                Main.extensionManager._loadExtension;
            if (!createObj || !loadExt) {
                throw new Error('extensionManager API not found');
            }

            const dirFile = Gio.File.new_for_path(newDir);
            const newExt = createObj.call(
                Main.extensionManager, newUuid, dirFile, EXTENSION_TYPE_PER_USER
            );

            const selfUuid = this.uuid;
            const loadResult = loadExt.call(Main.extensionManager, newExt);
            Promise.resolve(loadResult).then(() => {
                Main.extensionManager.disableExtension?.(selfUuid);
                Main.extensionManager.enableExtension(newUuid);
                console.log(`[StreamDeckTiler] HotReload → ${newUuid}`);
            }).catch(e => {
                console.log(`[StreamDeckTiler] HotReload load failed: ${e.message}`);
            });

            return newUuid;
        } catch (e) {
            console.log(`[StreamDeckTiler] HotReload failed: ${e.message}`);
            return '';
        }
    }

    HotExit() {
        // Defer the teardown so the D-Bus reply is sent before we disable.
        GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
            try {
                for (const uuid of this._listTempUuids(true)) {
                    this._removeExtensionByUuid(uuid);
                }
                Main.extensionManager.enableExtension?.(MAIN_UUID);
                console.log('[StreamDeckTiler] HotExit completed');
            } catch (e) {
                console.log(`[StreamDeckTiler] HotExit failed: ${e.message}`);
            }
            return GLib.SOURCE_REMOVE;
        });
        return true;
    }
}
