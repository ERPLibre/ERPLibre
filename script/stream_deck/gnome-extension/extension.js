/**
 * Stream Deck Tiler — GNOME Shell Extension
 *
 * Registry-based: each panel button is an indicator module under
 * indicators/. extension.js wires the D-Bus interface, instantiates
 * indicators based on GSettings, and reacts to live toggles.
 */

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

import {IndicatorRegistry} from './lib/registry.js';
import {runMigrationGjs} from './lib/settings.js';
import {parseObject} from './lib/settings.js';
import {exportSettingsAsObj} from './lib/settings.js';
import {Debouncer, gitPull, gitCommitPush} from './lib/git-sync.js';
import {setGettext} from './lib/i18n.js';
import {ClaudeStateWatcher} from './lib/claude-state.js';
import {listMpvEntriesSync, sendMpvCommand} from './lib/mpv-state.js';
import {runSchemaMigrations} from './lib/migrations.js';
import {indicatorDescriptor as controllerDescriptor}
    from './indicators/controller.js';
import {indicatorDescriptor as pencilDescriptor}
    from './indicators/pencil.js';
import {indicatorDescriptor as mediaDescriptor}
    from './indicators/media.js';
import {indicatorDescriptor as erplibreDescriptor}
    from './indicators/erplibre.js';
import {indicatorDescriptor as networkDescriptor}
    from './indicators/network.js';
import {indicatorDescriptor as deviceDescriptor}
    from './indicators/device.js';
import {indicatorDescriptor as summaryDescriptor}
    from './indicators/summary.js';

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
    <method name="OpenPath">
      <arg type="s" direction="in" name="path"/>
      <arg type="b" direction="out" name="ok"/>
    </method>
    <method name="OpenFilm">
      <arg type="s" direction="in" name="film_id"/>
      <arg type="s" direction="in" name="player"/>
      <arg type="b" direction="out" name="ok"/>
    </method>
    <method name="OpenMedia">
      <arg type="s" direction="in" name="media_id"/>
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
    <method name="ListMedia">
      <arg type="s" direction="out" name="json"/>
    </method>
    <method name="ListInstances">
      <arg type="s" direction="out" name="json"/>
    </method>
    <method name="FocusClaudeSession">
      <arg type="s" direction="in" name="session_id"/>
      <arg type="b" direction="out" name="ok"/>
    </method>
    <method name="GetFocusedWindowId">
      <arg type="s" direction="out" name="id"/>
    </method>
    <method name="SetClaudeSessionWindow">
      <arg type="s" direction="in" name="session_id"/>
      <arg type="b" direction="out" name="ok"/>
    </method>
    <method name="AcceptClaudeSession">
      <arg type="s" direction="in" name="session_id"/>
      <arg type="b" direction="out" name="ok"/>
    </method>
    <method name="KillClaudeSession">
      <arg type="s" direction="in" name="session_id"/>
      <arg type="b" direction="out" name="ok"/>
    </method>
    <method name="DebugClaudeIndex">
      <arg type="s" direction="out" name="json"/>
    </method>
    <method name="RenameClaudeSession">
      <arg type="s" direction="in" name="session_id"/>
      <arg type="s" direction="in" name="description"/>
      <arg type="b" direction="out" name="ok"/>
    </method>
    <method name="ListMpvSessions">
      <arg type="s" direction="out" name="json"/>
    </method>
    <method name="MpvSendCommand">
      <arg type="i" direction="in" name="pid"/>
      <arg type="s" direction="in" name="command"/>
      <arg type="b" direction="out" name="ok"/>
    </method>
  </interface>
