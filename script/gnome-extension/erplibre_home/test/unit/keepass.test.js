import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname, join} from 'node:path';
import {
    extractAttribute,
    cacheKey,
    MasterPasswordCache,
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
