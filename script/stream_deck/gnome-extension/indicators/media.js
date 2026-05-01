import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {parseList, serializeList} from '../lib/settings.js';
import {buildBrowserArgv, buildMpvArgv, buildVlcArgv, buildSpotifyArgv,
    formatPosition, spawnDetached} from '../lib/spawn.js';
import {buildMediaLabel, defaultMediaEntry, isSpotifyUrl, normaliseKind,
    nextEpisodeUrl, nextEpisodeLabel, formatLastPlayed,
    sortEntries, filterEntries, formatProgress}
    from '../lib/media-helpers.js';
import {MediaDialog} from '../ui/media-dialog.js';
import {MediaLibraryDialog} from '../ui/media-library-dialog.js';
import {makeBadgedIcon, bindBadgeOrientation, attachHoverTooltip,
    formatBadgeTooltip} from '../lib/badges.js';
import {_} from '../lib/i18n.js';
import {logInfo, logWarn} from '../lib/log.js';
import {writeMpvEntry, deleteMpvEntry, listMpvEntriesSync}
    from '../lib/mpv-state.js';

function _notify(title, body) {
    try { Main.notify(title, body); } catch (_e) {}
}

// See indicators/controller.js for the rationale of the random suffix.
const _GTYPE_SUFFIX = Math.floor(Math.random() * 1e9).toString(36);

