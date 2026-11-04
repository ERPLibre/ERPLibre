import {test} from 'node:test';
import assert from 'node:assert/strict';
import {existsSync, readFileSync} from 'node:fs';
import {join} from 'node:path';
import {fake, settle} from './gjs-fake.js';
import {
    runProcess,
    spawnDetached,
    buildTerminalArgv,
    buildBrowserArgv,
    buildMpvArgv,
    buildVlcArgv,
    buildSpotifyArgv,
    parsePosition,
    formatPosition,
} from '../../lib/spawn.js';

test('buildTerminalArgv with cwd + command', () => {
    const argv = buildTerminalArgv({
        cwd: '/home/x/proj',
        command: 'claude --resume',
        terminal: 'gnome-terminal',
    });
    assert.deepEqual(argv, [
        'gnome-terminal', '--working-directory=/home/x/proj',
        '--', 'bash', '-lc', 'claude --resume; exec bash',
    ]);
});

test('buildTerminalArgv falls back to xterm', () => {
    const argv = buildTerminalArgv({
        cwd: '/p', command: 'cmd', terminal: 'xterm',
    });
    assert.deepEqual(argv, ['xterm', '-e',
        'bash -lc "cd /p && cmd; exec bash"']);
});

test('buildBrowserArgv', () => {
    assert.deepEqual(
        buildBrowserArgv('https://example.com'),
        ['xdg-open', 'https://example.com']
    );
});

test('buildMpvArgv with position', () => {
    assert.deepEqual(
        buildMpvArgv('https://x', '00:01:23'),
        ['mpv', '--script-opts=ytdl_hook-ytdl_path=yt-dlp',
         '--save-position-on-quit=yes',
         '--start=00:01:23', 'https://x']
    );
});

test('buildMpvArgv without position', () => {
    assert.deepEqual(
        buildMpvArgv('https://x', ''),
        ['mpv', '--script-opts=ytdl_hook-ytdl_path=yt-dlp',
         '--save-position-on-quit=yes', 'https://x']
    );
});

test('buildMpvArgv always pins ytdl backend to yt-dlp', () => {
    const argv = buildMpvArgv('https://x', '');
    assert.ok(argv.some(a => a.includes('ytdl_path=yt-dlp')),
        `expected yt-dlp in argv, got ${argv}`);
});

test('buildMpvArgv enables save-position-on-quit', () => {
    const argv = buildMpvArgv('https://x', '');
    assert.ok(argv.includes('--save-position-on-quit=yes'),
        `expected save-position arg in ${argv}`);
});

test('buildVlcArgv wraps with yt-dlp resolver shell command', () => {
    const argv = buildVlcArgv('https://x', '');
    assert.equal(argv[0], 'bash');
    assert.equal(argv[1], '-c');
    assert.match(argv[2], /yt-dlp -g -f best "\$1"/);
    assert.match(argv[2], /exec vlc /);
    // URL is pased as $1 (after the script name placeholder).
    assert.equal(argv[3], 'sdt-vlc');
    assert.equal(argv[4], 'https://x');
});

test('buildVlcArgv embeds --start-time when position set', () => {
    const argv = buildVlcArgv('https://x', '00:01:23');
    assert.match(argv[2], /exec vlc --start-time=83/);
});

test('buildSpotifyArgv hands the URI to xdg-open', () => {
    assert.deepEqual(
        buildSpotifyArgv('spotify:track:abc'),
        ['xdg-open', 'spotify:track:abc']);
    assert.deepEqual(
        buildSpotifyArgv('https://open.spotify.com/track/abc'),
        ['xdg-open', 'https://open.spotify.com/track/abc']);
});

test('buildVlcArgv passes URL via $1 (no quoting hell)', () => {
    const argv = buildVlcArgv('https://x?with&weird="chars', '');
    // The URL is in argv[4] verbatim; the shell never sees it as
    // unescaped text inside the script string.
    assert.equal(argv[4], 'https://x?with&weird="chars');
    assert.match(argv[2], /\$\{URL:-\$1\}/);
});

test('parsePosition handles hh:mm:ss / mm:ss / seconds', () => {
    assert.equal(parsePosition('01:23:45'), 5025);
    assert.equal(parsePosition('05:30'),    330);
    assert.equal(parsePosition('120'),      120);
    assert.equal(parsePosition(''),         0);
    assert.equal(parsePosition('garbage'),  0);
});

test('formatPosition seconds → hh:mm:ss', () => {
    assert.equal(formatPosition(5025), '01:23:45');
    assert.equal(formatPosition(0),    '00:00:00');
    assert.equal(formatPosition(59),   '00:00:59');
});

test('a malformed URL reaches the player verbatim', () => {
    // The player, not the extension, reports a bad URL.
    for (const url of ['not a url', 'htp:/x y', '://', 'https://']) {
        assert.deepEqual(buildBrowserArgv(url), ['xdg-open', url]);
        assert.equal(buildMpvArgv(url, '').at(-1), url);
        assert.equal(buildMpvArgv(url, '1:00').at(-1), url);
    }
});

/** The entries of the extension log, once the async append landed. */
async function logEntries() {
    const path = join(fake.env.XDG_STATE_HOME, 'erplibre-home', 'log.jsonl');
    for (let i = 0; i < 50 && !existsSync(path); i++) await settle();
    return readFileSync(path, 'utf8').trim().split('\n')
        .map(l => JSON.parse(l));
}

test('a spawn that fails notifies and logs under the program', async () => {
    fake.reset();
    fake.onSpawn = () => { throw new Error('No such file'); };
    const notified = [];
    const ok = await spawnDetached(['mpv', 'https://v.test/a'],
        {notify: (t, b) => notified.push([t, b]), title: 'Media'});
    assert.equal(ok, false);
    assert.deepEqual(notified, [['Media', 'Spawn failed: No such file']]);
    const [entry] = await logEntries();
    assert.equal(entry.level, 'error');
    assert.equal(entry.source, 'mpv');
    assert.equal(entry.message, 'mpv https://v.test/a :: No such file');
});

test('a command that exits non-zero notifies and logs its exit', async () => {
    fake.reset();
    fake.onSpawn = () => ({exit: 3, stderr: 'locked'});
    const notified = [];
    const res = await runProcess(['xdotool', 'key', 'Tab'],
        {notify: (t, b) => notified.push([t, b]), title: 'ERPLibre'});
    assert.equal(res.ok, false);
    assert.equal(res.exit, 3);
    assert.deepEqual(notified, [['ERPLibre', 'Command failed: xdotool']]);
    const [entry] = await logEntries();
    assert.equal(entry.level, 'error');
    assert.equal(entry.source, 'xdotool');
    assert.equal(entry.message, 'xdotool key Tab :: exit=3 locked');
});
