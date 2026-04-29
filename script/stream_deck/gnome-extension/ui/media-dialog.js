import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';
import {ModalDialog} from 'resource:///org/gnome/shell/ui/modalDialog.js';

import {validatePositionInput, guessKind, normaliseKind}
    from '../lib/media-helpers.js';

// See indicators/controller.js for the rationale of the random suffix.
const _GTYPE_SUFFIX = Math.floor(Math.random() * 1e9).toString(36);

export const MediaDialog = GObject.registerClass(
{GTypeName: `SDT_MediaDialog_${_GTYPE_SUFFIX}`},
class MediaDialog extends ModalDialog {
    _init({title = 'Add media', entry = null, onConfirm, onDelete}) {
        super._init({styleClass: 'streamdeck-tiler-dialog'});
        this._onConfirm = onConfirm;
        this._onDelete = onDelete;

        const box = new St.BoxLayout({vertical: true,
            style: 'spacing: 8px;'});
        this.contentLayout.add_child(box);

        box.add_child(new St.Label({text: title,
            style: 'font-weight: bold;'}));

        this._nameEntry = new St.Entry({hint_text: 'Name (required)',
            text: entry?.name ?? ''});
        box.add_child(this._nameEntry);

        this._urlEntry = new St.Entry({hint_text: 'URL (required)',
            text: entry?.url ?? ''});
        this._urlEntry.clutter_text?.connect?.('text-changed',
            () => this._maybeAutoKind());
        box.add_child(this._urlEntry);

        // Kind selector — Video / Audio. Auto-detected from URL on
        // text-changed, but user can override before saving.
        this._kind = entry?.kind
            ? normaliseKind(entry.kind)
            : guessKind(entry?.url ?? '');
        const kindRow = new St.BoxLayout({vertical: false,
            style: 'spacing: 8px;'});
        kindRow.add_child(new St.Label({text: 'Kind:'}));
        this._kindVideoBtn = new St.Button({label: 'Video',
            style_class: 'streamdeck-tiler-btn'});
        this._kindAudioBtn = new St.Button({label: 'Audio',
            style_class: 'streamdeck-tiler-btn'});
        this._kindVideoBtn.connect('clicked',
            () => this._setKind('video'));
        this._kindAudioBtn.connect('clicked',
            () => this._setKind('audio'));
        kindRow.add_child(this._kindVideoBtn);
        kindRow.add_child(this._kindAudioBtn);
        box.add_child(kindRow);
        this._refreshKindButtons();

        this._epEntry = new St.Entry({hint_text: 'Episode (e.g. S2E5)',
            text: entry?.episode ?? ''});
        box.add_child(this._epEntry);

        this._posEntry = new St.Entry({
            hint_text: 'Position (hh:mm:ss or seconds)',
            text: entry?.position ?? '',
        });
        box.add_child(this._posEntry);
        this._posError = new St.Label({text: '',
            style: 'color: #d33; font-size: 0.85em;'});
        box.add_child(this._posError);

        const buttons = [
            {label: 'Cancel', action: () => this.close(),
                key: Clutter.KEY_Escape},
            {label: 'Save', action: () => this._confirm(), default: true},
        ];
        if (onDelete) {
            buttons.unshift({label: 'Delete',
                action: () => { onDelete(); this.close(); }});
        }
        this.setButtons(buttons);
    }

    _confirm() {
        const name = this._nameEntry.get_text().trim();
        const url = this._urlEntry.get_text().trim();
        const position = this._posEntry.get_text().trim();
        if (!name || !url) return;
        if (!validatePositionInput(position)) {
            this._posError.set_text('Invalid position format');
            return;
        }
        this._onConfirm({
            name, url,
            episode: this._epEntry.get_text(),
            position,
            kind: normaliseKind(this._kind),
        });
        this.close();
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
