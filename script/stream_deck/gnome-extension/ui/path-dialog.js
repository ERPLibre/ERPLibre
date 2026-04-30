import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import {ModalDialog} from 'resource:///org/gnome/shell/ui/modalDialog.js';
import {_} from '../lib/i18n.js';

// See indicators/controller.js for the rationale of the random suffix.
const _GTYPE_SUFFIX = Math.floor(Math.random() * 1e9).toString(36);

export const PathDialog = GObject.registerClass(
{GTypeName: `SDT_PathDialog_${_GTYPE_SUFFIX}`},
class PathDialog extends ModalDialog {
    _init({title = _('Add path'), entry = null, recentPaths = [],
        onConfirm}) {
        super._init({styleClass: 'streamdeck-tiler-dialog'});
        this._onConfirm = onConfirm;

        const box = new St.BoxLayout({vertical: true, style: 'spacing: 8px;'});
        this.contentLayout.add_child(box);

        box.add_child(new St.Label({text: title,
            style: 'font-weight: bold;'}));

        this._labelEntry = new St.Entry({
            hint_text: _('Label (optional)'),
            text: entry?.label ?? '',
        });
        box.add_child(this._labelEntry);

        const pathRow = new St.BoxLayout({style: 'spacing: 4px;'});
        this._pathEntry = new St.Entry({
            hint_text: _('/path/to/project'),
            text: entry?.path ?? '',
            x_expand: true,
        });
        pathRow.add_child(this._pathEntry);
        const pickBtn = new St.Button({label: '📁'});
        pickBtn.connect('clicked', () => this._launchChooser());
        pathRow.add_child(pickBtn);
        box.add_child(pathRow);

        if (recentPaths.length) {
            box.add_child(new St.Label({text: _('Recent:'),
                style: 'opacity: 0.7;'}));
            for (const r of recentPaths.slice(0, 5)) {
                const btn = new St.Button({label: r,
                    style: 'text-align: left;'});
                btn.connect('clicked', () => {
                    this._pathEntry.set_text(r);
                });
                box.add_child(btn);
            }
        }

        this.setButtons([
            {label: _('Cancel'), action: () => this.close(),
                key: Clutter.KEY_Escape},
            {label: _('Save'), action: () => this._confirm(),
                default: true},
        ]);
    }

    _launchChooser() {
        // Use zenity as the cross-DE file chooser invokable from a shell context.
        let proc;
        try {
            proc = Gio.Subprocess.new(
                ['zenity', '--file-selection', '--directory',
                    `--title=${_('Select project path')}`],
                Gio.SubprocessFlags.STDOUT_PIPE);
        } catch (e) {
            console.log(`[StreamDeckTiler] zenity not available: ${e.message}`);
            return;
        }
        proc.communicate_utf8_async(null, null, (p, res) => {
            try {
                const [, stdout] = p.communicate_utf8_finish(res);
                const path = (stdout || '').trim();
                if (path) this._pathEntry.set_text(path);
            } catch (_e) {}
        });
    }

    _confirm() {
        const label = this._labelEntry.get_text();
        const path = this._pathEntry.get_text().trim();
        if (!path) return;
        const expanded = path.startsWith('~')
            ? GLib.build_filenamev([GLib.get_home_dir(), path.slice(1)])
            : path;
        this._onConfirm({label, path: expanded});
        this.close();
    }
});
