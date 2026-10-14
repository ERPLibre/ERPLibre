import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DECK_UNIT, CONTROLLER_REL, DECK_ENTRY_REL, deckUnitPath,
    openDeckArgv, restartDeckArgv, deckStateArgv, deckRunning, deckCheckArgv,
    deckStartFailure} from '../../lib/deck-service.js';

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
        ['systemctl', '--user', 'show', '-p', 'ActiveState', '--value',
            DECK_UNIT]);
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
    assert.ok(src.includes('deckStartFailure('));
    assert.ok(src.includes('deckUnitPath(GLib.get_user_config_dir())'));
    assert.ok(!src.includes("const CONTROLLER_REL"));
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
