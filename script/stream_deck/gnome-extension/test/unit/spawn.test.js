import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
    buildTerminalArgv,
    buildBrowserArgv,
    buildMpvArgv,
    buildVlcArgv,
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
         '--start=00:01:23', 'https://x']
    );
});

test('buildMpvArgv without position', () => {
    assert.deepEqual(
        buildMpvArgv('https://x', ''),
        ['mpv', '--script-opts=ytdl_hook-ytdl_path=yt-dlp', 'https://x']
    );
});

test('buildMpvArgv always pins ytdl backend to yt-dlp', () => {
    const argv = buildMpvArgv('https://x', '');
    assert.ok(argv.some(a => a.includes('ytdl_path=yt-dlp')),
        `expected yt-dlp in argv, got ${argv}`);
});

test('buildVlcArgv with hh:mm:ss position', () => {
    assert.deepEqual(
        buildVlcArgv('https://x', '00:01:23'),
        ['vlc', '--start-time=83', 'https://x']
    );
});

test('buildVlcArgv with seconds position', () => {
    assert.deepEqual(
        buildVlcArgv('https://x', '120'),
        ['vlc', '--start-time=120', 'https://x']
    );
});

test('buildVlcArgv without position', () => {
    assert.deepEqual(buildVlcArgv('https://x', ''), ['vlc', 'https://x']);
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
