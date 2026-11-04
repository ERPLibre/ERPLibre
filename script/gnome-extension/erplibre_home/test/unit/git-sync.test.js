import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdirSync, writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {fake, runForReal} from './gjs-fake.js';
import {Debouncer, SYNC_FILE, LEGACY_SYNC_FILE, syncImportPath, gitPull,
    gitCommitPush} from '../../lib/git-sync.js';

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

test('gitPull rebases on the remote, theirs winning a conflict', async () => {
    fake.reset();
    assert.equal(await gitPull('/srv/sync'), true);
    assert.deepEqual(fake.spawned.map(s => s.argv),
        [['git', '-C', '/srv/sync', 'pull', '--rebase',
            '--strategy-option=theirs']]);
});

test('gitPull gives false, never an error, when the pull fails', async () => {
    fake.reset();
    fake.onSpawn = () => ({exit: 1});
    assert.equal(await gitPull('/srv/sync'), false);
    fake.onSpawn = () => { throw new Error('no git'); };
    assert.equal(await gitPull('/srv/sync'), false);
});

const GIT_ENV = {
    GIT_AUTHOR_NAME: 'Deck', GIT_AUTHOR_EMAIL: 'deck@test.invalid',
    GIT_COMMITTER_NAME: 'Deck', GIT_COMMITTER_EMAIL: 'deck@test.invalid',
};

function git(...args) {
    const r = runForReal(['git', ...args], GIT_ENV);
    assert.equal(r.exit, 0, r.stderr);
    return r.stdout.trim();
}

/** A sync repository holding SYNC_FILE; with a remote when `remote`. */
function syncRepo(remote) {
    fake.reset();
    fake.onSpawn = argv => runForReal(argv, GIT_ENV);
    const repo = join(fake.root, 'sync');
    if (remote) {
        const bare = join(fake.root, 'remote.git');
        git('init', '-q', '--bare', bare);
        git('clone', '-q', bare, repo);
        writeFileSync(join(repo, SYNC_FILE), '{}');
        git('-C', repo, 'add', SYNC_FILE);
        git('-C', repo, 'commit', '-q', '-m', 'first');
        git('-C', repo, 'push', '-q', '-u', 'origin', 'HEAD');
    } else {
        mkdirSync(repo);
        git('init', '-q', repo);
    }
    writeFileSync(join(repo, SYNC_FILE), '{"settings": {}}');
    return repo;
}

const AUTO_SYNC = /^auto sync deckhost \d{4}-\d\d-\d\dT\d\d:\d\d/;

test('gitCommitPush commits "auto sync <host> <date>" locally', async () => {
    const repo = syncRepo(false);
    assert.equal(await gitCommitPush(repo, 'deckhost'), true);
    assert.match(git('-C', repo, 'log', '-1', '--format=%s'), AUTO_SYNC);
    assert.equal(git('-C', repo, 'status', '--porcelain'), '');
});

test('gitCommitPush pushes when the repository has a remote', async () => {
    const repo = syncRepo(true);
    assert.equal(await gitCommitPush(repo, 'deckhost'), true);
    assert.match(git('-C', join(fake.root, 'remote.git'), 'log', '-1',
        '--format=%s'), AUTO_SYNC);
});
