import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';
import {ModalDialog} from 'resource:///org/gnome/shell/ui/modalDialog.js';

import {parseList, serializeList} from '../lib/settings.js';
import {buildMediaLabel, normaliseKind, formatLastPlayed,
    sortEntries, filterEntries, groupBy, formatProgress, isSpotifyUrl}
    from '../lib/media-helpers.js';
import {_} from '../lib/i18n.js';

// See indicators/controller.js for the rationale of the random suffix.
const _GTYPE_SUFFIX = Math.floor(Math.random() * 1e9).toString(36);

const _SORT_LABELS = [
    ['last_played', () => _('Last played')],
    ['alpha',       () => _('A → Z')],
    ['play_count',  () => _('Most played')],
    ['rating',      () => _('Rating')],
    ['added',       () => _('Recently added')],
];

const _GROUP_LABELS = [
    ['none',   () => _('No group')],
    ['artist', () => _('Artist')],
    ['album',  () => _('Album')],
    ['genre',  () => _('Genre')],
    ['year',   () => _('Year')],
];

const _TAB_LABELS = [
    ['all',   () => _('All')],
    ['video', () => _('Films')],
    ['audio', () => _('Music')],
];

export const MediaLibraryDialog = GObject.registerClass(
{GTypeName: `SDT_MediaLibraryDialog_${_GTYPE_SUFFIX}`},
class MediaLibraryDialog extends ModalDialog {
    _init({settings, onLaunch, onEdit, onDelete} = {}) {
        super._init({styleClass: 'streamdeck-tiler-dialog'});
        this._settings = settings;
        this._onLaunch = onLaunch;
        this._onEdit = onEdit;
        this._onDelete = onDelete;

        // Track collapsed group keys for the lifetime of the dialog —
        // we want users to fold an artist heading and have it stay
        // folded as they tweak the search box. Not persisted across
        // openings on purpose.
        this._collapsed = new Set();
        this._selectedId = null;
        this._query = '';
        this._unwatched = false;
        this._unfinished = false;
        this._favourites = false;
        // Flat list of entry ids currently visible in the list pane,
        // in render order. Used by ↑/↓ keys to walk selection without
        // a tree traversal. Rebuilt by _renderList.
        this._visibleIds = [];

        const root = new St.BoxLayout({vertical: false,
            style: 'spacing: 12px; min-width: 900px; min-height: 540px;'});
        this.contentLayout.add_child(root);

        root.add_child(this._buildSidebar());
        root.add_child(this._buildList());
        root.add_child(this._buildDetail());

        this.setButtons([{
            label: _('Close'), action: () => this.close(),
            key: Clutter.KEY_Escape, default: true,
        }]);

        this._sigMedia = this._settings.connect('changed::media',
            () => this._render());
        this.connect('key-press-event',
            (_a, ev) => this._onKeyPress(ev));
        this._render();
    }

    _onKeyPress(event) {
        const sym = event.get_key_symbol();
        // While the user is typing in the search entry, only Escape
        // is intercepted (already wired through setButtons). Anything
        // else propagates so backspace etc. still works.
        const focused = global.stage?.get_key_focus?.();
        const inSearch = focused
            && (focused === this._searchEntry
                || focused === this._searchEntry?.clutter_text);
        if (inSearch) return Clutter.EVENT_PROPAGATE;

        if (sym === Clutter.KEY_slash) {
            this._searchEntry.grab_key_focus();
            return Clutter.EVENT_STOP;
        }
        if (sym === Clutter.KEY_Up) {
            this._moveSelection(-1);
            return Clutter.EVENT_STOP;
        }
        if (sym === Clutter.KEY_Down) {
            this._moveSelection(+1);
            return Clutter.EVENT_STOP;
        }
        if (sym === Clutter.KEY_Return || sym === Clutter.KEY_KP_Enter) {
            const e = this._selectedEntry();
            if (e) this._onLaunch?.(e, 'mpv');
            return Clutter.EVENT_STOP;
        }
        if (sym === Clutter.KEY_Delete) {
            const e = this._selectedEntry();
            if (e) {
                this._onDelete?.(e);
                this._selectedId = null;
                this._render();
            }
            return Clutter.EVENT_STOP;
        }
        if (sym >= Clutter.KEY_0 && sym <= Clutter.KEY_5) {
            const n = sym - Clutter.KEY_0;
            const e = this._selectedEntry();
            if (e) this._setRating(e, n);
            return Clutter.EVENT_STOP;
        }
        return Clutter.EVENT_PROPAGATE;
    }

    _moveSelection(delta) {
        if (!this._visibleIds.length) return;
        const cur = this._visibleIds.indexOf(this._selectedId);
        let next;
        if (cur < 0) {
            next = delta > 0 ? 0 : this._visibleIds.length - 1;
        } else {
            next = cur + delta;
            if (next < 0) next = 0;
            if (next >= this._visibleIds.length)
                next = this._visibleIds.length - 1;
        }
        this._selectedId = this._visibleIds[next];
        this._renderList();
        this._renderDetail();
    }

    close() {
        if (this._sigMedia) {
            this._settings.disconnect(this._sigMedia);
            this._sigMedia = 0;
        }
        super.close();
    }

    // ---------------------------------------------------------------
    // Sidebar
    // ---------------------------------------------------------------

    _buildSidebar() {
        const side = new St.BoxLayout({vertical: true,
            style: 'spacing: 10px; min-width: 200px;'});

        side.add_child(new St.Label({text: _('Tab'),
            style: 'font-weight: bold;'}));
        side.add_child(this._buildSegmentedRow(_TAB_LABELS,
            () => this._activeTab(),
            (v) => this._settings.set_string('media-active-tab', v)));

        side.add_child(new St.Label({text: _('Group by'),
            style: 'font-weight: bold; padding-top: 6px;'}));
        side.add_child(this._buildSegmentedColumn(_GROUP_LABELS,
            () => this._groupBy(),
            (v) => this._settings.set_string('media-group-by', v)));

        side.add_child(new St.Label({text: _('Sort by'),
            style: 'font-weight: bold; padding-top: 6px;'}));
        side.add_child(this._buildSegmentedColumn(_SORT_LABELS,
            () => this._sortMode(),
            (v) => this._settings.set_string('media-sort-mode', v)));

        side.add_child(new St.Label({text: _('Search'),
            style: 'font-weight: bold; padding-top: 6px;'}));
        this._searchEntry = new St.Entry({
            hint_text: _('Name, artist, album…'),
            can_focus: true,
        });
        this._searchEntry.clutter_text?.connect?.('text-changed', () => {
            this._query = this._searchEntry.get_text();
            this._renderList();
        });
        side.add_child(this._searchEntry);

        side.add_child(new St.Label({text: _('Filters'),
            style: 'font-weight: bold; padding-top: 6px;'}));
        side.add_child(this._buildFilterToggle(_('Unwatched'),
            () => this._unwatched, v => { this._unwatched = v; }));
        side.add_child(this._buildFilterToggle(_('Continue watching'),
            () => this._unfinished, v => { this._unfinished = v; }));
        side.add_child(this._buildFilterToggle(_('Favourites'),
            () => this._favourites, v => { this._favourites = v; }));

        return side;
    }

    _buildSegmentedRow(items, getter, setter) {
        const row = new St.BoxLayout({vertical: false,
            style: 'spacing: 4px;'});
        const refresh = () => {
            for (const child of row.get_children()) {
                const k = child._sdtKey;
                child.style = getter() === k
                    ? 'background: #3477b8; color: white;'
                        + ' padding: 4px 10px; border-radius: 4px;'
                    : 'background: rgba(127,127,127,0.18);'
                        + ' padding: 4px 10px; border-radius: 4px;';
            }
        };
        for (const [key, label] of items) {
            const btn = new St.Button({
                label: label(),
                reactive: true, can_focus: true, track_hover: true,
                x_expand: true,
            });
            btn._sdtKey = key;
            btn.connect('clicked', () => { setter(key); refresh(); });
            row.add_child(btn);
        }
        // Re-render the active tint whenever GSettings change so the
        // dialog stays in sync with the dropdown picking a tab.
        const sigKey = (() => {
            if (items === _TAB_LABELS) return 'changed::media-active-tab';
            if (items === _GROUP_LABELS) return 'changed::media-group-by';
            return 'changed::media-sort-mode';
        })();
        const sig = this._settings.connect(sigKey, () => {
            refresh();
            this._render();
        });
        row.connect('destroy', () => this._settings.disconnect(sig));
        refresh();
        return row;
    }

    _buildSegmentedColumn(items, getter, setter) {
        const col = new St.BoxLayout({vertical: true,
            style: 'spacing: 2px;'});
        const refresh = () => {
            for (const child of col.get_children()) {
                const k = child._sdtKey;
                child.style = getter() === k
                    ? 'background: #3477b8; color: white;'
                        + ' padding: 4px 10px; border-radius: 4px;'
                        + ' text-align: left;'
                    : 'background: rgba(127,127,127,0.10);'
                        + ' padding: 4px 10px; border-radius: 4px;'
                        + ' text-align: left;';
            }
        };
        for (const [key, label] of items) {
            const btn = new St.Button({
                label: label(),
                reactive: true, can_focus: true, track_hover: true,
                x_expand: true,
            });
            btn._sdtKey = key;
            btn.connect('clicked', () => { setter(key); refresh(); });
            col.add_child(btn);
        }
        const sigKey = items === _GROUP_LABELS
            ? 'changed::media-group-by'
            : 'changed::media-sort-mode';
        const sig = this._settings.connect(sigKey, () => {
            refresh();
            this._render();
        });
        col.connect('destroy', () => this._settings.disconnect(sig));
        refresh();
        return col;
    }

    _buildFilterToggle(label, getter, setter) {
        const btn = new St.Button({
            label: `☐ ${label}`,
            reactive: true, can_focus: true, track_hover: true,
            x_expand: true,
            style: 'padding: 3px 8px; text-align: left;',
        });
        const refresh = () => {
            btn.set_label(`${getter() ? '☑' : '☐'} ${label}`);
        };
        btn.connect('clicked', () => {
            setter(!getter());
            refresh();
            this._renderList();
        });
        refresh();
        return btn;
    }

    // ---------------------------------------------------------------
    // List column
    // ---------------------------------------------------------------

    _buildList() {
        const wrap = new St.BoxLayout({vertical: true,
            x_expand: true,
            style: 'spacing: 4px; min-width: 380px;'});
        this._listSummary = new St.Label({text: '',
            style: 'font-size: 0.85em; opacity: 0.7;'});
        wrap.add_child(this._listSummary);
        this._scroll = new St.ScrollView({
            x_expand: true, y_expand: true,
            style: 'min-height: 480px;'
                + ' background: rgba(0,0,0,0.10); border-radius: 6px;',
        });
        this._listBox = new St.BoxLayout({vertical: true,
            x_expand: true, style: 'padding: 6px; spacing: 2px;'});
        // GNOME 46+: ScrollView.add_child; older API used set_child or
        // add_actor. Try both so the dialog works on either.
        if (typeof this._scroll.set_child === 'function')
            this._scroll.set_child(this._listBox);
        else if (typeof this._scroll.add_child === 'function')
            this._scroll.add_child(this._listBox);
        else
            this._scroll.add_actor(this._listBox);
        wrap.add_child(this._scroll);
        return wrap;
    }

    // ---------------------------------------------------------------
    // Detail column
    // ---------------------------------------------------------------

    _buildDetail() {
        this._detail = new St.BoxLayout({vertical: true,
            style: 'spacing: 6px; min-width: 260px;'});
        this._detail.add_child(new St.Label({
            text: _('Detail'),
            style: 'font-weight: bold;'}));
        this._detailEmpty = new St.Label({
            text: _('Pick a media on the left.'),
            style: 'opacity: 0.7;'});
        this._detail.add_child(this._detailEmpty);
        this._detailBody = new St.BoxLayout({vertical: true,
            style: 'spacing: 4px;'});
        this._detail.add_child(this._detailBody);
        return this._detail;
    }

    // ---------------------------------------------------------------
    // Render pipeline
    // ---------------------------------------------------------------

    _render() {
        this._renderList();
        this._renderDetail();
    }

    _renderList() {
        this._listBox.destroy_all_children();
        this._visibleIds = [];

        const all = parseList(this._settings.get_string('media'));
        const tab = this._activeTab();
        const filtered = filterEntries(all, {
            kind: tab === 'all' ? undefined : tab,
            query: this._query,
            unwatched: this._unwatched,
            unfinished: this._unfinished,
            favourites: this._favourites,
        });
        const sorted = sortEntries(filtered, this._sortMode());

        this._listSummary.set_text(
            _('{shown} of {total} entries')
                .replace('{shown}', sorted.length)
                .replace('{total}', all.length));

        if (!sorted.length) {
            this._listBox.add_child(new St.Label({
                text: _('(nothing matches)'),
                style: 'opacity: 0.7; padding: 6px;'}));
            return;
        }

        const groupKey = this._groupBy();
        const groups = groupKey === 'none'
            ? new Map([['', sorted]])
            : groupBy(sorted, groupKey);

        for (const [bucket, rows] of groups) {
            if (groupKey !== 'none') {
                const collapsed = this._collapsed.has(bucket);
                const label = bucket || _('(unspecified)');
                const head = new St.Button({
                    label: `${collapsed ? '▸' : '▾'}  ${label}`
                        + `   (${rows.length})`,
                    x_expand: true, reactive: true, can_focus: true,
                    track_hover: true,
                    style: 'background: rgba(255,255,255,0.05);'
                        + ' padding: 4px 8px; border-radius: 4px;'
                        + ' text-align: left; font-weight: bold;',
                });
                head.connect('clicked', () => {
                    if (collapsed) this._collapsed.delete(bucket);
                    else this._collapsed.add(bucket);
                    this._renderList();
                });
                this._listBox.add_child(head);
                if (collapsed) continue;
            }
            for (const entry of rows) {
                this._visibleIds.push(entry.id);
                this._listBox.add_child(this._buildRow(entry));
            }
        }
    }

    _buildRow(entry) {
        const selected = entry.id === this._selectedId;
        const btn = new St.Button({
            x_expand: true, reactive: true, can_focus: true,
            track_hover: true,
            style: selected
                ? 'background: rgba(52,119,184,0.35);'
                    + ' padding: 4px 8px; border-radius: 4px;'
                : 'padding: 4px 8px; border-radius: 4px;',
        });
        const inner = new St.BoxLayout({vertical: true,
            style: 'spacing: 1px;'});
        const head = buildMediaLabel(entry);
        const head2 = [];
        if (entry.artist) head2.push(entry.artist);
        if (entry.album) head2.push(entry.album);
        if (entry.year) head2.push(entry.year);
        const sub = head2.join(' · ');
        const last = formatLastPlayed(entry.last_played);
        const lastTxt = last
            ? `📅 ${last === 'today' ? _('today')
                : last === 'yesterday' ? _('yesterday') : last}`
            : '';
        const prog = formatProgress(entry.position, entry.duration);
        inner.add_child(new St.Label({text: head}));
        if (sub)
            inner.add_child(new St.Label({text: sub,
                style: 'font-size: 0.85em; opacity: 0.7;'}));
        const tail = [];
        if (lastTxt) tail.push(lastTxt);
        if (prog) tail.push(prog);
        if (Number(entry.play_count) > 0)
            tail.push(`▶×${entry.play_count}`);
        if (Number(entry.rating) > 0)
            tail.push('★'.repeat(entry.rating));
        if (tail.length)
            inner.add_child(new St.Label({text: tail.join('   '),
                style: 'font-size: 0.85em; opacity: 0.7;'}));
        btn.set_child(inner);
        btn.connect('clicked', () => {
            this._selectedId = entry.id;
            this._renderList();
            this._renderDetail();
        });
        return btn;
    }

    // ---------------------------------------------------------------
    // Detail
    // ---------------------------------------------------------------

    _selectedEntry() {
        if (!this._selectedId) return null;
        const all = parseList(this._settings.get_string('media'));
        return all.find(e => e.id === this._selectedId) || null;
    }

    _renderDetail() {
        this._detailBody.destroy_all_children();
        const entry = this._selectedEntry();
        this._detailEmpty.visible = !entry;
        if (!entry) return;

        const addLine = (label, value) => {
            if (!value) return;
            const row = new St.BoxLayout({vertical: false,
                style: 'spacing: 6px;'});
            row.add_child(new St.Label({text: `${label}:`,
                style: 'opacity: 0.7; min-width: 80px;'}));
            row.add_child(new St.Label({text: String(value),
                x_expand: true}));
            this._detailBody.add_child(row);
        };

        const title = new St.Label({text: entry.name || entry.url,
            style: 'font-weight: bold;'});
        this._detailBody.add_child(title);

        addLine(_('URL'), entry.url);
        addLine(_('Artist'), entry.artist);
        addLine(_('Album'), entry.album);
        addLine(_('Year'), entry.year);
        addLine(_('Genre'), entry.genre);
        addLine(_('Episode'), entry.episode);
        addLine(_('Position'), entry.position);
        addLine(_('Duration'), entry.duration);
        const last = formatLastPlayed(entry.last_played);
        addLine(_('Last played'),
            last === 'today' ? _('today')
                : last === 'yesterday' ? _('yesterday') : last);
        if (Number(entry.play_count) > 0)
            addLine(_('Play count'), entry.play_count);
        if (Number(entry.rating) > 0)
            addLine(_('Rating'), '★'.repeat(entry.rating));

        const actions = new St.BoxLayout({vertical: false,
            style: 'spacing: 4px; padding-top: 6px;'});
        const mkBtn = (label, fn) => {
            const b = new St.Button({label, reactive: true,
                can_focus: true, track_hover: true,
                style: 'background: rgba(127,127,127,0.18);'
                    + ' padding: 4px 8px; border-radius: 4px;'});
            b.connect('clicked', () => fn());
            return b;
        };
        actions.add_child(mkBtn(_('Browser'),
            () => this._onLaunch?.(entry, 'browser')));
        actions.add_child(mkBtn(_('mpv'),
            () => this._onLaunch?.(entry, 'mpv')));
        actions.add_child(mkBtn(_('VLC'),
            () => this._onLaunch?.(entry, 'vlc')));
        if (isSpotifyUrl(entry.url))
            actions.add_child(mkBtn(_('Spotify'),
                () => this._onLaunch?.(entry, 'spotify')));
        this._detailBody.add_child(actions);

        const admin = new St.BoxLayout({vertical: false,
            style: 'spacing: 4px; padding-top: 4px;'});
        admin.add_child(mkBtn(_('Edit'),
            () => this._onEdit?.(entry)));
        admin.add_child(mkBtn(_('Delete'), () => {
            this._onDelete?.(entry);
            this._selectedId = null;
            this._render();
        }));
        // Star picker — clicking sets the rating to N+1, clicking same
        // value again clears it. Persists immediately via GSettings so
        // the change survives the dialog being closed.
        for (let n = 1; n <= 5; n += 1) {
            const cur = Number(entry.rating) || 0;
            const filled = n <= cur ? '★' : '☆';
            const star = mkBtn(filled, () => this._setRating(entry,
                cur === n ? 0 : n));
            star.style += ' min-width: 24px; padding: 2px 4px;';
            admin.add_child(star);
        }
        this._detailBody.add_child(admin);
    }

    _setRating(entry, rating) {
        if (!this._settings) return;
        const list = parseList(this._settings.get_string('media'));
        const i = list.findIndex(e => e.id === entry.id);
        if (i < 0) return;
        list[i] = {...list[i], rating};
        this._settings.set_string('media', serializeList(list));
    }

    // ---------------------------------------------------------------
    // GSettings helpers
    // ---------------------------------------------------------------

    _activeTab() {
        const v = this._settings.get_string('media-active-tab');
        return (v === 'video' || v === 'audio') ? v : 'all';
    }

    _sortMode() {
        const v = this._settings.get_string('media-sort-mode');
        const known = new Set(['last_played', 'alpha', 'play_count',
            'rating', 'added']);
        return known.has(v) ? v : 'last_played';
    }

    _groupBy() {
        const v = this._settings.get_string('media-group-by');
        const known = new Set(['none', 'artist', 'album', 'genre', 'year']);
        return known.has(v) ? v : 'none';
    }
});
