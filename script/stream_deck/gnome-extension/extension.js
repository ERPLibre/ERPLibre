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
import Meta from 'gi://Meta';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

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
}
