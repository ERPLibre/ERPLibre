import {test} from 'node:test';
import assert from 'node:assert/strict';
import {parseList, serializeList, pushRecent, MAX_RECENT}
    from '../../lib/settings.js';

test('parseList returns [] on bad JSON', () => {
    assert.deepEqual(parseList('not json'), []);
    assert.deepEqual(parseList(''), []);
    assert.deepEqual(parseList('null'), []);
});

test('parseList returns array on valid JSON array', () => {
    assert.deepEqual(parseList('[{"a":1}]'), [{a: 1}]);
});

test('parseList returns [] when JSON is not an array', () => {
    assert.deepEqual(parseList('{"x":1}'), []);
    assert.deepEqual(parseList('"string"'), []);
});

test('serializeList round-trips', () => {
    const data = [{a: 1}, {b: 'two'}];
    assert.deepEqual(parseList(serializeList(data)), data);
});

test('pushRecent prepends + dedupes + caps', () => {
    let r = [];
    for (let i = 0; i < MAX_RECENT + 3; i++) r = pushRecent(r, `/p${i}`);
    assert.equal(r.length, MAX_RECENT);
    assert.equal(r[0], `/p${MAX_RECENT + 2}`);
});

test('pushRecent moves duplicate to front', () => {
    const r = pushRecent(['/a', '/b', '/c'], '/b');
    assert.deepEqual(r, ['/b', '/a', '/c']);
});
