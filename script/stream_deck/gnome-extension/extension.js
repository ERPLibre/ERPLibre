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
import {runMigrationGjs} from './lib/settings.js';
import {indicatorDescriptor as controllerDescriptor}
    from './indicators/controller.js';
import {indicatorDescriptor as pencilDescriptor}
    from './indicators/pencil.js';
import {indicatorDescriptor as filmDescriptor}
    from './indicators/film.js';
import {indicatorDescriptor as erplibreDescriptor}
    from './indicators/erplibre.js';

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
        this.#registry.register(pencilDescriptor);
        this.#registry.register(filmDescriptor);
        this.#registry.register(erplibreDescriptor);
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
