import {test} from 'node:test';
import assert from 'node:assert/strict';
import {verticalBoxProps, setBoxVertical, windowMaximizeFlags,
    unmaximizeWindow, maximizeWindow, defaultSeat}
    from '../../lib/shell-compat.js';

const Clutter = {Orientation: {HORIZONTAL: 0, VERTICAL: 1}};
const Meta = {MaximizeFlags: {HORIZONTAL: 1, VERTICAL: 2, BOTH: 3}};

// St 48+ exposes `orientation` on the BoxLayout prototype; St 45-47 does not.
const St51 = {BoxLayout: {prototype: {orientation: 0}}};
const St45 = {BoxLayout: {prototype: {vertical: false}}};

function recorder(methods) {
    const calls = [];
    const win = {};
    for (const [name, ret] of Object.entries(methods))
        win[name] = (...args) => { calls.push([name, ...args]); return ret; };
    return {win, calls};
}

test('verticalBoxProps uses orientation when St has it', () => {
    assert.deepEqual(verticalBoxProps(St51, Clutter), {orientation: 1});
});

test('verticalBoxProps falls back to vertical on older St', () => {
    assert.deepEqual(verticalBoxProps(St45, Clutter), {vertical: true});
});

test('setBoxVertical drives orientation on St 48+', () => {
    const box = {};
    setBoxVertical(St51, Clutter, box, false);
    assert.deepEqual(box, {orientation: 0});
    setBoxVertical(St51, Clutter, box, true);
    assert.deepEqual(box, {orientation: 1});
});

test('setBoxVertical drives vertical on older St', () => {
    const box = {};
    setBoxVertical(St45, Clutter, box, true);
    assert.deepEqual(box, {vertical: true});
});

test('windowMaximizeFlags prefers get_maximize_flags', () => {
    const {win} = recorder({get_maximize_flags: 2, get_maximized: 3});
    assert.equal(windowMaximizeFlags(win), 2);
});

test('windowMaximizeFlags falls back to get_maximized', () => {
    const {win} = recorder({get_maximized: 3});
    assert.equal(windowMaximizeFlags(win), 3);
});

test('unmaximizeWindow passes no flags on the new API', () => {
    const {win, calls} = recorder({get_maximize_flags: 3, unmaximize: null});
    unmaximizeWindow(win, Meta);
    assert.deepEqual(calls, [['unmaximize']]);
});

test('unmaximizeWindow passes BOTH on the old API', () => {
    const {win, calls} = recorder({get_maximized: 3, unmaximize: null});
    unmaximizeWindow(win, Meta);
    assert.deepEqual(calls, [['unmaximize', 3]]);
});

test('maximizeWindow does nothing for 0', () => {
    const {win, calls} = recorder({get_maximize_flags: 0, maximize: null});
    maximizeWindow(win, Meta, 0);
    assert.deepEqual(calls, []);
});

test('maximizeWindow maps BOTH to maximize() on the new API', () => {
    const {win, calls} = recorder({get_maximize_flags: 0, maximize: null,
        set_maximize_flags: null});
    maximizeWindow(win, Meta, 3);
    assert.deepEqual(calls, [['maximize']]);
});

test('maximizeWindow keeps one direction on the new API', () => {
    const {win, calls} = recorder({get_maximize_flags: 0, maximize: null,
        set_maximize_flags: null});
    maximizeWindow(win, Meta, 2);
    assert.deepEqual(calls, [['set_maximize_flags', 2]]);
});

test('maximizeWindow passes the flags on the old API', () => {
    const {win, calls} = recorder({get_maximized: 0, maximize: null});
    maximizeWindow(win, Meta, 1);
    assert.deepEqual(calls, [['maximize', 1]]);
});

test('defaultSeat goes through the stage context when present', () => {
    const seat = {};
    const stage = {get_context: () => ({get_backend: () => ({
        get_default_seat: () => seat})})};
    const OldClutter = {get_default_backend: () => {
        throw new Error('must not be called');
    }};
    assert.equal(defaultSeat(OldClutter, stage), seat);
});

test('defaultSeat falls back to Clutter.get_default_backend', () => {
    const seat = {};
    const OldClutter = {get_default_backend: () => ({
        get_default_seat: () => seat})};
    assert.equal(defaultSeat(OldClutter, {}), seat);
});
