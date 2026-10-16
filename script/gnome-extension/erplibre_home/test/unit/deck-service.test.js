import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DECK_UNIT, CONTROLLER_REL, DECK_ENTRY_REL, DECK_READ_AT_MS,
    deckUnitPath, deckLockPath, openDeckArgv, restartDeckArgv, deckStateArgv,
    deckRunning, deckCheckArgv, deckStartFailure, parseUnitShow,
    deckStartOutcome, deckStartSettled, awaitDeckStart, parseLockHolder,
    deckStartNotice}
    from '../../lib/deck-service.js';

const ROOT = '/opt/mon depot';
const PYTHON = `${ROOT}/.venv.streamdeck/bin/python`;

function extensionFile(rel) {
    return readFileSync(new URL(`../../${rel}`, import.meta.url), 'utf8');
}

test('the unit name and path are those the installer writes', () => {
    assert.equal(DECK_UNIT, 'erplibre-home-streamdeck.service');
    assert.equal(deckUnitPath('/opt/maison/.config'),
        '/opt/maison/.config/systemd/user/erplibre-home-streamdeck.service');
});

test('with the unit, open starts the unit whatever the venv', () => {
    for (const python of [PYTHON, null]) {
        assert.deepEqual(
            openDeckArgv({unitExists: true, python, root: ROOT}),
            ['systemctl', '--user', 'start', DECK_UNIT]);
    }
});

test('without the unit, open runs the controller under the venv', () => {
    assert.deepEqual(
        openDeckArgv({unitExists: false, python: PYTHON, root: `${ROOT}/`}),
        [PYTHON, `${ROOT}/${CONTROLLER_REL}`]);
});

test('without the unit nor the venv, open gives null', () => {
    assert.equal(openDeckArgv({unitExists: false, python: null, root: ROOT}),
        null);
});

test('restart goes through the unit only when it exists', () => {
    assert.deepEqual(restartDeckArgv({unitExists: true}),
        ['systemctl', '--user', 'restart', DECK_UNIT]);
    assert.equal(restartDeckArgv({unitExists: false}), null);
});

test('the state after a start is read from systemctl show', () => {
    assert.deepEqual(deckStateArgv(),
        ['systemctl', '--user', 'show', '-p', 'ActiveState',
            '-p', 'SubState', '-p', 'Result', '-p', 'ExecMainCode',
            '-p', 'ExecMainStatus', DECK_UNIT]);
});

test('the state is read in a short bounded series after the start', () => {
    // Type=simple: systemctl start returns once the program is forked,
    // before a busy deck (2) or no visual deck (3) ends it. The first read
    // follows the click; no gap exceeds RestartSec=3, so a read lands in
    // the restart wait of a crash loop; the last read bounds the series.
    const at = DECK_READ_AT_MS;
    assert.ok(at.length >= 2 && at.length <= 6, String(at));
    assert.ok(at[0] >= 1000 && at[0] <= 3000, String(at));
    for (let i = 1; i < at.length; i++)
        assert.ok(at[i] > at[i - 1] && at[i] - at[i - 1] <= 3000, String(at));
    assert.ok(at[at.length - 1] <= 10000, String(at));
});

// Runs awaitDeckStart on `states` read in turn; returns the outcome, the
// waits asked for and the number of reads.
async function series(states) {
    const waits = [];
    let reads = 0;
    const outcome = await awaitDeckStart({
        wait: async ms => { waits.push(ms); },
        readProps: async () => states[Math.min(reads++, states.length - 1)],
    });
    return {outcome, waits, reads};
}

test('the reads stop at the first state that says why nothing runs',
    async () => {
        const run = await series([SHOWN.running, SHOWN.busy, SHOWN.running]);
        assert.deepEqual(run.outcome, {kind: 'busy'});
        assert.equal(run.reads, 2);
        assert.deepEqual(run.waits,
            [DECK_READ_AT_MS[0], DECK_READ_AT_MS[1] - DECK_READ_AT_MS[0]]);
        const skip = await series([SHOWN.skipped]);
        assert.deepEqual(skip.outcome, {kind: 'skipped'});
        assert.equal(skip.reads, 1);
    });

