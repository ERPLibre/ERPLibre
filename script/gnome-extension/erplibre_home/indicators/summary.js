import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {parseList} from '../lib/settings.js';
import {_} from '../lib/i18n.js';

// See indicators/controller.js for the rationale of the random suffix.
const _GTYPE_SUFFIX = Math.floor(Math.random() * 1e9).toString(36);

/**
 * Compact text-only status indicator for users who prefer a single
 * short line over the six-icon strip. Reads paths, alive Claude
 * sessions, awaiting Claude sessions and media count and renders
 * them as glyph-prefixed numbers separated by NBSPs.
 *
 * The indicator is opt-in (enable-summary GSetting, default off).
 * Clicking opens a tiny dropdown that links to prefs.
 */
export const SummaryIndicator = GObject.registerClass(
{GTypeName: `SDT_SummaryIndicator_${_GTYPE_SUFFIX}`},
class SummaryIndicator extends PanelMenu.Button {
    _init({extension, openPrefs, claudeState} = {}) {
        super._init(0.0, 'Stream Deck Summary');
        this._extension = extension;
        this._openPrefs = openPrefs;
        this._settings = extension?.getSettings ? extension.getSettings()
            : null;
        this._claudeState = claudeState || null;
        this._claudeIndex = null;

        this._label = new St.Label({
            y_align: Clutter.ActorAlign.CENTER,
            style: 'font-feature-settings: "tnum"; padding: 0 4px;',
        });
        this.add_child(this._label);

        if (this._claudeState) {
            this._claudeUnsub = this._claudeState.subscribe(idx => {
                this._claudeIndex = idx;
                this._refresh();
            });
        }

        if (this._settings) {
            for (const k of ['paths', 'media']) {
                const sig = this._settings.connect(`changed::${k}`,
                    () => this._refresh());
                this._sigs ??= [];
                this._sigs.push(sig);
            }
        }

        this._buildMenu();
        this._refresh();
    }

    destroy() {
        if (this._claudeUnsub) {
            try { this._claudeUnsub(); } catch (_e) {}
            this._claudeUnsub = null;
        }
        for (const s of this._sigs || [])
            if (s) this._settings.disconnect(s);
        this._sigs = null;
        super.destroy();
    }

    _refresh() {
        if (!this._label || !this._settings) return;
        const dirs = parseList(
            this._settings.get_string('paths')).length;
        const media = parseList(
            this._settings.get_string('media')).length;
        const idx = this._claudeIndex;
        const alive = idx?.totalAlive
            ?? ((idx?.totalActive || 0) + (idx?.totalWorking || 0));
        const awaitStop = idx?.totalAwaitStop || 0;
        const awaitNotify = idx?.totalAwaitNotify || 0;
        const awaiting = awaitStop + awaitNotify;

        const parts = [];
        if (dirs)     parts.push(`${dirs}↑`);
        if (alive)    parts.push(`${alive}●`);
        if (awaiting) parts.push(`${awaiting}⏳`);
        if (media)    parts.push(`${media}🎬`);
        this._label.set_text(parts.join(' '));
    }

    _buildMenu() {
        const open = new PopupMenu.PopupMenuItem(_('⚙ Open prefs'));
        open.connect('activate', () => this._openPrefs?.());
        this.menu.addMenuItem(open);
    }
});

export const indicatorDescriptor = {
    id: 'summary',
    displayName: 'Summary',
    defaultEnabled: false,
    ctor: (opts) => new SummaryIndicator(opts),
};
