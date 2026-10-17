import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {projectRootFrom, makeGioReadLink, normalizePath, resolveLinkTarget,
    streamDeckPython, galleryServerCommand} from '../../lib/project-root.js';

const CHECKOUT = '/opt/depot';
const EXT_SRC = `${CHECKOUT}/script/gnome-extension/erplibre_home`;
const EXT_DIR = '/opt/maison/.local/share/gnome-shell/extensions';
const LINK = `${EXT_DIR}/erplibre-home@technolibre.ca`;

// readLink stub: a table of link path -> target, null for anything else.
function linksTo(table) {
    const calls = [];
    const readLink = (p) => {
        calls.push(p);
        return Object.prototype.hasOwnProperty.call(table, p)
            ? table[p] : null;
    };
    readLink.calls = calls;
    return readLink;
}

test('normalizePath folds . and .. segments', () => {
    assert.equal(normalizePath('/a/./b/../c/'), '/a/c');
    assert.equal(normalizePath('/../a'), '/a');
    assert.equal(normalizePath('a/../../b'), '../b');
    assert.equal(normalizePath('/'), '/');
});

test('resolveLinkTarget keeps absolute and joins relative targets', () => {
    assert.equal(resolveLinkTarget('/x/y/link', '/t/u'), '/t/u');
    assert.equal(resolveLinkTarget('/x/y/link', '../t'), '/x/t');
    assert.equal(resolveLinkTarget('/link', 't'), '/t');
});

test('direct path: same result as the former regex', () => {
    const readLink = linksTo({});
    assert.equal(projectRootFrom(EXT_SRC, readLink), CHECKOUT);
    assert.equal(projectRootFrom(`${EXT_SRC}/`, readLink), CHECKOUT);
    assert.deepEqual(readLink.calls, [EXT_SRC, EXT_SRC]);
});

test('direct path without readLink: same result as the former regex', () => {
    assert.equal(projectRootFrom(EXT_SRC), CHECKOUT);
    assert.equal(projectRootFrom(EXT_SRC, null), CHECKOUT);
});

test('path without the extension suffix comes back unchanged', () => {
    assert.equal(projectRootFrom('/opt/ailleurs/', linksTo({})),
        '/opt/ailleurs/');
});

test('absolute symlink: root of the link target', () => {
    assert.equal(projectRootFrom(LINK, linksTo({[LINK]: EXT_SRC})),
        CHECKOUT);
});

test('absolute symlink with a trailing slash on both sides', () => {
    assert.equal(projectRootFrom(`${LINK}/`, linksTo({[LINK]: `${EXT_SRC}/`})),
        CHECKOUT);
});

test('relative symlink: resolved against the link parent', () => {
    const target = '../../../../../depot/script/gnome-extension/erplibre_home';
    assert.equal(projectRootFrom(LINK, linksTo({[LINK]: target})), CHECKOUT);
});

test('hot-reload uuid dir: a copy of the link, same root', () => {
    const reload =
        `${EXT_DIR}/erplibre-home-reload-1700000000000@technolibre.ca`;
    assert.equal(projectRootFrom(reload, linksTo({[reload]: EXT_SRC})),
        CHECKOUT);
});

test('chained symlinks are followed', () => {
    const middle = '/opt/liens/extension';
    const readLink = linksTo({[LINK]: middle, [middle]: EXT_SRC});
    assert.equal(projectRootFrom(LINK, readLink), CHECKOUT);
});

test('a symlink cycle stops after a bounded number of hops', () => {
    const readLink = linksTo({[LINK]: 'erplibre-home@technolibre.ca'});
    assert.equal(projectRootFrom(LINK, readLink), LINK);
    assert.equal(readLink.calls.length, 8);
});

test('a readLink that throws counts as no symlink', () => {
    const readLink = () => { throw new Error('EACCES'); };
    assert.equal(projectRootFrom(EXT_SRC, readLink), CHECKOUT);
});

test('empty or non-string path gives an empty root', () => {
    assert.equal(projectRootFrom('', linksTo({})), '');
    assert.equal(projectRootFrom(undefined, linksTo({})), '');
});

// Gio stub: answers from a link table, records the query_info arguments.
function fakeGio({targets = {}, fail = false} = {}) {
    const seen = [];
    return {
        seen,
        FileQueryInfoFlags: {NOFOLLOW_SYMLINKS: 'nofollow'},
        File: {
            new_for_path: (p) => ({
                query_info: (attr, flags, cancellable) => {
                    seen.push({p, attr, flags, cancellable});
                    if (fail) throw new Error('No such file or directory');
                    return {get_symlink_target: () => targets[p] ?? null};
                },
            }),
        },
    };
}

test('makeGioReadLink returns the target, queried without following', () => {
    const Gio = fakeGio({targets: {[LINK]: EXT_SRC}});
    assert.equal(makeGioReadLink(Gio)(LINK), EXT_SRC);
    assert.deepEqual(Gio.seen, [{p: LINK, attr: 'standard::symlink-target',
        flags: 'nofollow', cancellable: null}]);
});

