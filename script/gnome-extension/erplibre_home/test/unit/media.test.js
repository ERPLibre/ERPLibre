import {test} from 'node:test';
import assert from 'node:assert/strict';
import {buildMediaLabel, defaultMediaEntry, validatePositionInput,
    isSpotifyUrl, guessKind, normaliseKind, normaliseMediaUrl,
    nextEpisodeUrl, nextEpisodeLabel, extractMediaInfo,
    formatLastPlayed,
    positionToSeconds, formatProgress,
    groupBy, sortEntries, filterEntries}
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

test('normaliseMediaUrl: vimeo numeric id with various paths', () => {
    assert.equal(normaliseMediaUrl('https://vimeo.com/123456789'),
        'vimeo:123456789');
    assert.equal(normaliseMediaUrl('https://player.vimeo.com/video/123456789'),
        'vimeo:123456789');
    assert.equal(
        normaliseMediaUrl('https://vimeo.com/showcase/abc/video/123456789'),
        'vimeo:123456789');
});

test('normaliseMediaUrl: peertube watch / embed / w / bare uuid', () => {
    const uuid = '12345678-1234-1234-1234-123456789012';
    assert.equal(
        normaliseMediaUrl(`https://peer.example.org/videos/watch/${uuid}`),
        `peertube:peer.example.org:${uuid}`);
    assert.equal(
        normaliseMediaUrl(`https://peer.example.org/videos/embed/${uuid}`),
        `peertube:peer.example.org:${uuid}`);
    assert.equal(
        normaliseMediaUrl('https://peer.example.org/w/abc'),
        'peertube:peer.example.org:abc');
});

test('normaliseMediaUrl: dailymotion video / embed / dai.ly', () => {
    assert.equal(
        normaliseMediaUrl('https://www.dailymotion.com/video/x7tgad0'),
        'dailymotion:x7tgad0');
    assert.equal(
        normaliseMediaUrl('https://www.dailymotion.com/embed/video/x7tgad0'),
        'dailymotion:x7tgad0');
    assert.equal(normaliseMediaUrl('https://dai.ly/x7tgad0'),
        'dailymotion:x7tgad0');
});

test('normaliseMediaUrl: twitch vod and clips', () => {
    assert.equal(
        normaliseMediaUrl('https://www.twitch.tv/videos/123456789'),
        'twitch:vod:123456789');
    assert.equal(
        normaliseMediaUrl('https://clips.twitch.tv/AbcDefSlug'),
        'twitch:clip:AbcDefSlug');
    assert.equal(
        normaliseMediaUrl('https://twitch.tv/channel/clip/AbcDefSlug'),
        'twitch:clip:AbcDefSlug');
});

test('normaliseMediaUrl: odysee channel + title', () => {
    assert.equal(
        normaliseMediaUrl('https://odysee.com/@chan:1/title:5'),
        'odysee:@chan:title');
});

test('normaliseMediaUrl: rumble v-id', () => {
    assert.equal(
        normaliseMediaUrl('https://rumble.com/v3abc-some-slug.html'),
        'rumble:3abc');
});

test('normaliseMediaUrl: tiktok long + short forms', () => {
    assert.equal(
        normaliseMediaUrl('https://www.tiktok.com/@user/video/12345'),
        'tiktok:12345');
    assert.equal(
        normaliseMediaUrl('https://vm.tiktok.com/abcShort/'),
        'tiktok:short:abcShort');
});

test('normaliseMediaUrl: instagram reel / p / tv', () => {
    assert.equal(
        normaliseMediaUrl('https://www.instagram.com/reel/CABCdef/'),
        'instagram:reel:CABCdef');
    assert.equal(
        normaliseMediaUrl('https://www.instagram.com/p/CABCdef/'),
        'instagram:p:CABCdef');
});

test('normaliseMediaUrl: facebook watch / videos / fb.watch', () => {
    assert.equal(
        normaliseMediaUrl('https://www.facebook.com/watch/?v=12345'),
        'facebook:12345');
    assert.equal(
        normaliseMediaUrl('https://www.facebook.com/user/videos/12345/'),
        'facebook:12345');
    assert.equal(
        normaliseMediaUrl('https://fb.watch/abcShort/'),
        'facebook:short:abcShort');
});

