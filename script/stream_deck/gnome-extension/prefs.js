import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import Gtk from 'gi://Gtk';
import {ExtensionPreferences}
    from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';
import {setGettext} from './lib/i18n.js';

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

        window.add(buttonsPage);
        window.add(this._buildPencilPage(settings));
        window.add(this._buildFilmPage(settings));
        window.add(this._buildErpLibrePage(settings));
        window.add(this._buildNetworkPage(settings));
        window.add(this._buildDevicePage(settings));
        window.add(this._buildThemingPage(settings));
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