test('makeGioReadLink returns null for a non-symlink', () => {
    assert.equal(makeGioReadLink(fakeGio())(EXT_SRC), null);
});

test('makeGioReadLink returns null when Gio throws', () => {
    assert.equal(makeGioReadLink(fakeGio({fail: true}))('/opt/absent'), null);
});

test('makeGioReadLink plugs into projectRootFrom', () => {
    const readLink = makeGioReadLink(fakeGio({targets: {[LINK]: EXT_SRC}}));
    assert.equal(projectRootFrom(LINK, readLink), CHECKOUT);
});

// fileExists stub: true only for the paths listed, records each call.
function existing(...paths) {
    const calls = [];
    const fileExists = (p) => {
        calls.push(p);
        return paths.includes(p);
    };
    fileExists.calls = calls;
    return fileExists;
}

const DECK_PYTHON = `${CHECKOUT}/.venv.streamdeck/bin/python`;

test('streamDeckPython returns the venv python when it is present', () => {
    const fileExists = existing(DECK_PYTHON);
    assert.equal(streamDeckPython(CHECKOUT, fileExists), DECK_PYTHON);
    assert.deepEqual(fileExists.calls, [DECK_PYTHON]);
});

test('streamDeckPython returns null when the venv is absent', () => {
    assert.equal(streamDeckPython(CHECKOUT, existing()), null);
});

test('streamDeckPython tolerates a trailing slash on the root', () => {
    assert.equal(streamDeckPython(`${CHECKOUT}/`, existing(DECK_PYTHON)),
        DECK_PYTHON);
});

test('streamDeckPython: no root, or a fileExists that throws, gives null', () => {
    const fileExists = existing(DECK_PYTHON);
    assert.equal(streamDeckPython('', fileExists), null);
    assert.equal(streamDeckPython(undefined, fileExists), null);
    assert.deepEqual(fileExists.calls, []);
    assert.equal(streamDeckPython(CHECKOUT,
        () => { throw new Error('EACCES'); }), null);
});

// The message the device and controller indicators show without the venv.
const NOT_INSTALLED =
    'ERPLibre Home Stream Deck is not installed: ' +
    'make erplibre_home_streamdeck_install';
const OLD_MSGID = 'Python venv not found at .venv.erplibre';

function extensionFile(rel) {
    return readFileSync(new URL(`../../${rel}`, import.meta.url), 'utf8');
}

// msgstr of `msgid` in a catalog, or undefined when the msgid is absent.
function msgstrOf(catalog, msgid) {
    const quoted = JSON.stringify(msgid);
    const at = catalog.indexOf(`msgid ${quoted}\n`);
    if (at < 0) return undefined;
    const rest = catalog.slice(at).split('\n')[1];
    return JSON.parse(rest.replace(/^msgstr /, ''));
}

test('missing-venv message: a msgid of the .pot, translated in fr and en', () => {
    assert.equal(msgstrOf(extensionFile('po/erplibre-home.pot'),
        NOT_INSTALLED), '');
    assert.equal(msgstrOf(extensionFile('po/en.po'), NOT_INSTALLED),
        NOT_INSTALLED);
    assert.equal(msgstrOf(extensionFile('po/fr.po'), NOT_INSTALLED),
        "ERPLibre Home Stream Deck n'est pas installé : " +
        'make erplibre_home_streamdeck_install');
    for (const po of ['po/erplibre-home.pot', 'po/en.po', 'po/fr.po'])
        assert.equal(msgstrOf(extensionFile(po), OLD_MSGID), undefined, po);
});

test('both deck indicators show that message, and only through _()', () => {
    for (const js of ['indicators/device.js', 'indicators/controller.js']) {
        const src = extensionFile(js);
        assert.ok(src.includes(`_('${NOT_INSTALLED}')`), js);
        assert.ok(src.includes('streamDeckPython('), js);
        assert.ok(!src.includes('.venv.erplibre'), js);
    }
});

test('galleryServerCommand runs the gallery under the venv python, no make', () => {
    assert.equal(galleryServerCommand(CHECKOUT, DECK_PYTHON),
        `'${DECK_PYTHON}' '${CHECKOUT}/script/stream_deck/games/gallery_server.py'`);
    assert.equal(galleryServerCommand(`${CHECKOUT}/`, DECK_PYTHON),
        `'${DECK_PYTHON}' '${CHECKOUT}/script/stream_deck/games/gallery_server.py'`);
});

test('galleryServerCommand quotes a path with a space or a quote', () => {
    const root = "/opt/mon dépôt/l'autre";
    const python = `${root}/.venv.streamdeck/bin/python`;
    assert.equal(galleryServerCommand(root, python),
        "'/opt/mon dépôt/l'\\''autre/.venv.streamdeck/bin/python' " +
        "'/opt/mon dépôt/l'\\''autre/script/stream_deck/games/gallery_server.py'");
});

test('the controller launches the gallery through galleryServerCommand', () => {
    const src = extensionFile('indicators/controller.js');
    assert.ok(src.includes('galleryServerCommand('));
    assert.ok(!src.includes('make streamdeck_gallery'));
});
