import GObject from 'gi://GObject';
import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {parseList, serializeList} from '../lib/settings.js';
import {buildBrowserArgv, buildMpvArgv, spawnDetached} from '../lib/spawn.js';
import {buildFilmLabel, defaultFilmEntry} from '../lib/film-helpers.js';
import {FilmDialog} from '../ui/film-dialog.js';

function _notify(title, body) {
    try { Main.notify(title, body); } catch (_e) {}
}

export const FilmIndicator = GObject.registerClass(
class FilmIndicator extends PanelMenu.Button {
    _init({extension, openPrefs}) {
        super._init(0.0, 'Stream Deck Film');
        this._extension = extension;
        this._openPrefs = openPrefs;
        this._settings = extension.getSettings();
        this.add_child(new St.Icon({
            icon_name: 'video-x-generic-symbolic',
            style_class: 'system-status-icon',
        }));
        this._sig = this._settings.connect('changed::films',
            () => this._rebuildMenu());
        this._rebuildMenu();
    }

    destroy() {
        if (this._sig) this._settings.disconnect(this._sig);
        super.destroy();
    }

    _rebuildMenu() {
        this.menu.removeAll();
        const films = parseList(this._settings.get_string('films'));
        if (!films.length) {
            this.menu.addMenuItem(new PopupMenu.PopupMenuItem(
                '(no films — use + Add film)', {reactive: false}));
        } else {
            for (const film of films) this.menu.addMenuItem(this._makeRow(film));
        }
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const add = new PopupMenu.PopupMenuItem('+ Add film…');
        add.connect('activate', () => this._openAddDialog());
        this.menu.addMenuItem(add);

        const prefsItem = new PopupMenu.PopupMenuItem('⚙ Open prefs');
        prefsItem.connect('activate', () => this._openPrefs?.());
        this.menu.addMenuItem(prefsItem);
    }

    _makeRow(film) {
        const sub = new PopupMenu.PopupSubMenuMenuItem(buildFilmLabel(film));

        const browserItem = new PopupMenu.PopupMenuItem('▶ Browser');
        browserItem.connect('activate', () => this._launch(film, 'browser'));
        sub.menu.addMenuItem(browserItem);

        const mpvItem = new PopupMenu.PopupMenuItem('▶ mpv');
        mpvItem.connect('activate', () => this._launch(film, 'mpv'));
        sub.menu.addMenuItem(mpvItem);

        const editItem = new PopupMenu.PopupMenuItem('✎ Edit');
        editItem.connect('activate', () => this._editEntry(film));
        sub.menu.addMenuItem(editItem);

        return sub;
    }

    async _launch(film, player) {
        const argv = player === 'mpv'
            ? buildMpvArgv(film.url, film.position || '')
            : buildBrowserArgv(film.url);
        await spawnDetached(argv, {notify: _notify, title: 'Stream Deck'});
    }

    _openAddDialog() {
        const dlg = new FilmDialog({
            title: 'Add film',
            onConfirm: data => {
                const list = parseList(this._settings.get_string('films'));
                list.push(defaultFilmEntry(data));
                this._settings.set_string('films', serializeList(list));
            },
        });
        dlg.open();
    }

    _editEntry(entry) {
        const dlg = new FilmDialog({
            title: 'Edit film',
            entry,
            onConfirm: data => {
                const list = parseList(this._settings.get_string('films'));
                const i = list.findIndex(e => e.id === entry.id);
                if (i >= 0) {
                    list[i] = {...list[i], ...data};
                    this._settings.set_string('films', serializeList(list));
                }
            },
            onDelete: () => {
                const list = parseList(this._settings.get_string('films'))
                    .filter(e => e.id !== entry.id);
                this._settings.set_string('films', serializeList(list));
            },
        });
        dlg.open();
    }
});

export const indicatorDescriptor = {
    id: 'film',
    displayName: 'Film',
    defaultEnabled: true,
    ctor: (opts) => new FilmIndicator(opts),
};
