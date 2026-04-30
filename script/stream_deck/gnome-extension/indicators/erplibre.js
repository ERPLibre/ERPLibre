import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GObject from 'gi://GObject';
import GLib from 'gi://GLib';
import Soup from 'gi://Soup';
import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {parseList, serializeList, uuid4} from '../lib/settings.js';
import {buildBrowserArgv, buildTerminalArgv, findTerminal,
    spawnDetached, runProcess} from '../lib/spawn.js';
import {detectLocalInstancesGjs} from '../lib/erplibre-detect.js';
import {callKeepassCli, masterPasswordCache, cacheKey}
    from '../lib/keepass.js';
import {InstanceDialog} from '../ui/instance-dialog.js';
import {MasterPwDialog} from '../ui/master-pw-dialog.js';
import {makeBadgedIcon, bindBadgeOrientation, attachHoverTooltip,
    formatBadgeTooltip, BADGE_OK, BADGE_WARN, BADGE_ALERT}
    from '../lib/badges.js';
import {_} from '../lib/i18n.js';

const PROBE_TTL_MS = 30 * 1000;

function _notify(title, body) {
    try { Main.notify(title, body); } catch (_e) {}
}

// See indicators/controller.js for the rationale of the random suffix.
const _GTYPE_SUFFIX = Math.floor(Math.random() * 1e9).toString(36);

