import {test} from 'node:test';
import assert from 'node:assert/strict';
import {IndicatorRegistry} from '../../lib/registry.js';

test('register stores entries by id', () => {
    const reg = new IndicatorRegistry();
    const ctorA = () => ({});
    reg.register({id: 'a', ctor: ctorA, displayName: 'A'});
    assert.equal(reg.list().length, 1);
    assert.equal(reg.list()[0].id, 'a');
    assert.equal(reg.get('a').ctor, ctorA);
});

test('register rejects duplicate ids', () => {
    const reg = new IndicatorRegistry();
    reg.register({id: 'a', ctor: () => ({}), displayName: 'A'});
    assert.throws(
        () => reg.register({id: 'a', ctor: () => ({}), displayName: 'A2'}),
        /already registered/
    );
});

test('list preserves registration order', () => {
    const reg = new IndicatorRegistry();
    reg.register({id: 'a', ctor: () => ({}), displayName: 'A'});
    reg.register({id: 'b', ctor: () => ({}), displayName: 'B'});
    reg.register({id: 'c', ctor: () => ({}), displayName: 'C'});
    assert.deepEqual(reg.list().map(e => e.id), ['a', 'b', 'c']);
});

test('orderedIds applies button-order, ignoring unknowns, appending missing', () => {
    const reg = new IndicatorRegistry();
    for (const id of ['a', 'b', 'c']) {
        reg.register({id, ctor: () => ({}), displayName: id});
    }
    assert.deepEqual(reg.orderedIds(['c', 'a']), ['c', 'a', 'b']);
    assert.deepEqual(reg.orderedIds(['z', 'b']), ['b', 'a', 'c']);
});
