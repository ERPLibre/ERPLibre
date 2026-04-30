import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GObject from 'gi://GObject';
import GLib from 'gi://GLib';
import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {detectStreamDecksGjs} from '../lib/usb.js';
import {spawnDetached} from '../lib/spawn.js';
import {makeBadgedIcon, bindBadgeOrientation} from '../lib/badges.js';

function _notify(title, body) {
    try { Main.notify(title, body); } catch (_e) {}
}

const PIDFILE = `${GLib.get_user_cache_dir()}/streamdeck-tiler/controller.pid`;
const CONTROLLER_REL = 'script/stream_deck/erplibre_controller.py';

// See indicators/controller.js for the rationale of the random suffix.
const _GTYPE_SUFFIX = Math.floor(Math.random() * 1e9).toString(36);

export const DeviceIndicator = GObject.registerClass(
{GTypeName: `SDT_DeviceIndicator_${_GTYPE_SUFFIX}`},
class DeviceIndicator extends PanelMenu.Button {
    _init({extension, openPrefs, iconName = 'input-tablet-symbolic'} = {}) {
        super._init(0.0, 'Stream Deck Device');
        this._extension = extension;
        this._openPrefs = openPrefs;
        this._settings = extension.getSettings();
        this._cache = [];
        this._badged = makeBadgedIcon({St, Gio, Clutter, iconName});
        this.add_child(this._badged.actor);
        this._rescanThenRebuild();
        this._sigTimer = this._settings.connect(
            'changed::device-auto-refresh-sec', () => this._resetTimer());
        this._sigBadges = this._settings.connect(
            'changed::enable-icon-badges',
            () => this._refreshBadge());
        this._sigOrient = bindBadgeOrientation(this._badged, this._settings);
        this._resetTimer();
    }

    destroy() {
        if (this._timerId) GLib.source_remove(this._timerId);
        this._timerId = 0;
        if (this._sigTimer) this._settings.disconnect(this._sigTimer);
        this._sigTimer = 0;
        if (this._sigBadges) this._settings.disconnect(this._sigBadges);
        this._sigBadges = 0;
        if (this._sigOrient) this._settings.disconnect(this._sigOrient);
        this._sigOrient = 0;
        super.destroy();
    }

    _refreshBadge() {
        if (!this._badged) return;
        if (!this._settings.get_boolean('enable-icon-badges')) {
            this._badged.setBadges([]);
            return;
        }
        this._badged.setBadges([{count: this._cache.length}]);
    }

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

    async _rescanThenRebuild() {
        this._cache = await detectStreamDecksGjs();
        this._rebuildMenu();
        this._refreshBadge();
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
