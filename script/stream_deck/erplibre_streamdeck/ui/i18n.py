# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Translation of the few deck labels short enough to fit a key."""

import os


# Lookup table for the few deck labels short enough to translate
# without overflowing a 72×72 pixel button. Most labels stay in their
# universal English/abbreviation form (TILE, OK, REC, STOP, BT, FOCUS,
# A11Y, etc.) since translating them would either lose recognition
# (TILE → TUILE) or no longer fit the rendered glyph budget.
LANG = os.environ.get('LANG', 'en').lower()[:2]
LABELS = {
    'fr': {
        # Navigation / actions
        'BACK':       'RETOUR',
        'QUIT':       'QUITTER',
        'KILL':       'TUER',
        'CANCEL':     'ANNULER',
        'CLEAR':      'EFFACER',
        'DELETE':     'SUPPR',
        'NEW':        'NOUV',
        # Timer page
        'RFSH':       'ACTUAL',
        'RESET\nALL': 'RAZ\nTOUT',
        'RESET':      'RAZ',
        'ALL?':       'TOUT?',
        'RESET\nALL?': 'RAZ\nTOUT?',
        'EXPT\nCSV':  'EXP\nCSV',
        'CLEAN\nDASH': 'NETTOY\nTABL',
        'NO\nTIMERS': 'AUCUN\nMINUT',
        # Idle screen titles
        'TILE':       'TUILE',
        'TIMER':      'MINUT',
        'SOUND':      'SON',
        'LAYOUT':     'DISPO',
        'TRANSL':     'TRADUC',
        # Sound / mic / bluetooth labels
        'MIC\nN/A':   'MIC\nN/D',
        'MIC\nON':    'MIC\nON',
        'MIC\nOFF':   'MIC\nMUET',
        'MIC\nMUTE':  'MIC\nMUET',
        'OUT\nMUTE':  'SORT\nMUET',
        'BT\nN/A':    'BT\nN/D',
        # Layout slot prompts
        'SAVE':       'ENREG',
        'EMPTY':      'VIDE',
        # Errors
        'NO\nEXT':    'EXT\nABS',
        'DECK\nTOO\nSMALL': 'DECK\nTROP\nPETIT',
        # Project shortcuts
        'TODO':       'TODO',
        'ENTER\n↵':   'ENTRER\n↵',
        'FORGET':     'OUBLI',
        # Claude session page
        'FOCUS':      'FOCUS',
        'ACCEPT\n↵':  'OK\n↵',
        'SET\nWIN':   'DEF\nFEN',
        # MPV session page
        'PLAY\nPAUSE': 'LECT\nPAUSE',
        'VOL\n−':     'VOL\n−',
        'VOL\n+':     'VOL\n+',
    },
}


def t(label):
    """Translate `label` to the active deck language. Falls back to
    the original English label when no translation is recorded."""
    return LABELS.get(LANG, {}).get(label, label)
