/**
 * Reading of the gallery's answer to `GET /launch/<id>`.
 *
 * The gallery answers 2xx when the game starts, and otherwise a JSON body
 * `{"error": "<one line>"}`: 403 when GAMES refuses the games, 404 for an
 * unknown game. Pure: node --test loads it without any gi:// import.
 */

/**
 * Returns null for a 2xx status, else the line that says why: the
 * gallery's `error` string when the body carries a non-blank one,
 * `HTTP <status>` otherwise.
 */
export function launchRefusal(status, bodyText) {
    if (status >= 200 && status < 300) return null;
    let why = '';
    try {
        const parsed = JSON.parse(bodyText);
        if (parsed && typeof parsed.error === 'string')
            why = parsed.error.trim();
    } catch (_e) {}
    return why || `HTTP ${status}`;
}
