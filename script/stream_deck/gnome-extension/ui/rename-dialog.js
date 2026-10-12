import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';
import {ModalDialog} from 'resource:///org/gnome/shell/ui/modalDialog.js';
import {_} from '../lib/i18n.js';

// See indicators/controller.js for the rationale of the random suffix.
const _GTYPE_SUFFIX = Math.floor(Math.random() * 1e9).toString(36);

export const RenameDialog = GObject.registerClass(
{GTypeName: `SDT_RenameDialog_${_GTYPE_SUFFIX}`},
class RenameDialog extends ModalDialog {
    _init({title = _('Rename'), value = '', onConfirm} = {}) {
        super._init({styleClass: 'streamdeck-tiler-dialog'});
        this._onConfirm = onConfirm;

        const box = new St.BoxLayout({vertical: true,
            style: 'spacing: 8px; min-width: 360px;'});
        this.contentLayout.add_child(box);

        box.add_child(new St.Label({text: title,
            style: 'font-weight: bold;'}));

        this._entry = new St.Entry({
            hint_text: _('description'),
            text: value,
            x_expand: true,
        });
        box.add_child(this._entry);

        this.setButtons([
            {label: _('Cancel'), action: () => this.close(),
             key: Clutter.KEY_Escape},
            {label: _('Save'), action: () => this._save(),
             default: true},
        ]);

        this.connect('opened', () => this._entry.grab_key_focus());
    }

    _save() {
        const text = this._entry.get_text().trim();
        try { this._onConfirm?.(text); } catch (_e) {}
        this.close();
    }
});
