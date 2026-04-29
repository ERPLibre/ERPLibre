import {uuid4} from '../lib/settings.js';

export function resolveLabel(entry) {
    if (entry?.label && entry.label.trim() !== '') return entry.label;
    const path = entry?.path || '';
    if (path === '/') return '/';
    const trimmed = path.replace(/\/+$/, '');
    const idx = trimmed.lastIndexOf('/');
    return idx >= 0 ? trimmed.slice(idx + 1) : trimmed;
}

export function defaultPathEntry({label = '', path = '', default_cmd} = {}) {
    return {
        id: uuid4(),
        label,
        path,
        default_cmd: default_cmd || 'claude --resume',
    };
}

// Indicator class + descriptor are added in Task 2.

import {parseList, serializeList, pushRecent} from '../lib/settings.js';
import {findTerminal, buildTerminalArgv, spawnDetached} from '../lib/spawn.js';

// `gi://` and `resource://` modules are only resolvable inside GJS. We
// therefore load them via dynamic import behind a try/catch so this file
// can also be evaluated under Node for unit tests of the pure helpers
// above. In GJS, the `try` branch succeeds and we register the indicator
// class + descriptor; in Node the imports throw and we leave a stub
// descriptor whose `ctor` errors out if anyone tries to instantiate it.

export let PencilIndicator = null;
export let indicatorDescriptor = {
    id: 'pencil',
    displayName: 'Pencil',
    defaultEnabled: true,
    ctor: () => {
        throw new Error(
            'PencilIndicator unavailable: GJS modules failed to load.'
        );
    },
};

