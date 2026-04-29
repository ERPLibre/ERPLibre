/**
 * Schema migration runner.
 *
 * Each entry in MIGRATIONS upgrades the user's stored data from
 * `from` to `from + 1`. The runner reads `schema-version` from the
 * Gio.Settings, applies any matching upgrade in order, and writes
 * the new version back. A failing migration leaves the version
 * untouched so the next launch retries.
 *
 * Pure logic is exported so node tests can drive each migration
 * with a mock settings object.
 */

export const CURRENT_VERSION = 2;

/**
 * v1 → v2: rename `film` indicator data to `media`.
 *
 * - Copies the `films` GSetting (JSON array) into `media`,
 *   tagging every existing entry with `kind: 'video'` so the new
 *   sectioned dropdown still surfaces them under the Videos header.
 * - Mirrors the toggle: `enable-film` → `enable-media`.
 * - Leaves the legacy keys in place. Removing a key from the schema
 *   would lose the user's data on a downgrade; keeping it costs
 *   only the storage of the original strings.
 */
export function migrateFilmToMedia(settings) {
    const filmsRaw = settings.get_string('films');
    let mediaRaw = settings.get_string('media');
    // Don't clobber a hand-edited new-key value.
    if (mediaRaw && mediaRaw !== '[]') return;

    let films;
    try { films = JSON.parse(filmsRaw || '[]'); }
    catch (_e) { films = []; }
    if (!Array.isArray(films)) films = [];

    const tagged = films.map(e => ({
        kind: 'video',
        ...e,
        // If the entry already has a kind keep it; otherwise kind:
        // 'video' from the spread above wins.
    }));
    settings.set_string('media', JSON.stringify(tagged));

    // Mirror the toggle: only override the new key when the user has
    // explicitly disabled the old one (the new default is true).
    if (!settings.get_boolean('enable-film')) {
        settings.set_boolean('enable-media', false);
    }
}

const MIGRATIONS = [
    {from: 1, fn: migrateFilmToMedia},
];

/**
 * Apply pending migrations. Synchronous so callers (notably
 * `enable()` in extension.js) can rely on the data being upgraded
 * before the indicator descriptors look up their per-id GSettings.
 */
export function runSchemaMigrations(settings, log = (_m) => {}) {
    let v = settings.get_int('schema-version');
    while (v < CURRENT_VERSION) {
        const m = MIGRATIONS.find(x => x.from === v);
        if (!m) {
            log(`no migration for version ${v} → ${v + 1}; stop`);
            return v;
        }
        try {
            m.fn(settings);
        } catch (e) {
            log(`migration ${v} → ${v + 1} failed: ${e.message || e}`);
            return v;
        }
        v += 1;
        settings.set_int('schema-version', v);
        log(`migrated to version ${v}`);
    }
    return v;
}
