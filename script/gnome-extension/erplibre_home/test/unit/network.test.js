import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {parseNmapOG, deriveCidrFromIpRoute, expandCidrV4Slash24}
    from '../../lib/network.js';

const nmapFx = readFileSync(
    new URL('../fixtures/nmap-oG.txt', import.meta.url), 'utf8');
const routeFx = readFileSync(
    new URL('../fixtures/ip-route.json', import.meta.url), 'utf8');

test('parseNmapOG extracts hosts with port 22 open', () => {
    const hosts = parseNmapOG(nmapFx);
    assert.deepEqual(hosts.map(h => h.ip).sort(),
        ['192.168.1.10', '192.168.1.42']);
});

test('parseNmapOG empty input', () => {
    assert.deepEqual(parseNmapOG(''), []);
});

test('deriveCidrFromIpRoute returns /24 of default-gateway iface', () => {
    assert.equal(deriveCidrFromIpRoute(routeFx), '192.168.1.0/24');
});

test('deriveCidrFromIpRoute returns null when no default route', () => {
    const noDefault = JSON.stringify(
        [{dst: '10.0.0.0/8', dev: 'eth0', prefsrc: '10.0.0.5'}]);
    assert.equal(deriveCidrFromIpRoute(noDefault), null);
});

test('expandCidrV4Slash24 returns 256 addresses', () => {
    const ips = expandCidrV4Slash24('192.168.1.0/24');
    assert.equal(ips.length, 256);
    assert.equal(ips[0], '192.168.1.0');
    assert.equal(ips[255], '192.168.1.255');
});

test('expandCidrV4Slash24 rejects non-/24', () => {
    assert.throws(() => expandCidrV4Slash24('10.0.0.0/16'), /only \/24/);
});
