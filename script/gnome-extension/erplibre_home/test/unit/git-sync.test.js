import {test} from 'node:test';
import assert from 'node:assert/strict';
import {Debouncer, SYNC_FILE, LEGACY_SYNC_FILE, syncImportPath} from '../../lib/git-sync.js';

test('Debouncer fires after delay', async () => {
    const calls = [];
    const d = new Debouncer({delayMs: 30,
        scheduler: setTimeout, canceller: clearTimeout});
    d.bump(() => calls.push('a'));
    d.bump(() => calls.push('b'));
    await new Promise(r => setTimeout(r, 60));
    assert.deepEqual(calls, ['b']);
});

test('SYNC_FILE is the ERPLibre Home name', () => {
    assert.equal(SYNC_FILE, 'erplibre-home.json');
    assert.equal(LEGACY_SYNC_FILE, 'streamdeck-tiler.json');
});

test('syncImportPath prefers the new file when both exist', () => {
    const present = new Set(['/r/erplibre-home.json', '/r/streamdeck-tiler.json']);
    assert.equal(syncImportPath('/r', p => present.has(p)),
        '/r/erplibre-home.json');
});

test('syncImportPath falls back to the legacy file', () => {
    const present = new Set(['/r/streamdeck-tiler.json']);
    assert.equal(syncImportPath('/r', p => present.has(p)),
        '/r/streamdeck-tiler.json');
});

test('syncImportPath returns null when neither exists', () => {
    assert.equal(syncImportPath('/r', () => false), null);
});
