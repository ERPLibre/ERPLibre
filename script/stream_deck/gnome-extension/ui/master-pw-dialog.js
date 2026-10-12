import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';
import {ModalDialog} from 'resource:///org/gnome/shell/ui/modalDialog.js';
import {_} from '../lib/i18n.js';

// See indicators/controller.js for the rationale of the random suffix.
const _GTYPE_SUFFIX = Math.floor(Math.random() * 1e9).toString(36);

export const MasterPwDialog = GObject.registerClass(
{GTypeName: `SDT_MasterPwDialog_${_GTYPE_SUFFIX}`},
class MasterPwDialog extends ModalDialog {
    _init({db, onConfirm, onCancel}) {
        super._init({styleClass: 'streamdeck-tiler-dialog'});
        this._onConfirm = onConfirm;
        this._onCancel = onCancel;

        const box = new St.BoxLayout({vertical: true,
            style: 'spacing: 8px;'});
        this.contentLayout.add_child(box);
        box.add_child(new St.Label({
            text: _('Unlock {db}').replace('{db}', db),
            style: 'font-weight: bold;'}));
        this._entry = new St.PasswordEntry({hint_text: _('Master password')});
        box.add_child(this._entry);

        this.setButtons([
            {label: _('Cancel'),
                action: () => { this._onCancel?.(); this.close(); },
                key: Clutter.KEY_Escape},
            {label: _('Unlock'), action: () => this._confirm(),
                default: true},
        ]);

        // Focus password entry when dialog opens.
        this.connect('opened', () => this._entry.grab_key_focus?.());
    }

    _confirm() {
        const pw = this._entry.get_text();
        if (!pw) return;
        this._onConfirm(pw);
        this.close();
    }
});
