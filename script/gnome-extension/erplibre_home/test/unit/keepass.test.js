import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname, join} from 'node:path';
import {fake} from './gjs-fake.js';
import {
    extractAttribute,
    cacheKey,
    MasterPasswordCache,
    callKeepassCli,
} from '../../lib/keepass.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const FIXTURE = join(__dirname, '..', 'fixtures', 'keepassxc-cli-show.txt');

test('extractAttribute strips trailing newline from CLI stdout', () => {
    const stdout = readFileSync(FIXTURE, 'utf8');
    assert.equal(extractAttribute(stdout), 'admin@example.com');
});

test('cacheKey concatenates db + keyfile + yubikey_serial', () => {
    assert.equal(
        cacheKey({db: '/d.kdbx', keyfile: '/k', yubikey_serial: '1234'}),
        '/d.kdbx:/k:1234'
    );
    assert.equal(
        cacheKey({db: '/d.kdbx'}),
        '/d.kdbx::'
    );
});

test('MasterPasswordCache stores then expires entries', async () => {
    const cache = new MasterPasswordCache({ttlMs: 50});
    cache.set('k', 'secret');
    assert.equal(cache.get('k'), 'secret');
    await new Promise(r => setTimeout(r, 80));
    assert.equal(cache.get('k'), undefined);
});

test('MasterPasswordCache.invalidate removes entry', () => {
    const cache = new MasterPasswordCache();
    cache.set('k', 'secret');
    cache.invalidate('k');
    assert.equal(cache.get('k'), undefined);
});

test('MasterPasswordCache keeps an entry 5 minutes by default', () => {
    let now = 1000;
    const cache = new MasterPasswordCache({now: () => now});
    cache.set('k', 'secret');
    now += 5 * 60 * 1000;
    assert.equal(cache.get('k'), 'secret');
    now += 1;
    assert.equal(cache.get('k'), undefined);
});

const UNLOCK = {db: '/v/team.kdbx', entry: 'erp/admin',
    attribute: 'password', masterPassword: 'hunter2'};

test('callKeepassCli runs show -a with the password on stdin', async () => {
    fake.reset();
    fake.onSpawn = () => ({stdout: 's3cret\n'});
    assert.equal(await callKeepassCli(UNLOCK), 's3cret');
    assert.deepEqual(fake.spawned.map(s => s.argv),
        [['keepassxc-cli', 'show', '-a', 'password', '/v/team.kdbx',
            'erp/admin']]);
    assert.equal(fake.spawned[0].stdin, 'hunter2\n');
});

test('callKeepassCli passes the key file and the YubiKey slot', async () => {
    const cases = [
        [{keyfile: '/v/k.key', yubikey_slot: 2, yubikey_serial: '1234'},
            ['--key-file', '/v/k.key', '--yubikey', '2:1234']],
        [{yubikey_slot: 1}, ['--yubikey', '1']],
        [{yubikey_slot: 0, yubikey_serial: '1234'}, []],
    ];
    for (const [extra, options] of cases) {
        fake.reset();
        await callKeepassCli({...UNLOCK, ...extra});
        assert.deepEqual(fake.spawned[0].argv,
            ['keepassxc-cli', 'show', '-a', 'password', ...options,
                '/v/team.kdbx', 'erp/admin'], JSON.stringify(extra));
    }
});

test('callKeepassCli gives null when keepassxc-cli fails', async () => {
    fake.reset();
    fake.onSpawn = () => ({exit: 1, stdout: ''});
    assert.equal(await callKeepassCli(UNLOCK), null);
    fake.onSpawn = () => { throw new Error('no keepassxc-cli'); };
    assert.equal(await callKeepassCli(UNLOCK), null);
});
