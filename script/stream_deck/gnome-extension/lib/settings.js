/**
 * Settings module. Pure JSON helpers + Gio.Settings wrapper.
 *
 * Pure helpers are tested via node --test. The Gio.Settings wrapper
 * is only usable from GJS at extension runtime.
 */

export const MAX_RECENT = 10;

export function parseList(serialized) {
    if (typeof serialized !== 'string' || serialized === '') return [];
    try {
        const parsed = JSON.parse(serialized);
        return Array.isArray(parsed) ? parsed : [];
    } catch (_e) {
        return [];
    }
}

export function serializeList(arr) {
    return JSON.stringify(Array.isArray(arr) ? arr : []);
}

export function parseObject(serialized) {
    if (typeof serialized !== 'string' || serialized === '') return {};
    try {
        const parsed = JSON.parse(serialized);
        return (parsed && typeof parsed === 'object' && !Array.isArray(parsed))
            ? parsed
            : {};
    } catch (_e) {
        return {};
    }
}

export function serializeObject(obj) {
    return JSON.stringify(obj && typeof obj === 'object' ? obj : {});
}

export function pushRecent(arr, value) {
    const list = Array.isArray(arr) ? arr.slice() : [];
    const filtered = list.filter(v => v !== value);
    filtered.unshift(value);
    return filtered.slice(0, MAX_RECENT);
}

/**
 * Generate a UUID v4 (RFC 4122). Used for stable IDs on catalogue entries.
 * Pure JS so it works in both Node tests and GJS runtime.
 */
export function uuid4() {
    const bytes = new Uint8Array(16);
    if (typeof globalThis.crypto?.getRandomValues === 'function') {
        globalThis.crypto.getRandomValues(bytes);
    } else {
        for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256);
    }
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const h = [...bytes].map(b => b.toString(16).padStart(2, '0'));
    return `${h.slice(0, 4).join('')}-${h.slice(4, 6).join('')}-${h.slice(6, 8).join('')}-${h.slice(8, 10).join('')}-${h.slice(10).join('')}`;
}

/**
 * GJS-only thin wrapper around Gio.Settings. Lazily loaded so Node tests
 * importing this file don't blow up.
 */
let _gioSettings = null;
export function getSettings(extensionInstance) {
    if (_gioSettings) return _gioSettings;
    _gioSettings = extensionInstance.getSettings();
    return _gioSettings;
}

export function resetCachedSettings() {
    _gioSettings = null;
}

/**
 * Pure-logic migration: given the parsed legacy JSON object and the
 * existing paths array, return the new paths array. No file I/O.
 */
export function migrateLegacyJson(legacy, existingPaths) {
    if (Array.isArray(existingPaths) && existingPaths.length > 0) {
        return existingPaths;
    }
    if (!legacy || typeof legacy !== 'object') return existingPaths || [];
    const erpPath = legacy.erplibre_path;
    if (typeof erpPath !== 'string' || !erpPath.trim()) {
        return existingPaths || [];
    }
    return [{
        id: uuid4(),
        label: 'ERPLibre',
        path: erpPath,
        default_cmd: 'claude --resume',
    }];
}

/**
 * Default legacy JSON path. GJS-only — wrapped in a function so Node
 * tests don't import GLib.
 */
export async function legacyJsonPath() {
    const {default: GLib} = await import('gi://GLib');
    return GLib.build_filenamev([
        GLib.get_user_config_dir(),
        'streamdeck-tiler',
        'extension-settings.json',
    ]);
}

/**
 * Run the migration at extension enable time. Callable only from GJS.
 *
 *   1. If migration-done is true, no-op.
 *   2. Read legacy JSON; on parse failure, log + mark done + exit.
 *   3. Merge into paths; bump schema-version + migration-done.
 *   4. Rename the legacy file to <name>.bak.
 */
export async function runMigrationGjs(settings, log = console.log) {
    if (settings.get_boolean('migration-done')) return;
    const {default: GLib} = await import('gi://GLib');
    const path = await legacyJsonPath();
    let legacy = {};
    if (GLib.file_test(path, GLib.FileTest.EXISTS)) {
        try {
            const [ok, contents] = GLib.file_get_contents(path);
            if (ok) legacy = JSON.parse(new TextDecoder().decode(contents));
        } catch (e) {
            log(`[StreamDeckTiler] migration: bad legacy JSON: ${e.message}`);
            legacy = {};
        }
    }
    const existing = parseList(settings.get_string('paths'));
    const merged = migrateLegacyJson(legacy, existing);
    if (merged !== existing) {
        settings.set_string('paths', serializeList(merged));
    }
    settings.set_int('schema-version', 1);
    settings.set_boolean('migration-done', true);
    if (GLib.file_test(path, GLib.FileTest.EXISTS)) {
        try {
            GLib.rename(path, `${path}.bak`);
        } catch (_e) {}
    }
}

export const SCHEMA_KEYS = [
    'enable-controller','enable-pencil','enable-film',
    'enable-erplibre','enable-network','enable-device',
    'button-order','paths','films','instances','recent-paths',
    'terminal-claude-cmd','erplibre-auto-detect','erplibre-local-pattern',
    'network-cidrs','network-ssh-user','network-use-nmap',
    'network-read-ssh-config','network-auto-refresh-sec',
    'device-auto-refresh-sec','icon-overrides','enable-git-sync',
    'git-sync-path','schema-version',
    'enable-icon-badges','enable-claude-state-watch',
    'enable-claude-desktop-notify',
    'panel-box',
];

export function exportSettingsAsObj(settings) {
    const out = {};
    for (const k of SCHEMA_KEYS) {
        const v = settings.get_value(k);
        out[k] = v.deep_unpack ? v.deep_unpack() : v.unpack();
    }
    return {schema_version: settings.get_int('schema-version'),
        settings: out};
}

export async function importSettingsFromObj(settings, obj) {
    if (!obj || typeof obj !== 'object' || !obj.settings) return false;
    const {default: GLib} = await import('gi://GLib');
    for (const [k, raw] of Object.entries(obj.settings)) {
        if (!SCHEMA_KEYS.includes(k)) continue;
        try {
            const cur = settings.get_value(k);
            const variantType = cur.get_type_string();
            const variant = GLib.Variant.new(variantType, raw);
            settings.set_value(k, variant);
        } catch (_e) { /* skip mismatched */ }
    }
    return true;
}

export function resetAllSettings(settings) {
    for (const k of SCHEMA_KEYS) settings.reset(k);
}
