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
 * systemctl start (or restart) exits 0 even when no program is left
 * running: ExecCondition skips the start (no deck plugged in,
 * DECK_PROGRAM=none), or, with Type=simple, the start returns once the
 * program is forked and the program exits a moment later (the deck lock
 * held elsewhere, no visual Stream Deck). The indicator therefore waits
 * DECK_SETTLE_MS, reads the unit's state, and when no program runs says
 * why: who holds the deck lock, no visual deck, or the reason the entry
 * point's --check gives for a skip.
 *
 * Pure: the caller says whether the unit file exists, passes the venv
 * python, the command outputs and the lock text, so node --test loads this
 * module without any gi:// import.
 */

import {_} from './i18n.js';

export const DECK_UNIT = 'erplibre-home-streamdeck.service';

// Controller script, relative to the checkout root.
export const CONTROLLER_REL = 'script/stream_deck/erplibre_controller.py';

// The service's entry point, relative to the checkout root.
export const DECK_ENTRY_REL = 'script/install/erplibre_home_deck.sh';

// ActiveState values in which the deck program runs or is about to.
const RUNNING_STATES = ['active', 'activating', 'reloading'];

// Exit codes of the deck programs that the unit does not restart
// (script/stream_deck/deck_lock.py: BUSY_EXIT, NO_DECK_EXIT).
const BUSY_EXIT = '2';
const NO_DECK_EXIT = '3';

// systemd's ExecMainCode for a main process that exited (CLD_EXITED), as
// opposed to one killed by a signal, whose ExecMainStatus is the signal.
const CLD_EXITED = '1';

// Milliseconds between a start and the state read: long enough for a
// program that finds the deck busy or no visual deck to have exited, short
// enough for the notice to follow the click.
export const DECK_SETTLE_MS = 1500;

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
 * Path of the deck lock under `runtimeDir` ($XDG_RUNTIME_DIR), as
 * deck_lock.lock_path() builds it.
 */
export function deckLockPath(runtimeDir) {
    return `${runtimeDir}/erplibre-home/deck.lock`;
}

/**
 * argv that prints, as Key=Value lines, the unit properties
 * deckStartOutcome() reads after a start or a restart.
 */
export function deckStateArgv() {
    return ['systemctl', '--user', 'show', '-p', 'ActiveState', '-p', 'Result',
        '-p', 'ExecMainCode', '-p', 'ExecMainStatus', DECK_UNIT];
}

/**
 * The Key=Value lines of `stdout` as an object; other lines are skipped.
 */
export function parseUnitShow(stdout) {
    const props = {};
    for (const line of String(stdout ?? '').split('\n')) {
        const eq = line.indexOf('=');
        if (eq > 0)
            props[line.slice(0, eq).trim()] = line.slice(eq + 1).trim();
    }
    return props;
}

/**
 * What a start left, from the properties parseUnitShow() reads:
 * {kind: 'running'}; 'busy' and 'no-deck' when the program exited with
 * deck_lock's BUSY_EXIT or NO_DECK_EXIT; 'skipped' when ExecCondition
 * kept the program from starting (Result=exec-condition, or, on a systemd
 * that reports a skip as success, no main process ever ran); otherwise
 * 'failed', with the state and result as `detail`.
 */
export function deckStartOutcome(props) {
    const state = props.ActiveState ?? '';
    if (deckRunning(state))
        return {kind: 'running'};
    if (props.ExecMainCode === CLD_EXITED) {
        if (props.ExecMainStatus === BUSY_EXIT)
            return {kind: 'busy'};
        if (props.ExecMainStatus === NO_DECK_EXIT)
            return {kind: 'no-deck'};
    }
    if (props.Result === 'exec-condition' ||
        (state === 'inactive' && props.ExecMainCode === '0'))
        return {kind: 'skipped'};
    if (!state)
        return {kind: 'failed', detail: '?'};
    return {kind: 'failed',
        detail: props.Result ? `${state} (${props.Result})` : state};
}

/**
 * {pid, program} read from the lock's text, each kept only in the form
 * deck_lock.parse_holder() keeps ("?" otherwise); null for an empty text.
 */
export function parseLockHolder(text) {
    const words = String(text ?? '').split(/\s+/).filter(w => w !== '');
    if (!words.length)
        return null;
    const pid = /^[0-9]{1,10}$/.test(words[0]) ? words[0] : '?';
    const program = /^[A-Za-z0-9_-]{1,32}$/.test(words[1] ?? '')
        ? words[1] : '?';
    return {pid, program};
}

/**
 * The notice for `outcome` (deckStartOutcome), translated, or null when the
 * program runs. `holder` is parseLockHolder() of the lock, for 'busy';
 * `checkStderr` is the entry point's --check output, for 'skipped'.
 */
export function deckStartNotice(outcome, {holder = null, checkStderr = ''} = {}) {
    let why;
    switch (outcome.kind) {
    case 'running':
        return null;
    case 'busy':
        why = holder
            ? `${_('the deck is held by')} ${holder.program} (PID ${holder.pid})`
            : `${_('the deck is held by')} ${_('another program')}`;
        break;
    case 'no-deck':
        why = _('no visual Stream Deck is plugged in');
        break;
    case 'skipped':
        why = deckStartFailure('inactive', checkStderr);
        break;
    default:
        why = outcome.detail ?? '?';
    }
    return `${_('The deck program did not start:')} ${why}`;
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
