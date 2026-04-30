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
