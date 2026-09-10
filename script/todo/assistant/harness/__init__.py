#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les harnais d'agent : ce qui est mesuré, et ce qui n'est pas inventé.

Un agent n'est pas un serveur de modèle. Il s'adresse par identifiant de
session et non par port, il tient sa propre histoire côté processus, et il
n'annonce aucune capacité — là où un serveur répond `/v1/models` à qui frappe.
Les deux ne partagent donc ni la reconnaissance, ni l'appariement, ni la
conversation, et les mêler dans une seule liste numérotée ferait partager les
mêmes chiffres à deux modèles mentaux.

Deux règles gouvernent tout ce paquet.

**Un harnais absent est NOMMÉ, jamais omis.** Le menu le montre, grisé, avec
ce qui manque — le binaire, son répertoire de configuration. Le faire
disparaître de la liste ne dirait pas à l'utilisateur qu'il existe et qu'un
`install` suffirait ; une liste qui ne montre que ce qui marche cache
précisément l'information qui sert.

**Aucun adaptateur non mesuré n'entre.** Un adaptateur écrit d'après une
documentation est faux par endroits sans que rien ne le dise, et un menu qui
propose une action qui échoue est pire qu'un menu qui l'annonce indisponible.
`verifie` est donc une DONNÉE de chaque harnais, mise à vrai le jour où
quelqu'un a lancé le vrai logiciel et lu sa sortie — pas une supposition que
le code tire de la présence du binaire.

Les deux règles se rejoignent sur un point : la présence du binaire et la
justesse de l'adaptateur sont deux questions séparées, et le menu doit dire
laquelle des deux manque.
"""
