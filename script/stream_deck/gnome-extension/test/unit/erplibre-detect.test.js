import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {parseEnvVarSh, deriveInstanceFromDir, expandHome}
    from '../../lib/erplibre-detect.js';

const sample = readFileSync(
    new URL('../fixtures/env_var.sh.sample', import.meta.url), 'utf8');

test('parseEnvVarSh extracts ERPLIBRE_PORT_HTTP', () => {
    const env = parseEnvVarSh(sample);
    assert.equal(env.ERPLIBRE_PORT_HTTP, '8071');
    assert.equal(env.ERPLIBRE_PORT_LONGPOLLING, '8072');
    assert.equal(env.EL_LANG, 'fr');
});

test('parseEnvVarSh tolerates missing file content', () => {
    assert.deepEqual(parseEnvVarSh(''), {});
});

test('deriveInstanceFromDir builds canonical entry', () => {
    const inst = deriveInstanceFromDir('/home/x/erplibre01', sample);
    assert.equal(inst.type, 'local');
    assert.equal(inst.local_path, '/home/x/erplibre01');
    assert.equal(inst.port, 8071);
    assert.equal(inst.url, 'http://localhost:8071');
    assert.equal(inst.name, 'erplibre01');
});

test('deriveInstanceFromDir falls back to 8069 when no port', () => {
    const inst = deriveInstanceFromDir('/home/x/erplibre', '');
    assert.equal(inst.port, 8069);
    assert.equal(inst.url, 'http://localhost:8069');
});

test('expandHome resolves ~', () => {
    assert.equal(expandHome('~/foo', '/home/x'), '/home/x/foo');
    assert.equal(expandHome('/abs', '/home/x'), '/abs');
});
