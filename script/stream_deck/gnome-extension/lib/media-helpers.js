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
    position = '', kind = '', last_played = '',
    artist = '', album = '', year = '', genre = '',
    rating = 0, play_count = 0, duration = '',
    added_at = '', tags = []} = {}) {
    // added_at is stamped on first creation so the library can sort
    // by "recently added". Caller-provided values win so tests and
    // migrations stay deterministic.
    const stamp = added_at || new Date().toISOString();
    return {
        id: uuid4(),
        name, url, episode, position,
        kind: kind || guessKind(url),
        last_played,
        artist, album, year, genre,
        rating: Number.isFinite(rating) ? rating : 0,
        play_count: Number.isFinite(play_count) ? play_count : 0,
        duration,
        added_at: stamp,
        tags: Array.isArray(tags) ? [...tags] : [],
    };
}

/**
 * Render an ISO timestamp as a short locale-friendly day string. Used
 * by the media dropdown to surface a last-played indicator on each
 * row. Returns '' for empty / invalid input.
 */
export function formatLastPlayed(iso, now = new Date()) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    const todayKey = (date) =>
        `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
        + `-${String(date.getDate()).padStart(2, '0')}`;
    if (todayKey(d) === todayKey(now)) return 'today';
    const yesterday = new Date(now);
    yesterday.setDate(now.getDate() - 1);
    if (todayKey(d) === todayKey(yesterday)) return 'yesterday';
    return todayKey(d);
}

export function validatePositionInput(text) {
    if (typeof text !== 'string' || text === '') return true;
    return /^\d+(:\d+){0,2}$/.test(text.trim());
}

/**
 * Convert a "hh:mm:ss" / "mm:ss" / "seconds" string to seconds. Returns
 * 0 for empty / invalid input. Used to compare position against
 * duration when building progress bars.
 */
export function positionToSeconds(text) {
    const s = String(text || '').trim();
    if (!s) return 0;
    if (!/^\d+(:\d+){0,2}$/.test(s)) return 0;
    const parts = s.split(':').map(p => parseInt(p, 10));
    if (parts.some(n => !Number.isFinite(n))) return 0;
    if (parts.length === 1) return parts[0];
    if (parts.length === 2) return parts[0] * 60 + parts[1];
    return parts[0] * 3600 + parts[1] * 60 + parts[2];
}

/**
 * Render a `▮▮▮▮▯ 78%` progress bar from a position / duration pair.
 * Returns `''` when duration is missing or non-positive — the caller
 * is expected to fall back to plain text. The bar uses 5 cells so it
 * stays compact in a PopupMenu row.
 */
export function formatProgress(position, duration, cells = 5) {
    const pos = positionToSeconds(position);
    const dur = positionToSeconds(duration);
    if (dur <= 0) return '';
    const ratio = Math.max(0, Math.min(1, pos / dur));
    const full = Math.round(ratio * cells);
    const bar = '▮'.repeat(full) + '▯'.repeat(cells - full);
    const pct = Math.round(ratio * 100);
    return `${bar} ${pct}%`;
}

/**
 * Group entries by an attribute. `key` may be `''` (single bucket),
 * `'artist'`, `'album'`, `'genre'`, `'year'` or `'kind'`. Empty values
 * land in an `''` bucket the caller can render as "(sans artiste)".
 * Insertion order is preserved (Map iteration order = insertion).
 */
export function groupBy(entries, key) {
    const out = new Map();
    const list = Array.isArray(entries) ? entries : [];
    if (!key) {
        out.set('', [...list]);
        return out;
    }
    for (const e of list) {
        const raw = e?.[key];
        const bucket = (typeof raw === 'string' ? raw.trim() : raw)
            || '';
        if (!out.has(bucket)) out.set(bucket, []);
        out.get(bucket).push(e);
    }
    return out;
}

const _SORT_MODES = new Set(['last_played', 'alpha', 'play_count',
    'rating', 'added']);

function _alphaCmp(a, b) {
    return String(a?.name || '').localeCompare(String(b?.name || ''),
        undefined, {sensitivity: 'base'});
}

function _isoCmp(aIso, bIso) {
    // Empty values sort last regardless of direction.
    const a = aIso || '';
    const b = bIso || '';
    if (!a && !b) return 0;
    if (!a) return 1;
    if (!b) return -1;
    return b.localeCompare(a);
}

/**
 * Sort entries by one of the supported modes. Returns a new array,
 * does not mutate the input. Unknown modes fall back to alphabetical.
 *
 *   last_played: most-recent first, empty `last_played` last.
 *   alpha:       A→Z by name, locale-aware, accent-insensitive.
 *   play_count:  highest first, ties → last_played → alpha.
 *   rating:      highest first, ties → last_played → alpha.
 *   added:       most-recent `added_at` first, empty last.
 */
export function sortEntries(entries, mode = 'last_played') {
    const list = Array.isArray(entries) ? [...entries] : [];
    const m = _SORT_MODES.has(mode) ? mode : 'alpha';
    const tieBreak = (a, b) => {
        const cmp = _isoCmp(a?.last_played, b?.last_played);
        return cmp !== 0 ? cmp : _alphaCmp(a, b);
    };
    if (m === 'last_played') {
        list.sort((a, b) => {
            const cmp = _isoCmp(a?.last_played, b?.last_played);
            return cmp !== 0 ? cmp : _alphaCmp(a, b);
        });
    } else if (m === 'added') {
        list.sort((a, b) => {
            const cmp = _isoCmp(a?.added_at, b?.added_at);
            return cmp !== 0 ? cmp : _alphaCmp(a, b);
        });
    } else if (m === 'play_count') {
        list.sort((a, b) => {
            const av = Number.isFinite(a?.play_count) ? a.play_count : 0;
            const bv = Number.isFinite(b?.play_count) ? b.play_count : 0;
            return bv - av || tieBreak(a, b);
        });
    } else if (m === 'rating') {
        list.sort((a, b) => {
            const av = Number.isFinite(a?.rating) ? a.rating : 0;
            const bv = Number.isFinite(b?.rating) ? b.rating : 0;
            return bv - av || tieBreak(a, b);
        });
    } else {
        list.sort(_alphaCmp);
    }
    return list;
}

const _UNFINISHED_STALE_DAYS = 7;

function _isStale(iso, now, days) {
    if (!iso) return true;
    const t = Date.parse(iso);
    if (!Number.isFinite(t)) return true;
    return (now.getTime() - t) > days * 24 * 3600 * 1000;
}

/**
 * Apply zero or more filter predicates to a list. All passed flags
 * AND together. Match on `query` is a case-insensitive substring on
 * `name`, `artist`, `album` and `tags`.
 *
 *   kind:        'video' | 'audio' (anything else disables the filter).
 *   query:       substring (trimmed, lower-cased).
 *   unwatched:   true → keep only entries without a last_played stamp.
 *   unfinished:  true → keep entries with a non-empty position whose
 *                last_played is older than 7 days (or never played).
 *   favourites:  true → keep entries with rating >= 4.
 */
export function filterEntries(entries, opts = {}, now = new Date()) {
    const list = Array.isArray(entries) ? entries : [];
    const {kind, query, unwatched, unfinished, favourites} = opts;
    const k = (kind === 'video' || kind === 'audio') ? kind : null;
    const q = String(query || '').trim().toLowerCase();
    return list.filter(e => {
        if (!e) return false;
        if (k && normaliseKind(e.kind) !== k) return false;
        if (unwatched && e.last_played) return false;
        if (unfinished) {
            if (!e.position) return false;
            if (!_isStale(e.last_played, now, _UNFINISHED_STALE_DAYS))
                return false;
        }
        if (favourites && (Number(e.rating) || 0) < 4) return false;
        if (q) {
            const hay = [e.name, e.artist, e.album,
                ...(Array.isArray(e.tags) ? e.tags : [])]
                .map(v => String(v || '').toLowerCase()).join(' ');
            if (!hay.includes(q)) return false;
        }
        return true;
    });
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

    // ---- Quebec / Canadian streaming ----

    // ICI Tou.tv — Radio-Canada. URL patterns:
    //   ici.tou.tv/{show-slug}/S{n}E{n}
    //   ici.tou.tv/{show-slug}        (show home)
    //   tou.tv/{show-slug}/...        (older host)
    if (host === 'ici.tou.tv' || host === 'tou.tv') {
        if (seg[0]) {
            const show = seg[0].toLowerCase();
            const ep = seg[1]
                ? `:${seg[1].toLowerCase()}`
                : '';
            return `toutv:${show}${ep}`;
        }
    }

    // Noovo (Bell Média). URL patterns:
    //   noovo.ca/emissions/{show}/saison-{n}/episode-{n}
    //   noovo.ca/emissions/{show}
    //   noovo.ca/videos/{slug}
    if (host === 'noovo.ca' || host === 'www.noovo.ca') {
        if (seg[0] === 'emissions' && seg[1]) {
            const show = seg[1].toLowerCase();
            const tail = seg.slice(2).join(':').toLowerCase();
            return tail ? `noovo:${show}:${tail}` : `noovo:${show}`;
        }
        if (seg[0] === 'videos' && seg[1])
            return `noovo:video:${seg[1].toLowerCase()}`;
    }

    // Télé-Québec. URL patterns:
    //   telequebec.tv/{show-slug}
    //   telequebec.tv/{show-slug}/{episode-slug}
    if (host === 'telequebec.tv' || host === 'www.telequebec.tv') {
        if (seg[0]) {
            const tail = seg.slice(1).join(':').toLowerCase();
            return tail
                ? `telequebec:${seg[0].toLowerCase()}:${tail}`
                : `telequebec:${seg[0].toLowerCase()}`;
        }
    }

    // TV5 Unis (francophone Canada). URL patterns:
    //   tv5unis.ca/videos/{show}/{episode}
    //   tv5unis.ca/{show}/{episode}
    if (host === 'tv5unis.ca' || host === 'www.tv5unis.ca') {
        const idx = seg[0] === 'videos' ? 1 : 0;
        if (seg[idx]) {
            const tail = seg.slice(idx + 1).join(':').toLowerCase();
            return tail
                ? `tv5unis:${seg[idx].toLowerCase()}:${tail}`
                : `tv5unis:${seg[idx].toLowerCase()}`;
        }
    }

    // Radio-Canada OHdio (audio: balados, musique, première). URL:
    //   ici.radio-canada.ca/ohdio/balados/{slug}/episode-...
    //   ici.radio-canada.ca/ohdio/premiere/...
    if ((host === 'ici.radio-canada.ca' || host === 'www.ici.radio-canada.ca'
            || host === 'ohdio.ca')
            && (seg[0] === 'ohdio' || host === 'ohdio.ca')) {
        const tail = (host === 'ohdio.ca' ? seg : seg.slice(1))
            .join(':').toLowerCase();
        if (tail) return `ohdio:${tail}`;
    }

    // CBC Gem (federal but watched widely in Quebec). URL:
    //   gem.cbc.ca/{show-slug}/s{n}e{n}
    //   gem.cbc.ca/media/{show}/{id}
    if (host === 'gem.cbc.ca') {
        if (seg[0] === 'media' && seg[2])
            return `cbcgem:${seg[1].toLowerCase()}:${seg[2]}`;
        if (seg[0]) {
            const tail = seg.slice(1).join(':').toLowerCase();
            return tail
                ? `cbcgem:${seg[0].toLowerCase()}:${tail}`
                : `cbcgem:${seg[0].toLowerCase()}`;
        }
    }

    // Crave (Bell). URL: crave.ca/{lang}/{type}/{slug}/{id}
    if (host === 'crave.ca' || host === 'www.crave.ca') {
        // Drop the optional /fr or /en locale prefix.
        const start = (seg[0] === 'fr' || seg[0] === 'en') ? 1 : 0;
        const tail = seg.slice(start).join(':').toLowerCase();
        if (tail) return `crave:${tail}`;
    }

    // Vrai (Québecor / Vidéotron). URL: vrai.ca/{show}/{episode...}
    if (host === 'vrai.ca' || host === 'www.vrai.ca') {
        if (seg[0]) {
            const tail = seg.slice(1).join(':').toLowerCase();
            return tail
                ? `vrai:${seg[0].toLowerCase()}:${tail}`
                : `vrai:${seg[0].toLowerCase()}`;
        }
    }

    // TVA+ (Québecor) — modern host tvaplus.ca, legacy tva.ca/videos.
    if (host === 'tvaplus.ca' || host === 'www.tvaplus.ca') {
        if (seg[0]) {
            const tail = seg.slice(1).join(':').toLowerCase();
            return tail
                ? `tvaplus:${seg[0].toLowerCase()}:${tail}`
                : `tvaplus:${seg[0].toLowerCase()}`;
        }
    }
    if ((host === 'tva.ca' || host === 'www.tva.ca')
            && seg[0] === 'videos' && seg[1]) {
        const tail = seg.join(':').toLowerCase();
        return `tvaplus:${tail}`;
    }

    // ICI Musique (Radio-Canada streaming musical). URLs:
    //   ici.radio-canada.ca/musique/...
    //   icimusique.ca/...   (vanity host)
    if (host === 'icimusique.ca' || host === 'www.icimusique.ca') {
        const tail = seg.join(':').toLowerCase();
        if (tail) return `icimusique:${tail}`;
    }
    if ((host === 'ici.radio-canada.ca'
            || host === 'www.ici.radio-canada.ca')
            && seg[0] === 'musique') {
        const tail = seg.slice(1).join(':').toLowerCase();
        if (tail) return `icimusique:${tail}`;
    }

    // Apple TV (movies + shows) — match the Apple Music style.
    if (host === 'tv.apple.com') {
        // /{country}/{type}/{slug}/{id}
        const types = new Set(['movie', 'show', 'episode']);
        for (let i = 0; i < seg.length - 1; i += 1) {
            if (types.has(seg[i]) && seg[seg.length - 1])
                return `appletv:${seg[i]}:${seg[seg.length - 1]}`;
        }
    }

    // Twitch live channel (no episode id — bucket by channel).
    if (host === 'twitch.tv' || host === 'www.twitch.tv') {
        if (seg.length === 1 && seg[0])
            return `twitch:live:${seg[0].toLowerCase()}`;
    }

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

/**
 * Best-effort metadata extraction from a media URL. Returns
 * `{name, episode, artist, album}` with any field possibly empty.
 * Designed to power an Auto-fill button in the Add media dialog so
 * the user can paste a URL and let the dialog populate the readable
 * bits.
 *
 * The name comes from the show slug when one is in the path
 * (tou.tv, noovo, vrai, telequebec, tv5unis, gem, soundcloud,
 * bandcamp, etc.), otherwise from a hint of the host (Vimeo,
 * YouTube, Spotify…). The episode marker is derived from
 * S{n}E{n}, saison-N/episode-N or the trailing numeric id when no
 * structured marker exists. `artist` / `album` are populated only
 * for music platforms where the URL itself carries them
 * (SoundCloud, Bandcamp, Mixcloud, Apple Music album).
 */
export function extractMediaInfo(url) {
    const raw = String(url || '').trim();
    const result = {name: '', episode: '', artist: '', album: ''};
    if (!raw) return result;

    // Compact and verbose episode markers — same regexes as
    // nextEpisodeUrl but match-only.
    const compact = /S(\d+)E(\d+)/i;
    const verbose = /(?:saison|season)-?(\d+)(?:[-/]episode-?)(\d+)/i;
    const cM = compact.exec(raw);
    const vM = verbose.exec(raw);
    if (cM) result.episode = `S${cM[1]}E${cM[2]}`.toUpperCase();
    else if (vM) result.episode = `S${vM[1]}E${vM[2]}`;

    let u;
    try { u = new URL(raw); }
    catch (_e) {
        return result;
    }

    const host = (u.hostname || '').toLowerCase();
    const seg = (u.pathname || '').split('/').filter(Boolean);

    const slug = (s) => String(s || '')
        .replace(/[-_]+/g, ' ')
        .replace(/\b\w/g, c => c.toUpperCase())
        .trim();

    // Strip an episode-bearing trailing segment so the name comes
    // from the show slug, not the episode marker.
    const showSeg = (segments) => {
        const cleaned = segments.filter(s =>
            !compact.test(s) && !/^episode-?\d+/i.test(s)
            && !/^saison-?\d+/i.test(s) && !/^season-?\d+/i.test(s));
        return cleaned[0] || segments[0] || '';
    };

    if (host === 'ici.tou.tv' || host === 'tou.tv'
            || host === 'vrai.ca' || host === 'www.vrai.ca'
            || host === 'telequebec.tv' || host === 'www.telequebec.tv'
            || host === 'gem.cbc.ca') {
        result.name = slug(showSeg(seg));
        return result;
    }

    if (host === 'noovo.ca' || host === 'www.noovo.ca') {
        const start = (seg[0] === 'emissions' || seg[0] === 'videos') ? 1 : 0;
        result.name = slug(showSeg(seg.slice(start)));
        return result;
    }

    if (host === 'tv5unis.ca' || host === 'www.tv5unis.ca') {
        const start = seg[0] === 'videos' ? 1 : 0;
        result.name = slug(showSeg(seg.slice(start)));
        return result;
    }

    if (host === 'tvaplus.ca' || host === 'www.tvaplus.ca'
            || host === 'tva.ca' || host === 'www.tva.ca') {
        const start = (seg[0] === 'series' || seg[0] === 'videos'
            || seg[0] === 'emissions') ? 1 : 0;
        result.name = slug(showSeg(seg.slice(start)));
        return result;
    }

    if (host === 'soundcloud.com' || host === 'www.soundcloud.com') {
        // /{user}/{track} or /{user}/sets/{playlist}
        if (seg.length >= 2) {
            const isSet = seg[1] === 'sets';
            const track = isSet ? (seg[2] || '') : seg[1];
            const user = seg[0];
            result.artist = slug(user);
            if (isSet) result.album = slug(track);
            result.name = `${slug(user)} — ${slug(track)}`;
        }
        return result;
    }

    if (host.endsWith('.bandcamp.com')) {
        const artist = host.replace(/\.bandcamp\.com$/, '');
        const isAlbum = seg[0] === 'album';
        const track = seg[1] || '';
        result.artist = slug(artist);
        if (isAlbum && track) result.album = slug(track);
        result.name = track
            ? `${slug(artist)} — ${slug(track)}`
            : slug(artist);
        return result;
    }

    if (host === 'mixcloud.com' || host === 'www.mixcloud.com') {
        if (seg.length >= 2) {
            result.artist = slug(seg[0]);
            result.name = `${slug(seg[0])} — ${slug(seg[1])}`;
        }
        return result;
    }

    if (host === 'music.apple.com') {
        // /{country}/album/{slug}/{id}?i={trackid}
        // /{country}/playlist/{slug}/{id}
        const types = new Set(['album', 'playlist', 'song']);
        const idx = seg.findIndex(s => types.has(s));
        if (idx >= 0 && seg[idx + 1]) {
            const albumSlug = slug(seg[idx + 1]);
            if (seg[idx] === 'album') result.album = albumSlug;
            result.name = `Apple Music — ${albumSlug}`;
        }
        return result;
    }

    if (host === 'open.spotify.com') {
        result.name = `Spotify — ${slug(seg[1] || seg[0] || '')}`;
        return result;
    }

    if (_YT_HOSTS.test(host)) {
        // No real title without an API call. Use the video id as a
        // placeholder the user can rename if desired.
        const id = (host.endsWith('youtu.be')
            ? seg[0] : (u.searchParams.get('v') || seg[1] || '')) || '';
        if (id) result.name = `YouTube — ${id}`;
        return result;
    }

    if (host === 'vimeo.com' || host === 'player.vimeo.com') {
        const id = [...seg].reverse().find(s => /^\d+$/.test(s));
        if (id) result.name = `Vimeo — ${id}`;
        return result;
    }

    // Generic fallback: take the last meaningful segment.
    const tail = [...seg].reverse().find(s => !compact.test(s)
        && !/^episode-?\d+/i.test(s) && !/^saison-?\d+/i.test(s)
        && !/^season-?\d+/i.test(s));
    if (tail) result.name = slug(tail);
    return result;
}

/**
 * Compute the URL of the episode that follows `url` by simple
 * pattern increment. Returns null when no recognised episode marker
 * is found. Pure helper, unit-tested.
 *
 * Supported URL shapes (most QC-friendly first):
 *   …/S01E03                 → …/S01E04
 *   …/s01e03                 → …/s01e04
 *   …/saison-1/episode-3     → …/saison-1/episode-4
 *   …/season-1/episode-3     → …/season-1/episode-4
 *   …/saison1-episode3       → …/saison1-episode4
 *
 * Season transitions are intentionally not handled — bumping into a
 * non-existent episode is the user's signal to manually pick the
 * next season's first episode.
 */
export function nextEpisodeUrl(url) {
    const raw = String(url || '');
    if (!raw) return null;
    const patterns = [
        // Compact SnnEnn anywhere in the URL.
        /(S)(\d+)(E)(\d+)/i,
        // saison-N/episode-N or season-N/episode-N (slash separator).
        /(saison|season)(-)(\d+)(\/episode-)(\d+)/i,
        // saisonN-episodeN or saison-N-episode-N (single segment).
        /(saison|season)(-?)(\d+)(-episode-?)(\d+)/i,
    ];
    for (const re of patterns) {
        const m = re.exec(raw);
        if (!m) continue;
        // The episode digits sit in the last capture group of every
        // pattern above; the rest gets concatenated unchanged.
        const lastIdx = m.length - 1;
        const oldEp = m[lastIdx];
        const next = parseInt(oldEp, 10) + 1;
        const padded = String(next).padStart(oldEp.length, '0');
        const head = m.slice(1, lastIdx).join('');
        const replaced = raw.replace(re, head + padded);
        return replaced;
    }
    return null;
}

/**
 * Compute a label suffix that reflects the bumped episode for a
 * "Next episode" entry. Returns '' when no S{n}E{n} or
 * episode/saison marker fits the original name.
 */
export function nextEpisodeLabel(name, oldUrl, newUrl) {
    if (!name || !oldUrl || !newUrl) return name || '';
    const compact = /S(\d+)E(\d+)/i;
    const oldM = compact.exec(oldUrl);
    const newM = compact.exec(newUrl);
    if (oldM && newM) {
        const tag = `S${newM[1]}E${newM[2]}`;
        if (compact.test(name)) return name.replace(compact, tag);
        return `${name} — ${tag}`;
    }
    const ep = /episode-?(\d+)/i;
    const newEp = ep.exec(newUrl);
    if (newEp) {
        const tag = `Ép. ${newEp[1]}`;
        if (ep.test(name)) return name.replace(ep, `episode-${newEp[1]}`);
        return `${name} — ${tag}`;
    }
    return name;
}

// Backwards-compat aliases — older callers (and a few tests) still
// reference the film-prefixed helpers.
export {
    buildMediaLabel as buildFilmLabel,
    defaultMediaEntry as defaultFilmEntry,
};
