import {test} from 'node:test';
import assert from 'node:assert/strict';
import {launchRefusal, galleryTargets} from '../../lib/gallery-launch.js';

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

const ROOT = '/opt/depot';
const yes = () => true;

test('galleryTargets: the checkout of the extension comes first', () => {
    const paths = [{label: 'Other', path: '/srv/autre'}];
    assert.deepEqual(galleryTargets(ROOT, paths, yes), [
        {path: ROOT, label: '', own: true, ready: true},
        {path: '/srv/autre', label: 'Other', own: false, ready: true},
    ]);
});

test('galleryTargets: a configured checkout appears once, as its own', () => {
    const paths = [
        {label: 'Here', path: `${ROOT}/`},
        {label: '', path: '/srv/autre'},
        {label: 'Twice', path: '/srv/autre//'},
    ];
    const targets = galleryTargets(ROOT, paths, yes);
    assert.deepEqual(targets.map((t) => [t.path, t.own]),
        [[ROOT, true], ['/srv/autre', false]]);
});

test('galleryTargets: ready comes from the callback, a throw is false', () => {
    const paths = [{path: '/srv/a'}, {path: '/srv/b'}];
    const ready = (p) => {
        if (p === '/srv/b') throw new Error('stat');
        return p === ROOT;
    };
    assert.deepEqual(galleryTargets(ROOT, paths, ready).map((t) => t.ready),
        [true, false, false]);
});

test('galleryTargets: no root, blank or missing paths are skipped', () => {
    const paths = [{path: ''}, {label: 'x'}, null, {path: '/srv/a'}];
    assert.deepEqual(galleryTargets('', paths, yes),
        [{path: '/srv/a', label: '', own: false, ready: true}]);
    assert.deepEqual(galleryTargets('', [], yes), []);
    assert.deepEqual(galleryTargets(ROOT, undefined, yes).length, 1);
});
