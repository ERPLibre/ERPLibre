import {test} from 'node:test';
import assert from 'node:assert/strict';
import {parseStateEntry, indexSessions, summaryForCwd,
    STATUS_ACTIVE, STATUS_AWAIT_STOP, STATUS_AWAIT_NOTIFY}
    from '../../lib/claude-state.js';

test('parseStateEntry: rejects payloads without session_id', () => {
    assert.equal(parseStateEntry(null), null);
    assert.equal(parseStateEntry({}), null);
    assert.equal(parseStateEntry({session_id: ''}), null);
});

test('parseStateEntry: normalises trailing slash', () => {
    const e = parseStateEntry({
        session_id: 'abc',
        pid: 100,
        cwd: '/home/x/proj/',
        ts_active: 1700,
    });
    assert.equal(e.session_id, 'abc');
    assert.equal(e.pid, 100);
    assert.equal(e.cwd, '/home/x/proj');
    assert.equal(e.status, STATUS_ACTIVE);
    assert.equal(e.ts, 1700);
});

test('parseStateEntry: derives status from max timestamp', () => {
    assert.equal(parseStateEntry(
        {session_id: 'a', ts_active: 50, ts_stop: 100}).status,
        STATUS_AWAIT_STOP);
    assert.equal(parseStateEntry(
        {session_id: 'a', ts_stop: 100, ts_notification: 200}).status,
        STATUS_AWAIT_NOTIFY);
    // User activity after notification clears it.
    assert.equal(parseStateEntry(
        {session_id: 'a', ts_notification: 200, ts_active: 300}).status,
        STATUS_ACTIVE);
    // Tie between notification and stop favours notification.
    assert.equal(parseStateEntry(
        {session_id: 'a', ts_stop: 100, ts_notification: 100}).status,
        STATUS_AWAIT_NOTIFY);
});

test('parseStateEntry: ts_tool yields working status', async () => {
    const {STATUS_WORKING} = await import('../../lib/claude-state.js');
    assert.equal(parseStateEntry(
        {session_id: 'a', ts_active: 50, ts_tool: 100}).status,
        STATUS_WORKING);
    // Stop after tool resets to await_stop (Ctrl+C semantics).
    assert.equal(parseStateEntry(
        {session_id: 'a', ts_tool: 100, ts_stop: 200}).status,
        STATUS_AWAIT_STOP);
    // Notification still wins over working.
    assert.equal(parseStateEntry(
        {session_id: 'a', ts_tool: 100, ts_notification: 200}).status,
        STATUS_AWAIT_NOTIFY);
});

test('parseStateEntry: legacy {status, ts} payload still parses', () => {
    assert.equal(parseStateEntry(
        {session_id: 'a', status: STATUS_AWAIT_STOP, ts: 999}).status,
        STATUS_AWAIT_STOP);
    assert.equal(parseStateEntry(
        {session_id: 'a', status: STATUS_AWAIT_NOTIFY, ts: 999}).status,
        STATUS_AWAIT_NOTIFY);
});

test('indexSessions: empty list yields zeroes', () => {
    const idx = indexSessions([]);
    assert.equal(idx.total, 0);
    assert.equal(idx.totalActive, 0);
    assert.equal(idx.totalAwaiting, 0);
    assert.equal(idx.byPath.size, 0);
});

test('indexSessions: aggregates per cwd + counts statuses', () => {
    const entries = [
        {session_id: 's1', cwd: '/a', status: STATUS_ACTIVE, pid: 1, ts: 1},
        {session_id: 's2', cwd: '/a', status: STATUS_AWAIT_STOP, pid: 2, ts: 2},
        {session_id: 's3', cwd: '/a', status: STATUS_AWAIT_NOTIFY, pid: 3, ts: 3},
        {session_id: 's4', cwd: '/b', status: STATUS_ACTIVE, pid: 4, ts: 4},
    ];
    const idx = indexSessions(entries);
    assert.equal(idx.total, 4);
    assert.equal(idx.totalActive, 2);
    assert.equal(idx.totalAwaitStop, 1);
    assert.equal(idx.totalAwaitNotify, 1);
    assert.equal(idx.totalAwaiting, 2);

    const a = summaryForCwd(idx, '/a');
    assert.equal(a.total, 3);
    assert.equal(a.active, 1);
    assert.equal(a.awaitStop, 1);
    assert.equal(a.awaitNotify, 1);
    assert.equal(a.sessions.length, 3);

    const b = summaryForCwd(idx, '/b');
    assert.equal(b.total, 1);
    assert.equal(b.active, 1);

    assert.equal(summaryForCwd(idx, '/missing'), null);
});

test('indexSessions: tolerates null/undef entries', () => {
    const idx = indexSessions([null, undefined,
        {session_id: 's', cwd: '/x', status: STATUS_ACTIVE}]);
    assert.equal(idx.total, 1);
});
