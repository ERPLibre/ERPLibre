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

// Only an Include before the first Host is covered: one inside a Host
// block is kept by the parser as a field of that Host.
test('parseSshConfig ignores an Include before the first Host', () => {
    const hosts = parseSshConfig([
        'Include ~/.ssh/config.d/*',
        'include extra.conf',
        'Host gw',
        '    HostName 10.4.4.1',
        'Host db',
        '    User ops',
    ].join('\n'));
    assert.deepEqual(hosts.map(h => h.alias), ['gw', 'db']);
    assert.deepEqual(hosts[0].fields, {HostName: '10.4.4.1'});
    assert.deepEqual(hosts[1].fields, {User: 'ops'});
});