test('normaliseMediaUrl: soundcloud track / set', () => {
    assert.equal(
        normaliseMediaUrl('https://soundcloud.com/Artist/MyTrack'),
        'soundcloud:artist:mytrack');
    assert.equal(
        normaliseMediaUrl('https://soundcloud.com/Artist/sets/MyPlaylist'),
        'soundcloud:set:artist:myplaylist');
});

test('normaliseMediaUrl: bandcamp track + album', () => {
    assert.equal(
        normaliseMediaUrl('https://artist.bandcamp.com/track/My-Song'),
        'bandcamp:artist:track:my-song');
    assert.equal(
        normaliseMediaUrl('https://artist.bandcamp.com/album/My-Album'),
        'bandcamp:artist:album:my-album');
});

test('normaliseMediaUrl: mixcloud user/show', () => {
    assert.equal(
        normaliseMediaUrl('https://www.mixcloud.com/User/My-Show/'),
        'mixcloud:user:my-show');
});

test('normaliseMediaUrl: tidal track / album / playlist', () => {
    assert.equal(
        normaliseMediaUrl('https://tidal.com/track/12345'),
        'tidal:track:12345');
    assert.equal(
        normaliseMediaUrl('https://tidal.com/browse/track/12345'),
        'tidal:track:12345');
    assert.equal(
        normaliseMediaUrl('https://tidal.com/album/67890'),
        'tidal:album:67890');
});

test('normaliseMediaUrl: deezer track with locale prefix', () => {
    assert.equal(
        normaliseMediaUrl('https://www.deezer.com/track/12345'),
        'deezer:track:12345');
    assert.equal(
        normaliseMediaUrl('https://www.deezer.com/fr/track/12345'),
        'deezer:track:12345');
    assert.equal(
        normaliseMediaUrl('https://www.deezer.com/en/album/67890'),
        'deezer:album:67890');
});

test('normaliseMediaUrl: tou.tv show + episode', () => {
    assert.equal(
        normaliseMediaUrl('https://ici.tou.tv/des-rumeurs-de-la-rue/S01E03'),
        'toutv:des-rumeurs-de-la-rue:s01e03');
    assert.equal(
        normaliseMediaUrl('https://ici.tou.tv/des-rumeurs-de-la-rue'),
        'toutv:des-rumeurs-de-la-rue');
    // Older host without 'ici.' prefix.
    assert.equal(
        normaliseMediaUrl('https://tou.tv/show-slug/S2E5'),
        'toutv:show-slug:s2e5');
});

test('normaliseMediaUrl: noovo emissions + videos', () => {
    assert.equal(
        normaliseMediaUrl(
            'https://noovo.ca/emissions/occupation-double/saison-12/episode-3'),
        'noovo:occupation-double:saison-12:episode-3');
    assert.equal(
        normaliseMediaUrl('https://noovo.ca/emissions/occupation-double'),
        'noovo:occupation-double');
    assert.equal(
        normaliseMediaUrl('https://www.noovo.ca/videos/abc-clip'),
        'noovo:video:abc-clip');
});

test('normaliseMediaUrl: telequebec show + episode', () => {
    assert.equal(
        normaliseMediaUrl('https://www.telequebec.tv/some-show'),
        'telequebec:some-show');
    assert.equal(
        normaliseMediaUrl('https://www.telequebec.tv/some-show/episode-1'),
        'telequebec:some-show:episode-1');
});

test('normaliseMediaUrl: tv5unis with or without /videos prefix', () => {
    assert.equal(
        normaliseMediaUrl('https://tv5unis.ca/videos/show/ep-1'),
        'tv5unis:show:ep-1');
    assert.equal(
        normaliseMediaUrl('https://www.tv5unis.ca/some-show/ep-2'),
        'tv5unis:some-show:ep-2');
});

test('normaliseMediaUrl: radio-canada ohdio balados', () => {
    assert.equal(
        normaliseMediaUrl(
            'https://ici.radio-canada.ca/ohdio/balados/Some-Slug/episode-1'),
        'ohdio:balados:some-slug:episode-1');
    assert.equal(
        normaliseMediaUrl(
            'https://ohdio.ca/balados/some-slug'),
        'ohdio:balados:some-slug');
});

