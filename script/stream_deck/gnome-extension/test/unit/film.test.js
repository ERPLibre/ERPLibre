import {test} from 'node:test';
import assert from 'node:assert/strict';
import {buildFilmLabel, defaultFilmEntry, validatePositionInput}
    from '../../lib/film-helpers.js';

test('buildFilmLabel joins fields with bullets', () => {
    assert.equal(
        buildFilmLabel({name: 'Foundation', episode: 'S2E5',
            position: '01:23:45'}),
        'Foundation · S2E5 · 01:23:45');
    assert.equal(
        buildFilmLabel({name: 'Solo', episode: '', position: ''}),
        'Solo');
    assert.equal(
        buildFilmLabel({name: 'Solo', episode: 'E1', position: ''}),
        'Solo · E1');
});

test('defaultFilmEntry stamps id + defaults', () => {
    const f = defaultFilmEntry({name: 'X', url: 'https://x'});
    assert.match(f.id, /^[0-9a-f]{8}-/);
    assert.equal(f.name, 'X');
    assert.equal(f.url, 'https://x');
    assert.equal(f.episode, '');
    assert.equal(f.position, '');
});

test('validatePositionInput accepts hh:mm:ss / mm:ss / seconds', () => {
    assert.equal(validatePositionInput(''), true);
    assert.equal(validatePositionInput('01:23:45'), true);
    assert.equal(validatePositionInput('5:30'), true);
    assert.equal(validatePositionInput('120'), true);
    assert.equal(validatePositionInput('1:2:3:4'), false);
    assert.equal(validatePositionInput('xx'), false);
});
