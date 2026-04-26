import GObject from 'gi://GObject';
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {scanNmapGjs, scanNcGjs, autoDetectCidrGjs, reverseDnsGjs}
    from '../lib/network.js';
import {parseSshConfig, isWildcardHost} from '../lib/ssh-config.js';
import {buildBrowserArgv, buildTerminalArgv, findTerminal,
    spawnDetached} from '../lib/spawn.js';

function _notify(title, body) {
    try { Main.notify(title, body); } catch (_e) {}
}

export const NetworkIndicator = GObject.registerClass(
class NetworkIndicator extends PanelMenu.Button {
    _init({extension, openPrefs, iconName = 'network-wired-symbolic'} = {}) {
        super._init(0.0, 'Stream Deck Network');
        this._extension = extension;
        this._openPrefs = openPrefs;
        this._settings = extension.getSettings();
        this._scanning = false;
        this._cancellable = null;
        this._scanResult = {cidr: null, hosts: [], lastScan: null};
        const _icon = iconName.startsWith('/')
            ? new St.Icon({
                gicon: Gio.icon_new_for_string(iconName),
                style_class: 'system-status-icon'})
            : new St.Icon({
                icon_name: iconName,
                style_class: 'system-status-icon'});
        this.add_child(_icon);
        this._sigUser = this._settings.connect(
            'changed::network-ssh-user', () => this._rebuildMenu());
        this._sigCfg = this._settings.connect(
            'changed::network-read-ssh-config', () => this._rebuildMenu());
        this._rebuildMenu();
        this._sigTimer = this._settings.connect(
            'changed::network-auto-refresh-sec', () => this._resetTimer());
        this._resetTimer();
    }

    destroy() {
        if (this._cancellable) this._cancellable.cancel();
        if (this._timerId) GLib.source_remove(this._timerId);
        this._timerId = 0;
        for (const s of [this._sigUser, this._sigCfg, this._sigTimer])
            if (s) this._settings.disconnect(s);
        super.destroy();
    }

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

    _rebuildMenu() {
        this.menu.removeAll();
        const lastTxt = this._scanResult.lastScan
            ? new Date(this._scanResult.lastScan).toLocaleTimeString()
            : 'never';
        const cidr = this._scanResult.cidr || '?';
        this.menu.addMenuItem(new PopupMenu.PopupMenuItem(
            `Subnet: ${cidr} · last scan ${lastTxt}`, {reactive: false}));
        const refresh = new PopupMenu.PopupMenuItem(
            this._scanning ? '🔄 Scanning…' : '🔄 Refresh scan');
        refresh.connect('activate', () => this._startScan());
        this.menu.addMenuItem(refresh);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        if (this._settings.get_boolean('network-read-ssh-config')) {
            this._addConfiguredHosts();
            this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        }
        this._addScannedHosts();
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const prefs = new PopupMenu.PopupMenuItem('⚙ Open prefs');
        prefs.connect('activate', () => this._openPrefs?.());
        this.menu.addMenuItem(prefs);
    }

    _addConfiguredHosts() {
        const path = `${GLib.get_home_dir()}/.ssh/config`;
        let hosts = [];
        if (GLib.file_test(path, GLib.FileTest.EXISTS)) {
            try {
                const [ok, contents] = GLib.file_get_contents(path);
                if (ok) hosts = parseSshConfig(
                    new TextDecoder().decode(contents));
            } catch (_e) {}
        }
        const real = hosts.filter(h => !isWildcardHost(h.alias));
        this.menu.addMenuItem(new PopupMenu.PopupMenuItem(
            `— Configured (${real.length}) —`, {reactive: false}));
        if (real.length === 0) {
            this.menu.addMenuItem(new PopupMenu.PopupMenuItem(
                '(no Host stanzas)', {reactive: false}));
            return;
        }
        for (const h of real) this.menu.addMenuItem(this._configuredRow(h));
    }

    _configuredRow(host) {
        const sub = new PopupMenu.PopupSubMenuMenuItem(host.alias);
        const ssh = new PopupMenu.PopupMenuItem('SSH terminal');
        ssh.connect('activate', () => this._sshAlias(host.alias));
        sub.menu.addMenuItem(ssh);
        if (host.fields?.HostName) {
            const cp = new PopupMenu.PopupMenuItem('Copy hostname');
            cp.connect('activate',
                () => this._copy(host.fields.HostName));
            sub.menu.addMenuItem(cp);
        }
        const sftp = new PopupMenu.PopupMenuItem('Open Files (sftp://)');
        sftp.connect('activate',
            () => spawnDetached(buildBrowserArgv(`sftp://${host.alias}`),
                {notify: _notify, title: 'Stream Deck'}));
        sub.menu.addMenuItem(sftp);
        const det = new PopupMenu.PopupMenuItem('Show details');
        det.connect('activate', () => {
            const lines = Object.entries(host.fields)
                .map(([k, v]) => `${k}: ${v}`).join('\n');
            _notify(host.alias, lines || '(no fields)');
        });
        sub.menu.addMenuItem(det);
        return sub;
    }

    _addScannedHosts() {
        this.menu.addMenuItem(new PopupMenu.PopupMenuItem(
            `— Scanned (${this._scanResult.hosts.length}) —`,
            {reactive: false}));
        for (const host of this._scanResult.hosts) {
            const sub = new PopupMenu.PopupSubMenuMenuItem(
                `${host.hostname || host.ip} (${host.ip})`);
            const ssh = new PopupMenu.PopupMenuItem('SSH terminal');
            ssh.connect('activate', () => this._sshIp(host.ip));
            sub.menu.addMenuItem(ssh);
            const cp = new PopupMenu.PopupMenuItem('Copy IP');
            cp.connect('activate', () => this._copy(host.ip));
            sub.menu.addMenuItem(cp);
            const sftp = new PopupMenu.PopupMenuItem('Open Files (sftp://)');
            sftp.connect('activate', () => spawnDetached(
                buildBrowserArgv(`sftp://${host.ip}`),
                {notify: _notify, title: 'Stream Deck'}));
            sub.menu.addMenuItem(sftp);
            const det = new PopupMenu.PopupMenuItem('Show details');
            det.connect('activate',
                () => _notify(host.ip,
                    `hostname: ${host.hostname || '?'}, port22: open`));
            sub.menu.addMenuItem(det);
            this.menu.addMenuItem(sub);
        }
    }

    async _sshAlias(alias) {
        const terminal = await findTerminal();
        if (!terminal) return;
        spawnDetached(
            buildTerminalArgv({cwd: GLib.get_home_dir(),
                command: `ssh ${alias}`, terminal}),
            {notify: _notify, title: 'Stream Deck'});
    }

    async _sshIp(ip) {
        const terminal = await findTerminal();
        if (!terminal) return;
        const userPref = this._settings.get_string('network-ssh-user').trim();
        const user = userPref || GLib.get_user_name();
        spawnDetached(
            buildTerminalArgv({cwd: GLib.get_home_dir(),
                command: `ssh ${user}@${ip}`, terminal}),
            {notify: _notify, title: 'Stream Deck'});
    }

    _copy(text) {
        try {
            St.Clipboard.get_default()
                .set_text(St.ClipboardType.CLIPBOARD, text);
        } catch (_e) {}
    }

    async _startScan() {
        if (this._scanning) return;
        this._scanning = true;
        this._cancellable = new Gio.Cancellable();
        this._rebuildMenu();
        try {
            const cidrs = this._settings.get_strv('network-cidrs');
            const cidr = cidrs.length > 0 ? cidrs[0]
                : (await autoDetectCidrGjs());
            if (!cidr) {
                _notify('Stream Deck', 'No network detected');
                return;
            }
            const useNmap = this._settings.get_boolean('network-use-nmap')
                && GLib.find_program_in_path('nmap');
            const scanner = useNmap ? scanNmapGjs : scanNcGjs;
            const {hosts, error} = await scanner(cidr, this._cancellable);
            if (error) _notify('Stream Deck', `Scan failed: ${error}`);
            for (const h of hosts) h.hostname = await reverseDnsGjs(h.ip);
            this._scanResult = {cidr, hosts, lastScan: Date.now()};
        } finally {
            this._scanning = false;
            this._cancellable = null;
            this._rebuildMenu();
        }
    }
});

export const indicatorDescriptor = {
    id: 'network',
    displayName: 'Network',
    defaultEnabled: true,
    ctor: (opts) => new NetworkIndicator(opts),
};
