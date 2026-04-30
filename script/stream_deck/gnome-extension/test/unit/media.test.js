import {test} from 'node:test';
import assert from 'node:assert/strict';
import {buildMediaLabel, defaultMediaEntry, validatePositionInput,
    isSpotifyUrl, guessKind, normaliseKind, normaliseMediaUrl}
    from '../../lib/media-helpers.js';

test('buildMediaLabel joins fields with bullets', () => {
    assert.equal(
        buildMediaLabel({name: 'Foundation', episode: 'S2E5',
            position: '01:23:45'}),
        'Foundation · S2E5 · 01:23:45');
    assert.equal(
        buildMediaLabel({name: 'Solo', episode: '', position: ''}),
        'Solo');
    assert.equal(
        buildMediaLabel({name: 'Solo', episode: 'E1', position: ''}),
        'Solo · E1');
});

test('defaultMediaEntry stamps id + defaults', () => {
    const f = defaultMediaEntry({name: 'X', url: 'https://x'});
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

test('defaultMediaEntry: auto-tags spotify URL as audio', () => {
    const e = defaultMediaEntry({name: 'song',
        url: 'https://open.spotify.com/track/abc'});
    assert.equal(e.kind, 'audio');
});

test('defaultMediaEntry: explicit kind wins', () => {
    const e = defaultMediaEntry({name: 'video',
        url: 'https://example.com/song.mp3', kind: 'video'});
    assert.equal(e.kind, 'video');
});

test('normaliseMediaUrl: empty input', () => {
    assert.equal(normaliseMediaUrl(''), '');
    assert.equal(normaliseMediaUrl(null), '');
    assert.equal(normaliseMediaUrl(undefined), '');
    assert.equal(normaliseMediaUrl('   '), '');
});

test('normaliseMediaUrl: youtube watch + youtu.be collapse to same key',
() => {
    const a = normaliseMediaUrl('https://www.youtube.com/watch?v=abc123');
    const b = normaliseMediaUrl('https://youtube.com/watch?v=abc123');
    const c = normaliseMediaUrl('https://m.youtube.com/watch?v=abc123');
    const d = normaliseMediaUrl('https://music.youtube.com/watch?v=abc123');
    const e = normaliseMediaUrl('https://youtu.be/abc123');
    const f = normaliseMediaUrl('https://youtu.be/abc123?t=42');
    assert.equal(a, 'youtube:abc123');
    assert.equal(b, 'youtube:abc123');
    assert.equal(c, 'youtube:abc123');
    assert.equal(d, 'youtube:abc123');
    assert.equal(e, 'youtube:abc123');
    assert.equal(f, 'youtube:abc123');
});

test('normaliseMediaUrl: youtube tracking params and playlists ignored',
() => {
    assert.equal(
        normaliseMediaUrl(
            'https://youtube.com/watch?v=abc&list=L&utm_source=foo'),
        'youtube:abc');
    assert.equal(
        normaliseMediaUrl('https://youtube.com/watch?v=abc&t=10s'),
        'youtube:abc');
});

test('normaliseMediaUrl: youtube shorts and embed', () => {
    assert.equal(
        normaliseMediaUrl('https://www.youtube.com/shorts/xyz789'),
        'youtube:xyz789');
    assert.equal(
        normaliseMediaUrl('https://www.youtube.com/embed/xyz789'),
        'youtube:xyz789');
});

test('normaliseMediaUrl: spotify URI and web link match', () => {
    assert.equal(normaliseMediaUrl('spotify:track:xyz'), 'spotify:track:xyz');
    assert.equal(
        normaliseMediaUrl('https://open.spotify.com/track/xyz'),
        'spotify:track:xyz');
    assert.equal(
        normaliseMediaUrl('https://open.spotify.com/track/xyz?si=abc'),
        'spotify:track:xyz');
});

test('normaliseMediaUrl: spotify supports album / playlist / episode', () => {
    assert.equal(
        normaliseMediaUrl('https://open.spotify.com/album/abc'),
        'spotify:album:abc');
    assert.equal(
        normaliseMediaUrl('https://open.spotify.com/playlist/abc'),
        'spotify:playlist:abc');
    assert.equal(
        normaliseMediaUrl('https://open.spotify.com/episode/abc'),
        'spotify:episode:abc');
});

test('normaliseMediaUrl: generic URLs lower-case host + drop query', () => {
    assert.equal(
        normaliseMediaUrl('HTTPS://Example.COM/A.mp3?utm=foo'),
        'https://example.com/a.mp3');
    assert.equal(
        normaliseMediaUrl('https://example.com/path/'),
        'https://example.com/path');
});

test('normaliseMediaUrl: malformed URL falls back to lowercase', () => {
    assert.equal(normaliseMediaUrl('not a url'), 'not a url');
    assert.equal(normaliseMediaUrl('Random TEXT'), 'random text');
});
