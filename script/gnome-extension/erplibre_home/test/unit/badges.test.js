import {test} from 'node:test';
import assert from 'node:assert/strict';
import {formatBadgeCount, formatBadgeTooltip, pickHighestKind, badgeStyleFor,
    normaliseOrientation, ORIENT_VERTICAL, ORIENT_HORIZONTAL,
    BADGE_DEFAULT, BADGE_WARN, BADGE_ALERT}
    from '../../lib/badges.js';

test('formatBadgeCount: 0 yields empty', () => {
    assert.equal(formatBadgeCount(0), '');
    assert.equal(formatBadgeCount(-3), '');
    assert.equal(formatBadgeCount(NaN), '');
    assert.equal(formatBadgeCount(undefined), '');
});

test('formatBadgeCount: small numbers stringified', () => {
    assert.equal(formatBadgeCount(1), '1');
    assert.equal(formatBadgeCount(7), '7');
    assert.equal(formatBadgeCount(99), '99');
});

test('formatBadgeCount: caps at 99+ by default', () => {
    assert.equal(formatBadgeCount(100), '99+');
    assert.equal(formatBadgeCount(2500), '99+');
});

test('formatBadgeCount: custom cap honoured', () => {
    assert.equal(formatBadgeCount(15, 9), '9+');
    assert.equal(formatBadgeCount(9, 9), '9');
});

test('pickHighestKind: alert beats warn beats default', () => {
    assert.equal(pickHighestKind([]), BADGE_DEFAULT);
    assert.equal(pickHighestKind([{kind: BADGE_DEFAULT}]), BADGE_DEFAULT);
    assert.equal(pickHighestKind(
        [{kind: BADGE_WARN}, {kind: BADGE_DEFAULT}]), BADGE_WARN);
    assert.equal(pickHighestKind(
        [{kind: BADGE_WARN}, {kind: BADGE_ALERT}]), BADGE_ALERT);
});

test('badgeStyleFor returns the same string for unknown kinds', () => {
    assert.equal(badgeStyleFor('nope'), badgeStyleFor(BADGE_DEFAULT));
});

test('formatBadgeTooltip skips zero entries unless flagged', () => {
    assert.equal(
        formatBadgeTooltip([
            {count: 3, label: 'paths'},
            {count: 0, label: 'awaiting'},
            {count: 2, label: 'active'},
        ]),
        '3 paths · 2 active');
    assert.equal(
        formatBadgeTooltip([
            {count: 0, label: 'paths', alwaysShow: true},
        ]),
        '0 paths');
});

test('formatBadgeTooltip falls back to bare count when no label', () => {
    assert.equal(formatBadgeTooltip([{count: 5}]), '5');
    assert.equal(formatBadgeTooltip([]), '');
    assert.equal(formatBadgeTooltip(null), '');
});

test('normaliseOrientation defaults to vertical', () => {
    assert.equal(normaliseOrientation('vertical'), ORIENT_VERTICAL);
    assert.equal(normaliseOrientation('horizontal'), ORIENT_HORIZONTAL);
    assert.equal(normaliseOrientation(''), ORIENT_VERTICAL);
    assert.equal(normaliseOrientation(undefined), ORIENT_VERTICAL);
    assert.equal(normaliseOrientation('bogus'), ORIENT_VERTICAL);
});