test('normaliseMediaUrl: cbc gem show + episode', () => {
    assert.equal(
        normaliseMediaUrl('https://gem.cbc.ca/some-show/s01e01'),
        'cbcgem:some-show:s01e01');
    assert.equal(
        normaliseMediaUrl('https://gem.cbc.ca/media/some-show/12345'),
        'cbcgem:some-show:12345');
});

test('normaliseMediaUrl: vrai show + episode', () => {
    assert.equal(
        normaliseMediaUrl('https://vrai.ca/some-show'),
        'vrai:some-show');
    assert.equal(
        normaliseMediaUrl('https://www.vrai.ca/some-show/saison-1/ep-3'),
        'vrai:some-show:saison-1:ep-3');
});

test('normaliseMediaUrl: tvaplus modern + tva.ca/videos legacy', () => {
    assert.equal(
        normaliseMediaUrl('https://tvaplus.ca/series/some-show/ep-1'),
        'tvaplus:series:some-show:ep-1');
    assert.equal(
        normaliseMediaUrl('https://www.tvaplus.ca/series/some-show'),
        'tvaplus:series:some-show');
    assert.equal(
        normaliseMediaUrl('https://tva.ca/videos/some-clip-id'),
        'tvaplus:videos:some-clip-id');
});

test('normaliseMediaUrl: icimusique vanity + radio-canada path', () => {
    assert.equal(
        normaliseMediaUrl('https://icimusique.ca/balado/Some-Show'),
        'icimusique:balado:some-show');
    assert.equal(
        normaliseMediaUrl(
            'https://ici.radio-canada.ca/musique/balado/some-show/ep-1'),
        'icimusique:balado:some-show:ep-1');
});

test('normaliseMediaUrl: apple tv movie + show + episode', () => {
    assert.equal(
        normaliseMediaUrl(
            'https://tv.apple.com/us/movie/some-slug/umc.cmc.abc'),
        'appletv:movie:umc.cmc.abc');
    assert.equal(
        normaliseMediaUrl(
            'https://tv.apple.com/ca/show/some-slug/umc.cmc.xyz'),
        'appletv:show:umc.cmc.xyz');
});

test('normaliseMediaUrl: twitch live channel', () => {
    assert.equal(
        normaliseMediaUrl('https://www.twitch.tv/SomeStreamer'),
        'twitch:live:somestreamer');
});

test('normaliseMediaUrl: crave drops fr/en locale prefix', () => {
    assert.equal(
        normaliseMediaUrl('https://www.crave.ca/fr/series/some-show'),
        'crave:series:some-show');
    assert.equal(
        normaliseMediaUrl('https://www.crave.ca/en/series/some-show'),
        'crave:series:some-show');
});

test('normaliseMediaUrl: apple music album + track inside album', () => {
    assert.equal(
        normaliseMediaUrl(
            'https://music.apple.com/us/album/some-slug/1234567890'),
        'applemusic:album:1234567890');
    assert.equal(
        normaliseMediaUrl(
            'https://music.apple.com/us/album/some-slug/1234567890?i=99999'),
        'applemusic:album:1234567890:i:99999');
});

test('nextEpisodeUrl: SnnEnn compact pattern increments', () => {
    assert.equal(
        nextEpisodeUrl('https://ici.tou.tv/des-rumeurs-de-la-rue/S01E03'),
        'https://ici.tou.tv/des-rumeurs-de-la-rue/S01E04');
    assert.equal(
        nextEpisodeUrl('https://ici.tou.tv/show/s01e09'),
        'https://ici.tou.tv/show/s01e10');
});

test('nextEpisodeUrl: saison-N/episode-N pattern increments', () => {
    assert.equal(
        nextEpisodeUrl(
            'https://noovo.ca/emissions/od/saison-12/episode-3'),
        'https://noovo.ca/emissions/od/saison-12/episode-4');
});

test('nextEpisodeUrl: season prefix in English also works', () => {
    assert.equal(
        nextEpisodeUrl('https://example.com/show/season-2/episode-9'),
        'https://example.com/show/season-2/episode-10');
});

test('nextEpisodeUrl: zero-padded episode keeps padding width', () => {
    assert.equal(
        nextEpisodeUrl('https://x/show/S02E09'),
        'https://x/show/S02E10');
    assert.equal(
        nextEpisodeUrl('https://x/show/S02E099'),
        'https://x/show/S02E100');
});

