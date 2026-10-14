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
 * systemctl start (or restart) exits 0 even when the unit's ExecCondition
 * skips the start (no deck plugged in, DECK_PROGRAM=none): the indicator
 * then reads the unit's state and, when no program runs, shows the reason
 * the entry point's --check gives.
 *
 * Pure: the caller says whether the unit file exists, passes the venv
 * python and the command outputs, so node --test loads this module without
 * any gi:// import.
 */

export const DECK_UNIT = 'erplibre-home-streamdeck.service';

// Controller script, relative to the checkout root.
export const CONTROLLER_REL = 'script/stream_deck/erplibre_controller.py';

// The service's entry point, relative to the checkout root.
export const DECK_ENTRY_REL = 'script/install/erplibre_home_deck.sh';

// ActiveState values in which the deck program runs or is about to.
const RUNNING_STATES = ['active', 'activating', 'reloading'];

function trimRoot(root) {
    return root.length > 1 ? root.replace(/\/+$/, '') : root;
}

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
    return [python, `${trimRoot(root)}/${CONTROLLER_REL}`];
}

/**
 * argv that restarts the deck program through the unit, or null when the
 * unit file does not exist: the caller then stops the controller by its
 * pidfile and opens it again.
 */
export function restartDeckArgv({unitExists}) {
    return unitExists ? ['systemctl', '--user', 'restart', DECK_UNIT] : null;
}

/**
 * argv that prints the unit's ActiveState alone, read after a start or a
 * restart.
 */
export function deckStateArgv() {
    return ['systemctl', '--user', 'show', '-p', 'ActiveState', '--value',
        DECK_UNIT];
}

/**
 * Whether `state`, the output of deckStateArgv(), says the deck program
 * runs or is about to.
 */
export function deckRunning(state) {
    return RUNNING_STATES.includes(String(state ?? '').trim());
}

/**
 * argv of the entry point's own condition check in the checkout `root`:
 * it exits 1 with its reason on one stderr line when no program can run.
 */
export function deckCheckArgv(root) {
    return [`${trimRoot(root)}/${DECK_ENTRY_REL}`, '--check'];
}

/**
 * Why a start through the unit left no program running: the last
 * non-empty line of `checkStderr` (the check's reason), else the unit's
 * `state` trimmed, else "?".
 */
export function deckStartFailure(state, checkStderr) {
    const lines = String(checkStderr ?? '').split('\n')
        .map(l => l.trim()).filter(l => l !== '');
    if (lines.length)
        return lines[lines.length - 1];
    return String(state ?? '').trim() || '?';
}
