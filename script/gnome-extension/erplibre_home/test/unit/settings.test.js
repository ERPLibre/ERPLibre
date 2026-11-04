import {test} from 'node:test';
import assert from 'node:assert/strict';
import {existsSync, mkdirSync, readFileSync, writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {fake, makeSettings, schemaDefaults} from './gjs-fake.js';
import {parseList, serializeList, pushRecent, MAX_RECENT}
    from '../../lib/settings.js';
import {migrateLegacyJson, parseObject, runMigrationGjs,
    exportSettingsAsObj} from '../../lib/settings.js';

test('parseList returns [] on bad JSON', () => {
    assert.deepEqual(parseList('not json'), []);
    assert.deepEqual(parseList(''), []);
    assert.deepEqual(parseList('null'), []);
});

test('parseList returns array on valid JSON array', () => {
    assert.deepEqual(parseList('[{"a":1}]'), [{a: 1}]);
});

test('parseList returns [] when JSON is not an array', () => {
    assert.deepEqual(parseList('{"x":1}'), []);
    assert.deepEqual(parseList('"string"'), []);
});

test('serializeList round-trips', () => {
    const data = [{a: 1}, {b: 'two'}];
    assert.deepEqual(parseList(serializeList(data)), data);
});

test('pushRecent prepends + dedupes + caps', () => {
    let r = [];
    for (let i = 0; i < MAX_RECENT + 3; i++) r = pushRecent(r, `/p${i}`);
    assert.equal(r.length, MAX_RECENT);
    assert.equal(r[0], `/p${MAX_RECENT + 2}`);
});

test('pushRecent moves duplicate to front', () => {
    const r = pushRecent(['/a', '/b', '/c'], '/b');
    assert.deepEqual(r, ['/b', '/a', '/c']);
});

test('migrateLegacyJson seeds paths from erplibre_path', () => {
    const legacy = {erplibre_path: '/home/user/erplibre'};
    const out = migrateLegacyJson(legacy, []);
    assert.equal(out.length, 1);
    assert.equal(out[0].path, '/home/user/erplibre');
    assert.equal(out[0].label, 'ERPLibre');
    assert.match(out[0].id, /^[0-9a-f]{8}-/);
});

test('migrateLegacyJson is no-op when paths already populated', () => {
    const existing = [{id: 'x', label: 'L', path: '/p'}];
    const out = migrateLegacyJson({erplibre_path: '/other'}, existing);
    assert.deepEqual(out, existing);
});

test('migrateLegacyJson handles missing erplibre_path', () => {
    assert.deepEqual(migrateLegacyJson({}, []), []);
});

test('migrateLegacyJson tolerates corrupted legacy', () => {
    assert.deepEqual(migrateLegacyJson(null, []), []);
    assert.deepEqual(migrateLegacyJson('garbage', []), []);
});

test('recent-paths keeps the 10 most recent paths', () => {
    assert.equal(MAX_RECENT, 10);
    let r = [];
    for (let i = 1; i <= 11; i++) r = pushRecent(r, `/p${i}`);
    assert.equal(r.length, 10);
    assert.equal(r[0], '/p11');
    assert.equal(r[9], '/p2');
});

test('parseObject reads a JSON object and nothing else', () => {
    assert.deepEqual(parseObject('{"pencil": "x-symbolic"}'),
        {pencil: 'x-symbolic'});
    for (const bad of ['', 'not json', 'null', '[]', '["a"]', '"s"', '3'])
        assert.deepEqual(parseObject(bad), {}, bad);
    assert.deepEqual(parseObject(undefined), {});
});

test('the default top-bar order', () => {
    assert.deepEqual(schemaDefaults().get('button-order').value,
        ['summary', 'device', 'network', 'erplibre', 'media', 'pencil',
            'controller']);
});

test('the six indicators are enabled by default', () => {
    const keys = schemaDefaults();
    for (const id of ['controller', 'pencil', 'media', 'erplibre',
        'network', 'device']) {
        assert.equal(keys.get(`enable-${id}`).type, 'b', id);
        assert.equal(keys.get(`enable-${id}`).value, true, id);
    }
});

test('the catalogue, indicator, sync and migration defaults', () => {
    const keys = schemaDefaults();
    const expected = {
        'paths': ['s', '[]'],
        'instances': ['s', '[]'],
        'recent-paths': ['s', '[]'],
        'terminal-claude-cmd': ['s', 'claude --resume'],
        'erplibre-auto-detect': ['b', true],
        'erplibre-local-pattern': ['s', '~/erplibre*'],
        'network-cidrs': ['as', []],
        'network-ssh-user': ['s', ''],
        'network-use-nmap': ['b', true],
        'network-read-ssh-config': ['b', true],
        'network-auto-refresh-sec': ['i', 0],
        'device-auto-refresh-sec': ['i', 0],
        'icon-overrides': ['s', '{}'],
        'enable-git-sync': ['b', false],
        'git-sync-path': ['s', ''],
        'schema-version': ['i', 1],
        'migration-done': ['b', false],
    };
    for (const [name, [type, value]] of Object.entries(expected))
        assert.deepEqual(keys.get(name), {type, value}, name);
});

function legacyFile() {
    const dir = join(fake.env.XDG_CONFIG_HOME, 'erplibre-home');
    mkdirSync(dir, {recursive: true});
    return join(dir, 'extension-settings.json');
}

test('the legacy file is migrated once, then kept as .bak', async () => {
    fake.reset();
    const settings = makeSettings();
    const legacy = legacyFile();
    writeFileSync(legacy, '{"erplibre_path": "/srv/erp"}');
    await runMigrationGjs(settings, () => {});
    assert.deepEqual(parseList(settings.get_string('paths'))
        .map(p => [p.label, p.path]), [['ERPLibre', '/srv/erp']]);
    assert.equal(settings.get_boolean('migration-done'), true);
    assert.equal(existsSync(legacy), false);
    assert.equal(readFileSync(`${legacy}.bak`, 'utf8'),
        '{"erplibre_path": "/srv/erp"}');

    // A second run reads nothing: a new legacy file stays where it is.
    settings.set_string('paths', '[]');
    writeFileSync(legacy, '{"erplibre_path": "/srv/other"}');
    await runMigrationGjs(settings, () => {});
    assert.equal(settings.get_string('paths'), '[]');
    assert.equal(existsSync(legacy), true);
});

test('a corrupted legacy file is logged and leaves the defaults', async () => {
    fake.reset();
    const settings = makeSettings();
    writeFileSync(legacyFile(), '{"erplibre_path": ');
    const logged = [];
    await runMigrationGjs(settings, line => logged.push(line));
    assert.equal(logged.length, 1);
    assert.match(logged[0], /^\[ERPLibreHome\] migration: bad legacy JSON/);
    assert.equal(settings.get_string('paths'), '[]');
});

test('the export is {schema_version, settings: {key: value}}', () => {
    const settings = makeSettings({'schema-version': 2,
        'paths': '[{"path": "/a"}]', 'network-cidrs': ['10.0.0.0/24'],
        'enable-pencil': false});
    const out = exportSettingsAsObj(settings);
    assert.deepEqual(Object.keys(out).sort(), ['schema_version', 'settings']);
    assert.equal(out.schema_version, 2);
    assert.equal(out.settings['paths'], '[{"path": "/a"}]');
    assert.deepEqual(out.settings['network-cidrs'], ['10.0.0.0/24']);
    assert.equal(out.settings['enable-pencil'], false);
    assert.equal(out.settings['schema-version'], 2);
    assert.deepEqual(JSON.parse(JSON.stringify(out)), out);
});
