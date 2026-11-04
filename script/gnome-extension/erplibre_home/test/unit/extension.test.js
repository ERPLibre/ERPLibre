import {test, beforeEach, afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {existsSync, mkdirSync, readFileSync} from 'node:fs';
import {join} from 'node:path';
import {fake, makeSettings, settle} from './gjs-fake.js';

// After gjs-fake.js: extension.js imports gi:// modules statically.
const {default: ERPLibreHomeExtension} = await import('../../extension.js');

let ext = null;

beforeEach(() => fake.reset());

afterEach(() => {
    try { ext?.disable(); } catch (_e) {}
    ext = null;
});

async function enabled(overrides = {}) {
    fake.settings = makeSettings({
        'enable-claude-state-watch': false, ...overrides});
    ext = new ERPLibreHomeExtension({
        uuid: 'erplibre-home@technolibre.ca', path: fake.root});
    ext.enable();
    await settle();
    return ext;
}

function mounted(id) {
    const rec = fake.panel.find(p => p.role.endsWith(`-${id}`));
    assert.ok(rec, `indicator ${id} is mounted`);
    return rec.indicator;
}

/** The panel icon of indicator `id`: its first St.Icon. */
function panelIcon(id) {
    const i = fake.panel.findIndex(p => p.role.endsWith(`-${id}`));
    assert.ok(i >= 0, `indicator ${id} is mounted`);
    const from = i === 0 ? 0 : fake.panel[i - 1].widgetCount;
    const icon = fake.widgets.slice(from, fake.panel[i].widgetCount)
        .find(w => w.type === 'Icon');
    assert.ok(icon, `indicator ${id} shows an icon`);
    return icon.props.icon_name ?? icon.props.gicon?.icon;
}

/** The exported interface: method name → {in, out} GVariant types. */
function exportedMethods() {
    assert.equal(fake.exported.length, 1);
    const methods = new Map();
    const re = /<method name="(\w+)">([\s\S]*?)<\/method>/g;
    for (const [, name, body] of fake.exported[0].xml.matchAll(re)) {
        const args = [...body.matchAll(
            /<arg type="([^"]+)" direction="(in|out)"/g)];
        methods.set(name, {
            in: args.filter(a => a[2] === 'in').map(a => a[1]).join(''),
            out: args.filter(a => a[2] === 'out').map(a => a[1]).join(''),
        });
    }
    return methods;
}

function assertSignatures(expected) {
    const methods = exportedMethods();
    for (const [name, sig] of Object.entries(expected)) {
        assert.deepEqual(methods.get(name), sig, name);
        assert.equal(typeof fake.exported[0].object[name], 'function',
            `${name} is implemented by the exported object`);
    }
}

test('the indicator methods keep their D-Bus signatures', async () => {
    // A caller built against a signature gets an error from the bus when
    // an argument is added, dropped or retyped.
    await enabled();
    assertSignatures({
        OpenPath: {in: 's', out: 'b'},
        OpenFilm: {in: 'ss', out: 'b'},
        OpenInstance: {in: 'ss', out: 'b'},
        ScanNetwork: {in: '', out: 's'},
        ListDevices: {in: '', out: 's'},
        ListPaths: {in: '', out: 's'},
        ListFilms: {in: '', out: 's'},
        ListInstances: {in: '', out: 's'},
    });
});

test('the tiling, tracker and hot-reload methods stay exported', async () => {
    // The deck's tiling, timers, layouts and dev-reload plugins call these.
    await enabled();
    assertSignatures({
        TileWindow: {in: 'iiiiii', out: 'b'},
        GetMonitorGeometry: {in: '', out: 'iiii'},
        GetGridSize: {in: 'ii', out: 'ii'},
        ListTrackerTimers: {in: '', out: 's'},
        ToggleTrackerTimer: {in: 's', out: 'b'},
        AddTrackerTimer: {in: '', out: 's'},
        HotReload: {in: '', out: 's'},
        HotExit: {in: '', out: 'b'},
        ResetAllTrackerTimers: {in: '', out: 'b'},
        ListWindows: {in: '', out: 's'},
        ApplyLayout: {in: 's', out: 'i'},
        GetFocusedWindowClass: {in: '', out: 's'},
    });
});

const REMOTE = {id: 'r1', type: 'remote', name: 'R', url: 'https://r.test'};
const LOCAL = {id: 'l1', type: 'local', name: 'L',
    url: 'http://localhost:8069', local_path: '/srv/erp'};

async function erplibreSpy() {
    await enabled({instances: JSON.stringify([REMOTE])});
    const ind = mounted('erplibre');
    ind._localCache = [LOCAL];
    const calls = [];
    ind._launchBrowser = inst => calls.push(['url', inst.id]);
    ind._autoLogin = inst => calls.push(['login', inst.id]);
    ind._copyAttr = (inst, attr) => calls.push([`copy ${attr}`, inst.id]);
    ind._openInKeepassXC = inst => calls.push(['keepass', inst.id]);
    ind._startServer = inst => calls.push(['server', inst.id]);
    return calls;
}

test('OpenInstance maps each action to its instance action', async () => {
    const calls = await erplibreSpy();
    const expected = {
        url: ['url', 'r1'],
        login: ['login', 'r1'],
        copy_user: ['copy username', 'r1'],
        copy_pass: ['copy password', 'r1'],
        open_keepass: ['keepass', 'r1'],
    };
    for (const [action, call] of Object.entries(expected)) {
        calls.length = 0;
        assert.equal(ext.OpenInstance('r1', action), true, action);
        assert.deepEqual(calls, [call], action);
    }
});

test('OpenInstance answers false to an unknown action or id', async () => {
    const calls = await erplibreSpy();
    assert.equal(ext.OpenInstance('r1', 'reboot'), false);
    assert.equal(ext.OpenInstance('r1', ''), false);
    assert.equal(ext.OpenInstance('nope', 'url'), false);
    assert.deepEqual(calls, []);
});

test('OpenInstance starts a server for a local instance only', async () => {
    const calls = await erplibreSpy();
    assert.equal(ext.OpenInstance('r1', 'start_server'), false);
    assert.deepEqual(calls, []);
    assert.equal(ext.OpenInstance('l1', 'start_server'), true);
    assert.deepEqual(calls, [['server', 'l1']]);
});

test('OpenFilm plays in mpv or the browser, the default', async () => {
    const film = {id: 'f1', name: 'F', url: 'https://v.test/f1'};
    await enabled({media: JSON.stringify([film])});
    const ind = mounted('media');
    const launched = [];
    ind._launch = (entry, player) => launched.push([entry.id, player]);
    for (const player of ['mpv', 'browser', '', 'vlc'])
        assert.equal(ext.OpenFilm('f1', player), true, player);
    assert.deepEqual(launched, [['f1', 'mpv'], ['f1', 'browser'],
        ['f1', 'browser'], ['f1', 'browser']]);
    assert.equal(ext.OpenFilm('nope', 'mpv'), false);
    assert.equal(launched.length, 4);
    assert.equal(ext.ListFilms(), JSON.stringify([film]));
});

test('each indicator shows its default symbolic icon', async () => {
    await enabled();
    assert.deepEqual(
        Object.fromEntries(['controller', 'pencil', 'media', 'erplibre',
            'network', 'device'].map(id => [id, panelIcon(id)])),
        {
            controller: 'input-gaming-symbolic',
            pencil: 'document-edit-symbolic',
            media: 'video-x-generic-symbolic',
            erplibre: 'network-server-symbolic',
            network: 'network-wired-symbolic',
            device: 'input-tablet-symbolic',
        });
});

test('icon-overrides replaces the icons of the named indicators', async () => {
    await enabled({'icon-overrides': JSON.stringify({
        pencil: 'emblem-ok-symbolic', network: '/opt/icons/net.svg'})});
    assert.equal(panelIcon('pencil'), 'emblem-ok-symbolic');
    assert.equal(panelIcon('network'), '/opt/icons/net.svg');
    assert.equal(panelIcon('device'), 'input-tablet-symbolic');

    // A change remounts the indicators with the new icons.
    fake.panel = [];
    fake.widgets = [];
    fake.settings.set_string('icon-overrides',
        JSON.stringify({device: 'emblem-system-symbolic'}));
    assert.equal(panelIcon('device'), 'emblem-system-symbolic');
    assert.equal(panelIcon('pencil'), 'document-edit-symbolic');
});

test('a non-object icon-overrides keeps the default icons', async () => {
    for (const bad of ['not json', '["pencil"]']) {
        fake.panel = [];
        fake.widgets = [];
        ext?.disable();
        await enabled({'icon-overrides': bad});
        assert.equal(panelIcon('pencil'), 'document-edit-symbolic', bad);
    }
});

const PULL_ARGV = repo => ['git', '-C', repo, 'pull', '--rebase',
    '--strategy-option=theirs'];

test('enable pulls the sync repository, theirs on conflict', async () => {
    const repo = join(fake.root, 'sync');
    await enabled({'enable-git-sync': true, 'git-sync-path': repo});
    assert.deepEqual(fake.spawned.filter(s => s.argv[0] === 'git')
        .map(s => s.argv), [PULL_ARGV(repo)]);
});

test('a failed pull leaves enable whole', async () => {
    const repo = join(fake.root, 'sync');
    fake.onSpawn = argv => (argv[0] === 'git' ? {exit: 1} : {});
    await enabled({'enable-git-sync': true, 'git-sync-path': repo});
    assert.equal(fake.panel.length, 6);
    assert.ok(fake.spawned.some(s => s.argv[0] === 'git'));
});

test('enable pulls nothing when the sync is off', async () => {
    await enabled({'git-sync-path': join(fake.root, 'sync')});
    assert.deepEqual(fake.spawned.filter(s => s.argv[0] === 'git'), []);
});

test('a settings change is written 5 s later, on a single timer', async () => {
    const repo = join(fake.root, 'sync');
    mkdirSync(repo);
    await enabled({'enable-git-sync': true, 'git-sync-path': repo});
    const before = fake.timeouts.length;
    fake.settings.set_string('paths', '[{"path": "/a"}]');
    fake.settings.set_string('paths', '[{"path": "/b"}]');
    const sync = fake.timeouts.slice(before).filter(t => t.ms === 5000);
    assert.equal(sync.length, 2);
    assert.deepEqual(sync.map(t => t.removed), [true, false]);
    assert.equal(existsSync(join(repo, 'erplibre-home.json')), false);
    sync[1].fn();
    await settle();
    const written = JSON.parse(
        readFileSync(join(repo, 'erplibre-home.json'), 'utf8'));
    assert.equal(written.settings.paths, '[{"path": "/b"}]');
});
