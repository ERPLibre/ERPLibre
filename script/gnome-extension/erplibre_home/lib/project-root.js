/**
 * Project root of the checkout that holds this extension.
 *
 * GNOME Shell reports `extension.path` as the directory under
 * ~/.local/share/gnome-shell/extensions, and that directory is a symlink
 * to <checkout>/script/gnome-extension/erplibre_home. The root is read on
 * the link target, not on the link path. The hot-reload directory is a
 * real one, whose entries are links to that source and whose
 * metadata.json is its own: its root is read on its extension.js link.
 *
 * Pure: the filesystem is reached only through the injected `readLink`,
 * so node --test loads this module without any gi:// import.
 */

const EXTENSION_SUFFIX_RE = /\/script\/gnome-extension\/erplibre_home\/?$/;

// Bound on chained links; a link cycle stops here instead of looping.
const MAX_LINK_HOPS = 8;

/**
 * Lexical normalisation: drops empty and `.` segments, folds `..` into
 * its parent. The parent directories are taken as written, like
 * `realpath -s`, not re-resolved on disk.
 */
export function normalizePath(path) {
    const absolute = path.startsWith('/');
    const out = [];
    for (const part of path.split('/')) {
        if (part === '' || part === '.') continue;
        if (part === '..') {
            if (out.length && out[out.length - 1] !== '..') out.pop();
            else if (!absolute) out.push('..');
            continue;
        }
        out.push(part);
    }
    const joined = out.join('/');
    if (absolute) return `/${joined}`;
    return joined || '.';
}

/**
 * Absolute path a link points to: an absolute target is kept, a relative
 * one is joined to the directory that contains the link.
 */
export function resolveLinkTarget(linkPath, target) {
    if (target.startsWith('/')) return normalizePath(target);
    const parent = linkPath.replace(/\/[^/]*$/, '') || '/';
    return normalizePath(`${parent}/${target}`);
}

function _readLinkOrNull(readLink, path) {
    if (typeof readLink !== 'function') return null;
    try {
        const target = readLink(path);
        return typeof target === 'string' && target !== '' ? target : null;
    } catch (_e) {
        return null;
    }
}

/**
 * `path` with its symlinks followed, up to MAX_LINK_HOPS, trailing
 * slashes dropped. `readLink(p)` returns the symlink target of `p`
 * (absolute or relative), or null when `p` is not a symlink.
 */
export function resolveLinks(path, readLink) {
    let current = path.length > 1 ? path.replace(/\/+$/, '') : path;
    for (let hop = 0; hop < MAX_LINK_HOPS; hop++) {
        const target = _readLinkOrNull(readLink, current);
        if (target === null) break;
        current = resolveLinkTarget(current, target);
    }
    return current;
}

/**
 * Checkout root for an extension path.
 *
 * The path's links are followed (resolveLinks), then the
 * /script/gnome-extension/erplibre_home suffix is stripped. A resolved path
 * without the suffix is read through its extension.js instead, which a
 * hot-reload directory links into the source; when that does not lead to
 * the suffix either, the path comes back resolved, or as given when it is
 * not a link.
 */
export function projectRootFrom(path, readLink) {
    if (typeof path !== 'string' || path === '') return '';
    const current = resolveLinks(path, readLink);
    if (EXTENSION_SUFFIX_RE.test(current))
        return current.replace(EXTENSION_SUFFIX_RE, '');
    const entry = resolveLinks(`${current}/extension.js`, readLink);
    const source = entry.replace(/\/extension\.js$/, '');
    if (source !== entry && EXTENSION_SUFFIX_RE.test(source))
        return source.replace(EXTENSION_SUFFIX_RE, '');
    return current === resolveLinks(path, null) ? path : current;
}

/**
 * GJS `readLink` for projectRootFrom, built on the Gio namespace the
 * caller already imported. It queries `standard::symlink-target` without
 * following the link; a missing file, a non-link or any Gio error
 * gives null.
 */
export function makeGioReadLink(Gio) {
    return (path) => {
        try {
            const info = Gio.File.new_for_path(path).query_info(
                'standard::symlink-target',
                Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, null);
            return info.get_symlink_target() || null;
        } catch (_e) {
            return null;
        }
    };
}

// Interpreter of the Stream Deck venv, relative to the checkout root. Only
// the Stream Deck level of install_erplibre_home.sh creates it.
export const STREAMDECK_PYTHON_REL = '.venv.streamdeck/bin/python';

/**
 * Python of the Stream Deck venv under `root`, or null when it is absent.
 *
 * `fileExists(p)` tells whether the interpreter at `p` can be started; a
 * fileExists that throws counts as absent. An empty root gives null
 * without asking. The indicators call this at the time of the action, so a
 * Stream Deck level added after the session started is found.
 */
export function streamDeckPython(root, fileExists) {
    if (typeof root !== 'string' || root === '') return null;
    const base = root.length > 1 ? root.replace(/\/+$/, '') : root;
    const python = `${base}/${STREAMDECK_PYTHON_REL}`;
    try {
        return fileExists(python) ? python : null;
    } catch (_e) {
        return null;
    }
}

// Gallery server, relative to the checkout root.
export const GALLERY_SERVER_REL = 'script/stream_deck/games/gallery_server.py';

// `s` as one POSIX shell word: single-quoted, each ' written as '\''.
function shellWord(s) {
    return `'${String(s).replace(/'/g, "'\\''")}'`;
}

/**
 * Shell command line that starts the gallery server of `root` under
 * `python`, the interpreter streamDeckPython(root) returned. Both paths are
 * quoted, so a checkout whose path holds a space or a quote still runs.
 * The line needs neither make nor the checkout as working directory.
 */
export function galleryServerCommand(root, python) {
    const base = root.length > 1 ? root.replace(/\/+$/, '') : root;
    return `${shellWord(python)} ${shellWord(`${base}/${GALLERY_SERVER_REL}`)}`;
}

/**
 * Whether the gallery of `root` can start: the Stream Deck venv's python
 * passes `isExecutable` and the gallery server passes `isFile`. A callback
 * that throws counts as absent; an empty root gives false. The controller
 * indicator greys out a folder for which this is false.
 */
export function galleryReady(root, isExecutable, isFile) {
    if (streamDeckPython(root, isExecutable) === null) return false;
    const base = root.length > 1 ? root.replace(/\/+$/, '') : root;
    try {
        return Boolean(isFile(`${base}/${GALLERY_SERVER_REL}`));
    } catch (_e) {
        return false;
    }
}
