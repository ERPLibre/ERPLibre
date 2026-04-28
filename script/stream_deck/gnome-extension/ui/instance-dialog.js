import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';
import {ModalDialog} from 'resource:///org/gnome/shell/ui/modalDialog.js';

// See indicators/controller.js for the rationale of the random suffix.
const _GTYPE_SUFFIX = Math.floor(Math.random() * 1e9).toString(36);

export const InstanceDialog = GObject.registerClass(
{GTypeName: `SDT_InstanceDialog_${_GTYPE_SUFFIX}`},
class InstanceDialog extends ModalDialog {
    _init({title = 'Add instance', entry = null, onConfirm, onDelete}) {
        super._init({styleClass: 'streamdeck-tiler-dialog'});
        this._onConfirm = onConfirm;
        this._onDelete = onDelete;

        const box = new St.BoxLayout({vertical: true,
            style: 'spacing: 6px;'});
        this.contentLayout.add_child(box);
        box.add_child(new St.Label({text: title,
            style: 'font-weight: bold;'}));

        this._fields = {};
        this._addField(box, 'name', entry?.name, 'Name');
        this._addField(box, 'url', entry?.url, 'URL (https://…)');
        this._addField(box, 'port', String(entry?.port ?? ''), 'Port (8069)');
        this._addField(box, 'keepass_db', entry?.keepass_db, 'KeePassXC DB path');
        this._addField(box, 'keepass_keyfile', entry?.keepass_keyfile,
            'KeePassXC key file (optional)');
        this._addField(box, 'keepass_yubikey_slot',
            String(entry?.keepass_yubikey_slot ?? ''),
            'YubiKey slot (1, 2, or empty)');
        this._addField(box, 'keepass_yubikey_serial', entry?.keepass_yubikey_serial,
            'YubiKey serial (optional)');
        this._addField(box, 'keepass_entry', entry?.keepass_entry,
            'KeePassXC entry title');
        this._addField(box, 'auto_login_method',
            entry?.auto_login_method ?? 'selenium',
            'auto_login_method: selenium | xdotool | none');

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

    _addField(box, key, initial, hint) {
        const e = new St.Entry({hint_text: hint, text: initial ?? ''});
        this._fields[key] = e;
        box.add_child(e);
    }

    _confirm() {
        const data = {};
        for (const [k, e] of Object.entries(this._fields))
            data[k] = e.get_text().trim();
        data.port = parseInt(data.port || '8069', 10) || 8069;
        data.keepass_yubikey_slot =
            parseInt(data.keepass_yubikey_slot || '0', 10) || 0;
        if (!['selenium', 'xdotool', 'none'].includes(data.auto_login_method))
            data.auto_login_method = 'selenium';
        if (!data.name || !data.url) return;
        this._onConfirm(data);
        this.close();
    }
});
