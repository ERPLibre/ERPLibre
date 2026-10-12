/**
 * Registry of indicator descriptors. Decouples instantiation from
 * extension.js so adding a button = one register() call.
 */
export class IndicatorRegistry {
    constructor() {
        this._entries = new Map();
        this._order = [];
    }

    register({id, ctor, displayName, defaultEnabled = true}) {
        if (this._entries.has(id)) {
            throw new Error(`Indicator id '${id}' already registered`);
        }
        if (typeof ctor !== 'function') {
            throw new Error(`Indicator '${id}' ctor must be a function`);
        }
        this._entries.set(id, {id, ctor, displayName, defaultEnabled});
        this._order.push(id);
    }

    get(id) {
        return this._entries.get(id);
    }

    list() {
        return this._order.map(id => this._entries.get(id));
    }

    /**
     * Apply user-configured order, ignoring unknown ids, then append
     * registered ids that are not in the user list (for forward-compat).
     */
    orderedIds(userOrder) {
        const known = new Set(this._entries.keys());
        const result = [];
        const seen = new Set();
        for (const id of (userOrder || [])) {
            if (known.has(id) && !seen.has(id)) {
                result.push(id);
                seen.add(id);
            }
        }
        for (const id of this._order) {
            if (!seen.has(id)) result.push(id);
        }
        return result;
    }
}
