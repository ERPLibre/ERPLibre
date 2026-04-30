/**
 * Top-bar icon with overlaid count badges. Pure formatting helpers are
 * unit-tested under Node. The widget builder is synchronous and takes
 * already-loaded gi modules so the file itself stays Node-importable.
 */

export const BADGE_DEFAULT = 'default';
export const BADGE_OK = 'ok';
export const BADGE_INFO = 'info';
export const BADGE_WARN = 'warn';
export const BADGE_ALERT = 'alert';

// Cap on vertical badge stack so the top-bar height stays bounded even
// when an indicator wants to surface more counts than fit beside its
// icon.
export const BADGE_VERTICAL_MAX = 3;

export const ORIENT_VERTICAL = 'vertical';
export const ORIENT_HORIZONTAL = 'horizontal';

export function normaliseOrientation(value) {
    return value === ORIENT_HORIZONTAL ? ORIENT_HORIZONTAL : ORIENT_VERTICAL;
}

// Tight base style so up-to-three vertically stacked badges still fit
// inside a stock GNOME top bar (~32 px). Keep bold weight + white text
// so the small font stays legible against the saturated colors.
const STYLE_BASE =
    'border-radius: 5px;' +
    'padding: 0 3px;' +
    'min-width: 8px;' +
    'font-size: 8px;' +
    'font-weight: bold;' +
    'color: white;' +
    'text-align: center;';

const STYLE_BY_KIND = {
    [BADGE_DEFAULT]: `${STYLE_BASE}background-color: #3477b8;`,
    [BADGE_OK]:      `${STYLE_BASE}background-color: #2e7d32;`,
    [BADGE_INFO]:    `${STYLE_BASE}background-color: #00838f;`,
    [BADGE_WARN]:    `${STYLE_BASE}background-color: #d4a017;`,
    [BADGE_ALERT]:   `${STYLE_BASE}background-color: #c62828;`,
};

/**
 * Stable display string for a count: '' when n===0, '99+' when over the cap.
 */
export function formatBadgeCount(n, cap = 99) {
    const x = Number.isFinite(n) ? Math.max(0, Math.floor(n)) : 0;
    if (x === 0) return '';
    if (x > cap) return `${cap}+`;
    return String(x);
}

/**
 * Resolve the highest-severity kind from the list of badges
 * (alert > warn > ok > default).
 */
export function pickHighestKind(badges) {
    let best = BADGE_DEFAULT;
    for (const b of badges || []) {
        if (b?.kind === BADGE_ALERT) return BADGE_ALERT;
        if (b?.kind === BADGE_WARN) best = BADGE_WARN;
        else if (b?.kind === BADGE_OK && best === BADGE_DEFAULT)
            best = BADGE_OK;
    }
    return best;
}

export function badgeStyleFor(kind) {
    return STYLE_BY_KIND[kind] || STYLE_BY_KIND[BADGE_DEFAULT];
}

function _buildIcon(St, Gio, iconName) {
    if (typeof iconName === 'string' && iconName.startsWith('/')) {
        return new St.Icon({
            gicon: Gio.icon_new_for_string(iconName),
            style_class: 'system-status-icon',
        });
    }
    return new St.Icon({
        icon_name: iconName,
        style_class: 'system-status-icon',
    });
}

/**
 * Build an icon actor with an overlay row of badge labels in the
 * top-right corner. Returns {actor, setBadges, setIcon}.
 *
 * Each badge: {count: number, kind?: 'default'|'warn'|'alert',
 *              text?: string}. `text` overrides the formatted count.
 *
 * GJS-only — pass already-loaded gi module defaults via `gi`.
 */
export function makeBadgedIcon({St, Gio, Clutter, iconName,
    orientation = ORIENT_VERTICAL}) {
    // Horizontal row: icon on the left, badge stack (vertical or
    // horizontal) on the right. Keeps the icon graphic untouched.
    const root = new St.BoxLayout({
        style_class: 'system-status-icon',
        vertical: false,
        x_expand: false,
        y_expand: false,
        style: 'spacing: 2px;',
    });

    let icon = _buildIcon(St, Gio, iconName);
    root.add_child(icon);

    let currentOrientation = normaliseOrientation(orientation);
    const badgeBox = new St.BoxLayout({
        vertical: currentOrientation === ORIENT_VERTICAL,
        x_align: Clutter.ActorAlign.CENTER,
        y_align: Clutter.ActorAlign.CENTER,
        x_expand: false,
        y_expand: false,
        style: 'spacing: 1px; padding: 0;',
    });
    root.add_child(badgeBox);

    let lastBadges = [];

    function setIcon(name) {
        if (!name) return;
        const next = _buildIcon(St, Gio, name);
        root.replace_child(icon, next);
        icon = next;
    }

    function _render() {
        badgeBox.destroy_all_children();
        const visible = [];
        for (const b of lastBadges) {
            if (!b) continue;
            const text = b.text ?? formatBadgeCount(b.count);
            if (text === '') continue;
            visible.push({text, kind: b.kind || BADGE_DEFAULT});
            if (visible.length >= BADGE_VERTICAL_MAX) break;
        }
        for (const v of visible) {
            const label = new St.Label({
                text: v.text,
                x_align: Clutter.ActorAlign.CENTER,
                y_align: Clutter.ActorAlign.CENTER,
                style: badgeStyleFor(v.kind),
            });
            badgeBox.add_child(label);
        }
    }

    function setBadges(badges) {
        lastBadges = Array.isArray(badges) ? badges.slice() : [];
        _render();
    }

    function setOrientation(value) {
        const next = normaliseOrientation(value);
        if (next === currentOrientation) return;
        currentOrientation = next;
        badgeBox.vertical = next === ORIENT_VERTICAL;
        _render();
    }

    return {actor: root, setBadges, setIcon, setOrientation};
}

/**
 * Wire a Gio.Settings 'badge-orientation' key to the badged icon.
 * Applies the current value immediately and returns the signal id so
 * the caller can disconnect on destroy.
 */
export function bindBadgeOrientation(badged, settings) {
    if (!badged?.setOrientation || !settings) return 0;
    const apply = () =>
        badged.setOrientation(settings.get_string('badge-orientation'));
    apply();
    return settings.connect('changed::badge-orientation', apply);
}
