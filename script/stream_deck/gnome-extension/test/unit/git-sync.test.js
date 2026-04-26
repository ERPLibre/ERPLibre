import {test} from 'node:test';
import assert from 'node:assert/strict';
import {Debouncer} from '../../lib/git-sync.js';

test('Debouncer fires after delay', async () => {
    const calls = [];
    const d = new Debouncer({delayMs: 30,
        scheduler: setTimeout, canceller: clearTimeout});
    d.bump(() => calls.push('a'));
    d.bump(() => calls.push('b'));
    await new Promise(r => setTimeout(r, 60));
    assert.deepEqual(calls, ['b']);
});