test('nextEpisodeUrl: returns null when no episode marker', () => {
    assert.equal(nextEpisodeUrl('https://ici.tou.tv/des-rumeurs-de-la-rue'),
        null);
    assert.equal(nextEpisodeUrl('https://example.com/random/path'), null);
    assert.equal(nextEpisodeUrl(''), null);
    assert.equal(nextEpisodeUrl(null), null);
});

test('nextEpisodeLabel: appends or replaces SnnEnn tag in name', () => {
    assert.equal(
        nextEpisodeLabel('Show', 'http://x/S01E03', 'http://x/S01E04'),
        'Show — S01E04');
    assert.equal(
        nextEpisodeLabel('Show — S01E03',
            'http://x/S01E03', 'http://x/S01E04'),
        'Show — S01E04');
});

test('extractMediaInfo: tou.tv show + SnnEnn marker', () => {
    const r = extractMediaInfo(
        'https://ici.tou.tv/des-rumeurs-de-la-rue/S01E03');
    assert.equal(r.name, 'Des Rumeurs De La Rue');
    assert.equal(r.episode, 'S01E03');
});

test('extractMediaInfo: noovo emissions saison-N/episode-N', () => {
    const r = extractMediaInfo(
        'https://noovo.ca/emissions/occupation-double/saison-12/episode-3');
    assert.equal(r.name, 'Occupation Double');
    assert.equal(r.episode, 'S12E3');
});

test('extractMediaInfo: vimeo + youtube use id as placeholder name', () => {
    const v = extractMediaInfo('https://vimeo.com/123456789');
    assert.equal(v.name, 'Vimeo — 123456789');
    assert.equal(v.episode, '');
    const y = extractMediaInfo('https://www.youtube.com/watch?v=abc123');
    assert.equal(y.name, 'YouTube — abc123');
    assert.equal(y.episode, '');
});

test('extractMediaInfo: soundcloud user — track', () => {
    const r = extractMediaInfo(
        'https://soundcloud.com/some-artist/cool-track');
    assert.equal(r.name, 'Some Artist — Cool Track');
});

test('extractMediaInfo: bandcamp artist + track', () => {
    const r = extractMediaInfo(
        'https://artist.bandcamp.com/track/my-song');
    assert.equal(r.name, 'Artist — My Song');
});

test('extractMediaInfo: empty url returns empty fields', () => {
    const r = extractMediaInfo('');
    assert.equal(r.name, '');
    assert.equal(r.episode, '');
});

test('extractMediaInfo: generic URL falls back to last path segment', () => {
    const r = extractMediaInfo(
        'https://example.com/library/cool-documentary');
    assert.equal(r.name, 'Cool Documentary');
});

test('nextEpisodeLabel: appends Ép. tag for episode-N pattern', () => {
    assert.equal(
        nextEpisodeLabel('Show',
            'http://x/saison-1/episode-3',
            'http://x/saison-1/episode-4'),
        'Show — Ép. 4');
});

test('formatLastPlayed: empty / invalid input returns empty string', () => {
    assert.equal(formatLastPlayed(''), '');
    assert.equal(formatLastPlayed(null), '');
    assert.equal(formatLastPlayed(undefined), '');
    assert.equal(formatLastPlayed('not a date'), '');
});

test('formatLastPlayed: same day yields "today"', () => {
    const now = new Date('2026-04-30T15:00:00Z');
    const iso = '2026-04-30T08:30:00Z';
    assert.equal(formatLastPlayed(iso, now), 'today');
});

test('formatLastPlayed: previous day yields "yesterday"', () => {
    const now = new Date('2026-04-30T15:00:00Z');
    const iso = '2026-04-29T22:00:00Z';
    assert.equal(formatLastPlayed(iso, now), 'yesterday');
});

test('formatLastPlayed: older dates yield ISO short form', () => {
    const now = new Date('2026-04-30T15:00:00Z');
    const iso = '2026-04-15T10:00:00Z';
    assert.equal(formatLastPlayed(iso, now), '2026-04-15');
});

test('defaultMediaEntry: stores empty last_played by default', () => {
    const e = defaultMediaEntry({name: 'Foo', url: 'https://x'});
    assert.equal(e.last_played, '');
});

