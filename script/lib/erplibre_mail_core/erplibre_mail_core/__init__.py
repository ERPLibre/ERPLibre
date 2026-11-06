# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le noyau des règles de courriel d'ERPLibre : décrire une règle, filtrer
un message, décider d'un envoi automatique, rendre la réponse et le
rapport de statistiques, construire les messages SMTP, lire les réponses
IMAP et revendiquer un message.

Le paquet n'a ni interface, ni stockage, ni fichier de configuration : il
n'importe que la bibliothèque standard (`markdown_it`, facultatif, à
l'usage). La langue et le fuseau sont des paramètres de l'appelant
(`i18n`, `zone`). Les sous-modules s'importent un à un ; ce fichier n'en
charge aucun.
"""

__version__ = "0.1.0"
