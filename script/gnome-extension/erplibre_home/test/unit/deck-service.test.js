import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DECK_UNIT, CONTROLLER_REL, deckUnitPath, openDeckArgv,
    restartDeckArgv} from '../../lib/deck-service.js';

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

test('the device indicator takes both argv from this module', () => {
    const src = extensionFile('indicators/device.js');
    assert.ok(src.includes("from '../lib/deck-service.js'"));
    assert.ok(src.includes('openDeckArgv('));
    assert.ok(src.includes('restartDeckArgv('));
    assert.ok(src.includes('deckUnitPath(GLib.get_user_config_dir())'));
    assert.ok(!src.includes("const CONTROLLER_REL"));
});
