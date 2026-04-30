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

/**
 * Filter kinds matched by the badge-click filter:
 *   'alive'    — sessions actively connected (status === 'active' /
 *                'working'); excludes anything in awaiting state.
 *   'awaiting' — sessions waiting for the user (Stop hook fired or
 *                Notification hook fired).
 *   'notify'   — only sessions that fired the Notification hook.
 *   null       — no filter, every session matches.
 */
export function sessionMatchesFilter(session, filter) {
    if (!filter) return true;
    const status = session?.status || '';
    if (filter === 'alive')
        return status === 'active' || status === 'working';
    if (filter === 'awaiting')
        return status === 'awaiting_stop'
            || status === 'awaiting_notification';
    if (filter === 'notify')
        return status === 'awaiting_notification';
    return true;
}