test('a program that fails late is still reported', async () => {
    const states = DECK_READ_AT_MS.map(() => SHOWN.running);
    states[states.length - 1] = SHOWN.crashed;
    const run = await series(states);
    assert.deepEqual(run.outcome,
        {kind: 'failed', detail: 'failed (exit-code, status 1)'});
    assert.equal(run.reads, DECK_READ_AT_MS.length);
});

test('a program still running at the last read counts as started',
    async () => {
        const run = await series([SHOWN.running]);
        assert.deepEqual(run.outcome, {kind: 'running'});
        assert.equal(run.reads, DECK_READ_AT_MS.length);
        assert.equal(run.waits.reduce((a, b) => a + b, 0),
            DECK_READ_AT_MS[DECK_READ_AT_MS.length - 1]);
    });

test('a unit on its way down is read again for its end state', async () => {
    const stopping = {ActiveState: 'deactivating', SubState: 'stop-sigterm',
        Result: 'success', ExecMainCode: '0', ExecMainStatus: '0'};
    assert.equal(deckStartSettled(stopping), false);
    assert.equal(deckStartSettled(SHOWN.running), false);
    assert.equal(deckStartSettled(SHOWN.restartQueued), true);
    const run = await series([stopping, SHOWN.noDeck]);
    assert.deepEqual(run.outcome, {kind: 'no-deck'});
    assert.equal(run.reads, 2);
});

test('a clean stop after the program ran is not a failed start',
    async () => {
        // A hand-over to a game or a restart click stops the unit while
        // the reads go on: SIGTERM ends the program with 143, which
        // SuccessExitStatus turns into Result=success.
        const stopping = {ActiveState: 'deactivating',
            SubState: 'stop-sigterm', Result: 'success', ExecMainCode: '0',
            ExecMainStatus: '0'};
        const stopped = {ActiveState: 'inactive', Result: 'success',
            ExecMainCode: '1', ExecMainStatus: '143'};
        const run = await series([SHOWN.running, stopping, stopped]);
        assert.deepEqual(run.outcome, {kind: 'running'});
        assert.equal(run.reads, 2);
        const late = await series([SHOWN.running, SHOWN.crashed]);
        assert.deepEqual(late.outcome,
            {kind: 'failed', detail: 'failed (exit-code, status 1)'});
    });

test('systemctl show lines become properties', () => {
    assert.deepEqual(
        parseUnitShow('ActiveState=failed\nResult=exit-code\n' +
            'ExecMainCode=1\nExecMainStatus=2\n\nodd line\n'),
        {ActiveState: 'failed', Result: 'exit-code', ExecMainCode: '1',
            ExecMainStatus: '2'});
    assert.deepEqual(parseUnitShow(null), {});
});

// What systemctl show reports a moment after each kind of start.
const SHOWN = {
    running: {ActiveState: 'active', Result: 'success', ExecMainCode: '0',
        ExecMainStatus: '0'},
    busy: {ActiveState: 'failed', Result: 'exit-code', ExecMainCode: '1',
        ExecMainStatus: '2'},
    noDeck: {ActiveState: 'failed', Result: 'exit-code', ExecMainCode: '1',
        ExecMainStatus: '3'},
    skipped: {ActiveState: 'inactive', Result: 'exec-condition',
        ExecMainCode: '0', ExecMainStatus: '0'},
    skippedOld: {ActiveState: 'inactive', Result: 'success',
        ExecMainCode: '0', ExecMainStatus: '0'},
    crashed: {ActiveState: 'failed', Result: 'exit-code', ExecMainCode: '1',
        ExecMainStatus: '1'},
    killed: {ActiveState: 'failed', Result: 'signal', ExecMainCode: '2',
        ExecMainStatus: '2'},
    // Exited 1 and waiting RestartSec before Restart=on-failure.
    restarting: {ActiveState: 'activating', SubState: 'auto-restart',
        Result: 'exit-code', ExecMainCode: '1', ExecMainStatus: '1'},
    restartingKilled: {ActiveState: 'activating', SubState: 'auto-restart',
        Result: 'signal', ExecMainCode: '2', ExecMainStatus: '11'},
    // systemd 254+: RestartSec elapsed, the restart job is queued.
    restartQueued: {ActiveState: 'activating',
        SubState: 'auto-restart-queued', Result: 'exit-code',
        ExecMainCode: '1', ExecMainStatus: '1'},
    starting: {ActiveState: 'activating', SubState: 'start',
        Result: 'success', ExecMainCode: '0', ExecMainStatus: '0'},
};

