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

/**
 * Reduce a media URL to a canonical form so two equivalent links
 * dedupe to the same key. Strips tracking params and timestamps,
 * extracts video / track ids when the host is known, lowercases
 * everything that is not an identifier.
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

    if (_YT_HOSTS.test(host)) {
        let id = '';
        if (host.endsWith('youtu.be')) {
            id = u.pathname.replace(/^\/+/, '').split('/')[0] || '';
        } else if (u.pathname === '/watch') {
            id = u.searchParams.get('v') || '';
        } else if (u.pathname.startsWith('/shorts/')) {
            id = u.pathname.split('/')[2] || '';
        } else if (u.pathname.startsWith('/embed/')) {
            id = u.pathname.split('/')[2] || '';
        }
        if (id) return `youtube:${id}`;
    }

    if (host === 'open.spotify.com') {
        const m =
            /^\/(track|album|playlist|episode|show|artist)\/([A-Za-z0-9]+)/
                .exec(u.pathname);
        if (m) return `spotify:${m[1]}:${m[2]}`;
    }

    return `${u.protocol}//${host}${u.pathname.toLowerCase()}`
        .replace(/\/+$/, '');
}

// Backwards-compat aliases — older callers (and a few tests) still
// reference the film-prefixed helpers.
export {
    buildMediaLabel as buildFilmLabel,
    defaultMediaEntry as defaultFilmEntry,
};
