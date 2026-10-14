import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {parseLsusbVerbose} from '../../lib/usb.js';

const fx = readFileSync(
    new URL('../fixtures/lsusb-elgato.txt', import.meta.url), 'utf8');

test('parseLsusbVerbose finds two Elgato devices', () => {
    const devs = parseLsusbVerbose(fx);
    assert.equal(devs.length, 2);
    assert.equal(devs[0].product, 'Stream Deck XL');
    assert.equal(devs[0].serial, 'AL01K1A12345');
    assert.equal(devs[0].bus, '003');
    assert.equal(devs[0].device, '010');
    assert.equal(devs[1].product, 'Stream Deck Mini');
});

test('parseLsusbVerbose handles empty input', () => {
    assert.deepEqual(parseLsusbVerbose(''), []);
});
