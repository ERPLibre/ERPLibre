import {test} from 'node:test';
import assert from 'node:assert/strict';
import {formatLogEntry, trimLog, MAX_LOG_LINES, LOG_LEVELS}
    from '../../lib/log.js';

test('formatLogEntry: defaults missing fields', () => {
    const line = formatLogEntry({source: 'film', message: 'oops'});
    const parsed = JSON.parse(line);
    assert.equal(parsed.source, 'film');
    assert.equal(parsed.level, 'info');
    assert.equal(parsed.message, 'oops');
    assert.ok(line.endsWith('\n'));
    assert.ok(Number.isFinite(parsed.ts));
});

test('formatLogEntry: clamps unknown level to info', () => {
    const parsed = JSON.parse(formatLogEntry({level: 'critical'}));
    assert.equal(parsed.level, 'info');
});

test('formatLogEntry: keeps known levels', () => {
    for (const lvl of LOG_LEVELS) {
        assert.equal(JSON.parse(formatLogEntry({level: lvl})).level, lvl);
    }
});

test('trimLog: short text untouched', () => {
    const t = 'a\nb\nc\n';
    assert.equal(trimLog(t, 5), 'a\nb\nc\n');
});

test('trimLog: drops oldest beyond cap', () => {
    const big = Array.from({length: 10}, (_, i) => `l${i}`).join('\n');
    const out = trimLog(big, 3);
    assert.equal(out.split('\n').filter(Boolean).join(','), 'l7,l8,l9');
});

test('trimLog: empty input', () => {
    assert.equal(trimLog('', 5), '');
    assert.equal(trimLog(null, 5), '');
});

test('MAX_LOG_LINES is reasonable default', () => {
    assert.ok(MAX_LOG_LINES >= 100);
});
