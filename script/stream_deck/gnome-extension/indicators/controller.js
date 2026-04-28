import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GObject from 'gi://GObject';
import Soup from 'gi://Soup';
import St from 'gi://St';
import GLib from 'gi://GLib';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {detectStreamDecksGjs} from '../lib/usb.js';
import {makeBadgedIcon} from '../lib/badges.js';
import {parseList} from '../lib/settings.js';
import {buildTerminalArgv, findTerminal, spawnDetached}
    from '../lib/spawn.js';

const GALLERY_PORT = 8042;
const GALLERY_URL = `http://localhost:${GALLERY_PORT}`;
const PROJECT_URL = 'https://github.com/ERPLibre/ERPLibre';
const PROJECT_NAME = 'ERPLibre Stream Deck';

function _notify(title, body) {
    try {
        Main.notify(title, body);
    } catch (e) {
        console.log(`[StreamDeckTiler:controller] notify failed: ${e.message}`);
    }
}

// Unique per module evaluation. Required for the HotReload UUID-rename
// trick: GObject types are process-wide and immutable, so loading the
// same class under a fresh UUID needs a fresh GTypeName.
const _GTYPE_SUFFIX = Math.floor(Math.random() * 1e9).toString(36);

export const ControllerIndicator = GObject.registerClass(
{GTypeName: `SDT_ControllerIndicator_${_GTYPE_SUFFIX}`},
class ControllerIndicator extends PanelMenu.Button {
    _init({extension, iconName = 'input-gaming-symbolic', openPrefs} = {}) {
        super._init(0.0, 'Stream Deck Controller');
        this._extension = extension;
        this._openPrefs = openPrefs;
        this._settings = extension?.getSettings ? extension.getSettings()
            : null;
        this._badged = makeBadgedIcon({St, Gio, Clutter, iconName});
        this.add_child(this._badged.actor);
        this._buildMenu();
        this.menu.connect('open-state-changed', (_menu, isOpen) => {
            if (isOpen) {
                this._refreshGames();
                this._rescanDecks();
            }
        });
        if (this._settings) {
            this._sigBadges = this._settings.connect(
                'changed::enable-icon-badges',
                () => this._refreshBadge());
            this._sigPaths = this._settings.connect(
                'changed::paths',
                () => this._populateGallerySubmenu());
        }
        this._rescanDecks();
    }

    destroy() {
        if (this._settings) {
            for (const k of ['_sigBadges', '_sigPaths']) {
                if (this[k]) this._settings.disconnect(this[k]);
                this[k] = 0;
            }
        }
        super.destroy();
    }

    async _rescanDecks() {
        try {
            const list = await detectStreamDecksGjs();
            this._deckCount = Array.isArray(list) ? list.length : 0;
        } catch (_e) {
            this._deckCount = 0;
        }
        this._refreshBadge();
    }

    _refreshBadge() {
        if (!this._badged) return;
        if (this._settings &&
            !this._settings.get_boolean('enable-icon-badges')) {
            this._badged.setBadges([]);
            return;
        }
        this._badged.setBadges([{count: this._deckCount || 0}]);
    }

    _buildMenu() {
        const about = new PopupMenu.PopupMenuItem('About');
        about.connect('activate', () => {
            try {
                Gio.AppInfo.launch_default_for_uri(PROJECT_URL, null);
            } catch (_e) {
                _notify(PROJECT_NAME, `Open ${PROJECT_URL} for project info.`);
            }
        });
        this.menu.addMenuItem(about);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        this._gallerySection = new PopupMenu.PopupSubMenuMenuItem(
            'Start gallery server…');
        this.menu.addMenuItem(this._gallerySection);
        this._populateGallerySubmenu();

        this._gamesSection = new PopupMenu.PopupSubMenuMenuItem('Games');
        this.menu.addMenuItem(this._gamesSection);
        this._populateGamesPlaceholder('Loading…');

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        const settings = new PopupMenu.PopupMenuItem('Open prefs…');
        settings.connect('activate', () => {
            if (typeof this._openPrefs === 'function') this._openPrefs();
        });
        this.menu.addMenuItem(settings);
    }

    _populateGallerySubmenu() {
        if (!this._gallerySection) return;
        this._gallerySection.menu.removeAll();
        const paths = this._settings
            ? parseList(this._settings.get_string('paths'))
            : [];
        if (!paths.length) {
            this._gallerySection.menu.addMenuItem(
                new PopupMenu.PopupMenuItem(
                    '(no paths configured — add one in pencil prefs)',
                    {reactive: false}));
            return;
        }
        for (const p of paths) {
            const label = p.label && p.label.trim() !== ''
                ? `${p.label} (${p.path})` : p.path;
            const item = new PopupMenu.PopupMenuItem(label);
            item.connect('activate', () => this._launchGalleryAt(p.path));
            this._gallerySection.menu.addMenuItem(item);
        }
    }

    async _launchGalleryAt(cwd) {
        const terminal = await findTerminal();
        if (!terminal) {
            _notify(PROJECT_NAME,
                'No terminal found. Install gnome-terminal, kgx or xterm.');
            return;
        }
        const argv = buildTerminalArgv({
            cwd,
            command:
                'source .venv.erplibre/bin/activate && ' +
                'make streamdeck_gallery',
            terminal,
        });
        spawnDetached(argv, {notify: _notify, title: PROJECT_NAME});
    }

    _populateGamesPlaceholder(label) {
        this._gamesSection.menu.removeAll();
        this._gamesSection.menu.addMenuItem(
            new PopupMenu.PopupMenuItem(label, {reactive: false}));
    }

    _refreshGames() {
        this._populateGamesPlaceholder('Loading…');
        const session = new Soup.Session();
        session.timeout = 3;
        const message = Soup.Message.new('GET', `${GALLERY_URL}/api/games`);
        session.send_and_read_async(
            message, GLib.PRIORITY_DEFAULT, null, (sess, result) => {
                try {
                    const bytes = sess.send_and_read_finish(result);
                    const text = new TextDecoder().decode(bytes.get_data());
                    const games = JSON.parse(text);
                    this._populateGames(Array.isArray(games) ? games : []);
                } catch (_e) {
                    this._populateGamesPlaceholder(
                        'Gallery offline (start gallery_server.py)');
                }
            });
    }

    _populateGames(games) {
        this._gamesSection.menu.removeAll();
        if (!games.length) {
            this._populateGamesPlaceholder('No games found');
            return;
        }
        games.sort((a, b) =>
            (a.name || a.id || '').localeCompare(b.name || b.id || ''));
        for (const g of games) {
            const id = g.id || '';
            const name = g.name || id;
            if (!id) continue;
            const item = new PopupMenu.PopupMenuItem(name);
            item.connect('activate', () => this._launchGame(id));
            this._gamesSection.menu.addMenuItem(item);
        }
    }

    _launchGame(gameId) {
        const session = new Soup.Session();
        session.timeout = 3;
        const message = Soup.Message.new('GET',
            `${GALLERY_URL}/launch/${gameId}`);
        session.send_and_read_async(
            message, GLib.PRIORITY_DEFAULT, null, (sess, result) => {
                try {
                    sess.send_and_read_finish(result);
                } catch (_e) {
                    _notify(PROJECT_NAME,
                        `Could not launch ${gameId}: gallery offline?`);
                }
            });
    }
});

export const indicatorDescriptor = {
    id: 'controller',
    displayName: 'Controller',
    defaultEnabled: true,
    ctor: (opts) => new ControllerIndicator(opts),
};
