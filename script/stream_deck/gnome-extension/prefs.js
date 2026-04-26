import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import {ExtensionPreferences}
    from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

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