export const MediaIndicator = GObject.registerClass(
{GTypeName: `SDT_MediaIndicator_${_GTYPE_SUFFIX}`},
class MediaIndicator extends PanelMenu.Button {
    _init({extension, openPrefs, iconName = 'video-x-generic-symbolic'} = {}) {
        super._init(0.0, 'Stream Deck Media');
        this._extension = extension;
        this._openPrefs = openPrefs;
        this._settings = extension.getSettings();
        this._badged = makeBadgedIcon({St, Gio, Clutter, iconName});
        this.add_child(this._badged.actor);
        this._sig = this._settings.connect('changed::media',
            () => { this._rebuildMenu(); this._refreshBadge(); });
        // Refresh on menu open so the ▶ "playing" indicator picks up
        // mpv state changes without polling.
        this.menu.connect('open-state-changed', (_menu, isOpen) => {
            if (isOpen) this._rebuildMenu();
        });
        this._sigTab = this._settings.connect(
            'changed::media-active-tab',
            () => this._rebuildMenu());
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
        this._rebuildMenu();
        this._refreshBadge();
    }

    destroy() {
        if (this._sig) this._settings.disconnect(this._sig);
        if (this._sigTab) this._settings.disconnect(this._sigTab);
        if (this._sigBadges) this._settings.disconnect(this._sigBadges);
        if (this._sigOrient) this._settings.disconnect(this._sigOrient);
        this._tip?.detach();
        super.destroy();
    }

    _tooltipText() {
        const films = parseList(this._settings.get_string('media'));
        const videos = films.filter(
            f => normaliseKind(f.kind) === 'video').length;
        const audio = films.filter(
            f => normaliseKind(f.kind) === 'audio').length;
        return formatBadgeTooltip([
            {count: videos, label: 'videos'},
            {count: audio,  label: 'audio'},
        ]) || '0 media';
    }

    _refreshBadge() {
        if (!this._badged) return;
        if (!this._settings.get_boolean('enable-icon-badges')) {
            this._badged.setBadges([]);
            return;
        }
        const films = parseList(this._settings.get_string('media'));
        this._badged.setBadges([{count: films.length}]);
    }

    _activeTab() {
        const v = this._settings.get_string('media-active-tab');
        return (v === 'video' || v === 'audio') ? v : 'all';
    }

    _setActiveTab(tab) {
        const next = (tab === 'video' || tab === 'audio') ? tab : 'all';
        if (this._activeTab() === next) return;
        this._settings.set_string('media-active-tab', next);
    }

    _rebuildMenu() {
        this.menu.removeAll();

        // Pin the action buttons at the top so they stay reachable
        // even when the catalogue is long enough to push the
        // bottom of the dropdown past the screen edge. (Wrapping the
        // rows in St.ScrollView caused submenu items to render with
        // unreadable theme colours on some setups, so we keep the
        // standard PopupMenu rendering and just rearrange.)
        const add = new PopupMenu.PopupMenuItem(_('+ Add media…'));
        add.connect('activate', () => this._openAddDialog());
        this.menu.addMenuItem(add);
        const lib = new PopupMenu.PopupMenuItem(_('📚 Open library…'));
        lib.connect('activate', () => this._openLibrary());
        this.menu.addMenuItem(lib);
        const prefsItem = new PopupMenu.PopupMenuItem(_('⚙ Open prefs'));
        prefsItem.connect('activate', () => this._openPrefs?.());
        this.menu.addMenuItem(prefsItem);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        const films = parseList(this._settings.get_string('media'));
        const videos = films.filter(
            f => normaliseKind(f.kind) === 'video');
        const audio = films.filter(
            f => normaliseKind(f.kind) === 'audio');

        // Tabs row — three PopupMenuItems with a leading marker on the
        // active one. Inline St.Buttons inside a PopupMenu swallow
        // keyboard navigation, so we stick with stock items. Override
        // `activate` so clicking a tab swaps the filter without
        // closing the dropdown — the default PopupMenuItem.activate
        // calls itemActivated() which dismisses the menu.
        const tab = this._activeTab();
        const mark = (key) => tab === key ? '● ' : '○ ';
        const makeTab = (key, label) => {
            const item = new PopupMenu.PopupMenuItem(label);
            item.activate = () => this._setActiveTab(key);
            return item;
        };
        this.menu.addMenuItem(makeTab('all',
            `${mark('all')}${_('All')} (${films.length})`));
        this.menu.addMenuItem(makeTab('video',
            `${mark('video')}${_('Films')} (${videos.length})`));
        this.menu.addMenuItem(makeTab('audio',
            `${mark('audio')}${_('Music')} (${audio.length})`));
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        if (!films.length) {
            this.menu.addMenuItem(new PopupMenu.PopupMenuItem(
                _('(no media — use + Add media)'), {reactive: false}));
            return;
        }

        const kindFilter = tab === 'all' ? undefined : tab;
        const visible = filterEntries(films, {kind: kindFilter});
        if (!visible.length) {
            this.menu.addMenuItem(new PopupMenu.PopupMenuItem(
                _('(empty — switch tab or add media)'),
                {reactive: false}));
            return;
        }

        const SECTION_CAP = 5;
        const ALL_CAP = 10;
        const seen = new Set();
        const take = (entries, n) => {
            const out = [];
            for (const e of entries) {
                if (seen.has(e.id)) continue;
                out.push(e);
                if (out.length >= n) break;
            }
            return out;
        };
        const renderSection = (title, entries) => {
            if (!entries.length) return;
            this.menu.addMenuItem(new PopupMenu.PopupMenuItem(
                title, {reactive: false}));
            for (const film of entries) {
                seen.add(film.id);
                this.menu.addMenuItem(this._makeRow(film));
            }
        };

        // Cache the playing-id set for the duration of this rebuild
        // so every row through _makeRow / _isPlaying shares one read
        // of the mpv-state directory instead of re-globbing per row.
        this._playingCache = this._playingIds();
        const playing = visible.filter(e => this._playingCache.has(e.id));
        const recents = sortEntries(
            visible.filter(e => e.last_played), 'last_played');
        const unfinished = filterEntries(visible, {unfinished: true});
        const favourites = sortEntries(
            filterEntries(visible, {favourites: true}), 'last_played');

        renderSection(_('▶ Now playing'), take(playing, SECTION_CAP));
        renderSection(_('⏱ Recents'), take(recents, SECTION_CAP));
        renderSection(_('↻ Continue watching'),
            take(unfinished, SECTION_CAP));
        renderSection(_('★ Favourites'), take(favourites, SECTION_CAP));

        // Fallback "All" section keeps the dropdown useful for fresh
        // catalogues whose entries have no last_played / rating yet.
        // Drops in items not already surfaced in a smart section.
        const remaining = take(sortEntries(visible, 'alpha'), ALL_CAP);
        if (remaining.length) {
            this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
            renderSection(
                _('— All ({n}) —').replace('{n}', visible.length),
                remaining);
            const overflow = visible.length - seen.size;
            if (overflow > 0) {
                const more = new PopupMenu.PopupMenuItem(
                    _('… {n} more in library').replace('{n}', overflow));
                more.connect('activate', () => this._openLibrary());
                this.menu.addMenuItem(more);
            }
        }
    }

    _playingIds() {
        try {
            return new Set(listMpvEntriesSync(Gio, GLib)
                .map(e => e.film_id));
        } catch (_e) { return new Set(); }
    }

    _isPlaying(filmId) {
        if (this._playingCache) return this._playingCache.has(filmId);
        try {
            return listMpvEntriesSync(Gio, GLib).some(
                e => e.film_id === filmId);
        } catch (_e) { return false; }
    }

    _makeRow(film) {
        const playing = this._isPlaying(film.id);
        const prefix = playing ? '▶ ' : '';
        const lastTag = this._lastPlayedTag(film);
        const prog = formatProgress(film.position, film.duration);
        const progTag = prog ? `   ${prog}` : '';
        const sub = new PopupMenu.PopupSubMenuMenuItem(
            `${prefix}${buildMediaLabel(film)}${progTag}${lastTag}`);

        const browserItem = new PopupMenu.PopupMenuItem(_('▶ Browser'));
        browserItem.connect('activate', () => this._launch(film, 'browser'));
        sub.menu.addMenuItem(browserItem);

        const mpvItem = new PopupMenu.PopupMenuItem(_('▶ mpv'));
        mpvItem.connect('activate', () => this._launch(film, 'mpv'));
        sub.menu.addMenuItem(mpvItem);

        const vlcItem = new PopupMenu.PopupMenuItem(_('▶ VLC'));
        vlcItem.connect('activate', () => this._launch(film, 'vlc'));
        sub.menu.addMenuItem(vlcItem);

        if (isSpotifyUrl(film.url)) {
            const spotifyItem = new PopupMenu.PopupMenuItem(_('▶ Spotify'));
            spotifyItem.connect('activate',
                () => this._launch(film, 'spotify'));
            sub.menu.addMenuItem(spotifyItem);
        }

        if (nextEpisodeUrl(film.url)) {
            const nextItem = new PopupMenu.PopupMenuItem(
                _('⏭ Next episode'));
            nextItem.connect('activate',
                () => this._addNextEpisode(film));
            sub.menu.addMenuItem(nextItem);
        }

        const editItem = new PopupMenu.PopupMenuItem(_('✎ Edit'));
        editItem.connect('activate', () => this._editEntry(film));
        sub.menu.addMenuItem(editItem);

        return sub;
    }

    _addNextEpisode(film) {
        const nextUrl = nextEpisodeUrl(film.url);
        if (!nextUrl) return;
        const films = parseList(this._settings.get_string('media'));
        const idx = films.findIndex(f => f.id === film.id);
        const newName = nextEpisodeLabel(film.name, film.url, nextUrl);
        const next = defaultMediaEntry({
            name: newName,
            url: nextUrl,
            episode: '',
            position: '',
            kind: normaliseKind(film.kind),
        });
        // Insert immediately after the source entry so the user sees
        // the new row right below the one they clicked.
        if (idx >= 0) films.splice(idx + 1, 0, next);
        else films.push(next);
        this._settings.set_string('media', serializeList(films));
    }

    async _launch(film, player) {
        // Stamp the click timestamp on the entry so the dropdown
        // surfaces a "📅 last played" line even before the player
        // returns. Captures every click — mpv / VLC / browser /
        // Spotify — since the user's intent is "I started watching
        // this", not "this player actually rendered frames".
        this._stampLastPlayed(film);
        if (player === 'mpv') {
            await this._launchMpvTracked(film);
            return;
        }
        let argv;
        if (player === 'vlc')
            argv = buildVlcArgv(film.url, film.position || '');
        else if (player === 'spotify')
            argv = buildSpotifyArgv(film.url);
        else
            argv = buildBrowserArgv(film.url);
        await spawnDetached(argv, {notify: _notify, title: 'Stream Deck'});
    }

    _lastPlayedTag(film) {
        if (!film?.last_played) return '';
        const raw = formatLastPlayed(film.last_played);
        if (!raw) return '';
        const human = raw === 'today'
            ? _('today')
            : raw === 'yesterday'
                ? _('yesterday')
                : raw;
        return `\n📅 ${human}`;
    }

    _stampLastPlayed(film) {
        if (!this._settings) return;
        const films = parseList(this._settings.get_string('media'));
        const idx = films.findIndex(f => f.id === film.id);
        if (idx < 0) return;
        const cur = films[idx];
        const count = Number.isFinite(cur.play_count) ? cur.play_count : 0;
        films[idx] = {
            ...cur,
            last_played: new Date().toISOString(),
            play_count: count + 1,
        };
        this._settings.set_string('media', serializeList(films));
    }

    async _launchMpvTracked(film) {
        const runtimeDir = GLib.get_user_runtime_dir()
            || GLib.get_tmp_dir();
        // 12 hex chars from urandom-ish via GLib UUID is overkill;
        // a millisecond timestamp + random suffix is plenty for a
        // socket path that lives less than a film viewing.
        const tag = `${Date.now().toString(36)}-`
            + Math.floor(Math.random() * 1e6).toString(36);
        const socketPath = `${runtimeDir}/sdt-mpv-${tag}.sock`;

        const argv = buildMpvArgv(film.url, film.position || '');
        argv.push(`--input-ipc-server=${socketPath}`);
        if (film.name) argv.push(`--title=${film.name}`);

        let proc;
        try {
            proc = Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE);
        } catch (e) {
            _notify('Stream Deck',
                _('mpv spawn failed: {err}').replace('{err}', e.message));
            logWarn('film', `mpv spawn failed: ${e.message}`);
            return;
        }
        const pidStr = proc.get_identifier();
        const pid = parseInt(pidStr, 10) || 0;
        if (!pid) return;

        const entry = {
            pid,
            ipc_socket: socketPath,
            url: film.url,
            title: film.name || film.url,
            film_id: film.id,
            started_at: Date.now(),
        };
        try { await writeMpvEntry(entry); }
        catch (e) { logWarn('film',
            `mpv state write failed: ${e.message || e}`); }
        logInfo('film',
            `mpv pid=${pid} sock=${socketPath} -> ${film.url}`);

        proc.wait_async(null, async (p, res) => {
            try { p.wait_finish(res); } catch (_e) {}
            try { await deleteMpvEntry(pid); } catch (_e) {}
            try { GLib.unlink(socketPath); } catch (_e) {}
            this._updateMpvPosition(film);
            logInfo('film', `mpv pid=${pid} exited`);
        });
    }

    _updateMpvPosition(film) {
        try {
            if (!film?.url || !film?.id) return;
            // mpv hashes the playback URL as upper-case MD5 hex and
            // stores `start=<seconds>` in the watch-later file. Some
            // mpv builds also write `duration=<seconds>`; we capture
            // it when present so the library can render a progress
            // bar. The duration line is optional — leave it empty
            // when missing rather than guessing.
            const hash = GLib.compute_checksum_for_string(
                GLib.ChecksumType.MD5, film.url, -1).toUpperCase();
            const path = `${GLib.get_user_config_dir()}`
                + `/mpv/watch_later/${hash}`;
            if (!GLib.file_test(path, GLib.FileTest.EXISTS)) {
                logInfo('film',
                    `mpv left no watch-later for ${film.url}`);
                return;
            }
            const [ok, contents] = GLib.file_get_contents(path);
            if (!ok) return;
            const text = new TextDecoder().decode(contents);
            const startM = text.match(/^start=([\d.]+)/m);
            const durM = text.match(/^duration=([\d.]+)/m);
            const startSec = startM
                ? Math.floor(parseFloat(startM[1])) : 0;
            const durSec = durM
                ? Math.floor(parseFloat(durM[1])) : 0;
            const list = parseList(this._settings.get_string('media'));
            const i = list.findIndex(e => e.id === film.id);
            if (i < 0) return;
            const next = {...list[i]};
            let changed = false;
            if (Number.isFinite(startSec) && startSec > 0) {
                const pos = formatPosition(startSec);
                if (next.position !== pos) {
                    next.position = pos;
                    changed = true;
                }
            }
            if (Number.isFinite(durSec) && durSec > 0) {
                const dur = formatPosition(durSec);
                if (next.duration !== dur) {
                    next.duration = dur;
                    changed = true;
                }
            }
            if (!changed) return;
            list[i] = next;
            this._settings.set_string('media', serializeList(list));
            logInfo('film',
                `mpv state updated for ${film.id} pos=${next.position}`
                + ` dur=${next.duration || '-'}`);
        } catch (e) {
            logWarn('film',
                `position update failed: ${e.message || e}`);
        }
    }

    _openAddDialog() {
        const dlg = new MediaDialog({
            title: 'Add media',
            onConfirm: data => {
                const list = parseList(this._settings.get_string('media'));
                list.push(defaultMediaEntry(data));
                this._settings.set_string('media', serializeList(list));
            },
        });
        dlg.open();
    }

    _editEntry(entry) {
        const dlg = new MediaDialog({
            title: 'Edit media',
            entry,
            onConfirm: data => {
                const list = parseList(this._settings.get_string('media'));
                const i = list.findIndex(e => e.id === entry.id);
                if (i >= 0) {
                    list[i] = {...list[i], ...data};
                    this._settings.set_string('media', serializeList(list));
                }
            },
            onDelete: () => {
                const list = parseList(this._settings.get_string('media'))
                    .filter(e => e.id !== entry.id);
                this._settings.set_string('media', serializeList(list));
            },
        });
        dlg.open();
    }

    _deleteEntry(entry) {
        const list = parseList(this._settings.get_string('media'))
            .filter(e => e.id !== entry.id);
        this._settings.set_string('media', serializeList(list));
    }

    _openLibrary() {
        const dlg = new MediaLibraryDialog({
            settings: this._settings,
            onLaunch: (entry, player) => this._launch(entry, player),
            onEdit: (entry) => this._editEntry(entry),
            onDelete: (entry) => this._deleteEntry(entry),
        });
        dlg.open();
    }
});

export const indicatorDescriptor = {
    id: 'media',
    displayName: 'Media',
    defaultEnabled: true,
    ctor: (opts) => new MediaIndicator(opts),
};