test('each start is classified from the unit state', () => {
    assert.deepEqual(deckStartOutcome(SHOWN.running), {kind: 'running'});
    assert.deepEqual(deckStartOutcome(SHOWN.busy), {kind: 'busy'});
    assert.deepEqual(deckStartOutcome(SHOWN.noDeck), {kind: 'no-deck'});
    assert.deepEqual(deckStartOutcome(SHOWN.skipped), {kind: 'skipped'});
    assert.deepEqual(deckStartOutcome(SHOWN.skippedOld), {kind: 'skipped'});
    assert.deepEqual(deckStartOutcome(SHOWN.crashed),
        {kind: 'failed', detail: 'failed (exit-code, status 1)'});
    // Killed by signal 2 is not the busy exit code 2.
    assert.deepEqual(deckStartOutcome(SHOWN.killed),
        {kind: 'failed', detail: 'failed (signal)'});
    assert.deepEqual(deckStartOutcome({}), {kind: 'failed', detail: '?'});
});

test('a program waiting to be restarted does not run', () => {
    // activating is a running state, except between a crash and the
    // restart: the click must not stay silent on a crash loop.
    assert.deepEqual(deckStartOutcome(SHOWN.restarting),
        {kind: 'failed', detail: 'auto-restart (exit-code, status 1)'});
    assert.deepEqual(deckStartOutcome(SHOWN.restartingKilled),
        {kind: 'failed', detail: 'auto-restart (signal)'});
    assert.deepEqual(deckStartOutcome(SHOWN.restartQueued),
        {kind: 'failed',
            detail: 'auto-restart-queued (exit-code, status 1)'});
    assert.deepEqual(deckStartOutcome(SHOWN.starting), {kind: 'running'});
});

test('the lock names its holder like deck_lock.parse_holder', () => {
    assert.equal(deckLockPath('/run/user/1234'),
        '/run/user/1234/erplibre-home/deck.lock');
    assert.deepEqual(parseLockHolder('4242 game\n'),
        {pid: '4242', program: 'game'});
    assert.deepEqual(parseLockHolder('12;reboot $(exemple)\n'),
        {pid: '?', program: '?'});
    assert.equal(parseLockHolder(''), null);
    assert.equal(parseLockHolder(null), null);
});

test('the notice says why no deck program runs', () => {
    assert.equal(deckStartNotice({kind: 'running'}, {}), null);
    assert.equal(
        deckStartNotice({kind: 'busy'},
            {holder: {pid: '4242', program: 'game'}}),
        'The deck program did not start: the deck is held by game ' +
        '(PID 4242)');
    assert.equal(deckStartNotice({kind: 'busy'}, {holder: null}),
        'The deck program did not start: the deck is held by another ' +
        'program');
    assert.equal(deckStartNotice({kind: 'no-deck'}, {}),
        'The deck program did not start: no visual Stream Deck is ' +
        'plugged in');
    assert.equal(
        deckStartNotice({kind: 'skipped'}, {checkStderr:
            '[ERPLibre Home] DECK_PROGRAM=none: no deck program to run\n'}),
        'The deck program did not start: [ERPLibre Home] ' +
        'DECK_PROGRAM=none: no deck program to run');
    // The check gave no line (its condition holds again, or it could not
    // run): the notice still names the skip and its causes.
    for (const checkStderr of ['', '\n \n', null])
        assert.equal(deckStartNotice({kind: 'skipped'}, {checkStderr}),
            'The deck program did not start: its start condition is not ' +
            'met (DECK_PROGRAM=none, no venv or no Stream Deck plugged in)');
    assert.equal(
        deckStartNotice({kind: 'failed', detail: 'failed (exit-code)'}, {}),
        'The deck program did not start: failed (exit-code)');
});

test('active, activating and reloading count as running', () => {
    for (const state of ['active', 'activating', 'reloading', 'active\n'])
        assert.equal(deckRunning(state), true, state);
    for (const state of ['inactive', 'failed', 'deactivating', '', null])
        assert.equal(deckRunning(state), false, String(state));
});

