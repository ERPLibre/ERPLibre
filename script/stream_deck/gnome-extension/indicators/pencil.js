import {uuid4} from '../lib/settings.js';

export function resolveLabel(entry) {
    if (entry?.label && entry.label.trim() !== '') return entry.label;
    const path = entry?.path || '';
    if (path === '/') return '/';
    const trimmed = path.replace(/\/+$/, '');
    const idx = trimmed.lastIndexOf('/');
    return idx >= 0 ? trimmed.slice(idx + 1) : trimmed;
}

export function defaultPathEntry({label = '', path = '', default_cmd} = {}) {
    return {
        id: uuid4(),
        label,
        path,
        default_cmd: default_cmd || 'claude --resume',
    };
}

// Indicator class + descriptor are added in Task 2.
