import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';
import {ModalDialog} from 'resource:///org/gnome/shell/ui/modalDialog.js';

import {validatePositionInput} from '../lib/film-helpers.js';

export const FilmDialog = GObject.registerClass(
class FilmDialog extends ModalDialog {
    _init({title = 'Add film', entry = null, onConfirm, onDelete}) {
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
        box.add_child(this._urlEntry);

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
        });
        this.close();
    }
});