try {
    const {default: Clutter} = await import('gi://Clutter');
    const {default: Gio} = await import('gi://Gio');
    const {default: GLib} = await import('gi://GLib');
    const {default: GObject} = await import('gi://GObject');
    const {default: St} = await import('gi://St');
    const Main = await import('resource:///org/gnome/shell/ui/main.js');
    const PanelMenu = await import(
        'resource:///org/gnome/shell/ui/panelMenu.js'
    );
    const PopupMenu = await import(
        'resource:///org/gnome/shell/ui/popupMenu.js'
    );
    const {PathDialog} = await import('../ui/path-dialog.js');
    const {makeBadgedIcon, badgeStyleFor, BADGE_DEFAULT, BADGE_OK,
        BADGE_WARN, BADGE_ALERT, formatBadgeCount} =
        await import('../lib/badges.js');
    const {_} = await import('../lib/i18n.js');
    const {normPath: _normPath, assignSessionsToPaths: _assignSessionsToPaths} =
        await import('../lib/pencil-helpers.js');

    const _DOT_COLOR_BY_KIND = {
        [BADGE_DEFAULT]: '#3477b8',
        [BADGE_OK]: '#2e7d32',
        [BADGE_WARN]: '#d4a017',
        [BADGE_ALERT]: '#c62828',
    };
    const _dotColorStyle = kind =>
        `color: ${_DOT_COLOR_BY_KIND[kind] ||
            _DOT_COLOR_BY_KIND[BADGE_DEFAULT]}; font-weight: bold;`;

    const _shortId = id => String(id || '').slice(0, 8);

    const _notify = (title, body) => {
        try {
            Main.notify(title, body);
        } catch (_e) {
            // best-effort notification
        }
    };

    // See indicators/controller.js for the rationale of the random suffix.
    const _GTYPE_SUFFIX = Math.floor(Math.random() * 1e9).toString(36);

    PencilIndicator = GObject.registerClass(
        {GTypeName: `SDT_PencilIndicator_${_GTYPE_SUFFIX}`},
        class PencilIndicator extends PanelMenu.Button {
            _init({extension, openPrefs, claudeState,
                iconName = 'document-edit-symbolic'} = {}) {
                super._init(0.0, 'Stream Deck Pencil');
                this._extension = extension;
                this._openPrefs = openPrefs;
                this._settings = extension?.getSettings
                    ? extension.getSettings()
                    : null;
                this._claudeState = claudeState || null;
                this._claudeIndex = null;

                this._badged = makeBadgedIcon({St, Gio, Clutter, iconName});
                this.add_child(this._badged.actor);

                if (this._settings) {
                    this._pathsSig = this._settings.connect(
                        'changed::paths',
                        () => { this._rebuildMenu(); this._refreshBadge(); }
                    );
                    this._cmdSig = this._settings.connect(
                        'changed::terminal-claude-cmd',
                        () => this._rebuildMenu()
                    );
                    this._badgeSig = this._settings.connect(
                        'changed::enable-icon-badges',
                        () => this._refreshBadge()
                    );
                }

                if (this._claudeState) {
                    this._claudeUnsub = this._claudeState.subscribe(
                        idx => {
                            this._claudeIndex = idx;
                            this._rebuildMenu();
                            this._refreshBadge();
                        });
                }

                this._rebuildMenu();
                this._refreshBadge();
            }

            destroy() {
                if (this._settings) {
                    for (const k of ['_pathsSig', '_cmdSig', '_badgeSig']) {
                        if (this[k]) {
                            this._settings.disconnect(this[k]);
                            this[k] = null;
                        }
                    }
                }
                if (this._claudeUnsub) {
                    try { this._claudeUnsub(); } catch (_e) {}
                    this._claudeUnsub = null;
                }
                super.destroy();
            }

            _refreshBadge() {
                if (!this._badged) return;
                if (this._settings &&
                    !this._settings.get_boolean('enable-icon-badges')) {
                    this._badged.setBadges([]);
                    return;
                }
                const dirs = this._settings
                    ? parseList(this._settings.get_string('paths')).length
                    : 0;
                const idx = this._claudeIndex;
                const totalActive = idx?.totalActive || 0;
                const awaitStop = idx?.totalAwaitStop || 0;
                const awaitNotify = idx?.totalAwaitNotify || 0;
                const awaiting = awaitStop + awaitNotify;
                const awaitKind = awaitNotify > 0
                    ? BADGE_ALERT : BADGE_WARN;
                this._badged.setBadges([
                    {count: dirs, kind: BADGE_DEFAULT},
                    totalActive > 0
                        ? {count: totalActive, kind: BADGE_OK}
                        : null,
                    awaiting > 0
                        ? {count: awaiting, kind: awaitKind}
                        : null,
                ]);
            }

            _rebuildMenu() {
                this.menu.removeAll();

                const paths = this._settings
                    ? parseList(this._settings.get_string('paths'))
                    : [];

                const allSessions = this._claudeIndex
                    ? Array.from(this._claudeIndex.byPath?.values() || [])
                        .flatMap(b => b.sessions)
                    : [];
                this._sessionOwner = _assignSessionsToPaths(
                    allSessions, paths);

                if (!paths.length) {
                    this.menu.addMenuItem(new PopupMenu.PopupMenuItem(
                        _('(no paths configured — use Add path…)'),
                        {reactive: false}));
                } else {
                    for (const entry of paths) {
                        this.menu.addMenuItem(this._makeRow(entry));
                        for (const item of this._makeSessionRows(entry)) {
                            this.menu.addMenuItem(item);
                        }
                    }
                }

                const orphans = allSessions.filter(
                    s => !this._sessionOwner.has(s.session_id));
                if (orphans.length) {
                    this.menu.addMenuItem(
                        new PopupMenu.PopupSeparatorMenuItem());
                    this.menu.addMenuItem(new PopupMenu.PopupMenuItem(
                        _('— Other sessions ({n}) —')
                            .replace('{n}', orphans.length),
                        {reactive: false}));
                    const sorted = orphans.slice().sort(
                        (a, b) => (b.ts || 0) - (a.ts || 0));
                    for (const s of sorted)
                        this.menu.addMenuItem(this._makeSessionItem(s));
                }

                this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

                const addItem = new PopupMenu.PopupMenuItem(_('+ Add path…'));
                addItem.connect('activate', () => this._openAddDialog());
                this.menu.addMenuItem(addItem);

                const prefsItem = new PopupMenu.PopupMenuItem(
                    _('⚙ Open prefs'));
                prefsItem.connect('activate', () => {
                    if (typeof this._openPrefs === 'function') {
                        try {
                            this._openPrefs();
                        } catch (_e) {
                            // ignore
                        }
                    }
                });
                this.menu.addMenuItem(prefsItem);

                this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
                this.menu.addMenuItem(new PopupMenu.PopupMenuItem(
                    _('— Legend —'), {reactive: false}));
                for (const row of this._buildLegendRows()) {
                    this.menu.addMenuItem(row);
                }
            }

            _buildLegendRows() {
                const entries = [
                    {kind: BADGE_DEFAULT,
                     text: _('Path / catalogue count')},
                    {kind: BADGE_OK,
                     text: _('Active session (Claude working)')},
                    {kind: BADGE_WARN,
                     text: _('Awaiting answer (Stop hook fired)')},
                    {kind: BADGE_ALERT,
                     text: _('Needs attention (Notification hook)')},
                ];
                return entries.map(e => {
                    const item = new PopupMenu.PopupBaseMenuItem(
                        {reactive: false, can_focus: false});
                    const box = new St.BoxLayout({
                        vertical: false,
                        style: 'spacing: 8px;',
                        x_expand: true,
                    });
                    box.add_child(new St.Label({
                        text: '●',
                        y_align: Clutter.ActorAlign.CENTER,
                        style: _dotColorStyle(e.kind),
                    }));
                    box.add_child(new St.Label({
                        text: e.text,
                        y_align: Clutter.ActorAlign.CENTER,
                        style: 'opacity: 0.85;',
                    }));
                    item.add_child(box);
                    return item;
                });
            }

            _makeRow(entry) {
                const item = new PopupMenu.PopupBaseMenuItem({reactive: false});
                const box = new St.BoxLayout({
                    vertical: false,
                    style: 'spacing: 6px;',
                    x_expand: true,
                });

                const labelBox = new St.BoxLayout({
                    vertical: true,
                    x_expand: true,
                });
                const titleRow = new St.BoxLayout({
                    vertical: false,
                    style: 'spacing: 6px;',
                });
                titleRow.add_child(new St.Label({text: resolveLabel(entry)}));
                const rowBadge = this._buildRowBadge(entry);
                if (rowBadge) titleRow.add_child(rowBadge);
                labelBox.add_child(titleRow);
                labelBox.add_child(new St.Label({
                    text: entry.path,
                    style: 'opacity: 0.6; font-size: 0.85em;',
                }));
                box.add_child(labelBox);

                const defaultCmd = this._settings
                    ? this._settings.get_string('terminal-claude-cmd')
                    : 'claude --resume';

                const resumeBtn = this._mkBtn(_('Resume'),
                    () => this._launch(entry, 'claude --resume'));
                const freshBtn = this._mkBtn(_('Fresh'),
                    () => this._launch(entry, 'claude'));
                const customBtn = this._mkBtn(_('Custom…'),
                    () => this._launch(entry, defaultCmd));
                const editBtn = this._mkBtn('✎',
                    () => this._editEntry(entry));

                for (const b of [resumeBtn, freshBtn, customBtn, editBtn]) {
                    box.add_child(b);
                }
                item.add_child(box);
                return item;
            }

            _makeSessionRows(entry) {
                const rows = [];
                if (!this._sessionOwner) return rows;
                const owner = _normPath(entry.path);
                const allSessions = Array.from(
                    this._claudeIndex?.byPath?.values() || [])
                    .flatMap(b => b.sessions);
                const ours = allSessions.filter(
                    s => this._sessionOwner.get(s.session_id) === owner);
                ours.sort((a, b) => (b.ts || 0) - (a.ts || 0));
                for (const s of ours) {
                    rows.push(this._makeSessionItem(s));
                    for (const act of this._makeSessionActions(s)) {
                        rows.push(act);
                    }
                }
                return rows;
            }

            _makeSessionActions(session) {
                const out = [];
                const setItem = new PopupMenu.PopupMenuItem(
                    `   ⤺ ${_('Set window…')}`);
                setItem.connect('activate',
                    () => this._startSetWindow(session));
                out.push(setItem);

                if (session.status === 'awaiting_notification'
                        || session.status === 'awaiting_stop') {
                    const accept = new PopupMenu.PopupMenuItem(
                        `   ↵ ${_('Accept response (send Enter)')}`);
                    accept.connect('activate',
                        () => this._acceptSession(session));
                    out.push(accept);
                }
                return out;
            }

            _startSetWindow(session) {
                _notify(_('Stream Deck'),
                    _('Switch to the target terminal within 3 s — its '
                      + 'window will be saved for this session.'));
                const sid = session.session_id;
                if (!sid) return;
                const ext = this._extension;
                if (!ext) return;
                GLib.timeout_add(GLib.PRIORITY_DEFAULT, 3000, () => {
                    const ok = ext.SetClaudeSessionWindow?.(sid);
                    _notify(_('Stream Deck'),
                        ok ? _('Window saved.')
                           : _('No focused window — try again.'));
                    return GLib.SOURCE_REMOVE;
                });
            }

            _acceptSession(session) {
                const sid = session.session_id;
                if (!sid) return;
                const ok = this._extension?.AcceptClaudeSession?.(sid);
                if (!ok) {
                    _notify(_('Stream Deck'),
                        _('Could not send Enter — see '
                          + 'script/stream_deck/INSTALL.md'));
                }
            }

            _makeSessionItem(session) {
                const item = new PopupMenu.PopupBaseMenuItem();
                item.connect('activate', () => {
                    try {
                        this._extension?.FocusClaudeSession?.(
                            session.session_id);
                    } catch (e) {
                        _notify(_('Stream Deck'),
                            _('Focus failed: ') + (e.message || e));
                    }
                });
                const box = new St.BoxLayout({
                    vertical: false,
                    style: 'spacing: 8px; padding-left: 16px;',
                    x_expand: true,
                });

                let dotKind = BADGE_OK;
                let stateLabel = _('Working');
                if (session.status === 'awaiting_notification') {
                    dotKind = BADGE_ALERT;
                    stateLabel = _('Needs attention');
                } else if (session.status === 'awaiting_stop') {
                    dotKind = BADGE_WARN;
                    stateLabel = _('Awaiting answer');
                }

                const dot = new St.Label({
                    text: '●',
                    y_align: Clutter.ActorAlign.CENTER,
                    style: `${_dotColorStyle(dotKind)}`,
                });
                box.add_child(dot);

                const labelBox = new St.BoxLayout({
                    vertical: true,
                    x_expand: true,
                });
                const desc = session.description ||
                    session.last_prompt || _('(no description yet)');
                labelBox.add_child(new St.Label({text: desc}));
                const meta = `${stateLabel} · ${_shortId(session.session_id)}`;
                labelBox.add_child(new St.Label({
                    text: meta,
                    style: 'opacity: 0.6; font-size: 0.85em;',
                }));
                box.add_child(labelBox);

                item.add_child(box);
                return item;
            }

            _buildRowBadge(entry) {
                if (!this._sessionOwner || !this._claudeIndex) return null;
                const owner = _normPath(entry.path);
                const allSessions = Array.from(
                    this._claudeIndex.byPath?.values() || [])
                    .flatMap(b => b.sessions);
                const ours = allSessions.filter(
                    s => this._sessionOwner.get(s.session_id) === owner);
                if (!ours.length) return null;
                let kind = BADGE_OK;
                if (ours.some(s => s.status === 'awaiting_notification'))
                    kind = BADGE_ALERT;
                else if (ours.some(s => s.status === 'awaiting_stop'))
                    kind = BADGE_WARN;
                return new St.Label({
                    text: formatBadgeCount(ours.length),
                    style: badgeStyleFor(kind),
                });
            }

            _mkBtn(label, onClick) {
                const btn = new St.Button({
                    label,
                    style_class: 'streamdeck-tiler-btn',
                    style: 'padding: 2px 6px;',
                });
                btn.connect('clicked', () => {
                    try {
                        onClick();
                    } catch (e) {
                        _notify(_('Stream Deck'),
                            _('Action failed: ') + (e.message || e));
                    }
                });
                return btn;
            }

            async _launch(entry, command) {
                const terminal = await findTerminal();
                if (!terminal) {
                    _notify(_('Stream Deck'),
                        _('No terminal found. Install gnome-terminal, '
                          + 'kgx or xterm.'));
                    return;
                }
                const argv = buildTerminalArgv({
                    cwd: entry.path,
                    command,
                    terminal,
                });
                const ok = await spawnDetached(argv,
                    {notify: _notify, title: _('Stream Deck')});
                if (ok && this._settings && entry?.path) {
                    const recent = parseList(
                        this._settings.get_string('recent-paths'));
                    this._settings.set_string('recent-paths',
                        serializeList(pushRecent(recent, entry.path)));
                }
            }

            _openAddDialog() {
                if (!this._settings) return;
                const recent = parseList(
                    this._settings.get_string('recent-paths'));
                const dlg = new PathDialog({
                    title: _('Add path'),
                    recentPaths: recent,
                    onConfirm: ({label, path}) => {
                        const list = parseList(
                            this._settings.get_string('paths'));
                        list.push(defaultPathEntry({label, path}));
                        this._settings.set_string('paths',
                            serializeList(list));
                    },
                });
                dlg.open();
            }

            _editEntry(entry) {
                if (!this._settings) return;
                const dlg = new PathDialog({
                    title: _('Edit path'),
                    entry,
                    onConfirm: ({label, path}) => {
                        const list = parseList(
                            this._settings.get_string('paths'));
                        const i = list.findIndex(e => e.id === entry.id);
                        if (i >= 0) {
                            list[i] = {...list[i], label, path};
                            this._settings.set_string('paths',
                                serializeList(list));
                        }
                    },
                });
                dlg.open();
            }
        }
    );

    indicatorDescriptor = {
        id: 'pencil',
        displayName: 'Pencil',
        defaultEnabled: true,
        ctor: (opts) => new PencilIndicator(opts),
    };
} catch (_e) {
    // Non-GJS environment (e.g. Node unit tests) — leave stub descriptor.
}
