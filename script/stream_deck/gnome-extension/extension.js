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
import Meta from 'gi://Meta';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

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
  </interface>
</node>`;

export default class StreamDeckTilerExtension extends Extension {
    #dbus = null;
    #registrationId = 0;

    enable() {
        this.#dbus = Gio.DBusExportedObject.wrapJSObject(IFACE_XML, this);
        this.#registrationId = this.#dbus.export(
            Gio.DBus.session,
            '/org/gnome/Shell/Extensions/StreamDeckTiler'
        );
        console.log('[StreamDeckTiler] D-Bus interface registered');
    }

    disable() {
        if (this.#dbus) {
            this.#dbus.unexport();
            this.#dbus = null;
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

    async HotReload() {
        try {
            // Purge leftover temps from previous reloads (except self)
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
            await loadExt.call(Main.extensionManager, newExt);

            Main.extensionManager.disableExtension?.(this.uuid);
            Main.extensionManager.enableExtension(newUuid);

            console.log(`[StreamDeckTiler] HotReload → ${newUuid}`);
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
