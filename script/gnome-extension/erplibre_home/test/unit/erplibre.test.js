import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {chmodSync, mkdirSync, writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {fake, makeSettings, settle} from './gjs-fake.js';
import {masterPasswordCache, cacheKey} from '../../lib/keepass.js';
import {parseList} from '../../lib/settings.js';

// After gjs-fake.js: the indicator imports gi:// modules statically.
const {indicatorDescriptor} = await import('../../indicators/erplibre.js');

const INSTANCE = {
    id: 'r1', type: 'remote', name: 'R', url: 'https://erp.test',
    keepass_db: '/v/team.kdbx', keepass_entry: 'erp/admin',
    auto_login_method: 'selenium',
};

beforeEach(() => {
    fake.reset();
    masterPasswordCache.clear();
    // keepassxc-cli answers the attribute it is asked for.
    fake.onSpawn = argv => (argv[0] === 'keepassxc-cli'
        ? {stdout: {username: 'admin', password: 's3cret'}[argv[3]] + '\n'}
        : {});
});

function erplibre(instance = INSTANCE, overrides = {}) {
    const settings = makeSettings({'erplibre-auto-detect': false,
        'instances': JSON.stringify(instance ? [instance] : []),
        ...overrides});
    fake.settings = settings;
    return indicatorDescriptor.ctor({
        extension: {getSettings: () => settings, path: fake.root},
        openPrefs() {}});
}

function find(menu, label) {
    for (const it of menu.items) {
        if (it.text === label) return it;
        const found = it.menu ? find(it.menu, label) : null;
        if (found) return found;
    }
    return null;
}

/** The item labelled `label` in `menu`, searched through sub-menus. */
function item(menu, label) {
    const found = find(menu, label);
    assert.ok(found, `menu item ${label}`);
    return found;
}

async function activate(ind, label) {
    item(item(ind.menu, `⚪ ${INSTANCE.name}`).menu, label).activate();
    await settle();
}

function cachePassword(instance = INSTANCE) {
    masterPasswordCache.set(cacheKey({db: instance.keepass_db,
        keyfile: instance.keepass_keyfile,
        yubikey_serial: instance.keepass_yubikey_serial}), 'master');
}

const spawnedOutside = () => fake.spawned.map(s => s.argv)
    .filter(a => a[0] !== 'keepassxc-cli');

test('Open in KeePassXC opens the database with its key file', async () => {
    await activate(erplibre({...INSTANCE, keepass_keyfile: '/v/k.key'}),
        'Open in KeePassXC');
    assert.deepEqual(spawnedOutside(),
        [['keepassxc', '/v/team.kdbx', '--keyfile', '/v/k.key']]);

    fake.spawned = [];
    await activate(erplibre(), 'Open in KeePassXC');
    assert.deepEqual(spawnedOutside(), [['keepassxc', '/v/team.kdbx']]);
});

function projectWithVenv() {
    const root = join(fake.root, 'checkout');
    const bin = join(root, '.venv.erplibre', 'bin');
    mkdirSync(bin, {recursive: true});
    writeFileSync(join(bin, 'python'), '#!/bin/sh\n');
    chmodSync(join(bin, 'python'), 0o755);
    return root;
}

test('selenium auto-login runs web_login.py in .venv.erplibre', async () => {
    const root = projectWithVenv();
    cachePassword();
    await activate(erplibre(INSTANCE, {'git-sync-path': root}),
        'Auto-login (selenium)');
    assert.deepEqual(spawnedOutside(), [[
        `${root}/.venv.erplibre/bin/python`,
        `${root}/script/selenium/web_login.py`,
        '--url', 'https://erp.test', '--user', 'admin', '--pass', 's3cret',
    ]]);
});

const XDOTOOL = [
    ['xdg-open', 'https://erp.test'],
    ['sleep', '2'],
    ['xdotool', 'type', 'admin'],
    ['xdotool', 'key', 'Tab'],
    ['xdotool', 'type', 's3cret'],
    ['xdotool', 'key', 'Return'],
];

test('xdotool auto-login opens the URL, then types the login', async () => {
    cachePassword();
    const inst = {...INSTANCE, auto_login_method: 'xdotool'};
    await activate(erplibre(inst), 'Auto-login (xdotool)');
    assert.deepEqual(spawnedOutside(), XDOTOOL);
});

test('selenium without .venv.erplibre falls back to xdotool', async () => {
    cachePassword();
    await activate(erplibre(INSTANCE,
        {'git-sync-path': join(fake.root, 'no-venv')}),
    'Auto-login (selenium)');
    assert.deepEqual(spawnedOutside(), XDOTOOL);
    assert.equal(fake.notified.length, 1);
});

function unlockDialogs() {
    return fake.dialogs.filter(d => d._entry);
}

test('a fresh cached master password unlocks without a prompt', async () => {
    const ind = erplibre();
    await activate(ind, 'Copy username');
    const [dialog] = unlockDialogs();
    assert.equal(dialog.opened, true);
    assert.deepEqual(fake.spawned, []);

    dialog._entry.set_text('master');
    dialog.buttons.find(b => b.default).action();
    await settle();
    assert.deepEqual(fake.clipboard, ['admin']);

    await activate(ind, 'Copy password');
    assert.equal(unlockDialogs().length, 1);
    assert.deepEqual(fake.clipboard, ['admin', 's3cret']);
    assert.deepEqual(fake.spawned.map(s => s.stdin),
        ['master\n', 'master\n']);
});

const UUID4 =
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

/** Save the add-instance dialog with `fields`, then the stored list. */
function addRemote(fields) {
    const ind = erplibre(null);
    item(ind.menu, '+ Add remote instance…').activate();
    const dialog = fake.dialogs.at(-1);
    for (const [k, v] of Object.entries(fields))
        dialog._fields[k].set_text(v);
    dialog.buttons.find(b => b.default).action();
    return parseList(fake.settings.get_string('instances'));
}

test('a remote instance is stored as type remote with a uuid', () => {
    const [entry] = addRemote({name: 'Prod', url: 'https://erp.test',
        keepass_db: '/v/team.kdbx', keepass_entry: 'erp/admin',
        auto_login_method: 'xdotool'});
    assert.match(entry.id, UUID4);
    assert.equal(entry.type, 'remote');
    assert.equal(entry.local_path, '');
    assert.equal(entry.name, 'Prod');
    assert.equal(entry.url, 'https://erp.test');
    assert.equal(entry.port, 8069);
    assert.equal(entry.keepass_db, '/v/team.kdbx');
    assert.equal(entry.keepass_entry, 'erp/admin');
    assert.equal(entry.auto_login_method, 'xdotool');
});

test('an unknown login method is stored as selenium', () => {
    for (const [given, stored] of [['none', 'none'], ['xdotool', 'xdotool'],
        ['selenium', 'selenium'], ['', 'selenium'], ['robot', 'selenium']]) {
        fake.reset();
        const [entry] = addRemote({name: 'P', url: 'https://erp.test',
            auto_login_method: given});
        assert.equal(entry.auto_login_method, stored, given);
    }
});
