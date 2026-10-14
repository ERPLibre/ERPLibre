/**
 * What the device indicator runs to open or restart the deck program.
 *
 * With the Stream Deck level, the installer writes the systemd --user unit
 * erplibre-home-streamdeck.service, which runs the program chosen in
 * ~/.config/erplibre-home/streamdeck.conf. When that unit file exists the
 * indicator drives the unit, so the service and the indicator never start
 * two programs on one deck; without it (a manual setup) the indicator
 * starts the controller itself under the deck venv.
 *
 * Pure: the caller says whether the unit file exists and passes the venv
 * python, so node --test loads this module without any gi:// import.
 */

export const DECK_UNIT = 'erplibre-home-streamdeck.service';

// Controller script, relative to the checkout root.
export const CONTROLLER_REL = 'script/stream_deck/erplibre_controller.py';

/**
 * Path of the unit file under `configDir`, the user configuration
 * directory ($XDG_CONFIG_HOME, or ~/.config).
 */
export function deckUnitPath(configDir) {
    return `${configDir}/systemd/user/${DECK_UNIT}`;
}

/**
 * argv that opens the deck program: `systemctl --user start` on the unit
 * when `unitExists`, else the controller of `root` under `python`. null
 * when there is no unit and `python` is null (the deck venv is missing):
 * the caller then says the Stream Deck level is not installed.
 */
export function openDeckArgv({unitExists, python, root}) {
    if (unitExists)
        return ['systemctl', '--user', 'start', DECK_UNIT];
    if (python === null || python === undefined)
        return null;
    const base = root.length > 1 ? root.replace(/\/+$/, '') : root;
    return [python, `${base}/${CONTROLLER_REL}`];
}

/**
 * argv that restarts the deck program through the unit, or null when the
 * unit file does not exist: the caller then stops the controller by its
 * pidfile and opens it again.
 */
export function restartDeckArgv({unitExists}) {
    return unitExists ? ['systemctl', '--user', 'restart', DECK_UNIT] : null;
}
