import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdirSync, readFileSync, writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {fake, makeSettings, settle} from './gjs-fake.js';
import {parseNmapOG, deriveCidrFromIpRoute, expandCidrV4Slash24,
    scanNmapGjs, scanNcGjs} from '../../lib/network.js';

// After gjs-fake.js: the indicator imports gi:// modules statically.
const {indicatorDescriptor} = await import('../../indicators/network.js');

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

test('scanNmapGjs runs nmap -p22 --open -oG - on the range', async () => {
    fake.reset();
    fake.onSpawn = () => ({stdout: nmapFx});
    const {hosts, error} = await scanNmapGjs('192.168.1.0/24', null);
    assert.deepEqual(fake.spawned.map(s => s.argv),
        [['nmap', '-p22', '--open', '-oG', '-', '192.168.1.0/24']]);
    assert.equal(error, null);
    assert.deepEqual(hosts.map(h => h.ip).sort(),
        ['192.168.1.10', '192.168.1.42']);
});

test('scanNcGjs probes port 22 of each /24 address with nc', async () => {
    fake.reset();
    fake.onSpawn = argv => ({exit: argv[3] === '10.4.4.7' ? 0 : 1});
    const {hosts} = await scanNcGjs('10.4.4.0/24', null);
    assert.equal(fake.spawned.length, 256);
    assert.deepEqual(fake.spawned[0].argv,
        ['nc', '-z', '-w1', '10.4.4.0', '22']);
    assert.deepEqual(fake.spawned[255].argv,
        ['nc', '-z', '-w1', '10.4.4.255', '22']);
    assert.deepEqual(hosts, [{ip: '10.4.4.7', port22: true}]);
});

function networkIndicator(overrides = {}) {
    const settings = makeSettings({'network-cidrs': ['10.4.4.0/24'],
        ...overrides});
    return indicatorDescriptor.ctor({
        extension: {getSettings: () => settings}, openPrefs() {}});
}

function scanners() {
    return fake.spawned.map(s => s.argv[0])
        .filter(p => p === 'nmap' || p === 'nc')
        .filter((p, i, all) => all.indexOf(p) === i);
}

test('the scan uses nmap when enabled and on PATH, else nc', async () => {
    const cases = [
        [true, ['nmap'], ['nmap']],
        [true, [], ['nc']],
        [false, ['nmap'], ['nc']],
    ];
    for (const [useNmap, programs, expected] of cases) {
        fake.reset();
        fake.programs = programs;
        const ind = networkIndicator({'network-use-nmap': useNmap});
        await ind._startScan();
        assert.deepEqual(scanners(), expected, `${useNmap} ${programs}`);
    }
});

/** The item labelled `label` in `menu`, searched through sub-menus. */
function item(menu, label) {
    for (const it of menu.items) {
        if (it.text === label) return it;
        const found = it.menu ? item(it.menu, label) : null;
        if (found) return found;
    }
    return null;
}

function sshCommands() {
    return fake.spawned.filter(s => s.argv[0] === 'gnome-terminal')
        .map(s => s.argv);
}

const terminal = command => ['gnome-terminal',
    `--working-directory=${fake.env.HOME}`, '--', 'bash', '-lc',
    `${command}; exec bash`];

test('SSH terminal on a configured host runs ssh <alias>', async () => {
    fake.reset();
    fake.programs = ['gnome-terminal'];
    mkdirSync(join(fake.env.HOME, '.ssh'));
    writeFileSync(join(fake.env.HOME, '.ssh', 'config'),
        'Host gw\n    HostName 10.4.4.1\n    User admin\n');
    const ind = networkIndicator();
    item(item(ind.menu, 'gw').menu, 'SSH terminal').activate();
    await settle();
    assert.deepEqual(sshCommands(), [terminal('ssh gw')]);
});

async function scannedIndicator(overrides) {
    fake.reset();
    fake.programs = ['gnome-terminal', 'nmap'];
    fake.onSpawn = argv => (argv[0] === 'nmap'
        ? {stdout: 'Host: 10.4.4.9 ()\tPorts: 22/open/tcp//ssh///\n'}
        : {});
    const ind = networkIndicator(overrides);
    await ind._startScan();
    item(item(ind.menu, '10.4.4.9 (10.4.4.9)').menu, 'SSH terminal')
        .activate();
    await settle();
    return sshCommands();
}

test('SSH terminal on a scanned host runs ssh <user>@<ip>', async () => {
    assert.deepEqual(await scannedIndicator({'network-ssh-user': 'ops'}),
        [terminal('ssh ops@10.4.4.9')]);
});

test('without network-ssh-user the scanned host gets $USER', async () => {
    assert.deepEqual(await scannedIndicator({'network-ssh-user': ''}),
        [terminal('ssh deckuser@10.4.4.9')]);
});
