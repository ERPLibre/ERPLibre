import {test} from 'node:test';
import assert from 'node:assert/strict';
import {migrateFilmToMedia, runSchemaMigrations, CURRENT_VERSION}
    from '../../lib/migrations.js';

function mockSettings(initial = {}) {
    const data = {
        'schema-version': 1,
        'enable-film': true,
        'enable-media': true,
        'films': '[]',
        'media': '[]',
        ...initial,
    };
    return {
        get_string: k => String(data[k] ?? ''),
        set_string: (k, v) => { data[k] = String(v); },
        get_boolean: k => Boolean(data[k]),
        set_boolean: (k, v) => { data[k] = !!v; },
        get_int: k => Number(data[k] ?? 0),
        set_int: (k, v) => { data[k] = Number(v); },
        _data: data,
    };
}

test('migrateFilmToMedia: copies films into media tagging kind=video', () => {
    const s = mockSettings({
        films: JSON.stringify([
            {id: '1', name: 'A', url: 'https://a/x', episode: '', position: ''},
            {id: '2', name: 'B', url: 'https://b/y', episode: '', position: ''},
        ]),
    });
    migrateFilmToMedia(s);
    const media = JSON.parse(s.get_string('media'));
    assert.equal(media.length, 2);
    assert.equal(media[0].kind, 'video');
    assert.equal(media[0].name, 'A');
});

test('migrateFilmToMedia: preserves existing kind on entries', () => {
    const s = mockSettings({
        films: JSON.stringify([
            {id: '1', name: 'song', url: 'spotify:track:x', kind: 'audio'},
        ]),
    });
    migrateFilmToMedia(s);
    const media = JSON.parse(s.get_string('media'));
    assert.equal(media[0].kind, 'audio');
});

test('migrateFilmToMedia: does not clobber a non-empty media key', () => {
    const s = mockSettings({
        films: JSON.stringify([{id: '1', name: 'A', url: 'x'}]),
        media: JSON.stringify([{id: '99', name: 'kept'}]),
    });
    migrateFilmToMedia(s);
    const media = JSON.parse(s.get_string('media'));
    assert.equal(media.length, 1);
    assert.equal(media[0].name, 'kept');
});

test('migrateFilmToMedia: mirrors enable-film=false to enable-media', () => {
    const s = mockSettings({'enable-film': false});
    migrateFilmToMedia(s);
    assert.equal(s.get_boolean('enable-media'), false);
});

test('migrateFilmToMedia: enable-film=true leaves enable-media alone', () => {
    const s = mockSettings({'enable-film': true, 'enable-media': false});
    migrateFilmToMedia(s);
    assert.equal(s.get_boolean('enable-media'), false);
});

test('runSchemaMigrations: bumps schema-version to current', () => {
    const s = mockSettings({
        films: JSON.stringify([{id: '1', name: 'A', url: 'x'}]),
    });
    const v = runSchemaMigrations(s);
    assert.equal(v, CURRENT_VERSION);
    assert.equal(s.get_int('schema-version'), CURRENT_VERSION);
});

test('runSchemaMigrations: idempotent on already-current data', () => {
    const s = mockSettings({'schema-version': CURRENT_VERSION});
    let logs = 0;
    const v = runSchemaMigrations(s, () => { logs += 1; });
    assert.equal(v, CURRENT_VERSION);
    assert.equal(logs, 0);
});

test('runSchemaMigrations: stops on a missing migration step', () => {
    const s = mockSettings({'schema-version': 99});
    const logged = [];
    const v = runSchemaMigrations(s, m => logged.push(m));
    // 99 > CURRENT_VERSION → loop body skipped, no-op.
    assert.equal(v, 99);
    assert.equal(logged.length, 0);
});

test('runSchemaMigrations: fault keeps version pinned for retry', () => {
    const s = mockSettings();
    s.set_string = () => { throw new Error('boom'); };
    const logged = [];
    const v = runSchemaMigrations(s, m => logged.push(m));
    assert.equal(v, 1);
    assert.equal(s.get_int('schema-version'), 1);
    assert.ok(logged.some(m => m.includes('failed')));
});
