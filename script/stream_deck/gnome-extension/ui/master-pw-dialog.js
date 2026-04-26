import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';
import {ModalDialog} from 'resource:///org/gnome/shell/ui/modalDialog.js';

export const MasterPwDialog = GObject.registerClass(
class MasterPwDialog extends ModalDialog {
    _init({db, onConfirm, onCancel}) {
        super._init({styleClass: 'streamdeck-tiler-dialog'});
        this._onConfirm = onConfirm;
        this._onCancel = onCancel;

        const box = new St.BoxLayout({vertical: true,
            style: 'spacing: 8px;'});
        this.contentLayout.add_child(box);
        box.add_child(new St.Label({text: `Unlock ${db}`,
            style: 'font-weight: bold;'}));
        this._entry = new St.PasswordEntry({hint_text: 'Master password'});
        box.add_child(this._entry);

        this.setButtons([
            {label: 'Cancel', action: () => { this._onCancel?.(); this.close(); },
                key: Clutter.KEY_Escape},
            {label: 'Unlock', action: () => this._confirm(), default: true},
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