test('defaultMediaEntry: preserves provided last_played', () => {
    const e = defaultMediaEntry({name: 'Foo', url: 'https://x',
        last_played: '2026-04-30T15:00:00Z'});
    assert.equal(e.last_played, '2026-04-30T15:00:00Z');
});

test('defaultMediaEntry: extra fields default to empty/zero', () => {
    const e = defaultMediaEntry({name: 'Foo', url: 'https://x'});
    assert.equal(e.artist, '');
    assert.equal(e.album, '');
    assert.equal(e.year, '');
    assert.equal(e.genre, '');
    assert.equal(e.rating, 0);
    assert.equal(e.play_count, 0);
    assert.equal(e.duration, '');
    assert.deepEqual(e.tags, []);
    // added_at is auto-stamped; just check it parses as a Date.
    assert.ok(!isNaN(new Date(e.added_at).getTime()),
        `expected a valid ISO date, got ${e.added_at}`);
});

test('defaultMediaEntry: caller-provided extras win', () => {
    const e = defaultMediaEntry({
        name: 'Bar', url: 'https://x',
        artist: 'A', album: 'B', year: '2024', genre: 'rock',
        rating: 4, play_count: 7, duration: '00:42:00',
        added_at: '2026-04-30T15:00:00Z',
        tags: ['fav', 'workout'],
    });
    assert.equal(e.artist, 'A');
    assert.equal(e.album, 'B');
    assert.equal(e.year, '2024');
    assert.equal(e.genre, 'rock');
    assert.equal(e.rating, 4);
    assert.equal(e.play_count, 7);
    assert.equal(e.duration, '00:42:00');
    assert.equal(e.added_at, '2026-04-30T15:00:00Z');
    assert.deepEqual(e.tags, ['fav', 'workout']);
});

test('defaultMediaEntry: rating + play_count guard against NaN', () => {
    const e = defaultMediaEntry({
        name: 'X', url: 'https://x',
        rating: NaN, play_count: 'oops',
    });
    assert.equal(e.rating, 0);
    assert.equal(e.play_count, 0);
});

test('defaultMediaEntry: tags is copied (no aliasing)', () => {
    const src = ['a', 'b'];
    const e = defaultMediaEntry({name: 'X', url: 'https://x', tags: src});
    src.push('c');
    assert.deepEqual(e.tags, ['a', 'b']);
});

// ---------------------------------------------------------------
// positionToSeconds / formatProgress
// ---------------------------------------------------------------

test('positionToSeconds: parses hh:mm:ss / mm:ss / s', () => {
    assert.equal(positionToSeconds('01:23:45'), 1 * 3600 + 23 * 60 + 45);
    assert.equal(positionToSeconds('5:30'), 5 * 60 + 30);
    assert.equal(positionToSeconds('120'), 120);
    assert.equal(positionToSeconds(''), 0);
    assert.equal(positionToSeconds('xx'), 0);
    assert.equal(positionToSeconds(null), 0);
});

test('formatProgress: empty duration yields empty string', () => {
    assert.equal(formatProgress('1:00', ''), '');
    assert.equal(formatProgress('1:00', '0'), '');
});

test('formatProgress: clamps to 0..100%', () => {
    assert.equal(formatProgress('0', '100'), '▯▯▯▯▯ 0%');
    assert.equal(formatProgress('100', '100'), '▮▮▮▮▮ 100%');
    // Position past duration should clamp, not overflow.
    assert.equal(formatProgress('200', '100'), '▮▮▮▮▮ 100%');
});

test('formatProgress: midway renders partial fill', () => {
    // 0:30 / 1:00 = 50%, 5 cells -> 3 (rounded from 2.5).
    assert.equal(formatProgress('30', '60'), '▮▮▮▯▯ 50%');
});

// ---------------------------------------------------------------
// groupBy
// ---------------------------------------------------------------

test('groupBy: empty key bucket = single group', () => {
    const list = [{name: 'a'}, {name: 'b'}];
    const m = groupBy(list, '');
    assert.equal(m.size, 1);
    assert.deepEqual(m.get(''), list);
});

