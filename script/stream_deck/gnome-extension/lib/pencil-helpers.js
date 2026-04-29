/**
 * Pure helpers used by the pencil indicator. Kept outside the GJS
 * try-block in indicators/pencil.js so node-only unit tests can
 * import them without touching gi modules.
 */

/** Strip a single trailing slash so '/a' and '/a/' compare equal. */
export function normPath(p) {
    return String(p || '').replace(/\/+$/, '');
}

/** True when `cwd` is the same dir as `base` or a descendant of it. */
export function cwdMatchesPath(cwd, base) {
    const c = normPath(cwd);
    const b = normPath(base);
    if (!c || !b) return false;
    return c === b || c.startsWith(`${b}/`);
}

/**
 * For each session, pick the configured path that is the longest
 * prefix of its cwd. Returns Map<session_id, ownerPath>. Sessions
 * without a matching path are absent from the map.
 *
 * `paths` is the list of configured entries (same shape as the
 * `paths` GSetting), `sessions` the list of normalised session
 * entries from claude-state.indexSessions.
 */
export function assignSessionsToPaths(sessions, paths) {
    const owners = new Map();
    const sortedPaths = (paths || []).slice().sort(
        (a, b) => normPath(b.path).length - normPath(a.path).length);
    for (const s of (sessions || [])) {
        if (!s) continue;
        for (const p of sortedPaths) {
            if (cwdMatchesPath(s.cwd, p.path)) {
                owners.set(s.session_id, normPath(p.path));
                break;
            }
        }
    }
    return owners;
}
