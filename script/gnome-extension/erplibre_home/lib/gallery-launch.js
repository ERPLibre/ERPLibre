/**
 * The gallery as the controller indicator sees it: the folders its submenu
 * offers to start the gallery server from, and the reading of the
 * gallery's answer to `GET /launch/<id>`.
 *
 * The gallery answers 2xx when the game starts, and otherwise a JSON body
 * `{"error": "<one line>"}`: 403 when GAMES refuses the games or the
 * request lacks GALLERY_ACTION_HEADER, 404 for an unknown game, 503 when no
 * terminal can run it. Pure: node --test loads it without any gi:// import.
 */

/**
 * The header, set to '1', that the gallery requires on a route that acts,
 * `/launch/<id>` included (contract 2.0 of the games): a page of another
 * site cannot send it, so it cannot launch a game through the gallery.
 */
export const GALLERY_ACTION_HEADER = 'X-Stream-Deck-Gallery';

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

// `path` without its trailing slashes; the root `/` stays `/`.
function _trimSlash(path) {
    return path.length > 1 ? path.replace(/\/+$/, '') : path;
}

/**
 * The folders the gallery submenu offers, in order: `root`, the checkout
 * that holds the extension, first (`own: true`), then each configured path
 * of `paths` (the `paths` setting, `{label, path}`) once. A path equal to an
 * earlier one, trailing slashes aside, is dropped, so a checkout also listed
 * in the paths appears once, as its own entry. An empty root, an entry
 * without a path and a blank path are skipped.
 *
 * `ready(path)` tells whether the gallery can start there; one that throws
 * counts as not ready. Each entry is `{path, label, own, ready}`, `label`
 * being the configured one, '' for the checkout and an unlabelled path.
 */
export function galleryTargets(root, paths, ready) {
    const seen = new Set();
    const targets = [];
    const add = (path, label, own) => {
        if (typeof path !== 'string' || path.trim() === '') return;
        const clean = _trimSlash(path);
        if (seen.has(clean)) return;
        seen.add(clean);
        let ok = false;
        try {
            ok = Boolean(ready(clean));
        } catch (_e) {}
        targets.push({path: clean, label, own, ready: ok});
    };
    add(root, '', true);
    for (const entry of Array.isArray(paths) ? paths : []) {
        if (!entry) continue;
        const label = typeof entry.label === 'string' ? entry.label : '';
        add(entry.path, label, false);
    }
    return targets;
}
