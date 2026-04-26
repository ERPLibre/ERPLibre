import {test} from 'node:test';
import assert from 'node:assert/strict';
import {parseList, serializeList, pushRecent, MAX_RECENT}
    from '../../lib/settings.js';
import {migrateLegacyJson} from '../../lib/settings.js';

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

test('migrateLegacyJson seeds paths from erplibre_path', () => {
    const legacy = {erplibre_path: '/home/leo/erplibre'};
    const out = migrateLegacyJson(legacy, []);
    assert.equal(out.length, 1);
    assert.equal(out[0].path, '/home/leo/erplibre');
    assert.equal(out[0].label, 'ERPLibre');
    assert.match(out[0].id, /^[0-9a-f]{8}-/);
});

test('migrateLegacyJson is no-op when paths already populated', () => {
    const existing = [{id: 'x', label: 'L', path: '/p'}];
    const out = migrateLegacyJson({erplibre_path: '/other'}, existing);
    assert.deepEqual(out, existing);
});

test('migrateLegacyJson handles missing erplibre_path', () => {
    assert.deepEqual(migrateLegacyJson({}, []), []);
});

test('migrateLegacyJson tolerates corrupted legacy', () => {
    assert.deepEqual(migrateLegacyJson(null, []), []);
    assert.deepEqual(migrateLegacyJson('garbage', []), []);
});