test('groupBy: by artist, blank values bucket together', () => {
    const list = [
        {name: 'a', artist: 'Foo'},
        {name: 'b', artist: '  '},
        {name: 'c', artist: 'Foo'},
        {name: 'd', artist: 'Bar'},
        {name: 'e'},
    ];
    const m = groupBy(list, 'artist');
    assert.deepEqual([...m.keys()], ['Foo', '', 'Bar']);
    assert.equal(m.get('Foo').length, 2);
    assert.equal(m.get('Bar').length, 1);
    // Blank artist + missing artist share the same bucket.
    assert.equal(m.get('').length, 2);
});

test('groupBy: handles non-array input safely', () => {
    assert.equal(groupBy(null, 'artist').size, 0);
    assert.equal(groupBy(undefined, 'artist').size, 0);
});

// ---------------------------------------------------------------
// sortEntries
// ---------------------------------------------------------------

test('sortEntries: last_played desc, empty values last', () => {
    const list = [
        {name: 'a', last_played: '2026-04-01T00:00:00Z'},
        {name: 'b', last_played: ''},
        {name: 'c', last_played: '2026-04-15T00:00:00Z'},
        {name: 'd'},
    ];
    const sorted = sortEntries(list, 'last_played').map(e => e.name);
    assert.deepEqual(sorted, ['c', 'a', 'b', 'd']);
});

test('sortEntries: alpha is locale + case insensitive', () => {
    const list = [{name: 'banana'}, {name: 'Apple'}, {name: 'éclair'}];
    const sorted = sortEntries(list, 'alpha').map(e => e.name);
    assert.deepEqual(sorted, ['Apple', 'banana', 'éclair']);
});

test('sortEntries: play_count desc, ties → last_played → alpha', () => {
    const list = [
        {name: 'a', play_count: 1, last_played: '2026-04-01'},
        {name: 'b', play_count: 5, last_played: '2026-04-10'},
        {name: 'c', play_count: 5, last_played: '2026-04-15'},
        {name: 'd', play_count: 5, last_played: '2026-04-15'},
    ];
    const sorted = sortEntries(list, 'play_count').map(e => e.name);
    // c and d tie on count + date → alpha picks c, d.
    assert.deepEqual(sorted, ['c', 'd', 'b', 'a']);
});

test('sortEntries: rating desc, NaN treated as 0', () => {
    const list = [
        {name: 'a', rating: 5},
        {name: 'b', rating: NaN},
        {name: 'c', rating: 3},
        {name: 'd'},
    ];
    const sorted = sortEntries(list, 'rating').map(e => e.name);
    assert.deepEqual(sorted, ['a', 'c', 'b', 'd']);
});

test('sortEntries: unknown mode falls back to alpha', () => {
    const list = [{name: 'b'}, {name: 'a'}];
    assert.deepEqual(
        sortEntries(list, 'wat').map(e => e.name),
        ['a', 'b']);
});

test('sortEntries: does not mutate input', () => {
    const list = [{name: 'b'}, {name: 'a'}];
    const before = [...list];
    sortEntries(list, 'alpha');
    assert.deepEqual(list, before);
});

// ---------------------------------------------------------------
// filterEntries
// ---------------------------------------------------------------

test('filterEntries: kind filter matches normalised kind', () => {
    const list = [
        {name: 'v1', kind: 'video'},
        {name: 'a1', kind: 'audio'},
        {name: 'x',  kind: 'something'},
    ];
    assert.equal(filterEntries(list, {kind: 'video'}).length, 2);
    assert.equal(filterEntries(list, {kind: 'audio'}).length, 1);
    assert.equal(filterEntries(list, {kind: 'oops'}).length, 3);
});

test('filterEntries: query is case-insensitive substring across fields', () => {
    const list = [
        {name: 'Foundation', artist: 'Asimov'},
        {name: 'Dune',       artist: 'Herbert', album: 'Sci-Fi'},
        {name: 'Other'},
        {name: 'tagged',     tags: ['workout']},
    ];
    assert.equal(filterEntries(list, {query: 'asim'}).length, 1);
    assert.equal(filterEntries(list, {query: 'sci'}).length, 1);
    assert.equal(filterEntries(list, {query: 'WORK'}).length, 1);
    assert.equal(filterEntries(list, {query: '   '}).length, 4);
    assert.equal(filterEntries(list, {query: 'nope'}).length, 0);
});

