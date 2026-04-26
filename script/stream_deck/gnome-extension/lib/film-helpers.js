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
    position = ''} = {}) {
    return {id: uuid4(), name, url, episode, position};
}

export function validatePositionInput(text) {
    if (typeof text !== 'string' || text === '') return true;
    return /^\d+(:\d+){0,2}$/.test(text.trim());
}
