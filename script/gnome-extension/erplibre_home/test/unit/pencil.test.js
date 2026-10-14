import {test} from 'node:test';
import assert from 'node:assert/strict';
import {resolveLabel, defaultPathEntry}
    from '../../indicators/pencil.js';

test('resolveLabel uses label when present', () => {
    assert.equal(
        resolveLabel({label: 'My Lab', path: '/home/x/lab'}),
        'My Lab');
});

test('resolveLabel falls back to basename', () => {
    assert.equal(resolveLabel({label: '', path: '/home/x/lab'}), 'lab');
    assert.equal(resolveLabel({path: '/home/x/lab/'}),         'lab');
    assert.equal(resolveLabel({path: '/'}),                    '/');
});

test('defaultPathEntry produces id + claude --resume default', () => {
    const e = defaultPathEntry({label: 'L', path: '/p'});
    assert.match(e.id, /^[0-9a-f]{8}-/);
    assert.equal(e.label, 'L');
    assert.equal(e.path, '/p');
    assert.equal(e.default_cmd, 'claude --resume');
});
