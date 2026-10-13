/**
 * Shell and Mutter API differences across the GNOME versions that
 * metadata.json declares. Each helper takes the gi modules, or the live
 * object it works on, as arguments: the file stays Node-importable and
 * the unit tests drive it with plain fakes.
 *
 * Every branch tests for the newer API first, so a version that has it
 * never reaches the older call.
 */

/**
 * Construction properties that make an St.BoxLayout vertical.
 *
 * St.BoxLayout carries `orientation` from GNOME 48 on, and GNOME 51
 * drops `vertical`: a box built with `vertical` there throws "No property
 * vertical on StBoxLayout" and takes the whole indicator down with it.
 * A box is horizontal by default on every version, so a horizontal box
 * needs no property at all.
 */
export function verticalBoxProps(St, Clutter) {
    if ('orientation' in St.BoxLayout.prototype)
        return {orientation: Clutter.Orientation.VERTICAL};
    return {vertical: true};
}

/** Turn an existing St.BoxLayout vertical (true) or horizontal (false). */
export function setBoxVertical(St, Clutter, box, vertical) {
    if ('orientation' in St.BoxLayout.prototype) {
        box.orientation = vertical
            ? Clutter.Orientation.VERTICAL
            : Clutter.Orientation.HORIZONTAL;
    } else {
        box.vertical = vertical;
    }
}

/**
 * Current Meta.MaximizeFlags of a window. Mutter 49 replaces
 * get_maximized() with get_maximize_flags(); the value has the same
 * meaning on both.
 */
export function windowMaximizeFlags(win) {
    if (typeof win.get_maximize_flags === 'function')
        return win.get_maximize_flags();
    return win.get_maximized();
}

/**
 * Clear a window's maximized state in both directions. The API that has
 * get_maximize_flags() takes no argument; the older one needs the flags.
 */
export function unmaximizeWindow(win, Meta) {
    if (typeof win.get_maximize_flags === 'function')
        win.unmaximize();
    else
        win.unmaximize(Meta.MaximizeFlags.BOTH);
}

/**
 * Maximize a window in the directions `flags` names; 0 does nothing.
 * On the API without a flags argument, maximize() covers both
 * directions and set_maximize_flags() a single one.
 */
export function maximizeWindow(win, Meta, flags) {
    if (!flags) return;
    if (typeof win.get_maximize_flags !== 'function')
        win.maximize(flags);
    else if (flags === Meta.MaximizeFlags.BOTH)
        win.maximize();
    else
        win.set_maximize_flags(flags);
}

/**
 * Default input seat. The backend is reached through the stage's
 * Clutter.Context; Clutter.get_default_backend(), the older path, is
 * gone from GNOME 51.
 */
export function defaultSeat(Clutter, stage) {
    const backend = typeof stage?.get_context === 'function'
        ? stage.get_context().get_backend()
        : Clutter.get_default_backend();
    return backend.get_default_seat();
}
