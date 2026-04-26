import Adw from 'gi://Adw';
import Gdk from 'gi://Gdk';
import Gio from 'gi://Gio';
import GObject from 'gi://GObject';
import Gtk from 'gi://Gtk';
import {ExtensionPreferences}
    from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';
import {setGettext} from './lib/i18n.js';
import {exportSettingsAsObj, importSettingsFromObj, resetAllSettings}
    from './lib/settings.js';

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
