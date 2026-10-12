import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {parseSshConfig, isWildcardHost} from '../../lib/ssh-config.js';

const text = readFileSync(
    new URL('../fixtures/ssh-config.txt', import.meta.url), 'utf8');

test('parseSshConfig collects Host stanzas', () => {
    const hosts = parseSshConfig(text);
    assert.equal(hosts.length, 4);
    const gw = hosts.find(h => h.alias === 'gateway');
    assert.equal(gw.fields.HostName, '192.168.1.1');
    assert.equal(gw.fields.User, 'admin');
});

test('parseSshConfig keeps wildcards but flag isWildcardHost', () => {
    const hosts = parseSshConfig(text);
    assert.equal(isWildcardHost('dev-*'), true);
    assert.equal(isWildcardHost('*'), true);
    assert.equal(isWildcardHost('gateway'), false);
    const wildcards = hosts.filter(h => isWildcardHost(h.alias));
    assert.equal(wildcards.length, 2);
});

test('parseSshConfig empty', () => {
    assert.deepEqual(parseSshConfig(''), []);
});
