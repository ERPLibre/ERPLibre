import {test} from 'node:test';
import assert from 'node:assert/strict';
import {_, _identity, setGettext} from '../../lib/i18n.js';

test('_identity returns its input verbatim', () => {
    assert.equal(_identity('Hello'), 'Hello');
    assert.equal(_identity(''), '');
});

test('_ in node falls back to identity (no .mo loaded)', () => {
    // Reset to default before checking — other tests may have called
    // setGettext and left a non-identity wrapper installed.
    setGettext(null);
    assert.equal(_('Hello'), 'Hello');
});

test('setGettext installs a custom resolver', () => {
    setGettext((s) => `[fr] ${s}`);
    assert.equal(_('Hello'), '[fr] Hello');
    setGettext(null);
});

test('setGettext with non-function falls back to identity', () => {
    setGettext('not-a-function');
    assert.equal(_('Hello'), 'Hello');
    setGettext(undefined);
    assert.equal(_('World'), 'World');
});

test('setGettext can be replaced multiple times', () => {
    setGettext((s) => s.toUpperCase());
    assert.equal(_('hello'), 'HELLO');
    setGettext((s) => s.toLowerCase());
    assert.equal(_('HELLO'), 'hello');
    setGettext(null);
});
