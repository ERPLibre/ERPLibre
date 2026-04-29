/**
 * Film helpers. Pure JS so they can be tested via node --test without
 * pulling in GJS imports.
 *
 * The GJS indicator class lives in indicators/film.js and imports from
 * here.
 */

import {uuid4} from './settings.js';

export function buildFilmLabel(entry) {
    const parts = [entry?.name || ''];
    if (entry?.episode && entry.episode.trim() !== '') parts.push(entry.episode);
    if (entry?.position && entry.position.trim() !== '') parts.push(entry.position);
    return parts.filter(Boolean).join(' · ');
}

export function defaultFilmEntry({name = '', url = '', episode = '',
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