export const ErpLibreIndicator = GObject.registerClass(
{GTypeName: `SDT_ErpLibreIndicator_${_GTYPE_SUFFIX}`},
class ErpLibreIndicator extends PanelMenu.Button {
    _init({extension, openPrefs, iconName = 'network-server-symbolic'} = {}) {
        super._init(0.0, 'Stream Deck ERPLibre');
        this._extension = extension;
        this._openPrefs = openPrefs;
        this._settings = extension.getSettings();
        this._localCache = [];
        this._instanceStatus = new Map(); // id -> {state, ts}
        this._badged = makeBadgedIcon({St, Gio, Clutter, iconName});
        this.add_child(this._badged.actor);
        this.menu.connect('open-state-changed', (_menu, isOpen) => {
            if (isOpen) this._probeAllInstances();
        });
        this._sigInstances = this._settings.connect('changed::instances',
            () => { this._rebuildMenu(); this._refreshBadge(); });
        this._sigPattern = this._settings.connect(
            'changed::erplibre-local-pattern', () => this._rescanThenRebuild());
        this._sigAuto = this._settings.connect(
            'changed::erplibre-auto-detect', () => this._rescanThenRebuild());
        this._sigBadges = this._settings.connect(
            'changed::enable-icon-badges',
            () => this._refreshBadge());
        this._sigOrient = bindBadgeOrientation(this._badged, this._settings);
        this._tip = attachHoverTooltip({
            St, Clutter,
            uiGroup: Main.layoutManager.uiGroup,
            target: this,
            getText: () => this._tooltipText(),
        });
        this._rescanThenRebuild();
    }

    destroy() {
        for (const s of [this._sigInstances, this._sigPattern, this._sigAuto,
            this._sigBadges, this._sigOrient])
            if (s) this._settings.disconnect(s);
        this._tip?.detach();
        super.destroy();
    }

    _tooltipText() {
        const all = this._allInstances();
        const total = all.length;
        const probed = all
            .map(i => this._instanceStatus.get(i.id)?.state)
            .filter(s => s);
        const up = probed.filter(s => s === 'up').length;
        const down = probed.filter(s => s === 'down').length;
        return formatBadgeTooltip([
            {count: total, label: 'instances', alwaysShow: true},
            {count: up,    label: 'up'},
            {count: down,  label: 'down'},
        ]);
    }

    _refreshBadge() {
        if (!this._badged) return;
        if (!this._settings.get_boolean('enable-icon-badges')) {
            this._badged.setBadges([]);
            return;
        }
        const all = this._allInstances();
        const total = all.length;
        if (total === 0) {
            this._badged.setBadges([]);
            return;
        }
        const probed = all
            .map(i => this._instanceStatus.get(i.id)?.state)
            .filter(s => s);
        const upCount = probed.filter(s => s === 'up').length;
        const downCount = probed.filter(s => s === 'down').length;
        let kind = BADGE_OK;
        if (probed.length > 0) {
            if (upCount === 0) kind = BADGE_ALERT;
            else if (downCount > 0) kind = BADGE_WARN;
        }
        this._badged.setBadges([{count: total, kind}]);
    }

    _allInstances() {
        const remotes = parseList(this._settings.get_string('instances'));
        return [
            ...(this._localCache || []).map(i => ({...i, _local: true})),
            ...remotes.map(i => ({...i, _local: false})),
        ];
    }

    _probeAllInstances() {
        const now = GLib.get_real_time() / 1000;
        const stale = id => {
            const e = this._instanceStatus.get(id);
            return !e || (now - e.ts) > PROBE_TTL_MS;
        };
        for (const inst of this._allInstances()) {
            if (!inst.id || !inst.url) continue;
            if (!stale(inst.id)) continue;
            this._probeInstance(inst);
        }
    }

    _probeInstance(inst) {
        try {
            const session = new Soup.Session();
            session.timeout = 2;
            const message = Soup.Message.new('GET', inst.url);
            session.send_and_read_async(
                message, GLib.PRIORITY_DEFAULT, null, (sess, result) => {
                    let state = 'down';
                    try {
                        sess.send_and_read_finish(result);
                        state = 'up';
                    } catch (_e) {
                        state = 'down';
                    }
                    this._instanceStatus.set(inst.id, {
                        state,
                        ts: GLib.get_real_time() / 1000,
                    });
                    this._refreshBadge();
                    this._rebuildMenu();
                });
        } catch (_e) {
            this._instanceStatus.set(inst.id, {
                state: 'down', ts: GLib.get_real_time() / 1000,
            });
        }
    }

    async _rescanThenRebuild() {
        if (this._settings.get_boolean('erplibre-auto-detect')) {
            this._localCache = await detectLocalInstancesGjs(
                this._settings.get_string('erplibre-local-pattern'));
        } else {
            this._localCache = [];
        }
        this._rebuildMenu();
        this._refreshBadge();
    }

    _rebuildMenu() {
        this.menu.removeAll();
        const remotes = parseList(this._settings.get_string('instances'));

        const localHeader = new PopupMenu.PopupMenuItem(_('— Local —'),
            {reactive: false});
        this.menu.addMenuItem(localHeader);
        if (this._localCache.length === 0) {
            this.menu.addMenuItem(new PopupMenu.PopupMenuItem(
                _('(no local instances)'), {reactive: false}));
        } else {
            for (const inst of this._localCache)
                this.menu.addMenuItem(this._makeRow(inst, true));
        }

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        const remoteHeader = new PopupMenu.PopupMenuItem(_('— Remote —'),
            {reactive: false});
        this.menu.addMenuItem(remoteHeader);
        if (remotes.length === 0) {
            this.menu.addMenuItem(new PopupMenu.PopupMenuItem(
                _('(no remote instances — use Add)'), {reactive: false}));
        } else {
            for (const inst of remotes)
                this.menu.addMenuItem(this._makeRow(inst, false));
        }

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const add = new PopupMenu.PopupMenuItem(_('+ Add remote instance…'));
        add.connect('activate', () => this._openAddDialog());
        this.menu.addMenuItem(add);
        const rescan = new PopupMenu.PopupMenuItem(_('🔄 Re-scan local'));
        rescan.connect('activate', () => this._rescanThenRebuild());
        this.menu.addMenuItem(rescan);
    }

    _makeRow(inst, isLocal) {
        const status = this._instanceStatus.get(inst.id)?.state;
        const dot = status === 'up' ? '🟢 '
            : status === 'down' ? '🔴 '
            : '⚪ ';
        const sub = new PopupMenu.PopupSubMenuMenuItem(`${dot}${inst.name}`);
        const open = new PopupMenu.PopupMenuItem(_('Open URL'));
        open.connect('activate', () => this._launchBrowser(inst));
        sub.menu.addMenuItem(open);

        if (isLocal) {
            const start = new PopupMenu.PopupMenuItem(_('Start server'));
            start.connect('activate', () => this._startServer(inst));
            sub.menu.addMenuItem(start);
        }

        const hasKeepass = inst.keepass_db && inst.keepass_entry;
        if (hasKeepass) {
            if (inst.auto_login_method !== 'none') {
                const login = new PopupMenu.PopupMenuItem(
                    _('Auto-login ({method})')
                        .replace('{method}', inst.auto_login_method));
                login.connect('activate', () => this._autoLogin(inst));
                sub.menu.addMenuItem(login);
            }
            const cu = new PopupMenu.PopupMenuItem(_('Copy username'));
            cu.connect('activate', () => this._copyAttr(inst, 'username'));
            sub.menu.addMenuItem(cu);
            const cp = new PopupMenu.PopupMenuItem(_('Copy password'));
            cp.connect('activate', () => this._copyAttr(inst, 'password'));
            sub.menu.addMenuItem(cp);
            const ok = new PopupMenu.PopupMenuItem(_('Open in KeePassXC'));
            ok.connect('activate', () => this._openInKeepassXC(inst));
            sub.menu.addMenuItem(ok);
        }

        const edit = new PopupMenu.PopupMenuItem(_('Edit instance'));
        edit.connect('activate', () => this._editEntry(inst, isLocal));
        sub.menu.addMenuItem(edit);
        return sub;
    }

    _launchBrowser(inst) {
        spawnDetached(buildBrowserArgv(inst.url),
            {notify: _notify, title: 'ERPLibre'});
    }

    async _startServer(inst) {
        const terminal = await findTerminal();
        if (!terminal) return;
        const argv = buildTerminalArgv({
            cwd: inst.local_path,
            command: 'make run',
            terminal,
        });
        spawnDetached(argv, {notify: _notify, title: 'ERPLibre'});
    }

    async _withMasterPw(inst, action) {
        const key = cacheKey({
            db: inst.keepass_db,
            keyfile: inst.keepass_keyfile,
            yubikey_serial: inst.keepass_yubikey_serial,
        });
        const cached = masterPasswordCache.get(key);
        const run = pw => action(pw, key);
        if (cached !== undefined) return run(cached);
        const dlg = new MasterPwDialog({
            db: inst.keepass_db,
            onConfirm: pw => {
                masterPasswordCache.set(key, pw);
                run(pw);
            },
        });
        dlg.open();
    }

    async _fetchAttr(inst, attribute) {
        return new Promise(resolve => {
            this._withMasterPw(inst, async (pw, key) => {
                const result = await callKeepassCli({
                    db: inst.keepass_db,
                    keyfile: inst.keepass_keyfile,
                    yubikey_slot: inst.keepass_yubikey_slot,
                    yubikey_serial: inst.keepass_yubikey_serial,
                    entry: inst.keepass_entry,
                    attribute,
                    masterPassword: pw,
                });
                if (result === null) {
                    masterPasswordCache.invalidate(key);
                    _notify('ERPLibre', 'KeePassXC unlock failed');
                }
                resolve(result);
            });
        });
    }

    async _copyAttr(inst, attribute) {
        const value = await this._fetchAttr(inst, attribute);
        if (value === null || value === undefined) return;
        try {
            const Clipboard = St.Clipboard.get_default();
            Clipboard.set_text(St.ClipboardType.CLIPBOARD, value);
            _notify('ERPLibre', `${attribute} copied`);
        } catch (_e) {}
    }

    _openInKeepassXC(inst) {
        const argv = ['keepassxc', inst.keepass_db];
        if (inst.keepass_keyfile) argv.push('--keyfile', inst.keepass_keyfile);
        spawnDetached(argv, {notify: _notify, title: 'ERPLibre'});
    }

    async _autoLogin(inst) {
        const user = await this._fetchAttr(inst, 'username');
        if (!user) return;
        const pass = await this._fetchAttr(inst, 'password');
        if (!pass) return;
        if (inst.auto_login_method === 'selenium')
            this._autoLoginSelenium(inst, user, pass);
        else if (inst.auto_login_method === 'xdotool')
            this._autoLoginXdotool(inst, user, pass);
    }

    _autoLoginSelenium(inst, user, pass) {
        // Resolve project root: assume extension lives in
        //   script/stream_deck/gnome-extension; root is three dirs up.
        const home = GLib.get_home_dir();
        const root = this._settings.get_string('git-sync-path').trim()
            || this._extension.path.replace(
                /\/script\/stream_deck\/gnome-extension\/?$/, '');
        const venv = `${root}/.venv.erplibre/bin/python`;
        const script = `${root}/script/selenium/web_login.py`;
        const argv = [venv, script,
            '--url', inst.url, '--user', user, '--pass', pass];
        if (!GLib.file_test(venv, GLib.FileTest.IS_EXECUTABLE)) {
            _notify('ERPLibre',
                `.venv.erplibre missing — falling back to xdotool`);
            this._autoLoginXdotool(inst, user, pass);
            return;
        }
        runProcess(argv, {notify: _notify, title: 'ERPLibre'});
    }

    async _autoLoginXdotool(inst, user, pass) {
        spawnDetached(buildBrowserArgv(inst.url),
            {notify: _notify, title: 'ERPLibre'});
        // Wait for browser focus to land. xdotool itself is the runner.
        const seq = [
            ['sleep', '2'],
            ['xdotool', 'type', user],
            ['xdotool', 'key', 'Tab'],
            ['xdotool', 'type', pass],
            ['xdotool', 'key', 'Return'],
        ];
        for (const argv of seq)
            await runProcess(argv, {notify: _notify, title: 'ERPLibre'});
    }

    _openAddDialog() {
        const dlg = new InstanceDialog({
            title: 'Add remote instance',
            onConfirm: data => {
                const list = parseList(this._settings.get_string('instances'));
                list.push({id: uuid4(), type: 'remote',
                    local_path: '', ...data});
                this._settings.set_string('instances', serializeList(list));
            },
        });
        dlg.open();
    }

    _editEntry(inst, isLocal) {
        if (isLocal) {
            // Local instances aren't persisted; promote to remote on save.
            const dlg = new InstanceDialog({
                title: 'Edit local override → save as remote',
                entry: inst,
                onConfirm: data => {
                    const list = parseList(this._settings.get_string('instances'));
                    list.push({id: uuid4(), type: 'remote',
                        local_path: '', ...data});
                    this._settings.set_string('instances', serializeList(list));
                },
            });
            dlg.open();
            return;
        }
        const dlg = new InstanceDialog({
            title: 'Edit instance',
            entry: inst,
            onConfirm: data => {
                const list = parseList(this._settings.get_string('instances'));
                const i = list.findIndex(e => e.id === inst.id);
                if (i >= 0) {
                    list[i] = {...list[i], ...data};
                    this._settings.set_string('instances', serializeList(list));
                }
            },
            onDelete: () => {
                const list = parseList(this._settings.get_string('instances'))
                    .filter(e => e.id !== inst.id);
                this._settings.set_string('instances', serializeList(list));
            },
        });
        dlg.open();
    }
});

export const indicatorDescriptor = {
    id: 'erplibre',
    displayName: 'ERPLibre',
    defaultEnabled: true,
    ctor: (opts) => new ErpLibreIndicator(opts),
};
