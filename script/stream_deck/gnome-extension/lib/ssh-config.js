export function parseSshConfig(text) {
    if (typeof text !== 'string' || text === '') return [];
    const out = [];
    let current = null;
    for (const rawLine of text.split('\n')) {
        const line = rawLine.replace(/#.*$/, '').trim();
        if (!line) continue;
        const m = line.match(/^([A-Za-z]+)\s+(.+)$/);
        if (!m) continue;
        const key = m[1];
        const value = m[2].trim();
        if (key.toLowerCase() === 'host') {
            current = {alias: value, fields: {}};
            out.push(current);
        } else if (current) {
            current.fields[key] = value;
        }
    }
    return out;
}

export function isWildcardHost(alias) {
    return /[*?]/.test(String(alias || ''));
}
