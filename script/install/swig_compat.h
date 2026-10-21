/*
 * © 2026 TechnoLibre (http://www.technolibre.ca)
 * License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
 *
 * Alias Python 2 que SWIG a retiré en 4.3 de son code généré, et que le
 * typemap CK_RV de pykcs11 emploie encore. Inclus de force dans chaque
 * compilation de « poetry install » par CPPFLAGS="-include <ce fichier>".
 *
 * Un fichier et non un « -D » : la forme fonction du -D porte des parenthèses,
 * que le shell d'un Makefile autotools reçoit sans guillemets — libsodium,
 * compilé par pynacl là où PyPI n'a pas de roue, s'y arrête sur « syntax error
 * near unexpected token `(' ». Un chemin n'en porte aucune.
 *
 * Le corps est celui que SWIG 4.2 écrivait, token pour token : un wrapper qui
 * le redéfinit encore ne lève aucun avertissement de redéfinition.
 */
#ifndef PyInt_FromLong
#define PyInt_FromLong(x) PyLong_FromLong(x)
#endif
