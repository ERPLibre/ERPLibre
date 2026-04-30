import {test} from 'node:test';
import assert from 'node:assert/strict';
import {normPath, cwdMatchesPath, assignSessionsToPaths,
    sessionMatchesFilter}
    from '../../lib/pencil-helpers.js';

test('normPath: strips trailing slashes', () => {
    assert.equal(normPath('/a/b'), '/a/b');
    assert.equal(normPath('/a/b/'), '/a/b');
    assert.equal(normPath('/a/b///'), '/a/b');
    assert.equal(normPath(''), '');
    assert.equal(normPath(null), '');
    assert.equal(normPath(undefined), '');
});

test('cwdMatchesPath: exact + subdir + neither', () => {
    assert.equal(cwdMatchesPath('/a/b', '/a/b'), true);
    assert.equal(cwdMatchesPath('/a/b/', '/a/b'), true);
    assert.equal(cwdMatchesPath('/a/b/c', '/a/b'), true);
    assert.equal(cwdMatchesPath('/a/b/c/d', '/a/b'), true);
    assert.equal(cwdMatchesPath('/a/bcd', '/a/b'), false);
    assert.equal(cwdMatchesPath('/a', '/a/b'), false);
    assert.equal(cwdMatchesPath('', '/a'), false);
    assert.equal(cwdMatchesPath('/a', ''), false);
});

test('assignSessionsToPaths: empty inputs', () => {
    assert.equal(assignSessionsToPaths([], []).size, 0);
    assert.equal(assignSessionsToPaths(null, null).size, 0);
    assert.equal(
        assignSessionsToPaths([{session_id: 'x', cwd: '/a'}], []).size, 0);
});

test('assignSessionsToPaths: exact match', () => {
    const m = assignSessionsToPaths(
        [{session_id: 'x', cwd: '/home/leo/erplibre01'}],
        [{path: '/home/leo/erplibre01'}]);
    assert.equal(m.get('x'), '/home/leo/erplibre01');
});

test('assignSessionsToPaths: subdir falls under parent path', () => {
    const m = assignSessionsToPaths(
        [{session_id: 'x', cwd: '/home/leo/erplibre01/mobile/foo'}],
        [{path: '/home/leo/erplibre01'}]);
    assert.equal(m.get('x'), '/home/leo/erplibre01');
});

test('assignSessionsToPaths: longest prefix wins', () => {
    const m = assignSessionsToPaths(
        [{session_id: 'x', cwd: '/a/b/c/d'}],
        [{path: '/a'}, {path: '/a/b/c'}, {path: '/a/b'}]);
    assert.equal(m.get('x'), '/a/b/c');
});

test('assignSessionsToPaths: no match → not in map', () => {
    const m = assignSessionsToPaths(
        [{session_id: 'x', cwd: '/tmp/other'}],
        [{path: '/home/leo/erplibre01'}]);
    assert.equal(m.has('x'), false);
});

test('assignSessionsToPaths: multiple sessions, mixed match', () => {
    const m = assignSessionsToPaths(
        [
            {session_id: 'a', cwd: '/p1'},
            {session_id: 'b', cwd: '/p2/sub'},
            {session_id: 'c', cwd: '/elsewhere'},
        ],
        [{path: '/p1'}, {path: '/p2'}]);
    assert.equal(m.get('a'), '/p1');
    assert.equal(m.get('b'), '/p2');
    assert.equal(m.has('c'), false);
});

test('assignSessionsToPaths: tolerates null/undef sessions', () => {
    const m = assignSessionsToPaths(
        [null, undefined, {session_id: 'a', cwd: '/p'}],
        [{path: '/p'}]);
    assert.equal(m.size, 1);
    assert.equal(m.get('a'), '/p');
});

test('assignSessionsToPaths: trailing-slash on path normalised', () => {
    const m = assignSessionsToPaths(
        [{session_id: 'a', cwd: '/p/sub'}],
        [{path: '/p/'}]);
    assert.equal(m.get('a'), '/p');
});

test('sessionMatchesFilter: null filter passes everything', () => {
    assert.equal(sessionMatchesFilter({status: 'active'}, null), true);
    assert.equal(sessionMatchesFilter({status: 'awaiting_stop'}, null), true);
    assert.equal(sessionMatchesFilter(undefined, null), true);
});

test('sessionMatchesFilter: alive matches active or working only', () => {
    assert.equal(sessionMatchesFilter({status: 'active'},  'alive'), true);
    assert.equal(sessionMatchesFilter({status: 'working'}, 'alive'), true);
    assert.equal(sessionMatchesFilter({status: 'awaiting_stop'},
        'alive'), false);
    assert.equal(sessionMatchesFilter({status: 'awaiting_notification'},
        'alive'), false);
});

test('sessionMatchesFilter: awaiting matches stop and notify', () => {
    assert.equal(sessionMatchesFilter({status: 'awaiting_stop'},
        'awaiting'), true);
    assert.equal(sessionMatchesFilter({status: 'awaiting_notification'},
        'awaiting'), true);
    assert.equal(sessionMatchesFilter({status: 'active'},
        'awaiting'), false);
});

test('sessionMatchesFilter: notify matches notification only', () => {
    assert.equal(sessionMatchesFilter({status: 'awaiting_notification'},
        'notify'), true);
    assert.equal(sessionMatchesFilter({status: 'awaiting_stop'},
        'notify'), false);
    assert.equal(sessionMatchesFilter({status: 'working'},
        'notify'), false);
});
