import Adw from 'gi://Adw';
import Gdk from 'gi://Gdk';
import Gio from 'gi://Gio';
import GObject from 'gi://GObject';
import Gtk from 'gi://Gtk';
import {ExtensionPreferences}
    from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';
import {setGettext} from './lib/i18n.js';
import {exportSettingsAsObj, importSettingsFromObj, resetAllSettings,
    parseList, serializeList}
    from './lib/settings.js';
import {readLogTail, clearLog} from './lib/log.js';
import {defaultMediaEntry as defaultFilmEntry}
    from './lib/media-helpers.js';

const INDICATORS = [
    {id: 'controller', label: 'Controller'},
    {id: 'pencil',     label: 'Pencil'},
    {id: 'film',       label: 'Film'},
    {id: 'erplibre',   label: 'ERPLibre'},
    {id: 'network',    label: 'Network'},
    {id: 'device',     label: 'Device'},
];

export default class StreamDeckTilerPrefs extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();
        setGettext((s) => this.gettext ? this.gettext(s) : s);

        const buttonsPage = new Adw.PreferencesPage({
            title: 'Buttons',
            icon_name: 'view-grid-symbolic',
        });

        const togglesGroup = new Adw.PreferencesGroup({
            title: 'Indicators',
            description: 'Toggle each panel button on or off.',
        });
        for (const ind of INDICATORS) {
            const row = new Adw.SwitchRow({
                title: ind.label,
                subtitle: `Show the ${ind.label.toLowerCase()} indicator in the top bar`,
            });
            settings.bind(`enable-${ind.id}`, row, 'active',
                Gio.SettingsBindFlags.DEFAULT);
            togglesGroup.add(row);
        }
        buttonsPage.add(togglesGroup);

        const orderGroup = new Adw.PreferencesGroup({
            title: 'Order in top bar',
            description: 'Drag rows to change the left-to-right order.',
        });
        buttonsPage.add(orderGroup);

        const list = new Gtk.ListBox({selection_mode: Gtk.SelectionMode.NONE});
        orderGroup.add(list);
        this._refreshOrderList(list, settings);

        window.add(buttonsPage);
        window.add(this._buildPencilPage(settings));
        window.add(this._buildFilmPage(settings));
        window.add(this._buildErpLibrePage(settings));
        window.add(this._buildNetworkPage(settings));
        window.add(this._buildDevicePage(settings));
        window.add(this._buildThemingPage(settings));
        window.add(this._buildAdvancedPage(settings));
        window.add(this._buildSyncPage(settings));
        window.add(this._buildLogPage(settings));
        window.add(this._buildHelpPage());
        window.add(this._buildAboutPage());
    }

    _buildAboutPage() {
        const page = new Adw.PreferencesPage({
            title: 'About', icon_name: 'dialog-information-symbolic',
        });

        const erp = new Adw.PreferencesGroup({
            title: 'ERPLibre',
            description:
                'Community fork of Odoo Community Edition under '
                + 'AGPL-3.0+. Supports Odoo 12 through 18 (default 18.0) '
                + 'and ships the Stream Deck tooling shown in this '
                + 'extension.',
        });
        page.add(erp);
        erp.add(this._linkRow('Project page', 'github.com/ERPLibre/ERPLibre',
            'https://github.com/ERPLibre/ERPLibre'));
        erp.add(this._linkRow('Documentation',
            'erplibre.readthedocs.io',
            'https://erplibre.readthedocs.io'));
        erp.add(this._linkRow('Issue tracker',
            'github.com/ERPLibre/ERPLibre/issues',
            'https://github.com/ERPLibre/ERPLibre/issues'));

        const tlc = new Adw.PreferencesGroup({
            title: 'TechnoLibre',
            description:
                'Quebec-based open-source company maintaining ERPLibre '
                + 'and the Stream Deck integration. Sponsors community '
                + 'development and offers commercial support.',
        });
        page.add(tlc);
        tlc.add(this._linkRow('Website', 'technolibre.ca',
            'https://technolibre.ca'));
        tlc.add(this._linkRow('Contact', 'mathben@technolibre.ca',
            'mailto:mathben@technolibre.ca'));

        const plugin = new Adw.PreferencesGroup({
            title: 'Stream Deck integration',
            description:
                'GNOME shell extension + Python deck driver under '
                + 'script/stream_deck/. Hooks Claude sessions, mpv, VLC, '
                + 'gallery server and Mutter window tiling onto the '
                + 'Elgato hardware.',
        });
        page.add(plugin);
        plugin.add(this._linkRow('Source folder',
            'script/stream_deck/gnome-extension/',
            'https://github.com/ERPLibre/ERPLibre/tree/master/'
                + 'script/stream_deck/gnome-extension'));
        plugin.add(this._linkRow('License', 'AGPL-3.0+',
            'https://www.gnu.org/licenses/agpl-3.0.html'));

        return page;
    }

    _linkRow(title, subtitle, uri) {
        const row = new Adw.ActionRow({title, subtitle});
        const btn = new Gtk.LinkButton({
            uri,
            label: 'Open',
            valign: Gtk.Align.CENTER,
        });
        row.add_suffix(btn);
        row.set_activatable_widget(btn);
        return row;
    }

    _buildHelpPage() {
        const page = new Adw.PreferencesPage({
            title: 'Help', icon_name: 'help-about-symbolic',
        });

        const badges = new Adw.PreferencesGroup({
            title: 'Badge colours',
            description: 'Counts shown beside each top-bar indicator.',
        });
        page.add(badges);
        for (const [title, subtitle] of [
            ['● Blue — catalogue count',
                'Paths, decks, instances or media stored in the indicator.'],
            ['● Green — active session',
                'Alive Claude session: SessionStart or UserPromptSubmit '
                + 'fired and the session is between turns.'],
            ['● Cyan — computing',
                'PreToolUse hook fired — Claude is running a tool.'],
            ['● Yellow — awaiting answer',
                'Stop hook fired — Claude finished its turn and waits '
                + 'for the next prompt.'],
            ['● Red — needs attention',
                'Notification hook fired — Claude needs explicit input '
                + '(approval, missing tool, etc.).'],
        ]) {
            badges.add(new Adw.ActionRow({title, subtitle}));
        }

        const hooks = new Adw.PreferencesGroup({
            title: 'Claude hooks',
            description:
                'How the Claude session badges stay in sync with the '
                + 'agent. Install them once with make claude_install_hooks.',
        });
        page.add(hooks);
        for (const [title, subtitle] of [
            ['SessionStart / UserPromptSubmit',
                'Marks the session as active (green) and captures the '
                + 'focused window id for terminal focus + Set window.'],
            ['PreToolUse',
                'Marks the session as computing (cyan).'],
            ['Stop',
                'Marks the session as awaiting answer (yellow).'],
            ['Notification',
                'Marks the session as needs attention (red) and '
                + 'optionally fires a desktop notification.'],
            ['SessionEnd',
                'Removes the state file when Claude exits cleanly.'],
            ['Ctrl+C interrupt',
                'Treated like Stop — the session goes back to '
                + 'awaiting answer instead of staying computing.'],
        ]) {
            hooks.add(new Adw.ActionRow({title, subtitle}));
        }

        const interactions = new Adw.PreferencesGroup({
            title: 'Indicator interactions',
            description: 'Mouse shortcuts on the top-bar icons.',
        });
        page.add(interactions);
        for (const [title, subtitle] of [
            ['Hover',
                'Shows a tooltip with the per-kind breakdown.'],
            ['Click on a pencil count badge',
                'Opens the dropdown filtered by that kind '
                + '(active / awaiting / notify). A × Clear row at the '
                + 'top resets the filter.'],
            ['Click on a session row',
                'Focuses the terminal window saved at SessionStart.'],
            ['Set window…',
                'Re-saves the focused window for that session if the '
                + 'terminal was reopened or moved.'],
        ]) {
            interactions.add(new Adw.ActionRow({title, subtitle}));
        }

        const tiler = new Adw.PreferencesGroup({
            title: 'Tiling on the deck',
            description:
                'TILE button on the deck enters a corner-pick mode.',
        });
        page.add(tiler);
        for (const [title, subtitle] of [
            ['Pick two corners',
                'First press selects the top-left of the target tile, '
                + 'second press selects the bottom-right. The focused '
                + 'window is moved + resized via the Mutter D-Bus API.'],
            ['Auto-cancel after 5 s',
                'If the second corner is never picked, tiling mode '
                + 'returns to idle without touching the focused window.'],
        ]) {
            tiler.add(new Adw.ActionRow({title, subtitle}));
        }

        return page;
    }

    _buildSyncPage(settings) {
        const page = new Adw.PreferencesPage({
            title: 'Sync', icon_name: 'folder-remote-symbolic',
        });
        const grp = new Adw.PreferencesGroup({title: 'Git sync'});
        page.add(grp);

        const enRow = new Adw.SwitchRow({title: 'Enable git sync'});
        settings.bind('enable-git-sync', enRow, 'active',
            Gio.SettingsBindFlags.DEFAULT);
        grp.add(enRow);

        const pathRow = new Adw.EntryRow({
            title: 'Sync repo path (must contain a git repo)'});
        settings.bind('git-sync-path', pathRow, 'text',
            Gio.SettingsBindFlags.DEFAULT);
        grp.add(pathRow);

        const warn = new Adw.ActionRow({
            title: 'Last write wins on conflict.',
            subtitle: 'Manual merges may be required.',
        });
        grp.add(warn);

        return page;
    }

    _buildAdvancedPage(settings) {
        const page = new Adw.PreferencesPage({
            title: 'Advanced', icon_name: 'document-properties-symbolic',
        });
        const grp = new Adw.PreferencesGroup({title: 'Backup & restore'});
        page.add(grp);

        const exp = new Adw.ActionRow({title: 'Export settings…'});
        const expBtn = new Gtk.Button({label: 'Export', valign: Gtk.Align.CENTER});
        expBtn.connect('clicked', () => this._exportSettings(settings, page));
        exp.add_suffix(expBtn);
        grp.add(exp);

        const imp = new Adw.ActionRow({title: 'Import settings…'});
        const impBtn = new Gtk.Button({label: 'Import', valign: Gtk.Align.CENTER});
        impBtn.connect('clicked', () => this._importSettings(settings, page));
        imp.add_suffix(impBtn);
        grp.add(imp);

        const rst = new Adw.ActionRow({title: 'Reset to defaults'});
        const rstBtn = new Gtk.Button({label: 'Reset',
            valign: Gtk.Align.CENTER, css_classes: ['destructive-action']});
        rstBtn.connect('clicked', () => this._resetAll(settings));
        rst.add_suffix(rstBtn);
        grp.add(rst);

        return page;
    }

    _exportSettings(settings, parent) {
        const dlg = new Gtk.FileChooserNative({
            title: 'Export settings', action: Gtk.FileChooserAction.SAVE,
            accept_label: 'Save', cancel_label: 'Cancel',
            modal: true, transient_for: parent.get_root?.(),
        });
        dlg.set_current_name('streamdeck-tiler-settings.json');
        dlg.connect('response', (_d, response) => {
            if (response === Gtk.ResponseType.ACCEPT) {
                const file = dlg.get_file();
                const obj = exportSettingsAsObj(settings);
                file.replace_contents(
                    new TextEncoder().encode(JSON.stringify(obj, null, 2)),
                    null, false, Gio.FileCreateFlags.REPLACE_DESTINATION, null);
            }
            dlg.destroy();
        });
        dlg.show();
    }

    _importSettings(settings, parent) {
        const dlg = new Gtk.FileChooserNative({
            title: 'Import settings', action: Gtk.FileChooserAction.OPEN,
            accept_label: 'Open', cancel_label: 'Cancel',
            modal: true, transient_for: parent.get_root?.(),
        });
        dlg.connect('response', async (_d, response) => {
            if (response === Gtk.ResponseType.ACCEPT) {
                const file = dlg.get_file();
                const [, contents] = file.load_contents(null);
                const text = new TextDecoder().decode(contents);
                try {
                    const obj = JSON.parse(text);
                    await importSettingsFromObj(settings, obj);
                } catch (_e) {}
            }
            dlg.destroy();
        });
        dlg.show();
    }

    _resetAll(settings) {
        resetAllSettings(settings);
    }

    _refreshOrderList(list, settings) {
        const known = new Set(['controller','pencil','film','erplibre',
            'network','device']);
        let order = settings.get_strv('button-order')
            .filter(id => known.has(id));
        for (const id of known)
            if (!order.includes(id)) order.push(id);

        while (list.get_first_child())
            list.remove(list.get_first_child());

        for (const id of order) {
            const row = new Gtk.ListBoxRow({name: id});
            const lbl = new Gtk.Label({
                label: id,
                xalign: 0,
                margin_start: 8,
                margin_end: 8,
                margin_top: 6,
                margin_bottom: 6,
            });
            row.set_child(lbl);

            // Drag source
            const src = new Gtk.DragSource();
            src.connect('prepare',
                () => Gdk.ContentProvider.new_for_value(id));
            row.add_controller(src);

            // Drop target
            const tgt = new Gtk.DropTarget({
                actions: Gdk.DragAction.MOVE,
                formats: Gdk.ContentFormats.new_for_gtype(GObject.TYPE_STRING),
            });
            tgt.connect('drop', (_t, value) => {
                if (typeof value !== 'string') return false;
                const fromIdx = order.indexOf(value);
                const toIdx = order.indexOf(id);
                if (fromIdx === -1 || toIdx === -1 || fromIdx === toIdx)
                    return false;
                order.splice(fromIdx, 1);
                order.splice(toIdx, 0, value);
                settings.set_strv('button-order', order);
                this._refreshOrderList(list, settings);
                return true;
            });
            row.add_controller(tgt);

            list.append(row);
        }
    }

    _buildThemingPage(settings) {
        const page = new Adw.PreferencesPage({
            title: 'Theming', icon_name: 'preferences-color-symbolic',
        });

        const badgeGroup = new Adw.PreferencesGroup({
            title: 'Badges',
            description:
                'Count badges shown beside each top-bar indicator icon.',
        });
        page.add(badgeGroup);

        const enableRow = new Adw.SwitchRow({
            title: 'Show count badges',
            subtitle:
                'Display the number of items beside each indicator icon.',
        });
        settings.bind('enable-icon-badges', enableRow, 'active',
            Gio.SettingsBindFlags.DEFAULT);
        badgeGroup.add(enableRow);

        const orientRow = new Adw.ComboRow({
            title: 'Stack direction',
            subtitle:
                'Vertical: stack beside icon, up to 3, centered when alone.\n'
                + 'Horizontal: single row beside icon.',
        });
        const orientModel = new Gtk.StringList();
        orientModel.append('Vertical');
        orientModel.append('Horizontal');
        orientRow.set_model(orientModel);
        const ORIENTATIONS = ['vertical', 'horizontal'];
        const _applyOrient = () => {
            const value = settings.get_string('badge-orientation');
            const idx = Math.max(0, ORIENTATIONS.indexOf(value));
            if (orientRow.get_selected() !== idx) orientRow.set_selected(idx);
        };
        _applyOrient();
        orientRow.connect('notify::selected', () => {
            const value = ORIENTATIONS[orientRow.get_selected()] || 'vertical';
            if (settings.get_string('badge-orientation') !== value)
                settings.set_string('badge-orientation', value);
        });
        settings.connect('changed::badge-orientation', _applyOrient);
        badgeGroup.add(orientRow);

        const group = new Adw.PreferencesGroup({title: 'Icon overrides'});
        page.add(group);

        const indicators = [
            ['controller', 'input-gaming-symbolic'],
            ['pencil',     'document-edit-symbolic'],
            ['film',       'video-x-generic-symbolic'],
            ['erplibre',   'network-server-symbolic'],
            ['network',    'network-wired-symbolic'],
            ['device',     'input-tablet-symbolic'],
        ];

        for (const [id, defaultIcon] of indicators) {
            const row = new Adw.EntryRow({
                title: id,
                text: this._currentOverride(settings, id) || defaultIcon,
            });
            row.connect('changed', () => this._setOverride(settings, id,
                row.get_text()));
            group.add(row);
        }
        return page;
    }

    _currentOverride(settings, id) {
        try {
            const obj = JSON.parse(
                settings.get_string('icon-overrides') || '{}');
            return obj[id] || '';
        } catch (_e) { return ''; }
    }

    _setOverride(settings, id, value) {
        let obj = {};
        try {
            obj = JSON.parse(settings.get_string('icon-overrides') || '{}');
        } catch (_e) {}
        if (value && value.trim() !== '') obj[id] = value.trim();
        else delete obj[id];
        settings.set_string('icon-overrides', JSON.stringify(obj));
    }

    _buildDevicePage(settings) {
        const page = new Adw.PreferencesPage({
            title: 'Device', icon_name: 'input-tablet-symbolic',
        });
        const opts = new Adw.PreferencesGroup({title: 'Options'});
        const refreshRow = new Adw.SpinRow({
            title: 'Auto-refresh (seconds, 0 = off)',
            adjustment: new Gtk.Adjustment({lower: 0, upper: 86400,
                step_increment: 60}),
        });
        settings.bind('device-auto-refresh-sec', refreshRow, 'value',
            Gio.SettingsBindFlags.DEFAULT);
        opts.add(refreshRow);
        page.add(opts);
        return page;
    }

    _buildNetworkPage(settings) {
        const page = new Adw.PreferencesPage({
            title: 'Network', icon_name: 'network-wired-symbolic',
        });
        const opts = new Adw.PreferencesGroup({title: 'Options'});
        const userRow = new Adw.EntryRow({title: 'SSH user (empty = $USER)'});
        settings.bind('network-ssh-user', userRow, 'text',
            Gio.SettingsBindFlags.DEFAULT);
        opts.add(userRow);
        const sshRow = new Adw.SwitchRow({title: 'Read ~/.ssh/config'});
        settings.bind('network-read-ssh-config', sshRow, 'active',
            Gio.SettingsBindFlags.DEFAULT);
        opts.add(sshRow);
        const nmapRow = new Adw.SwitchRow({title: 'Use nmap if available'});
        settings.bind('network-use-nmap', nmapRow, 'active',
            Gio.SettingsBindFlags.DEFAULT);
        opts.add(nmapRow);
        const refreshRow = new Adw.SpinRow({
            title: 'Auto-refresh (seconds, 0 = off)',
            adjustment: new Gtk.Adjustment({lower: 0, upper: 86400,
                step_increment: 60}),
        });
        settings.bind('network-auto-refresh-sec', refreshRow, 'value',
            Gio.SettingsBindFlags.DEFAULT);
        opts.add(refreshRow);
        page.add(opts);

        const cidrsGroup = new Adw.PreferencesGroup({
            title: 'CIDR ranges',
            description: 'Empty list = auto-detect. Edit via dconf-editor.',
        });
        page.add(cidrsGroup);
        return page;
    }

    _buildErpLibrePage(settings) {
        const page = new Adw.PreferencesPage({
            title: 'ERPLibre', icon_name: 'network-server-symbolic',
        });
        const detect = new Adw.PreferencesGroup({title: 'Local detection'});
        const autoRow = new Adw.SwitchRow({
            title: 'Auto-detect local instances',
        });
        settings.bind('erplibre-auto-detect', autoRow, 'active',
            Gio.SettingsBindFlags.DEFAULT);
        detect.add(autoRow);
        const patternRow = new Adw.EntryRow({title: 'Local search pattern'});
        settings.bind('erplibre-local-pattern', patternRow, 'text',
            Gio.SettingsBindFlags.DEFAULT);
        detect.add(patternRow);
        page.add(detect);

        const remotes = new Adw.PreferencesGroup({
            title: 'Remote instances',
            description: 'Edit via the Add instance dialog from the panel button.',
        });
        page.add(remotes);
        return page;
    }

    _buildFilmPage(settings) {
        const page = new Adw.PreferencesPage({
            title: 'Film', icon_name: 'video-x-generic-symbolic',
        });
        const group = new Adw.PreferencesGroup({
            title: 'Films',
            description: 'Edit via the Add film dialog from the panel button.',
        });
        page.add(group);

        const importGroup = new Adw.PreferencesGroup({
            title: 'Import from Firefox',
            description:
                'Scan every running Firefox profile\'s open tabs and '
                + 'add YouTube URLs as new film entries '
                + '(requires python3-lz4).',
        });
        const importRow = new Adw.ActionRow({
            title: 'Import YouTube tabs',
            subtitle: 'Click to scan now',
        });
        const importBtn = new Gtk.Button({
            label: 'Import',
            valign: Gtk.Align.CENTER,
            css_classes: ['suggested-action'],
        });
        importBtn.connect('clicked',
            () => this._runFirefoxImport(settings, importBtn));
        importRow.add_suffix(importBtn);
        importGroup.add(importRow);
        page.add(importGroup);
        return page;
    }

    _runFirefoxImport(settings, button) {
        const ext = this.dir?.get_path?.()
            || this.metadata?.path
            || this.path
            || '.';
        const helper = `${ext}/scripts/firefox_youtube_tabs.py`;
        button.set_sensitive(false);
        button.set_label('Scanning…');
        try {
            const proc = Gio.Subprocess.new(
                ['python3', helper],
                Gio.SubprocessFlags.STDOUT_PIPE
                    | Gio.SubprocessFlags.STDERR_PIPE);
            proc.communicate_utf8_async(null, null, (p, res) => {
                let stdout = '', stderr = '', ok = true;
                try {
                    [, stdout, stderr] = p.communicate_utf8_finish(res);
                    ok = p.get_successful();
                } catch (e) {
                    ok = false;
                    stderr = e.message || String(e);
                }
                this._applyFirefoxImport(settings, button,
                    ok, stdout, stderr);
            });
        } catch (e) {
            button.set_sensitive(true);
            button.set_label('Import');
            this._showImportToast(button,
                `Spawn failed: ${e.message || e}`);
        }
    }

    _applyFirefoxImport(settings, button, ok, stdout, stderr) {
        button.set_sensitive(true);
        button.set_label('Import');
        if (!ok) {
            this._showImportToast(button,
                `Helper failed: ${(stderr || '').slice(0, 200)}`);
            return;
        }
        let entries;
        try {
            entries = JSON.parse(stdout || '[]');
        } catch (_e) {
            this._showImportToast(button,
                'Helper output not JSON — see prefs Log');
            return;
        }
        if (!Array.isArray(entries) || !entries.length) {
            this._showImportToast(button,
                stderr.includes('python3-lz4 not installed')
                    ? 'Install python3-lz4: sudo apt install python3-lz4'
                    : 'No YouTube tabs found in Firefox session.');
            return;
        }
        const films = parseList(settings.get_string('media'));
        const existing = new Set(films.map(f => (f.url || '').trim()));
        let added = 0;
        for (const e of entries) {
            const url = String(e.url || '').trim();
            if (!url || existing.has(url)) continue;
            const name = String(e.title || url).slice(0, 80);
            films.push(defaultFilmEntry({name, url}));
            existing.add(url);
            added += 1;
        }
        if (added > 0) {
            settings.set_string('media', serializeList(films));
        }
        const skipped = entries.length - added;
        this._showImportToast(button,
            `Imported ${added} film${added === 1 ? '' : 's'}`
            + (skipped > 0 ? ` (${skipped} duplicate${skipped === 1
                ? '' : 's'} skipped)` : ''));
    }

    _showImportToast(button, message) {
        // Walk up to find the Adw.ToastOverlay or the prefs window
        // (which has add_toast on its child PreferencesWindow).
        let widget = button;
        while (widget) {
            if (typeof widget.add_toast === 'function') {
                widget.add_toast(new Adw.Toast({title: message,
                    timeout: 5}));
                return;
            }
            widget = widget.get_parent ? widget.get_parent() : null;
        }
        // Fallback: log to stderr; user can also see in Activity Log.
        console.log(`[StreamDeckTiler:prefs] ${message}`);
    }

    _buildLogPage(settings) {
        const page = new Adw.PreferencesPage({
            title: 'Log',
            icon_name: 'document-properties-symbolic',
        });
        const group = new Adw.PreferencesGroup({
            title: 'Recent activity',
            description: 'Last 200 entries from '
                + '$XDG_STATE_HOME/streamdeck-tiler/log.jsonl',
        });

        const buf = new Gtk.TextBuffer();
        const view = new Gtk.TextView({
            buffer: buf,
            editable: false,
            monospace: true,
            wrap_mode: Gtk.WrapMode.WORD_CHAR,
            top_margin: 6, bottom_margin: 6,
            left_margin: 6, right_margin: 6,
        });
        const scroll = new Gtk.ScrolledWindow({
            hexpand: true, vexpand: true,
            min_content_height: 320,
            child: view,
        });

        const refreshLog = async () => {
            try {
                const entries = await readLogTail(200);
                if (!entries.length) {
                    buf.set_text('(empty)', -1);
                    return;
                }
                const text = entries.map(e => {
                    const t = new Date(e.ts || 0).toLocaleString();
                    return `${t}  ${(e.level || '').padEnd(5)}  ${e.source}: `
                        + `${e.message}`;
                }).join('\n');
                buf.set_text(text, -1);
                const end = buf.get_end_iter();
                view.scroll_to_iter(end, 0, false, 0, 0);
            } catch (e) {
                buf.set_text(`Failed to read log: ${e.message || e}`, -1);
            }
        };

        const row = new Adw.ActionRow({title: 'Activity log'});
        const refreshBtn = new Gtk.Button({
            label: 'Refresh',
            valign: Gtk.Align.CENTER,
        });
        refreshBtn.connect('clicked', () => refreshLog());
        const clearBtn = new Gtk.Button({
            label: 'Clear',
            valign: Gtk.Align.CENTER,
            css_classes: ['destructive-action'],
        });
        clearBtn.connect('clicked', async () => {
            await clearLog();
            await refreshLog();
        });
        row.add_suffix(refreshBtn);
        row.add_suffix(clearBtn);
        group.add(row);

        const viewerGroup = new Adw.PreferencesGroup();
        viewerGroup.add(scroll);

        page.add(group);
        page.add(viewerGroup);

        // Initial fill on first display.
        refreshLog();
        return page;
    }

    _buildPencilPage(settings) {
        const page = new Adw.PreferencesPage({
            title: 'Pencil',
            icon_name: 'document-edit-symbolic',
        });
        const cmdGroup = new Adw.PreferencesGroup({
            title: 'Default command',
        });
        const cmdRow = new Adw.EntryRow({
            title: 'Default claude command',
        });
        settings.bind('terminal-claude-cmd', cmdRow, 'text',
            Gio.SettingsBindFlags.DEFAULT);
        cmdGroup.add(cmdRow);
        page.add(cmdGroup);

        const pathsGroup = new Adw.PreferencesGroup({
            title: 'Paths',
            description:
                'Edit via the Add path dialog from the panel button.',
        });
        page.add(pathsGroup);
        return page;
    }
}
