import {test} from 'node:test';
import assert from 'node:assert/strict';
import {_, _identity} from '../../lib/i18n.js';

test('_identity returns its input verbatim', () => {
    assert.equal(_identity('Hello'), 'Hello');
    assert.equal(_identity(''), '');
});

test('_ in node falls back to identity (no .mo loaded)', () => {
    assert.equal(_('Hello'), 'Hello');
});
