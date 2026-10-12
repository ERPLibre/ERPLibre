let _gettext = (s) => s;

export function setGettext(fn) {
    _gettext = typeof fn === 'function' ? fn : (s) => s;
}

export function _(s) { return _gettext(s); }

export function _identity(s) { return s; }