test('the check runs the entry point of the checkout with --check', () => {
    assert.equal(DECK_ENTRY_REL, 'script/install/erplibre_home_deck.sh');
    assert.deepEqual(deckCheckArgv(`${ROOT}/`),
        [`${ROOT}/${DECK_ENTRY_REL}`, '--check']);
});

test('a skipped start is explained by the last line of the check', () => {
    // ExecCondition skips the start: systemctl start exits 0 and the unit
    // stays inactive; the entry point says why on stderr.
    assert.equal(deckStartFailure('inactive',
        'debut\n[ERPLibre Home] no Stream Deck plugged in (USB vendor 0fd9)\n\n'),
    '[ERPLibre Home] no Stream Deck plugged in (USB vendor 0fd9)');
});

test('without a reason from the check, the state is shown', () => {
    assert.equal(deckStartFailure('failed\n', ''), 'failed');
    assert.equal(deckStartFailure('', null), '?');
});

test('the device indicator takes its argv from this module', () => {
    const src = extensionFile('indicators/device.js');
    assert.ok(src.includes("from '../lib/deck-service.js'"));
    assert.ok(src.includes('openDeckArgv('));
    assert.ok(src.includes('restartDeckArgv('));
    assert.ok(src.includes('deckStateArgv()'));
    assert.ok(src.includes('deckCheckArgv('));
    assert.ok(src.includes(
        'parseUnitShow((await runProcess(deckStateArgv())).stdout)'));
    assert.ok(src.includes('deckStartNotice('));
    assert.ok(src.includes('parseLockHolder('));
    assert.ok(src.includes('deckLockPath(GLib.get_user_runtime_dir())'));
    assert.ok(src.includes('deckUnitPath(GLib.get_user_config_dir())'));
    assert.ok(!src.includes("const CONTROLLER_REL"));
});

test('the indicator waits without blocking, and drops the wait on destroy',
    () => {
        const src = extensionFile('indicators/device.js');
        assert.ok(src.includes('awaitDeckStart({'));
        assert.ok(src.includes('GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms'));
        assert.ok(!src.includes('DECK_SETTLE_MS'));
        assert.ok(src.includes('this._destroyed = true;'));
        assert.ok(src.includes('if (this._destroyed)'));
        assert.ok(!src.includes('GLib.usleep'));
        const destroy = src.slice(src.indexOf('destroy() {'),
            src.indexOf('super.destroy()'));
        assert.ok(destroy.includes('this._settleIds'), destroy);
    });

test('the menu entry says it starts the deck program', () => {
    // It starts whichever program the settings name, not only the
    // controller.
    const src = extensionFile('indicators/device.js');
    assert.ok(src.includes("_('Start deck program')"));
    assert.ok(!src.includes('Open controller UI'));
    const fr = extensionFile('po/fr.po');
    for (const [msgid, msgstr] of [
        ['Start deck program', 'Démarrer le programme du deck'],
        ['The deck program did not start:',
            "Le programme du deck n'a pas démarré :"],
        ['the deck is held by', 'le deck est tenu par'],
        ['another program', 'un autre programme'],
        ['no visual Stream Deck is plugged in',
            "aucun Stream Deck à écran n'est branché"],
        ['its start condition is not met (DECK_PROGRAM=none, no venv or ' +
            'no Stream Deck plugged in)',
        "sa condition de démarrage n'est pas remplie (DECK_PROGRAM=none, " +
            'venv absent ou aucun Stream Deck branché)'],
    ]) {
        assert.ok(fr.includes(`msgid "${msgid}"\nmsgstr "${msgstr}"`), msgid);
        assert.ok(extensionFile('po/en.po').includes(
            `msgid "${msgid}"\nmsgstr "${msgid}"`), msgid);
        assert.ok(extensionFile('po/erplibre-home.pot').includes(
            `msgid "${msgid}"\nmsgstr ""`), msgid);
    }
    for (const po of ['po/erplibre-home.pot', 'po/en.po', 'po/fr.po'])
        assert.ok(!extensionFile(po).includes('Open controller UI'), po);
});
