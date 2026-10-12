import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
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
