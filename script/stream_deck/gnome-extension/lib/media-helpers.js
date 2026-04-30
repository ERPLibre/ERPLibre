/**
 * Media helpers (video + audio entries). Pure JS so they can be
 * tested via node --test without pulling in GJS imports.
 *
 * The GJS indicator class lives in indicators/media.js and imports
 * from here.
 */

import {uuid4} from './settings.js';

export function buildMediaLabel(entry) {
    const parts = [entry?.name || ''];
    if (entry?.episode && entry.episode.trim() !== '') parts.push(entry.episode);
    if (entry?.position && entry.position.trim() !== '') parts.push(entry.position);
    return parts.filter(Boolean).join(' · ');
}

export function defaultMediaEntry({name = '', url = '', episode = '',
    position = '', kind = ''} = {}) {
    return {id: uuid4(), name, url, episode, position,
        kind: kind || guessKind(url)};
}

export function validatePositionInput(text) {
    if (typeof text !== 'string' || text === '') return true;
    return /^\d+(:\d+){0,2}$/.test(text.trim());
}

const _AUDIO_EXT_RE = /\.(mp3|flac|ogg|opus|m4a|wav|aac|wma|aif{1,2})(\?|#|$)/i;

/** Detect Spotify URIs and Spotify web links. */
export function isSpotifyUrl(url) {
    const s = String(url || '');
    return /^spotify:/i.test(s) || /open\.spotify\.com\//i.test(s);
}

/**
 * Pick `'audio'` vs `'video'` based on URL signal alone. Used as the
 * default `kind` when the user does not pick one explicitly.
 */
export function guessKind(url) {
    const s = String(url || '').trim();
    if (!s) return 'video';
    if (isSpotifyUrl(s)) return 'audio';
    if (_AUDIO_EXT_RE.test(s)) return 'audio';
    if (/(?:\bsoundcloud\.com|\bbandcamp\.com|\bdeezer\.com|\b)tidal\.com/i
            .test(s)) return 'audio';
    return 'video';
}

export function normaliseKind(kind) {
    return kind === 'audio' ? 'audio' : 'video';
}

const _YT_HOSTS = /^(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)$/i;
const _PEERTUBE_UUID =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function _stripWww(host) {
    return (host || '').replace(/^www\./, '');
}

/**
 * Reduce a media URL to a canonical form so two equivalent links
 * dedupe to the same key. Strips tracking params and timestamps,
 * extracts video / track ids when the host is known, lowercases
 * everything that is not an identifier.
 *
 * Recognised platforms (in order): YouTube, Vimeo, PeerTube,
 * Dailymotion, Twitch (VOD + clip), Odysee, Rumble, TikTok,
 * Instagram, Facebook, Spotify (URI + web), SoundCloud, Bandcamp,
 * Mixcloud, Tidal, Deezer, Apple Music. Anything else falls back
 * to scheme + host + lowercased path with the query/fragment
 * stripped.
 */
export function normaliseMediaUrl(url) {
    const raw = String(url || '').trim();
    if (!raw) return '';

    const spURI = /^spotify:([a-z]+):([A-Za-z0-9]+)/i.exec(raw);
    if (spURI) return `spotify:${spURI[1].toLowerCase()}:${spURI[2]}`;

    let u;
    try { u = new URL(raw); }
    catch (_e) { return raw.toLowerCase(); }

    const host = (u.hostname || '').toLowerCase();
    const path = u.pathname || '';
    const seg = path.split('/').filter(Boolean);

    // ---- Video ----

    if (_YT_HOSTS.test(host)) {
        let id = '';
        if (host.endsWith('youtu.be')) id = seg[0] || '';
        else if (path === '/watch') id = u.searchParams.get('v') || '';
        else if (seg[0] === 'shorts' || seg[0] === 'embed') id = seg[1] || '';
        if (id) return `youtube:${id}`;
    }

    if (host === 'vimeo.com' || host === 'player.vimeo.com') {
        // /{id}, /showcase/X/video/{id}, /video/{id}
        const id = seg.findLast?.(s => /^\d+$/.test(s))
            ?? [...seg].reverse().find(s => /^\d+$/.test(s));
        if (id) return `vimeo:${id}`;
    }

    // PeerTube is federated: any host can serve a video. Detect by
    // the standard URL shapes /videos/watch/{uuid}, /w/{shortid},
    // /videos/embed/{uuid}, and dedupe within the same instance —
    // cross-instance dedupe needs an API call we don't make here.
    if (seg[0] === 'videos' && (seg[1] === 'watch' || seg[1] === 'embed')) {
        const id = seg[2];
        if (id) return `peertube:${host}:${id}`;
    }
    if (seg[0] === 'w' && seg[1]) {
        return `peertube:${host}:${seg[1]}`;
    }
    // Bare UUID path on a peertube-looking host (some embeds).
    if (seg.length === 1 && _PEERTUBE_UUID.test(seg[0]) && host.includes('.')) {
        return `peertube:${host}:${seg[0]}`;
    }

    if (host === 'dailymotion.com' || host === 'www.dailymotion.com') {
        if (seg[0] === 'video' && seg[1]) return `dailymotion:${seg[1]}`;
        if (seg[0] === 'embed' && seg[1] === 'video' && seg[2])
            return `dailymotion:${seg[2]}`;
    }
    if (host === 'dai.ly') {
        if (seg[0]) return `dailymotion:${seg[0]}`;
    }

    if (host === 'twitch.tv' || host === 'www.twitch.tv') {
        if (seg[0] === 'videos' && seg[1]) return `twitch:vod:${seg[1]}`;
        if (seg[1] === 'clip' && seg[2]) return `twitch:clip:${seg[2]}`;
    }
    if (host === 'clips.twitch.tv' && seg[0]) return `twitch:clip:${seg[0]}`;

    if (host === 'odysee.com' || host === 'www.odysee.com') {
        if (seg.length >= 2) {
            const channel = seg[0].split(':')[0].toLowerCase();
            const title = seg[1].split(':')[0].toLowerCase();
            return `odysee:${channel}:${title}`;
        }
    }

    if (host === 'rumble.com' || host === 'www.rumble.com') {
        if (seg[0]) {
            // /v{id}-{slug}.html  or /v{id}-{slug}
            const m = /^v([a-z0-9]+)/i.exec(seg[0]);
            if (m) return `rumble:${m[1]}`;
        }
    }

    if (host === 'tiktok.com' || host === 'www.tiktok.com') {
        if (seg[0]?.startsWith('@') && seg[1] === 'video' && seg[2])
            return `tiktok:${seg[2]}`;
    }
    if (host === 'vm.tiktok.com' && seg[0])
        return `tiktok:short:${seg[0]}`;

    if (host === 'instagram.com' || host === 'www.instagram.com') {
        if ((seg[0] === 'reel' || seg[0] === 'p' || seg[0] === 'tv')
                && seg[1])
            return `instagram:${seg[0]}:${seg[1]}`;
    }

    if (host === 'facebook.com' || host === 'www.facebook.com') {
        const v = u.searchParams.get('v');
        if (v) return `facebook:${v}`;
        if (seg[1] === 'videos' && seg[2]) return `facebook:${seg[2]}`;
    }
    if (host === 'fb.watch' && seg[0]) return `facebook:short:${seg[0]}`;

    // ---- Audio ----

    if (host === 'open.spotify.com') {
        const m =
            /^\/(track|album|playlist|episode|show|artist)\/([A-Za-z0-9]+)/
                .exec(path);
        if (m) return `spotify:${m[1]}:${m[2]}`;
    }

    if (host === 'soundcloud.com' || host === 'www.soundcloud.com') {
        if (seg.length >= 2) {
            const user = seg[0].toLowerCase();
            // /{user}/sets/{playlist}
            if (seg[1] === 'sets' && seg[2])
                return `soundcloud:set:${user}:${seg[2].toLowerCase()}`;
            return `soundcloud:${user}:${seg[1].toLowerCase()}`;
        }
    }

    if (host.endsWith('.bandcamp.com')) {
        const artist = host.replace(/\.bandcamp\.com$/, '');
        if ((seg[0] === 'track' || seg[0] === 'album') && seg[1])
            return `bandcamp:${artist}:${seg[0]}:${seg[1].toLowerCase()}`;
    }

    if (host === 'mixcloud.com' || host === 'www.mixcloud.com') {
        if (seg.length >= 2) {
            return `mixcloud:${seg[0].toLowerCase()}:${seg[1].toLowerCase()}`;
        }
    }

    if (_stripWww(host) === 'tidal.com'
            || _stripWww(host) === 'listen.tidal.com') {
        // /track/{id}, /browse/track/{id}, /album/{id}, /playlist/{uuid}
        const types = new Set(['track', 'album', 'playlist', 'video']);
        for (let i = 0; i < seg.length - 1; i += 1) {
            if (types.has(seg[i]) && seg[i + 1])
                return `tidal:${seg[i]}:${seg[i + 1]}`;
        }
    }

    if (_stripWww(host) === 'deezer.com') {
        const types = new Set(['track', 'album', 'playlist', 'artist',
            'episode', 'show']);
        for (let i = 0; i < seg.length - 1; i += 1) {
            if (types.has(seg[i]) && seg[i + 1])
                return `deezer:${seg[i]}:${seg[i + 1]}`;
        }
    }

    if (host === 'music.apple.com') {
        // /{country}/album/{slug}/{id}?i={trackid}
        // /{country}/playlist/{slug}/{id}
        const types = new Set(['album', 'playlist', 'song']);
        for (let i = 0; i < seg.length - 1; i += 1) {
            if (!types.has(seg[i])) continue;
            // The trailing numeric id, not the slug.
            const last = seg[seg.length - 1];
            if (/^\d+$/.test(last)) {
                const trackId = u.searchParams.get('i');
                const key = `applemusic:${seg[i]}:${last}`;
                return trackId ? `${key}:i:${trackId}` : key;
            }
        }
    }

    // Generic fallback.
    return `${u.protocol}//${host}${path.toLowerCase()}`
        .replace(/\/+$/, '');
}

// Backwards-compat aliases — older callers (and a few tests) still
// reference the film-prefixed helpers.
export {
    buildMediaLabel as buildFilmLabel,
    defaultMediaEntry as defaultFilmEntry,
};
