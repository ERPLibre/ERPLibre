import {test} from 'node:test';
import assert from 'node:assert/strict';
import {buildFilmLabel, defaultFilmEntry, validatePositionInput,
    isSpotifyUrl, guessKind, normaliseKind}
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

test('isSpotifyUrl: catches URI scheme + open.spotify.com', () => {
    assert.equal(isSpotifyUrl('spotify:track:abc'), true);
    assert.equal(isSpotifyUrl('spotify:album:xyz'), true);
    assert.equal(isSpotifyUrl('https://open.spotify.com/track/abc'), true);
    assert.equal(isSpotifyUrl('https://www.youtube.com/watch?v=x'), false);
    assert.equal(isSpotifyUrl(''), false);
    assert.equal(isSpotifyUrl(null), false);
});

test('guessKind: spotify and audio extensions land on audio', () => {
    assert.equal(guessKind('spotify:track:abc'), 'audio');
    assert.equal(guessKind('https://open.spotify.com/playlist/x'), 'audio');
    assert.equal(guessKind('https://example.com/song.mp3'), 'audio');
    assert.equal(guessKind('https://example.com/track.flac?x=1'), 'audio');
    assert.equal(guessKind('https://example.com/clip.opus'), 'audio');
});

test('guessKind: video URLs default to video', () => {
    assert.equal(guessKind('https://www.youtube.com/watch?v=x'), 'video');
    assert.equal(guessKind('https://example.com/movie.mkv'), 'video');
    assert.equal(guessKind(''), 'video');
});

test('normaliseKind: collapses to video unless explicitly audio', () => {
    assert.equal(normaliseKind('audio'), 'audio');
    assert.equal(normaliseKind('video'), 'video');
    assert.equal(normaliseKind('something-else'), 'video');
    assert.equal(normaliseKind(undefined), 'video');
});

test('defaultFilmEntry: auto-tags spotify URL as audio', () => {
    const e = defaultFilmEntry({name: 'song',
        url: 'https://open.spotify.com/track/abc'});
    assert.equal(e.kind, 'audio');
});

test('defaultFilmEntry: explicit kind wins', () => {
    const e = defaultFilmEntry({name: 'video',
        url: 'https://example.com/song.mp3', kind: 'video'});
    assert.equal(e.kind, 'video');
});
