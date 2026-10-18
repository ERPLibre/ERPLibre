import {test} from 'node:test';
import assert from 'node:assert/strict';
import {launchRefusal} from '../../lib/gallery-launch.js';

test('launchRefusal: a 2xx answer is no refusal', () => {
    assert.equal(launchRefusal(200, '{"ok": true}'), null);
    assert.equal(launchRefusal(204, ''), null);
});

test('launchRefusal: 403 gives the gallery error line', () => {
    const body = JSON.stringify({error: 'Games are disabled (GAMES=off).'});
    assert.equal(launchRefusal(403, body),
        'Games are disabled (GAMES=off).');
});

test('launchRefusal: 404 gives the gallery error line', () => {
    const body = JSON.stringify({error: 'Game not found: nope'});
    assert.equal(launchRefusal(404, body), 'Game not found: nope');
});

test('launchRefusal: a body without error falls back on the status', () => {
    assert.equal(launchRefusal(500, 'oops'), 'HTTP 500');
    assert.equal(launchRefusal(500, '{"error": 3}'), 'HTTP 500');
    assert.equal(launchRefusal(500, '{"error": "  "}'), 'HTTP 500');
    assert.equal(launchRefusal(502, null), 'HTTP 502');
});
