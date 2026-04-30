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
// icon. Two slots leaves enough vertical room for a readable font.
export const BADGE_VERTICAL_MAX = 2;

export const ORIENT_VERTICAL = 'vertical';
export const ORIENT_HORIZONTAL = 'horizontal';

export function normaliseOrientation(value) {
    return value === ORIENT_HORIZONTAL ? ORIENT_HORIZONTAL : ORIENT_VERTICAL;
}

// Two-slot vertical stack lets the font grow back to readable size
// while still fitting inside a stock GNOME top bar (~32 px).
const STYLE_BASE =
    'border-radius: 6px;' +
    'padding: 0 5px;' +
    'min-width: 12px;' +
    'font-size: 11px;' +
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
            visible.push({
                text,
                kind: b.kind || BADGE_DEFAULT,
                onClick: typeof b.onClick === 'function' ? b.onClick : null,
            });
            if (visible.length >= BADGE_VERTICAL_MAX) break;
        }
        for (const v of visible) {
            const label = new St.Label({
                text: v.text,
                x_align: Clutter.ActorAlign.CENTER,
                y_align: Clutter.ActorAlign.CENTER,
                style: badgeStyleFor(v.kind),
            });
            if (v.onClick) {
                // Reactive label catches the press first (Clutter delivers
                // events leaf → root) so the indicator can refresh its
                // dropdown filter before the parent button toggles the
                // menu open. Propagate the event so the menu still opens.
                label.reactive = true;
                label.track_hover = true;
                label.connect('button-press-event', () => {
                    try { v.onClick(); } catch (_e) {}
                    return Clutter.EVENT_PROPAGATE;
                });
            }
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

/**
 * Format the per-indicator hover tooltip from a list of badges, where
 * each entry carries a numeric count and an optional human label.
 * Pure helper, unit-tested.
 *
 * Example: formatBadgeTooltip([
 *     {count: 3, label: 'paths'},
 *     {count: 2, label: 'active'},
 *     {count: 1, label: 'awaiting'},
 * ]) => '3 paths · 2 active · 1 awaiting'.
 */
export function formatBadgeTooltip(parts) {
    const out = [];
    for (const p of parts || []) {
        if (!p) continue;
        const n = Number.isFinite(p.count) ? Math.max(0, Math.floor(p.count))
            : 0;
        if (n === 0 && !p.alwaysShow) continue;
        const label = (p.label || '').trim();
        out.push(label ? `${n} ${label}` : `${n}`);
    }
    return out.join(' · ');
}

/**
 * Attach a hover tooltip to a top-bar actor. Returns {detach, refresh}.
 *
 * Pure data-flow: reads tooltip text from `getText()` on each hover so
 * the caller can keep mutating its model without manually pushing
 * updates here. Floats a small St.Label in the supplied uiGroup
 * (typically Main.layoutManager.uiGroup) under the target actor.
 *
 * GJS-only — pass already-loaded St, Clutter and the uiGroup actor.
 */
export function attachHoverTooltip({St, Clutter, uiGroup, target, getText}) {
    if (!St || !Clutter || !uiGroup || !target) return {detach() {}};
    let tip = null;

    const _hide = () => {
        if (tip) {
            try { tip.destroy(); } catch (_e) {}
            tip = null;
        }
    };

    const _spawn = () => {
        _hide();
        const text = (typeof getText === 'function' ? getText() : '') || '';
        if (!text) return;
        tip = new St.Label({
            text,
            style:
                'background-color: rgba(0, 0, 0, 0.85);' +
                ' color: white; padding: 4px 8px;' +
                ' border-radius: 6px; font-size: 11px;',
        });
        uiGroup.add_child(tip);
        const [x, y] = target.get_transformed_position();
        const w = target.get_width();
        const h = target.get_height();
        const tw = tip.get_width() || 100;
        let nx = Math.round(x + w / 2 - tw / 2);
        if (nx < 4) nx = 4;
        tip.set_position(nx, Math.round(y + h + 4));
    };

    const eEnter = target.connect('enter-event', () => {
        _spawn();
        return Clutter.EVENT_PROPAGATE;
    });
    const eLeave = target.connect('leave-event', () => {
        _hide();
        return Clutter.EVENT_PROPAGATE;
    });
    const eDestroy = target.connect('destroy', _hide);

    return {
        detach() {
            try { target.disconnect(eEnter); } catch (_e) {}
            try { target.disconnect(eLeave); } catch (_e) {}
            try { target.disconnect(eDestroy); } catch (_e) {}
            _hide();
        },
        refresh() { if (tip) _spawn(); },
    };
}