test('filterEntries: unwatched keeps only entries without last_played', () => {
    const list = [
        {name: 'a'},
        {name: 'b', last_played: ''},
        {name: 'c', last_played: '2026-04-01'},
    ];
    assert.equal(filterEntries(list, {unwatched: true}).length, 2);
});

test('filterEntries: unfinished requires position + stale last_played', () => {
    const now = new Date('2026-05-01T00:00:00Z');
    const list = [
        // position + stale → keep
        {name: 'a', position: '5:00', last_played: '2026-04-01T00:00:00Z'},
        // position + recent → drop
        {name: 'b', position: '5:00', last_played: '2026-04-30T00:00:00Z'},
        // no position → drop
        {name: 'c', last_played: '2026-04-01T00:00:00Z'},
        // position + never played → keep (treated as stale)
        {name: 'd', position: '5:00'},
    ];
    const got = filterEntries(list, {unfinished: true}, now)
        .map(e => e.name);
    assert.deepEqual(got, ['a', 'd']);
});

test('filterEntries: favourites requires rating >= 4', () => {
    const list = [
        {name: 'a', rating: 5},
        {name: 'b', rating: 4},
        {name: 'c', rating: 3},
        {name: 'd'},
    ];
    const got = filterEntries(list, {favourites: true}).map(e => e.name);
    assert.deepEqual(got, ['a', 'b']);
});

test('filterEntries: flags compose with AND', () => {
    const now = new Date('2026-05-01T00:00:00Z');
    const list = [
        {name: 'hit', kind: 'audio', rating: 5,
            position: '1:00', last_played: '2026-04-01'},
        {name: 'miss-kind', kind: 'video', rating: 5,
            position: '1:00', last_played: '2026-04-01'},
        {name: 'miss-rating', kind: 'audio', rating: 1,
            position: '1:00', last_played: '2026-04-01'},
    ];
    const got = filterEntries(list, {
        kind: 'audio', favourites: true, unfinished: true,
    }, now).map(e => e.name);
    assert.deepEqual(got, ['hit']);
});

// ---------------------------------------------------------------
// extractMediaInfo: artist / album for music URLs
// ---------------------------------------------------------------

test('extractMediaInfo: result has artist + album fields by default', () => {
    const r = extractMediaInfo('https://example.com/foo');
    assert.equal(r.artist, '');
    assert.equal(r.album, '');
});

test('extractMediaInfo: soundcloud track sets artist (no album)', () => {
    const r = extractMediaInfo(
        'https://soundcloud.com/some-artist/cool-track');
    assert.equal(r.artist, 'Some Artist');
    assert.equal(r.album, '');
    // Name shape is unchanged for backwards compatibility.
    assert.equal(r.name, 'Some Artist — Cool Track');
});

test('extractMediaInfo: soundcloud /sets/ populates album', () => {
    const r = extractMediaInfo(
        'https://soundcloud.com/some-artist/sets/summer-mix');
    assert.equal(r.artist, 'Some Artist');
    assert.equal(r.album, 'Summer Mix');
});

test('extractMediaInfo: bandcamp /track/ sets artist only', () => {
    const r = extractMediaInfo(
        'https://artist.bandcamp.com/track/my-song');
    assert.equal(r.artist, 'Artist');
    assert.equal(r.album, '');
});

test('extractMediaInfo: bandcamp /album/ sets artist + album', () => {
    const r = extractMediaInfo(
        'https://artist.bandcamp.com/album/great-record');
    assert.equal(r.artist, 'Artist');
    assert.equal(r.album, 'Great Record');
    assert.equal(r.name, 'Artist — Great Record');
});

test('extractMediaInfo: mixcloud user/show', () => {
    const r = extractMediaInfo(
        'https://www.mixcloud.com/dj-foo/late-night-set/');
    assert.equal(r.artist, 'Dj Foo');
    assert.equal(r.name, 'Dj Foo — Late Night Set');
});

test('extractMediaInfo: apple music album sets album field', () => {
    const r = extractMediaInfo(
        'https://music.apple.com/us/album/great-record/12345?i=67890');
    assert.equal(r.album, 'Great Record');
    assert.equal(r.name, 'Apple Music — Great Record');
});

test('extractMediaInfo: video hosts do not populate music fields', () => {
    const r = extractMediaInfo('https://vimeo.com/123456789');
    assert.equal(r.artist, '');
    assert.equal(r.album, '');
});
