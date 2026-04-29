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

const STYLE_BASE =
    'border-radius: 7px;' +
    'padding: 0 4px;' +
    'min-width: 10px;' +
    'font-size: 9px;' +
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
export function makeBadgedIcon({St, Gio, Clutter, iconName}) {
    // Horizontal row: icon on the left, vertical badge stack on the
    // right. Keeps the icon graphic untouched and lets up to three
    // badges sit beside it (centered when there is only one).
    const root = new St.BoxLayout({
        style_class: 'system-status-icon',
        vertical: false,
        x_expand: false,
        y_expand: false,
        style: 'spacing: 2px;',
    });

    let icon = _buildIcon(St, Gio, iconName);
    root.add_child(icon);

    const badgeBox = new St.BoxLayout({
        vertical: true,
        x_align: Clutter.ActorAlign.START,
        y_align: Clutter.ActorAlign.CENTER,
        x_expand: false,
        y_expand: false,
        style: 'spacing: 1px; padding: 0;',
    });
    root.add_child(badgeBox);

    function setIcon(name) {
        if (!name) return;
        const next = _buildIcon(St, Gio, name);
        root.replace_child(icon, next);
        icon = next;
    }

    function setBadges(badges) {
        badgeBox.destroy_all_children();
        const visible = [];
        for (const b of badges || []) {
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

    return {actor: root, setBadges, setIcon};
}
