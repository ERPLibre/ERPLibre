import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';
import {ModalDialog} from 'resource:///org/gnome/shell/ui/modalDialog.js';

import {validatePositionInput, guessKind, normaliseKind,
    extractMediaInfo}
    from '../lib/media-helpers.js';
import {_} from '../lib/i18n.js';

// See indicators/controller.js for the rationale of the random suffix.
const _GTYPE_SUFFIX = Math.floor(Math.random() * 1e9).toString(36);

export const MediaDialog = GObject.registerClass(
{GTypeName: `SDT_MediaDialog_${_GTYPE_SUFFIX}`},
class MediaDialog extends ModalDialog {
    _init({title = _('Add media'), entry = null, onConfirm, onDelete}) {
        super._init({styleClass: 'streamdeck-tiler-dialog'});
        this._onConfirm = onConfirm;
        this._onDelete = onDelete;

        const box = new St.BoxLayout({vertical: true,
            style: 'spacing: 8px;'});
        this.contentLayout.add_child(box);

        box.add_child(new St.Label({text: title,
            style: 'font-weight: bold;'}));

        this._nameEntry = new St.Entry({
            hint_text: _('Name (auto-filled if empty)'),
            text: entry?.name ?? '',
        });
        box.add_child(this._nameEntry);

        // URL row with an Auto-fill button on the right that parses
        // the URL and populates Name + Episode from known platforms
        // (tou.tv, noovo, vrai, vimeo, soundcloud, …).
        const urlRow = new St.BoxLayout({vertical: false,
            style: 'spacing: 4px;'});
        this._urlEntry = new St.Entry({hint_text: _('URL (required)'),
            text: entry?.url ?? '', x_expand: true});
        this._urlEntry.clutter_text?.connect?.('text-changed',
            () => this._maybeAutoKind());
        urlRow.add_child(this._urlEntry);
        // Inline style mirrors the active kind button so the user
        // sees a real button-shaped clickable target. Without a
        // background the unstyled St.Button collapses to a flat
        // label that does not feel pressable.
        // Inline style mirrors the active kind button so the user
        // sees a real button-shaped clickable target. Without a
        // background the unstyled St.Button collapses to a flat
        // label that does not feel pressable.
        this._fillBtnLabel = _('Auto-fill');
        this._fillBtn = new St.Button({
            label: this._fillBtnLabel,
            reactive: true,
            can_focus: true,
            track_hover: true,
            style: 'background: #3477b8; color: white;'
                + ' padding: 4px 12px; border-radius: 4px;'
                + ' min-width: 80px;',
        });
        this._fillBtn.connect('clicked', () => this._autoFillFromUrl());
        urlRow.add_child(this._fillBtn);
        box.add_child(urlRow);

        // Inline status line under the URL row: success summarises
        // what got filled, failure tells the user nothing matched.
        this._fillStatus = new St.Label({
            text: '',
            style: 'font-size: 0.85em; opacity: 0.85;',
        });
        box.add_child(this._fillStatus);

        // Kind selector — Video / Audio. Auto-detected from URL on
        // text-changed, but user can override before saving.
        this._kind = entry?.kind
            ? normaliseKind(entry.kind)
            : guessKind(entry?.url ?? '');
        const kindRow = new St.BoxLayout({vertical: false,
            style: 'spacing: 8px;'});
        kindRow.add_child(new St.Label({text: _('Kind:')}));
        this._kindVideoBtn = new St.Button({label: _('Video'),
            style_class: 'streamdeck-tiler-btn'});
        this._kindAudioBtn = new St.Button({label: _('Audio'),
            style_class: 'streamdeck-tiler-btn'});
        this._kindVideoBtn.connect('clicked',
            () => this._setKind('video'));
        this._kindAudioBtn.connect('clicked',
            () => this._setKind('audio'));
        kindRow.add_child(this._kindVideoBtn);
        kindRow.add_child(this._kindAudioBtn);
        box.add_child(kindRow);
        this._refreshKindButtons();

        this._epEntry = new St.Entry({hint_text: _('Episode (e.g. S2E5)'),
            text: entry?.episode ?? ''});
        box.add_child(this._epEntry);

        // Library fields — optional, surface artist/album/year/genre
        // so the library dialog can group/filter on them. Auto-fill
        // also lands here for music URLs (Bandcamp, SoundCloud…).
        this._artistEntry = new St.Entry({
            hint_text: _('Artist / author'),
            text: entry?.artist ?? '',
        });
        box.add_child(this._artistEntry);
        this._albumEntry = new St.Entry({
            hint_text: _('Album / season'),
            text: entry?.album ?? '',
        });
        box.add_child(this._albumEntry);
        const ygRow = new St.BoxLayout({vertical: false,
            style: 'spacing: 4px;'});
        this._yearEntry = new St.Entry({
            hint_text: _('Year'),
            text: entry?.year ?? '',
            x_expand: true,
        });
        ygRow.add_child(this._yearEntry);
        this._genreEntry = new St.Entry({
            hint_text: _('Genre'),
            text: entry?.genre ?? '',
            x_expand: true,
        });
        ygRow.add_child(this._genreEntry);
        box.add_child(ygRow);

        this._posEntry = new St.Entry({
            hint_text: _('Position (hh:mm:ss or seconds)'),
            text: entry?.position ?? '',
        });
        box.add_child(this._posEntry);
        this._posError = new St.Label({text: '',
            style: 'color: #d33; font-size: 0.85em;'});
        box.add_child(this._posError);

        const buttons = [
            {label: _('Cancel'), action: () => this.close(),
                key: Clutter.KEY_Escape},
            {label: _('Save'), action: () => this._confirm(),
                default: true},
        ];
        if (onDelete) {
            buttons.unshift({label: _('Delete'),
                action: () => { onDelete(); this.close(); }});
        }
        this.setButtons(buttons);
    }

    _confirm() {
        let name = this._nameEntry.get_text().trim();
        const url = this._urlEntry.get_text().trim();
        const position = this._posEntry.get_text().trim();
        if (!url) return;
        if (!validatePositionInput(position)) {
            this._posError.set_text(_('Invalid position format'));
            return;
        }
        // Name is optional — derive from URL when blank so the
        // user can paste a link and hit Save without filling
        // anything else in.
        if (!name) name = extractMediaInfo(url).name || url;
        this._onConfirm({
            name, url,
            episode: this._epEntry.get_text(),
            position,
            kind: normaliseKind(this._kind),
            artist: this._artistEntry.get_text().trim(),
            album: this._albumEntry.get_text().trim(),
            year: this._yearEntry.get_text().trim(),
            genre: this._genreEntry.get_text().trim(),
        });
        this.close();
    }

    _autoFillFromUrl() {
        const url = this._urlEntry.get_text().trim();
        if (!url) {
            this._setFillStatus('warn', _('Paste a URL first.'));
            return;
        }

        // Even though extraction is synchronous, flip the button to
        // a working state so the user gets visual feedback that the
        // click registered. The actual work happens after a tick so
        // the UI repaints first.
        if (this._fillTimerId) {
            GLib.source_remove(this._fillTimerId);
            this._fillTimerId = 0;
        }
        this._fillBtn.set_label(_('Working…'));
        this._fillBtn.reactive = false;
        this._setFillStatus('info', '');

        this._fillTimerId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 50, () => {
            this._fillTimerId = 0;
            try {
                const info = extractMediaInfo(url);
                const filled = [];
                const skipped = [];
                if (info.name) {
                    if (!this._nameEntry.get_text().trim()) {
                        this._nameEntry.set_text(info.name);
                        filled.push(_('name'));
                    } else {
                        skipped.push(_('name'));
                    }
                }
                if (info.episode) {
                    if (!this._epEntry.get_text().trim()) {
                        this._epEntry.set_text(info.episode);
                        filled.push(_('episode'));
                    } else {
                        skipped.push(_('episode'));
                    }
                }
                if (info.artist) {
                    if (!this._artistEntry.get_text().trim()) {
                        this._artistEntry.set_text(info.artist);
                        filled.push(_('artist'));
                    } else {
                        skipped.push(_('artist'));
                    }
                }
                if (info.album) {
                    if (!this._albumEntry.get_text().trim()) {
                        this._albumEntry.set_text(info.album);
                        filled.push(_('album'));
                    } else {
                        skipped.push(_('album'));
                    }
                }
                if (filled.length) {
                    this._setFillStatus('ok',
                        _('✓ Filled {fields}.')
                            .replace('{fields}', filled.join(', ')));
                } else if (skipped.length) {
                    this._setFillStatus('warn',
                        _('⚠ Already filled — clear the field first.'));
                } else {
                    this._setFillStatus('warn',
                        _('⚠ Could not extract anything from this URL.'));
                }
            } catch (e) {
                this._setFillStatus('err',
                    _('× Auto-fill failed: {err}')
                        .replace('{err}', e.message || String(e)));
            } finally {
                this._fillBtn.set_label(this._fillBtnLabel);
                this._fillBtn.reactive = true;
            }
            return GLib.SOURCE_REMOVE;
        });
    }

    _setFillStatus(level, text) {
        if (!this._fillStatus) return;
        const colors = {
            ok:   '#2e7d32',
            warn: '#d4a017',
            err:  '#c62828',
            info: 'inherit',
        };
        this._fillStatus.style =
            `font-size: 0.85em; color: ${colors[level] || 'inherit'};`;
        this._fillStatus.set_text(text || '');
    }

    _setKind(kind) {
        this._kind = normaliseKind(kind);
        this._userPickedKind = true;
        this._refreshKindButtons();
    }

    _maybeAutoKind() {
        if (this._userPickedKind) return;
        const guess = guessKind(this._urlEntry.get_text());
        if (guess !== this._kind) {
            this._kind = guess;
            this._refreshKindButtons();
        }
    }

    _refreshKindButtons() {
        const accent = 'background: #3477b8; color: white;'
            + ' padding: 2px 8px; border-radius: 4px;';
        const dim = 'opacity: 0.6; padding: 2px 8px;';
        this._kindVideoBtn.style =
            this._kind === 'video' ? accent : dim;
        this._kindAudioBtn.style =
            this._kind === 'audio' ? accent : dim;
    }
});