</node>`;

export default class StreamDeckTilerExtension extends Extension {
    #dbus = null;
    #registrationId = 0;
    #indicators = new Map();
    #registry = null;
    #settings = null;
    #signalIds = [];
    #claudeState = null;

    enable() {
        this.#dbus = Gio.DBusExportedObject.wrapJSObject(IFACE_XML, this);
        this.#registrationId = this.#dbus.export(
            Gio.DBus.session,
            '/org/gnome/Shell/Extensions/StreamDeckTiler');

        this.#settings = this.getSettings();
        setGettext((s) => this.gettext ? this.gettext(s) : s);
        // Sync schema migrations must run BEFORE indicators load
        // (they read enable-${id} keys that the migrations may
        // have just populated). The async legacy-JSON migration
        // can stay fire-and-forget.
        runSchemaMigrations(this.#settings, m =>
            console.log(`[StreamDeckTiler] schema: ${m}`));
        runMigrationGjs(this.#settings).catch(e =>
            console.log(`[StreamDeckTiler] migration failed: ${e.message}`));

        this._syncDebounce = new Debouncer({delayMs: 5000,
            scheduler: (fn, ms) =>
                GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms,
                    () => { fn(); return GLib.SOURCE_REMOVE; }),
            canceller: id => GLib.source_remove(id)});

        if (this.#settings.get_boolean('enable-git-sync')) {
            const repo = this.#settings.get_string('git-sync-path');
            if (repo) gitPull(repo).then(() => this._syncImport(repo));
        }

        const watchKeys = ['paths','media','instances','icon-overrides',
            'enable-controller','enable-pencil','enable-media','enable-erplibre',
            'enable-network','enable-device','enable-summary','button-order'];
        for (const k of watchKeys) {
            const sig = this.#settings.connect(`changed::${k}`,
                () => this._syncDebounceWrite());
            this.#signalIds.push(sig);
        }

        if (this.#settings.get_boolean('enable-claude-state-watch')) {
            this.#claudeState = new ClaudeStateWatcher();
            this.#claudeState.start().catch(e =>
                console.log(`[StreamDeckTiler] claude-state: ${e.message}`));
            this._notifySeen = new Map(); // sid -> last notif ts (ms)
            this.#claudeState.subscribe(idx =>
                this._maybeNotifyAwaiting(idx));
        }

        this.#registry = new IndicatorRegistry();
        this.#registry.register(controllerDescriptor);
        this.#registry.register(pencilDescriptor);
        this.#registry.register(mediaDescriptor);
        this.#registry.register(erplibreDescriptor);
        this.#registry.register(networkDescriptor);
        this.#registry.register(deviceDescriptor);
        this.#registry.register(summaryDescriptor);
        // Future indicators register themselves here via subsequent plans.

        this._buildIndicators();
        this._connectToggleSignals();

        const orderSig = this.#settings.connect('changed::button-order',
            () => this._reorderIndicators());
        this.#signalIds.push(orderSig);

        const ovSig = this.#settings.connect('changed::icon-overrides',
            () => this._reorderIndicators());
        this.#signalIds.push(ovSig);

        const boxSig = this.#settings.connect('changed::panel-box',
            () => this._reorderIndicators());
        this.#signalIds.push(boxSig);

        console.log('[StreamDeckTiler] enabled');
    }

    disable() {
        if (this.#dbus) {
            this.#dbus.unexport();
            this.#dbus = null;
        }
        for (const id of this.#signalIds) this.#settings?.disconnect(id);
        this.#signalIds = [];
        try { this._syncDebounce?.flush(); } catch (_e) {}
        this._syncDebounce = null;
        for (const ind of this.#indicators.values()) {
            try { ind.destroy(); } catch (e) {
                console.log(`[StreamDeckTiler] destroy ${e.message}`);
            }
        }
        this.#indicators.clear();
        this._virtualKeyboard = null;
        try { this.#claudeState?.stop(); } catch (_e) {}
        this.#claudeState = null;
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
            const overrides = parseObject(
                this.#settings.get_string('icon-overrides'));
            const ind = desc.ctor({
                openPrefs: () => this.openPreferences(),
                extension: this,
                iconName: overrides[id] || undefined,
                claudeState: this.#claudeState,
            });
            const role = `${this.uuid}-${id}`;
            const box = this.#settings.get_string('panel-box') || 'left';
            // -1 appends. In the left box this lands the indicators just
            // before the centre clock; in right it lands at the system-tray
            // edge.
            Main.panel.addToStatusArea(role, ind, -1, box);
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

    // ---------- D-Bus method extensions ----------

    ListPaths()    { return this.#settings.get_string('paths'); }
    ListFilms()    { return this.#settings.get_string('media'); }
    ListMedia()    { return this.#settings.get_string('media'); }
    ListInstances(){ return this.#settings.get_string('instances'); }

    OpenPath(path) {
        const ind = this.#indicators.get('pencil');
        if (!ind) return false;
        const all = JSON.parse(this.#settings.get_string('paths') || '[]');
        const entry = all.find(e => e.path === path) || {path, label: ''};
        ind._launch(entry, this.#settings.get_string('terminal-claude-cmd'));
        return true;
    }

    OpenFilm(filmId, player) { return this.OpenMedia(filmId, player); }

    OpenMedia(mediaId, player) {
        const ind = this.#indicators.get('media');
        if (!ind) return false;
        const all = JSON.parse(this.#settings.get_string('media') || '[]');
        const film = all.find(f => f.id === mediaId);
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
            case 'start_server':
                if (inst.type === 'local') {
                    ind._startServer(inst);
                    return true;
                }
                return false;
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

    DebugClaudeIndex() {
        try {
            const idx = this.#claudeState?.getIndex?.()
                ?? {total: 0, byPath: new Map()};
            const sessions = [];
            for (const bucket of idx.byPath?.values?.() || []) {
                for (const s of (bucket.sessions || [])) {
                    sessions.push({
                        session_id: s.session_id,
                        cwd: s.cwd,
                        status: s.status,
                        ts_active: s.ts_active,
                        ts_stop: s.ts_stop,
                        ts_notification: s.ts_notification,
                        description: (s.description || '').slice(0, 60),
                    });
                }
            }
            return JSON.stringify({
                total: idx.total || 0,
                totalActive: idx.totalActive || 0,
                totalAwaitStop: idx.totalAwaitStop || 0,
                totalAwaitNotify: idx.totalAwaitNotify || 0,
                pollIntervalMs: this.#claudeState?._pollIntervalMs ?? -1,
                pollTimer: this.#claudeState?._pollTimer ?? -1,
                sessions,
            });
        } catch (e) {
            return JSON.stringify({error: e.message || String(e)});
        }
    }

    _maybeNotifyAwaiting(idx) {
        if (!this.#settings ||
            !this.#settings.get_boolean('enable-claude-desktop-notify'))
            return;
        const NOTIFY_THROTTLE_MS = 30 * 1000;
        const now = Date.now();
        const seen = this._notifySeen;
        if (!seen) return;
        for (const bucket of idx?.byPath?.values?.() || []) {
            for (const s of (bucket.sessions || [])) {
                if (s.status !== 'awaiting_notification') continue;
                // The notification ts identifies the *event*; throttle
                // by it so we never re-notify for the same hook fire.
                const eventTs = s.ts_notification || 0;
                const last = seen.get(s.session_id) || 0;
                if (eventTs <= last) continue;
                if (now - last < NOTIFY_THROTTLE_MS) continue;
                seen.set(s.session_id, eventTs);
                const desc = s.description || s.last_prompt || s.session_id;
                const body = s.notification_message || desc;
                try {
                    Main.notify(`Claude: ${desc}`.slice(0, 80), body);
                } catch (_e) {}
            }
        }
    }

    GetFocusedWindowId() {
        try {
            const w = global.display.focus_window;
            if (!w) return '';
            const id = w.get_stable_sequence?.() ?? w.get_id?.() ?? 0;
            return String(id);
        } catch (_e) { return ''; }
    }

    /**
     * Overwrite the `window_id` field of a session's state file to
     * whichever window currently has focus. Used by the pencil "Set
     * window" action so the user can correct a mis-captured target.
     */
    /**
     * Rename a session's `description` field. Marks
     * `description_locked: true` so the hook stops overwriting it on
     * later UserPromptSubmit. Empty string clears the lock so the next
     * prompt re-fills the description automatically.
     */
    RenameClaudeSession(sessionId, description) {
        try {
            const state = this._readClaudeState(sessionId);
            if (!state) return false;
            const text = String(description || '').trim().slice(0, 200);
            state.description = text;
            state.description_locked = text.length > 0;
            return this._writeClaudeState(sessionId, state);
        } catch (_e) { return false; }
    }

    SetClaudeSessionWindow(sessionId) {
        try {
            const state = this._readClaudeState(sessionId);
            if (!state) return false;
            const w = global.display.focus_window;
            if (!w) return false;
            const wid = w.get_stable_sequence?.() ?? w.get_id?.() ?? 0;
            if (!wid) return false;
            state.window_id = Number(wid);
            return this._writeClaudeState(sessionId, state);
        } catch (_e) { return false; }
    }

    /**
     * Send SIGTERM to the Claude process backing this session. The
     * SessionEnd hook then deletes the state file as Claude exits;
     * the watcher's PID-liveness sweep handles a hard kill.
     */
    /**
     * Return the list of running mpv sessions launched through the
     * film indicator as a JSON array. Used by the Stream Deck game
     * tiler so it can show one button per active film.
     */
    ListMpvSessions() {
        try {
            return JSON.stringify(listMpvEntriesSync(Gio, GLib));
        } catch (_e) { return '[]'; }
    }

    MpvSendCommand(pid, command) {
        try {
            const id = Number(pid);
            if (!id || id <= 1) return false;
            // Find the matching entry to get its socket.
            // We could re-read state, but since listMpvEntries is
            // async, do a minimal sync read via Gio here.
            const base = GLib.getenv('XDG_STATE_HOME')
                || `${GLib.get_home_dir()}/.local/state`;
            const path = `${base}/streamdeck-tiler/mpv/${id}.json`;
            if (!GLib.file_test(path, GLib.FileTest.EXISTS)) return false;
            const [ok, contents] = GLib.file_get_contents(path);
            if (!ok) return false;
            const entry = JSON.parse(new TextDecoder().decode(contents));
            const socketPath = entry.ipc_socket;
            if (!socketPath) return false;

            // Map shorthand commands to mpv IPC payloads.
            let payload;
            switch (String(command || '').toLowerCase()) {
                case 'play_pause':
                case 'cycle_pause':
                    payload = {command: ['cycle', 'pause']};
                    break;
                case 'play':
                    payload = {command: ['set_property', 'pause', false]};
                    break;
                case 'pause':
                    payload = {command: ['set_property', 'pause', true]};
                    break;
                case 'quit':
                    payload = {command: ['quit']};
                    break;
                case 'quit_save':
                    payload = {command: ['quit-watch-later']};
                    break;
                case 'vol_up':
                    payload = {command: ['add', 'volume', 5]};
                    break;
                case 'vol_down':
                    payload = {command: ['add', 'volume', -5]};
                    break;
                default:
                    try { payload = JSON.parse(command); }
                    catch (_e) { return false; }
            }
            // Fire and forget; sendMpvCommand is async but Gio
            // sockets honour writes synchronously enough on a Unix
            // domain that the next async boundary will deliver.
            sendMpvCommand(socketPath, payload).catch(() => {});
            return true;
        } catch (_e) { return false; }
    }

    KillClaudeSession(sessionId) {
        try {
            const state = this._readClaudeState(sessionId);
            if (!state || !state.pid) return false;
            const pid = Number(state.pid);
            if (!pid || pid <= 1) return false;
            Gio.Subprocess.new(
                ['kill', String(pid)], Gio.SubprocessFlags.NONE);
            return true;
        } catch (_e) { return false; }
    }

    /**
     * Focus the session's terminal then synthesize an Enter key via
     * ydotool so the user can auto-accept a Claude permission prompt
     * directly from the panel. Returns false (with a notification) if
     * ydotool is not available.
     */
    AcceptClaudeSession(sessionId) {
        const state = this._readClaudeState(sessionId);
        if (!state) return false;
        if (!this.FocusClaudeSession(sessionId)) return false;
        // Synthesize the Enter via Clutter's virtual keyboard. Since
        // we are inside Mutter we don't need wtype/ydotool — Mutter
        // restricts the public virtual-keyboard protocol but trusts
        // its own shell. A short delay gives focus time to land.
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 250, () => {
            try {
                this._sendKeyval(Clutter.KEY_Return);
            } catch (_e) {}
            return GLib.SOURCE_REMOVE;
        });
        return true;
    }

    _sendKeyval(keyval) {
        const seat = Clutter.get_default_backend().get_default_seat();
        if (!this._virtualKeyboard) {
            this._virtualKeyboard = seat.create_virtual_device(
                Clutter.InputDeviceType.KEYBOARD_DEVICE);
        }
        const time = Clutter.CURRENT_TIME;
        this._virtualKeyboard.notify_keyval(
            time, keyval, Clutter.KeyState.PRESSED);
        this._virtualKeyboard.notify_keyval(
            time, keyval, Clutter.KeyState.RELEASED);
    }

    _writeClaudeState(sessionId, data) {
        const sid = String(sessionId || '').trim();
        if (!sid) return false;
        const base = GLib.getenv('XDG_STATE_HOME')
            || `${GLib.get_home_dir()}/.local/state`;
        const dir = `${base}/streamdeck-tiler/claude`;
        const path = `${dir}/${sid}.json`;
        try {
            GLib.mkdir_with_parents(dir, 0o700);
            const json = JSON.stringify(data);
            const tmp = `${path}.tmp`;
            const file = Gio.File.new_for_path(tmp);
            file.replace_contents(
                new TextEncoder().encode(json),
                null, false, Gio.FileCreateFlags.REPLACE_DESTINATION, null);
            GLib.rename(tmp, path);
            return true;
        } catch (_e) { return false; }
    }

    FocusClaudeSession(sessionId) {
        try {
            const state = this._readClaudeState(sessionId);
            if (!state) return false;
            const wid = state.window_id
                ? Number(state.window_id) : 0;
            if (wid > 0) {
                for (const w of this._collectAllWindows()) {
                    const id = w.get_stable_sequence?.()
                        ?? w.get_id?.() ?? 0;
                    if (Number(id) === wid) {
                        return this._activateWindow(w);
                    }
                }
            }
            if (state.pid) {
                return this._focusWindowForPid(state.pid, state.cwd || '');
            }
            return false;
        } catch (_e) { return false; }
    }

    _activateWindow(target) {
        try {
            const time = global.display.get_current_time_roundtrip();
            const ws = target.get_workspace?.();
            const activeWs = global.workspace_manager?.get_active_workspace?.();
            if (ws && activeWs && ws !== activeWs) ws.activate(time);
            try { Main.activateWindow(target, time); }
            catch (_e) { target.activate(time); target.raise?.(); }
            return true;
        } catch (_e) { return false; }
    }

    _readClaudeState(sessionId) {
        const sid = String(sessionId || '').trim();
        if (!sid) return null;
        const base = GLib.getenv('XDG_STATE_HOME')
            || `${GLib.get_home_dir()}/.local/state`;
        const path = `${base}/streamdeck-tiler/claude/${sid}.json`;
        if (!GLib.file_test(path, GLib.FileTest.EXISTS)) return null;
        try {
            const [ok, contents] = GLib.file_get_contents(path);
            if (!ok) return null;
            return JSON.parse(new TextDecoder().decode(contents));
        } catch (_e) { return null; }
    }

    _readPpid(pid) {
        try {
            const [ok, contents] = GLib.file_get_contents(
                `/proc/${pid}/stat`);
            if (!ok) return 0;
            const text = new TextDecoder().decode(contents);
            const rparen = text.lastIndexOf(')');
            if (rparen < 0) return 0;
            const rest = text.slice(rparen + 2).split(' ');
            return parseInt(rest[1], 10) || 0;
        } catch (_e) { return 0; }
    }

    _focusWindowForPid(claudePid, cwd) {
        const ancestors = new Set([claudePid]);
        let p = claudePid;
        for (let i = 0; i < 20; i++) {
            const pp = this._readPpid(p);
            if (pp <= 1) break;
            ancestors.add(pp);
            p = pp;
        }
        const candidates = [];
        for (const w of this._collectAllWindows()) {
            const wpid = w.get_pid?.();
            if (wpid && ancestors.has(wpid)) candidates.push(w);
        }
        if (!candidates.length) return false;
        const basename = String(cwd || '').replace(/\/+$/, '')
            .split('/').pop() || '';
        const sorted = candidates.slice().sort((a, b) => {
            const ta = (a.get_title?.() || '').toLowerCase();
            const tb = (b.get_title?.() || '').toLowerCase();
            const ba = basename && ta.includes(basename.toLowerCase()) ? 1 : 0;
            const bb = basename && tb.includes(basename.toLowerCase()) ? 1 : 0;
            return bb - ba;
        });
        return this._activateWindow(sorted[0]);
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
